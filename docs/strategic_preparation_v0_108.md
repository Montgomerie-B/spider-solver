# Strategic preparation v0.108

The v0.107 controller could name an objective and play one legal step. On deal 4925153 it then dealt all five stock rows at corrected MW 27, with 36 cards still face-down and no foundation. v0.108 keeps that controller and changes the deal decision: a selected preparation can run for several legal moves, and a deal is compared with preparations that have actually been played on a clone.

No completed solution of deal 4925153 was found. There is no new verified MobilityWare result.

## 1. Root cause of the v0.107 premature deals

The v0.107 cold run is preserved at `artifacts/human_strategy/v0_107/cold_150s.json`. Replaying its 27 actions on `deals/4925153.txt` gives g=27, five deals, 36 face-down, 16 same-suit bonds, 0 foundations, and 6 legal moves. The strategic layer stopped and the best-g kernel then used the rest of the 150 seconds (138845 unique, 87971 expanded, unsolved).

At every stock decision the same ranking produced the deal:

1. Preparation was one ply. A `PREPARE` candidate was a single move, optionally bundled with the immediate deal. After the easy reveals, no legal move reduced `bury_risk` or the face-down count. `bury_risk` only counts an exposed top that can move onto a same-suit home now. Cards still face-down were not treated as access the deal would remove. `incoming_row_damage` counts mixed boundaries and buried useful tops. It does not count a face-down card the deal will cover.

2. Portfolio excavation objectives were generated and then placed behind every concrete move (`floor + 1`). Width 2 never executed them. Their benefit was a capped heuristic, not a state the engine had reached.

3. When no concrete move improved the estimate, `STRETCH:create_workspace` ranked first because its projected cost is the best concrete projection minus 1. The tactical budget (`tactical_max_cost` 3, 400 nodes, 0.35s) did not realise it. The failure was `not_found_within_bound`. The next sibling inside the width was `DEAL_NOW`. A missed workspace search was treated as a reason to deal.

4. Commitment lasted one step. After a partial `PREPARE`, a challenger outside the 0.75 margin replaced the plan. The stretch always sits outside that margin, so an open plan could not survive the next selection.

5. Backtracking restored only the siblings captured inside the current width. An expose objective outside that window was never selected. On the last pre-deal ranking a one-ply park had a positive benefit and still lost, because the width-2 backtrack window contained the deal instead.

`DEAL_NOW` therefore won while its own expected benefit was negative. Non-improving parks had been pushed behind the deal, and the only candidate ahead of it was a stretch the realiser could not finish. The preparations that would have exposed a buried card were generated, ranked outside the window, and never played. They were not proved useless.

## 2. Why the controller stopped with legal moves left

The end of that line is not "no legal moves".

Replaying the 27 actions leaves these six moves: `move 2 1 2`, `move 3 5 2`, `move 3 9 2`, `move 3 10 2`, `move 6 1 2`, `move 10 8 2`. An unblocked ranking of that position still returns candidates, including the stretch, those six moves, and portfolio expose, workspace, and consolidate objectives.

What happened during the run:

- Parks failed their purpose test (the estimate did not fall) and their ids were blocked. The cold artifact records 27 park failures.
- The stretch failed nine times inside the tactical budget. That is "selected but not realisable", which is not a proof that no workspace exists.
- Portfolio expose, create-workspace, and consolidate objectives were selected, missed the tactical budget, and were then suppressed for that state.
- Width had already grown from 2 to 3. The dormant stack was empty. The stop string was "no legal continuation under the current restrictions".

That string described a blocked objective list. The position still had six legal moves. The classification is "objectives suppressed after failure", with "selected but not realisable" as the reason several of those ids were blocked. The kernel clock that followed is a separate condition, "search budget exhausted". The kernel did not solve the game. `TIME_LIMIT` was not reported as `EXHAUSTED`, and it was not reported as a solved deal.

## 3. Architecture changes

The v0.107 loop is intact: one principal line, dormant siblings, widening, admissible pruning separate from heuristic order, and the same CLI flags. `engine.py` and `rules.py` were not modified. The production incumbent, campaign data, and reference solutions were not modified.

