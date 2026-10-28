# Phase-aware milestones v0.137

Schema `spider-phase-aware-milestone-0.137`. Deal `4925153`. Branch `local/phase-aware-milestone-v0-137`, started from v0.136 `40589d1c4ad7455c1cb01aad14427f55dbbbcd0e`.

Two facts still define the tactical milestone: one new club foundation, and at least one face-down card actually exposed. `phase_aware` is opt-in. Callers that omit it keep the v0.136 progress lane and action order. `f` orders candidates. It does not prune, and a milestone is not a finished game.

## Result

Gate A compared the two tableaux. Gate B passed. Gate C kept one milestone and the screen rejected it. Gate D did not run. The 171 objective is not established.

The five-move shortcut from checkpoint 152 is a different tableau from checkpoint 160. Both have face-down count 0, foundations spades, diamonds and clubs, and admissible `f = 169`. The shortcut costs 155 and the canonical window costs 158. The three saved moves are matched by a residual bound of 14 instead of 11. Same-suit bonds are 46 instead of 49, open columns are 2 instead of 3, and legal tableau moves are 56 instead of 124. The canonical suffix's first action, `move 3 4 1`, still applies. The next action, `move 3 5 3`, is illegal: column 5 holds the 3 of clubs, while the canonical line needs the 7 of hearts there so the 6-5-4 of hearts can move. The shortcut also leaves `6c 5c 4c` and the ace of spades on column 8, and the club run on column 6 stops at the 7. Those joins are still to be built. `f = 169` is the admissible lower bound on that different tableau. It is not a replayed finish.

The phase-aware control, with no reference actions, replayed that same five-move pack inside the v0.136 budget. The eight early roots were the paired v0.134 portfolio. The new ordering found one complete milestone, root 0 at `g = 154`, `h = 17`, `f = 171`, the same physical pack Gate C of v0.136 already exhausted. The screen requires `f <= 170` and also excludes that pack. Nothing opened. The 20,000-state continuation was not started. The v0.136 policy was not rerun.

Caps stayed at 12,000 / 12 seconds for the control, 6,000 / 6 seconds for each tactic, and 20,000 / 45 seconds for a continuation that did not run. RSS stayed 512 MB. One worker. The canonical post-SD5 search was not repeated. v0.138 was not started. The 172 and 185 files were hashed and replayed before and after.

## 1. Shortcut against checkpoint 160

Both lines were replayed from checkpoint 152 (`g = 150`, `h = 18`, `f = 168`, stock empty, one face-down card, no club foundation). `h` below is `admissible_remaining` on the resulting state. The v0.136 search range `min_h = 14`, `max_h = 19` is telemetry and was not copied into this table.

| | Checkpoint 160 | Five-move shortcut |
| --- | ---: | ---: |
| Corrected cost | 158 | 155 |
| Admissible `h` | 11 | 14 |
| `f = g + h` | 169 | 169 |
| Same-suit bonds | 49 | 46 |
| Mixed joins | 3 | 3 |
| Open columns | 3 | 2 |
| Legal tableau moves | 124 | 56 |
| Face-down cards | 0 | 0 |
| Foundations | spades, diamonds, clubs | spades, diamonds, clubs |
| Stock | 0 | 0 |

Packs differ. Post-stock symmetry packs differ. The shortcut actions are `move 5 2 1`, `move 5 9 1`, `move 4 5 1`, `move 4 1 2`, `move 4 9 1`. They are not stored in `src/spider/post_deal_milestone.py`.

Observed: three fewer corrected moves, residual bound worse by three, three fewer same-suit bonds, one fewer open column, and 68 fewer legal moves. The suffix does not transfer. Speculative, and not searched in this gate: some other line from the shortcut might still finish at 169 or below.

## 2. Opt-in ordering

`search_milestone(..., phase_aware=True)` uses three lanes and round-robin: foundation, reveal, setup. The foundation key ranks suit progress and leaves face-down out of the lead position. The reveal key leads with the face-down count, so a club-only state does not sit ahead of an earlier reveal on that lane. The setup key still leads with `g`, and with the named column's face-up length when a column is set, so a zero-cost park remains reachable. Every legal tableau move is still returned.

Action order reads the same two flags from the current state. When the foundation is done and the reveal is not, a reveal sorts first. When the reveal is done and the foundation is not, a suit extension sorts first. When neither is done, a move that extends, reveals, or uncovers sorts ahead of a move that does none of those. These keys are ordering only. The paid-move cap, the proof rule `g + admissible_remaining > proof_ceiling`, and exact best-`g` transpositions are unchanged. Equality with the ceiling stays eligible.

`hit_policy="lower_f"` is a separate selector. It replays up to 128 terminals, keeps a lower admissible `f` ahead of a lower `g`, and records truncation. An unverified terminal is not treated as a worse `f`. `retain_endpoints(order="f")` uses the same preference across roots. Default `order="g"` and default `hit_policy="lowest_g"` stay the historical rules.

`on_expand` counts a node after the kernel has already counted the expansion. It does not change heaps, admission, or pruning. Admitted phase counts include children that are not expanded. A `both_achieved` child is a terminal and is not expanded.

## 3. Positive control

Source: checkpoint 152. Budgets: 8 paid moves, 12 actions, 12,000 identities, 12 seconds, 512 MB, proof ceiling 172. `phase_aware=True`, stop on the first replayed milestone. No column filter and no reference actions.

