# Dependency options, offline provenance audit

Research note for GitHub issue #19. Parent commit `69264c065ec0ec2bd4a2ad83a804a2af3df4bf4f`. Branch `local/dependency-options-offline-audit-pr2`. This is a replay and contract audit. It is not a search of deal 4925153, not a new 171 game, and not a persisted frontier.

## What changed

`select_dependency_portfolio` still reserves a unique JOIN or REVEAL receiver, then fills by the existing source signature. The rank key is unchanged: lower corrected cost, lower `dependency_penalty`, higher `target_bonds`, then pack and id. Outcome signatures are reported on `PortfolioPick` and are not a weight. `kernel_lower_bound(state, g)` still returns `admissible_remaining(state)`. It does not read `g` or the penalty. `prefer_option_actions` still only reorders an action that is already in the generated list.

An admitted option now has to replay to its declared target pack, corrected cost, absolute `target_g`, admissible `h_target`, and `f_target = target_g + h_target`. A `dataclasses.replace` edit of any one of those fields is rejected, including an `h` and `f` pair that agrees with itself and disagrees with the replay. `finishability_proof` and a failed `replay_ok` flag are rejected. A zero-cost whole-column transfer stays legal and is scored 0. A real stock deal stays cost 1, which is `deal_cost()`.

Critical priority is applied only when the caller graph rebuilds to the same nodes as every admitted source. The comparison includes kind, satisfaction, `requires_all`, `requires_any`, and landing. Matching obligation id strings is not enough. A mismatched graph is refused: `protected_ids` stays empty, and the size-2 selector still chooses `spend-only-receiver`. RECEIVE nodes are not protected. When the matched graph has a size-1 RECEIVE landing, `receive_protection` is `unsupported` and that id is listed in `unsupported_receive_ids`. Enables and blocks still come only from JOIN and REVEAL.

`diverse_ancestor_available` is true only when admitted options carry two or more replay-verified checkpoint packs. `AncestorClaim.continuation` is replayed from `checkpoint_pack` and must reach `source_pack`. An empty continuation is valid only when the source already is that checkpoint. A failed replay increments `rejected_ancestor_claims` and is not counted. Stock length, including `len(stock) % 10 == 0`, is not an ancestor. Distinct source packs are not an ancestor. With no verified claim the status is `not_established`.

The rules engine, search kernel, Human Strategy Controller, purposeful-macro discovery, both solution files, and the incumbent are unchanged. `FrontierCheckpoint` is not implemented. `independent_cold_complete` stays false. `AGENTS.md` is unchanged.

## Feasibility is not two-stage cost

On the size-2 fixture both constructed options have corrected cost 1. `preserve-receiver` then the immediate join `(0, 1, 1)` costs 2 and reveals the face-down card. `spend-only-receiver`, then the blocker `(0, 2, 1)`, then `(0, 4, 1)` costs 3 and also reveals. The second `9c` keeps the reveal feasible after the spend. The selector still chooses the spend, because the singleton reserve is inactive and `target_bonds` is 1 against 0. Both penalties are 0.

That ordering is permissive. It does not say the spend is the cheaper two-stage plan. The first-option cost is 1 in both cases. The verified full costs are 2 and 3. No estimated second-stage cost is added to `h` or `f`, and none is passed to `kernel_lower_bound`. On the size-1 board the same spend has penalty 4, while `f_target` remains `target_g + h_target`.

## Source signature and outcome signature

On the size-1 board the preserve and spend options share a source pack and therefore one source signature: epoch 0, one face-down card, no foundations, buried suits `(0, 0, 1, 0)`, accessible intervals `(2, 3, 3, 4)` in suit order spades, hearts, diamonds, clubs. The preserve move does not change that signature. The spend merges `8c` onto `9c`, and the club interval count falls from 4 to 3. The target packs differ either way. The portfolio reports both outcome signatures and still ranks the preserve first, because of the unique receiver rather than the signature.

The same split appears on the published roots below: one source signature, eight target packs, and only three outcome signatures.

## Replay checks

A mutated cost, `target_g`, `h_target`, or `f_target` is dropped before ranking. So is a self-consistent but inflated `h` and `f`. A zero-cost park of `8c` onto an empty column, with no face-down card under it, is admitted at cost 0. Replacing that cost with 1, or with 1 and `target_g` 1, drops it. Replacing a legal deal's cost with 0 drops it.

`prefer_option_actions` does not append `(9, 8, 1)` when that tuple is absent from `tableau_actions`. While stock remains, `pack_whole_game_identity` equals `pack_state`. Permuting columns changes that ordered pack. `pack_post_stock_symmetry_state` still raises while stock remains.

## Obligation identity

The size-2 options replay against their own graph and choose the spend. The size-1 graph, passed in as a foreign argument, would have marked `preserve-receiver` as the unique-receiver preserver. It is refused. `protected_ids` is empty and the spend remains first. Replacing `requires_any` on `join:c:8:col0` while keeping every obligation id also refuses the graph.

