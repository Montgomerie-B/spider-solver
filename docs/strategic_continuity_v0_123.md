# Strategic continuity v0.123

The Human Strategy Controller can recover deferred frontier lines and can excavate a buried card at the 4,500-node rung. Extra search capacity, by itself, does not produce a second foundation. The binding fault after the 220-commit ceiling was removed was repeated execution of an objective the same physical state had already failed. Stopping those repeats lets the reported line follow the historical deal. The search still completes one foundation.

No complete-game improvement was found. The verified complete references remain MW 185 autonomous and MW 172 human.

## 1. Baseline commit and branch

Repository: `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`.

Branch: `local/strategic-continuity-v0-123`.

HEAD: `514665cfae7fabbcf6982f1406ab83ccff44fc7e` (`514665c Add strategic frontier recovery and deep search v0.122`).

The tree was clean at that commit before these edits. Nothing in this version was committed, pushed, merged, or opened as a pull request.

`engine.py`, `rules.py`, corrected MobilityWare scoring, the MW 185 and MW 172 solution files, the incumbent registry, anchored optimisation, and Spider Play Lab were not edited.

## 2. Files changed

Source and tests:

- `src/spider/human_strategy/__init__.py` — schema `spider-human-strategy-0.123`
- `src/spider/human_strategy/controller.py` — commit accounting, repeat guards, partial portfolio
- `src/spider/human_strategy/foundation_direction.py` — a refused alignment is not proposed again for that suit on that state
- `src/spider/human_strategy/strategic_frontier.py` — peak frontier and deferred occupancy
- `tools/human_strategy_solver.py` — prints the strategic commit count and limit
- `tests/test_human_strategy_v0_117.py` and `tests/test_human_strategy_v0_122.py` — schema pin
- `tests/test_human_strategy_v0_123.py` — new focused tests

Report: `docs/strategic_continuity_v0_123.md`.

Measurements: `artifacts/human_strategy/v0_123/`. The capacity-only file `experiment_a_capacity.json` was written before the schema string changed, so that file still records `spider-human-strategy-0.122`. The policy and later files record `spider-human-strategy-0.123`.

## 3. Meaning of the 220-commit counter

A strategic commit is one successful objective application. The counter in `solve` increments only when an objective execution status is `achieved` or `partial`, and when a held continuation applies a step. It does not increment when:

- a proposal fails
- a frontier line is installed or recovered
- a duplicate state is recognised
- a tactical node is expanded
- a scheduling iteration runs

A revisited deal that was the whole execution decrements the counter by one. Peak and final counts are stored as `strategic_commits`, `strategic_commit_peak`, and `strategic_commit_limit`. The solver stdout line `steps=` remains `objectives_attempted`, which includes failures. `strategic_commits=` is the commit counter.

The figure 220 is the CLI value `--max-steps 220` used by the v0.122 reproduction commands. The pilot profile default is 80. The check is `commits >= profile.max_steps`. Nothing in the source hard-codes 220. When that check fires, the status is `STEP_LIMIT` and the reason keeps the substring `strategic step budget ended`, then records the count, the limit, and any lines still queued. That stop is a configured budget. It is not graph exhaustion.

A second safety check stops when `objectives_attempted` exceeds `max_steps * 4`. Its reason is `attempt ceiling ended` and, when the queue is empty, it names any deferred candidates still held. Raising `--max-steps` to 1,000 raises that attempt ceiling to 4,000. `--slice` and `--line-attempts` do not depend on the commit limit. There is no random seed in this search.

`TIME_LIMIT`, `STEP_LIMIT`, `NODE_LIMIT`, `PLANNING_STALL`, `BOUNDED_EXHAUSTED`, and `SOLVED_VALID` stay distinct. `resolve_termination` names the condition that actually stopped the run. A secondary stall is recorded only as secondary. A step limit with deferred candidates still queued says so. Heuristic cost is not an admissible prune. `proof_prune` still requires `g + admissible_remaining`.

## 4. Capacity-only experiment

