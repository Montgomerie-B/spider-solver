# Autonomous solve campaign for deal 4925153

Category: `INDEPENDENT_COMPLETE_FOUND`.

The best verified route costs 158 corrected MobilityWare moves and has 158 actions: 153 tableau moves, 5 deals, and 8 automatic sequence removals. Independent `validate_solution` replay leaves 8 foundations, an empty stock, and an empty tableau. Optimality is unestablished. A later 15-minute search under a paid ceiling of 157 did not finish a cheaper game.

The first complete route from the opening cost 164. Ceiling searches then found 162, 160, and 158. None of those searches read `solutions/4925153_canonical.moves`, `solutions/4925153_autonomous_185.moves`, or the known g123 prefix.

## Machine and budgets

This machine has 8 CPUs and 16264.7 MB of RAM. Available memory at the opening search was 8457.2 MB. The RSS cap was 3000 MB, below 40 percent of the memory available at launch. Every search used one worker.

The opening search did not inherit the production 171 or 185 ceiling. Its paid ceiling was 400. That ceiling is not a proof. Proof pruning was off. After a verified route existed, later searches used that route's corrected cost minus one as the paid ceiling and `admissible_remaining` as `h`. A state is pruned only when `g + h` is strictly greater than the ceiling.

## Opening search

```
py -3 tools/autonomous_solve_campaign.py --deal deals/4925153.txt --time-limit 1500 --max-unique 1000000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 300 --status docs/autonomous_solve_campaign_status.json
```

The run lasted 1501.9 seconds and stopped on the time limit. It admitted 699,970 identities, expanded 200,073, and generated 5,439,427 successors. Peak RSS was 1565 MB. Deal actions admitted: 80,087. Tableau actions admitted: 816,757. The search neither always dealt nor refused to deal.

The kernel considered 872,276 zero-cost legal actions and admitted 119 states reached by a zero-cost step. A repeated identity at the same or higher `g` is a duplicate, not a new cycle. Zero-cost moves did not trap the search.

`lower_bound_prunes` was 0 and `ceiling_prunes` was 0. At the stop, each lane still held about 857,000 heap entries and the heap tops showed `g = 7`. That figure is not a proof that every cheaper state was expanded, and the saved checkpoint is not the kernel heap. Resume is a sampled reseed of verified prefixes. A restart does not inherit an exhaustion claim.

The first finished game was visible at the 300-second checkpoint and was still the cheapest terminal at the end: corrected cost 164, 159 tableau moves, 5 deals. `validate_solution` accepted it. File SHA-256 `5BC761FDB750A9FCDB9236706E4DD25EA8B8C83A91C75C564898695FF4488BE6`. Action-sequence hash `e56a441f03423876`.

This was not a rerun of the published 80,000-identity suit probe. That probe stopped at 4 foundations and corrected cost 139. The known g123 campaign route stays reference-conditioned and was not loaded.

## Optimisation

Anchored segment search on the 164-move file examined 6 windows, ran for 248.5 seconds, and returned `NO_IMPROVEMENT`. Peak RSS was 62 MB.

The same suit-ordered kernel was then started from the opening with `mode="optimise"`, `max_unique=800000`, and `rss_abort_mb=3000`. The incumbent was the campaign cost, not a published file.

| Ceiling | Seconds | Unique | Peak RSS | Proof prunes | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| 163 | 1200.1 | 514,088 | 989 MB | 1,309,694 | verified 162 |
| 161 | 900.1 | 385,342 | 761 MB | 943,488 | verified 160 |
| 159 | 900.1 | 435,936 | 850 MB | 762,596 | verified 158 |
| 157 | 900.1 | 472,757 | 906 MB | 353,044 | unfinished, 5 foundations |

`search_suit_ordered` still labels optimise mode `imported_verified_complete`. That string is the historical mode label. These four runs started from the deal and used a campaign cost as the ceiling.

Anchored search on the 158-move file examined 5 windows, ran for 239.3 seconds, and returned `NO_IMPROVEMENT`.

## Verified routes

