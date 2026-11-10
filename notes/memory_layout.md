# PS5 Orbis OS — WebContent Process Memory Layout

## Confirmed findings (this session)

- **V674 v5 result:** ALL 30 targets in sub-4GB + generic FreeBSD ranges crashed (SIGSEGV)
- **Conclusion:** PS5 WebContent process does NOT map code/heap in 0x0–0x2_8000_0000 range

## PS5 Orbis OS Address Space (FreeBSD 11 base)

```
0x0000_0000_0000_0000 — 0x0000_0000_0040_0000  : null guard (unmapped)
0x0000_0001_0000_0000 — 0x0000_0004_0000_0000  : heap / mmap area (libpas)
0x0000_0005_0000_0000 — 0x0000_0020_0000_0000  : WebKit .sprx load area
0x00007FFF_C000_0000 — 0x00007FFF_FFFF_FFFF    : stack (high 48-bit)
```

## Key facts

- **IsoHeap OFF, Gigacage OFF** on PS5 14.x — ArrayBuffer backing stores share the same libpas heap as JSC/WebCore C++ objects. This is what makes the AB(768) reclaim technique viable.
- **DAZ (Denormals-Are-Zero)** ON — float64 reads of pointer-shaped bit patterns return 0.0 when exponent bits indicate a denormal. Zero-hit still confirms the address is mapped.
- **ASLR entropy** on PS5 14.x for WebContent is low (estimated 8–12 bits) — slide increments in large pages
- **GPU surface exhaustion** — each `getContext('2d')` on a non-zero canvas allocates a GNM GPU surface. Keeping SPRAY_COUNT=5 avoids premature OOM dialog before V630 completes.
- **PS5 "not enough system memory" dialog** = web content process SIGSEGV, NOT actual OOM. This is the expected behavior during V674 crash-scan on unmapped addresses.

## V674 target address rationale (v6)

| Range | Rationale |
|-------|-----------|
| 0x1_0000_0000 – 0x1_C000_0000 | PS5 heap/mmap base (4–7GB) |
| 0x2_0000_0000 – 0x4_0000_0000 | Extended mmap area (8–16GB) |
| 0x5_0000_0000 – 0x20_0000_0000 | WebKit .sprx load range (20–128GB) |
| 0x7FFF_xxxx_xxxx | Stack (high 48-bit, wider offsets) |
| 0x800_0000 – 0xC000_0000 | Fallback sub-4GB in case PIE slide is small |

## v5 → v6 bug fix

V674 was using `c2.width=0, c2.height=0` to avoid GPU surface allocation. However a 0×0 canvas may not allocate a full 768B `CanvasRenderingContext2D` struct — the WebKit implementation may short-circuit or return a stub object. With nothing proper freed, the AB(768) spray reclaims random heap memory instead of the target object, and the forge writes to unrelated memory. Fixed in v6: use `width=1, height=1` and release GPU surfaces from the V573 spray before triggering V674.

## Next steps after V674 HIT

1. **V701** — Forge `lineDash` Vector (`m_lineDash` at offset +168) in the aliased AB for arbitrary R/W primitive
2. **V744** — `setLineDash` arbitrary write — write 8 bytes to any mapped address
3. **V788** — Type confusion via forged JSObject vtable
4. **V821** — vtable hijack + ROP chain to `system()` or kernel exploit entry
