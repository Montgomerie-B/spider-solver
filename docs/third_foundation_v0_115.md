# Multi-foundation progression and whole-game viability v0.115

v0.114 removed two foundations from deal 4925153 on an independent cold search: spades at corrected g=19 and clubs at corrected g=83. Six foundations remained. The clubs removal was a different ancestry from the g=74 position, where a 12-card clubs run sat under two covered kings and a tableau-only search inside corrected cost 8 removed nothing.

v0.115 stays inside that controller. After a removal, a search whose target is still ahead closes the finished campaign, drops that campaign's stock epoch and probe memory, and keeps searching. The frontier orders lines by buried cards with a bounded foundation credit, then by corrected g plus the admissible remainder. A queued line whose signature has already been tried can receive another slice. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

The cold two-foundation trajectory is unchanged. A continuation from the replayed g=83 board, and a cold search asked for three foundations, both stop at two. The strongest measured board after g=83 has corrected g=91, two foundations, and 21 face-down cards. `solved` is false. `SOLVED_VALID` was not returned.

## 1. Baseline

Schema is `spider-human-strategy-0.115`. The default artifact directory is `artifacts/human_strategy/v0_115/`.

Branch `local/third-foundation-v0-115`. HEAD `eb12e1008365c2db32c1c95ce3030c140179976b` (`Add frontier integrity and foundation bottleneck search v0.114`). The v0.115 edits are uncommitted.

Smoke still has `frontier_limit` 1, `slice_steps` 0, and `line_attempt_cap` 0. Pilot keeps 8 lines, 3 proposals, a slice of 24 new commits, and a per-line attempt cap of 48. Extended keeps 12 lines, 4 proposals, a slice of 40, and a cap of 80. Workers stay 1. Extended was not launched. Cold mode still rejects `--incumbent`. `--root post-sd3` remains diagnose-only.

A slice and a per-line cap still count new commits and new attempts since the line was installed. The global commit cap still stops the search and, when lines are queued, the stop text includes the pending count. `TIME_LIMIT` and `MEMORY_LIMIT` still do not pop. `FOUNDATION_TARGET_REACHED` does not pop. From the opening, the target counts removals during the solve. From a board that already has foundations, the count is foundations gained since the call started. A two-foundation board does not meet a target of three. `SOLVED_VALID` still requires `is_solved()`, which is eight foundations, and an independent replay.

## 2. What changed, and what was reused

The campaign ranker, the prerequisite planner, the bottleneck probe, the run guard, dominance, and the same-move rule are the v0.114 components. The edits are the ones below.

Exploration order. `line_priority` used to put foundation count first. It now starts with face-down cards minus 20 for each foundation already removed. `g + admissible` is the next key and only orders. Foundation-aware bonds are `same_suit_bonds + 12 * foundations`, so a removed suit's 12 internal bonds are not treated as lost structure. `outcome_rank` is unchanged: solved, then more foundations, then fewer face-down, then corrected g. The weight of 20 is not added to the MobilityWare cost and it does not prune. A line at g=100 is still queued when the frontier has room.

The weight leaves order unchanged among lines with the same foundation count, because the credit is constant there. Across counts, one foundation is worth about 20 buried cards. The g=19 spade board (33 face-down, credit 20, score 13) stays ahead of the opening (44 face-down, score 44). A two-foundation board with 50 face-down (score 10) loses to a one-foundation board with nothing buried (score -20).

Pop order. The first pop, and every even pop, stays in the best `max(3, proposals)` priorities. An odd pop still takes a never-explored signature outside that pool when one exists. Every fourth pop, when every outside signature has already been tried, takes the least-served outside line. A campaign label is not itself a signature.

Campaign close. `close_foundation_campaign` already dropped the horizon, the tried labels, and the resume counts. It now also drops `fork_block`, `refused_switch`, `bottleneck_cache`, `pinned_actions`, and `pending_alternate_bottleneck`, and it resets the switch counter, barren deals, and moves since the last deal. The next suit is ranked on the current board.

