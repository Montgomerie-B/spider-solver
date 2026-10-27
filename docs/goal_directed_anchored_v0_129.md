# Goal-directed anchored search v0.129

Schema `spider-goal-directed-anchored-0.129`. Deal `4925153`. Branch `local/goal-directed-anchored-v0-129`, started from v0.128 `2c06dff34de491e7fb79c8b86afccc96ea9e15a7` (`2c06dff Re-search five anchored windows on the 172 route v0.128`).

This is an incumbent-guided segment experiment. It is not an `independent_cold_complete` solve. The production incumbent was not overwritten. No second search architecture was added.

## Result

No fully replayed game cheaper than 172 was found. Neither policy produced a target-state rejoin.

| Window | Played cost | Uniform cost | Goal order |
| --- | ---: | --- | --- |
| Checkpoint 165–168, actions 166–168 | 3 | Budget-limited at g=0 | Budget-limited after entering g=2 |
| Checkpoint 146–149, actions 147–149 | 3 | Budget-limited at g=0 | Budget-limited after entering g=2 |
| Checkpoint 20–24, actions 21–24 | 4 | Exhausted. No exact rejoin at cost 3 or less | Exhausted. Same negative result |
| Checkpoint 76–80, actions 77–80 | 4 | Budget-limited at g=2 | Budget-limited after entering g=3 |
| Checkpoint 160–170, actions 161–170 | 10 | Budget-limited at g=1 | Budget-limited after entering g=9 |

The scheduling question is answered. On the four windows that v0.128 left inside the zero-cost component, the goal lane expanded paid states before the 20,000-state cap: g=2 on 165–168 and 146–149, g=3 on 76–80, and g=9 on 160–170. Those four goal runs still stopped on the unique cap, so they are not optimality proofs. Actions 21–24 finished under the cap for both policies, with zero rejoins.

The primary target, a replay-verified complete solution at 171 or fewer corrected MobilityWare moves, was not met. The searched portions of the five exact checkpoints do not contain a cheaper rejoin. The next experiment should move to a broader stock-boundary target and suffix repair. That expansion was not implemented.

## 1. Baseline

Repository `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`. Remote `origin` is `https://github.com/Montgomerie-B/spider-solver.git`. One worker. Corrected MobilityWare scoring. `MW_RULES` prices a whole face-up column moved onto an empty column at 0 when that column has no face-down cards. `can_deal_into_empty` stays true, so an empty column does not remove a stock deal.

Both historical solution files were replayed from `deals/4925153.txt` through `replay_actions_detailed` before the searches, and their bytes were hashed again afterwards.

| Route | SHA-256 | Explicit | Tableau | Deals | Foundations | Corrected MW | Legacy MW | Solved |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | 174 | 169 | 5 | 8 | 172 | 163 | yes |
| `solutions/4925153_autonomous_185.moves` | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` | 189 | 184 | 5 | 8 | 185 | 177 | yes |

The hashes were unchanged after the ten searches. `solutions/` was not written. The incumbent registry was not written. The 185 route was replayed and left unused as a donor.

The v0.126 full-suite failure is unchanged and was not rerun. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` where the assertion expects `TIME_LIMIT` when the whole suite runs. This experiment does not edit the Human Strategy Controller or that test.

The five windows, their tableaus, and their pack identities are the ones printed in Section 2 of `docs/anchored_optimisation_v0_128.md`. This run re-checked the played action strings and the per-step costs against that record. Every played step costs 1. No slice contains a deal. The source call to `segment_lower_bound` is 0 on every window.

