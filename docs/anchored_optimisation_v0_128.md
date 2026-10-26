# Anchored optimisation v0.128

Schema `spider-anchored-optimisation-0.128`. Deal `4925153`. Branch `local/anchored-optimisation-v0-128`, started from `5c64ef7fefb8cd1530ad3ff6708f3d642cafba8b` (`5c64ef7 Document agent-managed Git handoff and release workflow`), whose parent is the v0.127 audit `b2f08772fbde4d9dfc91be37b7c54845e7a5fcbe`.

This is an incumbent-guided segment experiment. It is not an `independent_cold_complete` solve. The production incumbent was not overwritten.

## Result

No fully replayed game cheaper than 172 was found. No window produced a target-state rejoin.

| Window | Played cost | Outcome |
| --- | ---: | --- |
| Checkpoint 165–168, actions 166–168 | 3 | Budget-limited, inconclusive |
| Checkpoint 146–149, actions 147–149 | 3 | Budget-limited, inconclusive |
| Checkpoint 20–24, actions 21–24 | 4 | Exhausted. No exact rejoin at cost 3 or less |
| Checkpoint 76–80, actions 77–80 | 4 | Budget-limited, inconclusive |
| Checkpoint 160–170, actions 161–170 | 10 | Budget-limited, inconclusive |

The primary target, a replay-verified complete solution at 171 or fewer corrected MobilityWare moves, was not met. The secondary target is met for one window only: actions 21–24 cannot be replaced by a cheaper path between those two exact states. The other four windows stopped at 20,000 unique states while the search was still far above the segment ceiling, so they are not proofs.

The diagnostic is in the last section. The deals-only segment bound does not prune the interior of these deal-free windows. The incumbent ceiling prunes only after the search expands nodes whose cost is already the ceiling. Uniform-cost order spends the unique budget on zero-cost whole-column rearrangements before that depth is reached. Transposition dominance is active and is not the cap that stops the search.

## 1. Baseline

Repository `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`. Remote `origin` is `https://github.com/Montgomerie-B/spider-solver.git`. One worker. Corrected MobilityWare scoring. `MW_RULES` prices a whole face-up column moved onto an empty column at 0 when that column has no face-down cards.

Both historical solution files were replayed from `deals/4925153.txt` through `replay_actions_detailed` before the searches, and their bytes were hashed again afterwards.

| Route | SHA-256 | Explicit | Tableau | Deals | Foundations | Corrected MW | Legacy MW | Solved |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | 174 | 169 | 5 | 8 | 172 | 163 | yes |
| `solutions/4925153_autonomous_185.moves` | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` | 189 | 184 | 5 | 8 | 185 | 177 | yes |

`verify_complete_solution` accepted the 172 file at expected cost 172, source `imported`. Checkpoint replay also finishes at corrected cost 172. The hashes were unchanged after the five searches. `solutions/` was not written. The incumbent registry was not written.

The v0.126 full-suite failure is unchanged and was not rerun. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` where the assertion expects `TIME_LIMIT` when the whole suite runs. The isolated test has passed before. This experiment does not edit the Human Strategy Controller or that test.

The checkpoint `state_id` stored by `build_checkpoints` is the first 16 hex characters of `pack_state`. On these positions that prefix is a pack header, and the start and end of a window can share it. The search compared full packs. Each endpoint below is identified by the SHA-256 of the full pack, truncated to 16 hex characters, and by the tableau. Face-down cards are listed deepest first. Face-up cards are listed bottom to top, so the last face-up token is the exposed card. Suit letters are the engine's lowercase form.

## 2. The five windows

The coordinates are the five inconclusive spans in Section 19 of `docs/whole_game_optimisation_audit_v0_127.md` and Experiment C of `docs/incumbent_anchored_optimisation_v0_118.md`. Checkpoint `start` is the number of incumbent actions already applied. The played slice is `actions[start:end]`. v0.118 left each of these five `INCONCLUSIVE` at its 2,500 unique-state cap (`unique limit`). That report did not publish per-window expansion counts for the 172 run. The 172 aggregate was expansions 1,809, segment-bound prunes 704, rejoins 0, 6.555 s, peak RSS 33.06 MB, `SEARCH_STATUS=NO_IMPROVEMENT`. Those figures are the 172 run only.