A local dead end. When no legal objective remains and backtracking finds nothing, the status is still `EXHAUSTED`. If the frontier queue is non-empty, the stop text says how many lines are queued and the search installs the next one. A planning stall already did this. The global step, time, and memory caps still do not.

A repeated probe. A bottleneck cache hit on `GRAPH_EXHAUSTED`, `NOT_FOUND_WITHIN_BOUND`, or `RESOURCE_LIMIT` logs that the same probe is not repeated and that the hit is not infeasibility. It returns no move. The penalty is not added to corrected g.

The removal record now stores foundation-aware bonds, the admissible remainder, the heuristic remainder, legal-move count, empty columns, and the suits already removed. The heuristic remainder is labelled as not a bound.

## 3. The g=83 checkpoint

The 83 actions are `tests/fixtures/g83_4925153_actions.json`. They were taken from the v0.114 cold line and replayed from `deals/4925153.txt`. They are a checkpoint. Cold solves do not receive them.

Replay spends corrected g=83. Spades leave at step 19 (`move 2 1 12`). Clubs leave at step 83 (`move 7 1 2`). Before that last move, column 1 is `Kc` through `3c`, eleven cards, king at the base, and column 7 holds `2c Ac` on top of `6c Ah 3s`. `can_move(6, 0, 2)` is true. After the move the foundations are spades then clubs, 26 cards, and `solved` is false. The card bag matches the opening. 104 cards. A second replay has the same canonical key.

The board, columns numbered from 1. Face-down is bottom to top. Face-up is bottom to top.

| Column | Face-down | Face-up |
| --- | --- | --- |
| 1 | empty | empty |
| 2 | `5h 9h Jh Ah 8d` | `Kd Qd 10s 9d 8s 7s Js 10h 9h 8h 7h 6h` |
| 3 | `Jc 7d` | `10c` |
| 4 | `Ac 2h Kd 10h 6h` | `7h Kh Qh Jd 10d Kh Qd Jd 10d 9d 8d` |
| 5 | `6d Ks 3h 4c` | `Kc Qh Jh` |
| 6 | `Qs Qc` | `2s 6d 5c 4d Ad 9c 8c 7c` |
| 7 | `8h` | `6c Ah 3s` |
| 8 | `2h 4h 2c` | `4s 7d 5s As` |
| 9 | `3d` | `6s 5h 4h 3d 2d 3c 2d Ad` |
| 10 | empty | `5d 9s 5d 4d 3h` |

Stock is empty. One empty column. 23 face-down. 19 same-suit bonds, 43 once the two removed suits are counted at 12 bonds each. 32 legal moves. Admissible remainder 53, so g plus the bound is 136. Heuristic remainder 88.0, which is not a bound. Exposed runs of length at least 3: hearts `10h`–`6h` on column 2, diamonds `Qd`–`8d` on column 4, clubs `9c`–`7c` on column 6. The remaining king of clubs is face-up on column 5, covered by `Qh Jh`. `3s` is the top of column 7.

The existing ranker, on this board, names four next campaigns. Estimated cost is the campaign heuristic. It is not a lower bound and it was not used as a prune.

| Label | Readiness | Estimated cost | Longest fragment | Buried cards of that suit |
| --- | --- | --- | --- | --- |
| `H#1` | excavation-led, operational | 19.0 | 5, column 2, `10h`–`6h` | 11, including `8h` on column 7 and `Ah` on column 2 |
| `D#1` | excavation-led, operational | 21.0 | 5, column 4, `Qd`–`8d` | 5, including `Kd` on column 4 and `8d` on column 2 |
| `S#2` | deferred | 30.0 | 2 | 2, `Ks` on column 5 and `Qs` on column 6 |
| `C#2` | deferred | 33.0 | 3, column 6, `9c`–`7c` | 5, including `Jc` on column 3 and `Ac` on column 4 |

