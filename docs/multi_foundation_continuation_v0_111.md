# Multi-foundation continuation v0.111

v0.110 removes one spade foundation from the untouched opening of deal 4925153 at corrected MobilityWare g=19. That run stops on purpose. v0.111 keeps the same controller and asks it to continue: close the finished campaign, rank the remaining suits, lock a new horizon, and build the next foundation's prerequisites. Exact stock reception now means the parent on the physical landing column. A covered run may be recovered by a bounded sequence of more than one legal move.

The second foundation was not reached. From the replayed g=19 board, and again from a cold run whose target was two foundations, the controller stops at cumulative corrected g=32 with one foundation still on the board. Seven legal tableau moves remain. The status is `PLANNING_STALL`. That is a classified stall, not a finished game and not a proof that every continuation was examined.

This is not a new solver. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

## 1. What changed

Schema is `spider-human-strategy-0.111`. The default artifact directory is `artifacts/human_strategy/v0_111/`.

`--goal play` is still the v0.108 controller. `--goal first-foundation` still stops at the first removal with `FOUNDATION_REACHED` and the reason `first foundation completed; this is a partial research trajectory, not a finished game`. The new goal is `--goal foundations`. `--target-foundations N` asks for N removals during that solve, from 1 to 8. Omitting the flag asks for all eight.

The count is gains during the solve, not the absolute number already on the board. From the opening, target 2 means two removals. From a state that already holds one foundation, target 1 means the next removal. A solve that removes all eight and passes `is_solved()` returns `SOLVED_VALID`. A configured target reached earlier returns `FOUNDATION_TARGET_REACHED` and the reason `foundation target N reached at corrected g G; this is a partial research trajectory, not a finished game`. `partial_trajectory` is true only for `FOUNDATION_REACHED` and `FOUNDATION_TARGET_REACHED`.

Other stop labels stay the ones the controller already emits: `TIME_LIMIT`, `STEP_LIMIT`, `MEMORY_LIMIT`, `PLANNING_STALL`. There is no separate `NODE_LIMIT` or `PLANNING_STALLED`. The best-g kernel still starts only for `--goal play` after `EXHAUSTED`. A foundations run does not fall into that search.

On each removal below the target the controller records the suit, the cards, the exact campaign cost (`line.g` minus the g at the previous removal, or `opening_g` for the first), the structural assessment, and a completed-campaign record. It then drops the locked horizon. The next proposal locks whatever the analyser selects. The old spade epoch is not inherited. The existing after-removal ranking is still emitted. That ranking is a candidate, not a command.

## 2. Exact landing-column reception

`obligation_is_satisfied` for a `SHAPE_RECEIVER` used to succeed when a suitable parent existed anywhere on the tableau, or anywhere in the next stock row. That is no longer true.

`direct_column_reception` returns true only when `obligation.receiver_column` exposes a card of the incoming suit whose rank is `receiver_rank`. A king has no ordinary parent, so the predicate returns false. Callers assess a queen-led anchor separately. The realizer still treats receivers as best-effort conditions, not gates. Realization of the existing benchmark stayed `FOUND`. The predicate now matches the column the child will actually land on.

`classify_incoming_receiver` names the planning distinction the predicate cannot:

| Status | Meaning |
| --- | --- |
| `already_positioned` | The landing column already exposes the parent. |
| `relocatable` | The parent is elsewhere and one legal move, accepted by `compare_exact_reception`, puts it on the landing column. |
| `needs_preparation` | A longer accepted path does the same. |
| `blocked` | The parent cannot be placed inside the probe bound. |
| `unavailable` | The parent is not yet a usable tableau card. |
| `not_worthwhile` | A relocation exists and loses the comparison with dealing now. |
| `king_anchor` | The incoming card is a king. Queen-led follow-up is recorded. The landing is not a foundation. |
| `post_deal_transfer` | After the exact row is dealt, the new card has one legal move onto a same-suit rank+1 parent. |

A deal covers every column. A parent that is the pre-deal top of some other column is buried by the new row, so a one-move post-deal transfer onto that same card does not exist. The one-move transfer is valid when the parent arrives in the same row on another column. A parent buried by the deal is a multi-move recovery problem, not a one-move transfer.