Moving the intact `8c` from column 0 onto empty column 2 costs 0. The source id `join:c:8:col0` is gone. `join:c:8:col2` is present. `(2, 1, 1)` is still legal, so the `9c` still accepts the card. The option nevertheless lists `join:c:8:col0` in `broken_dependencies`, because the id contains the column. This audit does not redesign the graph. One synthetic relocation is not a claim about every AND/OR graph.

A ten-card stock whose column-0 card is `AS` under a `2h`, with the other tops unable to receive that row, builds a size-1 RECEIVE node. The matched portfolio reports it as unsupported and does not put it in `protected_ids`. The size-1 club JOIN on that board is still protected. Neither the spend nor the deal lists a `receive:` id in `enables`, `blocks`, or `broken_dependencies`.

## Ancestry

Two states with ten stock cards and different packs are `not_established` when no claim is supplied. `len(stock) % 10 == 0` does not make them diverse. A later state reached by `(0, 2, 1)` from the size-1 opening shares that opening checkpoint: status `one_verified`, `diverse_ancestor_available` false, and one rejected claim for an illegal continuation. Two states that each attest themselves as the checkpoint, with an empty continuation, are `diverse_verified`. That positive control is synthetic. It is not evidence from deal 4925153.

## Verified routes

Both solution files were hashed and replayed from `deals/4925153.txt`. Neither file was written.

| | Canonical | Autonomous 185 |
| --- | --- | --- |
| File | `solutions/4925153_canonical.moves` | `solutions/4925153_autonomous_185.moves` |
| Actions | 174 | 189 |
| Deal indexes | 51, 89, 101, 119, 151 | 35, 67, 77, 126, 137 |
| Corrected cost | 172 | 185 |
| Admissible `h` at the finish | 0 | 0 |
| Foundations | 8 | 8 |
| Solved | yes | yes |
| SHA-256 | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` |

`f` in the tables below is `g + admissible_remaining`. It is not a finish forecast. While stock remains, that height is 5, 4, 3, 2, or 1. It jumps only after the stock is empty.

The opening is one pack. Every later paired stock epoch has a different pack and a different source signature.

| Stock | Canonical `g` / `h` / `f` | Face-down | Foundations | Bonds | Legal | 185 `g` / `h` / `f` | Face-down | Foundations | Bonds | Legal |
| --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 50, opening | 0 / 5 / 5 | 44 | 0 | 0 | 7 | 0 / 5 / 5 | 44 | 0 | 0 | 7 |
| 40, after deal 1 | 51 / 4 / 55 | 12 | 0 | 23 | 8 | 33 / 4 / 37 | 18 | 0 | 19 | 12 |
| 30, after deal 2 | 89 / 3 / 92 | 8 | 0 | 40 | 12 | 65 / 3 / 68 | 10 | 0 | 34 | 8 |
| 20, after deal 3 | 101 / 2 / 103 | 7 | 1 spade | 35 | 7 | 74 / 2 / 76 | 9 | 1 spade | 27 | 12 |
| 10, after deal 4 | 119 / 1 / 120 | 7 | 1 spade | 43 | 10 | 123 / 1 / 124 | 2 | 1 spade | 39 | 8 |
| 0, after deal 5 | 150 / 18 / 168 | 1 | spades, diamonds | 54 | 16 | 134 / 42 / 176 | 2 | spades, diamonds | 30 | 5 |

Checkpoint 140 is not the state immediately after the fourth deal. It is the state after 140 canonical actions: `g = 139`, `h = 1`, `f = 140`, 10 stock cards, 3 face-down, two foundations (spades and diamonds), two empty columns, 44 bonds, 31 legal tableau moves. Checkpoint 151, before the fifth deal, is `g = 149`, `h = 1`, `f = 150`, stock 10, face-down 1, no empty column, 50 bonds, 19 legal moves. Checkpoint 152 is the post-deal row above.

The 185 state before its fifth deal, action index 137, is `g = 133`, `h = 1`, `f = 134`, stock 10, face-down 2, two foundations, one empty column, 30 bonds, 17 legal moves. Dealing it reaches the stock-0 row: the empty column is filled, `h` becomes 42, and `f` becomes 176. One legal step at checkpoint 140 and one legal step at that 185 pre-deal state, each claimed by replaying its prefix from the opening, verify as one ancestor. The two graphs do not match, so critical priority is refused. The packs are different anyway.

## Published eight roots

The lines in `docs/reveal_aware_heart_macros_v0_139.md` were replayed from canonical checkpoint 140, then one fifth deal. No macro search was run. All eight match the published post-deal `g`, `h`, `f`, and face-down count. Each heart-top list contains `5h 4h 3h`. Foundations are spades and diamonds. Stock is empty. The option built from that same action list has `target_g` equal to the published `g`.

| Root | Cost from `g = 139` | `g` | `h` | `f` | Face-down | Bonds | Legal |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 3 | 142 | 24 | 166 | 3 | 48 | 13 |
| 1 | 4 | 143 | 24 | 167 | 3 | 48 | 15 |
| 2 | 5 | 144 | 24 | 168 | 3 | 48 | 16 |
| 3 | 5 | 144 | 25 | 169 | 3 | 47 | 14 |
| 4 | 5 | 144 | 25 | 169 | 3 | 47 | 15 |
| 5 | 4 | 143 | 25 | 168 | 3 | 47 | 13 |
| 6 | 4 | 143 | 24 | 167 | 3 | 48 | 15 |
| 7 | 5 | 144 | 24 | 168 | 3 | 48 | 15 |

All eight options are built at checkpoint 140, so they share one source pack and one source signature. Their target packs are eight different states. Their outcome signatures collapse to three. Epoch, face-down histogram, foundation suits, two-space flag, and buried-suit counts agree. The accessible-interval counts, in suit order spades, hearts, diamonds, clubs, are `(3, 11, 5, 8)` on roots 0, 1, 2, 6, and 7; `(3, 11, 6, 8)` on root 3; and `(3, 11, 5, 9)` on roots 4 and 5.

With an empty continuation back to checkpoint 140, the status is `one_verified`. Without a claim it is `not_established`, even though this state has a stock length divisible by 10.

The first legal tableau action at each post-deal state produces eight source packs. That action is the generator's first legal tuple, not a searched choice. Claiming each source by replaying its published macro and the fifth deal from checkpoint 140 still yields one verified checkpoint. The eight graphs are not the checkpoint graph, so the call refuses critical priority. Without claims the status is again `not_established`. The portfolio cap is an allocation. This call kept all eight steps. Keeping fewer would not prove an omitted step impossible.

Root 0's published twelve-action terminal, replayed after that root's macro and the fifth deal, matches the v0.139 record: `g = 154`, `h = 17`, `f = 171`, face-down 2, foundations spades and diamonds, 55 bonds, no empty column, 22 legal tableau moves, and a column-top heart run `kh` through `7h`. That `f` is the admissible sum on a replayed state. This audit did not continue it and did not screen it.

## Evidence that was not used

`artifacts/` is gitignored. On this working tree these files were present and untracked:

- `artifacts/stock_boundary_v0_133/results.json`
- `artifacts/purposeful_macro_v0_134/results.json`
- `artifacts/origin_fair_v0_135/results.json`
- `artifacts/post_deal_milestone_v0_136/results.json`

None was opened. None was regenerated. A clone of this commit does not contain the old eight-root packs, lineages, or costed candidate lists. The replayable substitute is the published move table above.

`docs/pre_sd5_backward_preparation_v0_132.md` records a checkpoint-140 probe that retained 20,000 identities and did not reach checkpoint 151. This audit does not rerun that probe, does not manufacture an SD3 or SD4 candidate, and does not treat that capped frontier as a second ancestor.

## Tests

`tests/test_dependency_options_two_stage.py` and `tests/test_dependency_options_offline_audit_pr2.py`: 15 passed in 1.64 seconds. The four PR1 tests were not edited.

The maintained regression is the v0.123 file list plus the v0.124, v0.125, v0.126, v0.129, v0.130, v0.131, v0.132, v0.133, v0.134, v0.135, v0.136, v0.137, v0.138, and v0.139 files, plus the PR1 and PR2 files: 47 files, 678 passed, 0 failed, in 229.26 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this run. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT`. It was not changed.

