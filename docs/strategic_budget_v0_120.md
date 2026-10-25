# Strategic search scheduling v0.120

Schema `spider-human-strategy-0.120`. The controller now decides, for each tactical objective, whether to search once at a small allowance, defer, replay a result already proved for that state, or spend one larger allowance. A nested probe cannot outlive the global deadline.

This release did not produce a new complete game. Deal 4925153 still has best verified complete cost **185** on `solutions/4925153_autonomous_185.moves`. The separate canonical file remains **172**. Both were replayed again. The 40-second global pilot still finishes with one foundation. Its chosen partial, corrected cost 38, is not an incumbent. The frontier still holds a one-foundation line at corrected cost 22, the same minimum retained in v0.119. Safe whole-game prunes remain 0.

## 1. Branch, HEAD, and Git status

Branch `local/strategic-budget-v0-120`. HEAD `bea9b10af184f5c72e2a94d6d7ef106c9e75cb3d` (`Add adaptive checkpoint optimisation v0.119`). The v0.120 edits are uncommitted. Nothing was committed, pushed, merged, or opened as a pull request.

`git status --short` after the coordinator run:

```
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M src/spider/human_strategy/strategic_frontier.py
 M src/spider/planner/backward_strategy.py
 M tests/test_human_strategy_v0_117.py
 M tools/human_strategy_solver.py
?? docs/strategic_budget_v0_120.md
?? src/spider/human_strategy/search_budget.py
?? tests/test_human_strategy_v0_120.py
```

`docs/adaptive_checkpoint_v0_119.md` still names HEAD `4be30e1`. That note was written before the v0.119 commit. This file does not rewrite it. The committed v0.119 tree is `bea9b10`.

Untouched: `engine.py`, `rules.py`, corrected MobilityWare scoring, `solutions/4925153_autonomous_185.moves`, `solutions/4925153_canonical.moves`, `solutions/4925153_incumbent.json`, historical campaign data, Spider Play Lab, `anchored.py`, and `search_kernel.py`. Frontier capacity stays at 8. The 2,500 unique cap, the 4,500-node excavation capability, and the 0.08-second workspace probe are unchanged.

Artifacts under `artifacts/human_strategy/v0_120/` are gitignored. `experiment_d_global.json` is the coordinator run. An earlier ladder-only pilot used that same path and was replaced by this run. Its figures below are the measurements taken before the coordinator was registered.

## 2. Baseline call path

v0.119 (`artifacts/human_strategy/v0_119/experiment_d_global.json`) ran the same 40-second command: deal 4925153, one worker, frontier 8, optimise under the verified 185 ceiling. It stopped `PLANNING_STALL` at 40.187 seconds with `deadline_elapsed` true and `resource_stops` 0. Foundation proposals took 37.299 seconds. The reported line's excavation lock holds 28,903 nodes (48 misses, 10 hits, 43 inconclusive, 6 expansions). Unique strategic states were 75. Evaluations were 111. One foundation. Reported partial g=50. Peak RSS 139.39 MB.

The elapsed-path event log is a different view from that lock. It has 25 announcements and 30,625 nodes actually expanded. Twelve of those announcements are the second, 4,500-node search of a probe that had already returned. Two of those graphs were already exhausted at 48 nodes, and the expansion searched them again. Ah, Jh, 9h, and 6h did reduce cover further, and two of those searches used the full 4,500 nodes. The rule was: an inconclusive result for its own ceiling, including a bare `NODE_LIMIT` with no moves and an exhaustive miss below cost 8, jumped to 4,500 nodes and 12 seconds.

| Elapsed-path probe | Nodes used | Result |
| --- | ---: | --- |
| Qh, first tier | 39 | unlocked |
| 4h, then the 4,500 expansion | 48, then 48 | graph already exhausted |
| Qh, then the 4,500 expansion | 48, then 48 | graph already exhausted |
| 7h, then the expansion | 162, then 347 | progress, then `PROBE_LIMIT` |
| Jh, then the expansion | 271, then 1,151 | progress at both caps |
| Ah, then the expansion | 1,125, then 4,500 | progress, full cap on the expansion |
| Jh, then the expansion | 1,125, then 4,500 | progress, full cap on the expansion |
| Jh `NODE_LIMIT`, then the expansion | 2,000, then 4,500 | the larger cap found progress |
| 9h `NODE_LIMIT`, then the expansion | 2,000, then 4,500 | the larger cap found progress |
| Kh, then the expansion | 479, then 730 | exhausted at both caps |
| 6h, then the expansion | 435, then 638 | progress at both caps |

