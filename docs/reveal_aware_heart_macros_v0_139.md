# Reveal-aware heart macros v0.139

Schema `spider-reveal-aware-heart-macros-0.139`. Deal `4925153`. Branch `local/reveal-aware-heart-macros-v0-139`, started from verified v0.138 `be5f64276f49f0d64532c1d62299e7f858ebe645`.

The terminal has to hold two facts at once: a seven-card descending heart run that ends on a column top, and fewer face-down cards than the search root. A buried run does not count. A reveal that is undone before the run is finished does not count. A heart foundation is not this goal. `f` is a screen. The proof rule stays `g + admissible_remaining > proof_ceiling`, with equality eligible. Caps were not raised.

## Result

Gate B passed. From checkpoint 158, with no reference actions, the run-and-reveal search built `Kh` through `7h` and revealed the last face-down card at `g = 159`, `h = 12`, `f = 171`. The feasibility oracle, checkpoint 163, is a different stack: `7h` through `Ah` at `g = 161`, `h = 9`, `f = 170`.

Gate C ran on the paired eight post-SD5 roots. Every recorded terminal was replayed before ranking. Root 0 produced one verified compound state, `g = 154`, `h = 17`, `f = 171`, face-down 3 to 2, top run `Kh` through `7h`. That `f` is above the `f <= 170` screen, so it was not continued. Roots 1–7 recorded no compound terminal. Each of those searches stopped on the 6-second clock with verification complete and zero terminals. Gate D did not run.

The release stopped at Gate C, inconclusive for these roots. No `<= 171` game was produced. The 172 line was not changed. v0.140 was not started.

The v0.138 node graphs were not stored. Root 7's 33 unverified terminals and the shortcut repair's 180 unverified terminals were not reconstructed, and this release did not rerun that search.

## 1. Exhaustive terminal verification

`hit_policy="lower_f"` now replays every terminal the bounded kernel recorded, assigns admissible `h` and `f`, keeps the cheaper physical chain for the same pack and then the same symmetry, and only then sorts by `f`. The legacy 128-terminal window remains for `lowest_g`. A synthetic board with more than 128 legal cost-1 terminals puts every best-`f` path after that window. The legacy verifier misses them. The opt-in verifier keeps one. An exception during the walk returns no best and reports `INCOMPLETE VERIFICATION`.

Post-processing wall and CPU are `verify_wall_s` and `verify_cpu_s`. They are not added to the search deadline or to search `cpu_s`.

In this experiment the searches recorded two terminals in total: one in the control and one on root 0. Both replayed. Unverified terminals are 0. Verification wall time was 0.000525 seconds for the control and 0.000592 seconds for root 0. The other roots recorded nothing, so their verification walk was empty. The 128-window was not the binding limit of this run.

## 2. Feasibility oracle

Checkpoint 158 is `g = 156`, `h = 13`, `f = 169`, stock empty, face-down 1, two foundations, top heart length 5. The seven-card top run is false.

The next five canonical actions were replayed and were not given to any search. Each costs 1. The first reveals the face-down card while the top run is still length 5. Both facts are true together only after the fifth action.

| | Checkpoint 158 | Checkpoint 163 |
| --- | ---: | ---: |
| Corrected cost | 156 | 161 |
| Admissible `h` | 13 | 9 |
| `f = g + h` | 169 | 170 |
| Top heart length | 5 (`Kh` through `9h`) | 7 (`7h` through `Ah`) |
| Face-down cards | 1 | 0 |
| Foundations | 2 | 3 |
| Same-suit bonds | 59 | 51 |
| Mixed joins | 3 | 3 |
| Open columns | 1 | 2 |
| Legal tableau moves | 72 | 114 |
| Stock | 0 | 0 |

The replay pack matches checkpoint 163. Paid cost is 5. `g` moves 156 to 161.

## 3. Positive control

Source: checkpoint 158. Budgets: 5 paid moves, 8 actions, 12,000 identities, 12 seconds, 512 MB, one worker, proof ceiling 172. Suit `h`, `run_reveal` lanes, stop on the first replayed compound state. No reference actions.

