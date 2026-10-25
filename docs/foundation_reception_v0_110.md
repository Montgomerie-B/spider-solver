# Foundation reception v0.110

v0.109 can remove a foundation once the prerequisites are already in place. On deal 4925153, from the canonical prefix of 82 actions, it deals and then plays `move 2 1 12`, reaching the first spade foundation at cumulative corrected MobilityWare g=83. From the opening it does not. The 150-second cold run ends at g=44 with the stock empty, 28 cards face-down, 24 same-suit bonds, and zero foundations. The clock does not bind. The run stops at 19.562 seconds.

v0.110 keeps that controller. It adds three decisions on the same first-foundation path: a locked operational epoch that a failed reveal cannot advance, a bounded legal sequence for a face-up card that is not yet movable, and a stock deal that is authorised only by a measured same-suit connection inside that locked horizon. The default `--goal play` path is unchanged.

This is not a new solver. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

## 1. Root cause of the v0.109 epoch drift

The campaign analyser returns a fresh `target_removal_epoch` on every reanalysis. On the cold line that number moved from 2 to 3 to 4 while the suit stayed `S#1`. Two helpers treated the new number as permission to deal:

- `_unlocking_deal`, when no one-ply reveal existed.
- `_frozen_row`, when the tableau had already been tried since the last deal.

Both produced the reason `selected: foundation plan deals one row because the tableau cannot reveal`. Each outward revision justified another row. Five deals emptied the stock. The suit was no closer to a legal removal.

A failed direct reveal and a tactical timeout are evidence about one attempt. They are not evidence that the suit can be finished only after another deal. v0.110 leaves both helpers in the file and does not call them.

## 2. Root cause of the premature stop

v0.109 reports `EXHAUSTED` with the reason `principal objective failed and no dormant alternative remained`. At the stop, 8 legal tableau moves are still present and the stock is empty. That is not a proof that every continuation was examined. The strategic phase simply has no objective it is willing to play. The best-g kernel is not started for `--goal first-foundation`, so the leftover 130 seconds are not used.

The first v0.110 cold attempt, before the measured-connection deal existed, made the same shape of mistake earlier and more honestly. It stopped at g=10 after 3.223 seconds, with 50 cards still in stock, 34 face-down, 5 bonds, 0 foundations, and 4 legal tableau moves. Status was `PLANNING_STALL`. Peak RSS was 39.93 MB. The foundation proposer had blocked the deal because the locked epoch was 2 and the shape policy does not recommend an intermediate row. Receiver search had already reported that the 9 of spades was sitting on the column the next 9 of spades would land on. No purpose-met substitute was legal, so the controller refused the dormant deal and stopped. The 4 moves were a queen parked onto an off-suit king, and three splits of the 7–2 spade run. None of those is a reason to declare the search finished, and none of them is the 9 of spades landing.

`PLANNING_STALL` is the right label for that stop. It is not a proof. The fix is to deal when the next row's connection has been measured, which is what the reported run does.

## 3. Decision path

`propose_foundation_step` still runs only for `--goal first-foundation`, after the portfolio has ranked candidates and only when the line is not holding a committed step. The order is:

1. A legal move that removes the selected foundation.
2. A mandatory excavate. A miss records `foundation: tactical miss on <id> does not make <suit> impossible` and does not change the operational epoch. Three misses suspend that one id. A legal peel of the same column is still played. A timeout does not retire the suit.
3. A same-suit join that lengthens the locked suit and does not take a proper suffix out of a protected run. Moving the whole run is allowed, including a zero-cost whole-column transfer.
4. If a mandatory excavate is still open, `plan_obstructed_access` searches for a legal uncovering sequence. If it finds one, only the first action is played. If it finds none, the deal is blocked. The event is `foundation: deal waits on <id>`.
5. A broken protected run blocks the deal.
6. If the next row is exactly the locked operational epoch, the campaign policy recommends a deal, and this state has not just dealt a barren row, the controller deals. The reason stays `selected: foundation plan deals after its prerequisites`. Receiver alignment is not consulted first. This is the canonical-action-82 path.
7. If the locked epoch is still ahead of the next row, the event names that epoch and the policy. If the analysed epoch differs from the operational epoch, a second event says the analysed epoch does not authorise a deal.
8. Access search runs again for any chosen tableau card that is not already a legal run head.
9. Receiver alignment runs for at most three chosen incoming cards of the locked suit, at corrected cost 3 and 500 expansions. A plan is played only when `compare_exact_reception` says preparation creates a same-suit landing, or a queen-led follow-up onto a king, that dealing immediately lacks, and the preparation cost is at most the deal cost plus 3.
10. `measured_stock_connection` may deal one row inside the locked horizon. The rule is in section 6. A raised analysed epoch is not an input.
11. `_horizon_deal` can still deal one intermediate row when the policy itself recommends a deal, a named card of the suit is still in a later stock row, and no one-ply reveal exists. The opening policy `shape_receivers_then_deal_do_not_fetishize_empty` does not recommend that deal. The reason, when it fires, is `selected: locked stock horizon still needs a row after preparation was tried`.
12. Otherwise the deal is blocked. If the portfolio's choice is a deal and no other legal move meets its declared purpose, and no dormant line remains, the status is `PLANNING_STALL` while any tableau move remains. `EXHAUSTED` is reserved for a state with no legal continuation, and for `--goal play`.