Direct callers that do not register a budget still use those historical sizes: 2,000 nodes and 3 seconds, then a justified 4,500 and 12 seconds. `plan_obstructed_access` itself is unchanged. g83 can still ask for 4,500 nodes. The controller is what stopped issuing that jump on every inconclusive result.

## 3. Search time attribution

The coordinator's 40-second run elapsed 40.028 seconds and stopped `PLANNING_STALL` with `deadline_elapsed` true and `resource_stops` 0. One legal tableau move remained (`move 4 1 1`). Campaigns entered were H#1, D#1, and C#1. S#2 was not entered. Feasibility was `SUSPENDED`. The stop text includes "a probe limit is not infeasibility".

`component_s` is exclusive wall clock. `component_inclusive.execute` is the whole `_execute` call. v0.119 stored that whole call in `component_s.tactical`.

| Bucket | Seconds |
| --- | ---: |
| bounds | 0.014 |
| candidates | 1.138 |
| foundation | 32.134 |
| apply | 0.002 |
| tactical (the part of `_execute` outside apply and realise) | 0.019 |
| frontier dedup | 0.004 |
| frontier evaluation | 0.004 |
| frontier admission | 0.004 |
| compare | 2.893 |
| realise | 0.767 |
| replay | 0.000 |
| inclusive execute | 0.788 |
| inclusive frontier | 0.012 |

Realise 0.767 + apply 0.002 + tactical 0.019 = 0.788, the inclusive execute total. The named component buckets sum to 36.979 seconds. About 3.05 seconds of the 40.028 sit outside those buckets.

Exclusive foundation timing, and the inclusive parent totals:

| Bucket | Exclusive | Inclusive |
| --- | ---: | ---: |
| foundation_analysis | 4.374 | 16.675 |
| workspace_planning | 12.300 | 12.300 |
| workspace_cache_lookup | 0.001 | 0.001 |
| tactical_realisation | 3.214 | 3.214 |
| feasibility_screen | 0.180 | 0.180 |
| cache_lookup | 0.005 | 0.005 |
| excavation_probe | 10.937 | 10.937 |
| dependency_planning | 0.089 | 10.863 |
| receiver_alignment | 2.052 | 2.052 |
| consequence_comparison | 0.000 | 0.000 |

`foundation_analysis` inclusive is exactly 4.374 + 12.300 + 0.001 = 16.675. Workspace planning is removed from the exclusive analysis bucket and kept in the inclusive one.

The exclusive sum of `dependency_planning`, `excavation_probe`, `feasibility_screen`, and `cache_lookup` is 11.211. Inclusive `dependency_planning` is 10.863. The 0.348 second difference is screen, cache, and excavation time recorded outside that parent span. Those exclusive buckets are run-wide. They are not added to the inclusive parent.

Exclusive foundation buckets sum to 33.152 seconds. `component_s.foundation` is 32.134. The 1.018 second difference is timing absorbed by recovery after the proposal charge, the same accounting gap measured on the ladder-only pilot. Resume is inside the foundation charge and also inside the timing buckets. The two totals are not subtracted from each other.

v0.119's `foundation_analysis` of 6.682 seconds included workspace. v0.119's `dependency_planning` of 27.335 seconds included excavation. The comparable figures are inclusive analysis 16.675 against that 6.682, and inclusive dependency 10.863 against that 27.335. Analysis rose because more distinct states were analysed. Dependency fell because the 4,500-node expansions stopped.

## 4. Previous versus new scheduling policy

Three measurements, same deal, one worker, frontier 8, 40-second budget, optimise under the verified 185 ceiling.

| | v0.119 | Ladder only, before the coordinator | Coordinator |
| --- | ---: | ---: | ---: |
| Elapsed | 40.187 | 40.104 | 40.028 |
| Status | PLANNING_STALL | PLANNING_STALL | PLANNING_STALL |
| Foundation component | 37.299 | 31.673 | 32.134 |
| Unique strategic states | 75 | 123 | 152 |
| States evaluated | 111 | 307 | 276 |
| Bounds | 138 | 380 | 354 |
| One-foundation lines, minimum g | 22 | 22 | 22 |
| Reported partial g | 50 | 60 | 38 |
| Foundations on that line | 1 | 1 | 1 |
| Best verified complete cost | 185 | 185 | 185 |
| Safe prunes | 0 | 0 | 0 |
| Heuristic exclusions | 9 | 11 | 35 |
| Peak RSS, MB | 139.39 | 64.95 | 72.64 |
| Deals | 3 | 4 | 2 |
| Result-cache hits / misses | 19 / 65 | 97 / 180 | 59 / 180 |
| Portfolio hits / misses | 43 / 47 | 206 / 92 | 123 / 113 |
| Workspace hits / misses | 3 / 81 | 5 / 171 | 12 / 201 |

