# Simple Progressive Search v0.13: Hard-Progress Reveal Ratchet

## 1. Verdict

`REVEAL_RATCHET_STALLS_AT_FD11` — the minimum-depth fd11 checkpoint is real and replay-valid, but a fresh shallow A+B+C search from it cannot reach fd10.

Phase 1 reproduces v0.12: fd 13→11 at local depth 9 (one move beyond the fd12 witness). That checkpoint has **no empty column**. Phase 2 then exhausts the entire A+B+C graph within depth 12 — only 1,725 unique states, frontier shrinking to 21 — with min fd still 11 and zero empties at every layer.

Each stage uses a fresh exact first-visit table. Production `solve_progressive` is unchanged.

## 2. Seed

- ok=True digest `53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a29000000121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- empty columns=[2]

## 3. Checkpoint comparison

| Start FD | Target FD | Local depth | Unique searched | Local MW cost | Start empties | End empties | Foundation |
| ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 13 | 11 | 9 | 522680 | 9 | [2] | [] | 0 |
| 11 | 10 | None | 1725 | None | [] | None | 0 |

## 4. Phase 1 — harvest fd11

- stop=fd <= 11 unique=522680 depth=9 local_cost=9 rss=250.00390625 elapsed=291.72905579999497
- replay ok=True total_path=111 cost=111 fd=11 stock=0 fnd=0 empties=[] run=6
- workspace timing=immediate consumed=3 transferred=0 recreated=2 second_empty=0 sequence=[[2], [], [], [], [2], [], [], [2], [], []]
- fixture `solutions/4925153_simple_v0_13_fd11.moves.txt`
- fresh_tt=True imported_keys=0

## 5. Phase 2 — restart from fd11

- no fd10. stop=max depth unique=1725 min_fd=11 max_fnd=0 gen_depth=12 rss=254.0 elapsed=2.5
- fresh_tt=True imported_keys=0
- the fd11 root has 0 empties; every Phase-2 layer also has 0 empties
- the unique set saturates (frontier 316 at depth 7, then declines to 21 at depth 12)

| Depth | Frontier | Unique | Generated | Dup | A | B | C | empty0 | empty1 | empty>=2 | min fd | max run |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 6 | 5 | 0 | 2 | 1 | 2 | 1 | 0 | 0 | 11 | 6 |
| 1 | 5 | 21 | 27 | 12 | 8 | 5 | 14 | 5 | 0 | 0 | 11 | 7 |
| 2 | 15 | 64 | 91 | 48 | 21 | 17 | 53 | 15 | 0 | 0 | 11 | 9 |
| 3 | 43 | 171 | 272 | 165 | 63 | 59 | 150 | 43 | 0 | 0 | 11 | 9 |
| 4 | 107 | 372 | 656 | 455 | 169 | 166 | 321 | 107 | 0 | 0 | 11 | 9 |
| 5 | 201 | 656 | 1177 | 893 | 336 | 338 | 503 | 201 | 0 | 0 | 11 | 9 |
| 6 | 284 | 972 | 1594 | 1278 | 495 | 505 | 594 | 284 | 0 | 0 | 11 | 9 |
| 7 | 316 | 1263 | 1711 | 1420 | 570 | 573 | 568 | 316 | 0 | 0 | 11 | 9 |
| 8 | 291 | 1490 | 1532 | 1305 | 549 | 523 | 460 | 291 | 0 | 0 | 11 | 9 |
| 9 | 227 | 1635 | 1171 | 1026 | 453 | 415 | 303 | 227 | 0 | 0 | 11 | 9 |
| 10 | 145 | 1704 | 736 | 667 | 302 | 287 | 147 | 145 | 0 | 0 | 11 | 7 |
| 11 | 69 | 1725 | 344 | 323 | 147 | 151 | 46 | 69 | 0 | 0 | 11 | 7 |
| 12 | 21 | 1725 | 0 | 0 | 0 | 0 | 0 | 21 | 0 | 0 | 11 | 6 |

## 6. Optional Phase 3 — fd10 to fd9

- not run.

## 7. Foundation

- no foundation reached.

## 8. Exactly one next recommendation

The minimum-depth fd11 consumed the last empty, and A+B+C from that empty-less checkpoint is a 1,725-state closed bubble with no fd10. Next: do not add a heuristic and do not deepen DFS from this checkpoint; if another ratchet is tried, compare same-depth fd11 children that still hold an empty.

## Integrity

Verdict REVEAL_RATCHET_STALLS_AT_FD11. fd11 depth=9 fd10=no fd9=no foundation=no.

Base SHA `4e6b452a85b52d45f4c9a168995c5f843a45bdbd`. Deal `deals/4925153.txt`.
Ratchet restarts use a fresh TT. Production solve_progressive is unchanged.

