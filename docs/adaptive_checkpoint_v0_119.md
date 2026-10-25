# Adaptive checkpoint shortcuts v0.119

Schema `spider-human-strategy-0.119`. Branch `local/adaptive-checkpoint-v0-119`. HEAD `4be30e1aa5003752b63f59f14a5d8d18430fa4b0` (`Add incumbent-anchored solution optimisation v0.118`). The v0.119 edits are uncommitted. Nothing was pushed, merged, or opened as a pull request.

Deal 4925153 still has best verified complete cost **185** on the autonomous file and **172** on the separate canonical file. Neither adaptive pilot found a cheaper complete route. A constructed board did: a verified cost-3 game was replaced by a replayed cost-1 game through a later checkpoint that fixed windows do not select.

## Files changed

Edited on this branch, not in the v0.118 commit:

- `src/spider/human_strategy/anchored.py` — multi-target search and adaptive regions
- `src/spider/human_strategy/controller.py` — foundation timing, workspace-probe budget, provenance
- `src/spider/human_strategy/foundation_direction.py` — portfolio and excavation cache counters
- `src/spider/planner/backward_strategy.py` — controller-only workspace probe budget and cache
- `src/spider/human_strategy/__init__.py` — schema `spider-human-strategy-0.119`
- `tools/human_strategy_solver.py` — `--adaptive`, `--horizon`, `--regions`
- `tests/test_human_strategy_v0_117.py` — schema assertion
- `tests/test_human_strategy_v0_119.py` — new
- `docs/adaptive_checkpoint_v0_119.md` — this note

Untouched: `engine.py`, `rules.py`, corrected MobilityWare scoring, `solutions/4925153_autonomous_185.moves`, `solutions/4925153_canonical.moves`, `solutions/4925153_incumbent.json`, historical campaign data, and Spider Play Lab. `search_kernel.py` was not edited.

## Baseline kept from v0.118

Those figures are the committed v0.118 measurements. This branch does not rewrite them.

Anchored MW 185, fixed windows: 189 actions, 190 checkpoints, cost 185, 16 windows, 12 exhausted, 4 stopped at 2,500 unique states, 523 segment-bound prunes, 2,346 expansions, 0 rejoins, no improvement, 6.780 seconds, RSS 33.25 MB. The capped windows were actions 65–73, 168–177, 177–182, and 183–187.

Separate MW 172: 175 checkpoints, 704 segment-bound prunes, 0 rejoins, no improvement, 6.555 seconds, RSS 33.06 MB.

Global 40-second optimise under the 185 ceiling (`artifacts/human_strategy/v0_118/experiment_a_global.json`): foundation proposals 37.044 of 40.195 seconds, excavation misses 34, inconclusive 20, nodes 2,859, hits 2, expanded 2, safe prunes 0, heuristic exclusions 10 (all `heuristic_admission`, 7 with `equivalent_retained`), partial trajectory g=53 with 1 foundation, 68 unique strategic states, 85 states evaluated, `TIME_LIMIT`, RSS 62.59 MB.

The fixed-window optimiser still turns the constructed cost-3 detour into a replayed cost-1 game. `test_eight_foundations_remain_the_victory_condition_and_fixed_mode_still_improves` checks that path with `adaptive=False`.

## Multi-target search

`search_targets` keeps the fixed one-endpoint `search_segment` path. Adaptive mode is opt-in (`optimise_anchored(..., adaptive=True)` or CLI `--adaptive` with `--mode anchored`).

From one source checkpoint the search receives every later checkpoint inside the horizon. Each target carries the incumbent state, the original segment cost `g[j] - g[i]`, and the checkpoint index. The kernel cost ceiling is one below the largest of those original costs. A branch that can no longer beat an early target stays alive while a later target is still strictly improvable. The lower bound at a node is the smallest deal-count bound among targets that this `g` can still beat. If every remaining target is unreachable or already at least as expensive as its own original cost, the bound is unreachable and the node is pruned. Face-down cards and foundation counts are not added. One action can satisfy more than one of those obligations.

A path is accepted only when its corrected cost is strictly below that target's original cost, the replay lands on the exact column-ordered state, and the spliced full game passes `verify_complete_solution` (solved, eight foundations, empty stock, cost below the current incumbent). The suffix starts at the matched checkpoint, which can be earlier than the horizon end. An equal cost leaves the incumbent in place. The production registry is not written.

Search identity is `pack_state` / `canonical_state_key`. `pack_post_stock_symmetry_state` is not used to append a suffix. The printed `state_id` is only the first 16 hex characters of the pack and can collide. It is not the rejoin key.

