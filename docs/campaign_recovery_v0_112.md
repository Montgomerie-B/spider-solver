# Campaign recovery v0.112

v0.111 removes one spade foundation from the untouched opening of deal 4925153 at corrected MobilityWare g=19, then stops at cumulative g=32. The status there is `PLANNING_STALL`. Seven legal actions remain, three stock rows remain, and the clock is not the cause.

v0.112 keeps that controller and changes how a campaign is chosen, how an already-dealt stock epoch is read, and what happens when the locked campaign cannot move. From the exact replayed g=32 board the controller now enters `D#1` and then `C#1`, plays 20 further legal actions, and stops at cumulative g=52 with one foundation. A clubs run of length 7 is on the board. No second foundation is removed. A cold run from move 0 still reaches the same g=19 spade foundation, then stalls at g=26 on a shorter branch than v0.111.

This is not a new planner. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

## 1. Root cause of the v0.111 g32 stall

The cause is in the v0.111 decision trace and in the control flow that produced it. The diagnose continuation and the cold target-2 run played the same 13-move suffix and stopped for the same reason.

After the spade removal the analyser ranked `D#1` at epoch 4, heuristic cost 24, readiness `excavation_led`. `_clearly_better` then switched to `H#1` at epoch 2, heuristic cost 31. The switch text is `switch D#1 to H#1 because its schedule is materially better`. The epoch term in `schedule_objective` made the earlier epoch look close enough. Operational feasibility was not part of that comparison. `D#1` had already uncovered `tableau:7:up:1` from under `10d`. That work was dropped with the horizon.

`H#1`'s target epoch had already been dealt. The in-hand branch logged `target epoch 2 is in hand and H#1 is still on the tableau; the deal waits` and still called `plan_receiver_alignment` against the next undealt row. The parent of `8h` is face-down on column 2, not on landing column 5. The parent of `4h` is face-down on column 2, not on landing column 10. Both searches returned `not_found_within_bound` at corrected cost 3. The incoming king on column 4 has queen-led follow-up false. The cost-3 miss was not labelled `PROVEN_INFEASIBLE`. It produced no candidate, `block_deal` stayed true, and no purpose-met substitute was legal, so the controller stalled.

`adopt_alternative_foundation` did run. Its last event is `campaign H#1 stalled; trying C#1`. The next iteration built an empty candidate list and returned `PLANNING_STALL` before `propose_foundation_step` could consume `hold_label`. `C#1` was announced and never proposed. `tried_labels` had moved on, so `D#1` was not resumed. `S#2` was never named. No recovery search existed. The best-g kernel still starts only for `--goal play`.

The stop reason was `planning stall: 7 legal tableau moves remain; this is not a proof that every continuation is exhausted; objectives suppressed after failure`. That count of 7 is `all_legal_actions` on the replayed board, which is six tableau moves plus one legal deal. The phrase "tableau" in the v0.111 reason included the deal.

## 2. Campaign selection and feasibility

Schema is `spider-human-strategy-0.112`. The default artifact directory is `artifacts/human_strategy/v0_112/`.

`--goal play` is still the v0.108 controller. `--goal first-foundation` still stops at the first removal with `FOUNDATION_REACHED` and the reason `first foundation completed; this is a partial research trajectory, not a finished game`. `--goal foundations` and `--target-foundations` are unchanged. The count is still removals during the solve. Kernel fallback stays play-only.

`campaign_near_term_status` classifies the next thing the controller can do:

| Status | When it is assigned |
| --- | --- |
| `READY` | A legal same-suit join exists for the suit. |
| `REQUIRES_PREPARATION` | Readiness is `ready_now`, `assembly_led`, or `excavation_led`, or any card of the suit is buried or obstructed. |
| `SUSPENDED` | Readiness is `blocked` and nothing of the suit is buried or obstructed. |
| `DEFERRED_BY_STOCK` | The target epoch has elapsed, or readiness is `deferred` or `stock_gated`, and the cases above did not match. |
| `PROBE_LIMIT` | A bounded access or recovery search missed. Assigned by that search, not by the ranker. |
| `PROVEN_INFEASIBLE` | Not assigned by a timeout or a cost bound. |