New module `src/spider/human_strategy/preparation.py`, called only when the selected candidate is `DEAL_NOW` or `STRETCH` and a stock row remains:

- It synthesises at most two shallow expose objectives, and it may also realise an expose, consolidate, or foundation objective already present in the ranked portfolio.
- `realize_objective` in `FAST_BOUNDED` mode searches a clone. The budget is independent of the tiny unit-test tactical cap: cost 6, at least 600 nodes, and at most 0.8s per objective. At most two realisations.
- Each realised tableau sequence is replayed on the engine. The following deal is also replayed when it is legal. The deal-now alternative is the same engine deal on a clone.
- The comparison score is `3 * face-down exposed + 1.2 * bond change + 8 * foundation change - corrected MW`. It is an ordering heuristic. It is not admissible and it does not prune.
- A preparation is preferred only when it exposes a card, completes a foundation, or builds a same-suit bond, the tableau cost stays within `max(4, 3 * reveals + 2)`, and the attained net beats dealing now. Creating an empty column is not enough.
- When the two nets are within 1.5, a one-ply follow-up on the attained states adds a small tie-break. That is the bounded consequence check. It is not run for ordinary one-ply moves.

Commitment:

- A winning preparation is marked `hold` and keeps its remaining legal actions.
- The next iterations play that plan while `plan_still_worth_following` says the remaining sequence still earns its cost. A stretch or a cheaper-looking deal cannot preempt it.
- The plan is dropped when the remainder is illegal, or when a suffix that is legal on its own is at least as good as the whole plan. One failed step does not mark the strategic objective impossible.
- The first move of an excavation is often a blocker relocation. `_execute` accepts that legal step for a held plan. The old `PREPARE` purpose test (bury risk falls, or the stock shrinks) would have rejected it.

Recovery:

- The line is snapshotted before a deal. If that deal does not expose a card, add a bond, or remove a foundation, and a saved preparation would have exposed a card, the deal is removed from the action list once and the preparation is played. The same pre-deal state is not revisited twice.
- When every preferred id is blocked and legal moves remain, stretch and portfolio misses are released once. Park and tactical failures stay blocked. The event is `retry: a missed realisation is not proof the objective is impossible`.
- If the portfolio still cannot move, the stop reason names the legal-move count. It does not say that no actions exist.
- The leftover-budget kernel, when it runs, orders by face-down count, then bonds, then foundations, then g. Admissible bounds remain the only pruning rule. The lane is ordering only.

Schema is `spider-human-strategy-0.108`. The CLI default output directory is `artifacts/human_strategy/v0_108/` so a later run does not overwrite the v0.107 baseline. Flags are unchanged. `--profile extended` still runs only when named. Cold mode still rejects an incumbent sequence.

## 4. Existing components that were integrated

| Component | What v0.108 does with it | Effect on decisions |
| --- | --- | --- |
| `realize_objective` | Realises the two deal-boundary objectives on a clone. | The cold run selects `PREPARE:expose_*` plans and plays their later steps with `continued: committed plan`. |
| `next_stock_row` | Names the exact incoming card on each column. | Evidence contains `fact: column N incoming … continues …` or a coverage estimate. The wasteful-landing fixture still deals because 6H continues 7H. |
| `generate_objective_portfolio` | Still supplies ranked portfolio targets. Compare may realise an expose, consolidate, or foundation target from that list. | Deep portfolio exposes are still often missed inside the smoke tactical cap. The plans that changed the cold line were the shallow exposes synthesised at the deal boundary. |
| `assess_tableau_move` | Unchanged one-ply park class and rehandling penalty. | A recoverable park is the first step of an expose plan. The lifecycle assessment is not a new deal-timing score. |
| One-ply follow-up | Used only when two deal-boundary nets are within 1.5. | Tie-break inside the comparison. It does not reorder ordinary moves. |
| `assess_deal_timing` | Not called. | It starts an economic-project search. The new comparison already deals and realises through the engine. Calling both on every deal would duplicate that work. |
| `rank_ready_suits` | Not called. | Principle 11 stays conditional. Longest-run ordering is still the only suit signal. |

No column-debt scalar was tuned. There is no blanket penalty on column 4.

## 5. Evidence of multi-step commitment

