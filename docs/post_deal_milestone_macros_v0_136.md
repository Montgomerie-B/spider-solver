# Post-deal milestone macros v0.136

Schema `spider-post-deal-milestone-0.136`. Deal `4925153`. Branch `local/post-deal-milestone-macros-v0-136`, started from v0.135 `e95f77ba5e9b0593be53632ca7f23d10cc9a69a4`.

One objective. After the fifth deal, expose at least one buried card and complete one club foundation. Empty columns, foundation count alone, and bond count are not that objective. A path counts only when both facts are true and the path replays from the source that produced it.

## Result

Gate A passed. Gate B kept one milestone. Gate C did not accept a game. The 171 objective is not established, and this run does not prove that no such game exists.

The positive control started at canonical checkpoint 152, corrected cost 150, one face-down card, and no club foundation. The canonical eight-action window was replayed first and was not given to the solver. Inside an 8-paid-move, 12-action, 12,000-state, 12-second, 512 MB budget, with proof ceiling 172, the search found its own five-move path. Replay ends at cost 155 with the ace of clubs exposed and the first club foundation removed. That is three corrected moves shorter than the canonical window, which reaches the same two facts at cost 158.

The unchanged v0.134 generator reproduced the same eight post-SD5 roots as v0.134 and v0.135. Each root then had one tactic search: 12 paid moves, 18 actions, 6,000 identities, 6 seconds, 512 MB, proof ceiling 171. Root 0 reached both facts at cost 154, admissible remaining 17, `f = 171`, after 12 paid moves and one exposed card. The other seven searches stopped on the six-second clock. Foundations without a reveal, and one reveal without a club foundation, were recorded and were not kept.

One origin-fair continuation then started from that single milestone state, not from the eight early roots. The existing cap is 20,000 identities, 45 seconds, 512 MB, and strict `g + h > 171`. The frontier was exhausted in 0.608 seconds: 28 identities, 28 expansions, 1,676 admissible rejections, no checkpoint match from 152 through 174, foundations stayed at 3, minimum `f` stayed 171. No route was accepted. `verify_complete_solution` was not given a candidate. The exhausted cone belongs to this `f = 171` state. Roots 1 through 7 never produced an eligible milestone, so their games were not searched.

Caps were not raised. The canonical post-SD5 search was not repeated. v0.137 was not started.

## 1. Canonical facts, recomputed

Checkpoint 140 is the pre-deal source: `g = 139`, ten stock cards, two foundations, no clubs. Both threes of clubs are in that final stock row, so a club foundation cannot exist before the fifth deal.

Checkpoint 152 is the control source: `g = 150`, `h = 18`, `f = 168`, stock empty, one face-down card, foundations are spades and diamonds. The next eight canonical tableau actions all cost 1. Step 7 removes the last face-down card. Step 8 completes the club foundation. Checkpoint 160 is `g = 158`, `h = 11`, `f = 169`, no face-down cards, three foundations. Those actions are a feasibility oracle. Their tuples are not in `src/spider/post_deal_milestone.py`.

## 2. Positive control

`search_milestone` saw the physical state, the suit, the face-down baseline, and the budgets. It did not see the eight reference actions.

| | Control |
| --- | ---: |
| Paid-move cap | 8 (`g <= 158`) |
| Proof ceiling | 172 |
| Depth / identities / time / RSS | 12 / 12,000 / 12 s / 512 MB |
| Workers | 1 |
| Stop | solved |
| Elapsed seconds | 0.096911 |
| Retained identities | 128 |
| Expansions | 7 (progress 5, setup 2) |
| Generated | 139 |
| Proof prunes | 0 |
| Peak RSS | 30.898 MB |
| Result `g` | 155 |
| Paid / zero-cost moves in the path | 5 / 0 |
| Club foundations | 0 to 1 |
| Face-down cards | 1 to 0 |
| Replay | pack and `g` match |

The path, in file order, is `move 5 2 1`, `move 5 9 1`, `move 4 5 1`, `move 4 1 2`, `move 4 9 1`. Minimum `f` on the control was 168. Minimum `h` was 14 and maximum `h` was 19.

