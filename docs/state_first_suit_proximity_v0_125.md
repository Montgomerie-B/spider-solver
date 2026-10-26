# State-first suit proximity v0.125

Deal `4925153`, plus one seeded two-deck smoke deal. Corrected MobilityWare costs. One worker. Memory cap 3,072 MB. Hard corrected-cost cap 300. This release does not commit, push, merge, or open a pull request.

The measured question was whether one cheap suit-completion signal, applied only as a sort key, would move the existing whole-game kernel toward removable king-to-ace sequences. It did. Under the same 80,000-unique-state cap the original kernel and the v0.124 strategy lane both finished with zero foundations. The suit ordering removed four, on a replay-checked path of corrected cost 139. It did not finish the game.

## 1. Starting commit and branch

Branch `local/state-first-suit-v0-125`, created from a clean tree.

HEAD `20fe3e1a578d65897e845cc59320fcde51a86eff` (`20fe3e1 Audit global search architecture and test state-first search v0.124`).

`engine.py`, `rules.py`, the Human Strategy Controller, the incumbent registry, and the verified solution files are unchanged. The v0.124 report and its artifacts were left in place. A pre-spec stash on `local/strategic-continuity-v0-123` was not popped.

## 2. Source-level search integration

Stage 1 is still `run_search` in `src/spider/search_kernel.py`, reached through `search_whole_game` in `src/spider/whole_game_anytime.py`.

`search_whole_game` passes `all_legal_actions`. That list is every legal tableau transfer plus a stock deal when `can_deal` is true. The experimental suit search uses the same function. `lane_keys` is unchanged and remains the control. Its seven names are cost, foundation, reveal, workspace, construction, prep, and epoch.

`search_suit_ordered` in `src/spider/global_search_experiment.py` is the new caller. It keeps those seven names and the six non-foundation tuples. It replaces only the foundation tuple. Round-robin weight stays one seventh. There is no eighth lane and no call into the Human Strategy Controller on this path.

`suit_lane_keys` reads the original tuple `(-foundations, face_down, stock_rows, g)` and emits `(-foundations, -proximity, face_down, stock_rows, g)`. Higher proximity is popped first when the foundation count ties. Face-down count, stock, and corrected cost still break the remaining ties.

Cold mode passes the hard cap 300 and `lower_bound_fn=None`. Optimise mode passes `min(incumbent - 1, 300)` and `admissible_remaining` only. Proximity is never that function. `stop_on_first_terminal` stays false, matching the whole-game adapter.

The v0.124 strategy search is still `search_strategy_guided`. Its cold path still overwrites the kernel ceiling to `None` after recording a hard cap of 300. This release did not change that line. A same-order census with that ceiling reproduced the saved strategy expansion counts exactly, so the published v0.124 strategy result remains the control.

`solve_then_optimise` runs the cold suit search and calls the existing `optimise_anchored` only when that search returns a replay-valid eight-foundation game. A failed cold search leaves stage 2 empty. No stored route is substituted.

The experimental CLI is `tools/global_search_experiment.py`. Variants are `suit` (now the default), `kernel`, `strategy`, and `solve-then-optimise`. `--deal-seed` builds a fresh two-deck shuffle. Cold mode rejects `--incumbent-cost` and `--incumbent-moves`.

Result schema for a suit run is `spider-global-search-0.125`. The module constant `SCHEMA` stays `spider-global-search-0.124`, which the v0.124 tests still require. The controller schema stays `spider-human-strategy-0.123`.

## 3. Existing foundation-scoring audit

`lane_keys` documents itself as having no suit or rank target. The foundation key is exactly `(-foundations, face_down, stock_rows, g)`. With zero foundations this is face-down count, then stock rows, then corrected cost.

The other lanes already carry the signals that v0.124 measured:

| Lane | Prefers |
| --- | --- |
| cost | lower corrected cost |
| reveal | fewer face-down cards, then more foundations, then more empty columns |
| workspace | more empty columns, then fewer face-down cards, then more run compression |
| construction | more same-suit bonds, then a longer run, then more merge edges |
| prep | more stock rows dealt (the key negates rows), then bonds and empty columns |
| epoch | fewer stock rows, then more foundations, then fewer face-down cards |

`current_tableau_summary` counts bonds, the longest visible same-suit component, merges, face-down cards, stock rows, empty columns, and foundations. It has no king bit, no missing-rank list, and no access penalty. `component_cover` is omitted on purpose, because undealt stock makes a full king-to-ace cover look incomplete.