Both copies are present. The finished spades and clubs are the first copy of each. Stock cannot supply another card. Hearts and diamonds are the operational pair. The ranker names hearts first. The search is then free to switch, and the runs below did switch. Space requirement on every campaign is 0. The analyser still estimates 6 park moves for hearts and 5 for diamonds. Those figures are expectations, not a plan that was executed.

## 4. Benchmark A — the two-foundation regression

Cold, from move 0, target 2, pilot, 150 seconds, 220 steps, frontier 8, proposals 3, portfolio off, one worker. No prefix.

| | Result |
| --- | --- |
| Status | `FOUNDATION_TARGET_REACHED` |
| Stop | foundation target 2 reached at corrected g 83; partial trajectory |
| Corrected g | 83 |
| Foundations | 2, spades then clubs |
| Solved | false |
| Actions | 83, last `move 7 1 2` |
| Deals | 5 |
| Elapsed | 79.887 s |
| Unique states | 92 |
| Attempted | 168 |
| Backtracks | 84 |
| Peak RSS | 85.91796875 MB |
| Prefix injected | false |
| Replay | ok, 83 MobilityWare moves, stock 0, solved false |
| Frontier | generated 23, explored 7, same-moves 1, dropped-full 9, unique histories 8, still queued 7 |

The 83 actions match the fixture with zero differences. The seven queued lines are the same seven v0.114 retained: the g=9 park, the g=17 reveal, `C#1` beside `D#1` at g=25, and four clubs alternatives at g=54 and g=68. The search stopped because the target was two. It did not play those lines. v0.114 recorded the same unique-state count, the same attempt count, and the same queue, in 87.901 s at 84.87109375 MB. The weight of 20 and the fourth-pop re-serve did not change this trajectory. Within one foundation count the face-down order is the old order.

Clubs complete at g=83 with face-down 23, bonds 19, foundation-aware bonds 43, admissible remainder 53, heuristic remainder 88.0, 32 legal moves, one empty column, stock 0. The trace names `H#1` next, epoch 5, estimated cost 19.0. Six run-guard redirects fired on the success ancestry. The first is `move 10 4 7` refused in favour of `move 10 1 7`.

## 5. Benchmark B — one more foundation from g=83

Diagnose, from the replayed g=83 state, `opening_g` 83, target one additional foundation, 150 seconds, 220 steps, frontier 8, proposals 3, slice 24, line-attempt cap 48, RSS abort 2048 MB, portfolio off. The 83 actions rebuilt the board. `solve` did not receive them. `prefix_injected` is false. The note on the result says it is a research continuation.

The ranker selected `H#1` over `D#1` at estimated cost 19.0. Hearts then hit `PROBE_LIMIT` on buried `8h` (column 7, cover 2) and buried `4h` (column 8, cover 5). The controller logged that a probe limit is not infeasibility, closed nothing, and switched. Diamonds, the second clubs, and the second spades were entered. Each yielded on its own probe limit. Buried diamonds named by the log include `7d`, `3d` on column 9 at cover 6, and `8d` on column 2 at cover 7. A later hearts pass names `2h` on column 8 at cover 6 and `Ah` on column 2 at cover 8. Recovery tried to uncover `8h` and did not. The same move was then refused when another label asked for it. `same_moves` is 10.

No stock was dealt. Stock was already empty. No foundation was removed.

The reported line adds eight legal moves and spends corrected g=91:

`move 2 5 5`, `move 7 1 1`, `move 4 2 3`, `move 9 1 2`, `move 6 3 3`, `move 3 4 4`, `move 3 2 1`, `move 4 3 4`.

Replaying the 83-action prefix plus these eight from the deal spends 91, keeps spades and clubs, adds no suit, and matches the opening bag. Face-down 21. Bonds 22, foundation-aware bonds 46. Empty columns 0. Legal moves 7. Admissible remainder 50, so g plus the bound is 141. Heuristic remainder 81.0. The empty column that g=83 had is gone. Two cards were uncovered. The admissible total rose by 5.

