# Frontier recovery v0.122

Strategic frontier recovery and a reserved deep tactical grant, on the v0.121 controller. No second solver. No new human-strategy principle. `engine.py`, `rules.py`, MobilityWare scoring, and anchored search were not edited.

## 1. Baseline and branch

Repository: `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`.

Branch: `local/frontier-recovery-v0-122`.

Baseline: `25072133f85162331e7c2af0abc42f12c9db36a3` (`2507213 Add workspace triage and productive deepening v0.121`), parent `6dd9524`. The working tree is that commit plus the uncommitted v0.122 edits. Nothing was committed, pushed, merged, or opened as a pull request.

Schema: `spider-human-strategy-0.122`.

One worker. Frontier capacity 8. Memory abort 3,072 MB. Pilot budgets 40 seconds and 150 seconds, with `--max-steps 220`.

## 2. Files changed

- `src/spider/human_strategy/strategic_frontier.py` — bounded deferred pool, one-at-a-time recovery, named-move pin, stall audit.
- `src/spider/human_strategy/controller.py` — recover when the active queue is empty, including after a dead-end with no dormant line; keep a step or memory stop when a better partial is reported.
- `src/spider/human_strategy/search_budget.py` — reserved 4,500-node grant with its own wall clock; a clock stop with an intermediate sequence can justify the next rung.
- `src/spider/human_strategy/foundation_direction.py` — a reserved deep allowance is not clipped back down to the proposal slice.
- `src/spider/human_strategy/__init__.py` — schema.
- `tools/human_strategy_solver.py` — version label.
- `tests/test_human_strategy_v0_117.py` — schema assertion.
- `tests/test_human_strategy_v0_122.py` — new focused tests.

Not changed: `engine.py`, `rules.py`, `anchored.py`, `search_kernel.py`, `solutions/`, the production incumbent registry, Spider Play Lab, and the v0.117 through v0.121 artifact directories.

## 3. Root cause of frontier exhaustion

v0.121's 150-second cold search stopped at 40.684 seconds with `PLANNING_STALL`, an empty queue, and about 109 seconds left. That empty queue was not proof that every legal continuation had been searched.

On the revised controller the active queue first empties at 42.978 seconds of the 150-second cold run. The audit stored on that event:

| Item | Value |
| --- | ---: |
| Retained strategic states | 174 |
| Explored lines | 27 |
| Explored physical states | 171 |
| Eligible deferred candidates | 22 |
| Deferred held / still stored | 24 / 24 |
| Legal tableau actions across the current and deferred states | 95 |
| Legal stock deals | 17 |
| Frontier transposition discards | 0 |
| Heuristic capacity discards | 35 |
| Resource-limited objectives | 41 |
| Objectives exhausted only inside their bound | 333 |
| Unexplored deferred successors | 22 |
| Of those, forced successors | 15 |
| Coordinator time still left | 107.022 s |
| Eligible work could still be started | yes |

Every capacity exclusion has `proof` false. Frontier transpositions are 0. The controller separately discarded one more expensive ancestry during the whole run (`dominance` 1 on stdout). That single dominance check is not why the queue was empty.

The policy text recorded at the empty event: the active frontier is empty, 22 heuristically deferred candidates remain eligible, and recovery will reconsider one of them. The text states that this is not graph exhaustion and not a proof.

The first eligible candidate was `PARK:move 1 4 1` at corrected g 39, campaign `C#1`.

Two later stops were scheduling, and both were fixed in this version:

- Restoring a deal-alternative such as `PARK:move 1 4 1` did not play that move. The label names a 1-based move whose third number is the card count. The pin was subtracting 1 from the count, so every one-card move failed the legality check and the line re-ran foundation recovery instead. The count is no longer decremented. A legal named move is pinned. An illegal name is not invented.
- A line with no legal action and an empty dormant list broke out of the search without looking at the deferred pool whenever the active queue was also empty. Recovery now runs on that exit too.

After those fixes the same cold configuration recovers work and then hits the configured 220-commit ceiling. See section 11. The frontier is not empty at that stop: 3 lines are still queued and 16 deferred candidates remain.

## 4. Queue and deferred-candidate accounting

The active queue stays at 8. Recovery does not increment `generated` and does not raise the cap.

A dropped or evicted line is held when its token is new, its corrected g is not worse than the stored ancestry, and it is either a forced successor or a physical state that is not already retained. A campaign-label copy of a state that is already retained is not stored. The pool holds 24 tokens. Overflow replaces the worst held token, and that token is not held again.

