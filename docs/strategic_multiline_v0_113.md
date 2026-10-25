# Strategic multi-line search v0.113

v0.112 can change campaign, refuse an elapsed suit, and recover from a suspended prerequisite. It still plays one history. When that history stalls it returns, even if the clock and several legal moves remain.

v0.113 puts a bounded frontier around that same controller. A stall on one line restores an earlier cloned state and its corrected move list, then continues under the same time, step, and memory budget. The frontier does not add a rules engine or a second tactical kernel. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

No benchmark removed a second foundation. `SOLVED_VALID` was not returned. The strongest constructive board is a replay-valid clubs run of length 12, topped by `Ac`, at corrected g=74, with the stock empty and 24 face-down cards. Both kings of clubs are still on the tableau and neither is an exposed landing, so the run does not come off.

## 1. What a strategic node is

Schema is `spider-human-strategy-0.113`. The default artifact directory is `artifacts/human_strategy/v0_113/`.

A node is one authoritative line:

| Field | What it holds |
| --- | --- |
| `state` | A cloned `SpiderState`. Evaluation never mutates another node's state. |
| `g` | Corrected cumulative MobilityWare cost. |
| `actions` | The full replayable ancestry from the solve root. |
| `lock` | A copied campaign lock: label, alternatives, hold, yield, and `fork_block`. |
| `force_id` | A candidate the restored line may try again. |
| `payload` | The controller's cloned `_Line` when the line was queued from the live search. A cheaper-ancestry revival has no payload and is rebuilt from the stored clone. |
| `priority` | Exploration order. Lower is tried sooner. Not a prune. |
| `signature` | `(foundations, stock rows, label, face-down // 5)`, used only to keep the queue from filling with copies of one shape. |
| `token` | `(canonical state key, label, forced candidate)`. An expanded token is not queued again. |

The frontier is off unless the goal is `first-foundation` or `foundations` and `frontier_limit` is greater than 1. `--goal play` is still the v0.108 controller. Smoke keeps `frontier_limit` 1, so the previous single-line path is unchanged. Pilot keeps 8 lines and 3 proposals. Extended keeps 12 and 4. The clamps are 1–16 lines and 1–4 proposals. Workers stay 1. Extended was not launched. Pilot's own time limit is still 600 seconds; every benchmark below overrides it.

## 2. Where lines are created

Lines are queued only at consequential choices.

Before a deal, up to `proposals_per_decision` non-deal candidates that were already in the considered set are retained. Each copy adds `DEAL:{label}` to that line's `fork_block`. The proposer skips that deal id on the restored line only. The principal line still deals. A forced candidate id by itself is not enough: the foundation proposer overwrites it. The block is what makes the alternative real.

When the in-place campaign switch adopts one sibling, the siblings it will not take on that iteration are queued with `hold_label` set. The adopt cap stays at 2. The third in-place adopt still returns `None`. The frontier is how a third suit gets a turn, on its own cloned state.

After a foundation is removed, and only when the search is going on to another foundation, the other ranked suits are queued from that post-removal state with `hold_label` set. A first-foundation goal returns at the removal and does not pop those lines. A foundations goal that has already hit its target returns the same way.

A planning stall, an empty candidate list, or a transposition that has nowhere else to go inside the current line records that line and pops another. `TIME_LIMIT`, `MEMORY_LIMIT`, and `STEP_LIMIT` do not pop. A success status does not pop. Restoring a node replaces the live state, the action list, the corrected g, and the campaign lock. It clears the in-line dormant stack. It does not clear the objective cache while sitting on the same board. The event is `frontier: restore ...`.

## 3. Order, diversity, and dominance

Exploration order, lowest first, is:

`(-foundations, face-down, g + admissible remaining, -foundation-aware bonds, -stock cards, label)`.

Foundation-aware bonds are `same_suit_bonds + 12 * foundations`. Twelve is the number of same-suit bonds a king-to-ace run takes with it, so a line that has removed a suit is not punished for the bonds that left the tableau. Admissible cost is only an ordering term. The frontier does not prune on it. The only mathematical prune remains the incumbent bound inside the controller, and cold mode has no incumbent.

