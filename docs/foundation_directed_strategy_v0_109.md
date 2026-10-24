# Foundation-directed strategy v0.109

v0.108 can hold a preparation, compare it with a deal, and recover from a failed objective. On deal 4925153 its 150-second cold run still ended with no foundation: corrected MW 53, 26 face-down, 16 same-suit bonds, stock empty. Local reveals and bonds never became a suit-removal plan.

v0.109 keeps that controller. When `--goal first-foundation` is set, each decision asks the existing foundation-campaign analyser which suit to finish, turns that campaign's obligations into a prerequisite list, and plays a legal step of that list. The default `--goal play` path is unchanged.

This is not a new solver. `engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified.

## 1. Why v0.108 never removed a suit

The v0.108 cold line is in `docs/strategic_preparation_v0_108.md`. Replaying it gives g=53, five deals, 26 face-down, 16 bonds, 0 foundations, 8 legal moves, TIME_LIMIT at 150.090s, peak RSS 209.65 MB. v0.107 had ended at g=27, 36 face-down, 16 bonds, 0 foundations.

Three facts from that run matter here:

1. Objectives were local. A reveal, a bond, or an empty column could win the comparison without naming the suit those cards belonged to.
2. The deal comparison used face-down exposed, bond change, and foundation change. It did not ask which buried card a chosen foundation still needed.
3. `rank_ready_suits` returns no ready suit at the opening, because no suit is complete. It cannot choose the first foundation. The campaign analyser can, and v0.108 never called it.

## 2. Modules reused

The new file `src/spider/human_strategy/foundation_direction.py` is an adapter. It does not reimplement feasibility or search.

| Existing function | Role in the controller |
| --- | --- |
| `analyze_foundation_feasibility` | Availability: face-up, face-down, stock, earliest epoch, burial. |
| `analyze_foundation_campaigns` | One next ordinal per suit, with cost, readiness, confidence, and blockers. Source combinations stay capped at 4. |
| `campaign_obligations_for_next_epoch` | The prerequisite list for the next stock row. |
| `obligation_is_satisfied` | Whether an excavate or a preserved fragment is already true. |
| `_objective_for_prefix` | The excavate turned into a `StrategicObjective`. |
| `realize_objective` in `FAST_BOUNDED` | A bounded legal path for that objective. |
| `next_stock_row` | The exact ten cards the next deal will place, and where. |
| `schedule` fields on `FoundationCampaign` | Ordering only. `schedule_objective` adds `6 * epoch delay` and a confidence penalty. It does not prune. |

Not on the decision path, on purpose:

- `rank_ready_suits`. It is empty until a suit is already completable.
- `assess_deal_timing`. The campaign's `space_plan.next_deal_policy` is what the adapter reads.
- `realize_campaign_to_next_epoch`. It forces one stock row and can spend a large node budget. The controller realises one prerequisite at a time instead.

## 3. Integration points

Call path, only when `solve(..., goal="first-foundation")`:

1. `tools/human_strategy_solver.py` passes the full deal and `goal`.
2. `controller.solve` rejects cold mode if an incumbent prefix is supplied. It does not read a solution file.
3. After `select_candidate`, and only when the line is not already holding a committed step, `propose_foundation_step` may replace the choice.
4. A held trailing `("deal",)` is cleared first, with the event `foundation: a bundled deal is reconsidered against the campaign`, so a v0.108 preparation cannot deal before the campaign looks.
5. If the proposal blocks a deal and some other legal move actually meets its declared purpose, that move is played. If none does, the deal is not played from that state.
6. When a foundation count increases and the game is not over, status becomes `FOUNDATION_REACHED`. `rank_foundations` names the next suit. The result is a partial research trajectory. The constructive kernel does not run, so leftover clock is not spent on best-g search.
7. `--goal play` never enters steps 3–6. Schema version is `spider-human-strategy-0.109`.

## 4. How a foundation is selected

`rank_foundations` builds one view per suit ordinal returned by the campaign portfolio. On the opening of 4925153 the labels are `S#1`, `H#1`, `D#1`, and `C#1`. There is no suit constant in the selector.

Each view separates three tiers:

- Theoretically available: current epoch is at least `earliest_epoch`. At the opening none of the four are. Spades and hearts are earliest at epoch 2, diamonds at 4, clubs at 5.
- Operationally attainable: readiness is `ready_now`, `excavation_led`, `assembly_led`, or `stock_gated`, and the campaign lists no blocker.
- Economically attractive: the portfolio's primary, which is the minimum of campaign cost, then `6 * (target epoch - current epoch)`, then a confidence penalty (HIGH 0, MEDIUM 2, LOW 6).

Empty columns are shared. The reason text says they do not choose the suit. Swapping the spade and heart cards in the real 104-card deal flips the winner from `S#1` to `H#1` (`test_priority_is_not_hard_coded_to_one_suit`).

The other physical copy is reported as `other_copy_earliest`. It is the later ordinal of the same suit, not a second use of the chosen cards. Chosen `source_key` values are unique (`test_duplicate_physical_sources_are_unique`). Card equality is not used to tell the copies apart.

The lock keeps the same label across moves. A different suit replaces it only when its schedule objective is at least 8 better, or its target epoch is more than one earlier and the objective is within 2. A single tactical miss does not clear the lock.

## 5. Prerequisite plan

`_agenda` copies two kinds of obligation into explicit prerequisites:

- `EXCAVATE_PREFIX`, one per required rank. Fields: id, rank, column, source keys, estimated peels, `mandatory_before_deal`, and whether `obligation_is_satisfied` is already true. The objective is the realiser's prefix objective.
- `PRESERVE_FRAGMENT` for a same-suit run already at a pile top. Splitting it, taking a proper suffix out of the run, is refused. Moving the whole run is allowed.

`MAKE_RANK_USABLE`, `SHAPE_RECEIVER`, `APPLY_DEAL`, and `VERIFY_POST_DEAL` are not separate moves. The deal is one later decision, and only after the mandatory excavates are actually satisfied. A preserved run that has been broken blocks the deal.

On the opening, the first proposal is an unachieved mandatory excavate of the queen of spades (`test_buried_card_becomes_a_prerequisite`). The plan is recomputed from the current state every decision. It is not a stored script.

## 6. Tactical realisation

For each unachieved mandatory excavate, in order:

1. `realize_objective` with a bound of at most 1.2s, 1500 nodes, and cost 8, and never above the active profile. A path that deals in the middle is rejected. A trailing deal is stripped and not played as part of the excavate.
2. On `RESOURCE_LIMIT`, the event is `foundation: tactical timeout does not retire {label}`. One legal peel of that column is still tried. The campaign stays locked.
3. On a miss, the event is `foundation: tactical miss on {id} does not make {label} impossible`. Three misses suspend that id only (`foundation: suspend {id}; campaign {label} stays open`). Suspension is not proof the suit is impossible, and it does not by itself authorise a deal.
4. If a legal one-ply peel of the column remains after suspension, it is still played.
5. Otherwise a same-suit join that lengthens the locked suit without splitting a protected run.

A repeated candidate id, including `JOIN:{label}` after `repeat state at no better corrected cost`, is passed in as `blocked` and is not proposed again at that state.

`_completion_move` scans legal tableau moves for one that increases the foundation count. That is how a finished run is removed. It is not a best-g search.

Failure text stays distinct: achieved, partial, tactical miss, timeout, and "the campaign stays open". A timeout is not recorded as infeasible.

## 7. Commitment and replanning

The lock stores the label, the stock length, per-prerequisite failure counts, and whether the choice was announced. While the lock holds, a slightly better one-ply score from the v0.108 portfolio does not replace the campaign. `foundation: continue {label}` is the marker, and the opening solve emits it across more than one action (`test_campaign_persists_across_actions`).

Replan events:

- `replan: foundation campaign after stock` when the stock length changes.
- `replan: foundation campaign after removal` when a foundation is removed, followed by the next ranked suit, its epoch, and its cost. The solve then stops. Continuing into the second suit is left to v0.110.
- A switch event only under the schedule gap in section 4.

The close-checkpoint test (`test_stock_deal_replans_the_campaign`, `test_foundation_removal_replans_the_next_suit`) sees both the stock replan and the removal replan, and the provenance record `reason=after removal`.

## 8. Deal timing

A deal is a campaign action only in three situations.