Collection of these eight modules still fails: 8 errors in 1.84 seconds with `PYTHONPATH=src`. The missing modules are `common_priority_schema_ab_v0_1`, `one_shot_natural_empty_service_v0_1`, `one_shot_natural_r3_service_v0_1`, and `workspace_opportunity_service_lane_v0_1`. The tests were not edited. Bare `pytest tests` was not used as the regression.

- `tests/test_exact_state_policy_context_equivalence_v0_1.py`
- `tests/test_one_shot_natural_empty_service_v0_1.py`
- `tests/test_one_shot_natural_r3_service_v0_1.py`
- `tests/test_workspace_opportunity_service_lane_v0_1.py`
- `tests/test_workspace_service_generalisation_panel_v0_1.py`
- `tests/test_workspace_service_lag1_grace_v0_1.py`
- `tests/test_workspace_service_stock_guard_v0_1.py`
- `tests/test_workspace_service_stock_synchronous_v0_1.py`

## Recommendation

Do not start a persisted-frontier implementation from this result.

The contract can now reject a malformed cost, `g`, `h`, or `f`, a stale obligation graph, and a false ancestor inferred from the stock length. That does not make the current rank worth storing. On the two-receiver fixture the selected first option costs 1, while the verified preserve-then-reveal line costs 2 and the selected spend-then-reveal line costs 3. Outcome diversity is telemetry: the eight published roots are eight packs, three outcome signatures, and one checkpoint-140 ancestor. The checked-in material does not supply a second verified ancestor for this deal. A join id also changes when an intact interval changes column, so a stored edge can look broken while the receiver is still legal. RECEIVE protection remains unsupported.

## What this does not show

The replay does not show a shorter game than 172, and it does not show that 172 or 185 is optimal. `independent_cold_complete` stays false. Deal 4925153 was not searched. Caps were not raised. The branch is not merged to `main`.
