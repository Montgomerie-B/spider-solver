# Simple Progressive Search v0.19: FD13 Plateau Alternative-FD12 Exit Audit

## 1. Verdict

`FD13_PLATEAU_STATE_EXPLOSION` — resource limits bound the fd13 plateau before exhaustion.

FD13 root proven dead to fd10: **False** — the fd13 plateau was not exhausted, so
alternative fd12 exits beyond the observed envelope are not ruled out.

What *was* resolved:

- The v0.12 fd12 checkpoint's complete future is **41,472** symmetry classes
  (20,736 fd12 + 1,728 known-dead fd11 + 19,008 other fd11), exhausted, no fd10.
- In the time-bounded fd13 plateau, **18** fd12 exits appeared: **15** land in that
  dead fd12 plateau; **3** are new (earliest depth 10, no empty, run 7).
- Those 3 new fd12 sources' shared continuation **exhausts** at 89,856 classes,
  min fd 11, no empty, no foundation, and never intersects the 41,472-class dead
  cache (`known_dead_prunes=0`). They are experimentally dead.
- The fd13 plateau itself was still growing at the 1800 s cap: 2,352,714 unique
  fd13 states through generated depth 11.

Production `pack_state` / `solve_progressive` are unchanged. Post-stock column symmetry
and the known-dead fd12 cache are research-only exact tools, not production features.

## 2. FD13 root

- replay_ok=True path=102 cost=102 fd=13 stock=0 fnd=0 empties=[2] run=6
- ordered digest: `53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a29000000121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- symmetry digest: `5350533101000000000000022d2c00080d0c262139383706000812272a0524133201000b1716352b14092534332201000d3d3c3b3a39383726252423222100121413121d071d1c1b1a19181716153433323104093a2c360835042302310b0d1c3b041118360a2a280706050403020911033d3c0b0a290827050515191b11282d0c2b1a29`
- stock0 A+B+C complete: True

## 3. Phase 0 — KNOWN_DEAD_FROM_FD12

- unique=41472 exhausted=True min_fd=11 fnd=0 empty=0 fd12_plateau=20736 expected_plateau=20736 elapsed=75.079289900008
- this is 20,736 fd12 + 1,728 + 19,008 fd11 classes, matching the v0.18 split graphs

## 4. Phase 1 — fd13 plateau

- exhausted=False stop=time limit unique=2352714 generated=8294080 dups=5941349 max_depth=11 elapsed=1800.4535942000075 rss=1428.4140625
- empty0=2188588 empty1=164126 empty_ge2=0 max_empties=1 max_run=9 max_adj=40 max_blocks=8
- fd13->fd12 edges=18 classes=18 known_dead=15 new=3 earliest_new_depth=10

## 5. Phase 2 — new fd12 continuation

- sources=3 unique=89856 stop=frontier empty min_fd=11 fnd=0 empty=0 known_dead_prunes=0 elapsed=149.73339169999235 rss=1429.28515625
- fd10=False foundation=False
- the three new fd12 futures are a closed experimentally-dead component, disjoint from KNOWN_DEAD_FROM_FD12

## 6. Exactly one next recommendation

Do not raise limits here. Report the bounded fd13 plateau and stop.

## Integrity

Verdict FD13_PLATEAU_STATE_EXPLOSION. dead_from_fd12=41472 plateau_subset=20736 fd13_unique=2352714 exhausted=False exits=18 known_dead=15 new=3 fd10=False foundation=False proven_dead=False.

Base SHA `b9927e50596996903aed3e0acd148fe6f84676ab`. Deal `deals/4925153.txt`.
Production pack_state and solve_progressive are unchanged.
An fd14 backtrack was not started. Heuristics and slack were not added.

