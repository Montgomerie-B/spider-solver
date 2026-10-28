# Heart-run follow-through v0.138

Schema `spider-heart-run-followthrough-0.138`. Deal `4925153`. Branch `local/heart-run-followthrough-v0-138`, started from v0.137 `2de1b845049979ea09ed351272615865fafab863`.

The target is a structural one: seven descending hearts on one column top. A buried run does not count, two shorter runs do not add, and the run is not a finished game. `f` orders candidates. The proof rule stays `g + admissible_remaining > proof_ceiling`, with equality eligible. Caps were not raised.

## Result

The anywhere-run predicate was already true at checkpoint 160, because column 7 holds a buried `8h 7h 6h 5h 4h 3h 2h Ah`. The additional obligation is the same length on a column top. That top run is false at checkpoint 160 and true after the next three canonical actions.

Gate A passed. From checkpoint 160, with no reference actions, the existing heart ordering built `Kh Qh Jh 10h 9h 8h 7h` at `g = 160`, `h = 10`, `f = 170`. The feasibility oracle, the canonical `7h` through `Ah` at checkpoint 163, costs `g = 161`, `h = 9`, `f = 170`. Same admissible `f`. The independent run is a different stack.

Gate B caught the same king-high run from the five-move shortcut at `g = 157`, `h = 13`, `f = 170`. The structure arrives inside the canonical assembly cost. The residual, the bond count, the open columns, and the legal-move count all stay behind checkpoint 163. The repair stopped on the clock with 180 unverified terminals, so a better residual in that tail is neither shown nor ruled out.

Gate C opened because Gate A passed. The eight early roots are the paired v0.134 portfolio. Seven roots replayed a top heart run. Root 3 stopped on the clock with no terminal. Six endpoints passed the `f <= 170` screen and had a proof-eligible child. The cheapest is root 0 at `g = 147`, `h = 22`, `f = 169`, with three cards still face-down and two foundations.

Gate D ran on those six prefixes. The proof-eligible frontier emptied: 258 identities, 260 expansions, 7.927 seconds, minimum `f` 169, maximum foundations 3, no solved game. Under `g + h > 171` those six prefixes have no completion at 171 or below. The 172 line is a different prefix and was not changed. Root 3 and the unverified extra terminals were not part of this continuation.

The 171 objective is not established. The canonical post-SD5 search was not repeated. The exhausted v0.136 pack was not rerun. v0.139 was not started.

## 1. What the three canonical actions add

Checkpoint 160 is `g = 158`, `h = 11`, `f = 169`, stock empty, face-down 0, three foundations. `evaluate_target(..., "same_suit_run_at_least", suit=h, min_len=7)` is already true. The longest top heart run is `Kh` through `9h`, length 5, on column 2. Column 1's top is `3h 2h Ah`, length 3, with `Kh` through `8h` buried under it.

The next three solution actions were replayed as a feasibility oracle and were not given to any search:

| Action | Cost | `g` | Top heart length |
| --- | ---: | ---: | ---: |
| `move 3 4 1` | 1 | 159 | 5 |
| `move 3 5 3` | 1 | 160 | 4 (`7h` through `4h`) |
| `move 1 5 3` | 1 | 161 | 7 |

The replay pack matches checkpoint 163. Column 5 is then `7h 6h 5h 4h 3h 2h Ah`. Column 1's `Kh` through `8h` is on top and is length 6. `h = 9`, so `f = 170`. Bonds 51, mixed joins 3, open columns 2, legal tableau moves 114, face-down 0, foundations 3, stock 0.

`choose_heart_obligation` therefore selects `top_same_suit_run_at_least`. Any top run of seven hearts meets it. The predicate is not locked to `7h` through `Ah`.

## 2. Positive control

Source: checkpoint 160. Budgets: 3 paid moves, 6 actions, 2,000 identities, 4 seconds, 512 MB, proof ceiling 172. Suit `h`, default lanes, stop on the first replayed top run. No reference actions.

| | Control |
| --- | ---: |
| Stop | solved |
| `g` / paid / zero-cost | 160 / 2 / 0 |
| Wall / process seconds | 0.051545 / 0.046875 |
| Bound time inside that | 0.011103 |
| Identities / expansions / generated | 49 / 2 / 125 |
| Lane expansions | progress 2, setup 0 |
| Peak RSS | 31.590 MB |
| Proof prunes | 0 |
| Search `min_f` / `min_h` | 169 / 10 |

Actions: `move 1 4 3`, `move 5 1 1`. Replay leaves column 1 as `Kh Qh Jh 10h 9h 8h 7h`. The goal is false on the root and true on the endpoint. Foundations stay 3. The position is not solved.

