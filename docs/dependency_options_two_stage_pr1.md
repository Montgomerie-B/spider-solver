# Dependency options, two-stage pilot

Research note for GitHub issue #18. Parent commit `a716aadee1ae1d9c4e484a00715d98433a6f6227`. Branch `local/dependency-options-two-stage-pr1`. This is not a 171 game, not a search of deal 4925153, and not a change to production play.

## What was added

`src/spider/dependency_options.py` builds a tactical option by replaying engine primitives. `rebuild_obligations` regenerates the graph from the current state. `build_option` sums `step_cost`, checks that `apply_action` returns the same cost, and derives `enables`, `blocks`, and `dependency_penalty` from the source graph and the replayed target. `select_dependency_portfolio` keeps a preserver ahead of a breaker only while a receiver OR-group has size 1. `kernel_lower_bound(state, g)` returns `admissible_remaining(state)` and does not read `g` or the penalty.

The rules engine, search kernel, Human Strategy Controller, purposeful-macro portfolio, and both solution files are unchanged. `FrontierCheckpoint` is not implemented. `independent_cold_complete` stays false.

## Fixture result

The synthetic board is the corrected one: column 3 face-up is `kd`, `8c`, with no face-down card. Spending the club leaves the king, so the column does not become empty.

On the one-receiver board, `tableau_actions` is `{(0, 2, 1), (3, 1, 1)}`, each at corrected cost 1. The portfolio selects `preserve-receiver` `(0, 2, 1)` first. That option enables `join:c:8:col0` and `reveal:col0:depth0`, blocks nothing, and has penalty 0, even though its `target_bonds` is 0 and the competing option's `target_bonds` is 1. The join `(0, 1, 1)` is replayed by the test after the option. It is not stored on the option. Combined corrected cost is 2. The position still has `(2, 0, 1)`.

`spend-only-receiver` `(3, 1, 1)` adds one bond and leaves no empty column. `broken_dependencies` and `blocks` are `join:c:8:col0` and `reveal:col0:depth0`. The satisfied `join:c:8:col3` is not blocked. The penalty is 4, from 2 broken obligations, 0 unrecovered empties, and 2 lost receivers. It is a sort key. `h_target` does not include it. After that spend, `(0, 2, 1)` is still legal and costs 1. After the spend and then `(0, 2, 1)`, `tableau_actions` is empty, and both `(0, 1, 1)` and `(0, 3, 1)` are illegal.

On the two-receiver board, column 4 is a second `9c`. Source actions are `{(0, 2, 1), (3, 1, 1), (3, 4, 1)}`. `(3, 4, 1)` stays legal and is not one of the two constructed options. Spending the first `9c` leaves the second, so the penalty is 0 and nothing is blocked. The portfolio then selects `spend-only-receiver` first because `target_bonds` is 1 against 0. After the spend and the blocker, `(0, 4, 1)` still reveals. The three-action corrected cost is 3.

Both `run_search` calls use `identity_fn=pack_state`, `store_fn=pack_state`, root `g` 0, `max_unique` 20, `time_limit_s` 2.0, and `proof_ceiling` 50. The first recorded action set is the size-1 pair. The size-2 call records all three legal moves. `prefer_option_actions` only reorders a move that is already legal.

## Tests

`tests/test_dependency_options_two_stage.py`: 4 passed in 0.83 seconds.

The maintained regression is the v0.123 file list plus the v0.124, v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, v0.137, v0.138, and v0.139 files, plus this pilot: 46 files, 667 passed, 0 failed, in 242.19 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT`. It was not changed.

Collection of these eight modules still fails on missing `*_v0_1` imports: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. They were not edited. Bare `pytest tests` was not used as the regression.

## What this does not show

A green pilot shows the contract on this fixture. It does not show a shorter game than 172, and it does not score the eight recorded roots. Deal 4925153 was not searched. Caps were not raised. The branch is not merged to `main`.