Almost every suit on these boards has a face-down card, so the near-term status is often `REQUIRES_PREPARATION` even when the campaign readiness is `deferred`.

`campaign_may_displace` refuses a switch that `_clearly_better` would otherwise take when the challenger is `DEFERRED_BY_STOCK`, `PROBE_LIMIT`, or `SUSPENDED` and the incumbent is `READY` or `REQUIRES_PREPARATION`. It also refuses when the challenger's target epoch has already been dealt, the challenger is not `READY`, and the incumbent still has tableau work. `_clearly_better` itself is unchanged. The gate returns false. It does not invent a switch. While the opening lock is `S#1`, the gate is not consulted.

The gate does not rewrite the first choice. An empty lock still returns `portfolio.primary`. On the replayed g=32 board that primary is `H#1`, epoch 2, estimated cost 26, schedule objective 32. `H#1` is probed and then yields. Only after a label is locked can a later, earlier-looking suit be refused. The refusal text is `keep D#1; H#1 looks earlier on the heuristic schedule but has no demonstrated next step`, and the campaign change is `refused switch D#1 to H#1; feasibility outweighs the epoch`.

At the g=19 removal the primary is still `D#1`, epoch 4, estimated cost 24. Hearts may not displace diamonds there. Diamonds may displace hearts. The cold opening therefore stays on spades until the removal, and the post-removal lock starts on diamonds rather than jumping to hearts.

## 3. Elapsed epochs

Four clocks stay distinct.

The earliest theoretical epoch is the stock horizon by which the chosen cards could be in play. It is still the analyser's `target_removal_epoch`. A past value does not make the suit impossible.

Current accessibility is where those cards are now: face-up, face-down, or still in the stock, and whether a legal move can touch them.

The next required future stock event is an undealt row that still holds a chosen card. Evidence on a necessary deal and on a measured deal now includes `fact: the next row is a future stock event, not a row already dealt`. The benchmark summary stores the first eight evidence lines, so that sentence is past the cut on the long runs. The g=32 unit test reads the full decision and requires the sentence, together with `not revised`, on the first deal.

The operational campaign horizon is still the locked `operational_epoch`. `revise_operational_epoch` is unchanged. A failed reveal does not walk it. An analysed-epoch increase without a stock change is still rejected. Both official pre-g19 deals still say the operational epoch was not revised, and both still use `selected: a known incoming card enables a same-suit connection after preparation was tried`.

When `current_epoch >= operational_epoch`, the proposer records that the epoch is already dealt and does not call receiver alignment for that historical row. If a shallow buried card of the suit has an access plan inside cost 4 and 800 nodes, that plan is the next action. Two buried cards are examined. A miss is `PROBE_LIMIT` and the event says the access bound is not infeasibility. A time guard under 0.15 seconds is the same status. The campaign then yields. The elapsed epoch does not, by itself, authorise the next deal. Automatic dealing after a failed tactical prerequisite stays refused.

## 4. Historical receiver obligations

`plan_receiver_alignment` still runs for a campaign whose target row has not been dealt. On an elapsed campaign it is skipped. The events are `epoch N is already dealt; receiver alignment is not generated for that historical row` and `remaining work is current accessibility, not a past landing column`.

The v0.111 obligation, moving the face-down parent of `8h` onto landing column 5 and the parent of `4h` onto landing column 10, is not generated on the g=32 hearts probe. The probe looks at buried hearts, shallowest cover first. On that board the first two are `8h` on column 7 at cover 2 and `6h` on column 4 at cover 3. Both miss inside the access bound. `4h` on column 8 is also at cover 3 and is outside the two-card cap. That cap is a limit, not a proof that column 8 is unreachable.