Alignment notes the wrong column before it searches. `receiver for 9s is already the top of column 7` stays an already-satisfied note. `receiver for 8h is on column 2 (face-down), not on landing column 5` is the new note, and it is not by itself a success. `not_found_within_bound` at corrected cost 3 is still a bound, not a proof.

## 3. Multi-move recovery and a necessary neutral deal

`measured_stock_connection` still requires a same-suit landing or a one-card follow-up that uses an incoming card of the locked suit. The same-suit continuation skip remains: an incoming card that extends the run is the connection, not a burial. A cover of a same-suit run of length 3 or more still looks for one legal move that lifts it. That path still emits `and one legal move lifts that cover`.

When that one move does not exist, `search_post_deal_recovery` searches legal tableau moves only. Bounds are 3 moves and 80 nodes. It does not deal and it does not split a protected run. A found sequence appends `N-move recovery costs C`. A miss returns no connection, so the deal is refused. Recovery alone does not authorise a deal. The landing or follow-up is still required. Search time is recorded as `consequence_probing` only when this search runs. Neither cold deal on 4925153 entered it. Both still used a one-move lift or a continuation, and both still carry the reason `selected: a known incoming card enables a same-suit connection after preparation was tried`.

`_necessary_deal` sits after that measured connection returns nothing, and before `_horizon_deal`. It can deal one row inside the locked operational horizon when a chosen card of the locked suit arrives in that exact row and the landing is not already same-suit. The reason is `selected: a required card arrives in this row even though its landing is neutral`. Evidence says the landing need not be same-suit, the operational epoch was not revised, and an analysed-epoch increase is not the reason. Both official deals on 4925153 found a measured connection first, so this path did not fire. A unit board where the required card lands off-suit does take it, and a forecast that walks epoch 2 to 5 without a stock change is still rejected.

The deal order that the v0.110 tests depend on is unchanged through the completing-row deal: removal, mandatory excavate, same-suit join, access while an excavate is open, protected-run block, then the locked completing row with `selected: foundation plan deals after its prerequisites`, before alignment. `_unlocking_deal` and `_frozen_row` stay unwired.

## 4. Commitment, alternatives, and the structural snapshot

The selected label stays while the schedule is not materially better and the suit is not stalled. A tactical miss still says the suit is not impossible. Three misses suspend that prerequisite id. Stuffing every open excavate does not declare the foundation impossible. The campaign stays open.

If another suit's estimated cost is within 6 of the lock, one event records an alternative portfolio and says similar costs are not proof and do not prune. On `--goal foundations` only, a stall may call `adopt_alternative_foundation` at most twice. The call drops the horizon, forces the new label once, and records `campaign <old> stalled; trying <new>`. `--goal first-foundation` does not take that switch, so a blocked proposer still ends as `PLANNING_STALL`.

`structural_assessment` records face-down cards, same-suit bonds, foundations, stock, empty columns, exposed same-suit fragments of length at least 2, mixed-suit boundaries, `admissible_remaining`, and `heuristic_remaining`. The heuristic is marked `heuristic_remaining_is_not_a_bound`. Only the admissible figure is a pruning number. The assessment is stored on the completion record. It does not stop the route.

## 5. g19 regression

Cold `--goal first-foundation`, 40 seconds, 80 steps, one worker, RSS abort 2048 MB. The prefix was not injected.

| | Result |
| --- | --- |
| Status | `FOUNDATION_REACHED` |
| Solved | false |
| Partial trajectory | true |
| Corrected g | 19 |
| Foundations | 1, spades, king through ace |
| Deals | 2 |
| Steps | 19 |
| Elapsed | 7.702 s |
| Peak RSS | 43.93 MB |
| Unique states | 20 |
| Stop | `first foundation completed; this is a partial research trajectory, not a finished game` |

The 19 actions, 0-based, are `(2,5,1)`, `(6,8,1)`, `(9,8,1)`, `(6,9,1)`, `(5,7,2)`, `(5,7,1)`, `(0,7,1)`, `(2,1,1)`, `(7,2,5)`, deal, `(9,5,1)`, `(1,9,1)`, `(2,5,1)`, `(2,8,6)`, `(8,6,7)`, `(6,0,9)`, `(0,1,10)`, deal, `(1,0,12)`. The last action is `move 2 1 12`. Independent replay of that prefix is legal, costs 19, leaves 33 face-down, 1 same-suit bond, 30 stock cards, and one spade foundation. Tableau plus stock plus foundations remains 104 cards.