The reported line, when the run did not succeed, is the best `outcome_rank`:

`(solved flag, -foundations, face-down, g)`.

A removal beats a cheaper board that still has the foundation on the tableau. At the same foundation count, fewer face-down cards beat a lower g. At the same face-down count, lower g wins. Same-suit construction is not in this tuple. Section 8 shows what that did to the g=74 clubs line.

When several nodes share the front of the priority list, the pop prefers the signature that has been expanded fewer times. A full queue drops a duplicate signature first. If the incoming signature is new and every resident signature is unique, the incoming node is left unexpanded and counted in `dropped_full`. That count is capacity. It is not exhaustion, and those nodes are not marked expanded.

Dominance, for one `canonical_state_key`:

* The cheapest corrected g is stored, with the snapshot that reached it.
* A later visit with a higher g does not become its own line. Its campaign label is added to the cheaper snapshot. If that label is not already queued or expanded, a line is queued on the cheaper ancestry with that label held. The expensive ancestry is not played.
* An equal g with a different label or a different forced candidate is a second context. Both stay, up to the cap.
* A later visit with a lower g replaces the snapshot. Queued nodes at the old g are dropped and their labels stay available for the new snapshot.
* A full queue leaves a line unexpanded. It does not mark it exhausted.

The cheaper line can consider the union of labels. It does not inherit the other line's failed-candidate set in reverse: a candidate id that has already failed on that physical state stays failed for every line at that state. `fork_block` is per lock, so a refused deal does not spread to the principal.

These runs recorded zero transpositions. The dominance rule is covered by `test_dominance_keeps_the_cheapest_ancestry_and_its_other_label`, which offers the same opening at g=10 as `D#1` and at g=14 as `H#1`, keeps g=10, and still accepts `C#1` at g=10 as its own line.

## 4. Tests

`tests/test_human_strategy_v0_113.py` has eight tests. Recorded g=19 and g=32 actions are fixture oracles. Cold solves in that file do not receive them.

| Test | What it holds |
| --- | --- |
| `test_two_branches_keep_separate_states_and_histories` | The opening and the g=19 board are both queued. Their action lists differ, their canonical keys differ, and clearing one stock does not change the other. |
| `test_dominance_keeps_the_cheapest_ancestry_and_its_other_label` | A higher g does not become its own line. Its label is retained. An equal g with another label is queued beside the cheap line. |
| `test_a_cheap_line_does_not_outrank_a_foundation_or_an_excavation` | The g=19 board outranks the opening despite the higher g. A synthetic line with fewer face-down cards outranks g=19. A removal at g=30 outranks the opening at g=0. |
| `test_frontier_stays_inside_its_cap_and_a_failed_pop_leaves_the_rest` | A limit of 3 retains at most 3 of 9 legal states, counts a capacity drop, and a pop leaves the rest queued. |
| `test_cold_first_foundation_is_unchanged_when_the_frontier_is_on` | Frontier 4, cold, no prefix. `FOUNDATION_REACHED`, solved false, g=19, the exact 19 actions. |
| `test_a_deal_retains_a_preparation_alternative` | A foundations run emits `instead of the deal`, generates at least one line, and every reported branch replays. |
| `test_g32_stall_restores_another_line_and_replays` | Diagnose from the replayed g=32 board. The suffix is not injected. The trace retains and restores. At least two distinct action lists. Every branch replays. The returned actions replay to the reported g and foundation count. |
| `test_cold_mode_refuses_a_prefix_and_zero_cost_scoring_holds` | Cold mode with an incumbent raises `ValueError` containing `cold`. A whole-column `8h` onto an empty column with no face-down costs 0. A deal costs 1. |

The new file passed 8 tests in 47.33 s. The regression command in section 12, including that file, passed 337 tests in 260.22 s, exit 0. That is the previous 329 plus these eight. `registry.py` was not edited. Principle 11 stays CONDITIONAL, 28 ACTIVE and 2 CONDITIONAL.

`SOLVED_VALID` still requires `is_solved()` and all eight foundations gone. The first-foundation result has one foundation and `solved` false. The eight tests do not themselves start from the g=26 fixture. Benchmark C does, and it uses the same restore path the g=32 test locks.

