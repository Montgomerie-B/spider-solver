# Bounded local-objective lookahead

Research note for GitHub issue #21. Branch `local/two-stage-planning-pilot-pr4`.

Panel freeze: `f8ab18fce4a86730ffc42a020ede4d356621fc17`, parent `8900ceb7d89606d1da205d454850fa7a5c1b92e4`.

Implementation checkpoint: `4e2f8e3ca2f4b750443c782e3c7d5513c2ff814d`. The evaluator and the development tests are in that commit. Reserved boards were not searched before it.

This is a local ranking pilot. It is not a whole-game search, not a result below 172, not a complete-game optimum, and not an admissible bound. `independent_cold_complete` stays false. Deal 4925153 was not loaded. `AGENTS.md`, the rules engine, the search kernel, and `dependency_options.py` were not edited.

## Question and method

Can a small replay-validated lookahead choose a cheaper complete short plan to the same stated objective than the unchanged PR3 selector?

Each board names one column that already has a face-down card. Success is a drop in that column's face-down count. A reveal in another column, a bare join, and an empty column are not success. Every legal tableau action becomes one option. `select_dependency_portfolio(..., limit=len(options))` is the unchanged baseline. Its order is not truncated.

The pilot replays each admitted prefix with `step_cost` and `apply_action`. If the prefix already meets the predicate, the continuation is empty and costs 0, and `run_search` is not called. Otherwise the existing kernel searches from that state. The continuation root's `g` is the replayed prefix cost, so `cost_ceiling=4` is the total from the common source. Declared `source_g` is ignored for that total and is not an opening proof.

The kernel records terminals while it generates children. `first_g` is that generation order, not the minimum. Every returned terminal is replayed. The cheapest replay that meets the predicate and matches `pack_state` is the witness. No `lower_bound_fn` is passed. Bonds, the dependency penalty, and `kernel_lower_bound` are not added to this cost.

| Candidate status | Meaning |
| --- | --- |
| `exact` | `stop_reason=complete`, no depth cap, and a replayed witness. This is the minimum cost inside the 4-move scope |
| `upper-unfinished` | A witness exists and the search stopped on a cap |
| `unknown` | A cap stopped the search before any valid witness |
| `exhausted-no-hit` | The scoped search finished with no witness. Ineligible for this comparison only. Not a proof that the action is globally useless |

If any admitted candidate is `unknown` or `upper-unfinished`, the comparison is `inconclusive` and the choice stays the baseline. An `exhausted-no-hit` candidate is left out of the minimum. It is not treated as infinite. Ties keep the earlier baseline index. `pruned` stays empty. The legal tableau set is returned unchanged.

Budget, fixed in the panel module: `max_unique=20`, `time_limit_s=2.0`, `rss_abort_mb=512`, `cost_ceiling=4`, `max_depth=None`, one worker, `stop_on_first_terminal=False`, `harvest_slack=None`. At most 8 candidate searches per board. Identity is ordered `pack_state`. Successors are `tableau_actions`, including a legal zero-cost move. Deal is not generated there. Every fixture also has one stock card, so `can_deal` is false and Deal is absent from `enumerate_legal_actions`. These are partial synthetic decks, not 104-card deals.

An initial structural empty accepts a move from every other face-up column. That is at least nine legal actions, which cannot fit the cap of eight without dropping a move. The panel therefore has no opening zero-cost candidate. The zero-cost move on the workspace board is a continuation, after `10d` onto `jh` creates the only empty column.

## One-shot invocation

Working directory: the repository root. Interpreter `py -3`. The official pass ran after `4e2f8e3` and before any later edit. It called `compare_panel_board(board)` once per `panel_boards()` entry, with the default budget and no custom limits. Development boards in that same pass matched the development tests. No fixture, weight, or evaluator edit followed the reserved outcomes.

```python
from spider.dependency_objective_panel import panel_boards
from spider.dependency_objective_lookahead import compare_panel_board

for board in panel_boards():
    result = compare_panel_board(board)
```

`tests/test_dependency_objective_reserved_pr4.py` repeats those same limits and locks the reserved statuses, costs, continuations, and unique counts. It is a confirmation, not a second budget. Wall-clock times below are from the official pass. They are not locked. The recorded times are `perf_counter` wall time. Process CPU was not instrumented separately.