A buried card that the search does reach becomes an accessibility candidate, id `access:tableau:{column}:down:{index}`, with the historical landing excluded from the evidence. On the g=52 line, after the clubs epoch had itself elapsed, `2c` was turned into that kind of prerequisite and the cover moved from 3 to 2. Later misses on `4c` at cover 5 and `8c` at cover 6 stayed `PROBE_LIMIT`.

The cost-3 relocation bound is unchanged. It is still not `PROVEN_INFEASIBLE`. The probe limits were not raised across the board. Elapsed access uses cost 4 and 800 nodes. Recovery uses cost 3 and 400 nodes. One buried card is tried per campaign, and at most three campaigns are tried.

## 5. Scheduling, suspension, and recovery

The portfolio is still one campaign per next suit ordinal. After one spade removal the other physical copy is `S#2`. Status in the lock is the feasibility string above, plus the existing label, hold, and tried-label fields. No separate task manager was added.

`adopt_alternative_foundation` is still capped at two switches. The third call returns `None`. The order on the g=32 continuation is the initial label, then the first unused alternative, then the next. That is `H#1`, then `D#1`, then `C#1`. `S#2` stays in the alternative list and is reported as not entered. Recovery, which runs only after the cap is spent, is what considers `S#2`.

A yield is set in two places. An elapsed campaign with no access plan sets it after the probe. A campaign whose every open mandatory excavate has already failed three times, or is already in `suspended_notes`, sets it instead of repeating `deal waits`. The event is `suspended prerequisites do not freeze {label}`. The first miss still waits. The opening spade line still returns a real access or deal candidate before this branch. `--goal first-foundation` does not resume, so a yield there still ends as `PLANNING_STALL`. The v0.110 test that patches the proposer and expects that stall still passes.

On `--goal foundations`, a proposal that yields with no candidate is consumed in the same turn. The controller clears the flag, adopts the next alternative, and continues. If the cap is spent it calls `recover_foundation_step` once per exact state. Recovery reuses `plan_obstructed_access`. It does not deal, does not start another kernel, and does not order moves by best-g. A hit is one access action, reason `selected: bounded recovery toward a buried foundation card`. A miss lists every remaining legal tableau move and says no bounded access step was found.

The same state is not resumed forever. `resume_counts` allows two proposals per canonical state, then recovery. A failed candidate id is still stored per state, not per campaign. A blocked deal id can still suppress that deal for every suit on that state. A new state key clears the resume count. A face-down decrease on an elapsed campaign clears failures, suspended notes, and the buried-card set, and logs `a reveal reopens suspended prerequisites`. Benchmark B never reduced face-down, so that hook did not fire. The opening spade epoch is below the operational epoch during the g=19 build, so the hook does not restart that line.

`PLANNING_STALL` is still the label from `strategic_stop_status`. On a foundations run the reason gains `planning_stall_detail`: the remaining tableau moves, the campaigns in `tried_labels`, the alternatives not entered, the feasibility status, and the sentence `a probe limit is not infeasibility`. The stall is a planning budget. It is not an exhaustive game-state search. `SOLVED_VALID` still requires `is_solved()` and all eight foundations gone.

## 6. The seven legal actions at g=32

The fixture is the cold g=19 prefix plus the 13-move v0.111 suffix, replayed with `apply_action`. Corrected g is 32. One spade foundation, 30 stock cards, 29 face-down, 8 same-suit bonds. `all_legal_actions` returns 7 actions. Six are tableau moves. The deal is legal. No seventh tableau move exists.

Column 2 already holds `Kd Qd Jd 10d`. Column 9 holds `9c 8d 7c 6c 5c`, so `8d` sits under `7c 6c 5c`. None of the six tableau moves is a same-suit join.