A replacement of segment cost `R` produces a complete-game cost of `prefix + R + suffix`. The suffix is the untouched incumbent tail, so `prefix + suffix = 172 - C`. Any `R <= C - 1` makes the spliced game 171 or less. The saving required on the full game is therefore 1. The kernel ceiling passed by `search_segment` is `C - 1`. The source call to `segment_lower_bound` is 0 on every window: none of the five slices contains a deal, and the foundation multiset at the start is still a subset of the target. `admissible_remaining` was recorded and was not given to the segment search. `proof_prune(prefix, admissible_remaining, 172)` is false at every source, so that whole-game bound does not retire any of these windows.

| Window | Actions | C | Prefix | Suffix | Kernel ceiling | Segment bound | Source `g+h` | v0.118 stop |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 165–168 | 166–168 | 3 | 163 | 6 | 2 | 0 | 170 | unique limit at 2,500 |
| 146–149 | 147–149 | 3 | 144 | 25 | 2 | 0 | 145 | unique limit at 2,500 |
| 20–24 | 21–24 | 4 | 20 | 148 | 3 | 0 | 25 | unique limit at 2,500 |
| 76–80 | 77–80 | 4 | 75 | 93 | 3 | 0 | 79 | unique limit at 2,500 |
| 160–170 | 161–170 | 10 | 158 | 4 | 9 | 0 | 169 | unique limit at 2,500 |

Every played step costs 1. The endpoints do not rejoin each other. No reference action was inserted into the frontier. The root of each search is the source pack alone, at segment cost 0.

### Checkpoint 165–168

Played cost 3. Actions `move 6 8 9`, `move 6 3 1`, `move 8 6 9`. Nine cards leave column 6 for empty column 8, `Ad` then moves from column 6 onto `2d` in column 3, and the nine cards return to column 6. Bonds go from 53 to 55. Foundations stay at 3. Face-down stays 0. Empty columns stay 4, 8 and 9. Stock is empty. Source pack `cbc91e65b2ee399e`. Target pack `ec14d854754265e3`.

Start, g=163, face-down 0, empty [4, 8, 9], foundations spades, diamonds, clubs:

```text
c1: Kh Qh Jh 10h 9h 8h
c2: Kh Qh Jh 10h 9h
c3: 4d 3d 2d
c4: empty
c5: 7h 6h 5h 4h 3h 2h Ah
c6: Ks Qs Jc 10c Ad 9c 8c 7c 6c 5c 4c 3c 2c Ac
c7: 8h 7h 6h 5h 4h 3h 2h Ah Kc Qc Js 10s 9s 8s 7s 6s 5s 4s 3s 2s As
c8: empty
c9: empty
c10: Kd Qd Jd 10d 9d 8d 7d 6d 5d
```

End, g=166. Column 3 is `4d 3d 2d Ad`. Column 6 has lost the buried `Ad` and is `Ks Qs Jc 10c 9c 8c 7c 6c 5c 4c 3c 2c Ac`. The other columns match the start.

### Checkpoint 146–149

Played cost 3. Actions `move 3 10 2`, `move 3 4 7`, `move 10 3 2`. `5h 4h` parks on empty column 10, `Qd`–`6d` moves from column 3 onto `Kd` in column 4, and `5h 4h` returns. Foundations stay at 2. Face-down stays 2. Stock stays 10. Empty column stays 10. Source `g+h` against 172 is 145. Source pack `a5f402cc468330af`. Target pack `3185440fa748062f`.

Start, g=144, foundations spades and diamonds:

```text
c1: Kh Qh Jh 10h 9h 8h
c2: Kh Qh Jh
c3: 4d 3d 2c Ac 6h Qd Jd 10d 9d 8d 7d 6d 5h 4h
c4: fd Ac 2h | Kd
c5: 2c
c6: Ks Qs Jc 10c Ad 9c 8c
c7: 8h 7h 6h 5h 4h 3h 2h Ah Kc Qc Js 10s 9s 8s 7s 6s 5s 4s 3s 2s Ah
c8: 6c 5c 4c
c9: Kc Qc Jc 10c 9c 8c 7c 6c 5c 4c
c10: empty
```

End, g=147. Column 3 is `4d 3d 2c Ac 6h 5h 4h`. Column 4 is `fd Ac 2h | Kd Qd Jd 10d 9d 8d 7d 6d`. The other columns match the start.

### Checkpoint 20–24