Completed campaign: `S#1 removed at corrected cost 19`, operational epoch 2, outstanding prerequisites empty.

### Stock boundaries on that prefix

| Milestone | Corrected g | Face-down | Bonds | Foundations | Stock |
| --- | ---: | ---: | ---: | ---: | ---: |
| Opening | 0 | 44 | 0 | 0 | 50 |
| Before deal 1 | 9 | 35 | 5 | 0 | 50 |
| After deal 1 | 10 | 35 | 6 | 0 | 40 |
| Before deal 2 | 17 | 33 | 11 | 0 | 40 |
| After deal 2 | 18 | 33 | 12 | 0 | 30 |
| Spade removed | 19 | 33 | 1 | 1 | 30 |

Both deals are `DEAL:S#1` with the measured-connection reason. Deal 1 evidence: schedule 31.0 is heuristic and does not prune, target epoch 2, now epoch 0, readiness `stock_gated` LOW, not theoretically available until epoch 2, operational epoch not revised, incoming column 1 `Js`, column 7 `9s`, column 9 `8s`. Deal 2 evidence: schedule 12.0, target epoch 2, now epoch 1, readiness `stock_gated` MEDIUM, incoming column 1 `Ks`, column 2 `As`, column 4 `7s`. No third deal was taken.

Timing on the lock at removal, seconds: foundation analysis 6.7504, tactical realisation 0.0776, dependency planning 0.0532, receiver alignment 0.0406, consequence comparison 0.0.

After removal the analyser ranks, and does not command:

| Label | Epoch | Heuristic cost | Readiness | Operational | Copy |
| --- | ---: | ---: | --- | --- | ---: |
| D#1 | 4 | 24.0 | excavation_led | true | 1, other copy epoch 5 |
| H#1 | 2 | 37.0 | deferred | false | 1, other copy epoch 5 |
| C#1 | 5 | 30.0 | deferred | false | 1, other copy epoch 5 |
| S#2 | 5 | 43.0 | deferred | false | 2, other copy epoch 2 |

## 6. The g19 board against the reference checkpoints

Same deal, each line measured at its own first foundation. Stock is 30 cards on all three. Empty columns are 0. Heuristic remaining is labelled and is not a bound.

| Checkpoint | Face-down | Bonds | Fragments of length ≥ 2 | Mixed boundaries | Admissible remaining | Heuristic remaining |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| v0.111 at g=19 | 33 | 1 | none | 12 | 5 | 57.5 |
| Canonical first foundation | 8 | 29 | column 7 hearts, length 8, top `Ah` | 12 | 3 | 32.5 |
| Autonomous 185 first foundation | 10 | 26 | diamonds on columns 2, 4 and 8; clubs on 9; spades on 10 | 13 | 3 | 31.0 |

The early removal leaves the excavation on the board. The reference checkpoints have already turned most of that excavation into same-suit structure. Cumulative g is not the comparison. The g=19 line remains a candidate ancestry. It is not treated as proof of a cheaper full game. Canonical first foundation stays g=90. The autonomous 185 first foundation stays g=71. Neither comparison is a completed-game claim.

## 7. Second-foundation campaign

Diagnose mode replayed the cold g=19 state. Provenance notes that the suffix was not injected. `--goal foundations --target-foundations 1` asks for one further removal. Budget 150 seconds and 200 steps. RSS abort 2048 MB. One worker. Extended was not launched.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Solved | false |
| Partial trajectory | false |
| Cumulative corrected g | 32 |
| Foundations | 1 |
| Deals in the suffix | 0 |
| Steps attempted | 24 |
| Actions in the suffix | 13 |
| Elapsed | 8.859 s |
| Peak RSS | 43.93 MB |
| Unique states | 14 |
| Stop | `planning stall: 7 legal tableau moves remain; this is not a proof that every continuation is exhausted; objectives suppressed after failure` |

Suffix, 0-based: `(7,9,1)`, `(0,2,1)`, `(3,0,1)`, `(8,3,1)`, `(3,1,1)`, `(9,1,2)`, `(0,9,2)`, `(2,0,1)`, `(0,7,2)`, `(1,0,2)`, `(1,3,1)`, `(0,1,3)`, `(7,8,2)`. Each of those 13 moves costs 1. 19 + 13 = 32.

