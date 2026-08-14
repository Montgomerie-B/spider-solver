# Workspace obstruction audit (one-off)

**On:** `dev/sprint1m-workspace-tactics`  
**Not a new strategy layer.** No epoch-planner change. No extra dealing.

## Classification: **C MIXED**

| State | Cheap workspace (≤8) | Deep result | Why |
|---|---|---|---|
| Machine pre-D1 (g=12, fd=32) | no | **EXHAUSTED ≤20** (4608 quotient states) | **B** — no fully-open column; proved none ≤20 |
| Machine post-D1 (g=23, fd=28) | yes, **cost 4** | FOUND 631 nodes | **A** vs 1M caps — 1M timed out at 578 nodes |
| Machine post-D2 best-ss (g=14, fd=32) | no (exhausted ≤12) | FOUND **cost 16** | **B** for cheap; expensive route exists |
| Human pre-D1 (g=50, fd=12) | **cost 2** | 45 nodes | 6 fully-open columns; dest prepared in 1 move |
| Human post-D2 (g=89, fd=8) | **cost 2** | 14 nodes | 8 fully-open columns |

Human vs machine in one sentence: the human has **fully-open piles** that can be parked once a rank+1 dest is created; the strong machine lines still have **face-down in every column**, so an empty requires reveal-then-peel (or cost 16+).

`workspace_potential` (revised): reward fully-open *non-king* columns. Separates human (open=6–8) from machine hard states (open=0). Not integrated into plan_search.