| Action | Cards | Lands on | Bonds | What it does |
| --- | --- | --- | --- | --- |
| `move 2 4 2` | `Jd 10d` | `Qh` | 8 to 7 | Splits the diamond run on column 2. Off-suit. |
| `move 3 8 1` | `6h` | `7d` | 8 to 8 | Parks `6h`. No reveal. |
| `move 3 10 1` | `6h` | `7s` | 8 to 8 | Parks `6h` on the other legal parent. No reveal. |
| `move 9 3 1` | `5c` | `6h` | 8 to 7 | Peels one club. Cover of `8d` would fall by one. Off-suit. |
| `move 9 8 2` | `6c 5c` | `7d` | 8 to 7 | Drops the cover of face-up `8d` from 3 to 1. |
| `move 9 10 2` | `6c 5c` | `7s` | 8 to 7 | The other landing for those same two clubs. Same uncover. |
| deal | the next row | every column | unchanged before the new cards are read | Buries the diamond run and the `8d` access. |

`move 9 8 2` is `(8, 7, 2)`. It is the action the continuation plays first. The trace names it as the one-move realisation of `tableau:8:up:1`, blocked by `7c 6c 5c`. `move 9 10 2` is another legal realisation of that same uncover and was not required once the first landing was played. The two `6h` parks and the diamond split do not serve a named prerequisite. They remain in the legal list until the position changes. The deal is legal and was refused until a later clubs campaign had a required card in the next row.

Campaigns on this exact board:

| Label | Target epoch | Now | Schedule objective | Near-term status | Role |
| --- | ---: | ---: | ---: | --- | --- |
| `H#1` | 2 | 2 | 32 | `REQUIRES_PREPARATION` | Primary. Epoch already dealt. |
| `D#1` | 4 | 2 | 40 | `REQUIRES_PREPARATION` | Resumed after hearts yields. |
| `C#1` | 5 | 2 | 54 | `REQUIRES_PREPARATION` | Entered after diamonds suspends. |
| `S#2` | 5 | 2 | 63 | `REQUIRES_PREPARATION` | Named eligible. Not scheduled. |

Schedule objectives include the confidence penalty. They are not bounds. Estimated costs in the selection events are 26 for `H#1` and, after the switch, 22 for `D#1`.

Hearts yields after the two buried probes. The trace then contains `campaign H#1 stalled; trying D#1` and `D#1 is the alternative under test`. After `excavate:r6:d3` and `excavate:r4:d3` are suspended, diamonds yields. The trace contains `trying C#1` and `C#1 is the alternative under test`. `S#2 stays eligible` is logged while hearts yields. `S#2` becomes a recovery probe only at the final stall, against `Ks` at cover 7. The switch cap is why it is not a scheduled campaign.

A blocked hearts access id does not change a lock that is already `D#1`. The unit test holds that lock, passes `access:tableau:3:up:1` as blocked, and the label stays `D#1`.

## 7. Continuation from g=32

Diagnose mode, opening g=32, `--goal foundations --target-foundations 1`, 150 seconds, 180 steps, one worker, RSS abort 2048 MB. The provenance note says the suffix was not injected. `prefix_injected` is false. Extended was not launched.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Solved | false |
| Partial trajectory | false |
| Cumulative corrected g | 52 |
| Foundations | 1 |
| Deals in the continuation | 3 |
| Actions | 20, each corrected cost 1 |
| Objectives attempted | 22 |
| Elapsed | 16.321 s |
| Peak RSS | 43.85 MB |
| Unique states | 21 |

The 20 actions, 0-based, are `(8,7,2)`, deal, `(0,6,1)`, `(2,3,1)`, `(7,2,1)`, `(9,2,1)`, `(9,5,2)`, `(9,0,1)`, `(0,1,1)`, `(5,1,2)`, `(1,4,1)`, `(7,4,2)`, deal, `(5,6,1)`, `(7,5,1)`, deal, `(4,1,1)`, `(4,5,3)`, `(3,5,1)`, `(7,2,1)`. Replay onto a clone of the g=32 board applies every one. 32 + 20 = 52.

