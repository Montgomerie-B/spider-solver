# Productive search v0.121

Schema `spider-human-strategy-0.121`. The controller still solves, then optimises. This release adds a legal-move screen in front of the short workspace search, lets a small reserve deepen an objective whose cover did not fall, and names a reached deadline as `TIME_LIMIT` when the policy has also stalled.

The 40-second pilot spent 0.082 seconds inside `realize_workspace`, down from 12.300 seconds. It reached 168 strategic states and still reported the same 38-action, one-foundation line as v0.120. Best verified complete cost remains 185. The 172 route remains valid and was not replaced.

## 1. Baseline and branch

Repository `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`.

| | |
| --- | --- |
| Starting commit | `6dd95244b96e79920b75ef1b7f4356832650a011` (`6dd9524 Add progressive strategic search budgeting v0.120`) |
| Parent | `bea9b10` v0.119 |
| Branch | `local/productive-search-v0-121` |
| Working tree | dirty, uncommitted |

The branch was created from a clean v0.120 HEAD. Nothing in this release was committed, pushed, merged, or opened as a pull request.

Files changed:

- `src/spider/planner/backward_strategy.py` — workspace screen, deadline clip, cache key
- `src/spider/human_strategy/search_budget.py` — nonmonotone reserve and decision log
- `src/spider/human_strategy/preparation.py` — `resolve_termination`
- `src/spider/human_strategy/controller.py` — deadline cause, progress, workspace counters
- `src/spider/human_strategy/foundation_direction.py` — install the workspace deadline; peel `workspace_screen`
- `src/spider/human_strategy/strategic_frontier.py` — `strategic_progress`
- `src/spider/human_strategy/__init__.py` — schema `spider-human-strategy-0.121`
- `tools/human_strategy_solver.py` — version label
- `tests/test_human_strategy_v0_117.py`, `tests/test_human_strategy_v0_119.py`, `tests/test_human_strategy_v0_120.py` — schema and screen assertions
- `tests/test_human_strategy_v0_121.py` — new
- `docs/productive_search_v0_121.md` — this report

`engine.py`, corrected MobilityWare scoring, `solutions/4925153_autonomous_185.moves`, `solutions/4925153_canonical.moves`, `solutions/4925153_incumbent.json`, the production incumbent registry, and Spider Play Lab were not modified. `anchored.py` and `search_kernel.py` were not modified. Cold mode does not load either completed route or the g83 fixture.

## 2. Reconciled v0.120 results

v0.120 measured the same 40-second command twice. The second run overwrote `artifacts/human_strategy/v0_120/experiment_d_global.json`. The two results stay separate. v0.121 compares against the later run only.

### Earlier ladder-only pilot

This run happened before `BudgetCoordinator` was registered. The artifact file was overwritten, so these figures live in the v0.120 session record and in `docs/strategic_budget_v0_120.md`. They are not a file that can be re-read.

| | |
| --- | ---: |
| Tests passing at that moment | 429 |
| Elapsed | 40.104 s |
| Status | `PLANNING_STALL` |
| Unique strategic states | 123 |
| States evaluated | 307 |
| Bounds | 380 |
| Foundation component | 31.673 s |
| Exclusive workspace planning | 11.263 s |
| Inclusive dependency planning | 9.431 s |
| Frontier lines explored | 29 |
| Reported partial g | 60 |
| Foundations on that line | 1 |
| Peak RSS | 64.95 MB |

429 is not the final v0.120 test count.

### Latest v0.120 configuration

This is the comparison baseline. Artifact: `artifacts/human_strategy/v0_120/experiment_d_global.json`. Tests: **441 passed in 236.25 seconds** (420 from v0.119 plus 21 in `tests/test_human_strategy_v0_120.py`).

| | |
| --- | ---: |
| Elapsed | 40.028 s |
| Status | `PLANNING_STALL` |
| `deadline_elapsed` | true |
| `resource_stops` | 0 |
| Unique strategic states | 152 |
| States evaluated | 276 |
| Bounds | 354 |
| Foundation component | 32.134 s |
| Exclusive workspace planning | 12.300 s |
| Exclusive excavation | 10.937 s |
| Exclusive foundation analysis | 4.374 s |
| Inclusive foundation analysis | 16.675 s |
| Inclusive dependency planning | 10.863 s |
| Workspace requests | 12 hits, 201 misses, 8 negative hits |
| Reported partial g | 38 |
| Foundations | 1 |
| Frontier generated / explored / still queued | 48 / 20 / 5 |
| Dropped because full | 35 |
| Deepened | 1 |
| Deferred | 16 |
| Identical probes skipped | 142 |
| Peak RSS | 72.64 MB |
| Best verified complete cost | 185 |
| `improved` | false |
| `cold_injection` | false |