Played cost 4. Actions `move 4 8 1`, `move 4 10 1`, `move 8 10 1`, `move 8 4 1`. `3d` moves from column 4 onto column 8 and then to column 10. `4s` moves from column 4 to column 10. `4h` moves from column 8 back onto column 4, which reveals `2h`. The column-inverse pair is `move 4 8 1` with `move 8 4 1`. Those two moves are not the same card. Foundations stay 0. Face-down falls from 25 to 24. The empty column closes. Stock stays 50. Source pack `4c83edf2c4c10b68`. Target pack `e8f85116226176bf`.

Start, g=20:

```text
c1: fd 10c Qd 6c 8s 5c | 2s
c2: fd 5h 9h Jh Ah 8d | Kd Qs Jd
c3: fd Jc | 7d
c4: fd Ac 2h Kd 10h 6h | 7h 6s 5h 4s 3d
c5: fd 6d Ks 3h 4c | Kc Qc Jc 10c 9c 8c 7c
c6: Qs
c7: fd 8h 6c 10s 10d | 8d 7s 6s 5s 4s 3s 2s
c8: fd 2h | 4h
c9: 3d 2c Ac
c10: empty
```

End, g=24. Column 4 is `fd Ac 2h Kd 10h 6h | 7h 6s 5h 4h`. Column 8 is `2h`. Column 10 is `4s 3d`. The other columns match the start.

### Checkpoint 76–80

Played cost 4. Actions `move 6 1 2`, `move 6 5 1`, `move 5 6 2`, `move 1 6 2`. `Jc 10c` parks on empty column 1. `Qs` moves onto `Ks`, then `Ks Qs` moves back onto the now empty column 6 and reveals `6d`. `Jc 10c` returns onto `Qs`. Foundations stay 0. Face-down falls from 9 to 8. Empty column stays 1. Stock stays 40. Source pack `90fb3bef8a9d42b9`. Target pack `cd5334b351570423`.

Start, g=75:

```text
c1: empty
c2: fd 5h 9h Jh Ah 8d | Kd Qs Js 10s 9s 8s 7s 6s 5s 4s 3s 2s
c3: 4d 3d 2c Ac
c4: fd Ac 2h Kd | 10h Kh Qd Jd 10d 9d 8d 7d 6d
c5: fd 6d | Ks
c6: Qs Jc 10c
c7: 8h 7h 6h 5h 4h 3h 2h
c8: 6c
c9: Kc Qc Jc 10c 9c 8c 7c 6c 5c 4c 8s 7d 6s
c10: 4s 3d 2s 5c 4d
```

End, g=79. Column 5 is `6d`. Column 6 is `Ks Qs Jc 10c`. The other columns match the start.

### Checkpoint 160–170

Played cost 10. This span contains actions 166–168, so it overlaps checkpoint 165–168. It was searched on the original 172 route after the four shorter windows returned no splice. Actions, each of cost 1:

`move 3 4 1`, `move 3 5 3`, `move 1 5 3`, `move 3 6 2`, `move 4 3 1`, `move 6 8 9`, `move 6 3 1`, `move 8 6 9`, `move 6 4 11`, `move 3 10 4`.

The last action is the second diamond removal. Foundations go from 3 to 4. Face-down stays 0. Empty columns go from [4, 8, 9] to [3, 8, 9, 10]. Stock is empty. Bonds go from 49 to 44. Source `g+h` against 172 is 169, so the whole-game bound leaves 3 of slack and does not forbid a 171-move finish from this checkpoint. Source pack `835bdfdf60a53114`. Target pack `5fcd364fe5a1913a`.

Start, g=158, foundations spades, diamonds, clubs:

```text
c1: Kh Qh Jh 10h 9h 8h 3h 2h Ah
c2: Kh Qh Jh 10h 9h
c3: 4d 3d 2c Ac 6h 5h 4h 2d
c4: empty
c5: 7h
c6: Ks Qs Jc 10c Ad 9c 8c 7c 6c 5c 4c 3c
c7: 8h 7h 6h 5h 4h 3h 2h Ah Kc Qc Js 10s 9s 8s 7s 6s 5s 4s 3s 2s As
c8: empty
c9: empty
c10: Kd Qd Jd 10d 9d 8d 7d 6d 5d
```

End, g=168, foundations spades, diamonds, clubs, diamonds:

```text
c1: Kh Qh Jh 10h 9h 8h
c2: Kh Qh Jh 10h 9h
c3: empty
c4: Jc 10c 9c 8c 7c 6c 5c 4c 3c 2c Ac
c5: 7h 6h 5h 4h 3h 2h Ah
c6: Ks Qs
c7: 8h 7h 6h 5h 4h 3h 2h Ah Kc Qc Js 10s 9s 8s 7s 6s 5s 4s 3s 2s As
c8: empty
c9: empty
c10: empty
```

## 3. Search contract

Each window called the existing `search_segment` with `exhaustive=True`, `max_unique=20000`, `time_limit_s=30`, `rss_abort_mb=3072`, and one worker. `exhaustive=True` keeps every rejoin until the graph or a budget ends, then `search_segment` keeps the cheapest. No rejoin occurred, so first-terminal stopping would have returned the same status.

The call is the existing machinery:

- Identity `pack_state`.
- Terminal test `pack_state` plus `canonical_state_key`. Column order is part of the key. `pack_post_stock_symmetry_state` is not used. Duplicate suit-rank copies are not distinct in the rejoin key.
- Successors `all_legal_actions`, including a legal deal.
- Order `step_cost`, then the action text. A zero-cost whole-column transfer sorts ahead of a cost-1 action.
- Lower bound `segment_lower_bound`: the exact number of deals needed to leave the target stock, or an unreachable sentinel when the stock or the foundation multiset cannot become the target. Face-down reveals are not added.
- Kernel ceiling `C - 1`. A child with `child_g` above that ceiling is not stored.
- Transposition: a child whose pack is already stored at an equal or better `g` is dropped.

Suit proximity, workspace score, and backward-planning preference were not used as bounds. No state was removed because it looked strategically unattractive.

The counters `ceiling_prunes`, `zero_cost_actions`, `expanded_by_g`, and `generated_by_g` were added to the existing kernel. They do not change which child is stored, expanded, or accepted. `SegmentResult` now carries those counts plus the peak RSS the kernel already measured. A final RSS sample was added so a short search still records a peak.

One existing kernel detail matters at the cap. `unique` increments before the child is stored. The child that makes `unique` reach 20,000 is discarded and is not tested as a terminal. A unique-limit stop therefore leaves one generated child unexamined. That single omission does not turn the stop into an exhaustion proof.

## 4. Comparison

Search time is the segment search only. Peak RSS is the kernel's working-set sample. The process stayed near 45 MB. The 3,072 MB cap did not bind. The 30-second cap did not bind.

| Window | Status | Stop | Expanded | Unique | Generated | Ceiling prunes | Lower-bound prunes | Transpositions | Stale | Zero-cost actions | Rejoins | Cheapest R | Seconds | Peak MB |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 165–168 | `INCONCLUSIVE` | unique limit | 131 | 20,000 | 21,476 | 0 | 49 | 1,438 | 0 | 1,965 | 0 | none | 5.557 | 45.20 |
| 146–149 | `INCONCLUSIVE` | unique limit | 620 | 20,000 | 23,547 | 0 | 620 | 3,428 | 0 | 3,100 | 0 | none | 6.105 | 45.20 |
| 20–24 | `EXHAUSTED` | complete | 6,475 | 7,330 | 17,831 | 95,093 | 855 | 10,500 | 2 | 1,954 | 0 | none | 8.609 | 45.20 |
| 76–80 | `INCONCLUSIVE` | unique limit | 2,192 | 20,000 | 47,699 | 0 | 2,192 | 27,700 | 0 | 690 | 0 | none | 9.252 | 45.20 |
| 160–170 | `INCONCLUSIVE` | unique limit | 248 | 20,000 | 26,782 | 0 | 0 | 6,783 | 0 | 2,108 | 0 | none | 5.504 | 45.20 |

Expansions by segment cost `g`:

| Window | g=0 | g=1 | g=2 | g=3 | Generated g |
| --- | ---: | ---: | ---: | ---: | --- |
| 165–168 | 131 | 0 | 0 | 0 | 0: 1,965; 1: 19,511 |
| 146–149 | 620 | 0 | 0 | 0 | 0: 3,100; 1: 20,447 |
| 20–24 | 2 | 68 | 785 | 5,620 | 0: 2; 1: 96; 2: 1,702; 3: 16,031 |
| 76–80 | 6 | 270 | 1,916 | 0 | 0: 12; 1: 426; 2: 7,446; 3: 39,815 |
| 160–170 | 120 | 128 | 0 | 0 | 0: 1,080; 1: 14,828; 2: 10,874 |

