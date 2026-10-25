# Frontier integrity and foundation-bottleneck search v0.114

v0.113 kept several campaign labels and restored their cloned states. On the stalls that mattered, those labels replayed one action list. The cold 150-second run stopped at one foundation. A clubs run of length 12 sat at corrected g=74 with both kings of clubs face-up and covered, and nothing removed that second suit.

v0.114 stays inside the same controller. It refuses to replay an action that another line has already played from the same physical state, gives a queued line a bounded slice of the budget, and adds one goal-directed search for an exposed run that is one rank short of a foundation. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

The cold search from move 0, with no saved prefix, removed a second foundation. The replayed line spends corrected g=83, removes spades at g=19 and clubs at g=83, and stops because the target was two foundations. `solved` is false. `SOLVED_VALID` was not returned. Six foundations remain.

That clubs removal is not the g=74 king excavation. At g=83 the king of clubs is already the base of an 11-card run, and `move 7 1 2` puts `2c Ac` on `3c`. The g=74 checkpoint was searched separately. Both of its kings stayed covered. The tactical search returned `GRAPH_EXHAUSTED` after 288 nodes and removed nothing.

## 1. Baseline

Schema is `spider-human-strategy-0.114`. The default artifact directory is `artifacts/human_strategy/v0_114/`.

Branch `local/frontier-bottleneck-v0-114`. HEAD `0f223bb243520a0be7a52218f40549cbcba0e3f1` (`Add bounded multi-line strategic search v0.113`). The v0.114 edits are uncommitted.

Smoke still has `frontier_limit` 1, `slice_steps` 0, and `line_attempt_cap` 0, so a one-line run does not slice and does not yield. Pilot keeps 8 lines, 3 proposals, a slice of 24 new commits, and a per-line attempt cap of 48. Extended keeps 12 lines, 4 proposals, a slice of 40, and a cap of 80. Workers stay 1. Extended was not launched. The new CLI flags are `--slice` and `--line-attempts`. Cold mode still rejects `--incumbent`.

A slice and a per-line cap count new commits and new objective attempts since the line was installed. They do not count the length of the restored ancestry. Restoring a long history is legal while time and the global step cap remain. The global cap (`commits >= max_steps`) still stops the search. When that happens with lines queued, the stop text includes the pending count. `TIME_LIMIT` and `MEMORY_LIMIT` still do not pop.

## 2. Why the same moves were counted as several branches

v0.113 dominance already kept the cheapest corrected g for one `canonical_state_key`. An equal g with another label was queued on purpose, so a second suit could be tried. The controller then let that restored line play the action the first label had just played. The branch log recorded both. The histories were the same cards.

Four measurements from v0.113 located the failure:

* From the g=19 board, five recorded branches played the same seven actions and differed only by `C#1`, `D#1`, and `H#1`.
* From g=26, every restored suit played `move 9 10 1` and stalled on the reverse.
* The cold run generated lines and still had seven queued at timeout, including the pre-deal openings at g=9 and g=17. It removed one foundation.
* Seed 111 stopped at `STEP_LIMIT` with four lines queued. The global attempt ceiling (`attempted > max_steps * 4`) refused to pop.

The g=74 board was a different failure. The run `Qc`–`Ac` was real. Neither king was a legal receiver. Knowing that a king was required did not move a card.

## 3. Dominance, and what counts as a different line

The cheaper-g rule is unchanged. A later visit with a higher g is folded onto the cheaper snapshot. Its label is kept. The expensive ancestry is not played. An equal g with a different label or a different forced candidate is still queued, up to the cap. A full queue increments `dropped_full` and leaves the node unexpanded. That is capacity. Admissible cost still only orders. `outcome_rank` is still `(solved, -foundations, face-down, g)`. A length-12 run is a last key on `line_priority` only, so it can break a tie and cannot outrank a foundation or a face-down count.

What changed is the controller's memory of played edges. The key is `(canonical state, action)`.

* If the action about to be played is already in that set, the line does not play it. The event is `frontier: same move ... campaign labels are not a new history`. `same_moves` increments.
* The label stays available. A different legal action from that state is still a different history.
* When a stall finds an empty queue, up to `proposals` unplayed tableau moves are queued, skipping a move that covers a productive run and skipping the immediate reverse of the last action. Those pinned moves are the first actions of the restored lines.
* A slice snapshot is logged with `compete` false, so it does not replace the best reported line. A foundation still outranks it through `outcome_rank`.