One legal tableau move remained (`move 4 1 1`). The deadline had elapsed and the status stayed `PLANNING_STALL`. That is the discrepancy v0.121 corrects. Inclusive foundation analysis is exactly 4.374 + 12.300 + 0.001. Inclusive dependency (10.863) is not equal to the exclusive child sum (11.211). Those gaps stay as measured.

The reported line's probe lock (74 nodes, 14 level-2 probes) is that line only. The coordinator used 11,177 nodes. The two counts are not added.

## 3. Workspace call path

A foundation proposal calls `load_portfolio`. The controller stores three things on the foundation cache before that call: the 0.08-second probe cap, the probe cache, and the global `perf_counter` deadline. `load_portfolio` installs them as context variables for the duration of the portfolio build and then resets them.

`analyze_space_liquidity`, the post-deal probe, and the fill-then-deal probe all call `_cheap_workspace_cost`. Direct planner calls leave the context variables unset and keep the historical 0.35-second, 400-node probe.

The order inside `_cheap_workspace_cost` is:

1. Cache lookup. The key is the packed tableau, `max_cost`, the node cap, the time limit rounded to five decimals, and `deals=false`. A dealing search cannot reuse it. A different cost, node cap, or time limit is a different key.
2. If the global deadline has already passed, return an uncached `probe TIME_LIMIT`. That answer is not stored.
3. If `one_move_creates` is already true on a profiled column, return cost 1.
4. If an empty column already exists, return cost 0.
5. Otherwise run `_screen_workspace`.
6. Otherwise call `realize_workspace`. That call is the `workspace_planning` bucket. The 0.08-second cap maps to 91 nodes.

The screen uses `enumerate_moves` and `move(..., rules=MW_RULES)`. It does not invent a legality rule.

| Screen result | When it is returned | What the short probe does |
| --- | --- | --- |
| `no_legal_move` | No empty column and no legal tableau move | Skip the heavy search. Cached for this key. |
| `structural` | No empty column, and the minimum face-down count plus one exceeds `max_cost` | Skip the heavy search. A column with face-down cards cannot be emptied inside that cost while no column is empty. Cached for this key. |
| `legal_one_move` | One rules-engine move increases the empty-column count | Return that move's cost. |
| `legal_two_move` | One rules-engine move leaves a child with `one_move_creates` | Return that move's cost plus one. |
| `two_move_negative` | The two-ply scan finishes and finds no create | Skip `realize_workspace` only when the node cap is at most 120. The production 91-node probe qualifies. A 400-node probe still searches. The note says this is not a proof. |
| incomplete | The scan exceeds 0.025 seconds | Fall through to `realize_workspace`. |

A two-move negative is stored only under its own key. It is not reused for a larger node budget, a different `max_cost`, a different time limit, a different tableau, or a dealing probe. A positive answer is a move the rules engine accepted.

### Why the 0.08-second probes filled 12 seconds

On the v0.120 coordinator run, 201 first-time probes each ran the 91-node improved search and almost all of them returned `resource_limit` after about 0.08 seconds. The opening position's full legal ply is a fraction of a millisecond, and a two-ply scan of those seven moves finds no create in a few milliseconds. The heavy search was spending the cap without returning a workspace the screen can already see is absent at one and two moves.

### What the 40-second run did

| Workspace counter | v0.120 | v0.121 |
| --- | ---: | ---: |
| Misses | 201 | 221 |
| Hits | 12 | 12 |
| Negative hits | 8 | 7 |
| Screened | — | 218 |
| Searched with `realize_workspace` | 201 | 1 |
| `two_move_negative` | — | 162 |
| `legal_two_move` | — | 40 |
| `legal_one_move` | — | 0 |
| `structural` | — | 0 |
| `no_legal_move` | — | 0 |
| Exclusive `workspace_planning` | 12.300 s | 0.082 s |