`min_h` was 0 on every window. `max_h` was the unreachable sentinel `1,000,000` on the first four windows and 0 on checkpoint 160–170. Lower-bound prunes are states whose stock or foundation multiset cannot become the target. They are not a positive deal-count cut. The source bound was already 0.

## 5. What each window establishes

**165–168, budget-limited.** All 131 expansions are at segment cost 0. The search generated 19,511 cost-1 children of those free positions and did not expand any of them. A cost-1 rejoin would have been recorded while those children were generated. None was. A cost-2 path was never expanded. The zero-cost component itself was not finished. The 9-card park is not proved necessary, and no cheaper exact replacement was found. Ceiling prunes are 0 because a single legal step from `g=0` costs 0 or 1, and the kernel ceiling is 2.

**146–149, budget-limited.** The same shape, with a smaller free set: 620 expansions, all at `g=0`, 3,100 zero-cost actions, 620 unreachable-state prunes, no ceiling prunes, no rejoin. Cost-2 paths were not expanded.

**20–24, exhausted.** The graph under ceiling 3 finished. Unique states stayed at 7,330, below the cap, in 8.609 s. Expansions reached `g=3`, and 95,093 children that would have cost 4 were pruned by the incumbent ceiling. 855 states were unreachable for the target stock or foundations. 10,500 children lost the transposition test. Two stale heap entries were skipped. Zero rejoins. There is no path of corrected cost 0, 1, 2, or 3 from this exact start state to this exact end state. The played four moves are a negative result inside that ceiling. This says nothing about a route that leaves the 172 checkpoint and returns at a later stock boundary.

**76–80, budget-limited.** Expansions reached `g=2` and generated 39,815 children at the ceiling `g=3`. None of those stored children was the target. Nodes at `g=2` were still unexpanded when the unique cap fired: 7,446 states at `g=2` had been generated and 1,916 had been expanded. Some ceiling-cost children therefore do not exist in this sample. Ceiling prunes stayed 0 because the search never expanded a node already at `g=3`. The 2,192 lower-bound prunes are unreachable states. 27,700 transpositions show that dominance is doing real work. The distinct remainder still hit 20,000 states.

**160–170, budget-limited.** The ceiling is 9. Expansions reached only `g=1`. Generated states reached `g=2`. Lower-bound prunes are 0 and ceiling prunes are 0: every stored state has `h=0` and `g` far below 9, and stock is already empty so a deal is not a way to change `h`. The free-transfer component, with three empty columns and no face-down cards, filled the budget. Overlap with 165–168 does not matter here, because neither window returned a splice.

No outcome was a target-state join that failed to save a move. No outcome was a join that failed the full-game replay. No candidate was submitted to `verify_complete_solution`, because `search_segment` returned no `FOUND` segment.

## 6. Acceptance and combination

The accept gate was ready and unused. A `FOUND` segment would have been spliced as the unchanged prefix, the discovered replacement, and the unchanged incumbent suffix, then replayed from the opening with `verify_complete_solution`. Acceptance would have required every action legal, stock deals legal, eight foundations, corrected cost at most 171, and provenance recorded as an incumbent-guided splice. The replacement would have been marked `independently_discovered_segment`. The tail would have been marked `reused_verified_suffix`. The route would not have been marked `independent_cold_complete`.

Zero windows met that gate. Overlapping windows were not added together. There was no pair of disjoint improvements to combine. The 172 file remains the verified complete solution.

## 7. Diagnosis

Safe pruning, transposition, and state expansion are not failing in the same way.

The incumbent ceiling is effective when the search can reach it. On actions 21–24 it rejected 95,093 edges and the graph then finished with no rejoin. On the other four windows the ceiling rejected nothing, because the unique cap arrived while every expanded node still had room under `C - 1`. A one-step legal move costs 0 or 1, so ceiling prunes begin only when a node at `g = C - 1` is expanded.

The segment lower bound does not cut ordinary positions in these windows. It is 0 wherever the target stock can be reached with no further deal and the foundations already present are still present at the target. `g + 0` stays inside the ceiling for every node the kernel is willing to store. The bound does reject states that have dealt off the target stock or removed a foundation sequence the target does not have. That is the whole of the 49, 620, 855, and 2,192 lower-bound prunes. Checkpoint 160–170 never generated such a state. Adding face-down or foundation obligations on top of the deal count would be the inadmissible sum `segment_lower_bound` already refuses to make. `admissible_remaining` at the window source is also too weak to prune against 172: the tightest of the five is `163 + 7 = 170`.