Final cold-run accounting, after recovery and the step stop:

| Counter | Value |
| --- | ---: |
| Generated | 71 |
| Explored | 49 |
| Dropped because full | 35 |
| Still queued | 3 |
| Frontier transpositions | 0 |
| Same-move refusals | 18 |
| Deferred held | 24 |
| Deferred remaining | 16 |
| Recovery attempts | 8 |
| Recoveries | 8 |
| Distinct recovered states | 5 |
| Recovery limit | 24 |

The 40-second optimise never emptied the queue before the deadline (`still_queued` 1, recoveries 0, deferred remaining 19). Recovery does not run while a line is still queued and the clock has not forced a stop.

## 5. Recovery policy

When a non-success stop finds the active queue empty, and the deadline, memory ceiling, and step ceiling have not been reached:

1. Record the stall audit once, on the first empty event.
2. If a planning stall left unplayed legal moves, seed those first. Seeding still runs only for `PLANNING_STALL`.
3. Otherwise take one eligible deferred line. Eligibility requires a legal pin if one is stored, a corrected g no worse than the stored ancestry, and a token that has not already been expanded.
4. If the line's label names a legal `move a b c`, pin that action. Columns are 1-based. The third number is the card count.
5. Install it through the existing queue and continue normal search.

The same token is held at most once, so recovery cannot cycle on it. A worse ancestry does not replace a cheaper exact state. Campaign labels are not treated as different physical states. Heuristic rejection stays `proof: false`.

The reconsideration limit is 24. Reaching it with deferred lines still stored is a reconsideration limit. It is not a proof that every legal continuation was searched. If nothing eligible remains, the stop is `PLANNING_STALL` with that audit text.

Named moves are recovered ahead of a bare label such as `STRETCH:create_workspace`.

## 6. Deep tactical budget policy

The production ladder is unchanged:

| Level | Max cost | Nodes | Ladder deadline |
| ---: | ---: | ---: | ---: |
| 2 | 4 | 160 | 0.28 s |
| 3 | 6 | 800 | 0.55 s |
| 4 | 8 | 4,500 | 1.25 s |

`deep_share` stays 0.15. A useful partial whose cover fell still climbs 160 to 800 inside the nonmonotone reserve of 3, on the ladder clock.

A clock stop is not an automatic climb. A zero-node `TIME_LIMIT` with no actions does not qualify. A blind `NODE_LIMIT` with no actions and no position evidence does not qualify. A `TIME_LIMIT` that produced an intermediate sequence, or the existing empty-column and buried-receiver evidence, can justify the next rung. Failure to reduce cover inside 800 nodes does not by itself forbid the reserved rung.

The reserved grant is separate from the 1.25-second ladder deadline. It asks for 4,500 nodes and a wall of `min(12s, remaining, remaining × deep_share)`, and only when that wall is at least 6.5 seconds. The proposal slice does not clip this wall back down. Node budget and wall clock are reported as separate numbers. At most two such grants are issued. After the reserve is spent, an 800-node hold can still be granted. A 40-second pilot has `0.15 × 40 = 6.0`, which is under 6.5, so that pilot does not emit a 4,500-node grant.

A stored `TIME_LIMIT` is keyed with its deadline. A larger node cap or a longer deadline is a different cache key. It is not a proof that the larger search fails.

## 7. Cache and dominance correctness

Exact-state dominance is unchanged. A higher corrected g for the same `canonical_state_key` is a transposition, `proof` true, and it is not placed in the deferred pool. A later cheaper visit drops the worse deferred copies of that state and clears their tokens so the cheaper token can be held.

Zero-cost MobilityWare moves are unchanged. Whole-column transfers onto an empty column with no face-down card in the source still cost 0, and that cost still participates in dominance.

Excavation cache lookup still requires the six-tuple identity for an exhaustive result. Timed failures use a seventh field, the rounded deadline. A result from one physical fingerprint is not reused on another. Workspace screening is unchanged: cap 0.08 seconds, two-move negatives are not proofs, and `realize_workspace` stays behind the screen.

Both timed pilots called the screen and did not call `realize_workspace` (`searched` 0).

## 8. Historical g83 divergence

Fixture `tests/fixtures/g83_4925153_actions.json`. 83 legal actions, corrected cost 83, spades then clubs, not a finished game. It is an audit. Cold search does not load it.

