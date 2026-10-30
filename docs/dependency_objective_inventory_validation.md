# Inventory validation of the frozen lookahead

Research note for GitHub issue #22. Branch `local/lookahead-inventory-validation`.

Evaluator and abstract panel remain at parent `1a56107c834b1139b3fefb601558fcbd045366fb`. Inventory inputs were frozen at `7b6a051d238e37888f4a0a1cbfe2ba48a2c7fb4c` before the one-shot below. No source, budget, or evaluator edit followed that run.

This is one bounded check of six constructed full-deck positions. It is an inventory-valid replication attempt. It is not opening reachability, a deal sample, a whole-game search, a result below 172, or a complete-game optimum. `independent_cold_complete` stays false. `opening_reachability` is `unestablished`. Deal 4925153, its checkpoints, the SD5 roots, and the 172/185 routes were not loaded. `AGENTS.md`, the evaluator, the abstract panel, the PR4 tests, the rules engine, and the search kernel were not edited.

The best verified complete-game result remains 172 corrected MobilityWare moves. This note does not relabel the PR4 abstract-panel pass.

## Question and method

With the evaluator frozen, do the local planning improvements survive on full, inventory-valid tableaux under the same PR4 limits?

Each source names one column that already has a face-down card. Success is a drop in that column's face-down count. A reveal in another column is not success. Every legal tableau action is one candidate. The unchanged `compare_local_objective` builds those options, scores the unchanged selector, and searches continuations. Ordered `pack_state` is the identity. `pack_post_stock_symmetry_state` is not used. No `lower_bound_fn` is passed. Bonds and the dependency penalty are not the objective cost.

The budget is the panel `COMPARISON_BUDGET`: `max_unique=20`, `time_limit_s=2.0`, `rss_abort_mb=512`, `cost_ceiling=4`, `max_depth=None`, one worker, `stop_on_first_terminal=False`, `harvest_slack=None`. At most eight candidates per source. Stock is empty, so Deal is illegal and the tableau set matches the engine's full legal set.

`upper-unfinished` and `unknown` keep the comparison inconclusive and keep the baseline choice. A retained witness inside an unfinished search is not a minimum certificate. `exhausted-no-hit` means no hit inside the scoped cap. Ties keep baseline order.

## Construction

Rule name: `spine-plus-inert-top-and-foundation-sink`. Label: `constructed_inventory_valid`.

1. Start from two copies of every suit and rank.
2. Place the abstract mechanism as the face-up spine. The abstract buried fillers are not copied.
3. Fill empty columns with inert tops. Ranks run from king downward. A rank adjacent to a current top, to a movable run's contact, or to an inert rank already chosen is skipped. A suit is used only while two copies remain, in order spades, hearts, diamonds, clubs.
4. Extract king-to-ace foundations in that same suit order, repeating while any suit still has every rank.
5. Give one face-down card to each column that is not free, target first. The remainder is sorted by rank, then suit.
6. Place every leftover card as face-up body under the lowest-index column that is neither the target nor free, and only when it does not form a same-suit bond with the current bottom.
7. Leave the stock empty.

Face-down limits are post-flip maxima: at most 5 in columns 0-3, at most 4 in columns 4-9, and at most 44 in total. They are not exact fills and they do not cap total column length. Length caps of 5 and 4 would hold 44 tableau cards. `104 - 44 = 60` is not a multiple of 13, so an empty stock and complete foundations could not both exist under that reading.

The target has no body, because the reveal fires only when that column's face-up cards leave. Workspace columns 2 and 4 stay a single face-up card with no face-down card, so a later whole-column move onto an empty column can cost 0. On these six sources the target face-down card is `As`, the lowest remaining card after foundations.

Body sits on one column: 31, 31, 31, 44, 30, and 33 cards for the six sources, in order. Those cards are outside the initial movable run. Inert tops may repeat a rank that is already showing. On the distractor and three-deep sources the extra nines add no root action while `8c` is covered. After `8c` is exposed, each nine is another rank receiver. That is a physical difference from the abstract panel. The comparison below is inside each new source. It is not a paired replay of a PR4 board.