## 5. Benchmark A — cold first foundation

Cold `--goal first-foundation`, frontier 4, proposals 3, 40 seconds, 80 steps, one worker, RSS abort 2048 MB, portfolio consultation off. No prefix.

| | Result |
| --- | --- |
| Status | `FOUNDATION_REACHED` |
| Solved | false |
| Partial trajectory | true |
| Corrected g | 19 |
| Foundations | 1, campaign `S#1`, exact cost 19 |
| Deals | 2 |
| Actions | the same 19 as v0.110 and v0.111, ending at `move 2 1 12` |
| Unique states | 20 |
| Elapsed | 7.143 s of 40 |
| Peak RSS | 44.88 MB |
| Prefix injected | false |
| Frontier | generated 5, explored 0, dropped 1, still queued 4 |

The goal returns at the removal, so the four retained deal alternatives were not played. They are still real lines, saved at the deals inside the spade build: `PARK:move 2 5 1` at g=9, and `PREPARE:move 1 7 1`, `PREPARE:move 7 9 1`, `REVEAL:move 7 8 1` at g=17. One earlier reveal at g=9 was dropped because the queue of 4 was full. The g=19 route is unchanged. The delayed-opening alternatives exist and were not required once the first foundation had been removed.

## 6. Benchmark B — from the g=19 board

Diagnose, opening g=19, `--goal foundations --target-foundations 1` (one further removal), frontier 8, proposals 3, 70 seconds, 120 steps. The continuation was not injected. Root replay: g=19, 1 foundation, 33 face-down, 1 bond, 30 stock.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Solved | false |
| Corrected g | 26 |
| Foundations during the solve | 0 further; the board still has 1 |
| Face-down / bonds / stock | 31 / 2 / 30 |
| Admissible remaining | 4 |
| Heuristic remaining | 55.0, not a bound |
| Elapsed | 4.656 s of 70 |
| Unique states | 8 |
| Backtracks | 7 |
| Frontier | generated 4, explored 4, still queued 0 |

All five recorded branches replay. All five play the same seven actions: `move 8 10 1`, `move 1 3 1`, `move 8 1 1`, `move 8 3 1`, `move 6 8 1`, `move 10 9 2`, `move 10 9 1`. That is the v0.112 cold suffix. The labels on those branches are `C#1`, `D#1`, and `H#1`. The stalls name `move 9 10 1` as the remaining tableau move. Feasibility is `SUSPENDED` or `DEFERRED_BY_STOCK`. `S#2` is entered on some of the restored locks and not on others. None of those restores changed a card.

The forks were taken at g=25 and g=26, after the seven moves had already been played. Restoring them put back that same ancestry with a different `hold_label`. The search did return to a saved decision, and it did try other suits. It did not produce a second action prefix. The queue was empty with 65 seconds left. That is exhaustion of the retained lines. It is not evidence that every legal continuation from g=19 has been tried. A different second foundation would have to be queued at g=19, before those seven moves. This diagnose call starts after the removal, so the post-removal hook never ran.

## 7. Benchmark C — the three stall roots

Each root was replayed from the opening with `apply_action` and then solved in diagnose mode. Opening g is the replayed cost. Target is one further foundation. Frontier 8, proposals 3, 40 seconds, 80 steps. The suffix was not injected. `prefix_injected` is false on every run.

The roots match the earlier checkpoints:

| Root | g | Foundations | Face-down | Stock |
| --- | ---: | ---: | ---: | ---: |
| g26 | 26 | 1 | 31 | 30 |
| g32 | 32 | 1 | 29 | 30 |
| g52 | 52 | 1 | 29 | 0 |

### g26

`PLANNING_STALL` at corrected g=27. One action, `move 9 10 1`, on every branch. Face-down stays 31. Bonds stay 2. Stock stays 30. Two diamond fragments of length 2 appear, tops `10d` and `9d`. Admissible remaining 4. Heuristic remaining 55.0, not a bound. Elapsed 1.038 s. Unique states 2. Generated 4, explored 4, queue empty. Peak RSS at this point in the process was 44.88 MB.