| | g=83 | g=91 |
| --- | ---: | ---: |
| Foundations | 2 | 2 |
| Face-down | 23 | 21 |
| Bonds / foundation-aware | 19 / 43 | 22 / 46 |
| Empty columns | 1 | 0 |
| Admissible remainder | 53 | 50 |
| g + admissible | 136 | 141 |
| Heuristic remainder | 88.0 | 81.0 |
| g + heuristic | 171.0 | 172.0 |

The heuristic sum is not a bound. It moved from 171 to 172 while the admissible total moved from 136 to 141. The continuation spent 8 and reduced the admissible remainder by 3.

A saved branch reaches g=94, still two foundations, still 21 face-down, by three extra moves ending `move 1 9 2`. `outcome_rank` keeps g=91 because the face-down count is the same and the cost is lower. Every recorded branch replays on the g=83 root.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Foundations gained | 0 |
| Elapsed | 24.945 s of 150 |
| Unique states | 23 |
| Attempted | 38 |
| Backtracks | 32 |
| Peak RSS | 41.0 MB |
| Frontier | generated 9, explored 9, same-moves 10, dropped-full 0, still queued 0 |

The stop names seven legal moves and says this is not a proof that every continuation is exhausted. Campaigns entered: `C#2`, `H#1`, `D#1`. Not entered on the final board: `S#2`, which had already been entered and yielded earlier. Feasibility: `PROBE_LIMIT`. The clock had about 125 seconds left. The limiter is the campaign layer, not the 150-second budget. Every generated line was explored. The tactical probes hit their existing bound and were not repeated. Raising the 150-second cap, by itself, does not uncover `8h`.

## 6. Benchmark C — cold, target three

Same cold command as benchmark A, with `--target-foundations 3`. No prefix. No g=19 seed. No g=83 seed.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Corrected g | 91 |
| Foundations | 2 |
| Solved | false |
| Actions | 91, and the first 83 match the fixture |
| Deals | 5 |
| Elapsed | 136.368 s of 150 |
| Unique states | 128 |
| Attempted | 362 |
| Backtracks | 265 |
| Peak RSS | 85.87109375 MB |
| Prefix injected | false |
| Replay | ok, 91 moves, 2 foundations, stock 0, solved false |
| Frontier | generated 38, explored 24, same-moves 11, dropped-full 14, unique histories 18, still queued 0 |

The two-foundation history is rediscovered. The events contain two removals and two campaign closures, then the search continues. The reported suffix is the same eight moves as benchmark B. The maximum foundation count on any recorded branch is 2.

The search did not spend the whole budget on copies of the g=83 route. Restores: 24. Run-guard redirects: 14. Three labels play one 11-action list that shares the first eight opening moves, then `move 8 3 5`, `move 8 1 1`, `move 3 1 2`, and stop `EXHAUSTED` at g=11 with 34 face-down and no foundation. `move 8 1 1` is the reveal the two-foundation run had retained at g=9. An `S#1` line reaches g=28 with no foundation and 27 face-down, last move `move 2 3 8`. The branch log also keeps OPEN slices of the spade-then-clubs ancestry at g=24, g=43, g=54, and g=67.

Fourteen proposals were refused because the frontier was full. A full frontier is capacity, not exhaustion and not a tactical-budget miss. At the stop, the queue is empty. Explored lines: 24. Retained at some point: 38. The clock had 13.632 seconds left. The status is the same planning stall as benchmark B, including the same seven legal moves and the same `PROBE_LIMIT`. The early ancestries received turns. None of them removed a third suit.

## 7. The two clubs histories

The g=74 actions are the stored v0.113 line. The g=83 actions are the fixture. Both were replayed from the deal in this session. The g=74 tactical probe was not run again.

The lines share 46 actions and the same board at corrected g=46. Column 1 is empty. Column 10's face-up is `Jc 10c 9c 8c 7c 6c 5c`, a 7-card clubs run. Column 4's face-up ends in `Qd`.