The lock selected `D#1` over `H#1`, target epoch 4, heuristic cost 24.0. The portfolio note named `C#1`. Excavate misses on `excavate:r6:d3` and `excavate:r4:d3` were suspended. One access sequence uncovered `tableau:7:up:1` from under `10d` and did not move the epoch. The controller then switched: `switch D#1 to H#1 because its schedule is materially better`. The epoch record reset. The new lock is `H#1`, target epoch 2, heuristic cost 31.0.

Epoch 2 is already dealt, so every later proposal says the deal waits. Access still played legal uncovering sequences. None of them moves the operational epoch:

- `tableau:3:up:1` blocked by `7s`, a 2-move sequence, then a 1-move sequence.
- `tableau:3:up:0` blocked by `Kh Qh`, cover 2 to 1.
- `tableau:2:up:1` blocked by `5c`, a 3-move sequence, then a 1-move sequence.
- `tableau:1:up:1` blocked by `Jd 10d`, a 3-move sequence, then a 2-move sequence.

Receiver alignment on the waiting row: the incoming king on column 4 is not a foundation, and the queen-led follow-up is false. The parent of `8h` is face-down on column 2, not on landing column 5, and is `not_found_within_bound` at corrected cost 3. The parent of `4h` is face-down on column 2, not on landing column 10, same bound. Dormant parks `move 9 10 2` and `move 9 3 1` were tried. Strategic width widened to 3. The last foundation event is `campaign H#1 stalled; trying C#1`. The next status is the stall. `C#1` was announced and not played. `S#2` was not tried. `D#1` was not resumed.

Timing on the last foundation trace item, seconds: foundation analysis 7.3717, tactical realisation 0.0002, dependency planning 0.4587, receiver alignment 0.6428, consequence comparison 0.0. No `consequence_probing` key. The suffix dealt nothing, so the multi-move recovery search did not run.

The decisive blocker is that switch. `H#1` looks earlier because epoch 2 is in hand. Its receivers for the next row are face-down and outside the cost-3 relocation bound, and the in-hand rule then refuses another deal. The heuristic that preferred `H#1` over the operational `D#1` is not a bound. The announced switch to `C#1` does not become the next proposal before the stall return.

## 8. Cold run aimed at two foundations

Cold from the opening, `--goal foundations --target-foundations 2`, 150 seconds, 220 steps, one worker, RSS abort 2048 MB. No stored prefix.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Solved | false |
| Partial trajectory | false |
| Cumulative corrected g | 32 |
| Foundations | 1 |
| Deals | 2, both during `S#1` |
| Steps attempted | 43 |
| Elapsed | 16.949 s |
| Peak RSS | 45.16 MB |
| Unique states | 33 |
| Prefix injected | false |

The action list is the 19-action g=19 prefix followed by the same 13-action suffix as the diagnose continuation. The event tail matches that continuation, including `campaign H#1 stalled; trying C#1` and `planning failure: 7 legal moves remain after objectives were blocked`. Completed campaign on the provenance record is `S#1` at exact cost 19, epoch 2, outstanding empty. The foundation-trace slice kept for the artifact is the last items, so the completion row itself is no longer in that slice. The campaign record is.

Deal reasons and evidence match section 5. No post-removal deal. Timing on the last foundation item, seconds: foundation analysis 14.4014, tactical realisation 0.1807, dependency planning 0.5457, receiver alignment 0.5669, consequence comparison 0.0.

The cold two-foundation run and the diagnose continuation from g=19 agree. The controller rediscovered the opening. It did not load it.

## 9. Independent fixture

`deals/` contains only `4925153.txt`. The extra fixture is a shuffle of that deal with `random.Random(111)`. Cold `--goal foundations --target-foundations 1`, 40 seconds, 40 commits. The attempt ceiling is four times the commit budget, so the stop fires when attempts pass 160.

| | Result |
| --- | --- |
| Status | `STEP_LIMIT` |
| Stop | `strategic step budget ended` |
| Corrected g | 22 |
| Foundations | 0 |
| Deals | 1 |
| Attempts | 161 |
| Elapsed | 17.05 s |
| Peak RSS | 45.19 MB |
| Unique states | 23 |