Unchanged v0.122 selection policy, deal `4925153`, cold, one worker, frontier 8, memory abort 3,072 MB, tactical ladder unchanged, global budget 150 seconds, `--max-steps 1000`. Artifact: `artifacts/human_strategy/v0_123/experiment_a_capacity.json`.

| Measure | v0.122 at 220 commits | Capacity-only |
| --- | --- | --- |
| Status | `STEP_LIMIT` at 52.258 s | `TIME_LIMIT` at 150.029 s |
| Strategic commits | 220 of 220 | 232 of 1,000 |
| Unique strategic states | 219 | 230 |
| Foundations | 1 | 1 |
| Reported corrected cost | 38 | 38 |
| Eighteenth action | `move 7 8 1` | `move 7 8 1` |
| Face-down on the reported line | 26 | 26 |
| Same-move suppressions | 18 | 3,476 |
| Identical tactical skips | 338 | 7,235 |
| Peak RSS | 88.31 MB | 117.79 MB |
| Deep 4,500-node grants | 2 | 2 |
| Deferred candidates left | 16 | 16 |
| Lines still queued | 3 | 1 |

Lifting the ceiling did not complete a second foundation. It did not extend the longest shared historical action prefix past 23. The extra minute was spent replaying the same deal-delay and the same move from states the search had already seen. The binding stop became the global deadline. That is not a strategic breakthrough.

Peak frontier occupancy was 8. Peak deferred occupancy was 24.

## 5. Exact action-18 divergence

The saved g83 trajectory is a diagnostic reference. It was not loaded into cold search. Replaying it on the authoritative engine gives corrected cost 83, foundations spades then clubs, 23 face-down cards, one empty column, and an unsolved game. The buried 8H on that state is column 7 (index 6) at cover 3.

The first 17 actions are shared by the fixture and the v0.122 reported cold line. After those 17 actions the physical state is unique: corrected cost 17, no foundation, 40 stock cards, 33 face-down, 11 same-suit bonds, admissible remainder 4. Both `deal` and `move 7 8 1` are legal there. Each costs 1. No other branch reaches that parent at a different action index.

The deal leaves face-down at 33. The move reveals one card and leaves face-down at 32. `line_priority` and `outcome_rank` both prefer the move on the first key, face-down. The second key, corrected cost plus admissible remainder, also prefers the move, because the deal raises the admissible remainder by 1. Same-suit bonds prefer the deal and do not decide. This is ordering, not a rejection and not a transposition. Frontier transpositions on these runs were 0.

At the same state the portfolio's `projected` order, with the pilot profile and the portfolio consultation off, ranks `PREPARE move 1 7 1` first (projected 71.0), then `PREPARE move 7 9 1` (75.0), then `REVEAL move 7 8 1` (77.5), then `DEAL_NOW:deal` (81.0). The deal's expected benefit is slightly higher than the reveal's. Projected cost still ranks the reveal ahead. `select_candidate` names that rule `best estimated completion cost`. The live controller's reported line is then chosen by the foundation layer, which plays the reveal. `compare_before_deal` is consulted only when the chosen kind is already a deal, so it is not the selector of that reported line.

After the historical deal, `move 2 1 12` removes the spade foundation at corrected cost 19. Face-down is still 33. The progress key `face_down - 20 * foundations` is 13. The reported one-foundation line at cost 38 has 26 face-down, so its progress key is 6 and it stays ahead. The historical line does not reach 23 face-down until much later. The search does not get there. The second foundation is action 83, `move 7 1 2`, at corrected cost 83.

## 6. The 31 stock-deal branches

On the v0.122 cold artifact, 49 retained branches:

- 31 play `deal` as action 18 from the exact historical parent
- 15 play `move 7 8 1` from that same parent
- 3 are shorter and never reach the parent
- 0 play a deal at action 18 from a different parent

All 31 deal children match the historical post-deal state. All 31 then play `move 2 1 12` and remove the spade foundation. Three stop at that foundation. Twenty-six share the next actions through prefix 22. Two share prefix 23 and then leave at `move 8 10 1`. None removes the clubs foundation. None reaches action 83.

