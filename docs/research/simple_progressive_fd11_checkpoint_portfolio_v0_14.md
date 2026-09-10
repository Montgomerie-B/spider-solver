# Simple Progressive Search v0.14: Minimum-Depth FD11 Checkpoint Portfolio

## 1. Verdict

`ALL_MIN_DEPTH_FD11_CHECKPOINTS_STALL` — the complete minimum-depth fd11 set has size **1**, it is the v0.13 first fd11, and it cannot reach fd10.

Greedy first-checkpoint commitment was not the failure mode. There is no equally short alternative. Completing generation of depth 9 (1,144,490 unique states) found a single canonical fd11: empties 0, run 6, 5 legal actions. Preflight without the depth-12 cut exhausts that state's A+B+C graph at 1,728 unique states / depth 13, still fd 11, still no empty, still no foundation.

Workspace is telemetry, not an objective. Production `solve_progressive` is unchanged.

## 2. Preflight — v0.13 first fd11 bubble

- true_exhaustion=True unique=1728 max_depth=13 fd10=False empty_created=False foundation=False stop=frontier empty elapsed=2.5237514000036754

## 3. Phase 1 — min-depth fd11 census

- complete=True partial=False unique=1144490 gen_depth=9 stop=max depth elapsed=651.4263961000106 rss=555.1484375
- candidates=1 empty0=1 empty1=0 empty_ge2=0
- empty identities={'()': 1}
- run distribution={'6': 1}
- legal-action range=[5, 5]
- fd10 at depth 9=False foundation at depth 9=False
- v0.13 first fd11 in set=True

## 4. Phase 2 — multi-source continuation

- sources=1 unique=1725 gen_depth=12 stop=max depth cross_origin_dups=0 min_fd=11 fnd=0 elapsed=2.386169699995662 rss=557.6015625

| Depth | Frontier | Unique | Generated | Dup | A | B | C | empty0 | empty1 | empty>=2 | min fd | origins |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 6 | 5 | 0 | 2 | 1 | 2 | 1 | 0 | 0 | 11 | 1 |
| 1 | 5 | 21 | 27 | 12 | 8 | 5 | 14 | 5 | 0 | 0 | 11 | 1 |
| 2 | 15 | 64 | 91 | 48 | 21 | 17 | 53 | 15 | 0 | 0 | 11 | 1 |
| 3 | 43 | 171 | 272 | 165 | 63 | 59 | 150 | 43 | 0 | 0 | 11 | 1 |
| 4 | 107 | 372 | 656 | 455 | 169 | 166 | 321 | 107 | 0 | 0 | 11 | 1 |
| 5 | 201 | 656 | 1177 | 893 | 336 | 338 | 503 | 201 | 0 | 0 | 11 | 1 |
| 6 | 284 | 972 | 1594 | 1278 | 495 | 505 | 594 | 284 | 0 | 0 | 11 | 1 |
| 7 | 316 | 1263 | 1711 | 1420 | 570 | 573 | 568 | 316 | 0 | 0 | 11 | 1 |
| 8 | 291 | 1490 | 1532 | 1305 | 549 | 523 | 460 | 291 | 0 | 0 | 11 | 1 |
| 9 | 227 | 1635 | 1171 | 1026 | 453 | 415 | 303 | 227 | 0 | 0 | 11 | 1 |
| 10 | 145 | 1704 | 736 | 667 | 302 | 287 | 147 | 145 | 0 | 0 | 11 | 1 |
| 11 | 69 | 1725 | 344 | 323 | 147 | 151 | 46 | 69 | 0 | 0 | 11 | 1 |
| 12 | 21 | 1725 | 0 | 0 | 0 | 0 | 0 | 21 | 0 | 0 | 11 | 1 |

## 5. Winning origin

- none.

## 6. First fd11 vs portfolio winner

| Metric | First fd11 | Portfolio (the only min-depth fd11) |
| --- | ---: | ---: |
| FD | 11 | 11 |
| Local depth from fd13 | 9 | 9 |
| Empties | [] | [] |
| Longest run | 6 | 6 |
| Adjacencies | 39 | 39 |
| Movable blocks | 4 | 4 |
| Legal actions | 5 | 5 |
| Can reach fd10 within 12 | no | no |
| Local depth to fd10 | — | — |

## 7. Exactly one next recommendation

No equally short fd11 checkpoint continues. Next: do not add a heuristic; the remaining question is whether a slightly longer route to fd11 yields a viable checkpoint — not this task.

## Integrity

Verdict ALL_MIN_DEPTH_FD11_CHECKPOINTS_STALL. candidates=1 complete=True fd10=no foundation=no.

Base SHA `dd16c4389c5f05cf157764c44a8c9dc3136dd924`. Deal `deals/4925153.txt`.
Multi-source search uses a fresh TT seeded only with min-depth fd11 states.
Production solve_progressive is unchanged.