Opening rank, heuristic costs: `S#1` epoch 3 cost 40, `D#1` epoch 4 cost 44, `H#1` epoch 5 cost 43, `C#1` epoch 2 cost 41. The selected suit and epoch differ from the unshuffled opening, which locks `S#1` at epoch 2. The first deal is `DEAL:S#1` at g=3, measured-connection reason, operational epoch held at 3, incoming column 1 `9s`, column 2 `3s`, column 6 `2s`. The event tail is then `continue C#1`, `deal waits on excavate:r9:d2`, and a dormant `DEAL_NOW` that is retried. The committed moves cycle. No foundation is removed. The selector responds to the layout. It does not finish a campaign inside this budget.

## 10. Tests

`tests/test_human_strategy_v0_111.py` has 16 tests. They build synthetic boards and replay captured positions. The cold test compares the solver's own actions with the g=19 oracle. It does not pass that list into `solve()`.

| Behaviour | Test |
| --- | --- |
| Exact column, not card presence | `test_exact_column_receiver_is_not_card_presence` |
| Parent on the wrong column, one legal relocation | `test_movable_receiver_on_the_wrong_column_can_be_relocated` |
| Blocked parent and a longer preparation | `test_blocked_receiver_and_multi_step_preparation` |
| Validated post-deal transfer, and a harmful move refused | `test_post_deal_transfer_is_validated_and_a_harmful_move_is_not` |
| Incoming king is not a failed reception and not a foundation | `test_incoming_king_is_neither_a_failed_reception_nor_a_foundation` |
| Two-move recovery is cited; an unrecoverable cover refuses the deal; `9s onto 10s` remains | `test_multi_move_recovery_is_searched_and_not_automatic` |
| Neutral required card deals; an epoch forecast without a stock change does not | `test_necessary_deal_does_not_require_a_same_suit_landing_or_an_epoch_bump` |
| Close drops the spade horizon; a stall can switch suit | `test_completion_drops_the_old_horizon_and_a_stall_can_change_target` |
| Ranking follows the deal; the two copies stay distinct | `test_foundation_ranking_is_not_hard_coded_and_copies_stay_distinct` |
| Prefix 82 still returns `FOUNDATION_REACHED` for first-foundation, and `FOUNDATION_TARGET_REACHED` for foundations target 1 | `test_first_foundation_status_stays_distinct_from_a_later_target` |
| Target 2 on prefix 82 continues, closes `S#1`, and does not reuse its prerequisites | `test_multi_foundation_continues_and_does_not_keep_the_old_spade_horizon` |
| The label holds across tactical steps; suspended excavates do not deadlock | `test_commitment_and_suspension_do_not_deadlock_the_campaign` |
| A whole-column move onto an empty column costs 0; a move that leaves face-down costs 1; a deal costs 1 | `test_corrected_mobilityware_cost_includes_a_free_whole_column_move` |
| Cold mode rejects an incumbent prefix | `test_cold_mode_refuses_a_stored_prefix` |
| Cold target 2 rediscovers the g=19 prefix and continues | `test_cold_opening_replays_the_spade_foundation_at_g19_and_can_continue` |
| The g=19 assessment is stored and is worse, on face-down cards, than the canonical first-foundation checkpoint | `test_g19_structure_is_not_treated_as_a_finished_game` |

The realizer assertion now requires `obligation_is_satisfied` to equal the exposed top of `receiver_column`. A recorded satisfied id must be that exact column.

Regression command in section 13, after the fixture corrections: 322 passed in 199.79 s, exit 0. That command is the previous 291-test set, plus `tests/test_human_strategy_v0_111.py`, plus `tests/test_foundation_campaign_realizer.py`. The registry is still 28 ACTIVE and 2 CONDITIONAL. Principle 11 stays CONDITIONAL. `registry.py` was not edited.

## 11. Accounting, replay, and what is not claimed

Corrected MobilityWare scoring was not edited. A deal costs 1. A tableau move costs 1, except a whole-column move with no face-down card onto an empty column, which costs 0. The g=19 removal's exact campaign cost is 19. The stall's cumulative cost is 32. 32 is the cost of a partial trajectory that still has one foundation. It is not a solution score.

Replay of the cold prefix confirms every action, the same-suit run that leaves, one spade foundation, 33 face-down, 30 stock cards, 1 bond, and 104 cards conserved. The cold two-foundation action list has that same prefix. The diagnose suffix matches the cold suffix action for action.

`SOLVED_VALID` was not returned. Eight foundations were not removed. No new completed-game MobilityWare score is claimed.