| | Control |
| --- | ---: |
| Stop | solved |
| `g` / paid / zero-cost | 159 / 3 / 0 |
| `h` / `f` | 12 / 171 |
| Wall / process seconds | 0.084514 / 0.093750 |
| Bound time inside that | 0.029270 |
| Verification wall / process | 0.000525 / 0.000000 |
| Identities / expansions / generated | 124 / 3 / 134 |
| Lane expansions | run 2, reveal 1, setup 0 |
| Peak RSS | 31.672 MB |
| Proof prunes | 0 |
| Terminals / verified / rejected | 1 / 1 / 0 |
| Verification | complete |
| Search `min_f` / `min_h` / `max_h` | 169 / 12 / 14 |

Actions: `move 4 6 2`, `move 1 8 1`, `move 5 1 1`. Replay leaves a top run `Kh` through `7h` and face-down 0. Bonds 60, mixed joins 4, open columns 1, legal tableau moves 68, foundations 2, stock 0. Children seen during the search: 57 reveal-only, 1 run-and-reveal, 0 run-only. The goal is false on the root and true on the endpoint. Foundations stay 2. The position is not solved.

| | Checkpoint 163 | Independent control |
| --- | ---: | ---: |
| Corrected cost | 161 | 159 |
| Admissible `h` | 9 | 12 |
| `f = g + h` | 170 | 171 |
| Top run | `7h` through `Ah` | `Kh` through `7h` |
| Same-suit bonds | 51 | 60 |
| Mixed joins | 3 | 4 |
| Open columns | 2 | 1 |
| Legal tableau moves | 114 | 68 |
| Face-down cards | 0 | 0 |
| Foundations | 3 | 2 |

The control meets the compound predicate inside the cap. Its admissible `f` is 171, one above the later screen. Gate B does not require `f <= 170`.

## 4. Portfolio

The unchanged 6-second macro generator rebuilt the eight roots from checkpoint 140. Stop: time limit. 2,990 identities, 217 expansions, 3,732 generated, 6.132113 seconds, peak RSS 33.539 MB.

The action lists, post-deal `g` / `h` / `f`, hit sets, packs, and symmetries match the stored v0.134 and v0.135 portfolios, so the comparison is paired. The identity count under the same clock differs from the v0.138 discovery trace, which recorded 3,198 identities. Pairing uses the portfolio fingerprint, not that counter.