`test_controller_commits_to_a_multi_action_objective` builds a column whose face-down 5H is reached by moving 2S onto 3D and then 9C onto 10S. The controller's first decision is `selected: measured preparation beats dealing now`. The second decision is `continued: committed plan` on the same objective id. The deal is not played between those two moves. Face-down count falls by 1.

On the cold 150-second line the same reason appears for expose plans on columns 8, 9, 6, and 5. Example: at g=5 the controller selects `PREPARE:expose_c8_d1` (`move 6 4 2`) and at g=6 continues it (`move 8 6 1`).

`test_controller_abandons_a_plan_when_the_benefit_disappears` uses the rule the loop calls before every held step. The two-move expose stays committed. A park followed by a deal does not: the deal is legal without the park, and the combined net is worse, so the reason is `abandoned: committed plan no longer improves on the alternatives`. An illegal remainder produces `abandoned: committed plan is no longer legal`.

## 6. Evidence of preparation-aware dealing

The comparison is on attained states.

- Productive fixture: two moves expose one card. Preparation net beats the deal net (about 0.03 against -0.97 after the small follow-up). The controller exposes the card before it deals.
- Wasteful fixture: 6H continues 7H and nothing is face-down. No preparation is realised. The first action is the deal, and the evidence names 6H.
- Exact alignment: `fact: column 1 incoming 6H continues 7H`.
- Obstruction: on the productive board the evidence says dealing would cover column 1 before its face-down card is exposed, and the choice is prepare.
- Beneficial cover: a king blocks the only face-down card, and 6H continues 7H on another column. The evidence still mentions the covered column. The choice is deal. After the deal the face-down card is still face-down.
- Empty columns: `prefer_preparation` rejects a candidate with no reveal, no bond, and no foundation. The free giveaway of 7H onto an empty column is not taken; the deal is.
- Recoverable park: the first action of the productive plan parks 2S on 3D. From there 2S can still move onto 3C. The next committed action uncovers 5H.
- A second constructed board, with the buried card on column 5 rather than column 1, also exposes that card before dealing (`test_preparation_generalises_beyond_the_benchmark_deal`). The behaviour is not a script for deal 4925153.

A preparation that costs four moves to expose one card loses the strict comparison (net about -1.97 against a deal near -0.97). The controller may still deal, and section 7 is what happens next.

## 7. Evidence of backtracking

`test_premature_deal_can_be_revisited`: the four-move expose is realised and saved, and it does not beat dealing now. The controller deals. The deal adds no face-down exposure, no bond, and no foundation. The event `revisit: dealing did not expose or build; trying the saved preparation` fires, the deal is removed from the action list, and the four expose moves are then played under the committed plan. Corrected cost does not keep the undone deal. Replay of the kept actions matches.

The cold run records that event twice. A deal that does create a bond is kept. The wasteful 6H-onto-7H fixture deals once and does not revisit.

Failed ids do not wipe unrelated moves (`test_failed_objective_does_not_suppress_unrelated_moves`). A realisation that misses cost 1 and succeeds at cost 6 shows that the miss was the budget (`test_failed_realisation_does_not_make_the_objective_impossible`). Park ids are not in the soft-retry set. The cold run emits `retry: a missed realisation is not proof the objective is impossible` once.

The stock-empty six-move position is classified as `objectives suppressed after failure`. A short solve from that position does not stop with "no legal continuation". `classify_stall` returns `no legal moves` only when the legal count is zero.

## 8. Stock-boundary comparison for 4925153

Both lines were replayed from `deals/4925153.txt` with corrected MobilityWare costs. g below includes the deal just played. Bonds are same-suit adjacencies on the tableau. The v0.107 file was not rewritten.

| Boundary | v0.107 g | v0.107 face-down | v0.107 bonds | v0.108 g | v0.108 face-down | v0.108 bonds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SD1 | 9 | 36 | 4 | 8 | 37 | 2 |
| SD2 | 12 | 36 | 6 | 11 | 37 | 4 |
| SD3 | 14 | 36 | 7 | 21 | 33 | 8 |
| SD4 | 15 | 36 | 7 | 42 | 26 | 12 |
| SD5 | 19 | 36 | 11 | 45 | 26 | 13 |
| End | 27 | 36 | 16 | 53 | 26 | 16 |

