# Method capture and optimisation for deal 4925153

Outcomes:

- `METHOD_CAPTURED`
- `COLD_REPRODUCTION_COMPLETE`
- `NO_VERIFIED_IMPROVEMENT`

The best verified cost remains 158. This campaign's own cold reproduction finished a validated 164-move game with the same action hash as the historical 164 route. No later search produced a complete legal game below 158. Optimality is unestablished. A unique cap, a paid ceiling, a sampled reseed, and an empty heap under a paid ceiling are not impossibility proofs.

Branch `local/method-capture-optimisation`. The recipe was frozen at `2220a360a6e528560e34f99f25083336909546a3` before search behaviour changed. Issue #26 stays open. Nothing was merged.

## Recipe

`docs/whole_game_method_v1.md` and `docs/research/method_capture_optimisation/method_v1.json` record `search_suit_ordered` as the reference. The kernel was not copied. Advice is off. The recorded seed is not an input to successor order. Identity is `pack_whole_game_identity`, storage is ordered `pack_state`, and successors are `all_legal_actions`. The paid cold ceiling is 400. Suit proximity orders the foundation lane only.

The historical 158 file was not rewritten. Working-tree CRLF SHA-256 `C5F4059E8288A8160449F5ACF2E8F8B3848368A63A1A99FAE8132E0358492CC1`. Git LF SHA-256 `D1CBE17BEDCA6625DD48223685908EB07C46990A70E0638A57F7E7C4AF19BD21`. Git blob `83430885e4c65b2c986b1cfa2b786914da256cb8`. Path hash `9145868d32e42008`. A fresh replay before the improvement search confirmed cost 158, eight foundations, and that those actions were not passed into the search.

## Commands

Cold reproduction:

```text
py -3 tools/autonomous_solve_campaign.py --mode cold --deal deals/4925153.txt --time-limit 1500 --max-unique 1000000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 600 --fresh
```

Fresh-opening improvement:

```text
py -3 tools/autonomous_solve_campaign.py --mode opening-improve --deal deals/4925153.txt --incumbent-cost 158 --cost-ceiling 157 --authenticate docs/research/autonomous_solve_campaign/4925153_cold_158.moves --time-limit 3600 --max-unique 1200000 --memory-mb 3000 --checkpoint-s 600
```

Route repair:

```text
py -3 tools/autonomous_solve_campaign.py --mode repair --route docs/research/autonomous_solve_campaign/4925153_cold_158.moves --time-limit 1800 --max-unique 60000 --memory-mb 3000 --repair-span 64 --repair-stride 16 --repair-windows 8 --window-s 180 --medium-s 300
```

Continuations use `--mode continue`. Exact frontier resume is not implemented. `resume_kind` is `sampled_reseed`.

## Machine

Windows, 8 CPUs, 16264.7 MB total. The probe is `GlobalMemoryStatusEx`. One worker, no child process. The aggregate cap is the lesser of the request, 8 GiB, and 40 percent of available RAM. Applied caps were 3000 MB, or 2976 MB when available RAM made 40 percent smaller. Legacy launches that omit `--mode` still use only the 40 percent clamp.

## Attempts

| Id | Kind | Stop | Solved | Elapsed | Unique | Peak RSS | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| a1 | cold opening | time limit | 164 | 1502 s | 644,476 | 1397 MB | validated, path hash `e56a441f03423876` |
| a2 | scalar opening, ceiling 157 | unique limit | no | 2922 s | 1,200,000 | 2441 MB | max 5 foundations |
| a3 | route repair of 158 | no improvement | no | 686 s | 60,000 per window | not recorded | 7 overlapping windows |
| a4 | labelled reseed, prefix not passed | unique limit | no | 405 s | 250,000 | not the intended search | fresh opening under ceiling 157 |
| a5 | reseed of the 155-move branch | heap empty under paid ceiling | no | short | 192 | 31 MB | that prefix has no finish at 157 |
| a6 | reseed of the 145-move branch | unique limit | no | 624 s | 400,000 | 715 MB | reached 7 foundations |
| a7 | same 145-move branch, cap 1,000,000 | unique limit | no | 1718 s | 1,000,000 | 1779 MB | still 7 foundations |

