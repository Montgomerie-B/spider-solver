# Complete-solution bootstrap and incumbent-constrained optimisation v0.117

v0.116 can expose a buried card, build `Kh`–`6h`, and tell a probe limit from an exhaustive miss. It has not been a whole-game optimiser. The live controller already compared `g + admissible_remaining` with an incumbent on the active line, and the v0.107 tests locked that event. The ceiling was a number from a replay. A partial file could supply it. Finding a cheaper finished game did not tighten it. A timed-out search reported the partial `g` as the line cost.

v0.117 keeps that controller. It adds a verified-route check, a ceiling that moves only when a strictly cheaper finished game replays, and provenance that keeps the verified incumbent when the search does not. Cold and solve modes still refuse a known sequence. The 150-second pilots on deal 4925153 did not finish a game and did not beat 185. They kept the imported ceiling. A constructed board did replace a verified cost of 3 with a replayed cost of 1.

`engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the production incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

## 1. Baseline

Schema is `spider-human-strategy-0.117`. The default artifact directory is `artifacts/human_strategy/v0_117/`.

Branch `local/solve-optimise-pipeline-v0-117`. HEAD `35eb761b0f96b11f506e3726cf07de69f0ded5cd` (`Add foundation-critical excavation and probe recovery v0.116`). The v0.117 edits are uncommitted. The tree was clean at that HEAD before those edits.

Pilot limits used below: one worker, frontier 8, 3 proposals, slice 24, per-line attempt cap 48, 220 steps, RSS abort 3072 MB, portfolio off, 150 seconds. Smoke tests stay on the small profile. Extended was not launched. `--root post-sd3` was not used.

`SOLVED_VALID` still requires `is_solved()`: eight foundations, an empty stock, and an empty tableau. A foundation removal is a partial trajectory.

## 2. Optimisation audit and the live call paths

The audit was made by reading the functions the controller actually calls. An incumbent field that no live path reads would not count. These paths do run.

| Path | What runs | What the 185 ceiling does there |
| --- | --- | --- |
| Cold and solve | `solve` rejects `incumbent_actions`. The CLI rejects `--incumbent` before the deal is searched | Not loaded |
| File load | `verify_complete_solution` replays a clone. Eight foundations, empty stock, and `is_solved()` are required. The cost is the replay | Accepted only when the replay is 185. A partial, illegal, or mis-costed file is rejected and the search does not start |
| Active line | Each visited line calls `admissible_remaining`. `proof_prune` is `g + h >= ceiling` | Consulted. The event text is `incumbent bound:` |
| Frontier admission | `_retain_line` applies the same gate before `StrategicFrontier.consider` | Consulted. A refusal here increments `safe_prunes`. It does not increment `dropped_full` |
| Frontier order | `line_priority` uses `g + admissible_remaining` as a sort key | Not a prune. The frontier docstring still says so |
| Cheaper finished game | `_adopt` stores the route only when independent replay solves the board and the cost is strictly below the verified incumbent | The ceiling becomes that cost. `improved` becomes true. Search continues unless the played actions are the supplied route |
| Timeout, step limit, stall, exhaustion | The partial line stays the reported trajectory. `best_verified_cost` stays the verified incumbent | Retained. A partial `g` is not written over it |
| Excavation | `_cached_excavation` caps `max_cost` with `lock["cost_ceiling"]`, which the controller sets to `max(0, ceiling - g - 1)` | Applied only when a ceiling exists. A miss keeps the existing probe category. It is not a permanent infeasibility |
| Constructive kernel | `_kernel_fallback` runs only when `goal` is `play`, status is `EXHAUSTED`, the portfolio has stopped, and legal moves remain. It passes `cost_ceiling = ceiling - 1` and `lower_bound_fn = admissible_remaining`. The kernel prunes when `g + h > ceiling - 1` | Same numeric rule, on that path only. The foundation pilots in this release did not enter it |
| Production registry | Not opened for write | Untouched |

`estimate_remaining`, debt, tableau-assembly preview, same-suit bonds, and `FOUNDATION_FACE_DOWN_WEIGHT` still order candidates. They are not passed to `proof_prune`.

Before this release the active-line comparison was already live in `optimise` mode. It was not applied when a line was admitted to the frontier. The CLI stored the replayed cost of any file that did not raise, including a partial game. There was no update when a cheaper finished game appeared, and no separate count of safe prunes, heuristic exclusions, and resource stops.

## 3. Solve mode

`cold` is unchanged: no incumbent sequence, default goal `play` unless the caller asks for foundations.

`solve` is the complete-game mode. It also rejects an incumbent sequence. With the default goal `play`, the CLI switches the goal to `foundations` and the target to 8. An explicit foundation target is left as given. Success is `SOLVED_VALID` after independent replay. The cost is then `best_verified_cost`, `incumbent_source` is `discovered`, and `new_discovery` is true.

On the constructed board in section 9, `solve` returns `move 1 2 12`, corrected cost 1, `SOLVED_VALID`.

`solve-optimise` runs that independent solve first. A supplied incumbent is invisible to the solve stage. If the solve stage finishes, the remaining time is an optimise stage whose ceiling is the discovered cost, labelled `discovered`. If the solve stage does not finish and a verified incumbent was supplied, the remaining time uses that incumbent and labels it `imported`. If neither route exists, the result is the partial trajectory and `best_verified_cost` is empty.

The unit check with `max_steps=0` and a verified cost-3 incumbent reports `best_verified_cost=3`, `improved=false`, `incumbent_source=imported`, and `solve_stage_completed=false`. The same board with a normal step budget discovers cost 1 in the solve stage and does not label the waste route as the answer.

## 4. Verified incumbent loading

`verify_complete_solution` clones the opening, replays every action, and requires a solved board: eight foundations and an empty stock. `expected_cost`, when passed, must equal the replay. The opening is not mutated.

| Check | Result on this tree |
| --- | --- |
| `solutions/4925153_autonomous_185.moves` | 189 actions, corrected cost 185, 8 foundations, solved, stock empty. Experiment A replayed it in 0.002 s |
| `solutions/4925153_canonical.moves` | 174 actions, corrected cost 172, 8 foundations, solved. Separate from the 185 file |
| First moves of the 185 file, or one legal opening move | Rejected. The message contains `partial trajectory` |
| `expected_cost=184` on the 185 file | Rejected. The message contains `incorrect cost` and the replayed 185 |
| An illegal action | Rejected. The message contains `illegal incumbent` |

The CLI prints the rejection and returns exit 2. A `--time-limit 0` optimise load of the 185 file prints:

```text
BEST_VERIFIED=185
IMPROVED=false
SEARCH_STATUS=TIME_LIMIT
```

`prefix_injected` is false. `solutions/4925153_incumbent.json` keeps its modification time. `solve()` still accepts a numeric ceiling that is looser than a supplied action list. The v0.107 test that passes the short solution with `incumbent_mw=10` still reproduces that solution. The file loader does not use that looser path. It sets the ceiling to the replayed cost.

## 5. Lower-bound audit

`admissible_remaining` is the proof value.

| Bound | Rule | Where it may be used |
| --- | --- | --- |
| `compute_solution_lower_bound` | Remaining deals, plus the paid tableau moves still required after each deal is allowed to flip at most ten cards and each paid tableau move is allowed to flip at most two. The naive sum of face-down cards plus deals is recorded and marked inadmissible | Every state. This is `h_admissible` |
| `stock_empty_assembly_h` | Assembly lower bound. Defined as 0 while any stock row remains | `admissible_remaining` takes it only when `stock_rows` is 0 |
| `estimate_remaining` | Admissible remainder plus debt, and, while stock remains, a tableau-assembly preview | Ordering only |
| Same-suit bonds, foundation-aware bonds, `FOUNDATION_FACE_DOWN_WEIGHT` | Structural order | Frontier order and reports. Not a prune |
| Campaign cost, receiver gaps, probe node counts | Search effort and diagnostics | Not a proof that a line can never beat the incumbent |

On the stocked preparation fixture, `stock_empty_assembly_h` is 0 and `admissible_remaining` equals `h_admissible`. `estimate_remaining` is strictly larger. A ceiling equal to the proof bound prunes the opening and names that admissible value in the event. A ceiling one above the proof bound plays a move. The larger estimate does not supply the event.

On the constructed endgame, stock is empty, the proof bound is 1, and the stock-empty assembly bound is at least 1. `admissible_remaining` is the max of the two. A whole-column king move onto an empty column costs 0. `proof_prune(0, h, h + 1)` is false. `proof_prune(1, h, h + 1)` is true. The free move does not spend corrected cost, so it does not meet a ceiling that an action-count of 1 would meet.

If a state had no applicable admissible bound, the safe value would be 0. The live prune does not need that substitute. It calls `admissible_remaining`.

## 6. Pruning

The gate is one comparison: `g + admissible_remaining >= ceiling`. It is counted once, as `safe_prunes`, and also stored under `pruned_by_incumbent` and `pruned_by_admissible_bound` so the two names in the brief are not added together. The provenance text says it is one gate.

The opening of the constructed board has admissible remainder 1. `optimise` with ceiling 1 returns `EXHAUSTED`, no actions, and an `incumbent bound:` event. Ceiling 2 solves at cost 1.

Heuristic capacity is `dropped_full`. A frontier of limit 2, offered four structurally different states at the same cost, leaves at least one unexpanded. A pruned micro search reports `heuristic_exclusion_is_not_proof` true, `safe_prunes >= 1`, and `heuristic_exclusions == 0`. The 150-second pilots report the opposite shape: `safe_prunes=0` and `heuristic_exclusions=10`. Those ten lines were left unexpanded because the frontier held 8. The stop text says the stall is not a proof that every continuation is exhausted.

`same_move_eliminations` counts a repeated action from the same physical state under another campaign label. That is one history. It is not an incumbent prune and not a cheaper-ancestry discard.

Resource stops are `TIME_LIMIT`, `MEMORY_LIMIT`, and `STEP_LIMIT`. The time-limit unit check reports `resource_stops >= 1` and keeps the verified cost. The 150-second pilots stopped as `PLANNING_STALL` with `resource_stops=0`. Their elapsed times are 150.043 s, 150.035 s, and 150.055 s. The stall text is the status the controller already uses when legal moves remain.

## 7. Transposition and dominance

`canonical_state_key` is the suit and rank layout. It includes face-down and face-up separation, stock, and foundations. It does not include Python object identity. A clone keeps the same card objects. A second card that compares equal and sits in the same layout shares the key. A different foundation count, a hidden card versus a face-up card, or a different stock is a different key.

Controller rule: the first visit stores `best_g`. A later visit of the same key at a higher corrected cost is discarded. The event is `transposition: discarded a more expensive ancestry`. The counter is `dominance_discards`.

Frontier rule, unchanged in behaviour: a higher `g` adds its campaign label to the cheaper snapshot and does not play the expensive ancestry (`transpositions`). An equal `g` with a different label or forced candidate stays, up to the cap. `dropped_full` is that cap. Admissible cost sorts the queue. It does not prune inside the frontier. The controller now refuses a line before `consider` when the incumbent gate fails. That refusal is a safe prune.

The 150-second pilots recorded `state_dominance_discards=0` and `frontier_transpositions=0`. They did record `same_move_eliminations` of 1361, 1338, and 1348. Those are repeated physical moves, not cheaper-ancestry wins.

## 8. Statuses and provenance

| Situation | `search_status` | `best_verified_cost` | `improved` | `incumbent_source` | Reported actions |
| --- | --- | --- | --- | --- | --- |
| Independent solve finishes | `SOLVED_VALID` | That replayed cost | false | `discovered` | The new route |
| Imported incumbent, search does not finish | `TIME_LIMIT`, `STEP_LIMIT`, `PLANNING_STALL`, or `EXHAUSTED` | The imported cost | false | `imported` | The partial or empty trajectory |
| Strictly cheaper finished route replays | `SOLVED_VALID` | The new cost | true | `discovered` | The new route |
| Supplied route is played again at the same cost | `SOLVED_VALID` | The verified cost | false | `imported` | That route. `reproduced_incumbent` is true |
| Solve stage fails, imported incumbent remains, optimise does not beat it | The optimise stop | The imported cost | false | `imported` | Partial or empty |
| Cold or solve with no finished game | The stop | empty | false | `none` | The partial trajectory |

`reported_trajectory` is `complete`, `partial`, or `empty`. `partial_g_is_not_the_best_complete_route` is true when a verified complete cost exists and the reported line is not a solved replay. `prefix_injected` and `assisted_suffix` stay false. Known-suffix reuse was not added. `--root post-sd3` remains diagnose-only.

`PLANNING_STALL` and a full frontier are not certificates of optimality. `GRAPH_EXHAUSTED_WITHIN_BOUND`, `PROBE_LIMIT`, `NODE_LIMIT`, and `TIME_LIMIT` on an excavation remain bounded misses. A tactical timeout does not write a permanent infeasibility for the campaign.

## 9. Controlled improvement

The fixture is seven completed foundations, `QH`–`AH` on column 1, and `KH` on column 2. It is not deal 4925153.

| Route | Actions | Corrected cost | Replay |
| --- | --- | --- | --- |
| Solve / cold | `move 1 2 12` | 1 | `SOLVED_VALID`, source `discovered` |
| Waste incumbent | ace off the run and back, then `move 1 2 12` | 3 | Verified before search |
| Optimise from the waste route | `move 1 2 12` | 1 | `improved=true`, `best_verified_cost=1`, `replay_ok=true`, source `discovered` |

Experiment E measured the replacement at 0.044 s and peak RSS 26.67578125 MB. Passing the cost-1 route back with a loose ceiling of 10 reproduces it and leaves `improved` false. A partial or empty search whose `g` is 0 keeps `best_verified_cost` at 3 or 1, whichever incumbent was verified. `g=0` is not reported as a better finished game.

`solve-optimise` on the same board, given the cost-3 route, still returns the discovered cost 1. The waste route is not injected into the solve stage.

## 10. MW 185 integration

Experiment A replayed `solutions/4925153_autonomous_185.moves` from `deals/4925153.txt`. Cost 185, 8 foundations, solved, stock empty, 189 actions, 0.002 s. Provenance is `imported`. This was not a new cold discovery.

Experiment B then ran optimise from the opening with that ceiling. Profile as in section 1. Goal `foundations`, target 8.

| Field | Measured |
| --- | --- |
| Before | 185, imported |
| After | 185 |
| `IMPROVED` | false |
| `SEARCH_STATUS` | `PLANNING_STALL` |
| Played line | 47 actions, corrected `g=47`, spades removed, 1 foundation |
| Spades removal inside that line | corrected cost 19 (`S#1 removed at corrected cost 19`) |
| End state | 24 face-down, 20 stock cards, 3 deals, 0 empty columns, admissible remainder 4, `g + admissible = 51`, solved false |
| Safe prunes | 0 |
| Bounds evaluated | 1529 |
| States evaluated | 1506 |
| Unique states | 84 |
| Heuristic exclusions | 10 |
| Frontier | generated 22, explored 7, still queued 5, transpositions 0 |
| Same-move eliminations | 1361 |
| Dominance discards | 0 |
| Elapsed | 150.043 s (wall 150.573 s) |
| Peak RSS | 62.12 MB |
| `prefix_injected` | false |
| `ceiling_final` | 185 |