Foundations are 0 on both lines, at every boundary. Both lines have dealt all five rows by the end. v0.108 has 8 legal moves left; v0.107 has 6.

Reading the table: SD1 and SD2 are not an improvement. v0.108 has one more face-down card and fewer bonds there, because an early expose replaced some of the joins the v0.107 line made. From SD3 onward the new line has exposed more cards. By the end it has uncovered 18 face-down cards (44 to 26) against 8 (44 to 36), at a higher corrected cost (53 against 27), with the same bond count and still no foundation. Delaying the later deals is not itself the result. The result is the cards those extra moves uncovered. The higher g is the cost of that excavation, and it has not yet been paid back in foundations.

## 9. Cold-solve benchmark

Command, matching the v0.107 limits:

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile smoke --time-limit 150 --max-steps 80 --strategic-width 2 --max-width 3 --out artifacts/human_strategy/v0_108/cold_150s.json
```

| | v0.107 | v0.108 |
| --- | --- | --- |
| Status | TIME_LIMIT | TIME_LIMIT |
| Solved | no | no |
| Corrected MW | 27 | 53 |
| Deals | 5 | 5 |
| Face-down at end | 36 | 26 |
| Same-suit bonds | 16 | 16 |
| Foundations | 0 | 0 |
| Legal moves left | 6 | 8 |
| Elapsed | 150.049s | 150.090s |
| Peak RSS | 126.52 MB | 209.65 MB |
| Strategic unique states | 28 | 54 |
| Attempts / achieved / failed / partial | 71 / 17 / 44 / 10 | 109 / 31 / 56 / 20 |
| Backtracks / widens | 43 / 1 | 56 / 1 |
| Kernel | best-g, 138845 unique, 87971 expanded, 146.181s, unsolved | constructive, 190411 unique, 69386 expanded, 143.56s, unsolved |
| First committed objective | PREPARE:move 3 6 1 | PREPARE:move 3 6 1 |
| Replay | ok, MW 27 | ok, MW 53 |
| Cold provenance | prefix not injected | prefix not injected |

Useful preparations on the v0.108 line include the committed exposes in section 5, plus two revisits of deals that had not exposed or built anything. The strategic layer also rejected several preparations whose attained net was worse than dealing (events include prep nets of -4.00, -3.00, -1.77, and -1.97 against deals near -1 or +0.20).

The run did not finish the deal. The constructive fallback did not finish it either. `TIME_LIMIT` here means the clock expired during that fallback after the strategic portfolio had stopped. It is not a claim that the game has no solution.

## 10. Post-SD3 benchmark

Root is the autonomous-185 post-SD3 state: g=74, hash `1afac24bf8c16067d1c86e1e3de3adc92e1085f77cf51121cfc124e41f0610b4`, 9 face-down, 27 bonds, 1 foundation, 20 stock cards. The 185 prefix was replayed only to reach that state. The suffix was not injected. This is not a cold discovery.

v0.107 command was `--time-limit 60 --max-steps 12 --strategic-width 3` and stopped on the step budget in 0.679s (suffix MW 12, g=86, face-down still 9, bonds 36, foundations 1). It dealt, joined, and dealt again. It did not run a multi-step expose.

v0.108 command:

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode diagnose --root post-sd3 --profile smoke --time-limit 90 --max-steps 24 --strategic-width 3 --out artifacts/human_strategy/v0_108/diagnose_post_sd3.json
```

The budgets are not identical. The strategic difference appears inside the first dozen commits, which is the part that can be compared.

At g=74 the comparison found no realised preparation (`prep_net=none`) and the controller dealt. That deal is the same first move as v0.107. Before the next deal, a realised expose on column 2 scored 2.60 against a deal net of 0.20. The controller played `move 2 7 1`, continued the plan, and finished it with `move 2 4 1` before dealing. After that second deal: g=83, face-down 8, bonds 34, foundations 1. v0.107's second deal was at g=79 with face-down still 9 and bonds 31.