What the foundation lane cannot tell apart, while no foundation has been removed:

- A. A long same-suit run that already holds the king and is a few accessible ranks from completion.
- B. Several short same-suit pairs that add many bonds and never approach one king-to-ace sequence.
- C. A run missing one or two ranks whose copies are face-up and legally joinable.
- D. The same length of run whose missing ranks are face-down, in stock, or sitting under a blocker.

Bonds and longest-run length treat A and a pile of short pairs as the same kind of progress. Face-down and stock then outrank both, because they sit in front of the foundation key and on two other lanes. A length-7 run with an empty stock and 14 face-down cards, which is the original kernel's best reported state, never has to answer whether the missing six ranks can be moved.

The missing signal is the distance from one physical same-suit run to a removable king-to-ace sequence, using the best remaining copy of each missing rank. That is not a second copy of the bond counter or the longest-run counter.

## 4. Suit-completion proximity definition

Implemented in `src/spider/suit_completion.py`. One scan of the ten columns and the stock. No excavation planner and no speculative line.

A candidate is a contiguous same-suit descending face-up segment. A buried length-1 card is ignored. An exposed length-1 card counts, so a bare king is visible to the score.

```
raw = length * 100
    + 250 if the segment contains the king
    + 80  if the segment contains the ace
    + 40  for a legal same-suit join downward onto this exposed top
    + 40  for a legal same-suit join of this exposed run onto a matching parent
    - access penalties of the ranks in 1..13 that the segment does not hold
    - (80 + 20 * cards above) when the segment is not the exposed top
```

Negative raw scores clamp to 0. Each suit keeps its best segment. The state's score is the sum of the four suits. Already removed foundations are not added back. The lane's `-foundations` component ranks those separately.

Access penalty for one missing rank, using the best physical copy once:

| Where the best copy sits | Penalty |
| --- | ---: |
| Exposed top run | 2 |
| Face-up, covered | 8 |
| Face-down | 20 |
| Stock | 28 |
| Absent from tableau and stock | 40 |

A join is one `can_move` check of the exposed same-suit run. An off-suit card of the right rank does not get the bonus. An empty column does not get it either.

On the opening of deal 4925153 the score is 226, from two exposed length-1 cards (clubs 138, diamonds 88). The signal is small until a real run exists. A complete heart king-to-ace still sitting on a column, before `check_seq`, scores 1,630 for hearts.

## 5. Correctness and duplicate-card handling

Spider has two copies of each suit and rank. The score keeps one segment per suit, so two heart runs are not added into a claim that both can be completed from the same cards. Two complete heart sequences on the tableau are counted as two physical sequences and still contribute 1,630, not 3,260.

A missing rank pays the better copy once. Two face-down aces cost 20, not 40. One exposed ace and one face-down ace cost 2. Copies are not interchangeable for play: moving one physical king changes a different column from moving the other, and `pack_state` keeps those positions distinct.

`check_seq` removes a finished king-to-ace inside the move. The successor therefore has a foundation and an empty run, and the heart score drops. Search census shows `run_ge_13 = 0` and `complete_exposed_states = 0` for that reason. Completed sequences are counted by foundation removals.

The score is an ordering estimate. `proof_prune(0, proximity, 50)` is true on the opening, which is what would happen if the integer were passed as a lower bound. Cold `lower_bound_prunes` stayed 0 on every suit run. The JSON field `proximity_prunes` is 0.

## 6. Runtime overhead

One thousand proximity scans of the opening took 0.155 seconds, about 155 microseconds each. Two hundred scans inside the unit test finished in well under a second.

At the 80,000-state cap the suit search used 100.212 seconds and 99.906 seconds of CPU. The saved original-kernel run used 102.863 seconds and 102.578 seconds of CPU. A lighter same-order census of that kernel, which does not build the old post-stock topology snapshot, finished the same 80,000 states in 57.127 seconds. The suit scan is visible against that lighter observer and is absorbed inside the wall time of the original published kernel run.

The 40-second suit run stored 35,478 unique states. The original kernel stored 36,548 in its own 40-second run. Throughput is close. The quality difference below is not an artifact of visiting far more states.

## 7. Legal-successor coverage

Successor generation is `all_legal_actions`. The suit path passes no action filter unless a caller supplies `advice_fn`. The primary runs did not.