`ACCESS` and `ALIGN` candidates are executed like a one-step tactical move. The corrected cost is added to the campaign record's `cost_invested`.

## 4. Campaign record and epoch rules

The lock kept across moves holds the suit label, the original target epoch and the rationale frozen at selection, the theoretical epoch, the operational epoch, the latest analysed epoch, required cards, outstanding and achieved prerequisites, blockers, unresolved access notes, receiving requirements, cost invested, alternatives, and suspensions. Every revision appends old epoch, new epoch, the state change, the prerequisite, the evidence, and why the stock decision changes. A rejected upward forecast is stored and emitted once per old epoch, new epoch, and stock length: `foundation: rejected epoch revision X -> Y; a forecast does not authorise another stock row`.

`revise_operational_epoch` raises the operational epoch only when a foundation was removed, when new stock information makes the analysed epoch earlier than the lock, or when stock has changed and a named rank's tableau count has fallen and the analyser now wants a later epoch. Burying a card under a deal does not reduce that count, so a deal cannot by itself walk 2 to 3 to 4. A downward revision after a stock change is allowed. Switching suits clears the epoch record.

On 4925153 the opening lock is `S#1`, original epoch 2, theoretical epoch 2, operational epoch 2. The cold run's `epoch_changes` and `rejected_revisions` are both empty at the removal.

The target suit can stay locked while the prerequisite plan changes. The schedule may replace the suit only when the new schedule objective is at least 8 better, or the target epoch is more than one earlier and the objective is within 2.

## 5. Multi-action prerequisites

`plan_obstructed_access` is a Dijkstra search on legal tableau moves. It does not deal. It does not split a protected run. Cost is the engine's corrected MobilityWare cost, so a zero-cost whole-column transfer stays free. Bounds are corrected cost 4 and 2500 nodes. `not found` means the bound was exhausted.

A face-up card is not treated as movable. The search succeeds when the card becomes a legal run head, or when its cover falls to zero and the cover started above zero. A card that starts at depth 0 and is not a legal head is not solved by an unrelated move that leaves it at depth 0. The queen of spades at canonical action 31 is the regression: she is face-up on column 2 under the jack and 10 of diamonds, and no legal move has her as its head. The search returns a sequence whose first action is `move 7 3 1`. Replaying the sequence drops her cover from 2 to 0. The operational epoch stays 2.

The candidate id is `access:<source_key>`. Only the first action is executed. The full sequence is in the evidence. The same source is not retried from an unchanged state. A stored miss is a miss of that attempt.

At canonical action 31 the direct excavate still misses first. The miss text remains `does not make S#1 impossible`. The access step is then selected. A failed reveal is not turned into a deal and is not turned into epoch 3.

Temporary parks are legal. The first step of that queen sequence moves the 6 of clubs onto the 7 of diamonds. Mixed-suit moves are not banned and are not scored as progress on their own. An off-suit park is played when it is a step of a checked sequence that uncovers a named card.

## 6. Receiver alignment and the measured deal

The next row is `stock[-10:]`, one card per column. Alignment asks `run_bounded_shaping_probe` for a same-suit parent on that column.

- `already_satisfied` means the parent is already the top. The note is `receiver for <card> is already the top of column <n>; no relocation is required`. It is not reported as unreachable.
- `not_found_within_bound` means no legal relocation was found inside cost 3. It is not a proof that none exists.
- A found path is cloned, applied, dealt, and compared with dealing immediately. `compare_exact_reception` uses corrected costs. Preparation is selected only when it creates a connection the immediate deal lacks. An illegal path is rejected. A relocation that both states already connect loses to dealing now.

