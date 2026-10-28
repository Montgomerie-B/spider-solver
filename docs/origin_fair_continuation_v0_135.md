# Origin-fair continuation v0.135

Schema `spider-origin-fair-continuation-0.135`. Deal `4925153`. Branch `local/origin-fair-continuation-v0-135`, started from v0.134 `1c7f3dfc008f90ccc712b6dbf4293204660c31e2`.

One question. On the same eight purposeful post-deal roots, and inside the same 20,000-state, 45-second, 512 MB budget, does a goal lane and a cost lane for each root give every viable root a real share of the search? A balanced share is not a cheaper game. A complete route is accepted only when the original deal replays at 171 or fewer corrected moves with eight foundations.

## Result

The continuation is inconclusive. It is a paired comparison with v0.134. Discovery used the unchanged generator and the same six-second cap. This run retained 3,344 identities and stopped on the clock; scoring the shortlist took 0.113 seconds, so the wall clock was 6.119 seconds. The eight committed roots matched `artifacts/purposeful_macro_v0_134/results.json` in order, actions, `g`, `h`, `f`, physical pack, and symmetry. The v0.134 continuation was not rerun. Its recorded search is the baseline for these same roots.

The fair search ran once. It stopped at 45.022 seconds with 5,695 retained identities, 3,318 expansions, and 121,948 generated children. Admissible pruning rejected 101,111 arrivals. No state matched a canonical checkpoint from 152 through 174. Foundations reached 3. Minimum `f` stayed 166. Minimum `h` was 12. No complete game was accepted.

Every admitted root stayed live and received a few hundred expansions:

| Origin | g | h | f | v0.134 expansions | v0.135 expansions | v0.135 goal | v0.135 cost | Status |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 142 | 24 | 166 | 1 | 415 | 403 | 12 | live |
| 1 | 143 | 24 | 167 | 1 | 408 | 404 | 4 | live |
| 2 | 144 | 24 | 168 | 0 | 407 | 395 | 12 | live |
| 3 | 144 | 25 | 169 | 0 | 409 | 392 | 17 | live |
| 4 | 144 | 25 | 169 | 0 | 408 | 399 | 9 | live |
| 5 | 143 | 25 | 168 | 0 | 450 | 406 | 44 | live |
| 6 | 143 | 24 | 167 | 0 | 413 | 406 | 7 | live |
| 7 | 144 | 24 | 168 | 2,190 | 408 | 399 | 9 | live |

The smallest share is 407 and the largest is 450. In v0.134, origin 7 took 2,190 of 2,192 expansions and origins 2 through 6 took none. That split is gone. None of these eight roots was symmetry-dominated, proof-dead at admission, or left with an empty frontier. Zero expansions here would have been reported as dominance or no viable frontier. It did not occur.

The shared transposition table still discarded the more expensive arrival. There were 23 cross-origin improvements to a best `g`. Those paths were not put back onto a lane to equalise the counts. The winning physical parent keeps the origin, and a dominated portfolio root is omitted before search. This portfolio had no such omission.

Goal lanes expanded 3,204 nodes and cost lanes 114. Within each root the v0.133 keys are unchanged: goal order is `(displacement, g)`, and the cost lane keeps `(g, displacement)` only when the displacement ties or improves that root's own nearest. The nearest record is per origin, so one root's close tableau does not switch off the other roots' cost lanes. The goal lanes are where the coverage comes from. The cost lanes remain the small exact-cost side of the same rule. Empty lanes do not expand a node. A node that sits on both of its origin's lanes is expanded once; this run recorded 186 stale pops.

Depth moved less far than the single-lineage v0.134 search. Expansions reached `g = 159` once. The earlier run, which stayed inside origin 7, reached `g = 160` and `h = 11`. This run's minimum `h` is 12. Wider coverage at the same cap is a shallower look along each root. It is not evidence that any of these tableaux can or cannot rejoin.

| | v0.134 continuation | v0.135 continuation |
| --- | ---: | ---: |
| Roots | the same eight | the same eight |
| Stop | time limit | time limit |
| Elapsed seconds | 45.036 | 45.022 |
| Retained identities | 3,182 | 5,695 |
| Expansions | 2,192 | 3,318 |
| Generated | 124,294 | 121,948 |
| Proof prunes | 104,769 | 101,111 |
| Goal / cost expansions | 2,180 / 12 | 3,204 / 114 |
| Maximum foundations | 3 | 3 |
| Minimum `f` | 166 | 166 |
| Reference matches | 0 | 0 |
| Accepted game | no | no |