| Window | Actions | C | Prefix | Suffix | Kernel ceiling |
| --- | --- | ---: | ---: | ---: | ---: |
| 165–168 | `move 6 8 9`, `move 6 3 1`, `move 8 6 9` | 3 | 163 | 6 | 2 |
| 146–149 | `move 3 10 2`, `move 3 4 7`, `move 10 3 2` | 3 | 144 | 25 | 2 |
| 20–24 | `move 4 8 1`, `move 4 10 1`, `move 8 10 1`, `move 8 4 1` | 4 | 20 | 148 | 3 |
| 76–80 | `move 6 1 2`, `move 6 5 1`, `move 5 6 2`, `move 1 6 2` | 4 | 75 | 93 | 3 |
| 160–170 | actions 161–170, including 166–168, ending `move 3 10 4` | 10 | 158 | 4 | 9 |

A replacement of segment cost `R` produces a complete-game cost of `prefix + R + suffix`. Because `prefix + suffix = 172 - C`, any `R <= C - 1` makes the spliced game 171 or less. `admissible_remaining` was recorded and was not given to the segment search. `proof_prune(prefix, admissible_remaining, 172)` is false at every source. The closest of the five is `163 + 7 = 170`.

## 2. What changed

`search_segment` still defaults to `policy="ucs"`. That path is the v0.128 lane key `(g,)`, the same successors, the same ceiling `C - 1`, and the same best-g dominance. Production `optimise_anchored` does not pass a policy, so it stays on this path.

`policy="goal"` uses the same kernel with two lanes, `("goal", "cost")`:

- The goal key is `(displacement, g)`.
- The cost key is `(g, displacement)` while the state's displacement is at most the nearest displacement queued so far. A worse state stays on the goal lane and is not deleted.
- Every engine-legal action is still generated. Inside one node the actions stay ordered by `(step_cost, str(action))`, so a zero-cost whole-column transfer is still emitted before a paid move from that node.
- Discovery mode stops at the first replay-valid rejoin. The driver requested that mode for every goal window. A hit under that stop proves the rejoin's legality and its cost. It does not prove that the cost is the minimum. No such hit occurred. A goal run that empties the heap is `cost_optimal`.
- `target_displacement` is an integer column-ordered score against the target physical state. Matched cards are read from the bottom of each column. Cards covering a matched base score higher than the same cards parked on an empty target column. Stock and foundation differences are included. The score is ordering only. It is not a lower bound and it is not a discard reason. The proof bound remains the deals-only `segment_lower_bound`, with the unreachable sentinel when the stock or foundation multiset cannot become the target.

The unique-state cap now stores and terminal-checks the identity that brings `unique` to `max_unique`, then stops. The previous kernel counted that child and dropped it before the terminal test. A better-g reopen of an identity already stored does not consume another unique slot. Searches that finish under the cap are unchanged: the uniform-cost run of actions 21–24 reproduced the v0.128 counters exactly.

Column-ordered identity stays `pack_state` plus `canonical_state_key`. The post-stock symmetry pack is unused. No orbit quotient, successor filter, tactical planner, or extra heuristic family was added.

## 3. Budget

Both policies used the same caps: 20,000 unique states, 30 seconds, 3,072 MB RSS, one worker. The root is the source pack at segment cost 0. No reference action was inserted into the frontier. Uniform cost ran with `exhaustive=True`. Goal ran with `exhaustive=False`, which stops at the first legal rejoin and otherwise continues to the cap or to an empty heap.

Search time is the segment search only. Affinity time is the portion of that search spent inside `target_displacement`. Peak RSS is the kernel's working-set sample. The process stayed near 45 MB. The 3,072 MB cap did not bind. The 30-second cap did not bind. The unique cap bound every window except both policies on actions 21–24.

## 4. Uniform-cost control

These counts match the v0.128 table. Elapsed time and the RSS sample moved by a fraction of a second and by under 1 MB. Expansion, generation, prune, transposition, and zero-cost counts match.