| | Checkpoint 163 | Independent control |
| --- | ---: | ---: |
| Corrected cost | 161 | 160 |
| Admissible `h` | 9 | 10 |
| `f = g + h` | 170 | 170 |
| Top run | `7h` through `Ah` | `Kh` through `7h` |
| Same-suit bonds | 51 | 50 |
| Mixed joins | 3 | 3 |
| Open columns | 2 | 3 |
| Legal tableau moves | 114 | 143 |
| Face-down cards | 0 | 0 |
| Foundations | 3 | 3 |

The heart ordering extends the longest top run, which at this root is the king-high stack. It reaches a legal seven-heart top two actions and one corrected move before the canonical ace-low stack, at the same `f`.

## 3. Shortcut repair

The v0.136 five-move shortcut was replayed from checkpoint 152 for comparison only: `move 5 2 1`, `move 5 9 1`, `move 4 5 1`, `move 4 1 2`, `move 4 9 1`. Endpoint `g = 155`, `h = 14`, `f = 169`, bonds 46, mixed joins 3, open columns 2, legal moves 56, face-down 0, foundations 3. The top heart run is length 5. Those tuples were not passed to `search_milestone`.

The repair used 6 paid moves, 12 actions, 6,000 identities, 6 seconds, 512 MB, proof ceiling 172, `hit_policy="lower_f"`, and the same top-run goal. It stopped on the clock.

| | Best verified repair | Checkpoint 163 |
| --- | ---: | ---: |
| Corrected cost | 157 | 161 |
| Admissible `h` | 13 | 9 |
| `f` | 170 | 170 |
| Top run | `Kh` through `7h` | `7h` through `Ah` |
| Bonds | 47 | 51 |
| Mixed joins | 3 | 3 |
| Open columns | 1 | 2 |
| Legal tableau moves | 56 | 114 |
| Face-down | 0 | 0 |
| Foundations | 3 | 3 |

Actions on that verified hit: `move 1 4 3`, `move 7 1 1`. Wall 6.006871 seconds, process time 6.000000 seconds, 1,268 identities, 486 expansions, 7,713 proof prunes, peak RSS 37.781 MB. Lanes: progress 259, setup 227. The kernel saw 308 terminals. Verification kept 128, retained 8, and left 180 unverified. Those 180 were not shown to have a worse `f`. Other verified hits sit at `g = 158`, `h = 12`, `f = 170`, still above the canonical residual of 9. The label is caught up on `g`. It is not a better tableau, and the clock makes the repair inconclusive about any cheaper residual still in the queue.

## 4. Eight early roots

`discover_macros` used the unchanged 6-second generator from checkpoint 140. This pass kept 3,198 identities, expanded 229, generated 4,002, and stopped at 6.148414 seconds. The portfolio fingerprint matches the v0.134 and v0.135 artifacts. Node counts inside the cap can move; the fingerprint is the pairing.

| Root | Post-deal `g` / `h` / `f` |
| --- | --- |
| 0 | 142 / 24 / 166 |
| 1 | 143 / 24 / 167 |
| 2 | 144 / 24 / 168 |
| 3 | 144 / 25 / 169 |
| 4 | 144 / 25 / 169 |
| 5 | 143 / 25 / 168 |
| 6 | 143 / 24 / 167 |
| 7 | 144 / 24 / 168 |

Each root then sought the top heart run with the default lanes, suit `h`, `hit_policy="lower_f"`, 12 paid moves, 18 actions, 6,000 identities, 6 seconds, 512 MB, and proof ceiling 171. All eight stopped on the clock. A clock stop with no hit is inconclusive for that root.

| Root | Met | First hit | `min_f` | Unique | Expanded | Terminals verified / seen | Proof prunes |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 0 | yes, `g = 152` | 10 paid, 1.581 s | 166 | 3,679 | 723 | 61 / 61 | 6,261 |
| 1 | yes, `g = 151` | 8 paid, 0.419 s | 167 | 1,963 | 525 | 5 / 5 | 7,711 |
| 2 | yes, `g = 151` | 7 paid, 0.221 s | 168 | 1,037 | 565 | 49 / 49 | 8,678 |
| 3 | no | | 169 | 707 | 405 | 0 / 0 | 7,580 |
| 4 | yes, `g = 153` | 9 paid, 0.349 s | 169 | 851 | 506 | 10 / 10 | 9,838 |
| 5 | yes, `g = 151` | 8 paid, 0.695 s | 168 | 1,673 | 515 | 72 / 72 | 7,375 |
| 6 | yes, `g = 150` | 7 paid, 1.374 s | 167 | 1,615 | 468 | 14 / 14 | 7,152 |
| 7 | yes, `g = 152` | 8 paid, 0.533 s | 168 | 1,335 | 526 | 128 / 161 | 8,664 |

