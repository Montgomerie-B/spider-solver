# Purposeful macro portfolio v0.134

Schema `spider-purposeful-macro-portfolio-0.134`. Deal `4925153`. Branch `local/purposeful-macro-portfolio-v0-134`, started from v0.133 `f1945b087691a86c4c7371a4306115d81536a6ea`.

One question. Can a short search of legal tableau moves, scored by the incoming fifth-deal row, build a receiver plan at least as good as the known feasible preparation, and can one multi-root continuation from those plans rejoin the 172 route at a full-game cost of 171 or less? Empty-column count is not the objective. A zero-cost whole-column transfer may be the first action of a useful sequence. This is one experiment. It is not a new solver, and a bounded miss is not an optimality proof.

## Result

The macro search did demonstrate the known feasible landing quality without being given those moves. From checkpoint 140 it retained 3,143 identities in a 6-second tableau search, then scored a shortlist of 64. Six replayed plans deal at `g = 142` with four same-suit landings. One of them has `h = 24`, `f = 166`, three face-down cards, 48 bonds, two foundations, and the same landing tuple as the named early candidate. Its actions are `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`. The first and third are zero-cost whole-column transfers. Two spaces were available at the start; the first transfer relocated an empty while the count stayed at two. The exact three-action list `move 2 5 1`, `move 3 1 2`, `move 9 2 1` was not that witness. A different generated plan does contain those three actions, with three extra zero-cost transfers between the park and the heart seat, and it reaches the same `g = 142`, `h = 24`, `f = 166` landing tuple. That plan was root 0 of the continuation. Same-suit count is not treated as proof of a cheaper finish: five-landing plans also appeared, at `g = 143` or `144` and `f = 167` to `169`.

The continuation then ran once. It stopped on the 45-second limit with 3,182 retained identities, 2,192 expansions, and 124,294 generated children. Admissible pruning rejected 104,769 arrivals. No state matched a canonical checkpoint from 152 through 174. Foundations reached 3. Minimum `f` stayed 166. No complete game was accepted. The outcome is inconclusive.

The schedule explains the miss better than the landing score does. The goal lane expanded 2,180 nodes and the cost lane 12. Of the eight roots, origin 7 received 2,190 expansions. Origins 0 and 1 were expanded once each. Origins 2 through 6 were not expanded. Origin 0 is the `f = 166` plan. Origin 7 is a five-landing tableau at `g = 144`, `h = 24`, `f = 168`. The unchanged v0.133 lanes starved the other purposeful roots. That is a measurement for a later scheduling change. The lanes were not retuned here.

The v0.133 single-root figures are a historical baseline, not a control that was rerun: 45.037 seconds, 3,317 retained, 2,765 expanded, 129,336 generated, 107,775 proof prunes, no reference match, maximum foundations 3, minimum `f` 166, goal lane 2,751 of 2,765. That run started from one named post-deal tableau. This run's expansions came from a different root. The two are not a paired comparison.

Caps were not raised. The canonical post-SD5 search was not repeated. Its 80,000-state and 90-second budgets were not used. No v0.135 work was started. Both solution files are unchanged. `independent_cold_complete` is false.

## 1. What a macro is

A candidate is an ordered tuple of engine-legal tableau moves. There is no new action type and `step_cost` is unchanged. A whole face-up column moved onto an empty column still costs 0 when the source has no face-down cards. Unrestricted Deal is unchanged and is not taken inside the macro budget. The deal is applied only when a shortlisted pre-deal state is scored.

The objective reuses `ObjectiveKind.SHAPE_STOCK_RECEIVER` and `evaluate_target(..., "column_top_is")`. The desired top is the next stock card's suit and rank plus one, on that physical column. `next_stock_row` supplies the row. `landing_kind` counts a same-suit hit only in that case. An empty column, including one that would catch a king, is not a hit. Creating or holding empties is recorded on the route and does not make the macro succeed.

Discovery keeps every legal tableau move. It does not import the workspace-tactic skip of a zero-cost move that fails to add an empty column, and it does not import the objective realiser's free-move skips or `workspace_quotient_key`. While stock remains, identity is ordered `pack_state`. Two discovery lanes order the same graph: receiver key `(-hits, -follow, g, face_down)` and setup key `(g, -follow, -hits, face_down)`. Follow-through is the best one-ply receiver gain. Neither key contains an empty count. The setup lane exists so a zero-cost transfer with no immediate gain is still expanded.

Limits for that search: depth 8, 4 paid moves, 4,000 retained identities, 6 seconds, 512 MB. `assess_immediate_deal` runs only on the shortlist of at most 64 states. The kernel stopped at 6 seconds with 3,143 identities. Scoring the shortlist took another 0.177 seconds, so the wall clock was 6.193 seconds. The witness was already inside that shortlist. The cap was not increased to absorb the scoring.

Gate B required one replayed plan with at least four same-suit landings and post-deal `g <= 142`. It passed. Six candidates were at `g = 142`, `f = 166`, and six more at `g = 142`, `f = 167`. The portfolio kept at most eight purposeful roots with `f <= 171`, including one four-landing root at `g = 142`. A post-deal state with `f > 171` can be left out of that committed deal. That does not delete the preceding tableau from further preparation, and this probe did not need to: the kept roots were all at `f <= 169`.

## 2. Portfolio and continuation

