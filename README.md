# PS5 14.20 Jailbreak Research

> CVE-2026-43720 — `HTMLCanvasElement::getContext()` reentrant UAF on 768B Canvas2D context

**Status:** V630 PASS ✅ | V674 crash-scan in progress 🔄

---

## Firmware Target

- **PS5 firmware:** 14.20
- **WebKit build:** WebKit-1400 (Safari 17.0 equivalent)
- **JIT:** Disabled (LLInt only)
- **IsoHeap:** OFF
- **Gigacage:** OFF
- **libpas:** Out-of-band bitmap — AB backing stores share heap with JSC/WebCore objects

> ⚠️ DO NOT UPDATE past 14.20 — firmware 14.22 patches the FontFace UAF chain.
> Keep auto-updates OFF: Settings → System → System Software → System Software Update and Settings

---

## CVE-2026-43720 — Root Cause

`HTMLCanvasElement::getContext()` reads dictionary options via a JS getter **before** committing the new context.

1. Outer call: `canvas.getContext('bitmaprenderer', opts)` starts
2. `opts.alpha` getter fires → calls `canvas.getContext('2d')` re-entrantly → allocates 768B `CanvasRenderingContext2D` C++ object, returns JS wrapper
3. Outer call resumes → replaces canvas context with `ImageBitmapRenderingContext` → **frees the 768B Canvas2D object**
4. JS wrapper (`innerCtx`) now holds a **dangling pointer** to freed 768B memory

---

## Exploit Chain

| Stage | Description | Status |
|-------|-------------|--------|
| V573  | Same-type Canvas2D reclaim spray (5× 1×1 no-DOM) | ✅ PASS slot=2 |
| V630  | Bidirectional alias R/W confirmed | ✅ PASS |
| V674  | AB(768) forge crash-scan for mapped address | 🔄 In progress |
| V701  | Forge lineDash Vector for arb R/W | ⏳ Pending |
| V744  | setLineDash arb write | ⏳ Pending |
| V788  | Type confusion | ⏳ Pending |
| V821  | vtable hijack + ROP chain | ⏳ Pending |

---

## V573 — UAF + Same-Type Reclaim

- Spray 5× `Canvas2D` contexts (1×1, no DOM attachment)
- Write sentinel `57005.0` (0xDEAD as float) via stale `innerCtx.lineWidth`
- Scan spray array for sentinel → confirms which slot reclaimed freed 768B
- **Result this session:** slot=2 confirmed

## V630 — Bidirectional Alias R/W

After alias confirmed:
```
aliasCtx.lineWidth = 2.718  →  innerCtx.lineWidth === 2.718  ✓
innerCtx.globalAlpha = 0.42  →  aliasCtx.globalAlpha === 0.42  ✓
innerCtx.miterLimit = 99     →  aliasCtx.miterLimit === 99     ✓
```
Full R/W into the freed 768B slot confirmed.

## V674 — AB(768) Forge Crash-Scan

Forge `m_stateStack.m_buffer` in a recycled ArrayBuffer to point at target address. `innerCtx2.lineWidth` read dereferences `TARGET+48`. If unmapped → SIGSEGV → PS5 shows "not enough system memory" dialog (PS5's generic web content process crash dialog, NOT actual OOM).

**Key offsets in Canvas2D 768B struct:**
```
+112: m_stateStack.m_buffer lo32
+116: m_stateStack.m_buffer hi32
+120: m_stateStack.m_capacity (set to 1)
+124: m_stateStack.m_size    (set to 1) → reads state[0]+48 = TARGET+48
```

**localStorage counter:** `v674_attempt` pre-incremented before probe read — survives crash, auto-advances across page reloads.

**DAZ ON:** float64 reads of pointer values return 0 for denormals. Zero-hit still confirms address is mapped.

**v5 bug fixed in v6:** V674 canvas must be 1×1 (not 0×0) to ensure full 768B context object is allocated and freed properly.

**PS5 Orbis address layout (v6 target list):** All sub-4GB addresses crashed in v5. PS5 WebContent process maps in 4GB–128GB range.

---

## PS5 Environment

- PS5 IP: `192.168.1.177`
- PC IP: `192.168.1.200`
- HTTP log port: `8080`
- Server: `server/https_server.py` (HTTP:8080 + HTTPS:443 dual)
- Serve page: `exploit/fontface_serve.html` → loads `exploit/canvas_uaf.js`

---

## Files

```
/
├── README.md
├── exploit/
│   ├── canvas_uaf.js        ← main exploit script (v6 current)
│   └── fontface_serve.html  ← PS5 browser delivery page
├── server/
│   └── https_server.py      ← dual HTTP+HTTPS log server
└── notes/
    └── memory_layout.md     ← PS5 Orbis address space notes
```
