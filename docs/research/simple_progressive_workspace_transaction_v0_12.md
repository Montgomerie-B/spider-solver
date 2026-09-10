# Simple Progressive Search v0.12: Workspace Transaction Reachability

## 1. Verdict

`SHALLOW_WORKSPACE_REVEALS_FD12` — a replay-valid fd 12 state exists at primitive depth 8 from the empty seed.

v0.11's 233k-state depth-2000 DFS never found fd 12. Fair shallow A+B+C search finds it in eight primitives. The first empty is useful short-term working capital: the shortest reveal **uses it immediately** (Tier C consume), recreates it twice, and uncovers a face-down card at depth 8.

Empty-quality class (research only): `PRODUCTIVE_SHORT_TERM_WORKSPACE`.

Layered first-visit BFS is a research harness. Production `solve_progressive` is unchanged. No heuristic was added.

## 2. Seed

- ok=True digest `53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a29000000121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- path=102 cost=102 fd=13 stock=0 fnd=0 empties=[2] initial_empty_column=2 run=6

## 3. Layered search

- completed generated depth=8
- completed expanded depth=7
- unique=1000000 generated=3206355 duplicate_skips=2206355
- min_fd=11 max_fnd=0 max_run=9 max_empties=1
- elapsed_s=557.9 rss_mb=452.0 stop=unique limit
- unique limit hit while expanding depth 8 (depth-8 frontier complete; depth 9 is not)
- min_fd 11 appeared among incomplete depth-9 children; the shortest fd<=12 witness is depth 8 / fd 12
- no second simultaneous empty and no foundation in the completed envelope

| Depth | Frontier | Unique | Generated | Dup skips | A | B | C | empty0 | empty1 | empty>=2 | min fd | max run |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 23 | 22 | 0 | 1 | 3 | 18 | 0 | 1 | 0 | 13 | 6 |
| 1 | 22 | 159 | 236 | 100 | 41 | 62 | 133 | 17 | 5 | 0 | 13 | 9 |
| 2 | 136 | 753 | 1334 | 740 | 253 | 413 | 668 | 120 | 16 | 0 | 13 | 9 |
| 3 | 594 | 3121 | 6035 | 3667 | 1098 | 1890 | 3047 | 529 | 65 | 0 | 13 | 9 |
| 4 | 2368 | 11478 | 23621 | 15264 | 4615 | 7399 | 11607 | 2138 | 230 | 0 | 13 | 9 |
| 5 | 8357 | 38445 | 81412 | 54445 | 17118 | 25439 | 38855 | 7672 | 685 | 0 | 13 | 9 |
| 6 | 26967 | 123518 | 263909 | 178836 | 56460 | 80610 | 126839 | 24820 | 2147 | 0 | 13 | 9 |
| 7 | 85073 | 384710 | 834651 | 573459 | 180032 | 248949 | 405670 | 78270 | 6803 | 0 | 13 | 9 |
| 8 | 261192 | 1000000 | 1995135 | 1379844 | 423591 | 582393 | 989151 | 241295 | 19897 | 0 | 12 | 9 |

## 4. Witnesses

- fd_le_12: depth=8 local_cost=8 total_path=110 cost=110 fd=12 fnd=0 empties=[] run=6 replay=True first_empty_use_depth=1 tier=C timing=USE NOW
  empty_sequence=[[2], [], [], [], [2], [], [], [2], []]
  local `(1,2,1) (1,0,1) (1,4,1) (2,0,1) (1,2,1) (4,1,2) (2,4,1) (1,2,3)`
  fixture `solutions/4925153_simple_v0_12_fd12.moves.txt`
  only one workspace fingerprint at this shortest depth: consume / recreate / consume / recreate / consume
- foundation: none
- empty_transferred: depth=1 local_cost=0 total_path=103 cost=102 fd=13 fnd=0 empties=[4] run=6 replay=True first_empty_use_depth=1 tier=B timing=USE NOW
  empty_sequence=[[2], [4]]
- empty_recreated: depth=3 local_cost=3 total_path=105 cost=105 fd=13 fnd=0 empties=[2] run=6 replay=True first_empty_use_depth=1 tier=C timing=USE NOW
  empty_sequence=[[2], [], [], [2]]
- empty_consumed: depth=1 local_cost=1 total_path=103 cost=103 fd=13 fnd=0 empties=[] run=6 replay=True first_empty_use_depth=1 tier=C timing=USE NOW
  empty_sequence=[[2], []]
- second_empty: none
- run_ge_10: none

## 5. USE NOW vs WAIT/SETUP

Best hard witness: **USE NOW**.

The first move occupies the seed empty (column 2) with Tier C `(1,2,1)` and consumes it. The empty is later recreated on column 2 at local depths 4 and 7, then consumed again. The reveal is not a King-to-empty transfer; the B transfer `(4,2,2)` exists at depth 1 with MW cost 0 but is not the shortest fd12 route.

WAIT/SETUP is not required for this particular reveal.

## 6. Comparison with v0.11 DFS

- v0.11 DFS unique=233865 min_fd=13 empties=1 run=9 fnd=0 max_depth=2000
- v0.12 BFS unique=1000000 min_fd=11 empties=1 run=9 fnd=0 completed_depth=8

## 7. Exactly one next recommendation

Keep the shortest fd<=12 transaction as a research fixture. Next: test whether that eight-move consume/recreate/reveal sequence can be detected cheaply enough to influence ordering; do not add Pass 3 and do not return to deep DFS from this seed.

## Integrity

Verdict SHALLOW_WORKSPACE_REVEALS_FD12. Generated depth 8, unique=1000000, min_fd=11, max_empties=1, max_run=9, fnd=0, quality=PRODUCTIVE_SHORT_TERM_WORKSPACE.

Base SHA `d7be8cb2816bd91568980a90d67ee07e809367a6`. Deal `deals/4925153.txt`.
Production solve_progressive is unchanged. This harness is research-only.