The ladder, before the coordinator existed, is what removed the automatic 4,500-node jump. Foundation time moved from 37.299 to 31.673 seconds on that pilot, and unique states moved from 75 to 123. The coordinator run keeps foundation time at 32.134 seconds and moves unique states from 123 to 152. States evaluated fell from 307 to 276. The extra states are new identities, not extra visits to the same ones.

The 25-second foundation target was not met. 32.134 / 40.028 is 80 percent of the run, down from 37.299 / 40.187 (93 percent) in v0.119. The largest exclusive bucket is still workspace planning at 12.300 seconds: 201 first-time probes at the unchanged 0.08-second cap. Excavation is the next bucket at 10.937 seconds. Cutting either one by suppressing legal foundation work would change the comparison, so it was not done.

## 5. Progressive budget design

The allowances are `TacticalLimits` on the coordinator. The defaults come from the v0.119 measurements and are replaceable. The CLI passes a custom ladder only when `--proposal-slice`, `--first-nodes`, `--first-seconds`, `--deep-nodes`, or `--deep-seconds` is set. Omitted flags keep the defaults. The middle step stays 800 nodes and 0.55 seconds unless the caller changes the object in code. Provenance `tactical_schedule.levels` and `budget.limits` both report the ladder that ran.

| Level | What it does | Default |
| --- | --- | --- |
| 1 | Screen only: absent card, legally movable head, already exposed, no legal tableau move | no search |
| 2 | First search | cost 4, 160 nodes, 0.28s |
| 3 | One deepen after cover fell inside the node budget | cost 6, 800 nodes, 0.55s |
| 4 | One further deepen on the same evidence | cost 8, 4,500 nodes, 1.25s |

Derivation, stored on the run: the first cap is three times the 48-node exhausted graphs, and 0.28 seconds is the 2,000-node/3-second probe scaled down with a little interpreter room. The middle cap sits under the partials that were still reducing cover below 1,151 nodes, with 0.55 seconds so two such probes fit in the 1.25-second proposal slice. The deep cap keeps the existing 4,500-node capability. Its deadline is the proposal slice, and `deep_share` 0.15 also caps it at 15 percent of the global time still left. `reserve_s` 1.25 refuses a deepen when less than that, plus 0.05 seconds, remains.

A registered coordinator grants one allowance and returns. After the other targets in that proposal have had a cheap look, it may take one deepen. A second deepen waits for a later proposal. The deepen is refused when another strategic line is queued and this proposal has not yet given those lines a turn, when the reserve is gone, or when the caller has under 0.2 seconds. A completed unlock or expose sets a viable alternative and blocks the deepen. A useful partial that is blocked stays on `open_partials` and stays eligible. A bare `NODE_LIMIT` with no moves, a `TIME_LIMIT`, and an exhaustive miss are not that evidence.

`clip` takes the minimum of the configured deadline, the caller `time_left`, and the global time remaining. A deepen also takes 15 percent of the global remainder. The one deepen in the 40-second run was `tableau:2:down:0` to 800 nodes with 0.31 seconds, under both the 0.55-second step and the 1.25-second slice. The event log shows 37 announcements at a 160-node cap, one at 800, and none at 4,500. Nine announcements are zero-node screens or defers.

Unscheduled callers still climb 160, then 800, then 4,500 inside one call when cover falls. `test_progressive_search_starts_small_and_climbs_only_when_cover_falls` covers that path. The controller path does not.

Classifications on a finished probe:

| Class | Meaning |
| --- | --- |
| `completed` | unlocked or exposed |
| `progress` | cover fell, and the clock did not stop the probe |
| `resource_limited` | `NODE_LIMIT`, `TIME_LIMIT`, or `PROBE_LIMIT` |
| `exhausted_within_bound` | the bounded graph was finished for this cost and policy |
| `proved_impossible` | the card is not on the tableau |
| `temporarily_deferred` | eligible later, not searched again under the same allowance |