1. Completing row. The next epoch equals `target_removal_epoch`, mandatory excavates are satisfied, the protected run is intact, `barren_deals` is 0, and `space_plan.next_deal_policy` starts with `deal_now`, `fill_then_deal`, or `carry_empty`. This is the close checkpoint. The reason is `selected: foundation plan deals after its prerequisites`.
2. The target epoch is still later, and no legal tableau move reveals a card. One row is tried. The reason says the tableau cannot reveal.
3. The target epoch is already in hand, the tableau still cannot reveal, and at least one tableau state has been played since the previous deal. One more row is tried. Two deals with no tableau state between them are refused.

While a mandatory excavate is unachieved and a reveal exists, the event is `foundation: deal waits on {id}` and the deal is blocked. While the target epoch is not the next row, the event is `foundation: target epoch N is not the next row; {policy} delays the deal` (`test_shape_policy_delays_an_intermediate_deal`).

`deal_now_workspace_recreates_cheaply_after` is not treated as "deal all remaining rows". It only authorises the single completing row.

What still goes wrong on the cold line is recorded in section 10. After each of those exceptional rows, reanalysis moved `target_removal_epoch` outward (2, then 3, then 4). Each time the tableau had no reveal, rule 3 dealt again. The guard stops a double deal on the same state. It does not stop a campaign whose target epoch keeps sliding forward. That is the remaining stock-exhaustion hole. It is not a fixed reveal quota, and it is not a hard-coded suit.

## 9. Controlled checkpoints

Both checkpoints replay a prefix of `solutions/4925153_canonical.moves` only to reach a state. The note is `diagnostic canonical prefix N; suffix not injected`. Provenance records `prefix_injected=false` and `assisted_suffix=false`. Cold mode never calls `parse_moves_file` (`test_cold_mode_does_not_read_solution_files`).

### Close to a foundation

Prefix: the first 82 canonical actions. Measured state before the controller runs: corrected g=81, 8 face-down, 40 stock cards, 0 foundations. The controller's own suffix is `deal`, then `move 2 1 12` (0-based `(1, 0, 12)`). Suffix MobilityWare cost is 2. Cumulative corrected cost is 83. Status is `FOUNDATION_REACHED`, `solved` is false, one foundation is removed, `partial_trajectory` is true, and the prefix was not injected. Elapsed 0.323s, peak RSS 27.6 MB. The locked suit is `S#1` at target epoch 2, estimated cost 4. After removal the next ranked suit is `H#1`, epoch 2, estimated cost 15.

That first action is not canonical action 83. The suffix does not include the reference shaping move `(1, 0, 2)` and is not the reference suffix. `test_checkpoint_completes_a_real_foundation` checks the status, the partial flag, the replay, and `cumulative_g == prefix cost + suffix cost`. A one-move fixture is not this test: the deal and the removing move are different actions, and the protected spade run is still under a king before the deal.

This is a partial research trajectory. It is not a new deal record and not a cold discovery. The canonical first foundation remains g=90. The autonomous 185 first foundation remains g=71. Neither file was modified.

### Earlier state

Prefix: the first 31 canonical actions. Face-down is still above 10. The queen of spades on column 2 is face-up but not in the movable same-suit suffix, and no legal move starts on that column. The face-down objective is already numerically satisfied, so the realiser returns a miss.

`test_earlier_checkpoint_still_has_excavation_work` requires the first action not to be a deal, the locked suit to stay `S#1`, a tactical-miss event that does not call the suit impossible, and a `foundation: continue S#1` event. The suffix is not injected. A later deal inside three steps is allowed. The miss is not treated as infeasibility (`test_tactical_timeout_does_not_retire_the_campaign` also forces three failures and checks that the label stays and the deal is not substituted for the open excavate).

## 10. Cold benchmark from move 0

Command (clock 150s, step cap 400 so the cap is not the v0.108 80-commit limit; this goal does not spend leftover time in the kernel):

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal first-foundation --time-limit 150 --max-steps 400 --strategic-width 2 --max-width 3 --out artifacts/human_strategy/v0_109/cold_150s.json
```

Result, replayed from that artifact onto `deals/4925153.txt`:

| | v0.109 cold |
| --- | --- |
| Status | EXHAUSTED |
| Stop | principal objective failed and no dormant alternative remained |
| Corrected MW g | 44 |
| Deals | 5 (stock empty) |
| Face-down | 28 |
| Same-suit bonds | 24 |
| Foundations | 0 |
| Legal moves at end | 8 |
| Elapsed | 19.562s |
| Peak RSS | 44.45 MB |
| Unique states | 44 |
| Objective attempts | 94 (31 achieved, 51 failed, 49 backtracks) |
| Solved | false |
| Partial trajectory | false |

The 150-second clock did not bind. The strategic phase ended in under 20 seconds. There is no MobilityWare solution score, because the route is not finished.

The first decision is `REVEAL excavate:r12:d1` (`move 3 6 1`), not a deal. The locked suit is `S#1` from the opening through the end. Four events say the target epoch is not the next row, so the first deal waits until action 12. Two later rows are the "tableau cannot reveal" exception. Two more are the "target epoch is in hand, one more row" exception, after reanalysis had raised the target to 3 and then to 4. All five rows are dealt. The campaign continues (`foundation: continue` 85 times) and does not remove a suit.

