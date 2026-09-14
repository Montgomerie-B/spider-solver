# f3_tactical_bridge_v0_79

Verdict: `F3_BRIDGE_REACHES_F4`

Per-suit tactical cash-out from the exact v0.78 g141 F3 produced F4 at
**g=163** (hearts, Δg=22, first hit 10.2 s) and F5 at **g=174** (second
diamonds, with an auto-cascade). Frozen stock-empty continuation then
proof-pruned every descendant: all have `g+h ≥ 192 > 186`.

Not a whole-game opening campaign. Canonical 172 was not a search input.
Incumbent remains 187.

## Hypothesis

Global endgame lanes found cheap F3 from g128 but not F4. A bounded
fixed-target foundation planner on each materially-ready remaining suit
should cross the F3→F4 valley, then return F4 states to the frozen solver.

## Root reconstruction

```text
opening → 187 rows=1 g123 → v0.71 five tactical actions → F2 g128
→ SD5 g129 → stock-empty search → exact v0.78 g141 digest
```

| | g | F | fd | h/f | legal | digest |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| post-SD5 | 129 | 2 | 2 | 43/172 | 5 | v0.76/v0.78 |
| recovered F3 | **141** | 3 | 2 | 33/174 | 41 | **equals v0.78** |

Recovery: 91.7 s, unique 11,027, abort on digest+g=141 (first seen path was
g=143; search continued to the recorded cheapest). Replay from opening ok.
Founded suits: **c, d, s**. Ready remaining: **s, h, d, c**. Rank-1: **h**.

## Per-suit tactical probes (75 s, ceiling 186, no Deal)

| suit | already F | found | cheapest g | Δg | first s | terminals | unique | exp |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **h** | 0 | **yes** | **163** | 22 | **10.2** | 1,109 | 16,765 | 2,851 |
| c | 1 | no | — | — | — | 0 | 20,756 | 4,043 |
| **d** | 1 | **yes** | **174** | 33 | **10.0** | 541 | 22,594 | 2,849 |
| s | 1 | no | — | — | — | 0 | 20,511 | 2,288 |

Hearts (never founded) is the cheap F4. Second diamonds also cash out, and
the completing move can auto-cascade to F5 (fd 2→1). Second clubs/spades
did not finish in 75 s.

v0.74 focused 187-root F4 = **175**. Hearts F4 at **163** is 12 MW cheaper
in path cost.

## F4/F5 portfolio (16 unique)

Cheapest hearts F4: g=163, h=**29**, f=**192**, legal=11, fd=2.

Cheapest diamond cascade F5: g=174, h=**21**, f=**194**, legal=7, fd=1.

All 16 admitted roots have `f ≥ 192`. v0.74's F4 was g=175 / h=13 / f=188 —
also above 186, but with much lower h.

## Frozen continuation

503 s requested. Actual 0.07 s. unique=16, expanded=**0**,
proof-prunes=**16** (8 at F4, 8 at F5). HORIZON 0.

Every root failed `g+h > 186` before a child was generated. The bridge
found real F4/F5 states; the frozen assembly bound declares them unusable
as 186-search roots.

Wall 396 s (recover 92 + probes 305 + continuation 0). Remaining envelope
was not useful once the F4 portfolio was proof-dead.

## Comparison

| | v0.74 187-root | v0.78 g128 | v0.79 from g141 |
| --- | ---: | ---: | ---: |
| cheapest F3 | 156 | **141** | 141 (recovered) |
| cheapest F4 | 175 / h13 / f188 | none in 900 s | **163 / h29 / f192** |
| F5 | 180 / h9 / f189 | none | **174 / h21 / f194** |
| F6–F8 / terminal | 183…187 | none | none (pruned) |

The g128 line is still the better F3 factory and now a working F4 factory
on hearts. It is a **worse assembly** F4: +16 h versus the 187-root F4.

## Tests

Focused: g141 digest contract, ready-suit inspection, reconstruction,
tactical ceiling 191 unchanged, search ceiling 186, no canonical, no
continuation suffixes. Plus v0.71/v0.78 regressions.

## Interpretation

The F3→F4 tactical-bridge hypothesis is **true for discovery** and **false
for 186-viability**. Global lanes were the bottleneck for *finding* F4.
Fixed-target hearts cash-out finds it in 10 s. Those F4s do not reduce
assembly h enough to survive `g+h > 186`, so returning them to the frozen
endgame is a no-op. The next gap is F4 *quality* (h), not F4 existence.

## Next recommendation

Search for hearts-F4 descendants with lower assembly h from this g141
root (or a slightly later F3), not another pre-Deal heuristic and not
more wall time. Do not copy canonical 172.