The first action is the `8d` uncover above. The lock then refuses to hand the line back to `H#1`. The first deal is at g=33, id `DEAL:C#1`, reason `selected: a required card arrives in this row even though its landing is neutral`. Evidence names `9c` on column 6 as blocked and `2c` on column 1 as unavailable, target epoch 5, current epoch 2. The operational epoch stays 5. The analysed epoch was not revised to authorise the row.

The second deal is at g=44, measured connection, incoming `4c` on column 5, `Qc` on column 6, `Kc` on column 7, `8c` on column 8. The third is at g=47, measured connection, incoming `3c` on column 4, `7c` on column 6, `3c` on column 9. Both keep the measured-connection reason and both say the operational epoch was not revised. Current epoch walks 2, then 3, then 4, inside operational epoch 5, which is the existing horizon rule.

End board, replay-checked: face-down 29, bonds 12, stock 0, foundations 1, empty columns 0. Fragments: column 2 hearts, length 2, top `9h`; column 6 clubs, length 7, top `3c` (`9c` through `3c`). Mixed-suit boundaries 32. `admissible_remaining` 72. `heuristic_remaining` 117.0, flagged as not a bound.

Face-down did not fall. Bonds rose from 8 to 12 because the clubs run was built. The stock was emptied by three in-horizon deals. That is legal continuation and a real clubs assembly. It is not a second foundation, and emptying the stock is not an improvement by itself.

The stall reason names nine remaining tableau moves: `move 3 4 1`, `move 4 1 1`, `move 4 6 1`, `move 4 9 1`, `move 6 10 2`, `move 6 5 4`, `move 6 7 4`, `move 6 8 4`, `move 6 2 6`. Campaigns entered: `H#1`, `D#1`, `C#1`. Not entered: `S#2`. Feasibility: `PROBE_LIMIT`. Recovery considered `D#1` (`3d` at cover 5), `H#1` (`4h` at cover 3), and `S#2` (`Ks` at cover 7), and found no bounded access step. Stock is empty, so no later row can supply the missing cards. Elapsed time is 16.3 seconds of the 150-second budget.

Timing on the last foundation record, seconds: foundation analysis 12.5558, dependency planning 2.8385, receiver alignment 0.4055, tactical realisation 0.0012, consequence comparison 0.0. The play-mode kernel was not entered.

## 8. Cold first foundation

Cold `--goal first-foundation`, 40 seconds, 80 steps, one worker, RSS abort 2048 MB. No prefix.

| | Result |
| --- | --- |
| Status | `FOUNDATION_REACHED` |
| Solved | false |
| Partial trajectory | true |
| Corrected g | 19 |
| Foundations | 1, spades |
| Deals | 2, both `DEAL:S#1` |
| Steps | 19 |
| Elapsed | 7.07 s |
| Peak RSS | 43.77 MB |
| Unique states | 20 |
| Prefix injected | false |

The 19 actions match the v0.110 and v0.111 prefix, ending at `(1,0,12)`. Completed campaign `S#1`, exact cost 19, operational epoch 2, outstanding empty. Both deals use the measured-connection reason. The first, at g=9, names incoming `Js`, `9s`, `8s`. The second, at g=17, names incoming `Ks`, `As`, `7s`. Both say the operational epoch was not revised. The removal event still ranks the next campaign as `D#1`, epoch 4, cost 24.

Timing, seconds: foundation analysis 6.1405, tactical realisation 0.0648, dependency planning 0.0491, receiver alignment 0.0405, consequence comparison 0.0.

The g=19 structure measured in v0.111 is unchanged by this opening: 33 face-down, 1 bond, stock 30. The canonical first foundation remains g=90 with 8 face-down and 29 bonds. The autonomous 185 first foundation remains g=71 with 10 face-down and 26 bonds. Those checkpoints were not re-solved. This release does not search for a different opening and does not treat the 19 actions as the only legal ancestry. Cold mode discovers them. It does not receive them.

## 9. Cold two-foundation attempt

