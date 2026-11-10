# PS5 14.20 Jailbreak Research

> WebKit browser exploit research for PS5 firmware 14.20  
> Primary vector: **CVE-2026-43720** — `HTMLCanvasElement::getContext()` reentrant UAF on 768B Canvas2D context

**Chain status:** V573 ✅ → V630 ✅ → V674 🔄 → V701 ⏳ → V744 ⏳ → V788 ⏳ → V821 ⏳

---

## Firmware Warning

> ⚠️ **DO NOT UPDATE past 14.20** — firmware 14.22 patches the Canvas `getContext()` UAF chain.  
> Keep auto-updates **OFF**: Settings → System → System Software → System Software Update and Settings

---

## Target Environment

| Property | Value |
|----------|-------|
| PS5 firmware | 14.20 |
| WebKit build | WebKit-1400 |
| UserAgent | Safari 17.0 (PS5) |
| JIT | **Disabled** (LLInt only — no JIT spraying) |
| IsoHeap | **OFF** |
| Gigacage | **OFF** |
| Heap allocator | libpas (out-of-band bitmap) |
| AB backing stores | **Share libpas heap with JSC/WebCore objects** |
| DAZ | **ON** (Denormals-Are-Zero — float reads of pointer bits return 0) |

---

## Research Path

### Phase 1 — FontFace UAF (dead end on 14.20)

Initial research targeted the **FontFace API UAF** that was well-documented in PS5 firmware 14.10 research. The technique exploits a race condition in `FontFace::load()` where the promise callback can fire while the underlying font data buffer is being reallocated, leaving a stale JS wrapper pointing at freed memory.

The plan was:
1. Trigger FontFace UAF to get a dangling `FontFace` JS object
2. Spray `ArrayBuffer(size)` to reclaim the freed slot
3. Use the stale wrapper to read/write into the reclaimed AB backing store
4. Build an arbitrary R/W primitive from there

**Why it failed on 14.20:** Sony backported a targeted patch into 14.20 that adds a validity check on the FontFace internal state pointer before any JS-visible property access. The check compares a generation counter embedded in the object header — if the counter doesn't match the canvas document's current generation, the access is silently dropped. The patch does not fix the underlying race; it just prevents exploitation of the resulting dangling pointer. We confirmed the UAF still fires (the freed allocation is visible in allocator telemetry) but the JS wrapper becomes a no-op immediately after the free.

This path is fully viable on **14.10 and below**. On 14.20 it is patched.

---

### Phase 2 — Canvas `getContext()` Reentrant UAF (CVE-2026-43720)

While auditing WebKit's canvas implementation looking for a FontFace alternative, we identified a reentrant flaw in `HTMLCanvasElement::getContext()`.

#### Root cause

`HTMLCanvasElement::getContext(type, options)` reads the `options` dictionary by invoking JS getters on it **before** it commits the new context type to the canvas element. The sequence:

```
getContext('bitmaprenderer', opts)
  → reads opts.alpha via JS getter        ← re-entrant window
      → opts.alpha getter calls canvas.getContext('2d')
          → allocates 768B CanvasRenderingContext2D (C++ heap)
          → canvas.m_context = new 2D context
          → returns JS wrapper (innerCtx)
      ← getter returns true
  → outer call resumes
  → canvas.m_context = new ImageBitmapRenderingContext  ← REPLACES 2D context
  → old CanvasRenderingContext2D is FREED (768B back to libpas)
  → returns bmrCtx
```

`innerCtx` (the JS wrapper returned from inside the getter) now points to a **freed 768B object**. The JS garbage collector does not know the C++ object is gone — the wrapper holds a raw pointer with no weak-ref or handle table indirection.

**CVE-2026-43720** was assigned for this issue. It affects WebKit-1400 on PS5 14.20. Sony's patch in 14.22 adds a context-change guard that invalidates re-entrant `getContext()` calls while an outer `getContext()` is in progress.