The cold run's reported 38-action line still shares the first 17 actions with the fixture. Action 18 is the split. The fixture deals. The reported line plays `move 7 8 1`.

That deal is generated. Of 49 retained branches, 31 play `deal` as action 18 and 15 play `move 7 8 1`. The reported line is the one with 26 face-down cards. The deal-following lines that were retained have at least 30 face-down cards, so the existing outcome rank keeps the 26-face-down line. This is a generated successor outranked on the reported trajectory. It is not a missing legal successor, and it is not a transposition. Frontier transpositions on this run are 0.

The longest shared prefix among retained cold branches is 23 actions, one past v0.121's longest retained prefix of 22. Both of those branches then play `move 10 2 1`. The fixture plays `move 8 10 1`. No retained branch removes the second foundation. The clubs removal at action 83 is not in the frontier.

The 40-second reported line does take the historical deal. It shares 22 actions with the fixture and then plays `move 10 4 1` where the fixture plays `move 4 2 1`. Its final position has 30 face-down cards, one same-suit run, 20 stock cards, and corrected g 34. That is a longer shared opening and a weaker end position than v0.121's reported g 38 line (26 face-down, three same-suit runs, 30 stock). The solver was not tuned to memorise the fixture.

## 9. Controlled 8H excavation

The production scheduling interface, on the legal g83 state, with a 90-second coordinator and the default ladder. The fixture actions were not injected into cold search. Artifact: `artifacts/human_strategy/v0_122/experiment_c_g83.json`.

The buried 8 of hearts is column index 6, cover 3.

| Stage | Nodes asked | Clock | Stop | Nodes used | Actions | Cover |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| Initial | 160 | 0.28 s | `TIME_LIMIT` | 120 | 2 | 3 → 3 |
| Intermediate | 800 | 0.55 s | `TIME_LIMIT` | 312 | 2 | 3 → 3 |
| Reserved deep | 4,500 | 12.00 s | exposed | 2,999 | 7 | 3 → 0 |

The intermediate sequence left the cover unchanged and was still eligible for the reserved rung. `deep_used` is 1. The nonmonotone reserve records 1 climb from 160 to 800. Level 4 was used once. Wall clock for the deep grant was 12.00 seconds. The search returned in 6.575 seconds, inside that wall, with 83.425 seconds of the 90-second coordinator left. Authoritative replay of the seven actions costs 7 and leaves cover 0. `replay_ok` is true.

This is the scheduler reaching the existing 4,500-node tier. It is not a hard-coded exception for the fixture, and it does not show that exposing 8H completes a foundation.

## 10. Standard 40-second comparison

Command in section 17. Deal 4925153. Mode `optimise`. Incumbent MW 185. Frontier 8. One worker.

| | v0.121 | v0.122 |
| --- | ---: | ---: |
| Status | `TIME_LIMIT` | `TIME_LIMIT` |
| Secondary | `PLANNING_STALL` | `PLANNING_STALL` |
| Deadline elapsed | yes | yes |
| Elapsed | 40.057 s | 40.031 s |
| Foundations | 1 | 1 |
| Corrected g | 38 | 34 |
| Actions | 38 | 34 |
| Deals | 2 | 3 |
| Face-down | 26 | 30 |
| Same-suit runs / longest | 3 / 2 | 1 / 2 |
| Empty columns | 0 | 0 |
| Stock cards | 30 | 20 |
| Unique strategic states | 168 | 147 |
| Peak RSS | 75.90 MB | 70.99 MB |
| Workspace searches | 1 in 0.082 s | 0 |
| Workspace screens | 218 | 171 in 0.741 s |
| Deepens to 800 | 5 | 4 |
| Reserved 4,500-node grants | 0 | 0 |
| Recoveries | 0 | 0 |
| Best verified | 185 | 185 |
| Improved | false | false |
| Cold injection | false | false |

`deep_used` is 0, as the 6.5-second floor requires. Screening still absorbs the workspace probes. The queue still held one line at the deadline, so recovery did not run.

The selected partial is not stronger than v0.121. Corrected g is lower because the line deals a third time. Face-down cards rose from 26 to 30 and same-suit runs fell from 3 to 1. Unique strategic states fell from 168 to 147. Those counts are not an improvement.

Safe whole-game prunes remain 0. A partial route did not replace the verified 185.