Cold from move 0, `--goal foundations --target-foundations 2`, 150 seconds, 220 steps, one worker, RSS abort 2048 MB. The g=19 prefix and the g=32 board were not injected.

| | Result |
| --- | --- |
| Status | `PLANNING_STALL` |
| Solved | false |
| Partial trajectory | false |
| Cumulative corrected g | 26 |
| Foundations | 1 |
| Deals | 2, both during `S#1` |
| Actions | 26 |
| Objectives attempted | 27 |
| Elapsed | 10.522 s |
| Peak RSS | 44.10 MB |
| Unique states | 27 |
| g=19 prefix | matches |
| Prefix injected | false |

The first 19 actions are the g=19 prefix. The seven actions after the removal are `(7,9,1)`, `(0,2,1)`, `(7,0,1)`, `(7,2,1)`, `(5,7,1)`, `(9,8,2)`, `(9,8,1)`. Each costs 1. 19 + 7 = 26. The first two match the v0.111 suffix. The third does not. v0.111's third suffix action is `(3,0,1)`, played after the switch onto `H#1`. This run refuses that displacement, so it does not reproduce the rest of the suffix and it never reaches the g=32 board.

End board: face-down 31, bonds 2, stock 30, foundations 1. Against the g=19 checkpoint that is two fewer face-down cards and one more bond. Against the v0.111 stall at g=32, which had 29 face-down and 8 bonds, this branch stopped earlier and with less assembly. It is a shorter continuation, not a better one.

Campaigns entered after the removal: `D#1`, `H#1`, `C#1`. `S#2` was not entered. The tail keeps `C#1` after misses on `excavate:r10:d3` and `excavate:r5:d3`, refuses a switch back to `H#1`, then suspends those excavates. Recovery probes `Ah` at cover 2, `8d` at cover 1, and `Ks` at cover 5. All three are `PROBE_LIMIT`. One tableau move remains, `move 9 10 1`, and it is named in the stall. Feasibility at the stall is `SUSPENDED`. Stock is still 30. Elapsed time is 10.5 seconds of 150.

Timing, seconds: foundation analysis 9.4427, tactical realisation 0.0679, dependency planning 0.1072, receiver alignment 0.0401, consequence comparison 0.0.

## 10. Second foundation

No run removed a second foundation. `SOLVED_VALID` was not returned. Eight foundations were not removed. No completed-game MobilityWare score is claimed.

The closest constructive result is the diagnose continuation in section 7: from the old stall, through a diamond access move and three evidenced clubs deals, to a clubs run of length 7 at g=52, still with one foundation and with the stock empty. The blocked prerequisite at that stop is access. `4c` is at cover 5, `8c` at cover 6, `3d` at cover 5, `4h` at cover 3, and `Ks` at cover 7. The cost-3 recovery miss did not move any of them. With the stock gone, a later foundation has to be built from the tableau.

The cold target-2 run is blocked earlier. `C#1` suspended `excavate:r10:d3` and `excavate:r5:d3`. Recovery missed `Ah`, `8d`, and `Ks`. `move 9 10 1` was still legal and was not played. `S#2` was considered only inside that recovery probe.

## 11. Corrected costs and replay

Corrected MobilityWare scoring was not edited. A deal costs 1. A tableau move costs 1, except a whole-column move with no face-down card onto an empty column, which costs 0. The g=19 removal's exact campaign cost is 19. The g=32 fixture replays at g=32. The 20-action continuation replays at g=52. The cold target-2 list replays at g=26. The seed-111 run replays at g=15. Card identity is unchanged. Tableau, stock, and foundations still conserve 104 cards on the g=19 replay, which leaves 33 face-down, 30 stock cards, and one 13-card foundation.

`heuristic_remaining` and every schedule objective in the traces are labelled as non-bounds. `admissible_remaining` is the only pruning figure the structural record stores. It did not prune these runs.

## 12. Tests

`tests/test_human_strategy_v0_112.py` adds seven tests. They use the replayed g=19 and g=32 boards. Cold solves in that file do not receive the recorded actions.