On the opening, a 400-state suit search stored every legal child of the root, including the deal. `heuristic_exclusions` is 0. `legal_actions_dropped` is 0. `lower_bound_prunes` is 0. Lane pops use the seven original names and stay level with each other.

`order_with_advice` moves one legal suggestion to the front and returns the rest. `None` or an illegal suggestion leaves engine order unchanged. `AdviceCache` skips a repeated packed state and stops calling after its budget. A search whose advice always returns `None` generates the same children as the unadvised search. That path was unit-tested and was not used in the deal measurements. Experiment D, suit plus campaign advice, was not run. The suit result is attributable to the foundation-lane key alone.

A unique or time limit is recorded as `resource_limited`. That is unfinished search. It is not a proof that the remaining foundations are impossible. Duplicate skips are the kernel's existing cheaper-ancestry rule (`child_g >= prev`), which also cuts zero-cost cycles.

## 8. Baseline, strategy, and suit

v0.124 file names do not match these labels. Control A here is the original seven-lane kernel, saved as `artifacts/global_search/v0_124/control_b_40.json` and `control_b_150.json`. Control B here is the strategy lane, saved as `experiment_c_40.json` and `experiment_c_150.json`. Those runs were not repeated as new policies. A same-order census reproduced their expansion counts and best adapter states, and added the run-length histogram the old files did not store.

Deal `4925153`. Cap 300. One worker. Seed 0 where a seed is used. The strategy lane uses seed 0. The suit and kernel runs use engine action order.

| | Control A kernel | Control B strategy | Experiment C suit |
| --- | ---: | ---: | ---: |
| Lanes | 7, original keys | 8, original plus strategy | 7, foundation key only |
| Foundations at 40 s | 0 | 0 | 3 |
| Foundations at 80,000 | 0 | 0 | 4 |
| States with a run of length 8 or more, 80,000 cap | 8,572 | 5,325 | 45,167 |
| Length 10 or more | 0 | 0 | 32,760 |
| Length 12 or more | 0 | 0 | 2,931 |
| Maximum run seen | 8 | 8 | 12 |
| Foundations removed | 0 | 0 | 4 |
| Complete eight-foundation game | no | no | no |

The kernel and the strategy lane do build some length-8 runs. They never recorded a length-10 run or a foundation inside this cap. The suit search records thousands of length-10 and length-12 runs, and the engine removes finished sequences. The highest proximity state is a different fact and is reported in section 11. It still has zero foundations.

## 9. Results at 40 seconds

Separate process. `--time-limit 40 --max-unique 80000`. Stop reason `time limit`. These numbers are not the 80,000-state run.

| | Kernel, saved 40 s | Strategy, saved 40 s | Suit, this run |
| --- | ---: | ---: | ---: |
| Unique states | 36,548 | 57,834 | 35,478 |
| Expanded | 5,567 | 9,819 | 4,231 |
| Generated | 59,635 | 94,084 | 70,493 |
| Duplicate skips | 22,097 | 34,636 | 34,276 |
| Heuristic exclusions | 0 | 0 | 0 |
| Lower-bound prunes | 0 | 0 | 0 |
| Foundations | 0 | 0 | 3 |
| Wall seconds | 40.002 | 40.000 | 40.010 |
| CPU seconds | 39.922 | 39.938 | 39.938 |
| Peak RSS MB | 75.99 | 121.71 | 89.87 |
| Stop | time limit | time limit | time limit |

Suit stock-row histogram: 5 rows 2,489; 4 rows 6,869; 3 rows 684; 2 rows 96; 1 row 33; empty 26,047. Deal-action nodes stored: 1,492.

First visited foundation states, search clock:

| Foundations | Seconds | Corrected cost | Face-down | Stock rows | Longest run |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.700 | 65 | 13 | 0 | 10 |
| 2 | 6.110 | 84 | 13 | 0 | 9 |
| 3 | 6.227 | 87 | 12 | 0 | 8 |

The exported best path is a different trajectory. Replayed from the opening in a second process: spades removed at cost 76, clubs at 84, diamonds at 87. End state cost 105, three foundations, seven face-down, stock empty, not solved. Replay cost matched.

Census inside this 40-second process: run length 8 or more 22,759; 10 or more 18,547; 12 or more 2,053; 13 exactly 0. Exposed runs: 15,175 / 10,048 / 1,696 / 0. Near-complete exposed runs with a buried or missing rank: 2,146. Near-complete exposed runs whose missing ranks are face-up: 5,719. States that already hold a foundation: 23,474. Minimum face-down seen: 7.