Distractor uses both club nines in the spine, so no club foundation can be completed. It has three foundations. The other five sources have four, one per suit.

| Source | Target | Legal actions | Baseline | Foundations | Hidden | Cards | Shape |
| --- | ---: | --- | --- | --- | ---: | ---: | --- |
| `blocker-chain` | 0 | `(1, 2, 1)`, `(3, 4, 1)` | `(3, 4, 1)` | s, h, d, c | 10 | 104 | pass |
| `immediate-join` | 5 | `(0, 1, 2)`, `(5, 6, 1)` | `(0, 1, 2)` | s, h, d, c | 10 | 104 | pass |
| `symmetric-tie` | 0 | `(0, 2, 1)`, `(0, 4, 1)` | `(0, 2, 1)` | s, h, d, c | 10 | 104 | pass |
| `distractor-reveal` | 0 | `(0, 2, 1)`, `(5, 6, 1)` | `(5, 6, 1)` | s, h, d | 10 | 104 | pass |
| `three-deep-uncover` | 0 | `(0, 2, 1)`, `(2, 3, 1)`, `(4, 5, 1)` | `(4, 5, 1)` | s, h, d, c | 10 | 104 | pass |
| `zero-cost-workspace` | 0 | `(1, 2, 1)`, `(2, 3, 1)`, `(5, 6, 1)` | `(5, 6, 1)` | s, h, d, c | 8 | 104 | pass |

Hidden cards are one per non-free column. Workspace columns 2 and 4 have none. Every face-down column has a face-up top. No column has a latent same-suit king-to-ace on top. Every foundation is a same-suit king-to-ace sequence. Each suit/rank appears twice across tableau and foundations.

Inert tops: blocker `Ks Kh Kd Kc 7s` on columns 5-9; immediate `Ks Kh Kd` on 2-4 and `Kc Js Jh` on 7-9; tie `Ks` on 3, `Kh Kd Kc` on 5-7, `Js Jh` on 8-9; distractor `9s` on 4 and `9h 9d 7s` on 7-9; three-deep `9s 9h 9d 7s` on 6-9; workspace `Ks Kh Kc` on 7-9. The workspace diamond king stays in its foundation because the spine already used one `Kd`.

The original six abstract fixtures fail this same static check on card count, stock length, and the two-copy count. Their tests and layouts were not modified.

Scripted engine replays, recorded with the freeze and not produced by search, still match the abstract mechanism costs. The immediate join reveals column 5 at cost 1. The tie's two parks each reveal column 0 at cost 2. The workspace continuation `(2, 3, 1)` then `(4, 2, 1)` costs 1 then 0 and does not reveal column 0.

## One-shot invocation

Working directory: the repository root. Interpreter `py -3`. `PYTHONPATH=src`. Run once, after `7b6a051`, by:

```text
py -3 -m spider.dependency_objective_inventory_run
```

That calls `compare_local_objective(state, reveal_predicate(state, target_column))` once per source, with no custom limits. The driver wraps the call in `time.perf_counter` and `time.process_time`. The evaluator file was not changed to add CPU timing. Windows `process_time` advances in 15.625 ms steps, so the CPU figures are coarse.

`tests/test_dependency_objective_inventory_lock.py` records the packs, statuses, costs, unique counts, and continuations. It does not call the lookahead.

## Comparison summary

| Source | Shape | Fully resolved | Baseline choice | Baseline scoped cost | Other exact or retained cost | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `blocker-chain` | pass | no | `(3, 4, 1)` | unfinished witness 3 | unfinished witness 2 | inconclusive, baseline kept |
| `immediate-join` | pass | yes | `(0, 1, 2)` | exact 2 | exact 1 | strict win |
| `symmetric-tie` | pass | yes | `(0, 2, 1)` | exact 2 | exact 2 | tie, baseline kept |
| `distractor-reveal` | pass | no | `(5, 6, 1)` | unfinished witness 3 | unfinished witness 2 | inconclusive, baseline kept |
| `three-deep-uncover` | pass | no | `(4, 5, 1)` | unfinished witness 4 | unfinished witness 3; side unknown | inconclusive, baseline kept |
| `zero-cost-workspace` | pass | no | `(5, 6, 1)` | unknown | exhausted miss; unknown | inconclusive, baseline kept |