`merges` stays the dominance counter. These benchmarks recorded `merges` 0 and `transpositions` 0. The duplicate histories were stopped by `same_moves`, after the labels had already been queued.

### From the g=19 board

Diagnose, one further foundation, frontier 6, slice 6, line-attempt cap 40, 36 steps, 30 seconds, portfolio off. No suffix was injected.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Corrected g | 25 |
| Foundations | 1 |
| Face-down / bonds / stock | 31 / 2 / 30 |
| Elapsed | 4.252 s |
| Unique states | 8 |
| Peak RSS | 43.07421875 MB |
| Prefix injected | false |
| Frontier | generated 5, explored 5, same-moves 1, unique histories 2, queue empty |

Six branch records collapse to two action lists, and both replay:

* Six moves, ending `move 10 9 2`, at g=25. Labels on that list: `H#1`, `C#1`, `D#1`.
* Those six plus `move 10 9 1`, at g=26. Labels: `D#1`, `C#1`, `H#1`.

The lists differ by one legal move. The states differ. Each list replays on its own. A slice at g=25 yielded the `H#1` line and a later pop restored it. The same-move event fired once, on `move 10 9 1`. Three labels on one list are one physical history.

This checkpoint does not grow two unrelated openings. It stops the label copies, and it keeps the one-move extension as its own replayable line.

### From the g=26 board

Same style of diagnose, from the replayed g=26 state. `PLANNING_STALL` at g=26. Elapsed 0.917 s. Unique states 2. Peak RSS 43.08203125 MB. Generated 2, explored 2, same-moves 1, unique histories 2, queue empty.

The two lists are `move 9 10 1` (g=27, `C#1`) and an empty action list at g=26 (`C#1` and `S#2`). The empty list is the stall snapshot. It is not a second tableau move. The same-move event is the refusal to play `move 9 10 1` again under another label. From this checkpoint the search still has one forward action.

### Cold evidence of real divergence

The cold run below is the stronger demonstration. After the shared 19-action spade opening, one saved line plays `move 8 10 1` and the line that removes the second foundation plays `move 1 3 1`. Eight recorded branches have eight different action lists. All eight replay. Three of them are proper prefixes of the success line and were restored after a slice. Section 7 has the counts.

## 4. Scheduling and the step budget

Pop order is still promise first. The priority tuple is unchanged except for the final length-12 tie-break. The first pop, and every even pop, stays inside the best `max(3, proposals)` priorities and prefers the signature that has been expanded fewer times. An odd pop may take the best never-explored signature that sits outside that pool. A delayed opening can receive one turn. The queue does not rotate.

A running line yields in three bounded cases, and only while another line is queued and time remains:

| Trigger | What is counted | What happens to the paused line |
| --- | --- | --- |
| Slice | New commits since install, default 24 on pilot | Requeued, then the other line is popped first |
| Per-line attempts | New objective attempts since install, default 48 on pilot | Not requeued. The global search continues |
| Global attempt ceiling | `attempted > max_steps * 4` | Yields while the queue is non-empty. The old behaviour set `STEP_LIMIT` and refused the pop |

`STEP_LIMIT` from the global commit cap still does not pop. An exhausted clock does not pop. A success status does not pop.

### Seed 111

The fixture is `random.Random(111)` shuffling a copy of `deals/4925153.txt`. Cold, target one foundation, frontier 8, proposals 3, slice 8, line-attempt cap 24, 40 seconds, 50 steps, portfolio off. No prefix.

| | Result |
| --- | --- |
| Status | `EXHAUSTED` |
| Stop | `no legal continuation under the current restrictions` |
| Corrected g | 7 |
| Foundations | 0 |
| Face-down / bonds / stock | 39 / 0 / 50 |
| Elapsed | 6.618 s of 40 |
| Unique states | 13 |
| Attempted | 16 |
| Peak RSS | 45.06640625 MB |
| Prefix injected | false |
| Frontier | generated 5, explored 1, same-moves 0, unique histories 2, still queued 4 |

One restore ran: `STRETCH:create_workspace retained instead of the deal at g=3`, label `S#1`. A slice then yielded at g=8. The two replayable histories are:

* g=8, `OPEN`, eight actions, including one deal. Face-down 41, bonds 3, stock 40. Label `S#1`.
* g=7, `EXHAUSTED`, seven actions, no deal. Face-down 39, bonds 0, stock 50. Label `D#1`.

The step ceiling did not swallow the queue. That is the repair of the v0.113 `STEP_LIMIT`. The run then left four lines queued anyway. The exit at "no legal continuation under the current restrictions" returns without calling the frontier pop. The pending count is accurate. The stop text does not say that the queue still holds lines. Those four are `REVEAL:move 5 1 1` at g=3, the g=8 slice, and `C#1` and `H#1` held beside `S#1` at g=7. No foundation was removed. The unit test uses a tighter budget and checks the same contract: a restore event, `explored >= 1`, two replayable histories, and `prefix_injected` false.

## 5. Foundation-bottleneck search

`propose_foundation_step` still returns a one-move legal completion first. The g=19 spade finish is that move, and the cold regression that locks those 19 actions still passes. Only when that one move does not exist does the bottleneck probe run.

The probe looks for an exposed same-suit run of length at least 12 with the ace on top and the bottom rank equal to the length. Any suit qualifies. Both physical copies of the missing rank are located. Face-up with depth greater than zero is not a receiver. The note on each covered copy is `face-up is not a legal receiver while cards cover this king`. Blockers are the cards above that copy. A movable suffix is recorded only when `can_move` accepts it. The search itself uses `enumerate_moves` and corrected step cost. It does not deal.

The order is a heap on `(corrected cost, disruption penalty, sequence)`. The penalty deprioritises a cover of a productive run. It is not added to g and it does not prune. A zero-cost edge pops before a one-cost edge. A state already seen at an equal or cheaper cost is not expanded again.

Statuses:

| Status | Meaning |
| --- | --- |
| `FOUND` | A popped state has one more foundation. The action list is replayed with `step_cost` before it is accepted |
| `GRAPH_EXHAUSTED` | The heap emptied inside the cost bound, the node cap and the clock were not hit, and no unseen successor sat past the bound |
| `NOT_FOUND_WITHIN_BOUND` | A successor past the cost bound was seen and not expanded |
| `RESOURCE_LIMIT` | The node cap or the time guard stopped the search |
| `NO_BOTTLENECK` | No qualifying run |

A node cap, a timeout, and `GRAPH_EXHAUSTED` do not set `PROVEN_INFEASIBLE`. `GRAPH_EXHAUSTED` describes the tableau moves inside the cost bound. The search does not deal, so a later deal from another position is outside that result. Nodes sitting on the cost bound are checked for a removal and do not generate children. On the g=74 probe, `zero_cost_expansions` was 0, so the interior of the search contained no free move that this rule could have skipped.

The live caller uses corrected cost 8, 2500 nodes, and at most 1.2 seconds. A second search runs only after `FOUND`, and only to offer the other king as an alternate plan. A found plan is a `BOTTLENECK` candidate with `hold` true, so the whole sequence stays committed. Its benefit is 12. The run guard does not redirect it. If the sequence covers the run on the way, the evidence says `fact: temporary park is recoverable`. Otherwise it says the run stays available until it moves onto the king. The result is cached on the position. A cache hit, or any status other than `FOUND`, returns no candidate and ordinary planning continues.

### Hearts fixture

This board is not deal 4925153. Twelve hearts, queen through ace, sit on column 5. Both kings of hearts are face-up and covered. Column 1 has `Kh` under `5s`. Column 6 has `Kh` under `4d 8s`. One column is empty. A face-up `9d` with nothing behind it can move onto that empty column at corrected cost 0.

`plan_foundation_bottleneck` returned `FOUND`.

| | Result |
| --- | --- |
| Actions | `move 1 2 1`, then `move 5 1 12` |
| Corrected cost | 2, replay cost 2 |
| Suit removed | hearts |
| Foundations after | 1 |
| Solved | false |
| Cheapest zero-cost edge | 0 |
| Kings | column 1 depth 1, blocker `5s`, one movable card; column 6 depth 2, blockers `4d 8s`, two movable singles |

`move 1 2 1` moves `5s` off the first king. `move 5 1 12` puts the hearts run on that king, and the completed sequence comes off. The second king stays covered. The free `9d` transfer is explored and is not the plan. One hearts foundation is not a finished game.

