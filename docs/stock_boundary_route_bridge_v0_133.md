# Stock-boundary route bridge v0.133

Schema `spider-stock-boundary-route-bridge-0.133`. Deal `4925153`. Branch `local/stock-boundary-route-bridge-v0-133`, started from v0.132 `1cc4378dd5ccd169bb13e9868721b7e4e6febc42`.

One question. The verified early fifth deal spends corrected cost 142 and has admissible remainder 24. The known winning route spends 150 at the same deal and then 22 more moves. This experiment asks whether the early tableau can rejoin any later checkpoint on that winning route, under post-stock column symmetry, and finish the deal in 171 or fewer corrected MobilityWare moves. It is one bounded bridge. It is not a new solver.

## Result

The bridge stopped on the 45-second limit. It retained 3,317 identities, expanded 2,765 nodes, and generated 129,336 children. Admissible pruning rejected 107,775 arrivals. No retained state matched any canonical checkpoint from 152 through 174, either as the same physical tableau or as a whole-column permutation. Foundations reached 3. The best `g + h` stayed 166, which is the score of the start position. No remapped suffix was replayed, and no complete game was submitted to `verify_complete_solution`. The outcome is inconclusive. The early position's `f = 166` is not a judgement that the deal finishes below or above 172.

The canonical post-SD5 search was not run. Its 80,000-state and 90-second budgets were not increased. No workspace macro-actions were added. Both solution files are unchanged.

## 1. Verified controls

Both published routes were replayed before the probe and hashed again after it.

| Route | Actions | Corrected MW | Foundations | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | 174 | 172 | 8 | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` |
| `solutions/4925153_autonomous_185.moves` | 189 | 185 | 8 | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` |

`independent_cold_complete` stays false. This run does not establish cold provenance for the 185 route.

The canonical fifth deal is action 151. Checkpoint 140, the state after the first diamond foundation, has `g = 139`, 10 stock cards, and two empty columns. Checkpoint 152, immediately after the fifth deal on the published route, has `g = 150`, `h = 18`, an empty stock, and a 22-action suffix. That suffix costs 22, contains no further deal, and finishes all eight foundations.

The named preparation from checkpoint 140 is `move 2 5 1`, `move 3 1 2`, `move 9 2 1`, then the real fifth deal. The first of those is a zero-cost whole-column transfer. The replay reaches `g = 142`, `h = 24`, `f = 166`, four same-suit landings, three face-down cards, 48 same-suit bonds, and two foundations. The landing kinds are same-suit, same-suit, non-connecting, non-connecting, non-connecting, same-suit, non-connecting, non-connecting, same-suit, non-connecting. The post-stock symmetry key of this tableau is not the key of any checkpoint from 152 through 174, so the search had to move.

A deterministic transposition of checkpoint 152 was remapped with `column_permutation_mapping` and `remap_tableau_action`. The remapped 22-move suffix replays, costs 22, and solves. The same actions with the original column indexes do not solve that transposed tableau. A change of foundations is rejected. While stock remains, a column swap is a different state, and the lookup does not call `pack_post_stock_symmetry_state`.

## 2. Rejoin and search limits

Checkpoints 152 through 174, all 23 of them, are rejoin targets. After the stock is empty, a candidate matches a target when `pack_post_stock_symmetry_state` agrees. That key includes foundations. The column map runs from the canonical tableau to the candidate, and every remaining reference action is rewritten. The suffix is then replayed on the candidate. A deal left in the suffix is rejected. While stock remains, only `pack_state` can match, because a future deal still addresses physical columns.

The projected full cost is `172 - (g_ref - g_candidate)`. It exists only when the candidate is strictly cheaper than that checkpoint. Equality is not a saving. A projected cost above 171 is not accepted. The composed route would be the canonical prefix through checkpoint 140, the named preparation, the bridge actions in physical coordinates, and the remapped suffix. `verify_complete_solution` would have to accept that whole deal at the projected cost. This probe never produced a candidate for that check.

Ordering reuses `target_displacement` on seven checkpoints: the first of each foundation count, which are 152, 160, 170, 171, 172, 173, and 174. The two lanes are the v0.129 pair, `(displacement, g)` and `(g, displacement)`. A state worse than the best displacement seen so far leaves the cost lane and stays on the goal lane. Displacement does not delete a state. Empty-column count is not a lane term.

Action order keeps every legal move, including a deal if the engine still allows one. Lower is earlier: corrected step cost, then a reveal of a face-down card, then a same-suit continuation. A move onto an empty column is not preferred. The existing `strategic_action_order` ranks that park ahead of other non-joins, so this bridge does not call it. Zero-cost whole-column transfers stay legal; their cost of 0 is the cost key, not an empty-column bonus.

