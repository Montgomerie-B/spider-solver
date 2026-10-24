# Integrated human-strategy controller v0.107

Deal 4925153 is the measured full deal. The human 172 and the autonomous 185 are reference costs only. Cold mode does not read their actions. A diagnostic post-SD3 root replays the 185 only to reach that state, and that replay is not a new discovery.

Branch `local/integrated-human-strategy-v0-107`. The branch starts at `fa7cf4651a2d04427bdcbfc0b4824b6767ed6edc`. This work is uncommitted.

Estimates below are estimates. A legal move is not a completed objective. TIME_LIMIT is not EXHAUSTED. A lower corrected cost with cards still buried is not a cheaper solution. A cleaner column is not a cheaper solution. No complete route was produced for deal 4925153.

## 1. Architecture

The controller is one loop in `src/spider/human_strategy/controller.py`:

Understand the position, score a small set of objectives, play one legal step, then reassess. Sibling objectives stay dormant. A failed objective is not replayed on that same state. Width grows only after the dormant siblings of a failure are gone. An open plan is held when a challenger does not improve the estimate, or when its projected gain is inside a margin of 0.75.

Five pieces do that work.

| Piece | Module | Role |
|---|---|---|
| Strategic context | `context.py` | Known cards, accessible cards, next stock row, bury risk, admissible remainder, estimate |
| Objective portfolio | `portfolio.py` | One candidate per legal action, plus one workspace stretch when nothing improves, plus existing portfolio targets ranked behind concrete moves |
| Tactical execution | `controller._execute` | One legal action, or `realize_objective` for a predicate target |
| Evaluation | `evaluation.py` | Admissible remainder for pruning. Heuristic remainder for ordering. The two are not mixed |
| Principal line | `controller.solve` | Commitment, backtrack, widening, transposition by exact state and g, optional best-g fallback |

`admissible_remaining` is `compute_solution_lower_bound`, plus `stock_empty_assembly_h` only after the stock is empty. It can prune. `estimate_remaining` adds face-down count, mixed boundaries, bury risk, buried useful cards, a tableau-assembly preview, and the estimated debt of the next stock row. Those additions order candidates. They are not proof bounds. `goodness_score` breaks ties after projected cost and after a solved terminal. It is not subtracted from the estimate.

A candidate kind is the purpose, not the fact that the move was legal. `DEAL_NOW` must shrink the stock. `PREPARE` must cut bury risk or then deal. `REVEAL` must flip a card. `SAME_SUIT` must add a bond. `FOUNDATION` must remove a sequence. `PARK` must lower the estimate. A park with a bounded exit and no better estimate fails. `TACTICAL` stays partial. A stretch that the realiser cannot finish is `not_found_within_bound`, which is not a proof that no workspace exists.

When the portfolio has blocked every retained candidate and legal moves remain, the leftover time goes to `search_kernel.run_search` as one best-g continuation from that state. The kernel does not see a known solution. Its ceiling, when an incumbent was supplied, is `incumbent_mw - 1`. A terminal still has to survive independent replay from the original root. This fallback is not a campaign, and it does not write the production incumbent.

## 2. The 30 principles

The catalogue is `src/spider/human_strategy/registry.py`. A row is ACTIVE when a test shows the principle changing a controller decision. CONDITIONAL means the tested behaviour is real and a named part of the principle is not on the decision path.

`operational_viability.rank_ready_suits` is not called. `planner.deal_timing.assess_deal_timing` is not called. v0.105 forensic attribution is not recomputed per move. Those gaps are why principles 11 and 29 are CONDITIONAL. The other 28 rows are ACTIVE on the fixtures named in the matrix. That does not mean the full deal is solved.

## 3. Existing modules reused

Used on the decision path, without copying their implementations:

- `planner.stock_reception.next_stock_row` — the exact next ten cards, column order
- `planner.lower_bounds.compute_solution_lower_bound` and `compute_objective_lower_bound`
- `assembly_lower_bound.stock_empty_assembly_h` — admissible only with an empty stock; a preview is used while stock remains
- `planner.objective_realizer.realize_objective` in `FAST_BOUNDED` mode
- `planner.strategic_objectives.generate_objective_portfolio` — targets sit behind concrete moves
- `move_lifecycle.assess_tableau_move` — ordering only; its rehandling cost is not a bound
- `planner.space_lifecycle.empty_count`
- `search_kernel.run_search` and `reconstruct_path` — leftover-budget fallback only
- `metrics.replay_actions_detailed`, `format_action`, `parse_moves_file`, `export_actions_to_moves_file`
- `research_actions` for legal application, corrected step cost, and the opening
- `state_identity.canonical_state_key` and `packed_state.pack_state`
- `counterfactual.experiment.reconstruct_roots` — diagnose mode, post-SD3 only