An exact target state is terminal, so the search does not expand through that checkpoint. A non-improving arrival does not stop the rest of the graph. A strict improvement sets the unique cap to zero so the kernel stops before the next new state, then the best saving that replays is kept. If that replay fails, the stop is inconclusive. Exhausting the graph is a negative result only for the selected targets and that ceiling. It is not a proof that the original segment is optimal on the whole game. `INCONCLUSIVE` results are not memoised. `FOUND`, `EXHAUSTED`, `NOT_CHEAPER`, and `IMPOSSIBLE` are. A reused hit reports zero new expansions.

Zero-cost whole-column transfers stay in the graph and sort ahead of paid moves. The kernel skips a state already reached at an equal or lower `g`, so a zero-cost cycle does not expand again. On the micro board, the search for a cost-0 path to the direct completing position exhausted at under 500 unique states with more duplicate skips than expansions.

## Adaptive windows

`select_windows` is unchanged and remains the default. `select_adaptive_regions` picks up to six non-overlapping sources. Exact cycles come first and need no search. Other regions take later checkpoints within a horizon of 16. The score only orders the sources. It uses reversals, stock-empty spans, foundation changes, parking, and the four v0.118 capped indexes (65, 168, 177, 183). A skipped span is not evidence.

On the 185 route those four indexes fall inside three of the six regions: 65–81, 153–169 (covers 168), and 177–189 (covers 177 and 183). The unique cap stays 2,500.

## Benchmark A — later checkpoint on a constructed board

Artifact: `artifacts/human_strategy/v0_119/experiment_a_fixture.json`.

The board is the seven-foundation micro position used in v0.118, not deal 4925153. The incumbent walks the ace across empty columns, walks the king, returns the ace, and removes the heart suit. Verified cost 3, eight foundations, empty stock, 13 checkpoints.

The first endpoint, checkpoint 1 at cost 1, is `EXHAUSTED` with proof limited to that ceiling. `search_targets` over the later checkpoints returns `FOUND` at cost 0, target index 11, whose original cost is 2. One expansion. The measured replacement is the zero-cost king transfer `move 2 5 1`. The solver does not contain that sequence.

`optimise_anchored(..., adaptive=True)` splices it, replays the full game, and stores cost 1 with eight foundations (`improved=True`, `incumbent_source=discovered`, 0.513 seconds, RSS 26.99 MB). Fixed mode with `max_span=8` selects no window: the useful span is 11, and the only foundation gap is span 12, past `max(max_span, 10)`. Fixed mode leaves cost 3 (`improved=False`, 0.003 seconds).

A second constructed position, with no empty column, checks the ceiling. The early target has original cost 1 and the search exhausts with no improvement, because the kernel ceiling is 0. The same graph with a later target of original cost 6 returns `FOUND` at cost 1. That move is too expensive to beat the early target and is still a strict improvement on the later one. The stored `ceiling` field is the largest original cost (6). The kernel uses 5.

## Benchmark B — adaptive MW 185

Command and artifact below. One process, source `solutions/4925153_autonomous_185.moves`.

Verified route retained: 190 checkpoints, cost 185, solved, eight foundations. Six regions, all `INCONCLUSIVE` at 2,500 unique states. 1,805 expansions, 1,336 segment-bound prunes, 92 targets considered, 14 exact-state encounters, 0 successful rejoins, 0 memo hits, 0 improvements. 10.651 seconds, RSS 33.32 MB. `known_inconclusive_covered` is `[65, 168, 177, 183]`.

| Source | Last target | Kind | Targets | Expansions | Unique | Prunes | Encounters |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 153 | 169 | stock_empty | 16 | 79 | 2500 | 0 | 2 |
| 177 | 189 | known_inconclusive | 12 | 83 | 2500 | 0 | 1 |
| 65 | 81 | known_inconclusive | 16 | 164 | 2500 | 1 | 1 |
| 0 | 16 | reversal | 16 | 706 | 2500 | 706 | 6 |
| 17 | 33 | reversal | 16 | 384 | 2500 | 383 | 3 |
| 34 | 50 | reversal | 16 | 389 | 2500 | 246 | 1 |

The 14 encounters arrived at an incumbent checkpoint at a cost that was not strictly lower. No suffix was appended. Compared with the v0.118 fixed pilot (16 windows, 12 exhausted, 4 capped, 523 prunes, 2,346 expansions, 0 rejoins, 6.780 seconds), this run covers the four capped regions inside three horizon searches and also spends the unique cap on three early reversal horizons. It does not show that any of those segments is optimal.

## Benchmark C — adaptive MW 172

Separate process. Source `solutions/4925153_canonical.moves`. The 185 action list was not an input.