`51 < 185`, so the incumbent gate correctly did not fire. The partial is labelled partial. It is not a better solution than the complete 185. Decisions on the played line: REVEAL 9, SAME_SUIT 58, ACCESS 35, DEAL_NOW 5, FOUNDATION 1, STRETCH 5, TACTICAL 2, ALIGN 4, PREPARE 8, PARK 9. 136 decisions, 55 achieved, 53 failed, 1 widen, 1420 backtracks.

The stop text names five legal tableau moves still open: `move 2 8 1`, `move 2 3 3`, `move 3 4 3`, `move 5 8 1`, `move 7 8 1`. Campaigns entered were `H#1`, `D#1`, and `C#1`. `S#2` was not entered. Feasibility was `SUSPENDED`. The text says a probe limit is not infeasibility.

## 11. MW 172 comparison

`solutions/4925153_canonical.moves` was verified on its own, then used as a separate optimise ceiling. It was not written over the 185 baseline, and the two runs were not merged.

The 172 pilot played the same 47 actions as the 185 pilot and as the cold pilot. End state is the same: `g=47`, spades, 24 face-down, 20 stock cards, admissible 4, `g + admissible = 51`. `51 < 172`, so this ceiling also did not prune.

| Field | 185 ceiling | 172 ceiling |
| --- | --- | --- |
| `BEST_VERIFIED` | 185 | 172 |
| `IMPROVED` | false | false |
| `SEARCH_STATUS` | `PLANNING_STALL` | `PLANNING_STALL` |
| Safe prunes | 0 | 0 |
| States evaluated | 1506 | 1485 |
| Bounds evaluated | 1529 | 1508 |
| Unique states | 84 | 84 |
| Heuristic exclusions | 10 | 10 |
| Queued lines | 5 | 5 |
| Elapsed | 150.043 s | 150.035 s |
| Peak RSS | 62.12 MB | 62.42 MB |
| Same-move eliminations | 1361 | 1338 |
| Objectives attempted | 136 | 138 |