Inspected and not called from this controller: `assess_deal_timing`, `rank_ready_suits`, `consequence_search`, `plan_search_v2`, `dependency`, `workspace_tactics`, `foundation_feasibility`, `whole_game_epoch_scheduler`, and the forensics package. `engine.py` and `rules.py` are unchanged. MobilityWare scoring and deal legality are unchanged.

## 4. New components

| Path | What it adds |
|---|---|
| `src/spider/human_strategy/controller.py` | Principal loop, purpose test, backtrack, widening, replay, kernel fallback |
| `src/spider/human_strategy/portfolio.py` | Candidate scoring, deal-versus-shuffle ordering, stretch, commitment |
| `src/spider/human_strategy/evaluation.py` | Admissible bound, heuristic estimate, one-ply cost-led action |
| `src/spider/human_strategy/context.py` | Known versus accessible cards, prerequisite notes |
| `src/spider/human_strategy/profiles.py` | `smoke`, `pilot`, `extended`. Extended runs only when named. Workers stay at 1 |
| `src/spider/human_strategy/registry.py` | The 30-row catalogue |
| `tools/human_strategy_solver.py` | CLI |
| `tests/test_human_strategy_v0_107.py` | Contract tests |

Research JSON is written under `artifacts/human_strategy/v0_107/`. That tree is gitignored. Nothing is written to `solutions/` or the production incumbent.

## 5. Decision pipeline

At each step the controller builds a context, scores every legal action, and keeps the best `strategic_width` candidates. The rank key is `(projected, unsolved first, lower attractiveness, structural risk, id)`.

`projected` is current g, plus the exact corrected cost of the action, plus `estimate_remaining` of the resulting position, plus ordering penalties. Penalties include dealing while a same-suit home is still open, destroying a same-suit landing, splitting a run, a useless king relocate, and an unexited rehandle. A deal is not penalised for consuming the landing it uses. A park, tactical step, or workspace move with no positive expected benefit is placed behind `DEAL_NOW`. That stops a zero-benefit shuffle from delaying a deal that the row will require anyway.

`expected_benefit` is the change in the estimate plus the change in the tie-break score. It decides commitment and the stretch gate. It is not an admissible quantity.

Portfolio objectives from the existing generator are placed strictly behind every concrete move. One `STRETCH:create_workspace` candidate is added when no concrete move improves the estimate and no column is empty. Its projected cost is optimistic (`best concrete - 1`) and its evidence says so. Failure does not prove that workspace is impossible.

## 6. Principal line

The chosen objective is executed. On success its siblings from before that step are dropped, so an older snapshot cannot erase a committed move. On failure the best remaining sibling is tried next. The stack is stored worst-first so the pop is the best sibling, not the weakest. Width increases by one, up to `max_width`, only when no sibling remains. A repeated state at an equal or higher g is a cycle and the objective fails. A more expensive ancestry of a known state is discarded.

The controller does not yet reopen an early committed deal in order to try a different ancestry. Dormant alternatives are siblings of a failed step. That is narrower than a beam over the first stock-deal decision.

## 7. Deal timing

`DEAL_NOW` is an objective. Before a deal the controller can see the next row, same-suit landings, and cards that still have a same-suit home. Preparation wins on the fixture where moving 6H onto 7H preserves a bond the deal would bury. The one-ply cost-led action there is `deal`, including when a free relocate exists. Immediate dealing wins on the fixture where the preparation does not improve the estimate, and on the fixture where a free move would give away the 6H landing. A zero-cost whole-column transfer is played when it improves a landing, and its recorded cost is 0. Unrestricted Deal stays legal with an empty column.

On deal 4925153 the same rule prepares and reveals before the first deal, then deals the remaining rows quickly. See Benchmark B. The fixture result and the full-deal result are both reported. The fixture does not prove the full deal was timed well.