| Root | Macro | `g` | `h` | `f` | Face-down | Top hearts |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 0 | `move 2 5 1`, `move 8 1 3`, `move 10 8 2`, `move 1 10 3`, `move 3 1 2`, `move 9 2 1` | 142 | 24 | 166 | 3 | `5h 4h 3h` |
| 1 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 10 2` | 143 | 24 | 167 | 3 | `5h 4h 3h` |
| 2 | `move 2 1 1`, `move 10 5 2`, `move 1 10 1`, `move 3 1 2`, `move 9 2 1`, `move 7 10 1`, `move 7 8 2` | 144 | 24 | 168 | 3 | `5h 4h 3h` |
| 3 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 4 5`, `move 8 4 2` | 144 | 25 | 169 | 3 | `5h 4h 3h` |
| 4 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 10 2`, `move 9 4 7` | 144 | 25 | 169 | 3 | `5h 4h 3h` |
| 5 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 9 4 7` | 143 | 25 | 168 | 3 | `5h 4h 3h` |
| 6 | `move 2 1 1`, `move 8 5 3`, `move 1 8 1`, `move 9 2 1`, `move 3 1 2`, `move 3 10 2` | 143 | 24 | 167 | 3 | `5h 4h 3h` |
| 7 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 10 2`, `move 7 5 1` | 144 | 24 | 168 | 3 | `5h 4h 3h` |

## 5. Compound tactics

Each root had one search: 12 paid moves, 18 actions, 6,000 identities, 6 seconds, 512 MB, one worker, proof ceiling 171, `run_reveal`, `hit_policy="lower_f"`. All legal actions stayed available. Verification ran after the clock and did not extend the search.

| Root | Stop | Unique | Expanded | Generated | Wall s | CPU s | Verify s | Proof ids | Terminals | Verified | Max top | Run only | Both |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | time limit | 3327 | 765 | 14690 | 6.014015 | 6.015625 | 0.000592 | 6492 | 1 | 1 | 9 | 170 | 1 |
| 1 | time limit | 1996 | 546 | 15355 | 6.008921 | 6.015625 | 0.000019 | 8272 | 0 | 0 | 9 | 140 | 0 |
| 2 | time limit | 1039 | 563 | 15720 | 6.005723 | 6.000000 | 0.000016 | 10379 | 0 | 0 | 9 | 54 | 0 |
| 3 | time limit | 886 | 523 | 17010 | 6.007926 | 6.000000 | 0.000016 | 9934 | 0 | 0 | 5 | 0 | 0 |
| 4 | time limit | 868 | 507 | 15839 | 6.019730 | 6.015625 | 0.000038 | 10219 | 0 | 0 | 9 | 10 | 0 |
| 5 | time limit | 1527 | 488 | 14469 | 6.007178 | 5.984375 | 0.000017 | 8255 | 0 | 0 | 9 | 96 | 0 |
| 6 | time limit | 1927 | 578 | 16701 | 6.002940 | 6.000000 | 0.000029 | 9039 | 0 | 0 | 9 | 101 | 0 |
| 7 | time limit | 1096 | 478 | 16628 | 6.017423 | 6.031250 | 0.000020 | 10235 | 0 | 0 | 11 | 99 | 0 |

Every row has verification `complete`, exhaustive true, replay-rejected 0, screened 0, and unverified terminals 0. `reveal_without_run` is 0 on every root. Minimum face-down stayed 3 except on root 0, where it fell to 2. Lane expansions stayed inside `run`, `reveal`, and `setup`. Peak RSS stayed between 38.984 MB and 39.672 MB.

Root 0's verified terminal, replayed from checkpoint 140 through that root's macro, the fifth deal, and these twelve actions:

`move 3 1 1`, `move 8 1 1`, `move 8 2 2`, `move 7 2 1`, `move 3 8 7`, `move 10 8 1`, `move 4 10 1`, `move 10 6 4`, `move 4 10 3`, `move 2 4 5`, `move 4 2 7`, `move 4 10 1`.

| | Root 0 compound state |
| --- | ---: |
| Corrected cost | 154 |
| Admissible `h` | 17 |
| `f` | 171 |
| Paid / zero-cost | 12 / 0 |
| Top run | `Kh` through `7h` |
| Face-down before / after | 3 / 2 |
| Same-suit bonds | 55 |
| Mixed joins | 6 |
| Open columns | 0 |
| Legal tableau moves | 22 |
| Foundations | 2 (`s`, `d`) |
| Stock | 0 |

The pack and the symmetry are absent from the v0.136, v0.137, and v0.138 exhausted identities. Selection still dropped it: `f = 171` is above the screen of 170. Eligible endpoints after that screen: 0. Kept: 0. Opened: 0. `f <= 170` is not a proof that this state cannot finish, and failing it is not a proof about the other seven roots.

Roots 1–7 built long heart runs while the three face-down cards stayed buried. Root 3's longest top heart run was 5. The missing piece on those seven roots, inside this cap, was a reveal in the same state as the run. Terminal verification did not discard a recorded compound candidate on those roots, because none was recorded.

## 6. Continuation

Gate D did not run. There was no new compound endpoint with `f <= 170` and a fully validated origin. The 20,000-identity, 45-second continuation stayed idle. No route was submitted to `verify_complete_solution`. `independent_cold_complete` stays false.

## 7. Solutions and tests

Both solution files were hashed and replayed before and after the driver. `solutions/4925153_canonical.moves` is 174 actions, MobilityWare 172, eight foundations, SHA-256 `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33`. `solutions/4925153_autonomous_185.moves` is 189 actions, MobilityWare 185, eight foundations, SHA-256 `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73`. The hashes match.

`tests/test_reveal_aware_heart_macros_v0_139.py`: 9 passed. The file locks the late-`f` fixture, incomplete verification, the unchanged `lowest_g` choice, checkpoints 158 and 163, the compound predicate, reveal-first and heart-first ordering, a zero-cost park on a stock-bearing board, proof equality, the exhausted-pack screen, and the driver's gate order. The unit tests do not run the 12-second control or the eight tactic searches.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

The maintained regression is the v0.123 file list plus the v0.124, v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, v0.137, v0.138, and v0.139 files: 45 files, 663 passed, 0 failed, in 221.80 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT`. It was not changed.

## 8. Next recommendation

Do not start v0.140 as another suit, length, or milestone variant. The compound predicate is feasible, and one paired root reached it, at an `f` the 171 screen will not continue. The other seven roots spent the cap on heart runs that never revealed a card. The next review should cover long-horizon dependencies, action abstractions, how informative the proof bound is once `f` is already in the high 160s, and the quality of this eight-root portfolio. This release does not start that review.