The capacity-only run has 33 deals from that same parent and 0 deals at action 18 from any other parent. Two additional branches share prefix 23. The longest shared prefix is still 23. Taking a stock deal somewhere else in another history is not one of these branches.

## 7. First demonstrated loss of strategic continuity

The reported cold trajectory leaves the historical parent at action 18 because face-down and projected cost prefer an immediate reveal. The deal is admitted: the branches above play it and complete the spade foundation.

The search as a whole then loses the historical continuation at action 23. The historical action is `move 4 2 1`. The longest cold follow that shares the action list stops at prefix 22, or in a few branches at prefix 23, whose next historical action is `move 8 10 1`. One branch later touches historical state identity 26 by a different suffix. Extra commits did not push the shared prefix past 23.

That loss is not a missing legal move, not a transposition, and not the 220-commit ceiling. The ceiling was removed and the prefix did not grow. The time that remained was consumed by repeating one move and one dormant deal.

## 8. Targeted policy correction

Three repeat loops were measured, in order, after the ceiling was relaxed. Each guard is an identity check on one physical state. None of them is a new human-playing principle, a score change, or a claim that the move is impossible from a different state.

1. Same-move cycle. A foundation delay replaced a dormant deal with `move 1 4 1`. The deal's force id had already been cleared, so the second suppression did not record it, and the deal was popped again. The force id is now captured before it is cleared. The second suppression of the same state, action, and dormant target retires that target. Same-move suppressions on the capacity run were 3,476. On the final policy run they are 32.

2. Alignment cycle. `ALIGN:S#1:2` was proposed again after it had failed, because the alignment proposal did not see the failed set. `alignment_already_refused` skips that suit's alignment on that state. A different suit is unaffected.

3. Park rebuild. When a deal is blocked, `_moves_that_meet_their_purpose` rebuilds legal tableau moves that the portfolio has already filtered. `PARK:move 4 3 8` was rebuilt and failed 3,554 times on one state, all with the reason `foundation prerequisites are still open, so the deal waits`. `purpose_met_substitutes` drops a substitute whose id, or whose concrete `move N N N` text, already failed on that state. Reclassifying the same move is not a new substitute. A different state's failure set does not hide the move.

A general guard refuses to execute a candidate id that is already in the failed set for that state. It may play a different tableau candidate. It does not substitute a stock deal: the campaign deal carries its own evidence, and stealing the portfolio deal dropped the `future stock event` evidence required by the g32 regression. A failed join that happens to use a move some other objective already tried remains a different objective. The g32 diagnostic still deals, and that deal still carries the foundation evidence.

The frontier width stays 8. Recovery still does not increment the generated count. Cheaper exact-state ancestry still dominates. Equivalent physical states do not occupy extra slots because their labels differ. `FOUNDATION_FACE_DOWN_WEIGHT` stays 20. The tactical ladder stays `(160, 0.28)`, `(800, 0.55)`, `(4500, 1.25)`.

Diagnostic runs kept under `artifacts/human_strategy/v0_123/`:

- `experiment_c_guard_miss.json` — same-move guard read a cleared force id
- `experiment_c_align_loop.json` — alignment id repeated until the attempt ceiling
- `experiment_c_park_loop.json` — one park id repeated 3,554 times on one state
- `experiment_c_before_join_fix.json` — the action-text guard also blocked a foundation join

Those files are not the policy comparison. `experiment_c_policy.json` is.

## 9. Capacity control versus revised policy

Both runs: deal `4925153`, cold, 150 seconds, frontier 8, one worker, memory 3,072 MB, `--max-steps 1000`, the same tactical limits, no stored solution and no g83 actions injected.