## 8. Deferred cost

v0.105 is the reason the estimate exists. At post-SD5 the autonomous line was 16 corrected moves ahead of the human line and much less built. This controller therefore does not rank by immediate g alone.

What the estimate actually did on the full deal is in Benchmark B: stock empty at corrected cost 27, 16 same-suit bonds, 36 face-down cards, 0 foundations. Legal moves remained. A cost of 27 to empty the stock is not progress toward the 172 or the 185. The bury-risk term catches a visible same-suit home. It does not price the face-down cards a deal will cover when no same-suit home is visible. That is the main gap in the deferred-cost model.

Rehandling from `assess_tableau_move` can change order. `test_rehandling_does_not_become_an_admissible_bound` shows a tidier column and a messier column have the same admissible remainder and the same incumbent prune.

## 9. Strategy coverage matrix

| ID | Implementation | Runtime trigger | Actual decision effect | Test evidence | Status |
|---|---|---|---|---|---|
| 1 | Rank by projected completion cost. A solved terminal beats a cheaper-looking unfinished move | Every selection | A cost-1 foundation completion beats a zero-cost relocate | `test_completion_cost_beats_a_free_relocate` | ACTIVE |
| 2 | Context stores face-down cards and the exact next stock row. Known is not accessible | `build_context` before each decision | Deal and preparation evidence cite the incoming card. A hidden duplicate is not movable | `test_known_hidden_card_is_not_accessible` | ACTIVE |
| 3 | A note names a face-down card that is the next rank of an accessible card | That card is the immediate face-down card of its column | The reveal of that card is preferred to an unrelated join | `test_backward_prerequisite_is_exposed_first` | ACTIVE |
| 4 | Every decision has an id, a purpose, and a success test | `select_candidate` and `_purpose_met` | A legal move that misses its purpose fails and does not change the state | `test_legal_move_that_misses_its_purpose_is_not_success` | ACTIVE |
| 5 | `strategic_width` limits the considered list. Smoke default is 2 | Each decision | Moves outside the width are not executed on that step | `test_width_limits_the_considered_set` | ACTIVE |
| 6 | Best objective first. Width grows only after a failure with no dormant sibling | Failure of the principal objective | The second objective runs after the first fails. Width starts at the configured value | `test_failed_objective_backtracks_then_widens` | ACTIVE |
| 7 | A mixed peel that reveals can outrank a cosmetic join | The peel flips a face-down card and the join does not | The disorderly reveal is selected | `test_revealing_mixed_move_beats_a_cosmetic_join` | ACTIVE |
| 8 | A foundation removal or a stock deal rebuilds the context | Foundation count increases, or the stock shrinks | The next decision is scored on the new state. The trace records `replan:` | `test_foundation_removal_replans` | ACTIVE |
| 9 | A same-suit join lowers the ordering estimate. A dead mixed park does not | Both destinations are legal | The same-suit join is selected | `test_same_suit_join_beats_a_dead_park` | ACTIVE |
| 10 | Splitting a same-suit run adds an ordering penalty unless the move reveals | The moved suffix is attached to a same-suit parent | A non-splitting join is selected and the run stays length 3 | `test_controller_does_not_split_a_built_run` | ACTIVE |
| 11 | Longest same-suit run is an ordering signal. `rank_ready_suits` is not called | Two same-suit joins | The longer run is extended. No decision uses a whole-deal removability ranking | `test_longer_run_is_extended_first` | CONDITIONAL |
| 12 | A move that completes K-to-A is kind `FOUNDATION` | The sequence is one legal move from completion | The foundation move is taken now | `test_completion_cost_beats_a_free_relocate` | ACTIVE |
| 13 | `CardFact.accessible` is true only for the trailing movable same-suit suffix | `build_context` | A face-down duplicate of a visible card is known and not accessible | `test_duplicate_physical_cards_stay_distinct` | ACTIVE |
| 14 | Same split penalty as principle 10 | A move would detach the end of a partial run | The partial run remains intact when another join exists | `test_controller_does_not_split_a_built_run` | ACTIVE |
| 15 | Foundation increase appends `replan: foundation removed` | Cards remain after the removal | The following decision is computed from the post-removal state | `test_foundation_removal_replans` | ACTIVE |
| 16 | A king relocate is penalised only when it reveals nothing and fixes no landing | The moved run is headed by a king and an empty column exists | A useless king move loses to a same-suit join. A revealing king move is taken | `test_king_move_depends_on_what_it_frees` | ACTIVE |
| 17 | An empty column is spent when the move reveals a card | A cover can move onto an empty column and flip a card | The empty column is used for the reveal | `test_empty_column_is_spent_to_reveal` | ACTIVE |
| 18 | `assess_tableau_move` supplies `exit_route_bounded`. Dead parks take a rehandling penalty | A tableau move is scored | A park with no bounded exit ranks behind a same-suit join | `test_same_suit_join_beats_a_dead_park` | ACTIVE |
| 19 | The chosen reveal records its exact corrected cost. A one-ply reveal beats an unsatisfied stretch | A one-ply reveal exists | The one-move reveal is the action executed | `test_empty_column_is_spent_to_reveal` | ACTIVE |
| 20 | Unexited rehandling is added to the ordering key only | `assess_tableau_move` reports no bounded exit | Mixed boundaries do not change `admissible_remaining` or the incumbent prune | `test_rehandling_does_not_become_an_admissible_bound` | ACTIVE |
| 21 | A park is achieved only when the estimate falls. A zero-benefit shuffle ranks behind `DEAL_NOW` | A bounded mixed park and a legal deal both exist | The deal is played. The park is not a successful objective | `test_same_suit_join_beats_a_dead_park`, `test_zero_benefit_shuffle_does_not_delay_the_deal` | ACTIVE |
| 22 | Corrected MobilityWare cost. A free transfer that improves a landing is `ZERO_COST` | Entire column, no face-down left, destination empty | The free transfer is played and its recorded cost is 0. Deal stays legal | `test_zero_cost_transfer_is_taken_when_it_improves_the_landing` | ACTIVE |
| 23 | A revealing mixed peel is `REVEAL`. A mixed park that does not help is penalised | Separate fixtures | The revealing disorderly move is chosen. The dead park is not | `test_revealing_mixed_move_beats_a_cosmetic_join` | ACTIVE |
| 24 | `DEAL_NOW` competes with preparation. Ranking uses the after-state estimate. One-ply cost-led ties prefer Deal | A stock row remains and both actions are legal | Preparation wins when it saves a bury. Deal wins when preparation is wasted | `test_costly_preparation_beats_immediate_deal`, `test_immediate_deal_beats_wasteful_preparation` | ACTIVE |
| 25 | `next_stock_row` names the ten cards. Evidence names a same-suit landing | Stock length is at least 10 | The trace cites the incoming card that the choice is about | `test_costly_preparation_beats_immediate_deal`, `test_immediate_deal_beats_wasteful_preparation` | ACTIVE |
| 26 | A bury-reducing move is bundled with the following deal and played first | `bury_risk` of the current position is positive | The saving move is first. The deal is held as the rest of that objective when no better reveal appears | `test_costly_preparation_beats_immediate_deal` | ACTIVE |
| 27 | An incoming same-suit landing lowers the deal's ordering cost. Giving that landing away is penalised | The next card continues the top in suit | Deal is selected. A free giveaway of the landing is not | `test_immediate_deal_beats_wasteful_preparation`, `test_immediate_deal_beats_a_free_giveaway_of_the_landing` | ACTIVE |
| 28 | Dormant siblings and a cheaper-g transposition | Objective failure, or a repeat at a worse g | The next sibling is played after a failure. A no-better repeat is rejected | `test_failed_objective_backtracks_then_widens`, `test_cycle_guard_rejects_a_repeat_at_no_better_cost` | ACTIVE |
| 29 | Failed ids are dropped for that exact state. Completed-route forensics are not loaded | An objective returns failed | That id is absent from the next portfolio on that state. The 172 and the 185 do not change the ranking | `test_failed_objective_is_not_retried_on_the_same_state` | CONDITIONAL |
| 30 | Warm mode prunes when g plus the admissible remainder cannot beat the ceiling. Cold mode rejects an incumbent sequence. Width grows after the line is exhausted | `optimise` mode, or a failed line with room to widen | Ceiling 0 plays nothing. Cold mode raises if a sequence is supplied. The production incumbent is not written | `test_warm_ceiling_prunes_and_cold_mode_refuses_injection` | ACTIVE |