The same fixture with `max_nodes` 1, and again with `time_left` 0, returns `RESOURCE_LIMIT`. Both notes say the stop is not infeasibility. Neither status is `PROVEN_INFEASIBLE`.

### Test A — both club kings at g=74

The root is the replay-verified g=74 line stored on the v0.113 cold run. Replay: g=74, 1 foundation, 24 face-down, 18 bonds, stock 0. Column 6 holds `Qc Jc 10c 9c 8c 7c 6c 5c 4c 3c 2c Ac`.

Both kings of clubs are face-up. Neither is accessible.

| Copy | Column | Depth | Blockers, bottom to top | Movable runs | Investment |
| --- | ---: | ---: | --- | --- | ---: |
| 1 | 10 | 2 | `Qh`, `5d` | none | 2 |
| 2 | 5 | 4 | `4d`, `Ad`, `8h`, `7c` | none | 4 |

No suffix above either king has a legal destination on this board. The 12-card run is one piece. It cannot move onto either king while those blockers remain. Stock is empty, so a deal is illegal.

Nine legal tableau moves: `move 2 4 2`, `move 6 1 2`, `move 6 7 2`, `move 6 9 2`, `move 6 10 4`, `move 6 5 6`, `move 6 8 6`, `move 6 2 8`, `move 6 4 10`.

The direct probe used cost 8, 2500 nodes, and 5 seconds.

| | Result |
| --- | --- |
| Status | `GRAPH_EXHAUSTED` |
| Nodes | 288 |
| Actions | none |
| Corrected cost of a plan | none (the field is 0 because no sequence was accepted) |
| Foundations after | 1 |
| Zero-cost expansions | 0 |
| Elapsed | 0.365 s |

The heap emptied. The node cap and the clock were not the stop. The search dealt nothing. This is the whole tableau component inside the cost bound. It is not a proof that a sequence longer than cost 8 is impossible, and it is not a retired suit. On this particular board the stock is already empty, so there is no later deal to wait for.

The live diagnose used the same board, target one further foundation, frontier 4, proposals 3, 35 seconds, 40 steps, portfolio off. The controller called the probe. The events name both kings and both blocker lists, twice, and record `GRAPH_EXHAUSTED` each time. Feasibility on the stall is `PROBE_LIMIT`. The stop text says a probe limit is not infeasibility.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Corrected g | 74 |
| Foundations | 1 |
| Face-down / bonds / stock | 24 / 18 / 0 |
| Elapsed | 8.891 s |
| Unique states | 2 |
| Attempted | 1 |
| Peak RSS | 30.98828125 MB |
| Prefix injected | false |
| Frontier | generated 5, explored 5, same-moves 2, unique histories 2, queue empty |

Campaigns entered: `S#2`, `C#1`, `H#1`. Not entered: `D#1`. The two recorded histories are `move 2 4 2` at g=75 (bonds 19, label `D#1`, replayed) and the empty stall at g=74 (label `H#1`). `same_moves` fired twice on `move 2 4 2`. Restores also named unplayed `move 6 9 2` and `move 6 5 6`. Those seeds do not appear as their own played action lists. No second foundation was removed.

## 6. Test B — the seven-card clubs run at g=52

The root is the replayed g=19 line, the g=32 suffix, and the 20-action continuation. Replay: g=52, 1 foundation, 29 face-down, 12 bonds, stock 0. Column 6 holds `9c 8c 7c 6c 5c 4c 3c`.

`move 3 6 1` is not legal on this board. It becomes legal only after `move 4 1 1` and `move 3 1 1`, at g=54. The legal cover at g=52 is `move 4 6 1`.

| Move | Where | Cost | Covers the run | Clubs afterwards | Face-down | Bonds | Legal moves |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: |
| `move 4 6 1` | g=52 | 1 | yes | length 1, `3c` on column 9 | 29 | 12 | 3 |
| `move 4 1 1` | g=52 | 1 | no | length 7, still column 6 | 29 | 12 | 8 |
| `move 3 6 1` | after the two parks, g=54 | 1 | yes | length 1, `3c` on column 9 | 29 | 12 | 2 |

The two parks themselves leave the run at length 7, bonds 12, face-down 29, and 8 legal moves, at g=54.

The cover does not reveal a card, does not add a bond, and does not cost less than the preserving move. It cuts the run from 7 to 1 and cuts the legal set from 8 to 3. v0.113 could select it because those two moves tie on corrected g, face-down, and bonds, and nothing in the choice scored the lost run. That is a consequence-evaluation gap. It is not a required park: a legal preserving move exists at the same cost.