| Test | What it holds |
| --- | --- |
| `test_g19_prefix_is_legal_and_costs_19` | Replay cost 19, one spade foundation, 33 face-down, 30 stock, 104 cards. |
| `test_elapsed_epoch_cannot_displace_an_operational_campaign` | At g=19, diamonds are `REQUIRES_PREPARATION`, hearts' epoch has elapsed, hearts may not displace diamonds, `S#2` is copy 2. |
| `test_g32_accounts_for_every_legal_action_and_continues` | 7 legal actions, 6 tableau. The stall detail names each tableau move, `S#2`, and `not infeasibility`. A short foundations solve from that board injects no prefix, plays a legal first action, enters `D#1` and `C#1`, keeps `D#1` against hearts, deals, and records a future stock event. |
| `test_historical_alignment_is_not_a_current_obligation` | A hearts lock at operational epoch 2 emits `historical row` and `past landing column`, and yields with `PROBE_LIMIT`, `DEFERRED_BY_STOCK`, or `SUSPENDED`. |
| `test_a_failed_hearts_probe_does_not_block_diamonds` | A blocked hearts access id leaves the `D#1` lock in place. |
| `test_switch_cap_and_cold_refusal` | First adopt is `D#1`, second is `C#1`, third is `None`. Cold mode with an incumbent raises `ValueError`. |
| `test_cold_opening_still_reaches_the_spade_foundation` | Cold first-foundation, no prefix, `FOUNDATION_REACHED`, g=19, the exact action tuple. |

The new file alone passed in 14.39 s. The regression command in section 16 passed 329 tests in 209.76 s, exit 0. That is the previous 322 plus these seven. `registry.py` was not edited. Principle 11 stays CONDITIONAL, 28 ACTIVE and 2 CONDITIONAL.

Items the seven tests do not assert on their own: a reveal clearing a suspended elapsed campaign, and the seed-111 preparation cycle. The reveal hook is in the proposer and did not run on benchmark B. The seed-111 cycle is the recorded failure in section 14, not a green assertion.

## 13. Peak RSS

One worker. RSS abort 2048 MB. No run aborted.

| Run | Peak RSS |
| --- | ---: |
| A, cold first foundation | 43.77 MB |
| B, continuation from g=32 | 43.85 MB |
| C, cold two-foundation | 44.10 MB |
| D, seed 111 | 44.55 MB |

The highest value in this release is the seed-111 run, 44.5546875 MB. Foundation analysis is the largest timer on every run. Consequence comparison stayed at 0.0 seconds. Dependency planning is the next visible cost on the g=32 continuation, 2.8385 seconds, which is the access and recovery work. The play-mode kernel did not run, so there is no separate fallback-search time to subtract.

## 14. Remaining limitations

The second foundation was not reached. The two outcomes that would have been stronger, a removal from the g=19 line and two removals from a cold opening, were not met. More time on the same probes would repeat the same cover bounds. Extended was not launched.

The cold target-2 branch stops at g=26. Refusing the unexecutable hearts switch also refuses the v0.111 suffix that had reached g=32 with 29 face-down and 8 bonds. The replacement branch reveals two cards and adds one bond, then suspends.

From the g=32 board the in-horizon deal rule still allows a required-card deal and later measured deals while the operational epoch is 5 and the current epoch is 2, 3, or 4. Three such deals empty the stock. Face-down stays 29. The clubs run is real. The missing excavation is still on the board, and no future row remains.

`S#2` is eligible at every yield and is not scheduled. The adopt cap of 2, which the unit test requires, spends its switches on `D#1` and `C#1`. Recovery then misses `Ks` inside cost 3 and does not become a campaign.

The first choice on an empty lock is still the primary. At g=32 that is the elapsed hearts campaign. The feasibility gate only blocks a later displacement.