## 10. Test evidence

`py -3 -m pytest tests/test_human_strategy_v0_107.py -q --tb=line`

33 passed in 0.73s after the kernel-fallback guard. The suite covers MobilityWare step cost, zero-cost transfers, unrestricted dealing, duplicate physical cards, known-versus-hidden access, objective generation and preconditions, tactical success and honest failure, commitment, dormant alternatives, widening, transposition, context-sensitive cache, deal versus preparation both ways, useful disorder, dead parks, recoverable reveals, suit-run priority, foundation replan, backward prerequisites, time and memory limits, cold-mode refusal of an injected sequence, and warm-mode provenance.

Existing regressions, not including any autonomous campaign:

`py -3 -m pytest tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py -q --tb=line`

208 passed in 115.85s.

Two preparation fixtures, both replayed:

- Costly preparation wins. Columns 6H and 7H, incoming 9C on the 6H column. Cost-led action is `deal`. The controller plays `move 1 2 1` then `deal`. Corrected cost 2. The heart bond survives. The same preparation is chosen when empty columns make a free dodge the cost-led action.
- Wasteful preparation loses. Incoming 6H lands on 7H. A mixed 4C-onto-5S shuffle does not win. The controller deals, and the evidence names 6H. A free giveaway of that landing also loses to the deal.