The played moves match. The small gaps in attempts, bounds, and same-move counts are extra failed probes under the clock. They are not a different route and they are not evidence that 172 pruned more of the tree. Both ceilings sit above the region this 150-second policy reached.

## 12. Cold full-game attempt

`solve` from move 0, no incumbent file, target 8, same 150-second pilot.

| Field | Measured |
| --- | --- |
| `BEST_VERIFIED` | none |
| `IMPROVED` | false |
| `SEARCH_STATUS` | `PLANNING_STALL` |
| `incumbent_source` | `none` |
| `prefix_injected` | false |
| Played line | The same 47 actions, `g=47`, spades, solved false |
| `g + admissible` | 51 |
| Safe prunes | 0 |
| States evaluated | 1495 |
| Bounds evaluated | 1495 |
| Unique states | 84 |
| Heuristic exclusions | 10 |
| Queued lines | 5 |
| Elapsed | 150.055 s (wall 150.493 s) |
| Peak RSS | 62.61 MB |
| Ceiling | none |

Cold bounds equal states evaluated. The optimise runs evaluate extra bounds at frontier admission because a ceiling exists. Cold has no ceiling, so those extra checks are absent. The move list is still the same 47 actions.

This is the same partial shape as the v0.116 cold target-3 pilot: one foundation, `g=47`, five lines queued, ten proposals unexpanded. It is not a complete game. Seven foundations remain.