| Measure | A. Capacity only | B. Revised policy |
| --- | --- | --- |
| Status | `TIME_LIMIT` | `PLANNING_STALL` |
| Elapsed | 150.029 s | 94.381 s |
| Time left | 0 s | 55.619 s |
| Peak RSS | 117.79 MB | 139.22 MB |
| Strategic commits | 232 of 1,000 | 373 of 1,000 |
| Objective attempts | 443 | 753 |
| Unique strategic states | 230 | 339 |
| Foundations, best and reported | 1 | 1 |
| Reported corrected cost | 38 | 47 |
| Reported face-down | 26 | 24 |
| Reported same-suit runs / longest | 3 / 2 | 4 / 4 |
| Reported stock cards | 30 | 20 |
| Eighteenth action | `move 7 8 1` | `deal` |
| Shared historical prefix, longest | 23 | 25 |
| Branches with prefix 22 or more | 30 | 104 |
| Same-move suppressions | 3,476 | 32 |
| Identical tactical skips | 7,235 | 553 |
| Deep grants used | 2 of 2 | 2 of 2 |
| Deferred left / recoveries | 16 / 8 | 1 / 14 |
| Second foundation | none | none |

Candidate B explores more distinct states and spends the commits on new objectives. The largest single failed id is `STRETCH:create_workspace`, 47 times, across 109 distinct failed states. The busiest state has 13 failures. That is not the one-state loop.

The reported line now deals at action 18 and shares the first 22 historical actions. It then plays `move 8 10 1` where the historical line plays `move 4 2 1`. One branch shares 25 actions, reaches corrected cost 25 with 32 face-down and one foundation, and stops `EXHAUSTED` because every retained continuation was more expensive than a known ancestry. That same physical state is reached by other branches at corrected cost 23 after 23 actions. Those cheaper lines end still on one foundation; one of them has reduced face-down from 32 to 29. Dominance is doing what it should. Extending the more expensive historical spelling of that state would not be a better route.

B's lower face-down count is a structural change inside one foundation. It is not a second foundation, and the higher corrected cost is not a better complete game. The two reported lines are also in different stock stages (30 cards left versus 20), so they do not have a single total order.

B stops with the frontier empty, one deferred candidate left, and about 56 seconds left. The stop names five legal tableau moves and says the campaign offered no executable step. The status is `PLANNING_STALL`. The deadline had not elapsed. This is not `STEP_LIMIT`, not `TIME_LIMIT`, and not proof that the position is exhausted.

## 10. Distinct partial-state portfolio

The portfolio keeps the outcome-rank leader inside each foundation and stock-row stage, at most eight rows. The sort is a reading order. `heuristic_only` is true. Corrected cost is the cost so far, not an admissible total.

Final cold policy run:

| Foundations | Stock rows left | Corrected g | Face-down | Empty | Bonds | Longest run | Legal moves | Objective | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 2 | 47 | 24 | 0 | 11 | 4 | 6 | D#1 | `PLANNING_STALL` |
| 1 | 3 | 30 | 28 | 0 | 6 | 3 | 4 | D#1 | `PLANNING_STALL` |
| 1 | 1 | 48 | 28 | 0 | 12 | 7 | 9 | C#1 | `OPEN` |
| 1 | 0 | 54 | 28 | 0 | 15 | 11 | 10 | C#1 | `PLANNING_STALL` |
| 0 | 4 | 30 | 27 | 0 | 14 | 9 | 9 | S#1 | `PLANNING_STALL` |
| 0 | 5 | 11 | 34 | 0 | 5 | 4 | 5 | H#1 | `EXHAUSTED` |

The reported line is the one-foundation, two-stock-row row, because outcome rank prefers fewer face-down cards inside the comparison the controller already uses. The cost-30 line at three stock rows is cheaper and has more cards hidden. Neither row dominates the other across stages.

The historical route, after the spade foundation, still has about 32 face-down. Its progress key is worse than the reported line's 24 face-down until late in the fixture. The search does develop deal-following lines, and one of them reaches 24 face-down, but that line has not assembled the clubs foundation. No score was tuned to the historical action list.

## 11. Independent 150-second cold results

Final command result, `experiment_c_policy.json`:

- Cold, no incumbent, `cold_injection` false, prefix not injected.
- `PLANNING_STALL` at 94.381 seconds, peak RSS 139.22 MB.
- Solved false. One foundation. Corrected cost 47. 373 strategic commits of a 1,000 limit.
- Best verified complete solution: none.
- Safe whole-game prunes: 0.
- Deep grants: 2. Nodes used 41,950 of 122,280 granted.

No branch completes two foundations.

## 12. Standard 40-second global results

Optimise mode, MW 185 incumbent, `--max-steps 220`, the same worker, frontier, and memory limits. Artifact: `experiment_d_global.json`.

- Cause `TIME_LIMIT` at 40.108 seconds. Secondary `PLANNING_STALL`. The deadline is what stopped the run.
- Strategic commits 194 of 220. The 220 ceiling was not the cause.
- One foundation. Reported corrected cost 30. Face-down 28. Same-suit runs 2, longest 3. Stock 30. Empty columns 0.
- Eighteenth action: `deal`.
- Unique strategic states 190. Same-move suppressions 13. Deep grants 0, which is what the 40-second reserve rule requires (`0.15 * 40` is under the 6.5-second deep minimum).
- Peak RSS 85.47 MB.
- Best verified complete cost 185. `improved` false. The partial trajectory did not replace the incumbent.

Against the v0.122 40-second partial (cost 34, 30 face-down, 20 stock, one same-suit run), this partial has a lower corrected cost and fewer face-down cards, with more stock left. Those are different stock stages. The complete incumbent is unchanged.

## 13. Deep excavation regression

Production scheduler on the state after the 83 fixture actions. The fixture actions were not given to cold search. Coordinator horizon 90 seconds. Artifact: `experiment_e_g83.json`.

| Rung | Stop | Nodes | Corrected cost | Cover |
| --- | --- | ---: | ---: | --- |
| 160 / 0.28 s | `TIME_LIMIT` | 144 | 2 | 3 to 3 |
| 800 / 0.55 s | `TIME_LIMIT` | 312 | 2 | 3 to 3 |
| 4,500 / 12 s reserved | exposed | 2,999 | 7 | 3 to 0 |

`deep_used` 1. Non-monotone deepen 1. Elapsed 6.582 seconds. Remaining coordinator time 83.418 seconds. Replay of the seven actions is valid at corrected cost 7, and the 8H is no longer buried.

The 160-rung node count was 120 in v0.122 and 144 here. Both stops are the 0.28-second clock, so the node count moves with the machine. The 800-rung count, the exposing node, the cost, and the replay match v0.122.

## 14. Complete-incumbent verification

- MW 185 adaptive anchored smoke, 8 seconds, one region: `NO_IMPROVEMENT`, solved, cost 185, 1.533 seconds, peak RSS 33.94 MB, 79 unique states.
- MW 172 fixed anchored smoke, 6 seconds, one region: `NO_IMPROVEMENT`, solved, cost 172, 5.242 seconds, peak RSS 33.84 MB, 1,809 unique states.
- `optimise_anchored(..., mode="cold")` still raises `AnchoredRefused`.
- The g83 action list is still rejected as a complete solution.
- No partial trajectory replaced either complete incumbent.
- `anchored.py` was not edited.

## 15. Test totals

`494 passed` in 215.38 seconds. The v0.122 suite was 478. The new file adds 16 tests. The preserved suite still passes, including the g32 requirement that a diagnostic continuation deals and that the deal evidence names a future stock event.

The new tests cover commit accounting, a limit above 220, deadline and memory precedence, frontier capacity 8 with recovery that does not raise the generated count, refused alignment, same-move suppression, cheaper exact-state dominance, distinct states sharing the frontier, illegal pins, the action-18 legal pair, g83 replay and cold independence, both complete incumbents, fixed and adaptive anchored time-zero runs, the reserved 4,500-node grant, the park-rebuild filter, and the rule that a heuristic remainder is not an admissible prune.

## 16. Runtime and peak RSS