## 11. Independent 150-second cold experiment

Command in section 17. No incumbent. No fixture prefix. Target eight foundations.

The first empty event is the audit in section 3, at 42.978 seconds, with 22 eligible deferred lines and 107 seconds left. Recovery then ran.

| | v0.121 cold | v0.122 cold |
| --- | ---: | ---: |
| Reported status | `PLANNING_STALL` | `STEP_LIMIT` |
| Deadline elapsed | false | false |
| Elapsed | 40.684 s | 52.258 s |
| Coordinator time left | 109.316 s | 97.743 s |
| Foundations | 1 | 1 |
| Corrected g | 38 | 38 |
| Face-down | 26 | 26 |
| Same-suit runs / longest | 3 / 2 | 3 / 2 |
| Stock cards | 30 | 30 |
| Empty columns | 0 | 0 |
| Unique strategic states | 174 | 219 |
| Peak RSS | 79.04 MB | 88.31 MB |
| Still queued at the stop | 0 | 3 |
| Recoveries / distinct states | 0 / 0 | 8 / 5 |
| Reserved 4,500 grants | 0 | 2 |
| `best_verified_cost` | null | null |
| `cold_injection` | false | false |

Eight deferred lines were restored. Five were distinct physical states. Each named line that was legal was pinned and played, including `PARK:move 1 4 1`, `PARK:move 2 4 1`, `PREPARE:move 9 4 1`, and `PREPARE:move 2 4 1`. The search then stopped because `commits` reached `--max-steps 220`, with the reason `strategic step budget ended; still queued 3`.

Before this version's reporting fix, that step stop was replaced by an earlier branch's `PLANNING_STALL` when the reporter preferred the 26-face-down line. The step stop is now the search status. The reported trajectory is still that 38-action line, because its face-down count ranks ahead of the later lines.

Retained branches: 49, all `replay_ok`. Forty-one have one foundation (g from 22 to 58, face-down from 26 to 32). Eight have zero foundations (g from 11 to 37, face-down from 27 to 34). None has two foundations.

Tactical budget: 76,040 nodes granted, 20,522 used. Classifications: completed 90, exhausted within bound 569, resource-limited 49, progress 3, temporarily deferred 16. Deepens 8, of which 3 are the nonmonotone 160-to-800 climbs and 2 are reserved 4,500-node grants at a 12.00-second wall (`tableau:2:up:0` and `tableau:9:down:2`). Those grants returned early. They did not consume 24 seconds. Workspace screen 1.287 seconds, 301 screened, 0 searched. Foundation component 40.321 seconds. Excavation probe 26.509 seconds.

The extra time, about 12 seconds past v0.121, was spent on distinct recovered lines and on those two deep grants. About 98 seconds of the coordinator remained because the 220-commit ceiling stopped the run. That ceiling is the configured `--max-steps 220` from the pilot command. It is a commit budget, not evidence that the deferred lines are impossible.

The reported game did not move past one foundation or past g 38. The strong outcome, a partial that is strategically past the old g 38 stall and that uses a meaningful share of the leftover clock, was not met. The stretch outcome of two foundations was not met.

## 12. Complete incumbent verification

| Route | Mode | Limit | Elapsed | Status | Verified cost | Foundations | Rejoins | Windows | Inconclusive | Exhausted | Expansions | RSS MB |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MW 185 | adaptive, 1 region | 8 s | 1.986 | `NO_IMPROVEMENT` | 185 | 8 | 0 | 1 | 1 | 0 | 79 | 33.56 |
| MW 172 | fixed endpoint, 1 region | 6 s | 5.928 | `NO_IMPROVEMENT` | 172 | 8 | 0 | 16 | 5 | 11 | 1,809 | 33.89 |

Both solved. `improved` is false. `cold_injection` is false. `prefix_injected` is false. `production_registry_written` is false. The 185 smoke is `target_mode` `multi-checkpoint` and considered 16 targets. The 172 smoke is `fixed-endpoint`. Neither partial replaced either route. The production incumbent file was not written.

The 40-second optimise still reports best verified cost 185. MW 172 remains the strongest retained verified complete reference and was not installed as the autonomous incumbent. No new complete game was produced. No cost below 172 is claimed.

`optimise_anchored(..., mode="cold")` still raises `AnchoredRefused`. Exact-state checkpoint rejoin remains the anchored identity. Safe whole-game prunes on both pilots were 0.

## 13. Tests