| Window | Status | Stop | Expanded | Unique | Generated | Ceiling prunes | Lower-bound prunes | Transpositions | Stale | Zero-cost | Rejoins | Seconds | Peak MB |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 165–168 | `INCONCLUSIVE` | unique limit | 131 | 20,000 | 21,476 | 0 | 49 | 1,438 | 0 | 1,965 | 0 | 4.710 | 44.27 |
| 146–149 | `INCONCLUSIVE` | unique limit | 620 | 20,000 | 23,547 | 0 | 620 | 3,428 | 0 | 3,100 | 0 | 5.555 | 44.52 |
| 20–24 | `EXHAUSTED` | complete | 6,475 | 7,330 | 17,831 | 95,093 | 855 | 10,500 | 2 | 1,954 | 0 | 7.919 | 44.91 |
| 76–80 | `INCONCLUSIVE` | unique limit | 2,192 | 20,000 | 47,699 | 0 | 2,192 | 27,700 | 0 | 690 | 0 | 9.403 | 44.91 |
| 160–170 | `INCONCLUSIVE` | unique limit | 248 | 20,000 | 26,782 | 0 | 0 | 6,783 | 0 | 2,108 | 0 | 5.506 | 45.09 |

Expansions by segment cost `g`. Every expansion was on the `cost` lane.

| Window | g=0 | g=1 | g=2 | g=3 | Generated g |
| --- | ---: | ---: | ---: | ---: | --- |
| 165–168 | 131 | 0 | 0 | 0 | 0: 1,965; 1: 19,511 |
| 146–149 | 620 | 0 | 0 | 0 | 0: 3,100; 1: 20,447 |
| 20–24 | 2 | 68 | 785 | 5,620 | 0: 2; 1: 96; 2: 1,702; 3: 16,031 |
| 76–80 | 6 | 270 | 1,916 | 0 | 0: 12; 1: 426; 2: 7,446; 3: 39,815 |
| 160–170 | 120 | 128 | 0 | 0 | 0: 1,080; 1: 14,828; 2: 10,874 |

`min_h` was 0 on every window. `max_h` was the unreachable sentinel `1,000,000` on the first four windows and 0 on checkpoint 160–170. `proof` and `cost_optimal` are true only for the completed 20–24 run. The driver aborted if that run was anything other than `EXHAUSTED` with zero rejoins. It stayed exhausted.

## 5. Goal order

| Window | Status | Stop | Expanded | Unique | Generated | Ceiling prunes | Lower-bound prunes | Transpositions | Stale | Zero-cost | Rejoins | Seconds | Affinity s | Peak MB |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 165–168 | `INCONCLUSIVE` | unique limit | 2,925 | 20,000 | 30,579 | 194,685 | 60 | 10,541 | 44 | 21,927 | 0 | 14.443 | 1.598 | 44.27 |
| 146–149 | `INCONCLUSIVE` | unique limit | 5,890 | 20,000 | 27,252 | 63,575 | 1,680 | 6,687 | 398 | 1,256 | 0 | 14.789 | 1.407 | 44.91 |
| 20–24 | `EXHAUSTED` | complete | 6,495 | 7,330 | 17,850 | 95,450 | 856 | 10,456 | 49 | 1,958 | 0 | 8.405 | 0.447 | 44.91 |
| 76–80 | `INCONCLUSIVE` | unique limit | 5,867 | 20,000 | 32,011 | 81,696 | 1,548 | 12,005 | 7 | 953 | 0 | 14.126 | 1.310 | 45.09 |
| 160–170 | `INCONCLUSIVE` | unique limit | 2,905 | 20,000 | 25,951 | 95,064 | 899 | 5,951 | 45 | 7,997 | 0 | 12.575 | 1.460 | 45.09 |

Lane expansions are `(cost, goal)`: 165–168 `(11, 2,914)`, 146–149 `(1, 5,889)`, 20–24 `(0, 6,495)`, 76–80 `(1, 5,866)`, 160–170 `(71, 2,834)`. The goal lane did almost all of the expansion. The cost lane expands a low-cost state when that state is behind a worse state on the goal heap. On actions 21–24 the goal order expanded each identity first, so the cost-lane copies were stale pops.