One motif has a fully resolved strict improvement: `immediate-join`. The tie resolves and keeps baseline order. Blocker, distractor, and three-deep each retain a cheaper-looking witness and then stop at 20 identities, so those comparisons stay inconclusive. Workspace records no objective witness. No fully resolved case is worse. The pass bar still fails: it requires two resolved strict wins, including distractor or three-deep.

## Per-source evidence

Candidate rows are in baseline order. Costs are corrected MobilityWare moves. Times are seconds. `wall` and `cpu` cover the whole `compare_local_objective` call. `baseline`, `kernel`, and `overhead` are the evaluator's own splits. Kernel time is the sum of continuation searches. Selector time is `baseline` only. The same rows score both choices.

An unfinished total is the replayed retained witness. It is not an exact minimum.

### `blocker-chain`

Legal set `{(1, 2, 1), (3, 4, 1)}`. Target column 0. Wall 0.062366. CPU 0.062500. Baseline 0.011960. Kernel 0.028092. Overhead 0.022277.

Source pack `53504b3101040000010101370121113c2c1c0c3b2b1b0b3a2a0a391909281808271736261606352515053424140438290101211a01013112010102130101220d0101321d0101032d0101233d010133070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost | Elapsed |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(3, 4, 1)` | upper-unfinished | unique limit | 1 | `(1, 2, 1)`, `(0, 1, 1)` | 3 | 20 | 5 | 21 | 0 | 0.021832 |
| `(1, 2, 1)` | upper-unfinished | unique limit | 1 | `(0, 1, 1)` | 2 | 20 | 6 | 22 | 0 | 0.006212 |

Both witnesses replay at those totals and reveal column 0. The search did not complete, so neither total is a minimum certificate. Status `inconclusive`. Choice stays `(3, 4, 1)`.

Witness packs: baseline path `53504b31010400000001010121113c2c1c0c3b2b1b0b3a2a0a391909281808271736261606352515053424140438370102211a2900013101020213120101220d0101321d0101032d0101233d010133070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`; other path `53504b31010400000001010121113c2c1c0c3b2b1b0b3a2a0a391909281808271736261606352515053424140438370102211a2901013112010102130101220d0101321d0101032d0101233d010133070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

### `immediate-join`

Legal set `{(0, 1, 2), (5, 6, 1)}`. Target column 5. Wall 0.031823. CPU 0.031250. Baseline 0.013034. Kernel 0.001557. Overhead 0.017196.

Source pack `53504b31010400000121113c2c1c0c3b2b3a2a1a0a2919092818083727170736261606352515342414330403010121050101310d0101021d0101122d01010138010122390101323d0101130b0101231b0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost | Elapsed |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(0, 1, 2)` | exact | complete | 1 | `(5, 6, 1)` | 2 | 2 | 1 | 1 | 0 | 0.001533 |
| `(5, 6, 1)` | exact | prefix-terminal | 1 | empty | 1 | 0 | 0 | 0 | 0 | 0.000000 |

`(5, 6, 1)` reveals column 5 immediately. The kernel is not called for that candidate. The baseline path replays at 2 and also reveals column 5. Status `ranked`. Choice `(5, 6, 1)`. This is a strict resolved improvement. The immediate-join semantics hold.

Final pack of the one-move plan: `53504b31010400000121113c2c1c0c3b2b3a2a1a0a2919092818083727170736261606352515342414330403010121050101310d0101021d0101122d00010101022239380101323d0101130b0101231b0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

### `symmetric-tie`

Legal set `{(0, 2, 1), (0, 4, 1)}`. Target column 0. Wall 0.032874. CPU 0.031250. Baseline 0.011949. Kernel 0.004453. Overhead 0.016441.