An incoming king has no rank-14 parent. Alignment records whether a queen-led run of the locked suit can move onto that king after the deal. The king landing is not a removed foundation. The cold run's second deal says so in the evidence: `after the deal move 2 1 12 removes the suit; the landing itself is not the foundation`.

`measured_stock_connection` authorises a deal without moving a receiver when all of the following hold:

- The next row is inside the locked operational horizon (`current + 1 <= operational`). A row past the lock is refused even if it connects.
- The state can deal, the deal id has not failed on this state, and the previous deal was not barren.
- The replayed deal creates a same-suit landing of the locked suit, or a legal follow-up that uses one of the newly dealt cards and extends that suit. Card identity is used, not rank-and-suit equality.
- No exposed same-suit run of length 3 or more is covered by a card that has no legal one-card move, unless the new card is itself the same-suit continuation of that run. The ace of spades onto the 2 of spades is a continuation. The 4 of diamonds onto the 2 of spades is a cover. The cold run's first deal covers a 6-card spade run with the 4 of diamonds, and one legal move lifts that cover, so the deal is allowed and the cover is named in the evidence.

The reason is `selected: a known incoming card enables a same-suit connection after preparation was tried`. The evidence includes the corrected deal cost, the landing, the follow-up, any cover, and `the operational epoch was not revised to authorise this row`.

A long run that would be buried with no one-move recovery refuses the deal even when a landing exists. `test_an_unrecoverable_long_run_blocks_a_cosmetic_deal` builds that board. Adding a 5 that the covering 4 can move onto makes the same landing acceptable.

## 7. What the cold run did with those rules

Command and output path are in section 12. The run is `FOUNDATION_REACHED`, solved false, partial trajectory true, prefix not injected, replay ok. Corrected suffix cost 19. One spade foundation, king through ace. Peak RSS 41.46 MB. Elapsed 8.006 seconds. Unique states 20. The clock and the 400-step cap do not bind. Three stock rows remain. The next ranked suit after removal is `D#1` at epoch 4, estimated cost 24, not theoretically available. The solve stops there, as v0.109 does.

The first decision is still `excavate:r12:d1`, `move 3 6 1`. The cost-led one-ply choice is deal. The controller does not take it.

No event contains `one more stock row` or `because the tableau cannot reveal`. `epoch_changes` is empty.

### Stock boundaries

Opening: g=0, 44 face-down, 0 bonds, 0 foundations, 50 cards in stock, target `S#1` operational epoch 2.

Deal 1, before the action, g=9, 35 face-down, 5 bonds, 0 foundations, stock 50. Target epoch 2, now epoch 0. Operational epoch stays 2. Preparation already played is the queen excavate, the joins that built the 7–2 of spades, and the access move that shifted the queen. Alignment did not move a receiver: the jack cannot reach column 1 within cost 3, the 9 of spades is already the top of column 7, the 8 of spades cannot reach column 9 within cost 3. The deal is authorised because 9 of spades lands on 10 of spades. Corrected deal cost 1. The 6-card spade run is covered by the 4 of diamonds and one legal move lifts it. The queen is covered by the 9 of diamonds. Six legal tableau moves remain: `move 2 5 1`, `move 3 8 2`, `move 3 1 3`, `move 3 4 5`, `move 3 9 5`, `move 8 1 1`. After the deal: g=10, 35 face-down, 6 bonds, 0 foundations, stock 40.

The moves after that deal uncover the queen and the spade run and assemble them. They are access and join steps, not a second stock row. The king row is deferred until the ace's column is the run.

Deal 2, before the action, g=17, 33 face-down, 11 bonds, 0 foundations, stock 40. Target epoch 2, now epoch 1. Operational epoch stays 2. The incoming king on column 1 is recorded as not a completed foundation. The queen-led follow-up is true. The ace's receiver is already the top of column 2. The measured landing is ace of spades onto 2 of spades. The replayed follow-up is `move 2 1 12`, which removes the suit. Fifteen legal tableau moves remain, including `move 2 4 11` and `move 1 7 1`. After the deal: g=18, 33 face-down, 12 bonds, 0 foundations, stock 30.