`test_zero_benefit_shuffle_does_not_delay_the_deal` is the post-SD3 pattern on a constructed board: a workspace stretch may be attempted, it fails without a move, and the first committed action is `deal`.

## 11. Benchmark results

Profiles: smoke is 20s, width 2, max width 3, 8 steps, tactical budget 400 nodes and 0.35s. The 150s run keeps that tactical budget and raises the clock to 150s and the step cap to 80. Extended was not launched. Pilot's 600s command was not left running. One short optimise invocation used the smoke step cap so the ceiling path could be checked. Workers used: 1. RSS abort: 1024 MB. Peak RSS on these runs stayed under 30 MB before the fallback.

One-ply cost-led means minimum immediate corrected cost, with Deal winning ties. It is the v0.106 preference in miniature. It is not a full search.

### Benchmark A — fixtures

The 33 contract tests are the deterministic fixtures. They cover preparation, dealing, reveals, joins, kings, empty columns, foundations, backtracking, and a one-move solved game.

The solved fixture is seven foundations already removed, QH-to-AH in column 1 and KH in column 2, stock empty. The controller plays `move 1 2 12`, status `SOLVED_VALID`, corrected MW 1, `replay.ok` true, `new_discovery` true, prefix not injected. The cost-led action is a free relocate of the whole run. No `.moves` file is written for that unit fixture. The CLI writes a `.moves` file only when a run returns `SOLVED_VALID`.

### Benchmark B — deal 4925153 from move 0

Cold. No solution file was read. Independent replay of the strategic actions matched the reported corrected cost. The game was not solved.

Smoke, default 8 steps, clock 20s:

| Item | Value |
|---|---|
| Status | `STEP_LIMIT` |
| Runtime | 0.135s |
| Peak RSS | 26.05 MB |
| Unique states | 9 |
| Attempted / achieved / failed / partial | 9 / 6 / 1 / 2 |
| Backtracks / widens | 1 / 0 |
| Deals / foundations / stock rows left | 0 / 0 / 5 |
| Corrected g | 8 |
| First objective | `PREPARE:move 3 6 1` |
| One-ply cost-led | `deal` |
| Replay | ok, MW 8, 4 bonds, 36 face-down, 5 legal moves left |

The first committed move differs from the cost-led deal. The line is preparation and reveals. It is not a solution.

Cold, `--time-limit 150 --max-steps 80`. The strategic portfolio stopped on its own, with legal moves left. The leftover budget went to one best-g kernel from that position (`max_unique` 400000, no depth cap, admissible remainder as the lower bound, stop on the first terminal). The kernel used the clock. It did not find a terminal. TIME_LIMIT here is the fallback clock. It is not EXHAUSTED, and it is not a solved game.