The guard runs only for a foundation goal, and only over candidates already in the considered set. If the chosen action covers an exposed same-suit run of length at least 7, and some other considered non-deal action does not, the guard plays the other one and logs `run guard:`. A same-suit join and a move of the whole run onto an empty column are not covers. A `FOUNDATION` or `BOTTLENECK` candidate is left alone. A candidate whose evidence contains `fact: temporary park is recoverable` is left alone, including when the action would cover the run. The guard does not invent a move outside the considered set. If every considered move covers, the cover stands.

The unit tests use this board for both sides. The unjustified `move 4 6 1` loses to `move 4 1 1` when both are considered. The same cover, tagged as a recoverable bottleneck park, is kept. There is no blanket ban.

## 7. Test D — cold search, two foundations

Cold, from move 0, pilot profile overridden to 150 seconds and 220 steps, frontier 8, proposals 3, slice 24, line-attempt cap 48, one worker, RSS abort 2048 MB, portfolio off, no incumbent. Target two foundations. The g=19, g=52, and g=74 checkpoints were not injected. `prefix_injected` is false.

| | Result |
| --- | --- |
| Status | `FOUNDATION_TARGET_REACHED` |
| Stop | foundation target 2 reached at corrected g 83; this is a partial research trajectory, not a finished game |
| Solved | false |
| Corrected g | 83 |
| Foundations | 2 |
| Deals | 5, at steps 10, 18, 31, 55, and 69 |
| Face-down / bonds / stock | 23 / 19 / 0 |
| Actions | 83, of which 78 are tableau moves |
| Elapsed | 87.901 s of 150 |
| Unique states | 92 |
| Attempted | 168 |
| Backtracks | 84 |
| Peak RSS | 84.87109375 MB |
| Prefix injected | false |
| Frontier | generated 23, explored 7, transpositions 0, merges 0, same-moves 1, dropped for capacity 9, unique histories 8, still queued 7 |

The search stopped on the second removal. It did not use the rest of the 150 seconds. RSS stayed far under the abort.

The 83 actions replay from the opening to g=83 and two foundations. The first 19 are the existing spade line. They end at `move 2 1 12`.

| Removal | Step | Action | Corrected g | Suit | Face-down | Bonds | Stock |
| --- | ---: | --- | ---: | --- | ---: | ---: | ---: |
| 1 | 19 | `move 2 1 12` | 19 | spades, `Ks` through `As` | 33 | 1 | 30 |
| 2 | 83 | `move 7 1 2` | 83 | clubs, `Kc` through `Ac` | 23 | 19 | 0 |

Immediately before `move 7 1 2`, column 1 is face-up `Kc Qc Jc 10c 9c 8c 7c 6c 5c 4c 3c`. The king is the base of that run, with ten cards above it, and `3c` is the head. Column 7 is `6c Ah 3s 2c Ac`. The move puts `2c Ac` on `3c`. The completed sequence comes off. Corrected cost of that move is 1. The other king of clubs is on column 5, face-up, with `Qh Jh` above it. It was not the receiver.

The only length-12 ace-topped run on this line was the spade run, and the ordinary completion move removed it at step 19. The clubs finish did not go through the bottleneck probe. The cold event sample that matches `bottleneck` or `run guard` contains six run-guard redirects and no `selected: foundation bottleneck` line. The substitutes the guard asked to play are on the 83-action ancestry:

| Guard refused | Guard played | Step on the success line |
| --- | --- | ---: |
| `move 10 4 7` | `move 10 1 7` | 47 |
| `move 1 4 7` | `move 3 10 1` | 48 |
| `move 1 4 7` | `move 9 4 2` | 49 |
| `move 1 5 3` | `move 10 7 1` | 52 |
| `move 1 5 3` | `move 3 10 1` | 53 |
| `move 1 4 5` | `move 10 4 1` | 67 |

Those six are measured membership in the ancestry. They are not a claim that the guard is the only reason the second suit came off.

Eight recorded branches, eight action lists, every one `replay_ok`:

| g | Status | Foundations | Face-down | Bonds | Stock | Label | How it relates to the success line |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| 83 | `FOUNDATION_TARGET_REACHED` | 2 | 23 | 19 | 0 | none | the reported line |
| 67 | `OPEN` | 1 | 23 | 22 | 10 | `C#1` | first 67 actions of the success line, a slice that was restored |
| 54 | `OPEN` | 1 | 23 | 13 | 20 | `C#1` | first 54 actions, then the success line deals |
| 43 | `OPEN` | 1 | 28 | 8 | 20 | `C#1` | first 43 actions, a slice that was restored |
| 31 | `PLANNING_STALL` | 1 | 29 | 8 | 30 | `C#1` | shares 30 actions, then `move 4 2 2` where the success line deals |
| 26 | `PLANNING_STALL` | 1 | 31 | 2 | 30 | `C#1` | shares the 19-action opening, then `move 8 10 1` |
| 25 | `PLANNING_STALL` | 1 | 31 | 2 | 30 | `D#1` | the same old suffix, one move shorter |
| 24 | `OPEN` | 1 | 31 | 2 | 30 | `D#1` | the same old suffix, sliced at g=24 and restored |

After the shared opening, `move 1 3 1` and `move 8 10 1` are different legal moves into different states. The g=31 fork is a third history: it refuses the deal the success line takes at step 31. `same_moves` fired once, on `move 10 9 1`.

Slices yielded and were restored at g=24 (`D#1`), g=43 (`C#1`), and g=67 (`C#1`). One restore after the first removal tried `H#1` instead of `D#1` at g=19. Other restores brought back a parked move at g=30 and a same-suit move at g=54.

Seven lines were still queued when the target returned:

| Reason | g | Label |
| --- | ---: | --- |
| `PARK:move 2 5 1` retained instead of the deal | 9 | `S#1` |
| `REVEAL:move 7 8 1` retained instead of the deal | 17 | `S#1` |
| `C#1` held beside `D#1` | 25 | `C#1` |
| `PARK:move 1 4 2` retained instead of the deal | 54 | `C#1` |
| `STRETCH:create_workspace` retained instead of the deal | 68 | `C#1` |
| `SAME_SUIT:move 4 6 4` retained instead of the deal | 68 | `C#1` |
| `SAME_SUIT:move 4 1 4` retained instead of the deal | 68 | `C#1` |

The g=9 and g=17 openings were kept and were not played. The success line is the spade-first history, continued past the removal. It is one possible line.

At the end, the exposed runs of length at least 3 are hearts `10h`–`6h` on column 2, diamonds `Qd`–`8d` on column 4, and clubs `9c`–`7c` on column 6. `3s` remains on column 7. This is not the g=74 board, which still has the 12-card clubs run and one foundation.

v0.113's cold target-2 run used 150.246 s and stopped at one foundation. This run reached two foundations in 87.901 s under the same 150-second and 220-step caps, with the slice scheduler and the same-move check in place. The beam width was not increased.

## 8. Tests

`tests/test_human_strategy_v0_114.py` has 16 tests. They cover the 18 required checks. The hearts board is the replay-verified bottleneck removal. The g=74 deal is not hard-coded as a solution, because that search did not find one.

| Test | What it holds |
| --- | --- |
| `test_labels_are_not_distinct_physical_branches` | Two labels and one action are one physical history |
| `test_merged_state_keeps_the_other_objective` | Folding a state keeps the other objective available |
| `test_unexplored_signature_outside_the_pool_gets_one_turn` | An odd pop can enter a never-tried signature outside the top pool |
| `test_distinct_lines_restore_with_their_own_g_and_tableau` | Two lines restore their own corrected g and tableau |
| `test_slice_services_a_pending_line_inside_the_budget` | A slice hands the budget to a queued line |
| `test_seed_111_restores_a_queued_alternative` | Seed 111 restores a queued line and replays two histories |
| `test_both_kings_are_examined_and_a_covered_king_is_not_a_receiver` | Both hearts kings are analysed. Face-up and covered is not accessible |
| `test_blocker_removal_is_a_legal_multi_action_plan` | The plan's moves are legal, and it takes more than one action |
| `test_zero_cost_edges_are_ordered_by_corrected_cost` | A zero-cost edge is recorded at cost 0 and does not replace the cost-2 plan |
| `test_the_long_run_is_preserved_until_the_king_receives_it` | The hearts run is still present until the completing move |
| `test_unjustified_cover_loses_to_a_preserving_move` | At g=52, `move 4 6 1` yields to `move 4 1 1` |
| `test_a_justified_temporary_park_stays_available` | The same cover is kept when it is marked recoverable |
| `test_a_bottleneck_plan_removes_a_foundation_on_replay` | The hearts plan replays to one new foundation and `is_solved()` is false |
| `test_a_search_limit_is_not_infeasibility` | A node cap and a zero time budget say they are not infeasibility |
| `test_a_finished_game_still_needs_eight_foundations` | Seven foundations fail `is_solved()`. Eight pass |
| `test_cold_solving_does_not_load_a_saved_prefix` | Cold mode with an incumbent raises `ValueError` containing `cold` |