A `NODE_LIMIT` is `resource_limited`. The 40-second run recorded `proved_impossible` zero times.

## 6. Cache correctness

An excavation result is stored under the tableau fingerprint (column suit and rank, stock length, foundation count), the source card, `allow_deals`, max cost, max nodes, and strategy. `allow_deals` true replaces the stock length with the stock's suit and rank sequence. A `TIME_LIMIT` is stored on that key plus the effective deadline rounded to 0.01 seconds. Lookup reads 6-tuples only, so a timed entry does not answer a different deadline.

Reuse:

- Exact key: reuse.
- `SUCCESS` whose corrected cost fits the requested ceiling, and whose stored cost is within that ceiling: reuse.
- Exhaustive miss with no actions, only when the stored cost is at least the requested cost: reuse.
- `NODE_LIMIT`, `TIME_LIMIT`, and a partial: do not answer a larger or different probe.
- A changed board changes the fingerprint. A changed deal policy changes `allow_deals` and, when deals are allowed, the stock identity.

The 40-second coordinator counters:

| Counter | Value |
| --- | ---: |
| Excavation cache hits | 0 |
| Excavation cache misses | 221 |
| Nodes saved by excavation hits | 0 |
| Hits by result type | none |
| Refused reuse | 1 |
| Larger-budget re-probes | 1 |
| Identical skips before search | 142 |
| Foundation proposals skipped at an equal cost | 19 |
| Portfolio hits / misses | 123 / 113 |
| Objective result-cache hits / misses | 59 / 180 |
| Workspace hits / misses / negative hits | 12 / 201 / 8 |

The 142 identical skips are the duplicate work that was avoided. An exhausted result was replayed, or an unchanged `NODE_LIMIT` was deferred, without calling the search. Those requests never reached the excavation cache, which is why the cache hit count is 0 and nodes saved is 0. The skipped searches were not measured, so this report does not convert 142 skips into a node total. One stored entry was refused for a different allowance, and one larger re-probe ran. That is the smaller-budget result leaving the larger investigation eligible.

There is no persistent frontier resume. A later probe on a changed board is a new record. A later probe on the same board at a larger node cap is a new search, taken through `take_deepen`, not through the old key.

## 7. Frontier diversity

`StrategicFrontier.consider` computes `canonical_state_key` before it builds a node. The same identity, label, and forced candidate already queued or expanded is returned immediately. A more expensive ancestry of the same identity is `transposition_dominance` with `proof` true, and the cheaper ancestry is kept. A later cheaper ancestry drops the queued worse nodes. Different physical states are separate keys. A full frontier of eight records `heuristic_admission` with `proof` false. Dropping a duplicate signature to make room uses the same non-proof exclusion.

Campaign labels are not physical states. The proposal skip token is the canonical identity, the campaign label, and the blocked-candidate tuple. An equal or higher g skips the foundation rebuild. A cheaper g does not. An open partial disables the skip so the deferred objective can return.

On this 40-second run the frontier did not record a transposition. `transpositions` 0, `merges` 0, `replaced` 0, `dominance` 0. The cheaper-ancestry path is tested and did not fire here: no costlier line arrived before a cheaper one of the same state. What did fire:

| Frontier field | Value |
| --- | ---: |
| Limit | 8 |
| Generated | 48 |
| Explored | 20 |
| Dropped because full | 35 |
| Same-move histories | 13 |
| Still queued | 5 |
| Exclusion overflow | 0 |
| Branches retained in the report | 21 |
| Replay-checked | 21 of 21 |

All 35 exclusions are `heuristic_admission` with `proof` false. 23 have `equivalent_retained` true. 12 do not. Heuristic rejection is incompleteness. The report's branches: 17 with one foundation, minimum corrected cost 22, maximum 51; 4 with zero foundations, minimum corrected cost 10.

`physical_duplicates` on the budget is 19. Those are foundation proposals skipped for an authoritative state and objective already evaluated at that cost. They are counted before `propose_foundation_step`, which is the expensive evaluation the frontier dedup is meant to avoid repeating.

Distinct strategic states explored: `unique_states` 152, which is `len(best_g)`. The coordinator separately saw 78 authoritative states inside tactical probes and 59 tactical objectives. Those are not added to the 152. Strategic identities and excavation nodes are different sets. The note in provenance says so.