## 13. Tests

`tests/test_human_strategy_v0_117.py` has 23 tests. They passed in 1.53 s on their own, then again inside the regression.

The regression command in section 17 passed 400 tests in 302.85 seconds, exit 0. That is the previous 377 plus these 23. `registry.py` was not edited.

The new tests cover the 185 replay, rejection of a partial route, a wrong cost, and an illegal action, cold and solve refusal of a known sequence, incumbent initialisation, the prune and the retain gates, a zero-cost move, the stock-empty assembly domain, heuristic exclusion as a non-proof, exact-state dominance, distinct labels at equal cost, retention after `TIME_LIMIT` and `STEP_LIMIT`, replacement only by a strictly cheaper replay, partial-`g` reporting, export and replay, a nested time guard and a cost ceiling, the g=19 and g=83 fixture replays, the clubs excavation at cost 4, and `solve-optimise` both when the solve stage finishes and when it does not.

The g=19 fixture still replays at corrected cost 19 with spades removed and `solved` false. The g=83 fixture still replays at corrected cost 83 with spades then clubs and `solved` false. The clubs excavation still returns `exposed`, cover 0, corrected cost 2, and the card is not a legal head. A `time_left` of 0.01 s returns `TIME_LIMIT`. A `cost_ceiling` of 0 caps `max_cost_limit` at 0 and does not return `PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS`.