Face-down along the deals, after each deal: 34, 31, 31, 29, 29. Bonds: 6, 10, 11, 12, 13, and 24 after the post-stock tableau moves.

## 11. Comparison with v0.108

Same deal, cold, no solution suffix. v0.108 figures are from `docs/strategic_preparation_v0_108.md` and were not re-run.

| | v0.107 | v0.108 | v0.109 |
| --- | --- | --- | --- |
| Corrected g | 27 | 53 | 44 |
| Face-down | 36 | 26 | 28 |
| Same-suit bonds | 16 | 16 | 24 |
| Foundations | 0 | 0 | 0 |
| Deals | 5 | 5 | 5 |
| Elapsed | 150.049s | 150.090s | 19.562s |
| Peak RSS | 126.52 MB | 209.65 MB | 44.45 MB |
| How time was spent | strategic layer, then best-g kernel | strategic layer, then best-g kernel | strategic layer only; kernel skipped |
| Clock bound the run | yes | yes | no |

v0.109 builds more same-suit material (24 bonds against 16) at a lower corrected cost than v0.108, and it names `S#1` as the campaign on the first decision. It exposes two fewer cards than v0.108 (28 face-down against 26). It still deals every row and still removes nothing. The architectural gain on the cold line is the campaign, not a better end position. The experimental gain is the checkpoint in section 9, where the same controller removes one foundation from a real mid-deal state without being shown the reference suffix.

## 12. Principles

The registry is still 28 ACTIVE and 2 CONDITIONAL. Nothing in v0.109 promotes a row. Principle 11 stays CONDITIONAL: the default play goal still does not call `rank_ready_suits`. Its text now says that `--goal first-foundation` calls `analyze_foundation_campaigns`. The registry test pointer is still `test_longer_run_is_extended_first` in the v0.107 file, so the coverage count cannot absorb the new tests.

Paths that the new tests actually exercise:

| Behaviour | Call | Test |
| --- | --- | --- |
| All four suits and both copies ranked | `rank_foundations` → `analyze_foundation_campaigns` | `test_all_suits_and_both_copies_are_ranked` |
| Available is not the same as accessible or attractive | `FoundationView` tiers | `test_availability_is_not_the_same_as_accessibility` |
| Suit is not hard-coded | same ranking on a transposed deal | `test_priority_is_not_hard_coded_to_one_suit` |
| Physical copies stay distinct | `chosen_source_keys` | `test_duplicate_physical_sources_are_unique` |
| A buried card becomes a prerequisite | `campaign_obligations_for_next_epoch` | `test_buried_card_becomes_a_prerequisite` |
| That prerequisite is played before a deal | `solve` → `propose_foundation_step` | `test_opening_pursues_the_prerequisite_before_dealing` |
| Legal corrected cost | `replay_actions_detailed` | `test_prerequisites_are_legal_corrected_moves` |
| The lock survives several actions | `foundation: continue` | `test_campaign_persists_across_actions` |
| Timeout and three misses do not retire the suit | `propose_foundation_step` with `time_left=0`, then `failures[id]=3` | `test_tactical_timeout_does_not_retire_the_campaign` |
| Stock and removal replan | events after the close solve | `test_stock_deal_replans_the_campaign`, `test_foundation_removal_replans_the_next_suit` |
| A protected run is not split to imitate the reference | `_splits_protected` | `test_protected_run_is_not_split_before_the_deal` |
| Empty columns do not choose the suit | view reasons | `test_empty_columns_do_not_choose_the_suit` |
| A park that is not a same-suit join can be played while face-down falls | opening solve | `test_a_temporary_park_can_advance_a_prerequisite` |
| A later, costlier suit is not the target | schedule objective | `test_an_expensive_late_suit_is_not_the_target` |
| Opening work beats an immediate deal | first decision | `test_foundation_preparation_beats_an_immediate_deal` |
| An intermediate deal is held while the target epoch is not the next row | `propose_foundation_step` loop | `test_shape_policy_delays_an_intermediate_deal` |
| Wasteful extra shaping is not inserted when the completing row is ready | close solve, first id `DEAL:S#1` | `test_wasteful_foundation_preparation_is_rejected` |
| Real checkpoint removes one foundation | `solve` diagnose, prefix 82 | `test_checkpoint_completes_a_real_foundation` |
| Earlier checkpoint still has excavation | diagnose, prefix 31 | `test_earlier_checkpoint_still_has_excavation_work` |
| Cold mode does not read a solution | `parse_moves_file` patched to raise | `test_cold_mode_does_not_read_solution_files` |
| Partial replay is not a solved game; time and memory limits stay distinct | close replay; `time_limit_s=0`; `rss_abort_mb=-1` on `goal=play` | `test_partial_route_replays_and_limits_stay_distinct` |

