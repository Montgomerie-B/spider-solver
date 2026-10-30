# Dependency contract continuity

Research note for GitHub issue #20. Parent commit `4105559fabf8a3ef74f0ce3f79a755cfc79e233e`. Branch `local/dependency-contract-continuity-pr3`. This is a semantic check on tactical options. It is not a search of deal 4925153, not a two-stage lookahead, and not a persisted frontier.

## What changed

`select_dependency_portfolio` still reserves a unique JOIN or REVEAL receiver, then fills by the existing source signature. The rank key is unchanged: lower corrected cost, lower `dependency_penalty`, higher `target_bonds`, then pack and id. `source_g` is not in that key. `kernel_lower_bound(state, g)` still returns `admissible_remaining(state)`. It does not read `g` or the penalty. `prefer_option_actions` still only reorders an action that is already legal. `tableau_actions` is unchanged.

Admission now replays the claimed source and recomputes the selector fields from that replay: `target_bonds`, `broken_dependencies`, `blocks`, `enables`, `outstanding_obligations`, `unresolved_dependencies`, and `dependency_penalty`, plus the PR2 checks on target pack, corrected cost, `target_g == source_g + cost`, admissible `h_target`, and `f_target = target_g + h_target`. A stored field that disagrees is dropped before ranking. The penalty is `len(broken) + net empties spent + lost receivers`, counted from the replayed states. It is still not added to `h` or `f`.

`source_g` on an option is only a declared base. The option record itself stays `source_g_provenance="unestablished"`. A value of `opening_verified` written onto the option is rejected. Absolute `g` is reported on the portfolio, and `absolute_g_used_for_proof` stays false.

| Portfolio `source_g_provenance` | When |
| --- | --- |
| `unestablished` | No source-cost claim supports every admitted option, and no ancestor checkpoint was verified |
| `checkpoint_relative` | `verify_ancestor_claim` reached the source. That check does not read corrected cost |
| `opening_verified` | Every admitted option has a `SourceCostClaim` whose replay from a caller-trusted `g=0` pack sums to that option's `source_g` |

An empty source-cost continuation is valid only for `source_g == 0` on that same pack. A failed claim increments `rejected_source_cost_claims` and does not drop a relatively consistent option.

JOIN continuity follows the replayed action path by face-up index. A span that moves as a whole keeps its cards. Suit and rank are not used to find another physical copy. An intact span in a new column is not a break while the span still has a legal receiver. The rebuilt graph may still emit a column-specific id for the current state. A split, a merge into a longer span, a foundation removal, or a span whose cards are no longer at the path index is `unresolved`: it is not broken, not blocked, and not enabled.

One PR2 assertion was repaired. `test_moving_an_interval_changes_its_column_bound_join_id` had locked the false break `join:c:8:col0` after the zero-cost park. The id still leaves column 0, and `(2, 1, 1)` is still legal. The source JOIN is no longer reported broken, and the penalty is 0. The other PR1 and PR2 assertions were not changed.

The rules engine, search kernel, Human Strategy Controller, purposeful-macro discovery, both solution files, and the incumbent are unchanged. `FrontierCheckpoint` is not implemented. `independent_cold_complete` stays false. `AGENTS.md` is unchanged.

## Verified actions and costs

On the size-1 board, `tableau_actions` is still `{(0, 2, 1), (3, 1, 1)}`.

| Option | Action | Cost | Bonds | Penalty | Broken | Unresolved |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `preserve-receiver` | `(0, 2, 1)` | 1 | 0 | 0 | none | none |
| `spend-only-receiver` | `(3, 1, 1)` | 1 | 1 | 4 | `join:c:8:col0`, `reveal:col0:depth0` | `join:c:8:col3`, `join:c:9:col1` |

With declared `source_g` 0 the spend option measures `target_g` 1, `h_target` 8, and `f_target` 9. The preserve option enables `join:c:8:col0` and `reveal:col0:depth0`. The portfolio still selects the preserver first. The merged club that landed on the only `9c`, and that `9c` itself, are unresolved. They are not enables and they are not breaks. `join:c:8:col3` stays out of `blocks`.

On the size-2 board the second `9c` remains. Spending `(3, 1, 1)` has penalty 0 and does not break `join:c:8:col0`. The portfolio still selects that spend first, at cost 1 and `target_bonds` 1. The existing measurement is unchanged: preserve then `(0, 1, 1)` costs 2, and spend then `(0, 2, 1)` then `(0, 4, 1)` costs 3. Those later costs are not a penalty and are not passed to `kernel_lower_bound`. `(3, 4, 1)` stays in `tableau_actions` and is not injected into either option.

The zero-cost park moves the whole `8c` from column 0 onto empty column 2. Corrected cost is 0, `target_g` is 0, and the penalty is 0. `join:c:8:col0` is absent from broken, blocks, and unresolved. The current graph contains `join:c:8:col2`. `(2, 1, 1)` remains legal.

The held-out board uses diamonds and different columns. `(5, 3, 1)` moves `6d` onto an empty column at cost 0. `join:d:6:col5` is not broken and not unresolved. The current id is `join:d:6:col3`. `(3, 8, 1)` onto the `7d` remains legal. The penalty is 0.