End of the v0.108 suffix: g=91, suffix MW 17, face-down 8, bonds 40, foundations 1, stock empty, 9 legal moves, replay ok. Elapsed 90.037s, peak RSS 108.87 MB. The constructive kernel then ran 85.993s (92898 unique, 33772 expanded) and did not solve. v0.107 never started that kernel, because its 12-step budget ended first. The kernel figures are not a like-for-like comparison.

The suffix does not imitate the original 185. Foundations stayed at 1.

## 11. Corrected strategy coverage

The registry is still 28 ACTIVE and 2 CONDITIONAL. The v0.107 fixture tests were re-run and still pass, so the fixture-level ACTIVE rows still change a decision on those boards. Two rows stay conditional:

- Principle 11. Longest-run ordering is real. `rank_ready_suits` is not called, so a suit is not judged removable from the whole deal.
- Principle 29. Failed ids are still blocked on the next decision at that state. A missed stretch or portfolio realisation may be retried once when nothing else is left. Completed-route forensics and the v0.105 attribution are not loaded. Cold mode does not read the 172 or the 185.

What changed in the real-deal path, as opposed to the fixtures:

- Stock timing (principles 24–26) now compares attained preparations with the deal. On v0.107 those principles fired for one-ply bury-risk fixtures and did not fire as multi-step excavation on 4925153.
- Objective commitment now spans the legal steps of a held plan. v0.107 reassessed after every single move.
- A deal that exposes nothing can be reopened once (principle 28's dormant line, plus the explicit revisit).
- Learning from a failed realisation (principle 29) now includes one soft retry. That retry is not learning from a finished route.

`assess_deal_timing` and `rank_ready_suits` remain unwired. Importing them would not have been coverage.

## 12. Tests

`tests/test_human_strategy_v0_108.py`: 18 passed in 0.69s.

| Requirement | Test |
| --- | --- |
| Multi-action commitment | `test_controller_commits_to_a_multi_action_objective` |
| Abandon when the benefit disappears | `test_controller_abandons_a_plan_when_the_benefit_disappears` |
| Productive preparation beats the deal | `test_productive_preparation_beats_an_immediate_deal` |
| Wasteful preparation loses | `test_wasteful_preparation_loses_to_an_immediate_deal` |
| Exact incoming alignment | `test_exact_incoming_column_alignment_is_named` |
| Deal would obstruct needed material | `test_dealing_that_covers_a_needed_card_is_visible` |
| Beneficial deal may cover material | `test_a_beneficial_deal_may_cover_material` |
| Empty columns are not rewarded alone | `test_empty_columns_are_not_rewarded_on_their_own` |
| Recoverable temporary park | `test_recoverable_temporary_park_is_used_to_expose` |
| A failed objective leaves other moves | `test_failed_objective_does_not_suppress_unrelated_moves` |
| A missed realisation is not impossibility | `test_failed_realisation_does_not_make_the_objective_impossible` |
| Revisit a premature deal | `test_premature_deal_can_be_revisited` |
| Six legal moves are not "no actions" | `test_stock_empty_position_with_legal_moves_is_not_no_actions` |
| Moves stay legal, costs stay corrected MW | `test_played_moves_stay_legal_and_use_corrected_costs` |
| A finished route is replay-verified | `test_a_finished_route_is_replay_verified` |
| Cold mode does not load the 172 or 185 | `test_cold_mode_does_not_load_reference_routes` |
| Time and memory limits stay distinct | `test_time_and_memory_limits_remain_distinct` |
| Behaviour is not specific to 4925153 | `test_preparation_generalises_beyond_the_benchmark_deal` |

`tests/test_human_strategy_v0_107.py`: 33 passed in 0.70s.

The previous regression set, 208 tests, passed again. Combined with both contract files: 259 passed in 111.36s.

```text
py -3 -m pytest tests/test_human_strategy_v0_107.py tests/test_human_strategy_v0_108.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py -q
```

## 13. Performance and memory

The cold strategic layer took about 6.5 seconds (150.090 minus the 143.56 second kernel) against about 3.9 seconds for v0.107. The extra time is the deal-boundary realisation, cached per state. Peak RSS rose from 126.52 MB to 209.65 MB. Both are under the smoke ceiling of 1024 MB. The constructive kernel stored more unique states (190411 against 138845) and expanded fewer (69386 against 87971). It still stopped on the clock, unsolved.

The post-SD3 run peaked at 108.87 MB inside a 90 second cap. Unit tests still stop on `TIME_LIMIT` at a zero time budget and on `MEMORY_LIMIT` at a negative RSS ceiling, with no solved claim.

No campaign was launched. `--profile extended` was not run.

## 14. Verified completed solutions

Deal 4925153 was not solved from move 0, and it was not solved from post-SD3. No new MobilityWare score is claimed.

The existing one-foundation fixture still finishes at corrected MW 1, status `SOLVED_VALID`, with an independent replay of one move and eight foundations. That fixture is not deal 4925153. Cold mode refuses an incumbent sequence on that fixture, and the production incumbent file was not written.

Every reported action list above replayed on the engine. The cold artifact's replay field is `ok` with mobilityware_moves 53. The post-SD3 replay field is `ok` with mobilityware_moves 17.

## 15. Known limitations

- The cold line still deals all five rows and still removes no foundation. Twenty-six face-down cards remain. That is better access than 36, and it is not a credible finished route.
- SD1 and SD2 give up bonds relative to v0.107. The first measured expose is not free.
- The comparison realises at most two objectives, and only when a deal or a workspace stretch has already won the one-ply ranking. A good excavation that the one-ply scorer plays by itself never goes through this hook, which is intentional. An excavation the realiser misses inside cost 6 is invisible to the comparison.
- A deal that creates a bond is not revisited, even if a larger excavation existed.
- The soft retry happens once, and only when the ranked list is empty. It does not reopen park failures.
- `assess_deal_timing` and `rank_ready_suits` are still off the decision path.
- The constructive fallback spends the remaining clock without a foundation target. On this deal that search did not solve, and it was the memory cost.
- Heuristic nets order candidates. Only the existing admissible remainder prunes, and only against an incumbent ceiling. Cold mode has no ceiling.

## 16. Recommended v0.109 development

Turn the cards v0.108 exposes into a foundation. The cold endgame has 26 face-down cards, 16 bonds, and no completed suit. The next controller should choose which exposed material is worth building, using suit removability at a real foundation decision (`rank_ready_suits` or the existing foundation-feasibility check), not another generic search.

Look at SD1 specifically. The v0.107 line reached that boundary with 4 bonds and 36 face-down; v0.108 reached it with 2 bonds and 37 face-down. If the early expose is displacing same-suit joins that were available at the same cost, the comparison should see those joins as a rival preparation, not only as one-ply noise.

Keep `assess_deal_timing` off the inner ply. If it is tried, call it once per deal, with a tight budget, and only as a check on the attained comparison.

Do not spend a 140-second fallback on a stock-empty position that has no foundation objective. Either give that fallback a foundation or access target, or stop when the strategic layer has no such target and report the planning failure directly.

## 17. Git status and reproduction

Branch `local/strategic-preparation-v0-108`. HEAD `fa7cf4651a2d04427bdcbfc0b4824b6767ed6edc`, subject "Add controlled counterfactual continuation experiments v0.106". Untracked on that branch:

- `docs/human_strategy_integration_v0_107.md`
- `docs/strategic_preparation_v0_108.md`
- `src/spider/human_strategy/`
- `tests/test_human_strategy_v0_107.py`
- `tests/test_human_strategy_v0_108.py`
- `tools/human_strategy_solver.py`

Nothing was committed, pushed, merged, or opened as a pull request. `engine.py`, `rules.py`, reference solutions, production campaign data, and the incumbent registry were not modified.

```text
git status -sb
git rev-parse HEAD
py -3 -m pytest tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py -q
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile smoke --time-limit 150 --max-steps 80 --strategic-width 2 --max-width 3 --out artifacts/human_strategy/v0_108/cold_150s.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode diagnose --root post-sd3 --profile smoke --time-limit 90 --max-steps 24 --strategic-width 3 --out artifacts/human_strategy/v0_108/diagnose_post_sd3.json
```

The v0.107 baseline used for section 8 is `artifacts/human_strategy/v0_107/cold_150s.json`. Leave that file in place.