Verified route retained: 175 checkpoints, cost 172, solved, eight foundations. Six regions, all `INCONCLUSIVE` at 2,500 unique states. 1,786 expansions, 1,588 segment-bound prunes, 86 targets considered, 14 exact-state encounters, 0 rejoins, 0 improvements. 10.004 seconds, RSS 33.20 MB. Covered known indexes are 65 and 168. Indexes 177 and 183 lie past this route.

| Source | Last target | Kind | Targets | Expansions | Unique | Prunes | Encounters |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 152 | 168 | stock_empty | 16 | 181 | 2500 | 0 | 1 |
| 168 | 174 | known_inconclusive | 6 | 16 | 2500 | 0 | 1 |
| 65 | 81 | known_inconclusive | 16 | 176 | 2500 | 176 | 2 |
| 0 | 16 | reversal | 16 | 715 | 2500 | 714 | 5 |
| 16 | 32 | reversal | 16 | 348 | 2500 | 348 | 1 |
| 32 | 48 | reversal | 16 | 350 | 2500 | 350 | 4 |

v0.118 on this file: 704 segment-bound prunes, 0 rejoins, 6.555 seconds, RSS 33.06 MB. Still no complete route cheaper than 172. A route cheaper than 185 would be an improvement on the autonomous reference and would still sit above this 172 reference. None was found.

## Benchmark D — global throughput under the 185 ceiling

Same command shape as v0.118: 40 seconds, frontier 8, proposals 3, slice 24, line attempts 48, one worker, portfolio consultation off, max steps 220, memory cap 3072 MB, goal foundations, target 8. Artifact `artifacts/human_strategy/v0_119/experiment_d_global.json`.

| Measure | v0.118 | v0.119 |
| --- | --- | --- |
| Status | TIME_LIMIT | PLANNING_STALL |
| Elapsed | 40.195 s | 40.187 s |
| Foundation component | 37.044 s | 37.299 s |
| Tactical component | 0.142 s | 0.513 s |
| Unique strategic states | 68 | 75 |
| States evaluated | 85 | 111 |
| Foundations | 1 | 1 |
| Partial g | 53 | 50 |
| Safe whole-game prunes | 0 | 0 |
| Heuristic exclusions | 10 | 9 |
| Equivalent retained | 7 | 7 |
| Excavation nodes | 2,859 | 28,903 |
| Excavation misses / hits / inconclusive | 34 / 2 / 20 | 48 / 10 / 43 |
| Peak RSS | 62.59 MB | 139.39 MB |

`PLANNING_STALL` here has `deadline_elapsed=true` and `resource_stops=0`. A nested probe used the last of the 40 seconds inside an iteration, and legal tableau moves were still present, so the loop header did not record `TIME_LIMIT`. Unique strategic states are canonical strategic keys. They are not the excavation node count.

v0.119 split of the foundation bucket:

- `foundation_analysis` 6.682 s
- `dependency_planning` 27.335 s
- `tactical_realisation` 2.861 s
- `receiver_alignment` 0.096 s
- `consequence_comparison` 0.000 s

The v0.118 artifact has no inner split. A 20-second diagnostic on this branch before the probe change spent 16.911 of 18.95 foundation seconds in `foundation_analysis`, and that time was two `realize_workspace` calls at 0.35 seconds that returned `resource_limit` on positions with no empty column.

## Cache correctness

The controller stores `_workspace_probe_s = 0.08` and a probe cache on the portfolio cache. `load_portfolio` installs both context variables only for the campaign build, then resets them. Direct planner calls leave the variables unset and still use 0.35 seconds and 400 nodes.

The cache key is the authoritative pack, the node cap, and the rounded time limit. A stored `None` is an unproved resource limit for that budget. A larger budget is a different key and runs again. The opening of 4925153 still has no empty column, so both the 0.35 second probe and the 0.08 second probe return no numeric workspace cost. This pilot recorded 81 misses, 3 hits, and 2 negative hits. `foundation_analysis` at 6.682 seconds matches those 81 short probes. Portfolio rebuilds: 47 misses, 43 hits, so an unchanged authoritative state does not rebuild the campaign.

Excavation still keys on state, source card, deal policy, max cost, max nodes, and strategy. A `PROBE_LIMIT` or `NODE_LIMIT` at one node cap is reused for that cap and is not treated as infeasibility. A larger node cap runs again. This pilot: 10 hits, all `negative_hits`, 0 revisits, 48 misses, 6 justified expansions. Identical failed probes were not expanded twice. The time budget is not part of the excavation key. A probe that starts and then hits the outer deadline can remain cached for that node cap. The pre-search guard (`time_left < 0.05`) still returns `TIME_LIMIT` and does not cache.