| Corrected cost | Actions | Tableau | Deals | File SHA-256 | Action hash |
| ---: | ---: | ---: | ---: | --- | --- |
| 164 | 164 | 159 | 5 | `5BC761FDB750A9FCDB9236706E4DD25EA8B8C83A91C75C564898695FF4488BE6` | `e56a441f03423876` |
| 162 | 162 | 157 | 5 | `3BD1308C5953C0F970035DFE69ACDAF7B8C423893842004BF1253D0417E10F94` | `f5c01d7af0713b15` |
| 160 | 160 | 155 | 5 | `46C98EA85C3749ED5E30173F49425CD596AF1CAB3DD28FB3AB356FEFD936C00E` | `c521042076b473dc` |
| 158 | 158 | 153 | 5 | `C5F4059E8288A8160449F5ACF2E8F8B3848368A63A1A99FAE8132E0358492CC1` | `9145868d32e42008` |

The moves live in `docs/research/autonomous_solve_campaign/`. Each file was replayed with `validate_solution` on deal `4925153`. Action count is reported separately from corrected cost; on these four routes every action cost 1, so the two numbers match. The production solution files and the incumbent registry were not modified.

158 is cheaper than the published canonical 172 and the published autonomous 185. Those files were not inputs. The comparison does not prove that 158 is optimal.

## Resume

Opening checkpoint and later attempt records: `docs/autonomous_solve_campaign_status.json`.

`exact_frontier_retained` is false. `restart_inherits_exhaustion` is false. A time limit, a unique cap, or a memory cap is not a closed component.

Another ceiling search from the opening, using the verified 158 as the incumbent:

```
py -3 -c "import sys; sys.path.insert(0,'src'); from spider.global_search_experiment import search_suit_ordered; from spider.research_actions import opening_from_deal; print(search_suit_ordered(opening_from_deal('deals/4925153.txt'), time_limit_s=1800, max_unique=800000, rss_abort_mb=3000, mode='optimise', incumbent_cost=158, cost_ceiling=157).to_dict())"
```

Anchored search of a campaign route, which refuses a path under `solutions/`:

```
py -3 tools/autonomous_solve_campaign.py --deal deals/4925153.txt --optimise-incumbent docs/research/autonomous_solve_campaign/4925153_cold_158.moves --time-limit 600 --max-unique 40000 --memory-mb 3000 --window-s 30 --medium-s 60 --max-windows 40 --adaptive --status docs/autonomous_solve_campaign_status.json
```

## Control JSON

`tests/test_cycle_escape_play.py` now accepts both line-ending forms of `docs/practical_witness_play_pilot.json`. The spec's recorded `control_sha256` stays the historical CRLF digest `CB3679168F2E90F3D24D870AA060300CD5B8D6292335B0C491460B7ECEA39BB6`. The LF normalization hashes to `E736A8A37828554A4C5064FC58C147DA36F1699D73A3BE4222AC37C11D76351F`. The pilot file was not rewritten.

## Tests and baseline failures

Campaign contract tests cover Deal generation, more than one successor, lower-`g` retention, a paid ceiling that is not a proof, checkpoint reload, physical replay, rejection of a tampered or foreign resume, and refusal of a published route path. Cold campaign source does not name the canonical or 185 files.

The maintained regression command is the 31-file list in `docs/strategic_continuity_v0_123.md`, plus the v0.124–v0.126 and v0.129–v0.139 files, the dependency PR2/PR3/PR4 and inventory files, the three practical-witness files, `tests/test_cycle_escape_play.py`, `tests/test_cycle_escape_play_lock.py`, and `tests/test_autonomous_solve_campaign.py`. That is 59 files. One run with `PYTHONPATH=src` and `-p no:cacheprovider` passed 752 tests in 253.43 seconds. The previous 58-file selection, without the new campaign file, was 744 passed.

`tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` instead of `TIME_LIMIT`. That is issue #6. The test was not weakened.

A fresh collection of these eight modules still fails, in 3.89 seconds, and they were not edited: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `tests/test_one_shot_natural_empty_service_v0_1.py`, `tests/test_one_shot_natural_r3_service_v0_1.py`, `tests/test_workspace_opportunity_service_lane_v0_1.py`, `tests/test_workspace_service_generalisation_panel_v0_1.py`, `tests/test_workspace_service_lag1_grace_v0_1.py`, `tests/test_workspace_service_stock_guard_v0_1.py`, `tests/test_workspace_service_stock_synchronous_v0_1.py`.

## Scope left unchanged

No merge. Issues #21–#25 stay open. `AGENTS.md` was not edited. The cycle-escape verdict and the practical-witness control verdict were not rerun or relabelled.
