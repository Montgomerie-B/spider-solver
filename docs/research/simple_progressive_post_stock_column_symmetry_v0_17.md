# Simple Progressive Search v0.17: Post-Stock Tableau Column-Symmetry Audit

## 1. Verdict

`POST_STOCK_COLUMN_SYMMETRY_HIGH_VALUE` — the stock=0 column quotient is exact, preserves hard reachability, and substantially reduces the measured search.

After stock is exhausted, treating "this pile is column 3" and "this identical pile is column 5" as different exact states wastes **44.3%** of the ordered unique set through generated depth 9 (`1,144,490 → 638,006`, reduction **1.79×**). The depth-9 frontier shrinks `759,780 → 413,328` (**1.84×**). Reduction grows with depth.

The v0.16 "outside-bubble" true first-crossing is **not** a new position. It is the known dead fd11 checkpoint with 1-based columns **3 and 5 swapped**. Under the quotient that labelling is first-visit-duplicate of the depth-9 dead class. The five other depth-10 true-crossings remain distinct symmetry classes, so one-move-slack diversity among those six children survives; the outside-vs-inside distinction does not.

Production `pack_state` / `solve_progressive` are unchanged. The post-stock column quotient is research-only. It is an **exact game automorphism at stock=0**, not heuristic pruning. It is **not integrated**.

## 2. Formal stock=0 symmetry contract

- ORDERED EXACT IDENTITY: `pack_state` serialises columns 0..9 in physical order. Magic `SPK1`.
- POST-STOCK SYMMETRY IDENTITY: when stock is empty, encode each complete column exactly (face-down order + face-up order), sort the ten encodings lexicographically, and keep canonical foundations. Magic `SPS1`. Never unpack this blob as a `SpiderState`.
- Card identity, face-down order, face-up order, foundations, and column multiplicity are retained. Only whole-column permutation is quotiented.
- Stock remaining: `pack_post_stock_symmetry_state` **raises**. `pack_search_identity(..., post_stock_column_symmetry=True)` falls back to ordered `pack_state`. Arbitrary column swaps of stock-bearing states are **not** identified (future deal rows still land left-to-right on physical columns).
- Concrete representative: BFS stores ordered `pack_state` for every class and generates legal moves on that physical labelling. Replay concatenates the original prefix with those physical actions. Paths never mix column indices from different representatives.
- Equivariance verified on constructed states: legal tableau successors, automatic flip, complete-run removal, and MobilityWare move cost.
- Contract verified: **True**

## 3. Negative stock-bearing test

A constructed stock-bearing state and the same state with two tableau columns swapped:

- `pack_post_stock_symmetry_state` raises `ValueError: post-stock column symmetry is undefined while stock remains`
- `pack_search_identity(..., post_stock_column_symmetry=True)` returns ordinary `pack_state` for both, and those ordered keys **differ**

The post-stock quotient does not leak into stock-bearing identity.

## 4. Phase 2 — v0.16 outside fd11 vs dead checkpoint

Independent inspection suggested a 1-based 3↔5 swap. Repository reconstruction **confirms** it.

- dead ordered digest: `53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100032d2c2b00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- outside ordered digest: `53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100022d0c00121413121d071d1c1b1a19181716153433323100032d2c2b00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- ordered keys equal: **no**
- symmetry keys equal: **yes**
- 0-based mapping dead→outside: `[0, 1, 4, 3, 2, 5, 6, 7, 8, 9]`
- 1-based mapping dead→outside: `{1:1, 2:2, 3:5, 4:4, 5:3, 6:6, 7:7, 8:8, 9:9, 10:10}`
- exact permutation: swap 1-based columns **3 and 5**
- permuting the dead state by that mapping reconstructs the outsider ordered digest exactly

Both states: fd 11, empties 0, foundations 0, run 6, legal 5 (A=2/B=1/C=2/D=0), stock 0.

## 5. Phase 3 — six true depth-10 fd11 states

- ordinary ordered canonical count: **6**
- post-stock symmetry-class count: **6**
- class multiplicities: all 1