## 12. Unresolved failures

The principal experimental goal, a replay-verified second foundation from the g=19 state, was not met inside the 150-second pilot. The stall fired in 8.859 seconds on the continuation and in 16.949 seconds on the cold target-2 run. More time on the same proposals would repeat the blocked receivers. Extended was not launched.

The first decisive blocker is the post-removal campaign choice:

1. `D#1` is selected at epoch 4, heuristic cost 24, and is operational.
2. The controller leaves it because `H#1` at epoch 2, heuristic cost 31, is called materially better.
3. Epoch 2 is in hand, so no further deal is considered.
4. `8h` and `4h` need parents that are face-down on column 2. Alignment cannot move them onto columns 5 and 10 within corrected cost 3.
5. The king on column 4 has no queen-led follow-up.
6. The failure path announces `C#1` and then returns `PLANNING_STALL` with 7 legal tableau moves left.

Unresolved alternatives that this run did not play: stay on `D#1`; deepen the heart receiver search or deal again with evidence while the parents are face-down; enter the announced `C#1` campaign on the next proposal; try `S#2` at epoch 5. None of those is certified by an admissible bound.

The g=19 structure is the other open question. Thirty-three cards are still face-down and the exposed same-suit fragments of length 2 or more are gone. The reference first-foundation checkpoints are much further through that excavation. If a later continuation of this opening is expensive, another first-foundation timing has to remain searchable. This release does not hard-code the 19 actions as the only legal ancestry. Cold mode still discovers them.

The shuffled fixture shows a second stall shape: a measured deal, a later suit whose excavate blocks the deal, and a repeating tableau cycle until the attempt ceiling. A suspended prerequisite must not be allowed to spin that cycle.

Consequence comparison stayed at 0.0 seconds on every reported run. The comparison work is still inside alignment and inside the measured-connection call. `consequence_probing` is recorded only when the multi-move search runs, and it did not run on these deals.

## 13. Reproduce

Branch `local/multi-foundation-strategy-v0-111`. HEAD `a2779467aab340d6bc071f30b454f73fe36b03b3` (`Add foundation prerequisite and reception planning v0.110`), which descends from `354a83fcb26e3b9b05884f4254e36900928faed3`. The v0.111 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py -q --tb=line
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal first-foundation --time-limit 40 --max-steps 80 --workers 1 --out artifacts/human_strategy/v0_111/cold_first.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 150 --max-steps 220 --workers 1 --out artifacts/human_strategy/v0_111/cold_two.json
```

The benchmark summary written by the bounded A–D driver is `artifacts/human_strategy/v0_111/benchmark_summary.json`. That directory is gitignored. The four solves together finished in 52.72 seconds because the stalls returned early. Peak RSS of those runs was 45.19 MB.

Git status at the time of this note:

```text
## local/multi-foundation-strategy-v0-111
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/preparation.py
 M src/spider/planner/foundation_campaign_realizer.py
 M tests/test_foundation_campaign_realizer.py
 M tools/human_strategy_solver.py
?? docs/multi_foundation_continuation_v0_111.md
?? tests/test_human_strategy_v0_111.py
```

## 14. Recommended v0.112

Keep this controller. Do not add a second planner and do not start the best-g kernel on a foundations goal.

Four changes follow from the stall:

1. "Target epoch is in hand" must not freeze a campaign whose next receivers are face-down and unreachable inside the relocation bound. An evidenced later row, or a switch back to a suit that is still operational, has to be a legal next proposal.
2. A lower epoch and a heuristic cost are not, by themselves, material evidence to abandon an excavation-led suit. `D#1` at epoch 4 was operational. `H#1` at epoch 2 could not place `8h` or `4h`.
3. When the failure path announces `trying C#1`, the next iteration should propose inside that campaign, or record why the switch was refused, before returning `PLANNING_STALL`.
4. The g=19 opening stays a preserved candidate. A continuation that keeps paying excavation after a cheap removal should be allowed to try another first-foundation timing. The structural snapshot in section 6 is the reason. It is not a bound.

On the shuffled fixture, a blocked excavate plus a dormant deal must not replay the same tableau cycle until the attempt multiplier fires. Suspend the prerequisite and move the campaign, which is the rule the synthetic commitment test already states.

Leave principle 11 CONDITIONAL until `--goal play` changes a decision the v0.107 registry test already names.