The proof bound is `admissible_remaining`. The kernel rejects a child only when `g + h > 171`. Equality stays eligible. `incumbent.proof_prune` rejects equality and was not used. Identity is `pack_whole_game_identity`. Stored paths use `pack_state`, so a reconstructed bridge keeps real column indexes.

At the root, `h = 24`. A successor that does not reduce that remainder is proof-dead once `g` reaches 148, because `148 + 24 = 172`. That is the admissible rule. It is not a guess about how the deal ends.

Resource cap for the single run: 20,000 retained identities, 45 seconds, 512 MB, one worker. The focused tests do not run this search.

## 3. Probe

| | |
| --- | ---: |
| Stop | time limit |
| Elapsed | 45.037 s |
| Retained identities | 3,317 |
| Stored nodes | 3,392 |
| Expanded | 2,765 |
| Generated | 129,336 |
| Duplicate skips | 18,170 |
| Stale skips | 49 |
| Ceiling prunes | 0 |
| Lower-bound prune events | 107,775 |
| Proof-prune identities | 78,284 |
| Unretained proof identities | 76,945 |
| Lower-bound calls | 111,167 |
| Zero-cost actions considered | 7,233 |
| Minimum `f` | 166 |
| Minimum `h` | 12 |
| Maximum `h` | 27 |
| Maximum foundations | 3 |
| Reference checkpoint matches | 0 |
| Physical matches | 0 |
| Symmetry-only matches | 0 |
| Rejected non-improving matches | 0 |
| Improving rejoin attempts | 0 |
| Remap failures | 0 |
| Replay failures | 0 |
| Terminal hits | 0 |
| Peak RSS | 47.3 MB |
| Displacement time | 1.789 s across 3,392 calls |
| Goal-lane expansions | 2,751 |
| Cost-lane expansions | 14 |

Expansion by corrected cost ran from `g = 142` through `g = 159` and stopped there. The busiest layers were `g = 151` to `g = 153` (373, 389, and 376 expansions). A state at `g = 159` with `h = 12` has `f = 171` and remains eligible. No retained state had a smaller remainder, so the next paid step was above the ceiling whenever `h` stayed 12. Minimum `f` never moved below the root's 166. Some states did reduce `h`, from 24 down to 12, after spending the difference. That is why the bound did not freeze the search at `g = 147`, and also why `f` did not improve.

Displacement scoring took 1.8 seconds, about 4% of the limit. It did not dominate the run. The caps were left where they were. The goal lane did almost all of the expansion. Most states were farther from the seven physical targets than the closest state already seen, so they stayed on the goal lane only. They were still generated and still checked against the symmetry index. The index recorded no hit. The search did not reach a hidden permutation and then fail to notice it.

`f = 166` remains the starting bound. A missed rejoin inside a time limit does not make the early deal worse than the published 172, and it does not make it better.

## 4. What was preserved

Corrected MobilityWare scoring is unchanged, including a zero-cost move of a whole face-up column onto an empty column when the source has no face-down cards. Unrestricted dealing into an empty column is unchanged. Packing formats, the search kernel, `engine.py`, `rules.py`, and the Human Strategy Controller were not edited. The v0.120 timing test was not weakened. Historical reports were not rewritten. No incumbent registry or solution file was written. The probe artifact is `artifacts/stock_boundary_v0_133/results.json`, which is gitignored.

## 5. Tests

`tests/test_stock_boundary_route_bridge_v0_133.py`: 10 passed in 0.60 seconds. The file locks the early candidate and the 22-cost suffix, identity and transposed remaps, rejection of an unmapped suffix, foundation mismatch, stock-bearing physical identity, the cheaper-`g` rule, strict proof pruning with equality kept, the unique cap, a solved root that does not search, action order without an empty-column preference, and the driver's refusal to call the old post-SD5 search.

The maintained regression is the file list in `docs/global_search_architecture_v0_124.md`, plus the v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, and v0.133 files. One run with `PYTHONPATH=src` collected those 39 files. All 596 tests passed in 216.44 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run, so it observed `TIME_LIMIT`. It can still return `PLANNING_STALL` in another full-suite run, and that sensitivity is not retired.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

## 6. Next decision

This bounded bridge did not reconnect the early fifth-deal tableau to a later checkpoint on the 172 route. The next separate decision is whether purposeful workspace macro-actions and longer-horizon strategic planning are required. Those were not implemented here. A larger unique cap, a longer clock, another search from the canonical `g = 150` position, and another general solver are not the follow-up from this result.