Expansions by segment cost:

| Window | Expanded by g | Deepest expanded | Generated at the deepest stored g |
| --- | --- | ---: | --- |
| 165–168 | 0: 1; 1: 80; 2: 2,844 | 2 | g=2 generated 29,454; g=3 ceiling-pruned |
| 146–149 | 0: 89; 1: 1,591; 2: 4,210 | 2 | g=2 generated 23,344; g=3 ceiling-pruned |
| 20–24 | 0: 2; 1: 68; 2: 786; 3: 5,639 | 3 | g=3 generated 16,050; the heap then emptied |
| 76–80 | 0: 6; 1: 214; 2: 1,328; 3: 4,319 | 3 | g=3 generated 26,500; g=4 ceiling-pruned |
| 160–170 | 0: 4; 1: 8; 2: 17; 3: 11; 4: 7; 5: 5; 6: 1; 7: 24; 8: 502; 9: 2,326 | 9 | g=9 generated 20,623; g=10 ceiling-pruned |

Affinity calls were 19,979, 18,886, 6,539, 18,459, and 19,102. Affinity time was 1.598 s, 1.407 s, 0.447 s, 1.310 s, and 1.460 s, which is 11.1%, 9.5%, 5.3%, 9.3%, and 11.6% of each goal search. Across the five goal runs that is 6.222 s of 64.338 s, about 9.7%. The score did not dominate the search.

`max_h` on the goal run of 160–170 rose to the unreachable sentinel. The uniform-cost run of that window stayed at `h=0`, because it never generated a stock or foundation state the bound rejects. The goal order did generate such states, and the bound pruned 899 of them. That bound is still the deals-only test. Displacement was not consulted.

## 6. What each window establishes

**165–168.** Uniform cost repeated v0.128: 131 expansions, all at g=0, 19,511 generated children at g=1, no rejoin. Goal order expanded 2,844 states at g=2 and ceiling-pruned 194,685 children at g=3. Generated states at g=2 were 29,454, so the g=2 layer was not finished, and most generated g=1 states were never expanded. Children of the expanded nodes were terminal-checked. None was the target. A rejoin hiding behind an unexpanded parent is still possible. Status `INCONCLUSIVE`. `proof` is false.

**146–149.** The same pair of outcomes. Uniform cost expanded 620 states at g=0. Goal order expanded 4,210 states at g=2, generated 23,344 states at g=2, and ceiling-pruned 63,575 children. Zero rejoins. The unique cap fired first. Status `INCONCLUSIVE`.

**20–24, negative control.** Uniform cost finished the graph under ceiling 3: 7,330 unique states, 6,475 expansions, 95,093 ceiling prunes, 855 unreachable-state prunes, 10,500 transpositions, 2 stale pops, 1,954 zero-cost actions, zero rejoins. Those counters match v0.128. There is no path of corrected cost 0, 1, 2, or 3 between these two exact states.

Goal order also emptied the heap. Unique identities are the same 7,330. Expansions are 6,495, generated children 17,850, ceiling prunes 95,450, lower-bound prunes 856, transpositions 10,456, stale pops 49, zero-cost actions 1,958. The extras are re-expansions. The goal lane can expand an identity at a worse `g` first. `seen_expand` then still accepts a later smaller `g`, and best-g dominance still drops an equal or worse arrival. The second expansion regenerates children, which is why generated, ceiling, stale, and expansion counts differ while the identity count matches. The heap finished with no terminal. That is the same negative result inside this ceiling. `proof` and `cost_optimal` are true for both policies. This says nothing about a route that leaves the 172 checkpoint and returns at a later stock boundary.

**76–80.** Uniform cost expanded through g=2 (6, 270, 1,916) and generated 39,815 children at g=3 without expanding that layer. Goal order expanded 4,319 states at g=3 and ceiling-pruned 81,696 children at g=4. Generated states at g=3 were 26,500, so the ceiling layer was entered and not finished. Zero rejoins. Status `INCONCLUSIVE`.