## 14. Runtime and memory

| Run | Elapsed | Peak RSS | Result |
| --- | --- | --- | --- |
| 185 replay | 0.002 s | not sampled | verified 185 |
| Micro improvement | 0.044 s | 26.67578125 MB | 3 replaced by 1 |
| 185 optimise pilot | 150.043 s | 62.12 MB | ceiling kept, partial `g=47` |
| 172 optimise pilot | 150.035 s | 62.42 MB | ceiling kept, same partial |
| Cold solve pilot | 150.055 s | 62.61 MB | no verified complete route, same partial |
| Regression | 302.85 s | not a search RSS | 400 passed |

One worker on each pilot. None approached the 3072 MB abort. The three deal pilots together were about 7.5 minutes of search.

## 15. Known limitations

The incumbent gate is live and tested. On deal 4925153, 150 seconds of this policy never reached a state where `g + admissible_remaining` was at least 172, let alone 185. Safe pruning therefore removed nothing in those pilots. The ten unexpanded lines are a full frontier of 8. They are not a proof that a cheaper finished game is absent.

The 185 ceiling, the 172 ceiling, and the cold run played one move list. Loading a verified incumbent did not, by itself, change the strategic choices. The micro fixture is the run that shows replacement. The deal pilots show retention.

The constructive kernel's ceiling is on the play-goal exhaustion path. These pilots used `foundations` and stopped in `PLANNING_STALL`, so that kernel did not run.