a1 expanded 181,905 states, generated 4,975,906, and made 119 zero-cost admissions. Lower-bound prunes were 0. `min_live_g` was 7. Lane pops were balanced. The candidate is `4925153_cold_feasibility_164.moves`, independently validated at corrected cost 164 with 5 deals and 8 foundations. `best_complete` holds that game. The best unfinished branch at the end of a1 was 7 foundations at cost 160, so a continuation does not restart the solved line.

a2 authenticated the scalar 158. `action_guidance` is none. `published_route_read` is false. The kernel's historical string `imported_verified_complete` is recorded beside those fields and does not mean a published file was read. Proof prunes were 1,095,889. Ceiling prunes were 0. Lanes stayed balanced. `min_live_g` was still 7. The deepest retained stock-empty branch had 5 foundations at cost 145. RSS was 2441 MB of a 3000 MB cap, so a fresh opening with a much higher identity cap would repeat this tree and then hit memory. That repeat was not run.

The 158 route has deals at actions 21, 51, 54, 55, and 58. Stock is empty from action 58 through 158. Repeated states at a higher cost: 0. a3 examined windows 0–64, 16–80, 32–96, 48–112, 64–128, 80–144, and 96–158. Each stopped on 60,000 unique states with the recorded lower-bound prune count at 0. Prefix, replacement, and suffix costs are recomputed before a splice is accepted. None was accepted.

a4 stored a 155-move prefix and then called the search without it. The kernel provenance is `partial_legal_search`. That attempt is not a reseed. The fix keeps `prefix_actions` on continuation calls.

a5 replayed the 155-move, 6-foundation, stock-empty branch. Provenance `checkpoint_continuation`. All seven lane heaps ended empty. Stop class `heap_empty_under_paid_ceiling`. 192 unique states. This shows that prefix cannot finish at cost 157. It does not show that every line from the opening fails.

a6 replayed the 145-move, 5-foundation branch from the ceiling-157 search. Provenance `checkpoint_continuation`. It reached 7 foundations, considered 573,216 zero-cost actions, admitted 0 zero-cost edges, and applied 2,689,561 ceiling prunes. `min_live_g` was 149. `closed_g` 148 is the heap observation `min_live_g - 1`, not a closure proof. Peak RSS was 715 MB.

a7 repeated that prefix with a 1,000,000 unique cap because a6 had stopped on the cap while memory was well below 3000 MB. It ran 1718 seconds, expanded 236,823 states, generated 6,153,815, and peaked at 1779 MB. Ceiling prunes were 8,703,067. Lower-bound prunes were 0 because a continuation does not install the admissible bound. Maximum foundations stayed 7. `min_live_g` was 150. The best partial replay reached cost 157 and was not a solved game. A third pass of this prefix would repeat the same million states. It was not run.

## Bottleneck

The opening search under ceiling 157 is limited by identity memory: 1.2 million states used 2441 MB, lanes stayed balanced, and the admissible bound pruned about 1.1 million children without proving the ceiling. The 158 repair is limited by the per-window identity cap; the stock-empty tail is 100 moves and contains no repeated higher-cost state for a cycle splice. The useful unfinished prefix at cost 145 can reach 7 foundations and then spends the state budget on ceiling-feasible moves, including hundreds of thousands of considered zero-cost actions and no admitted zero-cost edges. `seed` still does not change successor order.

## Checks

The maintained regression is the 31 files in the v0.123 command plus 29 later modules, including `tests/test_method_capture.py`: 60 files. It is not the whole suite. Result: 767 passed, 0 failed, 401.51 seconds. The previous 59-file selection was 752 passed. The added passes are the method-capture tests. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can report `PLANNING_STALL` instead of `TIME_LIMIT` (issue #6). These eight modules still fail collection and were not edited: `test_exact_state_policy_context_equivalence_v0_1.py`, `test_one_shot_natural_empty_service_v0_1.py`, `test_one_shot_natural_r3_service_v0_1.py`, `test_workspace_opportunity_service_lane_v0_1.py`, `test_workspace_service_generalisation_panel_v0_1.py`, `test_workspace_service_lag1_grace_v0_1.py`, `test_workspace_service_stock_guard_v0_1.py`, `test_workspace_service_stock_synchronous_v0_1.py`.

## What remains unfinished

`exact_frontier_retained` is false. The ledger keeps replayable unfinished branches and a ring of untried states. A default continuation skips solved terminals, skips a prefix whose cost is already over the ceiling, and skips a prefix whose paid-ceiling heap already emptied. Canonical, autonomous 185, and g123 actions were not loaded into the cold or scalar searches.