| # | bubble | ordered digest prefix | symmetry class |
| ---: | --- | --- | ---: |
| 1 | True | `53504b3101000000…` | 1 |
| 2 | True | `53504b3101000000…` | 2 |
| 3 | True | `53504b3101000000…` | 3 |
| 4 | True | `53504b3101000000…` | 4 |
| 5 | True | `53504b3101000000…` | 5 |
| 6 | False | `53504b3101000000…` | 6 |

The six depth-10 crossings are not column permutations of one another. Candidate 6 is a column permutation of the **depth-9 dead checkpoint**, which is not itself one of the six. Apparent one-move-slack diversity among the six children therefore survives; the claim that candidate 6 is a new continuation-relevant fd11 does not.

## 6. Phase 4 — dead-bubble ordered vs symmetry

- control (ordered `pack_state`): unique **1728**, stop=`frontier empty`, max generated depth 13, min fd 11, empty ever=no, foundation ever=no
- treatment (post-stock symmetry): unique **1728**, stop=`frontier empty`, max generated depth 13, min fd 11, empty ever=no, foundation ever=no
- quotient of the 1728 ordered hexes: **1728** classes
- reduction factor: **1.00**
- qualitative reachability: **identical** (no `SYMMETRY_CONTRACT_FAILURE`)

The closed fd11 bubble contains no hidden column-label copies of itself. Its 1728 states differ by card placement, not by pile labels. The v0.16 outsider graph is the same 1728 classes under a 3↔5 relabelling.

## 7. Phase 5 — shallow symmetry search from the fd13 seed

Authoritative seed: `solutions/4925153_simple_fd13_empty1_seed.moves.txt` (102 primitives, MW 102, fd 13, stock 0, foundations 0, empty `[2]`).

- stop=`max depth` (generated completely through depth 9)
- symmetry unique=**638,006** generated=**2,147,154** duplicate_skips=**1,509,149** duplicate rate=**0.70286**
- elapsed=**480.8 s** peak RSS=**436.2 MiB** (limits 2,000,000 / 1800 s / 4 GiB not hit)
- min fd=11; **fd12 minimum depth=8**; **fd11 minimum depth=9**
- fd12 witness replay from original deal: **True** (path length 110, MW 110)
- fd11 witness replay from original deal: **True** (path length 111, MW 111); representative digest **equals the known dead fd11 ordered key**

Ordered baseline is the committed v0.14 census, not rerun.

| Depth | Ordered frontier | Symmetry frontier | Ordered cumulative unique | Symmetry cumulative unique | Reduction |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 1 | 23 | 22 | 1.0455 |
| 1 | 22 | 21 | 159 | 136 | 1.1691 |
| 2 | 136 | 114 | 753 | 583 | 1.2916 |
| 3 | 594 | 447 | 3121 | 2203 | 1.4167 |
| 4 | 2368 | 1620 | 11478 | 7447 | 1.5413 |
| 5 | 8357 | 5244 | 38445 | 23770 | 1.6174 |
| 6 | 26967 | 16323 | 123518 | 74594 | 1.6559 |
| 7 | 85073 | 50824 | 384710 | 224678 | 1.7123 |
| 8 | 261192 | 150084 | 1144490 | 638006 | 1.7939 |
| 9 | 759780 | 413328 | 1144490 | 638006 | 1.7939 |

Proof status: exact post-stock column quotient for `stock=0`. Not heuristic. Not production.

## 8. Exactly one next recommendation

The post-stock column quotient is an exact symmetry reduction. Next: keep it research-only until a dedicated integration task; do not add two-move slack here.

## Integrity

Verdict POST_STOCK_COLUMN_SYMMETRY_HIGH_VALUE. ordered_eq=False symmetry_eq=True 1-based swap 3↔5. true-crossing ordered=6 symmetry=6. bubble 1728→1728. fd12=8 fd11=9 both replay. search unique=638006 through generated depth 9, 1.79× vs ordered 1144490. stop=max depth.

Base SHA `6eb0edc324203725e79e429630b5cd8f46498530`. Deal `deals/4925153.txt`.
Production pack_state and solve_progressive are unchanged. Two-move slack was not searched.
The quotient is not integrated.