#### Why 768B matters

libpas on PS5 14.x is configured with **IsoHeap OFF** and **Gigacage OFF**. This means:
- JS `ArrayBuffer` backing stores live in the **same libpas size class** as WebCore C++ objects of the same size
- A 768B ArrayBuffer allocation competes directly with a freed 768B `CanvasRenderingContext2D`
- With the right spray timing, an `ArrayBuffer(768)` reclaims the exact freed slot → JS holds both a typed array view into the memory AND a dangling Canvas2D context wrapper pointing at the same bytes

---

## Exploit Chain

### V573 — Same-Type Reclaim + Alias Detection

After triggering the UAF, we spray **5× Canvas2D contexts** (1×1 canvas, no DOM attachment) to maximize the chance one of them is allocated into the freed 768B slot.

Detection uses a float sentinel: write `57005.0` (the float representation of `0xDEAD`) to `innerCtx.lineWidth`. Then scan `sprayCtxs[i].lineWidth` — the slot that reads back `57005.0` is the alias.

**Result:** slot=2 confirmed this session (slot varies per run — libpas allocation order is non-deterministic across page loads).

**Why only 5?** Each `getContext('2d')` on a non-zero canvas allocates a **GNM GPU surface** on PS5. Too many simultaneous GPU surfaces exhaust the GNM allocator and trigger the PS5's "not enough system memory" dialog before the exploit reaches V630. 5 contexts is enough for reliable reclaim while staying within GNM budget.

### V630 — Bidirectional R/W Confirm

With `aliasCtx` (spray slot that aliased `innerCtx`) confirmed, we verify full bidirectional R/W by writing through both directions:

```
aliasCtx.lineWidth  = 2.718  →  innerCtx.lineWidth  === 2.718  ✓
innerCtx.globalAlpha = 0.42  →  aliasCtx.globalAlpha === 0.42  ✓
innerCtx.miterLimit  = 99    →  aliasCtx.miterLimit  === 99    ✓
```

This confirms we have a stable read/write primitive into the freed 768B Canvas2D context struct via the Canvas2D property API. All writes go through WebKit's float-based property setters — no raw memory writes yet, but the struct fields map to known offsets.

**After V630:** release all V573 GPU surfaces (`sprayCtxs = null; sprayCanvases = null`) and schedule V674 with a 300ms GC delay to let the PS5 GPU surface allocator recover.

### V674 — AB(768) Forge Crash-Scan

To build a raw arbitrary R/W primitive, we need a **second UAF** where an `ArrayBuffer(768)` reclaims the freed slot instead of a Canvas2D context. This gives us raw byte access to the same memory the dangling canvas wrapper reads.

**Technique (from v650 reference):**

1. Trigger a fresh UAF (second canvas, 1×1) → free another 768B slot
2. Spray 200× `ArrayBuffer(768)` → one reclaims the freed slot
3. Forge `m_stateStack.m_buffer` at AB offset +112 to point at `TARGET_ADDR`
4. Set `m_capacity=1`, `m_size=1` at offsets +120/+124
5. Read `innerCtx2.lineWidth` → WebKit reads `m_stateStack.m_buffer[0].lineWidth` = `*(TARGET_ADDR + 48)`
6. If `TARGET_ADDR` is **unmapped** → SIGSEGV → PS5 web content process crashes → PS5 shows "not enough system memory" dialog → page reloads → `localStorage` counter auto-advances → next target probed
7. If `TARGET_ADDR` is **mapped** → read survives → we have a leaked value from that address

**Key offsets in Canvas2D 768B struct:**
```
+112  m_stateStack.m_buffer  (ptr lo32)
+116  m_stateStack.m_buffer  (ptr hi32)
+120  m_stateStack.m_capacity
+124  m_stateStack.m_size
```

With `m_size=1`, `lineWidth` reads `m_buffer[0].lineWidth` = `*(m_buffer + 0*sizeof(State) + 48)` = `*(TARGET + 48)`.