Full regression, the v0.121 file list plus `tests/test_human_strategy_v0_122.py`:

**478 passed in 224.36 seconds.**

v0.121 was 452 passed in 228.52 seconds. v0.122 adds 26 tests in `tests/test_human_strategy_v0_122.py`. The new file covers deferred admission, one-at-a-time recovery, the recovery limit, cheaper-ancestry dominance, heuristic rejection versus proof, legal and illegal pins, stock deals, the 160 / 800 / 4,500 progression, cover that does not fall, deadline clipping, fairness across two deep grants, cache identity, `TIME_LIMIT` versus `PLANNING_STALL`, a step stop that is not relabelled as an earlier stall, the g83 fixture, cold independence, MW 185 and MW 172 verification, anchored refusal of cold mode, and the rule that a partial trajectory cannot replace a verified complete incumbent.

No 40-second or 150-second pilot runs inside pytest.

## 14. Runtime and memory

| Run | Elapsed | Peak RSS |
| --- | ---: | ---: |
| v0.122 40-second global | 40.031 s | 70.99 MB |
| v0.122 cold, step stop at 52.258 s of 150 | 52.258 s | 88.31 MB |
| g83 production schedule | 6.575 s | not a separate process RSS |
| Anchored 185 | 1.986 s | 33.56 MB |
| Anchored 172 | 5.928 s | 33.89 MB |
| Regression | 224.36 s | — |

The abort ceiling on the pilots is 3,072 MB. All of them stayed under it. Frontier capacity stayed 8.

## 15. Remaining limitations

The reported cold partial is still one foundation, corrected g 38, 26 face-down, 30 stock. Recovery and the two deep grants did not produce a second foundation.

The 220-commit ceiling stops the cold search while 3 lines are queued, 16 deferred candidates remain, and about 98 seconds are left. That is a configured step budget. It is not restricted-graph exhaustion, and the status is `STEP_LIMIT` for that reason.

The 40-second line that follows the historical deal further than v0.121 ends with more face-down cards and fewer same-suit runs. Outcome rank still prefers fewer face-down cards, so the cold report keeps the g 38 line. Heuristic progress measures are not admissible bounds.

A reserved 4,500-node search can return as soon as the graph hits the node cap. `deep_used` 2 is not 24 seconds of wall clock. The deep reserve stays at 2 so those probes cannot crowd out the frontier.

No new complete solution was found. The best verified complete cost on this deal remains 185 for the autonomous route. 172 remains the stronger verified complete reference.

## 16. Recommended next development

Let a cold run that still has queued lines or eligible deferred candidates continue until the global deadline, once the 220-commit ceiling is the only reason it would stop. Keep the frontier at 8, keep dominance, and do not treat the commit counter as a proof.

When several recovered lines are legal, prefer a line with better foundation and face-down structure over a line whose only advantage is a lower partial g. Keep that choice inside the existing outcome rank. Do not store the g83 moves as a cold prefix.

The 4,500-node grant is reachable. The next measurement is whether a recovered deal-following line, given the rest of the 150-second clock, can remove a second foundation. That has not been shown.

## 17. Reproduction

Interpreter `py -3`. Working directory: the repository root.

Regression:

```
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py tests/test_human_strategy_v0_119.py tests/test_human_strategy_v0_120.py tests/test_human_strategy_v0_121.py tests/test_human_strategy_v0_122.py -q --tb=line
```

40-second global:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_122/experiment_d_global.json
```

150-second cold:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_122/experiment_f_cold_150.json
```

Anchored smokes:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_autonomous_185.moves --adaptive --regions 1 --time-limit 8 --memory-mb 3072 --out artifacts/human_strategy/v0_122/experiment_e_anchored_185.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_canonical.moves --time-limit 6 --regions 1 --memory-mb 3072 --out artifacts/human_strategy/v0_122/experiment_e_anchored_172.json
```

## 18. Git status

Branch `local/frontier-recovery-v0-122` at `25072133f85162331e7c2af0abc42f12c9db36a3`.

```
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/search_budget.py
 M src/spider/human_strategy/strategic_frontier.py
 M tests/test_human_strategy_v0_117.py
 M tools/human_strategy_solver.py
?? tests/test_human_strategy_v0_122.py
?? docs/frontier_recovery_v0_122.md
```

`git diff --stat` before this document was added: 7 files, 488 insertions, 50 deletions. No commit.