## 8. Real 40-second comparison

Command, both for the ladder-only pilot and for this coordinator run:

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_120/experiment_d_global.json
```

Coordinator stdout: `status=PLANNING_STALL mw=38 solved=False steps=210`, `BEST_VERIFIED=185`, `IMPROVED=false`, `unique_states=152`, `elapsed_s=40.028`, `peak_rss_mb=72.641`, `budget_nodes_used=11177 granted=36000 deferred=16 deepened=1 cache_hits=0 awaiting=31`.

The first committed objective was `REVEAL excavate:r12:d1`. The cost-led action at the opening is `deal`. The chosen line ended on S#1, partial, one foundation, corrected cost 38.

Run-wide tactical accounting is the coordinator snapshot. The reported line's `excavation_probe_stats` is only that line's restored lock: 14 level-2 probes, 0 level-3, 0 level-4, 74 nodes, 7 completed, 7 inconclusive. The coordinator's 11,177 nodes used are every probe in the run, including lines that were not the one reported at the end. The event log's 47 announcements expanded 2,422 nodes. Those three figures are three views. They are not subtracted.

Granted 36,000 against 11,177 used means the searches returned before the node cap on average. One objective, `tableau:6:up:3`, accounts for 1,314 of the used nodes across 15 visits. The single deepen is visible in the log and used a 0.31-second clock, so it did not spend the global remainder.

## 9. Tactical work saved or deferred

| Decision | Count |
| --- | ---: |
| Cache misses that searched | 221 |
| Identical state and objective skipped before search | 142 |
| Deferred because the allowance and the board were unchanged | 16 |
| Deepened once | 1 |
| Revisited through that deepen | 1 |
| Awaiting a later look (`resource_limited`, `progress`, or deferred records) | 31 |
| Alternative lines queued at the stop | 5 |
| Objectives that received tactical work | 59 |

Classification decisions, including replays and defers, were `completed` 52, `exhausted_within_bound` 263, `resource_limited` 31, `temporarily_deferred` 16, `progress` 1. The 263 figure counts each replay of an exhausted result as well as the search that produced it. It is not 263 separate proofs and not 263 searches. The search count is the 221 cache misses.

The live log shows the scheduling the tests describe. `tableau:1:up:0` and `tableau:3:up:3` were deferred on an unchanged board at 160 nodes, with the text that they stay eligible when the board or the allowance changes. Later, `tableau:2:down:0` was deepened. `tableau:0:up:2` was deferred seven times in the event log rather than searched again at the same cap. Other objectives continued to receive first-level probes. The 6-second unit solve on the same deal, `test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`, sees the same pattern with the deep cap idle: several objectives, identical skips, and a later visit after the board has changed.

## 10. Strategic states and outcomes

152 distinct strategic states in 40.028 seconds is 3.80 states per second. v0.119 reached 75 in 40.187 seconds, 1.87 per second. Evaluations were 276. Bounds were 354. Objectives attempted 210. The run dealt twice.

The search did not complete a second foundation. The chosen line has one foundation at corrected cost 38. Seventeen retained branches have one foundation. The cheapest of those is 22. Four retained branches have zero foundations. The cheapest of those is 10. All 21 reported branches replay. None of these costs is a complete game. Best verified complete cost remains 185. `improved` is false. `incumbent_source` is `imported`. `adaptive` is false. `target_mode` is `global`. `cold_injection` is false.

`PLANNING_STALL` is the status because legal tableau moves remained when the policy stopped. `TIME_LIMIT` is recorded when the loop header, or the play-goal kernel, sees the deadline. This run's header did not take that branch. `deadline_elapsed` is true, and `resource_stops` is 0. A zero-second solve in the unit tests does report `TIME_LIMIT`, so the two statuses stay distinct.

## 11. Matched-horizon anchored comparison

Constructed fixture from v0.119: seven foundations, the heart run on column 0, the king on column 1. The 12-action route costs 3. Checkpoint 11 is the state after 11 actions, original segment cost 2. The paid return sits at span 11. Both searches below include that checkpoint, with the same 3-second limit and the same 1,500 unique-state cap.

| Search | Status | Cost | Expanded | Unique | Target |
| --- | --- | ---: | ---: | ---: | --- |
| Fixed `search_segment` to checkpoint 11 | FOUND | 0 | 1 | 12 | checkpoint 11 |
| Adaptive `search_targets` over checkpoints 1 through 11 | FOUND | 0 | 1 | 13 | 11 |

Both found the shortcut. The costs are equal. Adaptive search considered 11 targets and expanded one node, the same number of expansions as the fixed search. The advantage on this fixture is the shared horizon, which now includes checkpoint 11 for both. It is not an advantage of searching several targets. The older fixed windows with `max_span` 8 never select checkpoint 11. That remains a window-selection fact from v0.119, and it is not reused here as a multi-target result.

`anchored.py` was not modified.

## 12. Cold solve

```
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 8 --time-limit 15 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 120 --memory-mb 3072 --out artifacts/human_strategy/v0_120/experiment_f_cold.json
```

No incumbent argument. Result: `PLANNING_STALL`, solved false, one foundation, reported partial g=48, elapsed 15.019 seconds, 68 unique strategic states, 85 evaluations, peak RSS 51.12 MB. `best_verified_cost` is null. `incumbent_source` is `none`. `cold_injection` is false. `adaptive` is false. `target_mode` is `global`.

Campaigns entered were D#1, H#1, and C#1. S#2 was not entered. Feasibility was `PROBE_LIMIT`. Nine legal tableau moves remained. The coordinator granted 12,480 nodes, used 3,802, deferred 4, deepened 0, and skipped 17 identical probes. Foundation component time was 12.848 seconds, of which workspace planning was 6.190 and excavation was 2.812.

The cold pilot reaches one foundation and does not reach a second. The post-Spades stall is still where this budget stops. Provenance does not import the 172 or the 185.

## 13. MW 185 and MW 172

`verify_complete_solution` replayed both files on the deal opening during the unit test. 185 replays at cost 185 with eight foundations. 172 replays at cost 172 with eight foundations.

Bounded anchored smokes, without asking for a new complete game:

| Route | Mode | Time limit | Elapsed | Status | Verified cost | Rejoins | Windows | Inconclusive | Exhausted | Expansions | RSS MB |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 185 | adaptive, `--regions 1` | 8s | 1.421 | NO_IMPROVEMENT | 185 | 0 | 1 | 1 | 0 | 79 | 33.18 |
| 172 | fixed endpoint, `--regions 1` | 6s | 5.154 | NO_IMPROVEMENT | 172 | 0 | 16 | 5 | 11 | 1,809 | 33.71 |

`improved` is false on both. `cold_injection` is false. The 185 smoke is `target_mode` `multi-checkpoint`. The 172 smoke is `fixed-endpoint`. The production incumbent file was not written.

A zero-second `optimise_anchored` on the 185 in the unit test keeps cost 185, and the same call with mode `cold` raises `AnchoredRefused`.

## 14. Full tests

The v0.119 regression file list plus `tests/test_human_strategy_v0_120.py`:

**441 passed in 236.25 seconds.**

v0.119 had 420 passes. The v0.120 file adds 21 tests. No 40-second pilot runs inside pytest. The longest new test is a 6-second cold solve.

`tests/test_human_strategy_v0_120.py` contains 21 tests. Together with the retained v0.116 file they cover the 22 required checks:

1. Global deadline clip, including a nested probe that does not run after the parent clock is gone.
2. One scheduled allowance, then return. The 4,500 cap is not taken.
3. A real probe stops at its node cap, and a deadline already passed returns `TIME_LIMIT` with zero nodes and `exhaustive` false.
4. Cover that fell inside the node budget can deepen to 800. A bare `NODE_LIMIT` is deferred instead.
5. A successful probe is reused at a wider ceiling when its cost still fits.
6. An exhaustive miss is reused only inside the cost it finished.
7. A smaller `NODE_LIMIT` does not answer a larger node cap.
8. The same `NODE_LIMIT` on the same state is not searched again.
9. A different physical board is a new probe.
10. `allow_deals` and the stock identity change the cache key.
11. A queued alternative keeps the deepen from running, and the other objective still receives a 160-node probe.
12. The deferred partial remains eligible and is the objective deepened once the queue is clear.
13. The same frontier token is not admitted twice.
14. A cheaper ancestry replaces a costlier one. A later costlier visit is dominance with `proof` true.
15. A full beam of eight rejects the ninth line with `proof` false.
16. Node and time limits are not exhaustive.
17. A zero-second solve reports `TIME_LIMIT`, and a custom ladder appears in provenance.
18. The g19 prefix and the g83 trajectory replay as before.
19. An unscheduled call still uses 2,000 then 4,500. Covered by the existing test in this file.
20. Both complete routes verify, and anchored mode refuses `cold`.
21. Cold `solve` does not load a known solution. Covered by the existing short solve and by the 6-second live solve.
22. Fixed and adaptive search both include checkpoint 11 and both return cost 0.

g83's 4,500-node search remains in `tests/test_human_strategy_v0_116.py`, which this regression runs. The v0.120 file replays g19 and g83 instead of searching that position a second time.

## 15. Peak RSS

| Run | Peak RSS |
| --- | ---: |
| 40-second global optimise | 72.64 MB |
| 15-second cold | 51.12 MB |
| Anchored 185 smoke | 33.18 MB |
| Anchored 172 smoke | 33.71 MB |

The abort ceiling on the global and cold runs was 3,072 MB. v0.119's global peak was 139.39 MB, with the large excavation graphs cached. This run stays under that. The ladder-only pilot was 64.95 MB. The coordinator run is 7.7 MB higher, with 152 strategic states instead of 123.

## 16. Reproduction commands

Regression:

```
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py tests/test_human_strategy_v0_119.py tests/test_human_strategy_v0_120.py -q --tb=line
```

40-second global, 15-second cold, and the two anchored smokes are the commands in sections 8, 12, and 13. The matched-horizon numbers are from `search_segment` and `search_targets` on the constructed checkpoint fixture with `time_limit_s=3` and `max_unique=1500`, checkpoint 11 included in both horizons. The same comparison is `test_matched_horizon_fixed_and_adaptive_search_both_see_checkpoint_11`.

Interpreter: `py -3`. Working directory: the repository root.

## 17. Unresolved limitations

Foundation proposal time is 32.134 seconds. The experimental target was about 25. The ladder removed the 12-second monopoly. What remains is 12.300 seconds of first-time workspace probes and 10.937 seconds of many small excavations. Raising the 0.08-second workspace cap would spend more, not less. Suppressing those probes would report a faster controller and would also skip legal foundation analysis. That trade was not taken.

The excavation cache saved no nodes on this deal. Repeats were stopped by the coordinator before lookup. Cross-budget reuse happened once. There is still no resume of a previous search frontier.

The reported line's probe lock (74 nodes) is easy to misread as the run's excavation. The run used 11,177 nodes. Provenance now carries both, and they must stay separate.

Whole-game admissible pruning is unchanged. `safe_prunes` is 0. A partial cost, including 38, 22, and 10, is not a complete-game bound and is not a claim that 185 or 172 was beaten.

The frontier recorded no cost-dominance replacement on this deal. Capacity eight rejected 35 lines heuristically. All of those exclusions have `proof` false. Some of those lines may be worth a later visit. This release does not widen the beam.

Cold search for 15 seconds, and the 40-second optimise, both stop at one foundation. The second foundation was not rediscovered. No new eight-foundation route was produced. The 119-move benchmark was not attempted.

`dependency_planning`'s inclusive total and the sum of its expected exclusive children differ by 0.348 seconds, as section 3 records. Component foundation and the exclusive timing sum differ by 1.018 seconds. Both gaps are reported. They are not folded into a single bucket.

## 18. Recommended next development

The next throughput gain is inside foundation analysis, particularly the 0.08-second workspace probe on a state that has not been seen. 201 misses cost 12.300 seconds. The cache already returns the 12 repeats. Fewer first-time probes, or a cheaper negative answer on states that cannot build a workspace, is the lever that can move foundation time toward 25 seconds without deleting excavation.

Keep the 4,500-node capability for a partial that has already reduced cover, with the same reserve and `deep_share`. This run used that path once, for 0.31 seconds. Using it more often, only after cover falls and only when no alternative is waiting, is the productive excavation v0.119 was spending on exhausted 48-node graphs.

Leave the frontier at eight until a retained line is shown to be worse than a line the beam dropped. This run's cheapest one-foundation branch is still g=22, which the beam of eight already holds.

An explicit longer unique budget on one stock-empty anchored horizon remains a separate experiment. It is not required to schedule the global search, and it was not run here.

The cold controller still needs a way through the position after the first foundation. The 15-second pilot classifies that position `PROBE_LIMIT` with nine legal moves and four deferred objectives. Those deferred objectives are the ones a later, larger allowance should revisit, on a fresh board, once the cheap alternatives have had a turn.