The single search is the one probe whose screen did not finish inside the slice, or whose node budget was above the short-probe cutoff. Forty requests were answered by a real two-move create. One hundred sixty-two short probes took the negative screen and did not call the heavy search.

The 40-second artifact was written before the release step peeled `workspace_screen`, so that run's screen time sits inside exclusive `foundation_analysis` (6.937 seconds, up from 4.374). The cold run below uses the peel. It screened 233 requests, called `realize_workspace` zero times, and recorded 1.004 seconds of `workspace_screen`. Exclusive analysis on that run is 5.655 seconds, and inclusive analysis is 5.655 + 1.004 + 0.001 = 6.660.

The 40-second pilot screened 218 requests and searched once. Its heavy-search bucket is 0.082 seconds. The cold measurement puts a similar screen near one second. Even if the whole 2.563-second rise in exclusive analysis were screen time, workspace investigation on that pilot would be about 2.6 seconds. That is under the eight-second experimental target. The 0.082-second figure is the heavy search only.

## 4. Budget and cache

The production ladder is unchanged: 160 nodes and 0.28 seconds, then 800 nodes and 0.55 seconds, then 4,500 nodes and 1.25 seconds. The proposal slice stays 1.25 seconds. `deep_share` stays 0.15. Unscheduled callers still climb 2,000 nodes and 3 seconds, then 4,500 and 12 seconds.

What changed is who may take the next rung. A probe that reduced cover is still the first candidate, as in v0.120. A probe that did not reduce cover can join a second queue when `_nonmonotone_reason` returns a reason:

- The probe returned actions, and the target cover did not fall. The reason is that an intermediate sequence left the cover unchanged.
- The probe returned no actions, an empty column exists, and the position has a buried face-up receiver for the target or a same-suit descending pair of the target suit.

A `TIME_LIMIT`, an exhaustive miss, an already exposed card, and a bare node cap with no actions and no supporting position do not qualify. The reason allocates a reserve. It is not a proof the card can be reached.

The reserve allows three such deepens in one solve. Cover-reduction deepens do not consume it. `take_deepen` still yields when another strategic line is waiting and this proposal has not yet given those lines a cheap probe, when the global reserve is inside 0.05 seconds of empty, or when less than 0.2 seconds remain. One deepen is taken per proposal. Optional `detail` logging stays off on the pilots. The decision log keeps the last 24 reasons in the snapshot, and the event log records each deepen.

Workspace cache identity is the packed state plus cost, nodes, time limit, and `deals=false`. Excavation reuse is unchanged: an exact key hits, a successful plan can answer a wider ceiling when its cost still fits, and an exhaustive negative answers only a cost it already finished. The coordinator's excavation `cache_hits` stayed 0 on the 40-second run. Identical repeats are still stopped before lookup. That is the same residual as v0.120.

## 5. Nonmonotone excavation test

The fixture is built in `tests/test_human_strategy_v0_121.py` (`_parking_board`). The solver does not store its moves. The target is the 9 of clubs, covered by 8 of clubs and 7 of hearts. The 8 of diamonds that can receive the 7 is buried under the 2 of clubs. One column is empty. Four distinct kings are fully open, so the zero-cost cloud is large. Moving the mixed cover onto the only empty column does not expose the 9, and the next card has nowhere useful to go.

The production 0.28-second slice is shorter than this cloud. A 160-node search on it takes about 0.23 seconds and can stop on the clock. The test keeps the node caps at 160 and 800 and widens only that test's slice to 1.5 seconds and 3.0 seconds, so the node cap is what stops the first probe. The production ladder numbers are unchanged.

The test checks all of the following:

- The 160-node probe returns `NODE_LIMIT` and does not reduce cover.
- The justification string is non-empty.
- The scheduler then grants 800 nodes.
- That probe exposes the target.
- `nonmonotone_deepened` is 1, and the 4,500-node rung is unused.
- Elapsed time is under 8 seconds, and more than 15 seconds remain on a 30-second coordinator deadline.
- Replaying the returned actions on a fresh copy reproduces the cost and the final cover.
- The first action does not reduce cover.

A second test puts another objective in front of the queue. The hold waits. After that objective has had a turn, the same hold receives the 800-node grant. A connector board with no empty column and an action-less `NODE_LIMIT` does not enter the reserve.