Both policies are scored from these same candidate rows. Selector time is `baseline_seconds` only. Kernel time is the sum of the continuation searches. Overhead is the rest of the call. Searches are not charged twice.

## Board summary

| Board | Role | Resolved | Baseline | Baseline cost | Pilot | Pilot cost | Comparison |
| --- | --- | --- | ---: | ---: | --- | ---: | --- |
| `size-1-scarce-receiver` | development | yes | `(0, 2, 1)` | 2 | `(0, 2, 1)` | 2 | tie |
| `size-2-alternative-receiver` | development | yes | `(3, 1, 1)` | 3 | `(0, 2, 1)` | 2 | strict win |
| `blocker-chain` | development | yes | `(3, 4, 1)` | 3 | `(1, 2, 1)` | 2 | strict win |
| `immediate-join` | development | yes | `(0, 1, 2)` | 2 | `(5, 6, 1)` | 1 | strict win |
| `symmetric-tie` | development | yes | `(0, 2, 1)` | 2 | `(0, 2, 1)` | 2 | tie, baseline order kept |
| `distractor-reveal` | reserved | yes | `(5, 6, 1)` | 3 | `(0, 2, 1)` | 2 | strict win |
| `three-deep-uncover` | reserved | yes | `(4, 5, 1)` | 4 | `(0, 2, 1)` | 3 | strict win |
| `zero-cost-workspace` | reserved | no | `(5, 6, 1)` | unknown | `(5, 6, 1)` | unknown | inconclusive, baseline kept |

Fully comparable means every admitted candidate is `exact` or `exhausted-no-hit`, and the chosen costs are exact. Five comparable boards are strict improvements. Two are ties. None is a fully comparable regression. Two of the three reserved boards are fully comparable, and both show a strict improvement on different topologies. The workspace board supplies no measured cost advantage.

## Per-board evidence

Candidate rows stay in baseline order. `index` is that order. Costs are corrected MobilityWare moves. The final pack is the replay of prefix plus continuation.

### `size-1-scarce-receiver` (development)

Preserve the only club receiver, column 1. Target column 0. Stock `ad`.

Source `53504b3101000001010224381300013900012400022d3800010d00011d00012d00013d00010d00011d21`.

Legal set `{(0, 2, 1), (3, 1, 1)}`. Admitted both. Rejected none. Obligations `matched`. `absolute_g_used_for_proof` false.