| Item | Value |
|---|---|
| Overall status | `TIME_LIMIT` |
| Runtime / peak RSS | 150.049s / 126.52 MB |
| Strategic stop, then fallback | portfolio exhausted at 2.4s and g=27; kernel then `time limit` |
| Kernel unique / expanded / solved / kernel seconds | 138845 / 87971 / false / 146.181 |
| Unique strategic states | 28 |
| Attempted / achieved / failed / partial | 71 / 17 / 44 / 10 |
| Backtracks / widens | 43 / 1 |
| Deals | 5, so the stock was empty |
| Foundations | 0 |
| Corrected g | 27 |
| Bonds / face-down / legal moves left | 16 / 36 / 6 |
| First objective | `PREPARE:move 3 6 1`, then reveals, first deal at g=8 |
| Replay of the 27-move prefix | ok, not solved |

Five deals by corrected cost 27, with 36 cards still face-down and no foundation removed, is the deferred-cost failure on the real deal. The controller did not imitate a 49-move preparation, and it also did not keep preparing once its estimate preferred the deal. The 172 and the 185 are not beaten by this prefix. There is no verified complete MW score.

### Benchmark C — post-SD3 of the autonomous 185

Command: `--mode diagnose --root post-sd3 --time-limit 60 --max-steps 12 --strategic-width 3`. The 185 prefix was replayed only to reach the root. Provenance records that. `new_discovery` is false. `prefix_injected` is false.

Root hash `1afac24bf8c16067d1c86e1e3de3adc92e1085f77cf51121cfc124e41f0610b4`, g=74, two stock rows, one foundation. One-ply cost-led action: `deal`.

First decision, estimates labelled as estimates in the trace:

- Considered `STRETCH:create_workspace`, `DEAL_NOW:deal`, `TACTICAL:move 3 4 1`.
- Chose the stretch because no concrete move improved the estimate. The stretch evidence says the workspace value is optimistic and is not an admissible bound.
- The realiser returned `not_found_within_bound`. No move was played.
- Backtrack then played `DEAL_NOW`.

So the first *objective* differs from best-g, and the first *move* is the same deal best-g would play. Zero-benefit parks were ranked behind the deal and were not the committed alternative. After that deal the controller prepared (`PREPARE:move 9 3 1`) and made same-suit joins. Across 12 committed moves: status `STEP_LIMIT`, runtime 0.679s, peak RSS 28.79 MB, 13 unique states, 23 attempts, 9 achieved, 11 failed, 3 partial, 11 backtracks, 2 deals, foundations still 1, stock empty, suffix MW 12, replay ok. End of the suffix: 36 bonds, 9 face-down, 12 legal moves, not solved.

This is not evidence that delaying the deal would have been cheaper. It is evidence that the controller now names the deal, a workspace attempt, and a tactical alternative, and that it refuses a zero-benefit park as the reason to wait.

### Benchmark D — another position

No second deal file is in the repository. The independent positions are the constructed fixtures in the contract tests: the preparation board, the waste board, the foundation micro-solve, the reveal board, and the zero-benefit shuffle board. None of them encodes a 4925153 move sequence. The micro-solve is the verified complete route from Benchmark A.

### Comparison with one-ply cost-led search

| Root | Cost-led first action | Controller first committed objective | First played action |
|---|---|---|---|
| Opening | `deal` | `PREPARE:move 3 6 1` | `move 3 6 1` |
| Post-SD3 | `deal` | `STRETCH:create_workspace` (failed, no move) | `deal` |
| Waste fixture | a tableau shuffle or a free giveaway | `DEAL_NOW` | `deal` |
| Preparation fixture | `deal`, or a free dodge if empties exist | `PREPARE:move 1 2 1` | that prepare, then `deal` |

A richer first objective is not a better solved cost. On the full deal the controller's own line reached stock-empty at g=27 and stopped making strategic progress.

The existing best-g kernel, started from the same opening with `pack_state` identity, the admissible remainder, a 20s clock, and a 1024 MB ceiling, also found no terminal: 29077 unique states, 12842 expanded, max g 10, peak RSS 42.72 MB, stop `time limit`. Its budget is shorter than the 146s fallback, and its root is the opening rather than the g=27 prefix. Both runs are unsolved. The kernel's low max g is the best-g preference for cheap moves, which on this deal means dealing. The controller's first committed move is the preparation instead.

### Optimise provenance

`--mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile smoke --time-limit 15 --max-steps 4`