Peak RSS was 57.305 MB. Displacement scoring took 2.909 seconds across 5,825 calls. Zero-cost actions considered: 5,043. Ceiling prunes: 0. Duplicate skips: 15,020. Proof-prune identities: 81,068, of which 79,651 were never retained. `independent_cold_complete` is false.

Caps were not raised. The canonical post-SD5 search was not repeated. Its 80,000-state and 90-second budgets were not used. No v0.136 work was started. Both solution files are unchanged.

## 1. Scheduling change

`run_search` takes an optional `origin_lane_keys_fn(state, g, origin)`. The origin is the `SearchNode.origin` already stored for that node and copied onto its children. When the hook is omitted, lane selection is the previous one: the same `lane_keys_fn` or `lane_key_fns`, the same default cost lane, and the same round-robin. Existing callers were not switched over.

The v0.135 adapter registers sixteen lanes: `0.goal` through `7.goal`, then `0.cost` through `7.cost`. The kernel's existing round-robin visits every goal lane before any cost lane, then repeats. One non-empty lane per origin is the fairness mechanism. An empty or exhausted lane consumes a turn and does not consume an expansion. There is no hard quota and no second search.

One `best_g` map, one 20,000-identity cap, one 45-second deadline, and one 512 MB cap remain global. Proof rejection is still strict `g + h > 171`, and it still happens before a unique slot is taken. Equality stays eligible. `incumbent.proof_prune` is not used. Corrected `step_cost` is unchanged, including a zero-cost whole-column transfer. Target displacement, empty columns, landings, and purpose are ordering only.

Identity, action order, rejoin, remapping, and full-game acceptance are the v0.133 public helpers used by v0.134: `pack_whole_game_identity`, `bridge_action_order`, `matching_stops`, `replay_remapped_suffix`, `projected_full_cost`, and `accept_cost`. The macro prefix is the macro of the kernel origin. Survivors of symmetry deduplication keep caller order, so a dropped root does not shift another root onto the wrong macro. The v0.134 generator, `discover_macros`, and `select_portfolio` were not edited.

## 2. What was preserved

| File | Explicit moves | Corrected MW | Foundations | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | 174 | 172 | 8 | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` |
| `solutions/4925153_autonomous_185.moves` | 189 | 185 | 8 | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` |

The artifact is `artifacts/origin_fair_v0_135/results.json`. It is gitignored. It is not an incumbent. No route was composed, and `verify_complete_solution` was not given a candidate.

## 3. Tests

`tests/test_origin_fair_continuation_v0_135.py`: 14 passed in 0.42 seconds. The file locks the opt-in hook, legacy lane results when the hook is absent, the v0.133 cost-key rule, one expansion when a node sits on two lanes, caller indexes after admission sorting, three viable roots against a shared lane that spends the cap on one lineage, cross-origin better-`g` replay, omission of a symmetry-dominated root, a proof-dead root labelled as having no viable frontier, a zero-cost completion on the matching origin, a remapped suffix on the rejoining origin, last-slot admission, strict proof pruning, and the driver's refusal to call the old continuation or raise the caps. These tests do not run the 4,000-state discovery or the 20,000-state continuation.

The maintained regression is in section 4.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

## 4. Maintained regression

The maintained regression is the file list in `docs/global_search_architecture_v0_124.md`, plus the v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, and v0.135 files. One run with `PYTHONPATH=src` collected those 41 files. 622 tests passed and 1 failed in 218.72 seconds. The failure is `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`, which observed `PLANNING_STALL` instead of `TIME_LIMIT`. The assertion was not weakened. The other maintained tests passed, including the 14 new v0.135 tests. This sensitivity is not retired. The v0.134 regression recorded the same failure, with 608 passed and 1 failed.

## 5. Next recommendation

Extend the purposeful macro past fifth-deal reception, toward one concrete post-deal objective such as the next foundation or a specific buried receiver. Each of these eight roots already had a few hundred expansions under the existing cap, all eight were still live, and minimum `f` stayed 166. Another scheduler, a larger unique cap, a longer clock, and another undirected post-deal search are not the follow-up from this result.