| | This control |
| --- | ---: |
| Stop | solved |
| Milestone `g` | 155 |
| Paid / zero-cost | 5 / 0 |
| Wall / process seconds | 0.096012 / 0.093750 |
| Bound time inside that | 0.034448 |
| Identities / expansions / generated | 135 / 6 / 147 |
| Lane expansions | foundation 3, reveal 3, setup 0 |
| Peak RSS | 31.969 MB |
| Proof prunes | 0 |
| Search `min_f` / `min_h` / `max_h` | 168 / 14 / 19 |

Phase admissions: both unfinished 132, reveal-only 2, foundation-only 0, both achieved 1. Expansions: unfinished 5, reveal-only 1. The stored pack is the shortcut pack from section 1, so the recomputed endpoint is `h = 14`, `f = 169`. First hit at 0.096 seconds. One terminal, so hit selection did not drop another milestone. v0.136 recorded 0.096911 wall seconds and did not record process time, so there is no CPU comparison against that run. This wall time is 0.0009 seconds lower.

## 4. Eight early roots

`discover_macros` used the unchanged v0.134 generator and the 6-second discovery cap. The portfolio fingerprint matches the v0.134 and v0.135 artifacts. This discovery pass retained 3,198 identities, expanded 229, generated 4,002, and stopped on the clock at 6.123 seconds. Those node counts can move inside the cap. The fingerprint is the pairing.

Each root then used the new ordering, `hit_policy="lower_f"`, 12 paid moves, 18 actions, 6,000 identities, 6 seconds, 512 MB, and proof ceiling 171. All eight stopped on the clock. Queue sizes at the stop are unfinished heap entries, not a proof that no later milestone exists.

| Root | Met | First hit | `min_f` | Unique | Expanded | Foundation admitted / expanded | Reveal admitted / expanded | Both admitted |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| 0 | yes, `g = 154` | 12 paid, 3.994 s | 166 | 4,525 | 756 | 521 / 249 | 0 / 0 | 1 |
| 1 | no | | 167 | 2,386 | 585 | 250 / 193 | 0 / 0 | 0 |
| 2 | no | | 168 | 729 | 432 | 17 / 15 | 0 / 0 | 0 |
| 3 | no | | 169 | 829 | 512 | 6 / 6 | 0 / 0 | 0 |
| 4 | no | | 169 | 785 | 459 | 0 / 0 | 0 / 0 | 0 |
| 5 | no | | 168 | 1,516 | 532 | 0 / 0 | 3 / 3 | 0 |
| 6 | no | | 167 | 2,033 | 538 | 50 / 50 | 0 / 0 | 0 |
| 7 | no | | 168 | 1,031 | 475 | 13 / 13 | 0 / 0 | 0 |

Root 0's only verified terminal is the kept endpoint. `lower_f` retained that one state and did not hide a second terminal. Face-down fell from 3 to 2 and clubs rose from 0 to 1 on the terminal itself. No reveal-only state was admitted on that root: the expose and the foundation arrive on the same child.

The kept endpoint replays at `g = 154`, `h = 17`, `f = 171`, 12 paid moves, no zero-cost moves. Pre-deal macro: `move 2 5 1`, `move 8 1 3`, `move 10 8 2`, `move 1 10 3`, `move 3 1 2`, `move 9 2 1`. Tactical path: `move 5 2 1`, `move 5 9 1`, `move 3 1 1`, `move 3 5 7`, `move 3 7 1`, `move 3 9 1`, `move 10 5 1`, `move 10 6 3`, `move 4 6 1`, `move 4 9 3`, `move 4 10 2`, `move 4 9 1`. Its ordered pack is the v0.136 exhausted identity.

Recorded v0.136, not rerun: root 0 was the only hit, at the same `g` and `f`, with 3,756 identities and 640 foundation-only admissions. Reveal-only admissions were 0, 0, 0, 0, 0, 3, 0, 0 across roots 0–7. This run's reveal-only admissions are the same pattern. Roots 3 and 7 admitted a few foundation-only states that the recorded pass did not, and still finished no milestone. No endpoint has `f <= 170`.

Eight tactic searches took 48.115 wall seconds and 47.828 process seconds. The recorded v0.136 tactic wall time sums to 48.055 seconds. Process time was not stored for v0.136.

The screen's reasons for the only endpoint are "previously exhausted identity" and "f above screen" (`f = 171`, screen 170). `proof` is false. The one-ply successor check was not run, because the identity was already excluded. Gate D stayed closed. `verify_complete_solution` was not given a candidate.

## 5. Tests

`tests/test_phase_aware_milestone_v0_137.py` and `tests/test_post_deal_milestone_macros_v0_136.py`: 22 passed. The new file locks the shortcut comparison, the illegal suffix, legacy lanes when the flag is omitted, reveal-then-foundation, both partial phases under a 40-identity cap, state-derived phase flags, a zero-cost park followed by a paid move, `lower_f` selection separate from lane order, the screen's refusal of the exhausted `f = 171` pack, and the driver's gate order. A 30-identity cap on the split board admits the club-only child and then stops while expanding the next reveal, so the regression uses 40. These tests do not run the 12-second control or the eight tactic searches.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

The maintained regression is the v0.124 file list plus the v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, and v0.137 files: 43 files, 644 passed, 1 failed, in 223.15 seconds. The failure is `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`, which returned `PLANNING_STALL` instead of `TIME_LIMIT`. That assertion was not changed.

## 6. Next recommendation

Do not resume the `g = 154`, `h = 17`, `f = 171` identity, and do not treat a shorter club-and-reveal sequence as a gain when the recomputed `f` stays 169. The next experiment should search these same roots for a different post-deal state whose own admissible `f` is at most 170, under the same caps. This release does not start that search.