Root 7 left 33 terminals unverified. They were not shown to have a worse `f`. Eight tactic searches took 48.070 wall seconds and 47.766 process seconds.

Selection kept the lower `f`, then the lower `g`, one physical prefix per symmetry, then one endpoint per root, and filled any spare slot. 53 replayed heart states were eligible, 44 symmetries survived, 9 duplicates kept the lower `f`, and 36 higher-`f` states were truncated. `f` here is a lower bound. Every retained state still has three face-down cards and two foundations.

| Root | `g` | `h` | `f` | Paid | Bonds | Open | Legal moves | Top run | Screen |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 147 | 22 | 169 | 5 | 50 | 0 | 9 | 7 | opened |
| 6 | 150 | 20 | 170 | 7 | 52 | 0 | 16 | 7 | opened |
| 2 | 150 | 20 | 170 | 6 | 52 | 0 | 24 | 7 | opened |
| 5 | 152 | 18 | 170 | 9 | 54 | 1 | 54 | 9 | opened |
| 7 | 153 | 17 | 170 | 9 | 55 | 1 | 72 | 9 | opened |
| 0 | 148 | 22 | 170 | 6 | 50 | 0 | 9 | 7 | opened, same macro as the `g = 147` line |
| 4 | 151 | 20 | 171 | 7 | 52 | 1 | 50 | 9 | `f` above 170 |
| 1 | 151 | 20 | 171 | 8 | 52 | 0 | 16 | 7 | `f` above 170 |

The opened states each have one legal child with `g + h <= 171`. That one-ply check is not a search. `proof` on the screen is false. The v0.136 exhausted pack and its symmetry were loaded from the v0.136 and v0.137 artifacts and matched none of these endpoints, so that continuation was not started. Root 0's pre-deal macro is `move 2 5 1`, `move 8 1 3`, `move 10 8 2`, `move 1 10 3`, `move 3 1 2`, `move 9 2 1`. Its heart path to `g = 147` is `move 8 3 1`, `move 8 2 2`, `move 4 8 1`, `move 2 4 3`, `move 7 4 1`.

## 5. Continuation

One shared origin-fair search covered the six opened prefixes. Budget 20,000 identities, 45 seconds, 512 MB, one worker, ceiling 171. No tactical paid cap was passed in. Each origin kept its own pre-deal macro. No reference sequence was a seed.

The search stopped because the frontier was empty. Wall 7.926560 seconds, peak RSS 40.402 MB, 258 identities, 260 expansions, 20,081 generated, 1,076 zero-cost actions considered, 11,950 proof-pruned identities (11,916 unretained), 0 ceiling prunes, 0 terminals, 0 reference rejoins. Minimum `f` stayed 169. Minimum `h` seen in the search was 11 and maximum `h` was 24. Maximum foundations stayed 3.

Expansions by origin, in screen order: 10, 16, 29, 76, 126, 3. Every origin reports exhausted. `accept_improved_route` was not called. No solution file was written.

This is a negative result for these six prefixes under the existing proof rule. It does not cover root 3, the truncated higher-`f` heart states, or the 33 unverified root-7 terminals. The canonical 172 route remains the incumbent.

## 6. Solutions and tests

Both solution files were hashed and replayed before and after the driver. `solutions/4925153_canonical.moves` is 174 actions, MobilityWare 172, eight foundations, SHA-256 `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33`. `solutions/4925153_autonomous_185.moves` is 189 actions, MobilityWare 185, eight foundations, SHA-256 `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73`. The hashes match. `independent_cold_complete` stays false.

`tests/test_heart_run_followthrough_v0_138.py`: 9 passed. The file locks the top-run predicate against a buried run, the checkpoint-160 obligation, an unseeded one-move join, a zero-cost whole-column park on a stock-bearing board, ordered identity while stock remains, symmetry after the stock is empty, proof equality against a separate depth cap, lower-`f` retention of the cheaper prefix macro, rejection of an exhausted identity with `proof` false, and the driver's gate order. The unit tests do not run the 4-second control or the eight tactic searches. The zero-cost fixture keeps one stock card so the park stays a physical column. An empty stock would treat that park as a permutation of its parent and skip the column-specific goal.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

The maintained regression is the v0.123 file list plus the v0.124, v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, v0.137, and v0.138 files: 44 files, 654 passed, 0 failed, in 225.02 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT`. It was not changed.

## 7. Next recommendation

Do not search another suit length on these early roots. Every opened heart endpoint still had three face-down cards, and the cheapest, `g = 147`, `h = 22`, `f = 169`, was closed by the 171 proof with the foundations still at two. The next experiment should accept a top heart run only when the face-down count has also fallen, on these same eight roots and the same caps. Leave the exhausted `g = 154` pack out. This release does not start that search.