## 6. Objective scheduling on the 40-second run

Deal 4925153, optimise under the verified 185, one worker, frontier 8, original deal, 40 seconds, portfolio off, memory abort 3,072 MB.

| | v0.120 coordinator | v0.121 |
| --- | ---: | ---: |
| Elapsed | 40.028 s | 40.057 s |
| Status | `PLANNING_STALL` | `TIME_LIMIT` |
| Secondary | deadline had elapsed, status stayed a stall | `PLANNING_STALL` |
| Unique strategic states | 152 | 168 |
| States evaluated | 276 | 322 |
| Bounds | 354 | 400 |
| Foundation component | 32.134 s | 30.327 s |
| Objectives attempted | 210 | 258 |
| Nodes granted / used | 36,000 / 11,177 | 42,560 / 13,808 |
| Deepened | 1 | 5 |
| Nonmonotone deepens | 0 | 3 |
| Deferred | 16 | 3 |
| Identical skips | 142 | 148 |
| Strategic holds left | — | 2 |
| Peak RSS | 72.64 MB | 75.90 MB |

The five deepens, all to 800 nodes and none to 4,500:

| Objective | Clock | Reason |
| --- | --- | --- |
| `tableau:1:up:0` | 0.55 s | intermediate sequence, cover unchanged |
| `tableau:2:up:0` | 0.55 s | cover fell on the previous allowance |
| `tableau:2:up:0` | 0.55 s | intermediate sequence, cover unchanged |
| `tableau:0:up:2` | 0.23 s | intermediate sequence, cover unchanged |
| `tableau:9:down:2` | 0.55 s | cover fell on the previous allowance |

After the reserve of three was spent, later requests for `tableau:9:down:2` were refused with "the nonmonotone reserve is spent". That objective had already received one 800-node probe because cover fell. It did not receive the 4,500-node rung. No single probe took the rest of the 40 seconds. The longest deepen clock in the log is 0.55 seconds.

Classifications, including replays and defers: completed 65, exhausted within bound 274, resource limited 42, progress 2, temporarily deferred 3. The search count is the 238 coordinator cache misses, not the 274 exhaustion count. Result-level cache hits were 87 and misses 188. Portfolio hits were 156 and misses 117.

The first committed objective is still `REVEAL excavate:r12:d1`. The one-ply cost-led action is still `deal`. The reported line's own probe lock is still 14 level-2 probes, 74 nodes, and no level-3 or level-4 probe. Those 74 nodes are not part of the 13,808.

## 7. Termination

`strategic_stop_status` is unchanged. It still returns `PLANNING_STALL` when a foundation goal has legal tableau moves and no proof that every continuation is exhausted. The unit test of that function still expects the stall.

`resolve_termination` runs after the frontier summary, once the loop has stopped. If `perf_counter` is past the deadline and the status is `PLANNING_STALL`, the cause becomes `TIME_LIMIT` and the stall is stored as `secondary`. The stop text keeps both. `resource_stops` increments because the cause is a budget stop. A stall that finishes before the deadline stays `PLANNING_STALL`. `GRAPH_EXHAUSTED_WITHIN_BOUND` is reported as `BOUNDED_EXHAUSTED`. A probe `NODE_LIMIT` stays `NODE_LIMIT`. Legal moves remaining are recorded and do not, by themselves, pick the cause.

The 40-second run:

| | |
| --- | --- |
| Cause | `TIME_LIMIT` |
| Secondary | `PLANNING_STALL` |
| `deadline_elapsed` | true |
| Legal tableau moves | 1 (`move 4 1 1`) |
| `budget_stop` | `TIME_LIMIT` |
| `resource_stops` | incremented |

v0.120 reported the same remaining move and `deadline_elapsed` true, with status `PLANNING_STALL` and `resource_stops` 0. The new run names the deadline as the cause. Campaigns entered were H#1, D#1, and C#1. S#2 was not entered. Feasibility was `SUSPENDED`. The nested workspace deadline is the same global clock, so a probe that starts after the deadline returns immediately and is not cached.

A controllable clock in the unit tests covers the mapping without a real sleep: deadline plus stall becomes `TIME_LIMIT` with secondary `PLANNING_STALL`; a stall before the deadline stays a stall; graph exhaustion becomes `BOUNDED_EXHAUSTED`; a node cap stays `NODE_LIMIT`.