Seed 111, `random.Random(111)` shuffled into a 104-card deal, cold `--goal foundations --target-foundations 1`, 40 seconds, 40 steps: `STEP_LIMIT` at g=15, foundations 0, one `DEAL:S#1` at g=3, 15 actions, 161 objectives attempted, 16 unique states, 10.941 seconds, peak RSS 44.55 MB, prefix not injected. Opening rank: `S#1` epoch 3 cost 40 deferred, `D#1` epoch 4 cost 44 deferred, `H#1` epoch 5 cost 43 deferred, `C#1` epoch 2 cost 41 blocked. The preferred suit is present. After the measured deal the tail repeats `prepare column 5 before the deal; corrected preparation-plus-deal cost 3` for an ace of spades that is face-down on column 1 and face-up on column 2, not on landing column 5. `C#1` stays untried. Scheduling did not freeze for lack of a suit. It repeated one receiver preparation until the step budget.

The g=19 opening is still a discovered candidate with 33 face-down and one bond at the first removal. This release does not search an alternative opening when the downstream line gets expensive.

## 15. Recommended v0.113

Keep this controller. Do not add a second search kernel, and do not start the best-g kernel on a foundations goal.

The evidence that would justify the next change is a replay-verified second removal, or a continuation that reduces face-down without spending the whole stock. The present traces say where that work is stuck:

1. An in-horizon deal that does not reveal a card must not be repeated until the stock is empty. The g=52 line's three clubs deals are each evidenced. Their joint result is 29 face-down and no stock.
2. `S#2` needs a scheduled turn or an explicit suspension that names the `Ks` cover, rather than exclusion by a switch cap of 2. Raising the cap without a reveal guard will deal again.
3. The empty-lock choice should be allowed to pass over an elapsed primary when another suit has a demonstrated access step. Hearts at g=32 is probed and yields. That probe is useful once. It should not be the only way diamonds gets a turn.
4. The seed-111 column-5 preparation has to suspend when the parent is not on that landing column, and the blocked clubs campaign at epoch 2 has to be eligible. The same suspend-and-yield path that freed diamonds on 4925153 does not catch this repeated align.
5. The cold post-removal branch should be compared with the v0.111 suffix on face-down and bonds, not only on whether a hearts displacement was refused. A refusal that stops at g=26 with `move 9 10 1` unplayed has not yet replaced that suffix.
6. The g=19 ancestry stays reversible. A later opening search has the structural snapshot in the v0.111 report as its reason. This release did not run that search.

Leave principle 11 CONDITIONAL until `--goal play` changes a decision the v0.107 registry test already names.

## 16. Reproduce

Branch `local/campaign-recovery-v0-112`. HEAD `daf27052f8328a3376e3c93b712568f1fd86ae13` (`Add multi-foundation continuation and receiver alignment v0.111`), which descends from `354a83fcb26e3b9b05884f4254e36900928faed3`. The v0.112 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py -q --tb=line
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal first-foundation --time-limit 40 --max-steps 80 --workers 1 --out artifacts/human_strategy/v0_112/cold_first.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 150 --max-steps 220 --workers 1 --out artifacts/human_strategy/v0_112/cold_two.json
```

The benchmark summary for the bounded A–D driver is `artifacts/human_strategy/v0_112/benchmark_summary.json`. That directory is gitignored. The four solves together finished in about 45 seconds. Peak RSS of those runs was 44.55 MB.

Files touched:

```text
src/spider/human_strategy/__init__.py
src/spider/human_strategy/controller.py
src/spider/human_strategy/foundation_direction.py
tools/human_strategy_solver.py
tests/test_human_strategy_v0_112.py
docs/campaign_recovery_v0_112.md
```

## 17. Git

```text
branch: local/campaign-recovery-v0-112
HEAD:   daf27052f8328a3376e3c93b712568f1fd86ae13
status:
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M tools/human_strategy_solver.py
?? docs/campaign_recovery_v0_112.md
?? tests/test_human_strategy_v0_112.py
```

No commit, push, merge, or pull request.