The next action is the first difference. The g=83 line plays `move 10 1 7`, which puts the run on the empty column. The g=74 line plays `move 10 4 7`, which puts the run on `Qd`. The v0.115 cold replay logs `run guard: move 10 4 7 would cover a productive run; play move 10 1 7` on the success ancestry. The guard is general. It was not given this deal's clubs sequence.

What happens after that split is observed, and the later king assembly is not the same fact as the split.

* g=83 deals at step 55 and the deal exposes `Kc` on column 7. Step 62, `move 7 1 6`, is the first king-bottom clubs run: column 1, `Kc` through `8c`, length 6. Step 82 extends it to `Kc` through `3c`, length 11. Step 83 puts `2c Ac` on `3c` and removes clubs. Cost after the split: 37. Foundations at the end: 2. Face-down 23.
* g=74 deals at step 51 and also exposes `Kc` on column 7. Step 56, `move 7 10 1`, moves that king alone onto column 10. The line never builds a king-bottom clubs run. It ends at g=74, one foundation, 24 face-down, stock empty. Column 6 is `Qc` through `Ac`, length 12. One king of clubs is on column 5 under `4d Ad 8h 7c`. The other is on column 10 under `Qh 5d`. Cost after the split: 28.

The g=83 line spends 9 more than the g=74 line and removes the suit. It is a different ancestry. It is not a deeper search of the g=74 tableau. The retained v0.114 probe of that tableau, cost 8 and 2500 nodes, returned `GRAPH_EXHAUSTED` after 288 nodes in 0.365 s, dealt nothing, and removed nothing. That result stands. It is the tableau graph inside the cost bound. It is not a proof that the position has no longer solution, and this release did not repeat the probe.

A hypothesis that fits the observations: keeping the 7-card run on an empty column left it movable, and the later dealt king became its base. The 15 actions between the split and step 62 also differ, so the empty-column move is the first structural split and not, by itself, a complete cause of the removal. The run guard remains the general rule. The clubs moves are not hard-coded.

## 8. Whole-game cost

The known completed routes are corrected MW 172 and 185. They were used only as offline numbers. Their actions were not loaded.

| Checkpoint | g | Foundations | Face-down | Stock | g + admissible | Spend still available under 172 | Spend still available under 185 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Opening | 0 | 0 | 44 | 50 | 5 | 172 | 185 |
| Spades off | 19 | 1 | 33 | 30 | 24 | 153 | 166 |
| Shared ancestor | 46 | 1 | 27 | 20 | 52 | 126 | 139 |
| Clubs off | 83 | 2 | 23 | 0 | 136 | 89 | 102 |
| Best continuation | 91 | 2 | 21 | 0 | 141 | 81 | 94 |

At g=83 the admissible total is 136, which is below 172, so the bound does not rule out a finish cheaper than either known route. It also does not show that the route is ahead. Twenty-three cards are still face-down and the stock is empty, so every remaining burial has to be cleared by tableau moves. The heuristic remainder of 88 is almost the 89 points that separate g=83 from 172, and it is not a proof.

The g=91 continuation raises the admissible total. Uncovering two cards and spending the empty column increased the lower bound. A third foundation at a high cumulative g would have been evidence that a third suit can come off. It would not, by itself, have been evidence of a competitive full game. No third foundation was removed, so that question stays open.

Completed foundations remove 12 internal bonds each. Raw bond counts are not compared across the table. Foundation-aware bonds are 0 at the opening, 13 after spades, and 43 after clubs.

## 9. Benchmark E — seed 111

`random.Random(111)` shuffled a copy of `deals/4925153.txt`. Cold, target 2, frontier 8, proposals 3, slice 8, line-attempt cap 24, 40 seconds, 50 steps, portfolio off. These are the v0.114 seed-111 limits. The deal is not 4925153's layout. No prefix.