The controller stops because the campaigns it is willing to enter cannot name a next prerequisite, not because the position has no legal move. After `move 9 10 1` the reverse, `move 10 9 1`, is still legal. The stall lists it. Restored suits (`C#1`, `D#1`, `H#1`, `S#2`) each replay that same one-move ancestry and stall again. `S#2` is entered on the last branch and still plays only `move 9 10 1`. Feasibility on the reported line is `SUSPENDED`. A probe limit is named in the reason and is not treated as infeasibility.

This is a real restore of an earlier lock onto a cloned state. It is not a different trajectory. The open legal move is a reverse of the move just played, and no retained line had a different prefix to try. With the queue empty, the remaining 39 seconds were not spent.

### g32

The principal line reproduced the v0.112 continuation exactly and stalled at g=52: 20 actions, stock 0, face-down 29, bonds 12, clubs run of length 7 on column 6 topped by `3c`, hearts fragment of length 2 topped by `9h`. Nine tableau moves remain. Campaigns entered: `H#1`, `D#1`, `C#1`. Not entered: `S#2`. Feasibility `PROBE_LIMIT`.

The search then restored `C#1`, which had been held beside `H#1` at g=32, and played a different first action: a deal, rather than `move 9 8 2`. That line was still running when the 40-second budget ended.

| | v0.112 line, preserved | Alternative, reported |
| --- | --- | --- |
| Status | `PLANNING_STALL` | `TIME_LIMIT` |
| Corrected g | 52 | 64 |
| Foundations | 1 | 1 |
| Face-down | 29 | 24 |
| Bonds (adjusted) | 12 (24) | 15 (27) |
| Stock | 0 | 10 |
| Longest clubs fragment | 7, top `3c` | 5, top `4c`, plus a clubs 4 topped by `8c` |
| Admissible / heuristic | 72 / 117.0 on the known g=52 board | 8 / 56.5, heuristic not a bound |

Both lists replay. The alternative excavated five cards and kept one stock row. It did not build a longer single run than the clubs 7, and it did not remove a foundation. The reporter returned it because 24 face-down beats 29. Elapsed 40.562 s. Unique states 53. Deals on the reported line: 2. Backtracks 7. Generated 13, explored 1, dropped 4, still queued 8.

Still unexpanded when the clock stopped: `S#2` beside `H#1` at g=32; parks instead of the deals at g=33, g=44, and g=47; `STRETCH:create_workspace` and `PARK:move 2 4 2` at g=32; `PREPARE:move 10 7 1` and `SAME_SUIT:move 5 4 3` at g=52. The clubs continuation is not assumed to be the better line. It is the preserved stall. The deal-first line is the one that moved face-down, and it stopped because the shared clock ran out.

### g52

Stock is empty on entry. The exposed structure is the clubs run of length 7, `9c` through `3c` on column 6, and a hearts run of length 2 topped by `9h` on column 2. `C#1` is `excavation_led`, estimated cost 14, longest fragment 7, operationally attainable. `D#1`, `H#1`, and `S#2` are `deferred`. All four target epochs have elapsed. Current epoch is 5.

Buried clubs, which a foundation still needs around that run: `Jc` column 3, `Ac` column 4, `4c` column 5, `Qc` column 6 under the run, `2c` column 8, `8c` column 9, `Ac` column 10. Face-up `Kc`, `Qc`, and `2c` also sit on column 7, and another `Kc` is face-up on column 5, under `7c`. No legal move in the stall list picks the seven clubs up onto an exposed king.

Three campaign lines were restored. Two physical suffixes came out:

| Suffix | g | What it did |
| --- | ---: | --- |
| `move 4 1 1`, `move 3 1 1` | 54 | Parks onto column 1. The clubs 7 and the hearts 2 stay exposed. Bonds stay 12. Face-down stays 29. Eight tableau moves remain, including the moves that shift the clubs run. |
| those two, then `move 3 6 1` | 55 | Puts `2d` onto `3c`. The exposed clubs fragment disappears. The seven clubs are still in the column, under an off-suit deuce. Bonds stay 12. Two tableau moves remain. |