Transposition handling is doing what the kernel claims. Equal or worse arrivals are dropped at generation (`duplicate_skips`), which is why stale heap pops stay at 0 or 2. On actions 77–80 more than half of the generated children were duplicates. The survivors are still distinct packs. Column-ordered identity is required, because a suffix names physical columns. The post-stock symmetry pack would treat a free rearrangement as the same state and would make an exact suffix illegal to reuse. It was correctly left unused. The distinct free rearrangements are the bulk of the 20,000 states.

Zero-cost expansion is the limiter. The lane key is `(g,)`, and `step_cost` orders a free whole-column transfer first. That is the right order for a cheapest-path proof: every cost-0 state has to be expanded before a cost-1 state can be treated as settled. At actions 166–168 and 161–170 the board has several empty columns and no face-down cards, so every whole column can move to an empty column for free. A few hundred such expansions generate tens of thousands of distinct children and the cap stops the search at `g=0` or `g=1`. Memory and wall time are not the constraint. The 30-second and 3,072 MB allowances both had margin.

Nothing in the five runs shows an incorrect accept, a preloaded reference path, or a rejoin that the full-game gate would need to reject. The anchored optimiser, at this budget, cannot see past its own free-transfer component on the four unfinished windows. Raising the unique cap again would still be spent on those permutations before a cost-2 or cost-9 proof could close. The audit's next step, a later stock-boundary target rather than another exact checkpoint of the same span, is the honest follow-up. It was not started here.

## 8. Tests

Focused tests for the counter change and the anchored contract:

```text
$env:PYTHONPATH = "src"
py -3 -m pytest tests/test_search_kernel_consolidation_v0_57.py tests/test_human_strategy_v0_118.py -q --tb=line
```

31 passed in 2.14 s. The new kernel test checks that a partial move onto an empty column increments `ceiling_prunes` under ceiling 0, and that the whole-column transfer increments `zero_cost_actions` and is still generated. The existing v0.118 anchored tests passed with the extra `SegmentResult` fields.

The full regression was not run. The documented v0.126 timing-sensitive failure is separate from this run. No new regression was observed in the focused tests. Both historical solution hashes matched the values in Section 1 after the searches.

## 9. Reproduction

From the repository root. The driver inserts `src` on its own path. It writes `artifacts/anchored_v0_128/results.json` and does not write `solutions/`. `artifacts/` is gitignored.

```text
py -3 tools/anchored_optimisation_v0_128.py
```

The run that produced this report printed:

```text
DONE 165-168 status=INCONCLUSIVE stop=unique limit expanded=131 unique=20000 generated=21476 ceiling_prunes=0 lb_prunes=49 transpositions=1438 stale=0 zero_cost=1965 rejoins=0 best=None elapsed=5.557 peak=45.203125
DONE 146-149 status=INCONCLUSIVE stop=unique limit expanded=620 unique=20000 generated=23547 ceiling_prunes=0 lb_prunes=620 transpositions=3428 stale=0 zero_cost=3100 rejoins=0 best=None elapsed=6.105 peak=45.203125
DONE 20-24 status=EXHAUSTED stop=complete expanded=6475 unique=7330 generated=17831 ceiling_prunes=95093 lb_prunes=855 transpositions=10500 stale=2 zero_cost=1954 rejoins=0 best=None elapsed=8.609 peak=45.203125
DONE 76-80 status=INCONCLUSIVE stop=unique limit expanded=2192 unique=20000 generated=47699 ceiling_prunes=0 lb_prunes=2192 transpositions=27700 stale=0 zero_cost=690 rejoins=0 best=None elapsed=9.252 peak=45.203125
DONE 160-170 status=INCONCLUSIVE stop=unique limit expanded=248 unique=20000 generated=26782 ceiling_prunes=0 lb_prunes=0 transpositions=6783 stale=0 zero_cost=2108 rejoins=0 best=None elapsed=5.504 peak=45.203125
ACCEPTED 0 COMBINATIONS 0 HASHES_OK True
```

## 10. Scope left unchanged

No new solver, heuristic, strategic controller, or search architecture was added. `engine.py`, `rules.py`, the Human Strategy Controller, the seven search lanes, and the v0.120 timing test were not edited. The 185 route was replayed and then left unused as a donor. Cold whole-game search was not run. The five windows were not replaced with the opening reversal or with checkpoint 114–117.