The paid cap and the proof ceiling are separate. Checkpoint 152 has `f = 168`. A single ceiling of `150 + 8 = 158` would have proof-pruned the root before the first expansion. `SearchLimits.proof_ceiling` defaults to `None`, and callers that omit it still compare `g + h` with `cost_ceiling`, including harvest tightening. Equality with the proof ceiling stays eligible. `incumbent.proof_prune` is not used.

Ordering prefers a longer same-suit run and a shallower copy of the next card in that run. It returns every legal tableau action, including zero-cost whole-column transfers. Empty-column count is not a score. The suit-wide identity is `pack_whole_game_identity`. A column-specific face-down target uses ordered `pack_state` instead. The driver does not request a column.

## 3. Eight tactic searches

Discovery used the unchanged generator: 8 tableau actions, 4 paid moves, 4,000 identities, 6 seconds, 512 MB. This run retained 3,279 identities, expanded 234, generated 4,119, and stopped on the clock at 6.138 seconds. Scoring took 0.114 seconds. Sixty-four candidates were scored. The eight committed roots match the v0.134 and v0.135 artifacts in order, actions, `g`, `h`, `f`, physical pack, and symmetry. The comparison is paired. A different unique count under the same six-second cap is the unfinished frontier, not a generator change.

| Root | g | h | f | Actions |
| ---: | ---: | ---: | ---: | --- |
| 0 | 142 | 24 | 166 | `move 2 5 1`, `move 8 1 3`, `move 10 8 2`, `move 1 10 3`, `move 3 1 2`, `move 9 2 1` |
| 1 | 143 | 24 | 167 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 10 2` |
| 2 | 144 | 24 | 168 | `move 2 1 1`, `move 10 5 2`, `move 1 10 1`, `move 3 1 2`, `move 9 2 1`, `move 7 10 1`, `move 7 8 2` |
| 3 | 144 | 25 | 169 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 4 5`, `move 8 4 2` |
| 4 | 144 | 25 | 169 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 10 2`, `move 9 4 7` |
| 5 | 143 | 25 | 168 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 9 4 7` |
| 6 | 143 | 24 | 167 | `move 2 1 1`, `move 8 5 3`, `move 1 8 1`, `move 9 2 1`, `move 3 1 2`, `move 3 10 2` |
| 7 | 144 | 24 | 168 | `move 2 1 1`, `move 9 2 1`, `move 1 5 1`, `move 3 1 2`, `move 3 10 2`, `move 7 5 1` |

Every root started with three face-down cards and no club foundation. The suit and those baselines were read from the root. Column indexes and the canonical eight moves were not supplied.

| Root | Met | Stop | Unique | Expanded | Generated | Seconds | Min `f` | Clubs seen | Min face-down | Foundation only | Reveal only |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | yes | time limit | 3,756 | 798 | 16,874 | 6.003 | 166 | 1 | 2 | 640 | 0 |
| 1 | no | time limit | 2,423 | 635 | 17,533 | 6.005 | 167 | 1 | 3 | 365 | 0 |
| 2 | no | time limit | 887 | 520 | 16,236 | 6.009 | 168 | 1 | 3 | 13 | 0 |
| 3 | no | time limit | 792 | 523 | 16,519 | 6.003 | 169 | 0 | 3 | 0 | 0 |
| 4 | no | time limit | 866 | 545 | 16,523 | 6.003 | 169 | 0 | 3 | 0 | 0 |
| 5 | no | time limit | 1,879 | 673 | 16,929 | 6.017 | 168 | 0 | 2 | 0 | 3 |
| 6 | no | time limit | 2,345 | 607 | 16,653 | 6.002 | 167 | 1 | 3 | 50 | 0 |
| 7 | no | time limit | 1,154 | 515 | 15,914 | 6.014 | 168 | 0 | 3 | 0 | 0 |

Root 0's verified hit is 12 paid moves and no zero-cost move. Absolute `g` is `142 + 12 = 154`. One club foundation was added and face-down fell from 3 to 2. Admissible remaining at that state is 17, so `f = 171`. The tactical clock then expired, with one verified hit. Roots 1, 2, and 6 built a club foundation and did not expose a card. Root 5 exposed a card and did not build a club foundation. Those states fail the predicate. A six-second stop is a bounded miss for that root, not a proof that a longer tactic is impossible.

Retention kept the one eligible endpoint. Nothing was symmetry-dominated. The pre-deal macro stored with it is root 0's macro above. The continuation macro on `PostDealRoot` is that pre-deal macro only, so a later search cannot attach this tactical sequence to a different root.