v0.124's own 40-second and later unique-cap stops were separate processes too. The kernel's 40-second file stopped at 40.002 seconds. Its 80,000-state file stopped at 102.863 seconds. The strategy 80,000-state file stopped at 61.531 seconds. Those wall times stay with those files.

## 10. Results at 80,000 unique states

Separate process. `--time-limit 300 --max-unique 80000`. Stop reason `unique limit` at 100.212 seconds. This is not a continuation of the 40-second process.

| | Kernel, saved | Kernel census, same order | Strategy, saved | Strategy census, same order | Suit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unique | 80,000 | 80,000 | 80,000 | 80,000 | 80,000 |
| Expanded | 13,532 | 13,532 | 13,516 | 13,516 | 10,653 |
| Generated | 142,518 | 142,518 | 133,682 | 133,682 | 174,566 |
| Duplicate skips | 58,974 | 58,974 | 51,165 | 51,165 | 92,807 |
| Foundations | 0 | 0 | 0 | 0 | 4 |
| Wall seconds | 102.863 | 57.127 | 61.531 | 64.453 | 100.212 |
| CPU seconds | 102.578 | not recorded | 61.391 | not recorded | 99.906 |
| Peak RSS MB | 154.69 | 153.88 | 168.59 | 166.24 | 163.90 |
| Stop | unique limit | unique limit | unique limit | unique limit | unique limit |

The census wall times differ because the observer does less work per state than the original snapshot. Expanded, generated, and duplicate counts match the saved files. Kernel adapter-best is the saved state: cost 55, 14 face-down, 19 bonds, run 7, stock empty, zero foundations. Strategy report-best is the saved state: cost 85, 16 face-down, 32 bonds, run 7, stock empty, zero foundations.

Suit stock-row histogram: 5 rows 4,346; 4 rows 10,275; 3 rows 1,812; 2 rows 423; 1 row 66; empty 64,837. Deal-action nodes stored: 3,526. Lower-bound prunes 0. Heuristic exclusions 0. Lane pops are 1,683 or 1,684 on each of the seven names.

Suit census: run 8 or more 45,167; 10 or more 32,760; 12 or more 2,931; 13 exactly 0. Exposed: 31,949 / 18,428 / 2,326 / 0. Near-blocked 4,097. Near-accessible 9,131. States with at least one foundation: 55,483. Minimum face-down: 7. Maximum proximity seen: 4,854, on a state with zero foundations.

## 11. Best structural partial states

Leaders are independent. A higher proximity score is one column. It does not decide the report.

Suit, 80,000 states, each replay-checked:

| Leader | Cost | Foundations | Face-down | Bonds | Longest run | Exposed run | Stock rows | Proximity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Report (foundations, then face-down, then bonds, then run, then cost) | 139 | 4 | 8 | 28 | 11 | 11 | 0 | 2,772 |
| Fewest face-down | 102 | 3 | 7 | 26 | 11 | 3 | 0 | 1,724 |
| Longest run | 133 | 3 | 9 | 37 | 12 | 12 | 0 | 3,772 |
| Longest exposed run | 132 | 3 | 10 | 37 | 12 | 12 | 0 | 3,790 |
| Highest proximity | 82 | 0 | 14 | 53 | 12 | 12 | 0 | 4,854 |

The proximity leader is the clearest warning in the table. Fifty-three bonds and a proximity of 4,854 did not remove a foundation. The report leader did, at a lower proximity. The face-down leader still has the fewest buried cards and only three foundations. Those are different strengths. The report uses foundation count first because a removed sequence is finished work. It does not claim the cost-139 state dominates the cost-102 state on every axis.

The report leader's exposed run is length 11 and `near_blocked` is 1. One missing rank of that run is still face-down, in stock, or absent. The search is building real sequences and is still blocked on at least one of them.

Suit, 40-second process, report leader: cost 105, three foundations, seven face-down, 27 bonds, longest run 11, exposed run 3, stock empty, proximity 1,738, replay cost 105. The long run at that state is buried. The 80,000-state report leader is the one with an exposed length-11 run.

Control bests, unchanged from v0.124:

| Policy | Cost | Foundations | Face-down | Bonds | Longest run | Stock |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Kernel adapter | 55 | 0 | 14 | 19 | 7 | empty |
| Kernel report key, census | 58 | 0 | 14 | 24 | 7 | empty |
| Strategy report | 85 | 0 | 16 | 32 | 7 | empty |

The kernel report key in the census prefers 24 bonds at cost 58 over 19 bonds at cost 55. The adapter key, which the saved file used, prefers cost 55. Both have zero foundations.

## 12. Foundations removed

Engine removals on the exported suit trajectories, replayed from the untouched opening.

40-second best path: spades at cost 76, clubs at 84, diamonds at 87. Three foundations. Seven face-down at the end. Stock empty.

80,000-state best path: spades at cost 76, clubs at 84, diamonds at 87, hearts at 133. Four foundations. The end state continues to cost 139 with eight face-down and an empty stock. The fourth removal leaves nine face-down; later moves reach eight.

The search also visited some one-foundation state at cost 65, about four seconds in, on both suit processes. That prefix was not the exported best path and was not written out. The exported paths above are the ones a second process replayed.

No suit run stored a state whose longest visible run was 13, because `check_seq` removes that run before the successor is recorded. The foundation list is the completion count. Controls removed none.

## 13. Full solutions

None of the cold runs solved the game. `solved` is false. Provenance of both suit deal runs is `partial_legal_search`, with census label `unsuccessful_bounded_search` and incompleteness `resource_limited`.

That is not an independent cold complete solution. It is not a known-prefix trajectory. `known_prefix` is false. `imported_substitute` is false.

The verified MW 185 file and the MW 172 human file were not loaded. Their cold-discovery status is unchanged: 185 replays at 185 and was not found by this search; 172 is the imported human route; the historical 186 campaign used a known prefix. Replay of those files is not a discovery by this kernel.

No route under 172 was produced.

## 14. Independent-deal smoke

`opening_from_seed(125)` shuffles two full four-suit decks with `random.Random(125)` and deals through `SpiderState.from_cards`. The heuristic source does not contain the deal id. The same seed reproduces the same packed state. Seed 126 and deal 4925153 are different states.

Cap 2,500 unique states, time limit 30 seconds, both hit the unique limit in about three seconds.

| | Kernel | Suit |
| --- | ---: | ---: |
| Foundations | 0 | 0 |
| Adapter or report best cost | 30 | 37 |
| Face-down | 33 | 35 |
| Bonds | 15 | 24 |
| Longest run on that state | 3 | 5 |
| States with run length 8 or more | 0 | 117 |
| Maximum run seen | 5 | 8 |
| Peak RSS MB | 29.41 | 29.27 |

Neither policy removed a foundation at this budget. The suit search did reach length-8 runs on a deal it was not tuned on. The original kernel's longest run in the same 2,500 states was 5, and it stored no length-8 state. This is a smoke check, not a second 80,000-state campaign.

## 15. Incumbent integrity

`solutions/4925153_autonomous_185.moves`, `solutions/4925153_canonical.moves`, and `solutions/4925153_incumbent.json` are unmodified.

Tests replay 185 at cost 185 with eight foundations, replay 172 at cost 172 with eight foundations, and reject the g83 fixture as an incumbent. `optimise_anchored(..., mode="cold")` raises `AnchoredRefused`. A tiny anchored call on the imported 172 route returns that route unchanged at cost 172.

`solve_then_optimise` with a six-state cold budget returns `stage2: null`, `imported_substitute: false`, and provenance `unsuccessful_bounded_search`. Stage 2 was not started after the deal pilots, because stage 1 did not solve. No stored solution was written.

The production controller does not import `suit_completion` or `global_search_experiment`.

## 16. Exact test totals

Maintained v0.123 list, plus `tests/test_global_search_v0_124.py`, plus `tests/test_global_search_v0_125.py`:

**538 passed in 222.81 seconds.**

The new file adds 24 tests. The previous maintained-plus-v0.124 total was 514. 514 + 24 = 538.

`test_fixed_seed_is_deterministic` in the v0.124 file compared full JSON documents, including `elapsed_s` inside strata. Under the full-suite load those stamps differed by one millisecond while every move and state field matched. The assertion now ignores nested elapsed stamps. The ordering check remains.

