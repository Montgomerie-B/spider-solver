# Simple Progressive Search v0.22: FU5 Target-Conversion Audit

## 1. Verdict

`FU5_LOCAL_NO_CLEARANCE_PROGRESS` — no target FU below 5 and no reveal inside the completed shallow envelope.

The FU5 checkpoint is a **closed 108-state fd13 bubble**. Fair BFS exhausts it at depth 6:
never an empty, never FU&lt;5, never a reveal, never fd12. The remaining target face-up
stack is `c5,s4,d3,s2,c1` (bottom-to-top) with an **Ace** on top, no legal destination,
and no empty in the entire reachable graph. FU5 was a soft-metric attractor, not a
useful conversion launch point.

No new heuristic. Production identity is unchanged. Column 7 was not tested.

## 2. FU5 checkpoint

- replay_ok=True local_depth=12 total_path=114 cost=114 fd=13 empties=[] target_fu=5 blocks=5 top=1 face_up=[['c', 5], ['s', 4], ['d', 3], ['s', 2], ['c', 1]]
- ordered=`53504b310100000004053a2c36083504230231050715191b11282d3c3b3a39383700030d0c0b00121413121d071d1c1b1a19181716153433323100052d2c3b1a2900080d0c262139383706041718360a2a280706050403020911033d3c0b0a290827262524232221000812272a052413320100033d1c2b000b1716352b14092534332201`
- symmetry=`535053310100000000030d0c0b00033d1c2b00052d2c3b1a2900080d0c262139383706000812272a0524133201000b1716352b1409253433220100121413121d071d1c1b1a19181716153433323104053a2c36083504230231041718360a2a280706050403020911033d3c0b0a290827262524232221050715191b11282d3c3b3a393837`

## 3. Fair BFS from FU5

- stop=frontier empty unique=108 generated=462 dups=355 expanded=6 generated_depth=6 elapsed=0.19913130000350066 rss=21.7890625
- min_fu=5 min_blocks=5 min_fd=13
- reveal=False reveal_depth=None target_exits=0 known_dead=0 outside=0 off_target=0

| Depth | Frontier | Unique | min FU | FU5 | FU4 | FU3 | empty0 | empty1 | target exits |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 7 | 5 | 1 | 0 | 0 | 1 | 0 | 0 |
| 1 | 6 | 23 | 5 | 6 | 0 | 0 | 6 | 0 | 0 |
| 2 | 16 | 50 | 5 | 16 | 0 | 0 | 16 | 0 | 0 |
| 3 | 27 | 81 | 5 | 27 | 0 | 0 | 27 | 0 | 0 |
| 4 | 31 | 102 | 5 | 31 | 0 | 0 | 31 | 0 | 0 |
| 5 | 21 | 108 | 5 | 21 | 0 | 0 | 21 | 0 | 0 |
| 6 | 6 | 108 | 5 | 6 | 0 | 0 | 6 | 0 | 0 |

## 4. Downstream

- skipped: no OUTSIDE_KNOWN_DEAD target exit

## 5. Exactly one next recommendation

FU5 does not convert under fair shallow search. Next: stop this target-clearance line and recommend backtracking to an earlier hard-progress state. Do not add another heuristic.

## Integrity

Verdict FU5_LOCAL_NO_CLEARANCE_PROGRESS. FU5 depth=12 min_fu=5 reveal=False known=0 outside=0.

Base SHA `830b4d01a66c07974a6fe7c4941e86941d1c52e8`. Deal `deals/4925153.txt`.
No new heuristic. No column-7 arm. No production change.