The next action is `FOUNDATION:S#1`, `move 2 1 12`, actual corrected cost 1. After it: g=19, 33 face-down, 1 bond, 1 spade foundation, stock 30. The bond count falls because the removed run leaves the tableau.

### Comparison with v0.109

| | v0.109 cold | v0.110 cold |
| --- | --- | --- |
| Status | EXHAUSTED | FOUNDATION_REACHED |
| Corrected g | 44 | 19 |
| Face-down | 28 | 33 |
| Same-suit bonds | 24 | 1 after the removal, 12 immediately after the second deal |
| Foundations | 0 | 1 spade, king through ace |
| Deals | 5, stock empty | 2, 30 cards left |
| Elapsed | 19.562 s | 8.006 s |
| Peak RSS | 44.45 MB | 41.46 MB |
| Epoch | analysed target moved 2 to 3 to 4 | operational epoch stayed 2, no revision |
| Stop | legal moves remained; called exhausted | first foundation; partial trajectory |

The face-down count is higher, and the final bond count is lower, because the run that made the foundation has left the board and the later rows were not dealt. Those two figures are not the claim. The claim is the replayed removal at g=19, with both deals tied to a named landing inside the original epoch. Canonical first foundation remains g=90. The autonomous 185 first foundation remains g=71. This route is a partial trajectory. It is not a finished game and it is not a claim that g=19 dominates those full-game lines.

## 8. Checkpoints

Canonical prefixes are replayed only to reach a state. The reference suffix is not passed in.

| State | Result |
| --- | --- |
| Canonical action 31 | Queen of spades is face-up and not a legal head. Obstruction is the jack and 10 of diamonds. First selected step is `access:tableau:1:up:1`, `move 7 3 1`. Operational epoch stays 2. The miss is recorded and does not advance the epoch. |
| Canonical action 82 | `deal`, then `move 2 1 12`. Id `DEAL:S#1`. Reason `selected: foundation plan deals after its prerequisites`. Status `FOUNDATION_REACHED`, solved false, one foundation, suffix corrected cost 2, cumulative g = 81 + 2. The deal itself removes nothing. A queen-led spade run can move onto the king after the deal. |
| Opening, cold | Section 7. First foundation at g=19. |

Synthetic boards, not the real prefix:

- A 6 of spades can be moved onto the column that will receive the 5 of spades. The probe finds the path, the comparison chooses prepare, and the replay lands 6 then 5. The same 6 trapped under a king is `not_found_within_bound`. An illegal move is rejected.
- A receiver that is already on the landing column loses to dealing now. The extra relocation costs more and creates no new connection.
- An incoming king at canonical action 82 still deals. The new epoch lock does not block that row.
- Stuffing the prefix-31 excavate failures to 3 and blocking those ids does not produce a deal, and the operational epoch stays 2.

## 9. Strategy coverage

The registry is still 28 ACTIVE and 2 CONDITIONAL. Principle 11 stays CONDITIONAL. The registry file was not edited. The new tests live in `tests/test_human_strategy_v0_110.py` and do not change the v0.107 pointer `test_longer_run_is_extended_first`.

Paths the new tests exercise:

| Behaviour | Call | Test |
| --- | --- | --- |
| Face-up queen is not movable; a legal unblock is played; the epoch stays | `plan_obstructed_access`, `propose_foundation_step` | `test_early_queen_is_face_up_but_not_movable` |
| Close checkpoint still deals, then removes spades | `solve` on prefix 82 | `test_close_checkpoint_still_deals_then_removes_spades` |
| Legal receiver relocation, and a trapped receiver rejected | `run_bounded_shaping_probe`, `compare_exact_reception` | `test_receiver_alignment_places_a_legal_parent_and_rejects_a_trapped_one` |
| Incoming king still deals on the locked next row | `propose_foundation_step` on prefix 82 | `test_incoming_king_still_deals_when_the_locked_horizon_is_the_next_row` |
| Wasteful relocation loses to dealing now | `compare_exact_reception` | `test_wasteful_receiver_relocation_loses_to_dealing_now` |
| A failed reveal does not walk the epoch | `revise_operational_epoch`, prefix 31 with stuffed failures | `test_a_failed_reveal_does_not_walk_the_epoch_forward` |
| Unblock is more than one legal action | `plan_obstructed_access` | `test_multi_step_unblock_is_more_than_one_legal_action` |
| Legal moves left are a planning stall, including under a blocked proposer | `strategic_stop_status`, `solve` | `test_remaining_legal_moves_are_a_planning_stall` |
| A measured landing deals inside epoch 2 and does not revise it | opening `propose_foundation_step` loop | `test_measured_connection_deals_inside_the_locked_horizon` |
| A long run with no one-move recovery blocks a landing | `measured_stock_connection` | `test_an_unrecoverable_long_run_blocks_a_cosmetic_deal` |