The v0.125 tests cover a complete king-to-ace score, incomplete runs, missing-rank penalties, blocked versus accessible runs, two copies, off-suit stacks, stock-empty tableaux, scores before and after `check_seq`, the single changed lane, full legal generation, advice reordering, failed advice, zero-cost transfers, cheaper ancestry, no proximity prune, determinism, cold independence, eight-foundation replay, and the anchored refusal. Full-deal searches are outside pytest.

## 17. Runtime and peak memory

| Run | Wall seconds | CPU seconds | Peak RSS MB |
| --- | ---: | ---: | ---: |
| Suit 40 s, deal 4925153 | 40.010 | 39.938 | 89.87 |
| Suit 80,000, deal 4925153 | 100.212 | 99.906 | 163.90 |
| Suit smoke, seed 125, 2,500 states | 3.092 | 3.078 | 29.27 |
| Kernel smoke, seed 125, 2,500 states | 3.942 | 3.922 | 29.41 |
| Kernel census, 80,000 | 57.127 |  | 153.88 |
| Strategy census, 80,000 | 64.453 |  | 166.24 |
| Full regression | 222.81 |  |  |

The memory cap on every search was 3,072 MB. The highest RSS on a suit pilot was 163.90 MB. No run hit the RSS abort. One worker.

## 18. Recommended v0.126 work

Promote the suit foundation key as the experimental Stage 1 ordering. The CLI default is now `--variant suit`. `lane_keys` stays available as `--variant kernel`. The strategy lane stays available and is still not the control. The production Human Strategy Controller is unchanged.

The promotion rests on removed foundations, length-10 and length-12 runs, and replay-valid paths. It does not rest on the proximity leader. That state, cost 82 and proximity 4,854, removed nothing.

Do not open v0.126 by adding a planner, a new transposition table, or a checkpoint rejoin. The same kernel is now past the failure mode v0.124 measured. The next labelled experiment should spend a larger unique budget, reported separately from this 80,000 cap, and ask whether the cost-139 four-foundation path reaches a fifth removal. The first four arrivals were costs 76, 84, 87, and 133, so the gap before the fifth is the live question. Keep the face-down leader and the exposed-run leader in the report. Within one foundation count the proximity key only breaks ties, and the blocked length-11 run on the cost-139 state says the missing rank is still buried.

Leave cold mode independent of 172 and 185. If a later run does solve, pass that replay-checked route into the existing anchored optimiser and label it `independent_cold_complete`.

## 19. Reproduction commands

Working directory: the repository root. Interpreter `py -3`. One worker.

```
py -3 -m pytest tests/test_global_search_v0_125.py tests/test_global_search_v0_124.py -q --tb=short
```

The full regression is the command in `docs/strategic_continuity_v0_123.md` section 19, followed by `tests/test_global_search_v0_124.py tests/test_global_search_v0_125.py`.

```
py -3 tools/global_search_experiment.py --variant suit --mode cold --deal deals/4925153.txt --time-limit 40 --max-unique 80000 --memory-mb 3072 --seed 0 --cost-ceiling 300 --out artifacts/global_search/v0_125/suit_40.json

py -3 tools/global_search_experiment.py --variant suit --mode cold --deal deals/4925153.txt --time-limit 300 --max-unique 80000 --memory-mb 3072 --seed 0 --cost-ceiling 300 --out artifacts/global_search/v0_125/suit_80000.json

py -3 tools/global_search_experiment.py --variant kernel --mode cold --deal-seed 125 --time-limit 30 --max-unique 2500 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_125/smoke_kernel_seed125.json

py -3 tools/global_search_experiment.py --variant suit --mode cold --deal-seed 125 --time-limit 30 --max-unique 2500 --memory-mb 3072 --seed 0 --cost-ceiling 300 --out artifacts/global_search/v0_125/smoke_suit_seed125.json
```

Control files, already measured and cited: `artifacts/global_search/v0_124/control_b_40.json`, `control_b_150.json`, `experiment_c_40.json`, `experiment_c_150.json`.

## 20. Final Git status

Branch `local/state-first-suit-v0-125`. HEAD `20fe3e1a578d65897e845cc59320fcde51a86eff`. No commit was made.

```
 M src/spider/global_search_experiment.py
 M tests/test_global_search_v0_124.py
 M tools/global_search_experiment.py
?? docs/state_first_suit_proximity_v0_125.md
?? src/spider/suit_completion.py
?? tests/test_global_search_v0_125.py
```

Search artifacts under `artifacts/global_search/v0_125/` are untracked by the existing ignore rules. They were not added to `solutions/`.