## 8. Forty-second comparison

Command, both runs:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_121/experiment_d_global.json
```

The v0.120 file used the same flags and wrote `artifacts/human_strategy/v0_120/experiment_d_global.json`.

Stdout: `status=TIME_LIMIT mw=38 solved=False steps=258`, `BEST_VERIFIED=185`, `IMPROVED=false`, `unique_states=168`, `elapsed_s=40.057`, `peak_rss_mb=75.898`, `budget_nodes_used=13808 granted=42560 deferred=3 deepened=5 cache_hits=0 awaiting=33`.

### Time

| Bucket | v0.120 exclusive | v0.121 exclusive | v0.121 inclusive |
| --- | ---: | ---: | ---: |
| foundation component | 32.134 | 30.327 | — |
| foundation_analysis | 4.374 | 6.937 | 7.020 |
| workspace_planning | 12.300 | 0.082 | 0.082 |
| workspace_cache_lookup | 0.001 | 0.001 | 0.001 |
| tactical_realisation | 3.214 | 3.619 | 3.619 |
| feasibility_screen | 0.180 | 0.245 | 0.245 |
| cache_lookup | 0.005 | 0.007 | 0.007 |
| excavation_probe | 10.937 | 19.644 | 19.644 |
| dependency_planning | 0.089 | 0.119 | 17.413 |
| receiver_alignment | 2.052 | 1.836 | 1.836 |
| consequence_comparison | 0.000 | 0.000 | 0.000 |

Inclusive foundation analysis is 6.937 + 0.082 + 0.001 = 7.020. The screen time is inside the 6.937, as section 3 says. Inclusive dependency is 17.413 against an exclusive excavation of 19.644. That parent-and-child gap is the same kind of span mismatch v0.120 already had (10.863 inclusive against 11.211 of exclusive children). The buckets are not added together.

Exclusive foundation buckets sum to about 32.49 seconds. `component_s.foundation` is 30.327. The difference is the same post-proposal absorption gap as v0.120, where the exclusive sum was 33.152 and the component was 32.134. The two totals are not subtracted.

Other component seconds: bounds 0.027, candidates 1.514, apply 0.003, tactical 0.054, frontier dedup 0.006, evaluation 0.007, admission 0.006, compare 2.481, realise 0.694, replay 0.001. Inclusive execute is 0.752. The named component buckets are about 35.1 seconds of the 40.057.

### Position quality

The reported 38 actions are the same list as the v0.120 coordinator run, in the same order. Replay checks: cost 38, one foundation, 30 stock cards, not solved.

| Measure | Reported line |
| --- | ---: |
| Foundations | 1 |
| Face-down cards | 26 |
| Same-suit runs of length at least 2 | 3 |
| Longest of those runs | 2 |
| Empty columns | 0 |
| Stock cards | 30 |
| Corrected cost | 38 |
| Heuristic only | true |

`strategic_progress` records those measures and sets `heuristic_only`. They are not an admissible bound. S#1 was removed at cumulative g 33. The v0.114 cold line removed spades at g 19. This reported line is a more expensive route to one foundation.

Frontier, all 22 branches replay:

| Foundations | Lines | Minimum g | Maximum g | Minimum face-down |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 22 | 58 | 26 |
| 0 | 6 | 11 | 37 | 27 |

v0.120 retained 17 one-foundation lines, minimum g 22, minimum face-down 26, and 4 zero-foundation lines, minimum g 10. The cheapest one-foundation cost and the best face-down count on those lines did not improve. The extra states are additional visits, and the line the controller reports is the one it already had.

Generated 54, explored 21, dropped because full 35, same-move refusals 8, still queued 6, transpositions 0, merges 0, replaced 0. All 35 exclusions are heuristic admissions with `proof` false. `safe_prunes` is 0. Dominance discards are 0. A partial cost of 38, 22, or 11 is not a complete-game bound.

`best_verified_cost` is 185. `improved` is false. `incumbent_source` is `imported`. `cold_injection` is false. `adaptive` is false. `target_mode` is `global`.

The experimental workspace target, under eight seconds of first-time investigation, is met once the screen is counted with the 0.082-second search. The strong outcome, a better partial toward a second foundation inside 40 seconds, is not met. The reported position is the v0.120 position.

## 9. g83 diagnostic

Fixture `tests/fixtures/g83_4925153_actions.json`. It is replayed in tests and in this diagnostic. It is not loaded by cold search.

The 83 actions replay at corrected cost 83. Foundations come off as spades, then clubs. The position is not a finished game. Face-down cards at the end: 23. One column is empty. The buried 8 of hearts on column 7 (index 6) still has cover 3.

The reported 40-second line of both v0.120 and v0.121 shares the first 17 actions with this fixture. Action 18 is the split. The fixture deals. Both reported lines play `move 7 8 1`. The action lists of the two reported lines are equal for all 38 moves, so v0.121 did not move the reported choice.

Other retained branches do take that deal. v0.121 has nine branches whose 18th action is `deal`. The longest shared prefix with the fixture, among any retained branch, is 22 actions. The fixture's clubs removal at action 83 is not in the frontier. The controller still generates the deal alternative. It does not keep a line long enough, inside 40 seconds and frontier 8, to remove the second suit. Thirty-five lines were dropped because the frontier was full. Those drops have `proof` false.

Probes of the buried 8 of hearts from the fixture state, under the production clocks, all stop on time with cover still 3:

| Nodes asked | Clock | Status | Stop | Nodes expanded | Actions | Cover | Elapsed |
| ---: | ---: | --- | --- | ---: | ---: | --- | ---: |
| 160 | 0.28 s | progress | `TIME_LIMIT` | 120 | 2 | 3 → 3 | 0.329 s |
| 800 | 0.55 s | progress | `TIME_LIMIT` | 264 | 2 | 3 → 3 | 0.594 s |
| 4,500 | 1.25 s | progress | `TIME_LIMIT` | 576 | 2 | 3 → 3 | 1.299 s |

A `TIME_LIMIT` does not qualify for the nonmonotone reserve, so this position does not receive a larger rung after the 0.28-second probe. The clocks cut the search before the node caps. The same call with a 4,500-node cap and a 12-second deadline exposed the card at node 2,999, cost 7, seven actions, in 6.662 seconds. That search is outside the production 1.25-second clip, which had reached 576 nodes. The clip is a bounded miss. It does not show that the card is unreachable.

The unit test replays the 83 actions, runs one 160-node probe under a 3-second deadline, checks that cover does not fall, checks that the justification is non-empty, and checks that a zero-second cold solve with the full deal returns `TIME_LIMIT`, empty actions, `cold_injection` false, and `best_verified_cost` null.

## 10. Independent 150-second cold search

Command in section 14. No incumbent argument. The g83 file is not an input. Target eight foundations, so a second foundation would stay the best line and the search would continue. The profile time limit in the artifact is 150.0 seconds.

The search stopped at 40.684 seconds.

| | Cold 150 s | v0.114 reference |
| --- | ---: | ---: |
| Status | `PLANNING_STALL` | `FOUNDATION_TARGET_REACHED` |
| Cause | `PLANNING_STALL` | target 2 reached |
| `deadline_elapsed` | false | false (stopped on the target) |
| Elapsed | 40.684 s | 87.901 s |
| Budget left on the coordinator | 109.316 s | about 62 s |
| Foundations | 1 | 2 |
| Corrected g | 38 | 83 |
| Actions | 38 | 83 |
| Face-down | 26 | 23 |
| Stock cards | 30 | 0 |
| Deals | 2 | 5 |
| Unique strategic states | 174 | 92 |
| Peak RSS | 79.04 MB | 84.87 MB |
| `best_verified_cost` | null | not an incumbent |
| `incumbent_source` | `none` | none |
| `cold_injection` | false | `prefix_injected` false |
| Solved | false | false |

The v0.114 reference is the published cold result in `docs/frontier_bottleneck_v0_114.md`. It was not re-run. Its target was two foundations, and it stopped when clubs came off. This run's target was eight. The reported 38 actions are the same list as the 40-second optimise line. They are not the 172, the 185, or the g83 fixture.

Termination is a real stall. The frontier queue was empty (`still_queued` 0). Explored 27, generated 54, dropped because full 35, same-move refusals 12. One legal tableau move remained (`move 4 1 1`). Campaigns entered were H#1, D#1, and C#1. S#2 was not entered. Feasibility was `SUSPENDED`. Because the deadline had not elapsed, the cause stays `PLANNING_STALL` and `resource_stops` stays 0. That is the distinction section 7 describes.

The extra twenty seconds past the 40-second optimise explored six more branches. All 28 retained branches replay. Twenty have one foundation, minimum g 22, minimum face-down 26. Eight have zero foundations, minimum g 11. None has two foundations. S#1 still comes off at cumulative g 33. The nonmonotone reserve was spent (3 deepens). Three holds were still recorded when the queue emptied, and the line had already stalled, so they were not given the 4,500-node rung. `realize_workspace` was not called. `workspace_screen` is 1.004 seconds. Excavation is 19.243 seconds. Foundation component is 31.485 seconds. A bottleneck bucket of 1.153 seconds appears on this cold run.

The second-foundation capability from v0.114 was not recovered. The search had time left and no eligible frontier line left to run.

## 11. Incumbent integrity

The unit test replays both files from the opening. 185 ends solved, eight foundations, cost 185. 172 ends solved, cost 172. `optimise_anchored(..., mode="cold")` raises `AnchoredRefused`. A zero-second anchored call keeps the 185.

Bounded smokes, one region, no new complete game:

| Route | Mode | Limit | Elapsed | Status | Verified cost | Rejoins | Windows | Inconclusive | Exhausted | Expansions | RSS MB |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 185 | adaptive | 8 s | 1.488 | `NO_IMPROVEMENT` | 185 | 0 | 1 | 1 | 0 | 79 | 33.25 |
| 172 | fixed endpoint | 6 s | 5.408 | `NO_IMPROVEMENT` | 172 | 0 | 16 | 5 | 11 | 1,809 | 33.83 |

Both solved with eight foundations. `improved` is false. `cold_injection` is false. `prefix_injected` is false. `production_registry_written` is false. The 185 smoke is `target_mode` `multi-checkpoint` and considered 16 targets. The 172 smoke is `fixed-endpoint`. Neither partial replaced either route. The production incumbent file was not written. `anchored.py` was not edited.

## 12. Tests

The regression list from v0.120, plus `tests/test_human_strategy_v0_121.py`, passed **452 tests in 228.52 seconds** after the workspace-screen timing peel and the `screen_seconds` field. An earlier run of the same list, before that peel, passed 452 tests in 228.51 seconds. v0.120's final count was 441. The new file adds 11 tests.

`tests/test_human_strategy_v0_121.py` has 11 tests. They cover the 18 requested checks:

1. Cheap screening, and a two-move create that the rules engine accepts, without calling `realize_workspace`.
2. The same two-move path is the legal-move check.
3. A repeated identical request is a cache hit.
4. A different packed state is a miss. A no-move board and a structural bound are cached only for their own key.
5. A different `max_cost` is a different key. A two-move negative at 91 nodes does not answer a 400-node budget, which still calls `realize_workspace`.
6. The second identical short probe does not search again.
7. A cover reduction still deepens, and a bare node cap with no supporting position does not.
8. The parking-board probe deepens with no immediate cover reduction.
9. The first action of that expose does not reduce cover, and the replayed sequence does.
10. A deferred hold is the objective granted once the other line has run.
11. `alternatives_waiting` blocks the deepen, then a clear queue allows it.
12. An expired workspace deadline returns `TIME_LIMIT` and does not cache it. Nested probes see the global deadline.
13. `resolve_termination` separates `TIME_LIMIT`, `PLANNING_STALL`, `NODE_LIMIT`, and `BOUNDED_EXHAUSTED` on a controllable clock.
14. A more expensive visit of the same canonical state is dominance with `proof` true. `strategic_progress` is marked heuristic only.
15. The g83 prefix replays to spades then clubs.
16. A cold solve does not import those actions.
17. Both completed routes verify, and a partial is not written over them.
18. The 185 replay ends solved with eight foundations.

No 40-second or 150-second pilot runs inside pytest.

## 13. Peak RSS

| Run | Peak RSS |
| --- | ---: |
| v0.121 40-second global | 75.90 MB |
| v0.120 40-second global | 72.64 MB |
| v0.121 cold, stopped at 40.684 s of 150 | 79.04 MB |
| Anchored 185 smoke | 33.25 MB |
| Anchored 172 smoke | 33.83 MB |

The abort ceiling on the pilots is 3,072 MB. All five stayed under it.

## 14. Reproduction

Interpreter `py -3`. Working directory: the repository root.

Regression:

```
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py tests/test_human_strategy_v0_119.py tests/test_human_strategy_v0_120.py tests/test_human_strategy_v0_121.py -q --tb=line
```

40-second global: the command in section 8.

150-second cold:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 8 --time-limit 150 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_121/experiment_f_cold_150.json
```