**DAZ caveat:** PS5 has Denormals-Are-Zero enabled. If the 8 bytes at `TARGET+48` happen to encode a denormal float64, the read returns `0.0`. A zero result still confirms the address is **mapped** (unmapped → crash, not zero). We log both ZERO-HIT and NONZERO-HIT separately.

**v5 bug (fixed in v6):** The V674 canvas was initially created with `width=0, height=0` to avoid GNM GPU surface allocation. However a 0×0 canvas may not allocate a full 768B `CanvasRenderingContext2D` — WebKit may short-circuit and return a lightweight stub. With nothing proper freed, the AB spray reclaims unrelated heap and the forge has no effect. Fixed: use `width=1, height=1` and rely on the 300ms GC delay (which already freed the V573 GPU surfaces) to stay within GNM budget.

**v5 address list bug (fixed in v6):** The v5 target list covered `0x400000` through `0x2_8000_0000` — standard FreeBSD/Linux process ranges. ALL 30 probes SIGSEGV'd. PS5 Orbis OS maps the WebContent process entirely **above 4GB**. v6 target list starts at `0x1_0000_0000` (4GB) and covers the heap/mmap/sprx ranges up to `0x20_0000_0000` (128GB).

**Current status:** v6 running. Awaiting first HIT in the 4GB–128GB range.

### V701 — lineDash Vector Forge (arb R/W) ⏳

After V674 provides a confirmed mapped address, forge the `m_lineDash` Vector at offset +168 in the aliased Canvas2D struct. `m_lineDash` is a `Vector<float>` with layout `{data*, size, capacity}`. By writing a controlled `data*` and setting `size=N`, `setLineDash([v0,v1,...])` becomes an arbitrary write of float values to any mapped address.

### V744 — Arbitrary Write Primitive ⏳

Use the forged lineDash vector to write shellcode or a controlled vtable pointer to a known writable location discovered via V674 scan.

### V788 — Type Confusion ⏳

Forge a JSObject header in the writable region to confuse the JIT (or LLInt) type checker. On PS5 with JIT disabled, this targets the LLInt dispatch table or a C++ vtable.

### V821 — vtable Hijack + ROP ⏳

Overwrite a vtable pointer on a live C++ object (canvas, document, or window) with a ROP gadget chain. Target: `system()` call or kernel exploit entry point for privilege escalation.

---

## "Not Enough System Memory" Dialog

This is **not an actual out-of-memory error**. On PS5, the browser's web content process runs in a sandboxed subprocess. When that process crashes (SIGSEGV, SIGBUS, or any unhandled signal), the PS5 OS displays a generic "There is not enough free system memory" dialog rather than a process-crash notification. During V674 crash-scan, every probe of an unmapped address causes a SIGSEGV in the web content process, which surfaces as this dialog. Clicking **OK** restores the browser, reloads the page, and the `localStorage` counter advances to the next target. This is **expected behavior** during the scan.

---

## Setup

**Server** (run on PC before opening PS5 browser):
```bash
cd server/
# Generate self-signed cert if you don't have one:
openssl req -x509 -newkey rsa:2048 -keyout server.key -out server.crt -days 365 -nodes
python3 https_server.py
```

**PS5 browser:** navigate to `https://<YOUR_PC_IP>/canvas_serve.html`

Logs appear in `server/ps5_results/http_log.txt` and in stdout.

**Reset V674 scan:** click `[reset v674 counter]` on the page footer, then reload.

---

## Files

```
/
├── README.md
├── exploit/
│   ├── canvas_uaf.js       ← main exploit (v6 current)
│   └── canvas_serve.html   ← PS5 browser delivery page
├── server/
│   └── https_server.py     ← dual HTTP:8080 + HTTPS:443 log server
└── notes/
    └── memory_layout.md    ← PS5 Orbis address space research notes
```