v0.114 stopped `EXHAUSTED` at g=7 in 6.618 s, with four lines queued and a stop text that did not mention them. Unique states were 13.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Stop | 7 legal moves remain; objectives suppressed after failure; campaigns entered `C#1`, `S#1`, `H#1`; not entered `D#1`; feasibility `SUSPENDED`; explored 8; retained 13; still queued 5 |
| Corrected g | 21 |
| Foundations | 0 |
| Solved | false |
| Actions | 21, one deal |
| Elapsed | 40.014 s of 40 |
| Unique states | 37 |
| Attempted | 106 |
| Backtracks | 1119 |
| Peak RSS | 49.94140625 MB |
| Prefix injected | false |
| Replay | ok, 21 moves, stock 40, solved false |
| Frontier | generated 13, explored 8, same-moves 1042, dropped-full 0, unique histories 7, still queued 5 |

Eight restores ran, including the g=3 stretch that v0.114 restored once, the g=3 reveal, the g=8 slice, and held suits at g=7, g=12, and g=14. The same-move rule refused 1042 label replays. Seven action lists remain. The reported line is g=21, 37 face-down, label `H#1`. One recorded branch is a `TIME_LIMIT` at g=3. The overall status is the stall, and the clock was the reason the five pending lines were not started: the pop is refused in the last 0.05 s. `D#1` is one of those five. It was selected earlier in the run and was not missing from the scheduler. No foundation was removed, so there was no campaign transition to observe. Suit changes, slices, and the pending count did run on a deal other than the research layout.

## 10. Tests

`tests/test_human_strategy_v0_115.py` has 9 tests. The g=83 actions are read from the fixture and replayed. They are not passed to a cold `solve` as a policy. The third-foundation fixture is built from the real deal's card objects. Its winning move is not handed to the controller.

| Test | What it holds |
| --- | --- |
| `test_g83_replays_two_foundations_and_conserves_cards` | 83 actions, last move attaches `2c Ac` to `Kc`–`3c`, two suits off, bag conserved, solved false |
| `test_closing_a_campaign_drops_stale_obligations_and_copies_stay_distinct` | Close drops the epoch, the probe cache, and the pinned moves. The g=83 ranker still sees both copies of each suit |
| `test_two_foundations_do_not_meet_a_three_foundation_target` | A board that already has two foundations, asked for three, hits `STEP_LIMIT` with the pending-step text. Status is not `FOUNDATION_TARGET_REACHED`. The search closes the old campaign and generates a frontier line |
| `test_a_tractable_fixture_removes_the_third_foundation_on_replay` | One legal completion removes hearts. Replay adds one foundation, the suffix cost matches, and `is_solved()` is false |
| `test_foundation_count_does_not_outrank_a_prepared_line` | g=19 stays ahead of the opening. A buried two-foundation board loses to a cleared one-foundation board. The weight is 20 |
| `test_distinct_states_stay_distinct_and_labels_do_not` | Two labels on one state are one canonical key. The first two pops differ in state and actions |
| `test_a_dead_line_restores_a_queued_alternative` | An empty candidate list restores a different queued board. Cold mode does not inject the prefix |
| `test_search_limit_and_zero_cost_and_eight_foundations` | A one-node probe is `RESOURCE_LIMIT` and says it is not infeasibility. The full hearts probe removes one suit on replay. A whole-column move onto an empty column costs 0. Seven foundations are not solved. Eight are |
| `test_cold_mode_rejects_a_saved_prefix_and_a_worse_bound_stays_queued` | Cold mode plus the g=83 actions raises `ValueError` containing `cold`. A g=100 line is accepted while the queue has room |

The regression command in section 12 passed 362 tests in 301.41 s, exit 0. That is the previous 353 plus these 9. `registry.py` was not edited. Principle 11 stays CONDITIONAL, 28 ACTIVE and 2 CONDITIONAL.

## 11. What is still blocked, and what v0.116 should do

No third foundation came off deal 4925153. The best measured continuation of the g=83 line is corrected g=91, two foundations, 21 face-down, admissible total 141, about 25 seconds, frontier empty. The cold target-3 run reaches that same line, also plays the earlier openings, and stops on the same probe limit after 136.368 s. Fourteen proposals never ran because the frontier of 8 was full.