The foundation wall clock did not fall. The 0.35 second workspace timeouts were the previous dominant cost. After they shrank, `_elapsed_access_proposal` and `_access_proposal` used the same 40 seconds: up to 2,000 nodes and, when a limit is justified, 4,500 nodes with a 12 second deadline clamped by the remaining global time. That is the 27.335 seconds and 28,903 nodes. It is additional excavation, not a second run of the same workspace probe. Strategic exploration moved from 68 unique states and 85 evaluations to 75 and 111, still with one foundation and no whole-game prune. The partial g=50 trajectory is not an incumbent. Whole-game `g + admissible_remaining` remains far below 185, which is why safe prunes stay at 0.

## Benchmark E

`deals/` contains only `4925153.txt`. The multi-target improvement and the probe-cache tests use constructed boards: the long micro route above, the no-empty ceiling board, and a ten-column blocked board for the workspace cache. Those paths do not read the 185 or 172 action lists.

## Tests

`py -3 -m pytest` on the v0.118 regression file list plus `tests/test_human_strategy_v0_119.py`: **420 passed in 296.74 seconds**. The previous list accounted for 410 tests. The new file adds 10 tests and covers the 22 required checks: exact checkpoints, several later targets, a later-checkpoint improvement, a move that loses to the early ceiling and still beats a later target, column permutation, stock mismatch, foundation mismatch, zero-cost moves, bounded zero-cost cycles, strict improvement, mandatory full replay, incumbent replacement, rejected shortcuts, successive checkpoint refresh, inconclusive caps, memo reuse of overlapping work, a larger probe budget, identical failed probes, nested time limits, cold and solve independence, separate 185 and 172 provenance, and eight foundations.

Cold and solve reject `--adaptive` (exit 2) and still reject `--incumbent`. `optimise_anchored(..., mode="cold")` and `mode="solve"` raise `AnchoredRefused`.

## Runtime and memory

One worker. Anchored pilots finished in about 11 seconds, RSS about 33 MB, under the 120 second cap and the 3072 MB cap. The global pilot used its 40 seconds and peaked at 139.39 MB. The constructed adaptive improvement used 0.513 seconds and 26.99 MB. No 600 second run was started. The frontier stayed at 8.

## Limitations

Every adaptive region on both real routes stopped at 2,500 unique states. The exact states they did reach were not cheaper, so no suffix was joined. That is inconclusive inside the horizon and the cap.

An exact earlier checkpoint is terminal. A continuation that would pass through that state at a non-improving cost is not expanded. A later target is still open to a path that reaches it some other way, which is the constructed case.

The controller workspace probe is shorter than a direct planner probe. A workspace that would appear between 0.08 and 0.35 seconds is reported as unproved (`None`), not as impossible. On this opening both budgets already return `None`.

Global search still spends almost the entire 40 seconds inside foundation proposals. The repeated-probe caches work. The remaining time is deep excavation, and the strategic frontier only gained a small number of additional states. No verified complete game under 185, and none under 172, was produced. The 119-move benchmark was not run.

## Recommended v0.120

Keep the 2,500 cap as the default. An explicit longer unique budget on one stock-empty horizon (185 indexes 153–169 or 177–189) is the anchored experiment still worth running. Do not widen the strategic frontier to buy it.

On the global side, cap how long one foundation proposal may excavate before control returns to the frontier, and do not cache a deadline stop as if it were the same node-cap result. Leave the justified 4,500-node expansion available when the evidence asks for it. Do not invent a stronger whole-game bound by adding deals, reveals, and foundations together.

## Reproduction

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py tests/test_human_strategy_v0_119.py -q --tb=line
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_autonomous_185.moves --adaptive --horizon 16 --regions 6 --profile pilot --time-limit 120 --workers 1 --memory-mb 3072 --out artifacts/human_strategy/v0_119/experiment_b_anchored_185.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_canonical.moves --adaptive --horizon 16 --regions 6 --profile pilot --time-limit 120 --workers 1 --memory-mb 3072 --out artifacts/human_strategy/v0_119/experiment_c_anchored_172.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_119/experiment_d_global.json
```

Benchmark A is `optimise_anchored` on the constructed route in `tests/test_human_strategy_v0_119.py` (`test_multi_target_improves_a_later_checkpoint_fixed_windows_miss`). Measured JSON: `artifacts/human_strategy/v0_119/experiment_a_fixture.json`.

## Git status

Branch `local/adaptive-checkpoint-v0-119`. HEAD `4be30e1aa5003752b63f59f14a5d8d18430fa4b0`.

```text
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/anchored.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/planner/backward_strategy.py
 M tests/test_human_strategy_v0_117.py
 M tools/human_strategy_solver.py
?? docs/adaptive_checkpoint_v0_119.md
?? tests/test_human_strategy_v0_119.py
```

No commit, push, merge, or pull request.