The reporter kept g=54. The event is `frontier: report g=54 foundations=1 face-down=29 over a later line`. Same face-down, lower g. That choice also happens to keep the exposed run. `S#2` was entered on the g=55 branch (`not entered: none`) and the actions were still those three moves. Admissible remaining on the reported board is 72. Heuristic remaining is 117.5, not a bound. Elapsed 5.562 s of 40. Unique states 4. Generated 3, explored 3, queue empty. No foundation. The stock-empty position was not declared dead. The retained alternatives were played, they did not reveal a buried club, and then there was nothing left in the frontier.

## 8. Benchmark D — cold, 150 seconds, two foundations

Cold from move 0, `--goal foundations --target-foundations 2`, frontier 8, proposals 3, 150 seconds, 220 steps, one worker, RSS abort 2048 MB, portfolio consultation off. No reference moves and no g=19 prefix were passed in. `prefix_injected` is false. The first 19 actions are the g=19 spade removal anyway.

| | Reported line |
| --- | --- |
| Status | `TIME_LIMIT` |
| Solved | false |
| Corrected g | 52 |
| Foundations | 1 (`S#1` at cost 19). Target was 2. |
| Deals | 3 |
| Face-down / bonds / stock | 24 / 12 / 20 |
| Empty columns | 1 |
| Fragments | spades length 2 top `7s`; clubs length 7 top `5c`; clubs length 2 top `Ac`; diamonds length 2 top `10d` |
| Admissible remaining | 4 |
| Heuristic remaining | 49.0, not a bound |
| Unique states | 84 |
| Objectives attempted | 270 |
| Backtracks | 189 |
| Elapsed | 150.246 s, remaining 0 |
| Peak RSS | 67.47 MB |
| Frontier | generated 21, explored 5, dropped 9, transpositions 0, still queued 7 |

Three distinct action lists were replay-checked.

The first is the g=19 prefix plus the seven-move cold suffix, four times, at g=26, face-down 31, bonds 2, stock 30. Labels `C#1`, `D#1`, and `H#1`. Same board as benchmark B. `move 9 10 1` still legal. These stalls were recorded and the search left them.

The second diverges immediately after the removal. The restore event is `frontier: restore after removal try H#1 instead of D#1 at g=19`. Its first post-removal action is `move 1 3 1`, not `move 8 10 1`. That history runs to corrected g=74 and stalls. One foundation, 24 face-down, 18 bonds, adjusted bonds 30, stock 0. The exposed clubs run is length 12, top `Ac`, on column 6: `Qc` through `Ac`. `C#1` is `excavation_led`, estimated cost 3, operationally attainable. Hearts, diamonds, and `S#2` are `deferred`. `S#2` was not entered. Nine tableau moves remain: `move 2 4 2`, `move 6 1 2`, `move 6 7 2`, `move 6 9 2`, `move 6 10 4`, `move 6 5 6`, `move 6 8 6`, `move 6 2 8`, `move 6 4 10`. None of them is a 12-card move onto a king. Both kings of clubs are face-up and covered. Column 5 has `Kc` under `4d Ad 8h 7c`. Column 10 has `Kc` under `Qh 5d`. The top of column 6 is `Ac`. Buried clubs still on the board include `Jc` column 3, `Ac` column 4, `4c` column 5, `Qc` column 6, `2c` column 8. Admissible remaining 66. Heuristic remaining 106.5, not a bound. Feasibility `PROBE_LIMIT`. This is the furthest assembly the search produced. It is not a foundation.

The third list shares that post-removal family and was the line running at the deadline: g=52, the reported line above. It still has 20 stock cards and a clubs run of 7, not 12. `C#1` on that board is `stock_gated`, estimated cost 11, with seven clubs still in the stock (`3c`, `7c`, `3c`, `4c`, `Qc`, `Kc`, `8c`).

The reporter kept g=52 over g=74 because both have 24 face-down and one foundation, and 52 is the smaller g. The 12-card run, the extra six bonds, and the campaign cost of 3 did not enter `outcome_rank`. Exploration order has the same bias one step earlier: `g + admissible` is compared before bonds, so a cheaper unfinished fork is popped ahead of the g=67 alternatives that belong to the long clubs line.