| Run | Elapsed | Peak RSS | Stop |
| --- | ---: | ---: | --- |
| Capacity-only 150 s | 150.029 s | 117.79 MB | `TIME_LIMIT` |
| Revised policy 150 s | 94.381 s | 139.22 MB | `PLANNING_STALL` |
| Optimise 40 s | 40.108 s | 85.47 MB | `TIME_LIMIT` |
| 8H excavation | 6.582 s | inside the 90 s coordinator | exposed |
| Anchored 185 | 1.533 s | 33.94 MB | `NO_IMPROVEMENT` |
| Anchored 172 | 5.242 s | 33.84 MB | `NO_IMPROVEMENT` |
| Full regression | 215.38 s | not a search RSS | 494 passed |

All search runs stayed under the 3,072 MB abort. One worker was used. Frontier capacity stayed 8.

## 17. Remaining limitations

The independent cold solver completes one foundation inside 150 seconds. It does not complete two, and it does not complete the game.

The revised reported line follows the historical deal and then leaves at action 23. The longest exact historical prefix is 25 actions and is dominated by a cheaper ancestry of the same position. That cheaper ancestry also has one foundation.

The policy search stops at 94 seconds with commits and clock remaining because the active frontier is empty and the locked campaign has no executable step, while legal tableau moves remain. That stall is named as a stall. It is not a proof.

The 40-second search still does not receive a 4,500-node grant. That is the existing deep-reserve rule.

No new complete solution was found. Best verified complete cost on this deal remains 185 for the autonomous route. 172 remains the stronger verified complete reference.

## 18. Recommended v0.124 work

Keep the commit limit configurable. Do not put the 220 ceiling back as a silent default stop when the operator has raised it. Do not widen the frontier, do not raise the tactical ladder, and do not change the face-down weight to recognise the g83 action list.

The next measured question is the `PLANNING_STALL` with legal tableau moves still on the board, an empty frontier, and unused global time. Determine whether those moves were generated and failed, or were never admitted once the locked campaign declined them. If they were never admitted, the smallest correction is to keep ordinary legal objectives available after the campaign has no step. If they were tried and failed, say so and do not invent a new principle to force them.

Preserve dominance. A more expensive spelling of a state the search already holds at a lower corrected cost should stay dominated.

## 19. Reproduction

Interpreter `py -3`. Working directory: the repository root. One worker. Do not run another heavy process beside a timed pilot.

Regression:

```
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py tests/test_human_strategy_v0_119.py tests/test_human_strategy_v0_120.py tests/test_human_strategy_v0_121.py tests/test_human_strategy_v0_122.py tests/test_human_strategy_v0_123.py -q --tb=line
```

Capacity-only control, v0.122 policy, relaxed commit limit:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 1000 --memory-mb 3072 --out artifacts/human_strategy/v0_123/experiment_a_capacity.json
```

Revised policy, same budget:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 1000 --memory-mb 3072 --out artifacts/human_strategy/v0_123/experiment_c_policy.json
```

40-second optimise, MW 185:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_123/experiment_d_global.json
```

Anchored smokes:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_autonomous_185.moves --adaptive --regions 1 --time-limit 8 --memory-mb 3072 --out artifacts/human_strategy/v0_123/experiment_f_anchored_185.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_canonical.moves --time-limit 6 --regions 1 --memory-mb 3072 --out artifacts/human_strategy/v0_123/experiment_f_anchored_172.json
```

The 8H excavation is the production scheduler (`_progressive_excavation` and `_deepen_if_scheduled`) on the state after replaying `tests/fixtures/g83_4925153_actions.json`, with a 90-second `BudgetCoordinator`. It is not a cold solve and it does not inject those actions into one.

## 20. Final Git status

Branch `local/strategic-continuity-v0-123` at `514665cfae7fabbcf6982f1406ab83ccff44fc7e`.

```
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/strategic_frontier.py
 M tests/test_human_strategy_v0_117.py
 M tests/test_human_strategy_v0_122.py
 M tools/human_strategy_solver.py
?? docs/strategic_continuity_v0_123.md
?? tests/test_human_strategy_v0_123.py
```

`git diff --stat` on the tracked edits: 7 files, 282 insertions, 10 deletions. The new test file and this report are untracked. No commit.