| Origin | Post-deal g | h | f | Hits | Expansions | Macro, in brief |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 142 | 24 | 166 | 4 | 1 | named park, three extra free transfers, heart seat, jack |
| 1 | 143 | 24 | 167 | 5 | 1 | witness actions, then `move 3 10 2` |
| 2 | 144 | 24 | 168 | 5 | 0 | free transfers, then the four-landing core |
| 3 | 144 | 25 | 169 | 5 | 0 | witness actions, then two paid joins |
| 4 | 144 | 25 | 169 | 5 | 0 | witness actions, then a paid join and a run |
| 5 | 143 | 25 | 168 | 4 | 0 | witness actions, then `move 9 4 7` |
| 6 | 143 | 24 | 167 | 5 | 0 | free transfers, then the four-landing core and one join |
| 7 | 144 | 24 | 168 | 5 | 2,190 | witness actions, `move 3 10 2`, `move 7 5 1` |

The witness itself, the four-action plan at `f = 166`, is one of the six `f = 166` candidates and is not one of these eight objects. Root 0 is another `f = 166` plan and is the one the portfolio rule kept. Both were generated by the search. Neither list was written into the generator.

The continuation uses the public v0.133 helpers: `bridge_action_order`, `matching_stops`, `replay_remapped_suffix`, `projected_full_cost`, `accept_cost`, and `select_ordering_targets`. Lanes stay `(displacement, g)` and `(g, displacement)`, with the same nearest-displacement dropout on the cost lane only. Action order is corrected cost, then a reveal, then a same-suit continuation. An empty destination is not ranked. `strategic_action_order` is not used. Identity is `pack_whole_game_identity`. Stored paths stay `pack_state`. The proof test is strict `g + h > 171`. Equality stays. `incumbent.proof_prune` is not used. Each kernel origin is the caller's root index. A symmetry-dominated physical chain would be reported and left unexpanded. This portfolio had no such drop inside the continuation.

A root that already rejoined or was solved would have been recorded with zero expansions. None was. The one search then used 20,000 identities, 45 seconds, and 512 MB. It did not call the post-SD5 driver and it did not use 80,000 states or 90 seconds.

| | Discovery | Continuation |
| --- | ---: | ---: |
| Stop | time limit | time limit |
| Elapsed | 6.193 s, of which scoring 0.177 s | 45.036 s |
| Retained identities | 3,143 | 3,182 |
| Expanded | 226 | 2,192 |
| Generated | 3,932 | 124,294 |
| Zero-cost actions considered | 635 | 6,404 |
| Lower-bound prune events | 0 | 104,769 |
| Proof-prune identities | 0 | 72,394 |
| Unretained proof identities | 0 | 71,574 |
| Duplicate skips | — | 16,238 |
| Stale skips | — | 76 |
| Minimum `f` | — | 166 |
| Minimum `h` | — | 11 |
| Maximum `h` | — | 26 |
| Maximum foundations | — | 3 |
| Reference matches | — | 0 |
| Goal-lane expansions | — | 2,180 |
| Cost-lane expansions | — | 12 |
| Receiver-lane expansions | 103 | — |
| Setup-lane expansions | 123 | — |
| Peak RSS | 32.7 MB | 48.1 MB |
| Displacement time | — | 1.795 s across 3,295 calls |

Continuation expansions by corrected cost run from `g = 142` through `g = 160`. The busy band is `g = 152` to `g = 156`. One node was expanded at `g = 160`. Minimum `f` never left 166. `h` did fall, from the roots' 24–25 down to 11, which is why the bound did not freeze the graph at `g = 147`. Falling `h` on one root is not a rejoin.

No candidate was composed into a full route. `verify_complete_solution` was not given a continuation. A tactical receiver plan is not reported as a solved game.

## 3. What was preserved

Corrected MobilityWare scoring, unrestricted Deal, packing formats, `search_kernel.py`, `engine.py`, `rules.py`, and the Human Strategy Controller were not edited. The v0.133 bridge module was not retuned. Historical reports were not rewritten. The 172 and 185 solution files were hashed before and after:

| Route | Actions | Corrected MW | Foundations | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | 174 | 172 | 8 | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` |
| `solutions/4925153_autonomous_185.moves` | 189 | 185 | 8 | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` |

The artifact is `artifacts/purposeful_macro_v0_134/results.json`. It is gitignored. It is not an incumbent.

## 4. Tests

`tests/test_purposeful_macro_portfolio_v0_134.py`: 13 passed in 1.66 seconds. The file checks legal replay and the free park before a paid seat, rejection of a zero-cost move that achieves nothing, an empty column losing to a real receiver, column-specific `column_top_is` hits, two-space audit, stock-bearing `pack_state`, absolute post-deal `g`, origin-to-prefix reconstruction, a remapped suffix attached to the matching origin, last-slot admission, `g + h = 171` kept and `g + h = 172` rejected, and the refusal to call a tactical plan a complete game. The generator source does not contain the seeded action tuple. The driver does not call the old post-SD5 search. These tests do not run the 4,000-state or 20,000-state budgets.

The maintained regression is in section 5.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

## 5. Maintained regression

The maintained regression is the file list in `docs/global_search_architecture_v0_124.md`, plus the v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, and v0.134 files. One run with `PYTHONPATH=src` collected those 40 files. 608 tests passed and 1 failed in 216.78 seconds. The failure is `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`, which observed `PLANNING_STALL` instead of `TIME_LIMIT`. The assertion was not weakened. The other maintained tests passed, including the 13 new v0.134 tests. This sensitivity is not retired.

## 6. Next recommendation

Give each admitted post-deal root a share of the same 20,000-state and 45-second budget. In this run the existing goal lane spent 2,190 of 2,192 expansions on one `f = 168` root and left the `f = 166` preparation with a single expansion. That is a scheduling result. It is not evidence that the `f = 166` tableau cannot rejoin, and it is not a reason to raise the cap, repeat the canonical post-SD5 search, or add another heuristic family.