Those g=67 alternatives are still open, along with the delayed opening the cold run saved and never played:

| Still queued | g | Label |
| --- | ---: | --- |
| `PARK:move 2 5 1` instead of the deal | 9 | `S#1` |
| `REVEAL:move 7 8 1` instead of the deal | 17 | `S#1` |
| `C#1` held beside `H#1` | 23 | `C#1` |
| `S#2` held beside `C#1` | 26 | `S#2` |
| `PARK:move 3 8 1` instead of the deal | 30 | `C#1` |
| `STRETCH:create_workspace` instead of the deal | 67 | `C#1` |
| `SAME_SUIT:move 4 6 7` instead of the deal | 67 | `C#1` |

The g=9 and g=17 lines are the delayed-first-foundation openings. They were retained. They were not expanded. The clock was spent after the spade removal.

The budget was used. The stop is the 150-second limit, with seven lines still unexpanded. It is not a claim that the frontier was exhausted.

## 9. Benchmark E — seed 111

`random.Random(111)` shuffled the 104-card deal. Cold `--goal foundations --target-foundations 1`, frontier 8, proposals 3, 40 seconds, 50 steps, portfolio consultation off. No prefix from 4925153.

| | Result |
| --- | --- |
| Status | `STEP_LIMIT` |
| Solved | false |
| Corrected g | 15 |
| Foundations | 0 |
| Deals | 1 |
| Face-down / bonds / stock | 38 / 3 / 40 |
| Fragments | spades length 2 top `2s`; hearts length 2 top `3h` |
| Admissible / heuristic | 4 / 65.5, heuristic not a bound |
| Unique states | 16 |
| Objectives attempted | 201 |
| Backtracks | 186 |
| Elapsed | 10.998 s of 40 |
| Peak RSS | 67.48 MB |
| Frontier | generated 4, explored 0, still queued 4 |

The 15 actions replay. The shape matches the v0.112 seed-111 stall: one deal early, then repeated preparation until the step ceiling. The attempt cap is `max_steps * 4`, so 201 attempts ended the run while 29 seconds remained. `STEP_LIMIT` does not pop the frontier. Four lines were retained and not played: `STRETCH:create_workspace` and `REVEAL:move 5 1 1` instead of the deal at g=3 under `S#1`, and `H#1` and `D#1` held beside `C#1` at g=12. Branching is not hard-coded to deal 4925153. On this deal the step budget stopped it before a second line was entered.

## 10. What was and was not solved

No run removed a second foundation. No run returned `SOLVED_VALID`. There is no completed-game MobilityWare score.

Corrected costs of the reported lines, each replay-checked by the controller:

| Run | Reported g | Foundations | Status |
| --- | ---: | ---: | --- |
| A cold first foundation | 19 | 1 | `FOUNDATION_REACHED` |
| B from g=19 | 26 | 1 | `PLANNING_STALL` |
| C from g=26 | 27 | 1 | `PLANNING_STALL` |
| C from g=32 | 64 | 1 | `TIME_LIMIT` |
| C from g=52 | 54 | 1 | `PLANNING_STALL` |
| D cold, target 2 | 52 | 1 | `TIME_LIMIT` |
| D, explored, not reported | 74 | 1 | `PLANNING_STALL` |
| E seed 111 | 15 | 0 | `STEP_LIMIT` |

Every branch stored on those results has `replay_ok` true. A whole-column transfer onto an empty column with no face-down still costs 0. A deal still costs 1. The g=19 campaign cost is still 19. Cold mode rejects an incumbent sequence. The 172 and 185 files were not read by these solves.

Peak RSS across the one benchmark process reached 67.48 MB. No run hit the 2048 MB abort. The later figures include allocation from earlier runs in the same process. Foundation analysis remains the expensive part of each line. The play-mode kernel was not entered.

## 11. Limits, and what v0.114 should do