The 22 v0.109 tests still pass, including the shape-policy delay, the opening excavate-before-deal, and the prefix-82 reason string.

## 10. Tests, runtime, memory

Schema is `spider-human-strategy-0.110`. One worker. Profiles are unchanged: smoke 20 s, pilot 600 s, extended 3600 s. The cold benchmark overrides the pilot clock to 150 s and uses the pilot RSS abort of 3072 MB.

Timing on the campaign lock at the removal decision, cumulative for that solve:

| Bucket | Seconds |
| --- | --- |
| Foundation analysis | 6.7639 |
| Tactical realisation | 0.0675 |
| Dependency planning | 0.0490 |
| Receiver alignment | 0.0509 |
| Consequence comparison | 0.0000 |

Consequence comparison is accounted inside the alignment call and inside `measured_stock_connection`. The separate bucket stays at zero. Cache misses 17, cache hits 0. Peak RSS 41.46 MB.

`tests/test_human_strategy_v0_110.py` and `tests/test_human_strategy_v0_109.py` together: 32 passed in 24.76 s.

The regression command in section 12, run after the final controller change: 291 passed in 141.30 s. The v0.109 file alone had been 281 passes before this release. The ten new tests are the difference. Exit code 0.

Search bounds stay as coded: access cost 4 and 2500 nodes, alignment cost 3 and 500 expansions, tactical profile nodes 4000 on the pilot cold run. `not_found_within_bound` is not infeasibility. Source combinations remain capped at 4.

## 11. Unresolved issues

- The trajectory is partial. Three stock rows and 33 face-down cards remain. Seven suits are still on the board. The solve stops after the first removal by design.
- `D#1` is the next campaign and is not theoretically available until epoch 4. Continuing it under the same evidence rules is open work.
- `obligation_is_satisfied` for a shape-receiver is still true when a parent exists anywhere, not only on the landing column. Alignment and `measured_stock_connection` check the actual column. The obligation flag does not.
- A measured deal may cover a short card, such as the queen under the 9 of diamonds on the first row, when a longer run's cover can be lifted. The cold line does lift the queen and the 6-card run before the king row. A cover that needs more than one move is not searched inside the deal test.
- The consequence-comparison timer does not include the comparison work.
- `--goal play` is the v0.108 controller. Principle 11 stays CONDITIONAL.
- `PLANNING_STALL` is still returned when a deal is blocked, no purpose-met tableau move exists, and no measured connection is inside the locked horizon. That is a stall with legal moves left, not a proof.

## 12. Reproduce

Branch `local/foundation-reception-v0-110`. HEAD `354a83fcb26e3b9b05884f4254e36900928faed3` (`Add foundation-directed strategic planning v0.109`). The v0.110 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py -q --tb=line
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal first-foundation --time-limit 150 --max-steps 400 --strategic-width 2 --max-width 3 --out artifacts/human_strategy/v0_110/cold_150s.json
```

The cold artifact is gitignored. The run reported here wrote that path and printed:

```text
status=FOUNDATION_REACHED mw=19 solved=False steps=19
elapsed_s=8.006 peak_rss_mb=41.46484375 unique_states=20
first=REVEAL excavate:r12:d1 cost_led=deal
foundation=D#1 partial=True foundations=1
```

`foundation=D#1` is the suit ranked after the spade removal, not the suit that was removed. The removal decision is `FOUNDATION:S#1`.

## 13. Recommended v0.111

Continue past the first removal with the same lock, the same epoch rule, and the same measured-deal test. `D#1` on this board is not available until epoch 4, so the next suit has to earn its own landings. Do not start the best-g kernel and do not add a second planner.

Make the shape-receiver obligation true only when the parent is on the column the child will land on. Put the clone-and-deal comparison into the consequence-comparison timer. A cover that needs two legal moves, rather than one, can use the existing access search before the deal is refused.

Leave principle 11 CONDITIONAL until `--goal play` changes a decision the v0.107 registry test already names.