The 185 was replayed to obtain ceiling 185. The sequence was not injected. Status `STEP_LIMIT`, g=4, not solved, `new_discovery` false, `reproduced_incumbent` false, peak RSS 25.77 MB, runtime 0.068s. The production incumbent was not written. The 600s pilot optimise command was not run.

## 12. Known limitations

- Deal 4925153 was not solved. There is no new verified MW score.
- The full-deal line empties the stock at g=27 with 36 face-down cards and 0 foundations. The estimate prefers that to more preparation. v0.105 says a cost lead of that kind can be deferred work. This release did not correct it on the real deal.
- After the stock is empty the one-ply portfolio blocks itself: failed parks and a failed workspace stretch fill the blocked-id set, while legal moves remain. The best-g fallback then searched 138845 states in the leftover 146s and did not solve. That search started from the g=27 prefix, which still had 36 face-down cards.
- Early committed moves are not reopened. Width 2 then 3 is not a search of alternative early ancestries.
- `assess_deal_timing` and `rank_ready_suits` are unwired. Principle 11 does not decide that a suit is removable.
- Principle 29 remembers failures inside the run. It does not learn from the 172, the 185, or v0.105 attribution.
- The optimistic workspace stretch is retried on later states. On the 150s prefix it was chosen 9 times and did not create the missing endgame.
- `generate_objective_portfolio` exceptions become a filtered note. A portfolio failure does not change the concrete ranking.

## 13. Remaining unintegrated principles

Principle 11, suit removability beyond "extend the longer run". Principle 29, learning from completed routes and backward attribution. Both are CONDITIONAL.

Also unintegrated as machinery, even where a related principle is ACTIVE: deal-timing assessment, foundation feasibility, dependency hierarchies deeper than the immediate face-down card, consequence search, and plan search v2. Their absence is deliberate. They were not required to make the loop play, and calling the heavy deal-timing assessor on every ply would break the smoke budget.

## 14. Recommended v0.108 work

Price the face-down cards an immediate deal will bury, not only the visible same-suit homes. The g=27 prefix is the regression fixture for that change: a policy that still empties the stock with about 36 face-down cards and no foundation has not learned the v0.105 lesson.

Cache a failed workspace stretch per state so it is not the first action after every quiet position. When the portfolio dies in a stock-empty endgame, start the kernel from a state the strategic layer still believes is prepared, or do not deal the last rows until a foundation plan exists.

Wire `rank_ready_suits` at foundation choice points only. Keep `assess_deal_timing` off the inner ply. If it is used, call it once per deal decision.

## 15. CLI and output

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile smoke
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode diagnose --root post-sd3 --profile smoke --time-limit 60
```

`--profile extended` runs only when named. `--root post-sd3` requires `--mode diagnose`. Cold mode rejects `--incumbent`. Optimise mode requires `--incumbent` and uses it as a ceiling, not as a prefix. `--workers` is clamped to 1.

Other flags: `--time-limit`, `--memory-mb`, `--strategic-width`, `--max-width`, `--tactical-nodes`, `--tactical-seconds`, `--tactical-cost`, `--max-steps`, `--out`, `--no-portfolio`, `--baseline`.

Default output is `artifacts/human_strategy/v0_107/{mode}_{profile}.json`. The document has `schema` `spider-human-strategy-0.107`, `estimates_are_estimates`, a one-ply comparison, the result, and the coverage matrix. Each decision records state id, g, stock rows, foundations, the considered ids, the chosen objective, the reason, expected benefit, projected cost, structural risk, evidence, the moves actually applied, the status, and the cost-led action. A `.moves` file is written beside the JSON only for `SOLVED_VALID`, using the authoritative `move` / `deal` syntax. Exit code 0 unless the status is `INVALID` (exit 1) or the arguments are rejected (exit 2).

Commands used for the numbers in this file:

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile smoke --out artifacts/human_strategy/v0_107/cold_smoke.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile smoke --time-limit 150 --max-steps 80 --strategic-width 2 --max-width 3 --out artifacts/human_strategy/v0_107/cold_150s.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode diagnose --root post-sd3 --profile smoke --time-limit 60 --max-steps 12 --strategic-width 3 --out artifacts/human_strategy/v0_107/diagnose_post_sd3.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile smoke --time-limit 15 --max-steps 4 --out artifacts/human_strategy/v0_107/optimise_smoke.json
```