The regression command in section 10 passed 353 tests in 330.18 s, exit 0. That is the previous 337 plus these 16. A narrower run of the new file together with three v0.113 regressions passed 19 tests in 62.27 s before the full command. `registry.py` was not edited. Principle 11 stays CONDITIONAL, 28 ACTIVE and 2 CONDITIONAL.

## 9. What is still blocked, and what v0.115 should do

The second foundation is real, replayed, and partial. The g=74 position is unchanged: 24 face-down, stock empty, both club kings covered, 288 tableau states inside cost 8 and no removal. The live controller sees that result as `PROBE_LIMIT` and then stalls. Deepening that one tactical bound is the remaining way to attack that geometry. Raising the global beam, the 150-second cap, or the length-12 bonus does not expose a king that has no legal suffix today.

Seed 111 restores one line and then hits an exit that ignores the other four. That exit should call the same frontier continuation `PLANNING_STALL` already uses, and the stop text should keep the pending count. The clock had 33 seconds left.

The g=26 checkpoint still has one forward move. An empty stall snapshot must not be reported as a second strategy. The cold run is where the histories actually split, at `move 1 3 1` versus `move 8 10 1`, and again at the step-31 deal.

The g=9 and g=17 openings are still queued at the moment the second foundation returns. They are preserved. They were not required for this removal. Playing one of them is a separate experiment, aimed at a different first foundation.

The adopt cap stays at 2. `outcome_rank` stays four keys wide. A new kernel is not the next step. The cold target was 2, so the search was not asked for eight. The next measurement can raise the target on this same scheduler, keep one worker, and report whatever foundations actually come off. Two foundations are not a completed game.

## 10. Reproduce

Branch `local/frontier-bottleneck-v0-114`. HEAD `0f223bb243520a0be7a52218f40549cbcba0e3f1`. The v0.114 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py -q --tb=line
```

That command passed 353 tests in 330.18 s.

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 150 --max-steps 220 --frontier 8 --proposals 3 --workers 1 --no-portfolio --out artifacts/human_strategy/v0_114/cold_two.json
```

Optional overrides are `--slice` and `--line-attempts`. Cold mode rejects `--incumbent`. `--root post-sd3` remains diagnose-only.

Benchmarks A, B, and C are diagnose or direct probes from replayed roots. Seed 111 shuffles a copy of the same deal with `random.Random(111)`. The hearts board is constructed in `tests/test_human_strategy_v0_114.py`. None of those runs loads the 172 or 185 sequences. The measured summary is `artifacts/human_strategy/v0_114/benchmark_summary.json`. That directory is gitignored. The g=74 probe, the g=19 and g=26 diagnoses, seed 111, the hearts probe, and the cold search were the runs behind that file. The cold search itself elapsed 87.901 s.

Files created or modified:

```text
src/spider/human_strategy/__init__.py
src/spider/human_strategy/controller.py
src/spider/human_strategy/foundation_direction.py
src/spider/human_strategy/profiles.py
src/spider/human_strategy/strategic_frontier.py
tools/human_strategy_solver.py
tests/test_human_strategy_v0_114.py
docs/frontier_bottleneck_v0_114.md
```

`engine.py`, `rules.py`, `registry.py`, the solution files, and Play Lab are untouched.

## 11. Git

```text
branch: local/frontier-bottleneck-v0-114
HEAD:   0f223bb243520a0be7a52218f40549cbcba0e3f1
status:
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/profiles.py
 M src/spider/human_strategy/strategic_frontier.py
 M tools/human_strategy_solver.py
?? docs/frontier_bottleneck_v0_114.md
?? tests/test_human_strategy_v0_114.py
```

No commit, push, merge, or pull request.