`assess_deal_timing` and `rank_ready_suits` are still not called from `solve`. Importing them would not be a new active principle.

## 13. Correctness tests

`tests/test_human_strategy_v0_109.py` is 22 tests. The required regression, including that file, v0.108, v0.107, v0.106 counterfactuals, rules, metrics, canonical moves, the 4925153 accounting audit, deal and same-suit legality, state identity, the MobilityWare unrestricted contract, v0.105 forensics, the v0.57 search kernel, and Play Lab, was:

```text
py -3 -m pytest tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py -q --tb=line
```

281 passed in 129.75s. The historical autonomous campaign was not started.

A partial route is labelled `FOUNDATION_REACHED` or `EXHAUSTED` and is not written as a `.moves` solution. `.moves` export remains limited to `SOLVED_VALID`.

## 14. Performance

Opening campaign analysis is cached by `canonical_state_key`. The cold run's 44 unique states and 19.562s are the measured cost of reanalysis plus bounded realisation on this deal, at peak RSS 44.45 MB. The v0.108 cold run's 209.65 MB was dominated by the best-g kernel, which this goal does not start.

Profile code is unchanged: smoke 20s, pilot 600s, extended 3600s, one worker. The benchmark passes `--time-limit 150`. Extended was not launched. Estimates order work. Admissible remaining is still the only prune, and this goal did not apply an incumbent ceiling.

## 15. Known limitations

- Move 0 does not complete a foundation. The cold line deals all five rows and stops with 28 cards face-down.
- The exceptional "tableau cannot reveal" deal fires again whenever reanalysis raises `target_removal_epoch`. That is how all five rows were consumed. A frozen tableau is not evidence that the next row finishes the suit.
- `obligation_is_satisfied` for a shape-receiver is true when the parent rank is usable anywhere, not only on the landing column. The opening queen can be "satisfied" while the jack will not land on it.
- The fast realiser reports `not_found_within_bound` after a few dozen nodes when the legal graph is narrow. That is not a proof. The adapter then deals if no one-ply reveal exists. A two-step unblock that the beam missed is not retried at a higher budget.
- At canonical action 31 the queen is face-up and not legally movable. Three misses suspend that one id. The campaign stays open. The controller does not yet build the unblock (move the diamond off the queen, then move the queen).
- One suit stays locked until the schedule gap in section 4 or a foundation is removed. After removal, the solve stops instead of starting the next suit.
- Source combinations remain capped at 4. A cheaper physical copy outside that cap is invisible.
- `goal=play` is the v0.108 controller. Principle 11 stays CONDITIONAL there.

## 16. Recommended v0.110

Keep the adapter. Change the deal rule that treats a raised target epoch as a reason to take another row. The locked target from the first selection should be the one the completing-row test uses, unless a named card in the next exact row is a missing rank of that same target and the landing column can receive it.

Add one tactical step for a shape receiver that is usable on the wrong column: move it onto the landing column when that move is legal, or excavate the card that blocks that move, before any deal. The close checkpoint must still deal when the king is the incoming card on the protected run. The opening must not deal while the queen the jack needs is about to be buried and a legal save exists.

Do not add another search architecture. Do not promote principle 11 until the default play goal, not only `--goal first-foundation`, changes a decision the v0.107 registry test already names.