## 4. Continuation from the milestone

The continuation root is the retained state: origin 0, `g = 154`, `h = 17`, `f = 171`, purpose `post-deal club milestone`. It is not one of the eight early SD5 roots. v0.135 searched those eight together and stopped at 45.022 seconds with 5,695 identities, 3,318 expansions, minimum `f` 166, and expansions 415, 408, 407, 409, 408, 450, 413, 408. That run was not repeated.

| | This continuation | v0.135 continuation |
| --- | ---: | ---: |
| Roots | 1 milestone endpoint | 8 early SD5 roots |
| Stop | complete | time limit |
| Elapsed seconds | 0.608 | 45.022 |
| Retained identities | 28 | 5,695 |
| Expansions | 28 | 3,318 |
| Generated | 2,044 | 121,948 |
| Admissible rejections | 1,676 | 101,111 |
| Proof-prune identities | 998 | 81,068 |
| Minimum `f` | 171 | 166 |
| Maximum foundations | 3 | 3 |
| Reference matches | 0 | 0 |
| Accepted game | no | no |

All 28 expansions were on `0.goal`. `0.cost` expanded nothing. The origin status is exhausted. Goal remaining and cost remaining are 0. Cross-origin better-`g` updates: 0. Zero-cost actions considered: 158. Ceiling prunes: 0. Duplicate skips: 341. Stale skips: 4. Peak RSS was 39.719 MB. Minimum `h` was 11 and maximum `h` was 18. Expansions by `g` were 1, 3, 5, 7, 7, 4, and 1 at costs 154 through 160.

The scheduler flag is `negative_within_cap` because this frontier finished. That statement covers the retained milestone only. It does not cover roots 1 through 7, and it does not cover an unsearched cheaper milestone from root 0. No full route was composed. `independent_cold_complete` is false.

## 5. What was preserved

| File | Explicit moves | Corrected MW | Foundations | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | 174 | 172 | 8 | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` |
| `solutions/4925153_autonomous_185.moves` | 189 | 185 | 8 | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` |

Both hashes matched before and after the run. The artifact is `artifacts/post_deal_milestone_v0_136/results.json`. It is gitignored. It is not an incumbent.

`purposeful_macro.py` and `origin_fair_continuation.py` were not edited. The kernel change is the optional proof ceiling. Rules, `step_cost`, packing, and the Human Strategy Controller were not edited.

## 6. Tests

`tests/test_post_deal_milestone_macros_v0_136.py`: 12 passed. Together with `tests/test_proof_first_admission_v0_131.py` and `test_kernel_has_no_deal_or_suit_policy`, 23 passed in 0.83 seconds. The new file locks the issue budgets, the recomputed canonical window and the absence of those actions from the solver, a synthetic reveal-and-foundation, a zero-cost park before the paid join, rejection of a foundation that reveals nothing, symmetry unless the predicate names a column, proof equality and the untouched legacy ceiling, cheaper-prefix dominance, paid and depth caps, the origin's own tactical macro after the deal, and the driver's refusal to open Gate B or Gate C before the control. These tests do not run the 12,000-state control, the eight tactic searches, or the 45-second continuation.

The maintained regression is in section 7.

Bare `pytest tests` still fails collection on eight research modules that import missing `*_v0_1` services: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, and `tests/test_workspace_service_stock_synchronous_v0_1.py`. Those modules were not edited.

## 7. Maintained regression

The maintained regression is the file list in `docs/global_search_architecture_v0_124.md`, plus the v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, and v0.136 files. One run with `PYTHONPATH=src` collected those 42 files. 634 tests passed and 1 failed in 285.75 seconds. The failure is `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`, which observed `PLANNING_STALL` instead of `TIME_LIMIT`. The assertion was not weakened. The other maintained tests passed, including the 12 new v0.136 tests. This sensitivity is not retired. The v0.135 regression recorded the same failure, with 622 passed and 1 failed.

## 8. Next recommendation

Look for a reveal-and-club milestone with `f` strictly below 171 on these same post-deal roots. The only state retained here already sits on the proof ceiling, and the existing continuation exhausted it without a rejoin. A longer search of that state, a larger unique cap, and another pass over the canonical post-SD5 position do not follow from this result.