Wall: baseline 0.006852s, kernel 0.229268s, overhead 0.008588s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(0, 2, 1)` | exact | complete | 1 | `(0, 1, 1)` cost 1 | 2 | 3 | 2 | 2 | 2 | 0.209506 |
| `(3, 1, 1)` | exhausted-no-hit | complete | 1 | none | none | 2 | 2 | 1 | none | 0.019734 |

Final pack for the exact plan: `53504b3101000001000124000239380002241300022d3800010d00011d00012d00013d00010d00011d21`. Column 0 face-down count drops by 1. The spend prefix does not. Spending the only receiver has no reveal of column 0 inside this scope. That is not a claim that the move is illegal.

Pilot `(0, 2, 1)`, same as the baseline, cost 2.

### `size-2-alternative-receiver` (development)

Second `9c` on column 4, so the club join is not critical. Target column 0. Stock `ad`. The legal set includes the third move.

Source `53504b3101000001010224381300013900012400022d3800013900011d00012d00013d00010d00011d21`.

Legal set `{(0, 2, 1), (3, 1, 1), (3, 4, 1)}`. Admitted all three.

Wall: baseline 0.008472s, kernel 0.007807s, overhead 0.013576s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(3, 1, 1)` | exact | complete | 1 | `(0, 2, 1)`, `(0, 4, 1)` | 3 | 5 | 4 | 8 | 3 | 0.002829 |
| `(3, 4, 1)` | exact | complete | 1 | `(0, 2, 1)`, `(0, 1, 1)` | 3 | 5 | 4 | 8 | 3 | 0.002672 |
| `(0, 2, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 6 | 3 | 8 | 2 | 0.002270 |

Both spend plans replay at cost 3 and drop column 0's face-down count. The preserve plan replays at cost 2. Final pack of the cost-2 plan: `53504b3101000001000124000239380002241300022d3800013900011d00012d00013d00010d00011d21`.

Pilot `(0, 2, 1)` at 2. Baseline `(3, 1, 1)` at 3.

### `blocker-chain` (development)

`8c` is covered by `9d`. Clearing that cover reveals column 0 in two moves. The heart join is the competing first move. Target column 0. Stock `2d`.

Source `53504b310100000101010d3701020d382901010d1a01010d1201010d1301010d3501010d2501010d1501010d0501010d1d22`.

Legal set `{(1, 2, 1), (3, 4, 1)}`.

Wall: baseline 0.006566s, kernel 0.005684s, overhead 0.014701s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(3, 4, 1)` | exact | complete | 1 | `(1, 2, 1)`, `(0, 1, 1)` | 3 | 5 | 3 | 4 | 3 | 0.002888 |
| `(1, 2, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 8 | 4 | 8 | 2 | 0.002761 |

Pilot `(1, 2, 1)` at 2. Baseline `(3, 4, 1)` at 3. Final pack of the cost-2 plan: `53504b310100000100010d01020d383701020d1a2901010d1201010d1301010d3501010d2501010d1501010d0501010d1d22`.

### `immediate-join` (development)

Column 5's `8c` joins `9c` and reveals column 5 immediately. The spade run is a longer plan to the same reveal. Target column 5. Stock `2d`.

Source `53504b310100000101020d040301010d0501010d2d01010d3d01010d1d01010d3801010d3901010d1101010d2101010d3122`.

Legal set `{(0, 1, 2), (5, 6, 1)}`.

Wall: baseline 0.006695s, kernel 0.001231s, overhead 0.009217s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel called |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `(0, 1, 2)` | exact | complete | 1 | `(5, 6, 1)` cost 1 | 2 | 2 | 1 | 1 | 2 | yes, 0.001219s |
| `(5, 6, 1)` | exact | prefix-terminal | 1 | empty, cost 0 | 1 | 0 | 0 | 0 | none | no |

Pilot `(5, 6, 1)` at 1. Baseline `(0, 1, 2)` at 2. Final pack of the one-move plan: `53504b310100000101020d040301010d0501010d2d01010d3d01010d1d00010d01020d393801010d1101010d2101010d3122`.

### `symmetric-tie` (development)

`3h` can park on either 4. Both parks then reveal column 0 at the same cost. Target column 0. Stock `2d`.

Source `53504b310100000101020d381301010d3901010d2401010d3601010d0401010d2601010d1601010d0601010d1101010d2122`.

Legal set `{(0, 2, 1), (0, 4, 1)}`.

Wall: baseline 0.006264s, kernel 0.004507s, overhead 0.010305s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(0, 2, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 4 | 2 | 4 | 2 | 0.002780 |
| `(0, 4, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 4 | 2 | 4 | 2 | 0.001697 |

Both totals are 2. The pilot keeps `(0, 2, 1)`, the earlier baseline row. The two final packs differ because the park column differs. Both drop column 0's face-down count.

### `distractor-reveal` (reserved)

The objective is column 0 only. Queen onto the spade king reveals column 5 and adds a bond. Two `9c` landings keep the club join from being a size-1 critical receiver. Stock `2d`.

Source `53504b310100000101020d381301010d3901010d2401010d3901010d3101012d0c01010d0d01010d2101010d1101010d0122`.

Legal set `{(0, 2, 1), (5, 6, 1)}`.

Wall: baseline 0.006422s, kernel 0.005383s, overhead 0.015869s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(5, 6, 1)` | exact | complete | 1 | `(0, 2, 1)`, `(0, 1, 1)` | 3 | 8 | 4 | 10 | 3 | 0.003150 |
| `(0, 2, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 9 | 3 | 9 | 2 | 0.002210 |

The queen prefix reveals column 5 and does not meet the column-0 predicate. Its replayed route to column 0 costs 3. The column-0 plan costs 2. Final pack of that plan: `53504b310100000100010d01020d393801020d241301010d3901010d3101012d0c01010d0d01010d2101010d1101010d0122`.

Pilot `(0, 2, 1)` at 2. Baseline `(5, 6, 1)` at 3. This is a strict reserved improvement, and the other-column reveal is not counted as success.

### `three-deep-uncover` (reserved)

Column 0 is covered by `3h` then `4d`. Uncovering `8c` takes three moves. The diamond queen-king join is the competing bond. The side move `(2, 3, 1)` stays in the legal set. Stock `2d`.

Source `53504b31010000010103273824130101373901013704010137150101372c0101372d0101373101013721010137110101370122`.

Legal set `{(0, 2, 1), (2, 3, 1), (4, 5, 1)}`.

Wall: baseline 0.009900s, kernel 0.015302s, overhead 0.016050s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | `first_g` | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(4, 5, 1)` | exact | complete | 1 | `(0, 2, 1)`, `(0, 3, 1)`, `(0, 1, 1)` | 4 | 8 | 7 | 9 | 4 | 0.005518 |
| `(0, 2, 1)` | exact | complete | 1 | `(0, 3, 1)`, `(0, 1, 1)` | 3 | 15 | 12 | 21 | 3 | 0.006857 |
| `(2, 3, 1)` | exhausted-no-hit | complete | 1 | none | none | 4 | 4 | 6 | none | 0.002875 |

The side move finishes inside the scope with no column-0 reveal, so it is ineligible rather than unknown. The baseline route replays at 4. The uncover route replays at 3. Final pack of the cost-3 plan: `53504b31010000010001270102373938010237041301023715240101372c0101372d0101373101013721010137110101370122`.

Pilot `(0, 2, 1)` at 3. Baseline `(4, 5, 1)` at 4. This is the second strict reserved improvement. The topology is the three-cover uncover, not the distractor.

### `zero-cost-workspace` (reserved)

`10d` onto `jh` creates the only empty column. `kd` then has a legal zero-cost whole-column move onto that empty. The same-suit `6s`-`7s` join is the competing first move. Target column 0. Stock `2c`. No opening action is zero-cost.

Source `53504b310100000101022738130101373900012a0101371b00012d01013706010137070101371d0101373d0101370d32`.

Legal set `{(1, 2, 1), (2, 3, 1), (5, 6, 1)}`. All three prefixes cost 1.

Wall: baseline 0.009317s, kernel 0.009395s, overhead 0.011438s.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost actions seen | Kernel s |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(5, 6, 1)` | unknown | unique limit | 1 | none | none | 20 | 5 | 23 | 2 | 0.004047 |
| `(1, 2, 1)` | exhausted-no-hit | complete | 1 | none | none | 4 | 4 | 8 | 0 | 0.002452 |
| `(2, 3, 1)` | unknown | unique limit | 1 | none | none | 20 | 2 | 20 | 2 | 0.002858 |

No candidate produced an objective witness. The two unique-limit rows did see zero-cost successors, and those counts are not a certificate. The comparison is inconclusive. The pilot keeps the baseline `(5, 6, 1)`. There is no measured win and no measured loss. The legal set is unchanged.

A separate development fixture, not this board, replays a zero-cost whole-column move at corrected cost 0. After that move a face-down reveal predicate on another column is still false. On that fixture the kernel's `first_g` is 1 while the retained continuation cost is 0, and the search status is `exact`. The retained witness is the replayed minimum, not the first generated terminal.

## Controls that the verdict uses

- Size-1 still selects the sole receiver. The spend is exhausted inside the scope, not chosen.
- Size-2 selects the verified 2-move plan. The baseline's 3-move plan, and the third legal move's 3-move plan, both replay at 3.
- The immediate join is prefix-terminal at cost 1 and beats the cost-2 plan.
- The tie keeps baseline order.
- The reserved distractor is fully comparable. The other-column reveal is the baseline and costs 3 to the real target. The pilot pays 2.
- The reserved three-deep board is fully comparable and improves 4 to 3. Its side move is an exhausted miss, not an unknown.
- The reserved zero-cost board does not invent a cost. It falls back to the baseline because two candidates are unknown.
- Forged `target_bonds`, a foreign source pack, and stale obligations are refused before search. A mix that still has one valid option searches only that option. Legal moves stay available.
- Building the size-2 options at `source_g=5`, with `target_g` and `f_target` shifted consistently, selects the same action and the same local totals as `source_g=0`. `absolute_g_used_for_proof` stays false.
- `SearchLimits(max_unique=1)` on the tie board, only as a mechanism test, returns `unknown` for both candidates and keeps the baseline. That tighter cap was not used on the panel.
- `dependency_options.py` still has no `8c`, `9c`, `run_search`, or `discover_macros`. The lookahead module calls `run_search` and does not name those fixture cards, `kernel_lower_bound`, or `pack_post_stock_symmetry_state`.

## Tests

PR1–PR3, unchanged: `tests/test_dependency_options_two_stage.py`, `tests/test_dependency_options_offline_audit_pr2.py`, and `tests/test_dependency_contract_continuity_pr3.py`. Together with the panel test and the development lookahead test: 39 passed in 7.13 seconds before the implementation commit's reserved lock existed. The 25 PR1–PR3 tests are inside that 39. The reserved lock then passed alone in 1.97 seconds and matched the one-shot.

The maintained regression is the v0.123 file list plus the v0.124, v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, v0.137, v0.138, and v0.139 files, plus the PR1, PR2, and PR3 files (48 files), plus the three PR4 files. Invocation: `py -3 -m pytest` on those 51 files, `-q --tb=line`, from the repository root. One worker. Result: 703 passed, 0 failed, in 281.24 seconds. Bare `pytest tests` was not used. This selection is not a universally green full suite.

`tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. It was not edited. It can still return `PLANNING_STALL` instead of `TIME_LIMIT` (issue #6). That assertion was not weakened.

Collection of these eight modules is separate and was not treated as part of the green selection:

- `tests/test_exact_state_policy_context_equivalence_v0_1.py`
- `tests/test_one_shot_natural_empty_service_v0_1.py`
- `tests/test_one_shot_natural_r3_service_v0_1.py`
- `tests/test_workspace_opportunity_service_lane_v0_1.py`
- `tests/test_workspace_service_generalisation_panel_v0_1.py`
- `tests/test_workspace_service_lag1_grace_v0_1.py`
- `tests/test_workspace_service_stock_guard_v0_1.py`
- `tests/test_workspace_service_stock_synchronous_v0_1.py`

With `PYTHONPATH=src`, collection of those eight files reported 8 errors in 10.08 seconds. The tests were not edited. The missing modules remain the ones named in the PR3 note: `common_priority_schema_ab_v0_1`, `one_shot_natural_empty_service_v0_1`, `one_shot_natural_r3_service_v0_1`, and `workspace_opportunity_service_lane_v0_1`.

## Limitations

- The panel is a self-held-out engineering set. It is not a blinded independent validation.
- Every state is a partial deck with one stock card. None is deal 4925153 and none is a 104-card deal.
- An opening zero-cost move cannot be added without exceeding eight legal candidates. The workspace zero-cost move is a continuation, and inside `max_unique=20` that continuation search did not record an objective witness.
- `exhausted-no-hit` means no objective inside four corrected moves of that prefix. It is not global impossibility.
- The same objective costs score both choices. This does not isolate dependency semantics from plain cost search.
- No full-game lower bound was used. A pass here does not tighten `h` or `f`.
- Caps were not raised after the reserved pass. Unknowns were not ranked as infinity.
- Wall time is reported. CPU time was not split out.
- Nothing was proof-pruned. The recommendation does not remove a legal move.

## Verdict

**PILOT_PASS.**

Size-1 still preserves its receiver. Size-2 replaces the baseline 3-move reveal with the verified 2-move reveal. Two reserved boards are fully comparable, on different topologies, and both improve by one corrected move. No fully comparable board gets worse. The tie, the immediate join, the other-column reveal, and the zero-cost fallback behave as specified. The workspace board is the held-out unknown, and it keeps the baseline.

## Recommendation

Keep the lookahead as a research-only local ranking signal on this synthetic panel, and stop. Do not connect it to a production controller, raise `max_unique`, persist a frontier, or open a whole-game search from this pass.