Anchored smokes, after the cold run:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_autonomous_185.moves --adaptive --regions 1 --time-limit 8 --memory-mb 3072 --out artifacts/human_strategy/v0_121/experiment_e_anchored_185.json
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_canonical.moves --time-limit 6 --regions 1 --memory-mb 3072 --out artifacts/human_strategy/v0_121/experiment_e_anchored_172.json
```

## 15. Outstanding weaknesses

The reported 40-second line did not change. Extra strategic states did not become a second foundation or a lower face-down count on the best retained one-foundation line.

The time removed from `realize_workspace` went into excavation. Exclusive excavation rose from 10.937 seconds to 19.644 seconds. Foundation component time fell only from 32.134 seconds to 30.327 seconds. The 25-second foundation target from v0.120 is still missed.

The g83 buried 8 of hearts is cut by the 0.28-second clock at 120 nodes, and a clock stop does not qualify for a deepen. The production 1.25-second deep clip expands 576 nodes and leaves the cover at 3. The same function with a 12-second deadline exposes the card at node 2,999 in 6.662 seconds. Frontier capacity eight still drops lines with `proof` false, including lines that share a longer prefix with the historical two-foundation route.

The nonmonotone reserve is three deepens per solve. It was exhausted, and `tableau:9:down:2` was then refused. The 4,500-node rung stayed idle. Excavation cache hits stayed 0 because identical repeats are skipped before lookup. There is still no resume of a previous excavation frontier. `safe_prunes` is 0. Heuristic progress is not an admissible bound.

Screen time on the 40-second artifact sits inside exclusive foundation analysis. The cold run peels it: 1.004 seconds for 233 screens and zero calls to `realize_workspace`. A two-move negative is not a proof, and a short probe that skips the 91-node search can miss a create that search would have found. On the v0.120 sample those searches were returning `resource_limit`. The 40-second run searched once. The cold run searched zero times.

The cold frontier emptied with 109 seconds left. Dropped lines are not recalled. Holds left after the reserve is spent are not restarted as 4,500-node searches. That is why a 150-second budget ended at 40.684 seconds with one foundation.

## 16. Recommended v0.122 work

Resume a timed-out excavation from the nodes it already expanded. The g83 8 of hearts shows the size of that gap: the production clocks stop at 120, 264, and 576 nodes, and a 12-second call on the same function exposes the card at node 2,999. The policy is right to refuse a blind second start after `TIME_LIMIT`. A resume would spend the leftover deadline on the graph already built.

When the frontier queue is empty and the global clock has a large remainder, recall a limited number of heuristic drops (`proof` false) instead of returning `PLANNING_STALL`. The cold run left 109 seconds unused after dropping 35 lines. Widening the beam from eight is a different change and is not the recommendation.

Keep the screen and the peeled `workspace_screen` bucket. Keep the reserve small. The 4,500-node rung can stay idle until a resumed probe, rather than a fresh cap, has already shown cover progress.

A new complete game below 172 is still the long-term target. It needs a second foundation on a cold line first. This release did not produce one.

## 17. Git status

Branch `local/productive-search-v0-121` at `6dd9524`. Not committed.

```
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/preparation.py
 M src/spider/human_strategy/search_budget.py
 M src/spider/human_strategy/strategic_frontier.py
 M src/spider/planner/backward_strategy.py
 M tests/test_human_strategy_v0_117.py
 M tests/test_human_strategy_v0_119.py
 M tests/test_human_strategy_v0_120.py
 M tools/human_strategy_solver.py
?? docs/productive_search_v0_121.md
?? tests/test_human_strategy_v0_121.py
```

Pilot JSON under `artifacts/human_strategy/v0_121/` is gitignored, same as the earlier artifact directories. No commit, push, merge, or pull request.