The frontier does explore more than one legal ancestry. The cold run kept the g=19 spade line, stalled the old g=26 suffix, and also played a different post-removal history out to a 12-card clubs run. The g=32 diagnose kept the v0.112 clubs continuation and played a deal-first alternative beside it. Restores put back a cloned state and a replayable action list.

The lines that stall in about a second are the ones whose alternatives differ by campaign label and not by action. From g=19 in diagnose mode, and from g=26, every restored suit replayed the suffix that was already on the board. A label is not a second strategy once the moves have been played.

`TIME_LIMIT` and `STEP_LIMIT` do not restore. Seed 111 stopped with four lines queued and half a minute left. The cold 150-second run stopped with seven lines queued, including the two pre-deal openings at g=9 and g=17 and the two g=67 forks on the long clubs line.

`outcome_rank` breaks a face-down tie with raw g. That is why g=52, with 20 stock cards and a clubs run of 7, was reported ahead of g=74, with a clubs run of 12 and an estimated campaign cost of 3. The search had both. The returned line is the cheaper tie-break, and that tie-break does not look at the run.

Recommended v0.114, still without a new kernel and without raising the adopt cap:

1. Queue the alternative at the decision, with its own first action, before the principal plays the shared prefix. A `hold_label` on an already-played suffix does not search a different history.
2. When a line holds a long operational run, spend the remaining budget on that line's unexpanded nodes before popping a cheaper earlier fork. The concrete nodes are the g=67 workspace and same-suit lines, and the question on that board is how to expose a king of clubs under the `Qc`–`Ac` run. Estimated cost 3 is a heuristic. The nine legal moves show the king is not a landing yet.
3. Let a step-budget stop restore one queued line when time remains. Do not do that after a real time expiry. Seed 111 is the case that currently dies with the queue full and the clock running.
4. Put foundation-aware bonds, or the longest operational fragment, ahead of raw g in the reported-line rank when foundations and face-down are equal. Keep admissible cost out of pruning.
5. Play one retained pre-deal line from g=9 or g=17 in the cold search, so a delayed first foundation is a history and not only a queued name. Keep the g=19 line as well.
6. The acceptance test is still a second replay-verified removal, then eight. More branches, a higher g, and a longer run are not that result.

Leave principle 11 CONDITIONAL until `--goal play` changes a decision the v0.107 registry test already names.

## 12. Reproduce

Branch `local/strategic-multiline-v0-113`. HEAD `4086b0433efac576b47497bf025977d43b5f0e85` (`Add foundation campaign recovery v0.112`). The v0.113 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py -q --tb=line
```

That command passed 337 tests in 260.22 s. The new file alone passed 8 tests in 47.33 s.

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal first-foundation --time-limit 40 --max-steps 80 --frontier 4 --proposals 3 --workers 1 --no-portfolio --out artifacts/human_strategy/v0_113/cold_first.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 150 --max-steps 220 --frontier 8 --proposals 3 --workers 1 --no-portfolio --out artifacts/human_strategy/v0_113/cold_two.json
```

Benchmarks B and C are diagnose solves from replayed roots, with `opening_g` set to the replayed cost and `target_foundations` 1. They are not `--root post-sd3`, and cold mode was not given those action lists. The measured summary is `artifacts/human_strategy/v0_113/benchmark_summary.json`. That directory is gitignored. The five solves together finished in 224.6 s. Extended was not run.

Files created or modified:

```text
src/spider/human_strategy/__init__.py
src/spider/human_strategy/controller.py
src/spider/human_strategy/profiles.py
src/spider/human_strategy/strategic_frontier.py
tools/human_strategy_solver.py
tests/test_human_strategy_v0_113.py
docs/strategic_multiline_v0_113.md
```

`engine.py`, `rules.py`, `registry.py`, the solution files, and Play Lab are untouched.

## 13. Git

```text
branch: local/strategic-multiline-v0-113
HEAD:   4086b0433efac576b47497bf025977d43b5f0e85
status:
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/profiles.py
 M tools/human_strategy_solver.py
?? src/spider/human_strategy/strategic_frontier.py
?? tests/test_human_strategy_v0_113.py
?? docs/strategic_multiline_v0_113.md
```

No commit, push, merge, or pull request.