Source pack `53504b310104000001020138130120113c2c1c0c3b2b3a2a1a0a29190928180837271707362616063525150534143339010121240101310d010102040101121d0101222d0101323d0101030b0101231b0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost | Elapsed |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(0, 2, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 4 | 2 | 4 | 0 | 0.002278 |
| `(0, 4, 1)` | exact | complete | 1 | `(0, 1, 1)` | 2 | 4 | 2 | 4 | 0 | 0.002129 |

Both paths replay at 2 and reveal column 0. Status `ranked`. Choice stays the baseline `(0, 2, 1)`.

### `distractor-reveal`

Legal set `{(0, 2, 1), (5, 6, 1)}`. Target column 0. Wall 0.060585. CPU 0.062500. Baseline 0.015060. Kernel 0.010144. Overhead 0.035337.

Source pack `53504b31010300000102013813012d113d3d2d1d3c3c2c1c3b3b2b1b0b3a3a2a1a0a3828180837372717363626160635352515053434140433332303390101212401013139010131090101020c0101120d0101221901013229010132070d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost | Elapsed |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(5, 6, 1)` | upper-unfinished | unique limit | 1 | `(0, 2, 1)`, `(0, 1, 1)` | 3 | 20 | 4 | 20 | 0 | 0.004992 |
| `(0, 2, 1)` | upper-unfinished | unique limit | 1 | `(0, 1, 1)` | 2 | 20 | 4 | 20 | 0 | 0.005113 |

Both retained witnesses replay and reveal column 0. The queen move is only the start of the baseline witness; the retained continuation goes on to column 0. The search stopped at 20 identities on both candidates, so the 3-versus-2 pair is not a resolved comparison. Status `inconclusive`. Choice stays `(5, 6, 1)`.

### `three-deep-uncover`

Legal set `{(0, 2, 1), (2, 3, 1), (4, 5, 1)}`. Target column 0. Wall 0.067990. CPU 0.078125. Baseline 0.020678. Kernel 0.018337. Overhead 0.028938.

Source pack `53504b3101040000010301382413011f113d1d0d3c1c0c3b2b1b0b3a2a1a0a281808372717362616063525053414333901012104010131150101022c0101122d010122090101321901010329010123070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost | Elapsed |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(4, 5, 1)` | upper-unfinished | unique limit | 1 | `(0, 2, 1)`, `(0, 3, 1)`, `(0, 1, 1)` | 4 | 20 | 5 | 22 | 0 | 0.006072 |
| `(0, 2, 1)` | upper-unfinished | unique limit | 1 | `(0, 3, 1)`, `(0, 1, 1)` | 3 | 20 | 5 | 23 | 0 | 0.005778 |
| `(2, 3, 1)` | unknown | unique limit | 1 | none | none | 20 | 6 | 25 | 1 | 0.006425 |

The first two witnesses replay and reveal column 0. The side move has no witness. One zero-cost successor was counted on that side search and is not a certificate. Status `inconclusive`. Choice stays `(4, 5, 1)`.

### `zero-cost-workspace`

Legal set `{(1, 2, 1), (2, 3, 1), (5, 6, 1)}`. Target column 0. Wall 0.052430. CPU 0.046875. Baseline 0.018503. Kernel 0.012074. Overhead 0.021811.

Source pack `53504b310104000001020138130122113c2c1c0c3b2b0b3a1a0a29190928180837271736261635251505342414043323033900012a0101211b00012d01013106010102070101120d0101221d0101323d0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`.

| Option | Status | Stop | Prefix | Continuation | Total | Unique | Expanded | Generated | Zero-cost | Elapsed |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `(5, 6, 1)` | unknown | unique limit | 1 | none | none | 20 | 4 | 21 | 4 | 0.005896 |
| `(1, 2, 1)` | exhausted-no-hit | complete | 1 | none | none | 2 | 2 | 1 | 0 | 0.001825 |
| `(2, 3, 1)` | unknown | unique limit | 1 | none | none | 20 | 2 | 20 | 2 | 0.004255 |

No candidate produced an objective witness. The zero-cost counts are not a certificate. `(1, 2, 1)` finished inside the cap with no hit. Status `inconclusive`. Choice stays `(5, 6, 1)`. The unknown fallback holds.

## Tests

Static inventory checks and the 15 existing PR4 tests passed before the one-shot: 20 passed, 0 failed, in 1.66 seconds. Those checks do not call the lookahead. The original six abstract fixtures fail the inventory helper inside that run.

After the one-shot, the maintained selection plus the new files was run once. The selection is the v0.123 file list, plus `tests/test_global_search_v0_124.py`, `tests/test_global_search_v0_125.py`, `tests/test_global_search_v0_126.py`, `tests/test_goal_directed_anchored_v0_129.py`, `tests/test_post_sd5_completion_v0_130.py`, `tests/test_proof_first_admission_v0_131.py`, `tests/test_pre_sd5_backward_preparation_v0_132.py`, `tests/test_stock_boundary_route_bridge_v0_133.py`, `tests/test_purposeful_macro_portfolio_v0_134.py`, `tests/test_origin_fair_continuation_v0_135.py`, `tests/test_post_deal_milestone_macros_v0_136.py`, `tests/test_phase_aware_milestone_v0_137.py`, `tests/test_heart_run_followthrough_v0_138.py`, `tests/test_reveal_aware_heart_macros_v0_139.py`, plus `tests/test_dependency_options_two_stage.py`, `tests/test_dependency_options_offline_audit_pr2.py`, `tests/test_dependency_contract_continuity_pr3.py`, plus the three PR4 files, plus `tests/test_dependency_objective_inventory.py` and `tests/test_dependency_objective_inventory_lock.py`. That is 53 files.

Invocation: `py -3 -m pytest` on those 53 files, `-q --tb=line -p no:cacheprovider`, from the repository root. One worker. Result: 709 passed, 0 failed, in 249.06 seconds. Bare `pytest tests` was not used. This selection is not the entire suite.

The parent selection reported at `1a56107` was a different run: 51 files, 703 passed, 0 failed, in 281.24 seconds. That number is not recomputed here. The 709-pass result is the independent current run.

`tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. It was not edited. It can still return `PLANNING_STALL` instead of `TIME_LIMIT` (issue #6).

Collection of these eight modules is separate and was not treated as part of the green selection:

- `tests/test_exact_state_policy_context_equivalence_v0_1.py`
- `tests/test_one_shot_natural_empty_service_v0_1.py`
- `tests/test_one_shot_natural_r3_service_v0_1.py`
- `tests/test_workspace_opportunity_service_lane_v0_1.py`
- `tests/test_workspace_service_generalisation_panel_v0_1.py`
- `tests/test_workspace_service_lag1_grace_v0_1.py`
- `tests/test_workspace_service_stock_guard_v0_1.py`
- `tests/test_workspace_service_stock_synchronous_v0_1.py`

With `PYTHONPATH=src`, collection of those eight files reported 8 errors in 2.88 seconds. The tests were not edited.

## Limitations

- The sources are constructed motif controls. Opening reachability is unestablished.
- Filler geometry differs from the abstract panel, including extra nine-receivers after `8c` is exposed and a large body under one column. These are not paired copies of the PR4 boards.
- Four sources stopped at `max_unique=20` with unfinished or missing certificates. Those retained witnesses are not resolved wins.
- `exhausted-no-hit` means no objective inside the scoped cap of that prefix.
- The same objective costs score both choices.
- No full-game lower bound was used. The cap was not raised. No second seed or layout was tried.
- `independent_cold_complete` remains false. The verified complete-game result remains 172 corrected moves.
- Process CPU is the driver's `process_time` around each comparison. On this machine that clock steps by 15.625 ms.

## Verdict

**INCONCLUSIVE.**

All six sources pass the static inventory and shape checks. Only `immediate-join` is a fully resolved strict improvement. `symmetric-tie` resolves and keeps the baseline. `distractor-reveal` and `three-deep-uncover` both stop on the unique-state cap, so neither supplies the required resolved win. `blocker-chain` is likewise unfinished. `zero-cost-workspace` has no objective witness and keeps the baseline. No fully resolved case is worse. Opening reachability, deal distribution, whole-game performance, and a better optimum than 172 remain unestablished.

Do not retune, raise caps, or continue the search. The inventory sources do not establish a local benefit under the frozen PR4 limits. Leave the abstract PR4 result unqualified.