The first unresolved hearts prerequisite on the g=83 continuation is buried `8h` on column 7 at cover 2, then buried `4h` on column 8 at cover 5. The existing probe bound is corrected cost 8, 2500 nodes, and about 1.2 seconds. The cache now refuses to repeat a finished negative probe. Switching suits was tried. Diamonds, second clubs, and second spades probe-limited as well. Another 125 seconds on the same probes would not be a new search. A longer clock is not the next lever.

The g=74 cost-8 exhaustion stays a negative finding inside its own graph. It should not be repeated unchanged.

The cold two-foundation path is intact, including the seven lines that were queued when the target of two returned. With a target of three those early lines do get turns, and on this deal they do not remove a third suit either. Seed 111 shows the same scheduler changing suits and restoring queued lines on another shuffle. It removes nothing in 40 seconds, and five lines are still queued when the clock ends.

Whole-game order is already the second priority key. The g=91 continuation made that key worse. A useful next change is an excavation that can legally reduce cover on a buried foundation card when the current probe returns `PROBE_LIMIT` at cover 2, without treating the miss as infeasibility and without repeating the identical probe. Widening the frontier above 8 is a separate measurement: 14 lines were dropped for capacity on the cold target-3 run. Neither change should be bundled into a 600-second run until a short pilot shows the probe or the dropped lines doing different work.

Eight foundations are still the only finished game. Two foundations, however they were reached, are a partial trajectory.

## 12. Reproduce

Branch `local/third-foundation-v0-115`. HEAD `eb12e1008365c2db32c1c95ce3030c140179976b`. The v0.115 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py -q --tb=line
```

That command passed 362 tests in 301.41 s.

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 150 --max-steps 220 --frontier 8 --proposals 3 --workers 1 --no-portfolio --out artifacts/human_strategy/v0_115/cold_two.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 3 --time-limit 150 --max-steps 220 --frontier 8 --proposals 3 --workers 1 --no-portfolio --out artifacts/human_strategy/v0_115/cold_three.json
```

Benchmark B has no CLI root. Replay `tests/fixtures/g83_4925153_actions.json` from `deals/4925153.txt`, then call `solve` in diagnose mode with `opening_g=83`, `goal="foundations"`, `target_foundations=1`, the pilot profile, 150 seconds, 220 steps, frontier 8, proposals 3, slice 24, line-attempt cap 48, and portfolio consultation off. Pass the deal cards. Do not pass the 83 actions as `incumbent_actions`. Verify by replaying the prefix plus `result.actions` from the deal. The measured file is `artifacts/human_strategy/v0_115/g83_continuation.json`.

Seed 111 is `random.Random(111).shuffle` of a copy of the 104 cards in `deals/4925153.txt`, written back in that order and passed as `--deal`. The run was:

```text
py -3 tools/human_strategy_solver.py --deal <seed-111-file> --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 40 --max-steps 50 --frontier 8 --proposals 3 --slice 8 --line-attempts 24 --workers 1 --no-portfolio --out artifacts/human_strategy/v0_115/seed111.json
```

None of these runs loads the 172 or 185 sequences. The artifact directory is gitignored.

Files created or modified:

```text
src/spider/human_strategy/__init__.py
src/spider/human_strategy/controller.py
src/spider/human_strategy/foundation_direction.py
src/spider/human_strategy/strategic_frontier.py
tools/human_strategy_solver.py
tests/fixtures/g83_4925153_actions.json
tests/test_human_strategy_v0_115.py
docs/third_foundation_v0_115.md
```

`engine.py`, `rules.py`, `registry.py`, the solution files, and Play Lab are untouched.

## 13. Git

```text
branch: local/third-foundation-v0-115
HEAD:   eb12e1008365c2db32c1c95ce3030c140179976b
status:
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/strategic_frontier.py
 M tools/human_strategy_solver.py
?? docs/third_foundation_v0_115.md
?? tests/fixtures/
?? tests/test_human_strategy_v0_115.py
```

`tests/fixtures/` contains `g83_4925153_actions.json`. No commit, push, merge, or pull request.