The excavation cap is `ceiling - g - 1`. At a ceiling of 172 or 185 and `g=47`, the slack is far above the tactical caps of 4, 6, and 8, so those probes were not shortened by the incumbent. A miss is still not a permanent block. The pilot nevertheless stalled with legal moves left.

The live 150-second line removes spades at cost 19 and does not reach the clubs removal at 83. The g=83 trajectory remains a fixture replay, which the new test still checks. It was not the path this pilot played.

`solve()` can still be given a numeric ceiling above the cost of a supplied action list. That preserves the existing warm-ceiling test. Callers that need a verified ceiling should use the verifier or the CLI.

No cold solution of deal 4925153 was produced. The stored 185 was imported and labelled imported.

## 16. What v0.118 should measure

The pipeline can now start from a verified 185, search, and keep 185 unless a cheaper finished game replays. The next change should be judged by whether a complete-game search or an incumbent search moves that verified cost, or honestly reports the same 185 with a different prune count.

The immediate obstacle on this policy is the post-spade stall at `g=47`, with stock still present and `g + admissible = 51`. A longer run, or a change in which line is played after spades, is the measurement that can reach a region where 172 or 185 would actually prune. Widening the frontier from 8 to 32 is still a separate experiment. It would change the ten heuristic exclusions and should not be described as a proof.

The v0.116 cost-8 tableau exhaustion on the buried hearts cards was not repeated here. A higher excavation ceiling on that later board remains unmeasured. It should stay a labelled probe, not a silent cold-mode suffix.

Cold mode should continue to refuse the 172 and 185 files. A better deal route has to be played and replayed before it replaces either ceiling.

## 17. Reproduce

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py -q --tb=line
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --out artifacts/human_strategy/v0_117/experiment_b_185.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_canonical.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --out artifacts/human_strategy/v0_117/experiment_c_172.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode solve --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --out artifacts/human_strategy/v0_117/experiment_d_cold.json
```

Experiment A is `verify_complete_solution` on `solutions/4925153_autonomous_185.moves` with `expected_cost=185`. Experiment E is the constructed board in `tests/test_human_strategy_v0_117.py::test_incumbent_is_replaced_only_by_a_strictly_cheaper_replayed_route`. Measured JSON is under `artifacts/human_strategy/v0_117/` (`experiment_a_185.json`, `experiment_b_185.json`, `experiment_c_172.json`, `experiment_d_cold.json`, `experiment_e_micro.json`). That directory is gitignored.

## 18. Branch, HEAD, and status

Branch `local/solve-optimise-pipeline-v0-117`. HEAD `35eb761b0f96b11f506e3726cf07de69f0ded5cd`. The v0.117 edits are uncommitted. Do not commit them as part of reading this note.

`git diff --stat` on the tracked edits reports 432 insertions and 33 deletions across five files.

```text
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/strategic_frontier.py
 M tools/human_strategy_solver.py
?? docs/solve_optimise_pipeline_v0_117.md
?? src/spider/human_strategy/incumbent.py
?? tests/test_human_strategy_v0_117.py
```

`engine.py`, `rules.py`, `registry.py`, and the files under `solutions/` are absent from the status. No commit, push, merge, or pull request was made.