**160–170.** Uniform cost expanded 120 states at g=0 and 128 at g=1. Goal order reached the kernel ceiling: 2,326 expansions at g=9, 20,623 generated states at g=9, and 95,064 ceiling prunes at g=10. The layer is not finished. Zero rejoins. The window overlaps 165–168 and was searched on the original 172 route. Status `INCONCLUSIVE`.

No outcome was a target-state join. No outcome was a join that failed the full-game replay. No candidate was submitted to `verify_complete_solution`. A goal hit found before the heap emptied would have been labeled a legal rejoin of that recorded cost, and `cost_optimal` would have stayed false. None occurred.

## 7. Acceptance

The accept gate was ready and unused. A `FOUND` segment with cost below the played segment would have been spliced as the unchanged prefix, the discovered replacement, and the unchanged incumbent suffix, then replayed from the opening with `verify_complete_solution`. Acceptance required every action legal, stock deals legal, eight foundations, and corrected cost at most 171. Provenance would have been `independently_discovered_segment` for the replacement, `reused_verified_suffix` for the tail, and incumbent-guided for the route. `independent_cold_complete` would have stayed false.

Zero windows met that gate. Overlapping windows were not added. There was no pair of disjoint improvements to combine. The 172 file remains the verified complete solution.

## 8. Diagnosis and the next experiment

The goal order does the job v0.128 could not do inside 20,000 states. It spends unique states on states that look closer to the target pack, and it reaches the incumbent ceiling on 76–80 and 160–170 and the kernel ceiling's parent layer on 165–168 and 146–149. Zero-cost whole-column transfers remain legal. On 165–168 the goal run still generated 21,927 of them. They are no longer the only states the budget can see.

The four unfinished goal windows are still budget-limited. Entering g=2, g=3, or g=9 and finding no rejoin among the children of expanded nodes is evidence against a cheap exact replacement in the sampled region. It is not a proof that every path under the ceiling was examined. Raising the same exact-state cap, or adding another ordering on these same five checkpoints, would keep searching a column-ordered permutation space whose suffix names physical columns. The completed window, actions 21–24, is already proved empty under its ceiling.

The honest follow-up is a later stock-boundary target, with suffix repair when the rejoin is not an exact checkpoint. That experiment was not started. No generalised orbit quotient was introduced to force these windows closed.

## 9. Tests

Focused tests for the cap boundary, displacement ordering, successor coverage, zero-cost legality, deal retention, dominance, and the unknown-policy rejection:

```text
$env:PYTHONPATH = "src"
py -3 -m pytest tests/test_goal_directed_anchored_v0_129.py tests/test_search_kernel_consolidation_v0_57.py tests/test_human_strategy_v0_118.py -q --tb=short
```

37 passed in 2.35 s. The full regression was not run. The documented v0.126 timing-sensitive failure is separate from this run. No new regression was observed in the focused tests. Both historical solution hashes matched Section 1 after the searches.

## 10. Reproduction

From the repository root. The driver inserts `src` on its own path. It writes `artifacts/anchored_v0_129/results.json` and does not write `solutions/`. `artifacts/` is gitignored.

```text
py -3 tools/goal_directed_anchored_v0_129.py
```

The run that produced this report ended:

```text
WROTE artifacts/anchored_v0_129/results.json
ACCEPTED 0 HASHES_OK True
```

The per-window `DONE` lines match the tables in Sections 4 and 5. Numbers in this report are the rounded fields of that JSON.

## 11. Scope left unchanged

`engine.py`, `rules.py`, the Human Strategy Controller, the seven search lanes, and the v0.120 timing test were not edited. Cold whole-game search was not run. The five windows were not replaced with the opening reversal or with checkpoint 114–117. The 172 and 185 solution files and the production incumbent registry were not written.