The duplicate board has an `8c` on column 0, a longer `9c 8c` on column 1, another `8c` on column 3, and a free `9c` on column 4. Moving only the column-0 copy onto empty column 2 costs 0. Neither `join:c:8:col0` nor `join:c:8:col3` is broken, unresolved, or enabled. The longer run stays on column 1. After the move, `join:c:8:col2` and `join:c:8:col3` are distinct, and both `(2, 4, 1)` and `(3, 4, 1)` are legal. The longer same-suit run is not treated as the moved card.

## Forged fields

Each of these replacements is rejected by itself: `enables`, `blocks`, `broken_dependencies`, `dependency_penalty`, `target_bonds`, `outstanding_obligations`, `unresolved_dependencies`, and `source_g_provenance="opening_verified"`. A spend option rewritten to enable `join:c:8:col0` and `reveal:col0:depth0`, with empty blocks, empty broken ids, penalty 0, and `target_bonds` 99, is not admitted. The portfolio of that forgery plus the real preserver contains only `preserve-receiver`. The legal move set stays `{(0, 2, 1), (3, 1, 1)}`.

## Absolute g

Adding 5 to `source_g`, `target_g`, and `f_target` on the real preserver keeps `target_g - source_g == 1` and the same source pack. Admission accepts it. The size-1 order is unchanged, with the shifted preserver still first. Portfolio provenance stays `unestablished`. A source-cost claim that the same pack has `source_g` 5 fails, because the empty continuation replays at cost 0. The shifted option stays admitted, `rejected_source_cost_claims` is 1, and absolute `g` is not used as a proof.

A claim with empty continuation and `source_g` 0 on the synthetic opening is `opening_verified`. The option's own `source_g_provenance` remains `unestablished`. `absolute_g_used_for_proof` is false, and `ancestor_status` stays `not_established`.

After `(0, 2, 1)`, the next action `(0, 1, 1)` costs 1. Built with `source_g` 1, `target_g` is 2. An ancestor claim for that path is `one_verified` and only `checkpoint_relative`. The same path as a source-cost claim with `source_g` 1 is `opening_verified`, and that status is still not a proof input. Replacing the declared base with 6, and shifting `target_g` and `f_target` by 5, stays admitted. The cost claim for 6 is rejected. Provenance remains `checkpoint_relative` because the ancestor replay still matches the pack.

## Unresolved cases

These source ids were followed far enough to refuse both a break and an enable:

- `join:c:8:col3` and `join:c:9:col1` after `(3, 1, 1)` on the size-1 board. The club from column 3 is inside the longer `9c 8c` span. That is a merge, not a destroyed receiver. The column-0 club and its reveal are the real breaks.
- `join:s:9:col0` after moving only the top card of `9s 8s` onto `9h`, action `(0, 1, 1)`, cost 1. The source interval is split.
- `join:c:13:col0` and `join:c:1:col1` after `(1, 0, 1)` completes the club sequence. Corrected cost is 1, one foundation is removed, and the penalty is 0. Removal is not a lost receiver.

No unresolved id was promoted to an enable. Duplicate suit and rank, where the path still has one index, stay resolved. The module does not contain the fixture tokens `8c` or `9c`.

## Tests

`tests/test_dependency_options_two_stage.py`, `tests/test_dependency_options_offline_audit_pr2.py`, and `tests/test_dependency_contract_continuity_pr3.py`: 25 passed in 2.44 seconds. The four PR1 tests were not edited. One PR2 assertion was repaired, as recorded above.

The maintained regression is the v0.123 file list plus the v0.124, v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, v0.137, v0.138, and v0.139 files, plus the PR1, PR2, and PR3 files: 48 files, 688 passed, 0 failed, in 232.70 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT`. It was not changed.

Collection of these eight modules still fails: 8 errors in 1.87 seconds with `PYTHONPATH=src`. The missing modules are `common_priority_schema_ab_v0_1`, `one_shot_natural_empty_service_v0_1`, `one_shot_natural_r3_service_v0_1`, and `workspace_opportunity_service_lane_v0_1`. The tests were not edited. Bare `pytest tests` was not used as the regression.

- `tests/test_exact_state_policy_context_equivalence_v0_1.py`
- `tests/test_one_shot_natural_empty_service_v0_1.py`
- `tests/test_one_shot_natural_r3_service_v0_1.py`
- `tests/test_workspace_opportunity_service_lane_v0_1.py`
- `tests/test_workspace_service_generalisation_panel_v0_1.py`
- `tests/test_workspace_service_lag1_grace_v0_1.py`
- `tests/test_workspace_service_stock_guard_v0_1.py`
- `tests/test_workspace_service_stock_synchronous_v0_1.py`

## Recommendation

Do not start two-stage lookahead, frontier persistence, or a new whole-game search from this result.

Admission can now reject a forged enable, block, penalty, or bond score, and an intact relocation is no longer called a destroyed JOIN. That makes the existing rank key trustworthy on these fixtures. It does not make a second-stage cost admissible. The size-2 selector still spends a cost-1 bond while the verified preserve-then-reveal line costs 2 and the spend-then-reveal line costs 3. A later comparison of those objective costs has to stay a ranking signal. It must not be added to `h`, `f`, or `kernel_lower_bound`.

## What this does not show

The fixtures do not show a shorter game than 172, and they do not show that 172 or 185 is optimal. `independent_cold_complete` stays false. Deal 4925153 was not searched. Caps were not raised. No PR4 was started. The branch is not merged to `main`.
