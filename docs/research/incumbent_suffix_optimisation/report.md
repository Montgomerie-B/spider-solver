# Incumbent suffix optimisation for deal 4925153

The action-120 search found a complete game of 157 corrected MobilityWare moves. Independent replay from the original opening confirms it: 8 foundations, empty stock, empty tableau, path hash `89c75b02b80f1271`. The best verified cost was 158. It is now 157. Optimality is unproved.

The route is `docs/research/incumbent_suffix_optimisation/4925153_assisted_157.moves`. It shares the first 121 actions with the authenticated 158 game and then departs. The completing witness is the 158 route at action 151, hash `9145868d32e42008`. The search reached that physical state one corrected move cheaper and appended the verified suffix. The suffix cost was an upper bound, not an admissible lower bound.

## Replay

`validate_solution` and a second replay through `opening_from_deal` agree.

| Check | Value |
| --- | ---: |
| Corrected MobilityWare moves | 157 |
| Explicit commands | 157 |
| Tableau moves | 152 |
| Deals | 5 |
| Automatic foundation removals | 8 |
| Foundations | 8 |
| Stock remaining | 0 |
| Tableau empty | yes |
| Path hash | `89c75b02b80f1271` |
| Final state hash | `4e9861540eac570cb` |

Working-tree file: 1,980 bytes, CRLF. Raw SHA-256 `78BB38022565792BFE6A30813172667E2C8FDB15BC609BCE7899B50F22CF60CD`. LF SHA-256 `08F57DBB7BABA8899EC1D7F01267D9816526E55316431CC0AB14E5D549F8BB6B`. Git blob `34c4510cab64a5cb243e66e87faeef2a7751f6a9`.

## Attempts

One worker. Compact representation. Seven-lane suit order. Advice off. Seed 0 recorded and not wired into successor order. Ceiling at launch 157, incumbent 158. A suffix match publishes only after a full opening replay, then the live ceiling becomes that cost minus one. Host: Windows, Python 3.14, 8 CPUs, `GlobalMemoryStatusEx` total 17,054,756,864 bytes (16,264.7 MB). Requested RSS 3,000 MB. The applied cap was 3,000 MB on every attempt. Peak RSS stayed far below it.

Source commit for every attempt: `17b7e9f30731ea9b252045b03f7d38abbf2ce09b`. `git status` was dirty because this output directory was untracked. The hashed sources match that commit.

| Attempt | Prefix | g, h, f | Stop | Time s | Unique | Expanded | Generated | Proof prunes | Suffix hits | Accepted | Peak RSS MB |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| p1 | 140 | 140, 17, 157 | complete | 0.031 | 1 | 1 | 51 | 47 | 1 | 0 | 29.94 |
| p2 | 130 | 130, 23, 153 | complete | 38.133 | 2,800 | 2,823 | 69,897 | 57,709 | 22 | 0 | 40.64 |
| p3 | 120 | 120, 28, 148 | complete | 1,036.599 | 135,206 | 135,933 | 2,526,733 | 1,699,092 | 29 | 1 | 324.13 |

Prefix hashes: action 140 `ae95aea3d623d496`, action 130 `35881216a9aedfe2`, action 120 `66beed80ed3cfa17`. Each root is the physical state of the authenticated 158 route at that action.

Action 140 is the last own-route prefix with `g + h <= 157`. The heap emptied after the root. Four generated successors were duplicates of that state and 47 were proof-pruned. No continuation of that exact prefix can finish at 157 or less. Available RAM at launch was 7,972,777,984 bytes.

Action 130 was given an 1,800-second limit and a 2,000,000-identity cap. The component emptied in 38.1 seconds. All 22 suffix hits were non-improving. No solution under 158 exists from that exact prefix. Available RAM at launch was 7,932,235,776 bytes. The best retained partial reached 4 foundations at corrected cost 140.

Action 120 used the same 1,800-second and 2,000,000-identity limits. The 157 game was already published at the 600-second checkpoint (`unique=129167`, `expanded=64117`, `suffix_hits=29`, `best=157`). The live ceiling then became 156. The search continued and the heap emptied at 1,036.6 seconds. No cheaper game was published. Available RAM at launch was 8,206,594,048 bytes. Maximum foundations seen in the search were 6. That closure is the action-120 root, its opening ancestry, this deal, these rules, and the tightened ceiling. It is not a proof about prefixes that leave the 158 route before action 120.

## Authentication

The four own-campaign games were replayed before any search. Costs: 164, 162, 160, and 158. The 158 hash is `9145868d32e42008`. They share the first 130 actions. The suffix table has 220 distinct exact physical states.

On the 158 route the admissible figures are:

| Action | g | h | f | Foundations | Face-down | Stock cards |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 5 | 5 | 0 | 44 | 50 |
| 58 | 58 | 59 | 117 | 0 | 14 | 0 |
| 120 | 120 | 28 | 148 | 3 | 10 | 0 |
| 130 | 130 | 23 | 153 | 3 | 10 | 0 |
| 140 | 140 | 17 | 157 | 4 | 9 | 0 |
| 141 | 141 | 17 | 158 | 4 | 8 | 0 |
| 142 | 142 | 16 | 158 | 4 | 7 | 0 |
| 143 | 143 | 15 | 158 | 5 | 7 | 0 |

Stock is empty at action 58, and the admissible remainder there is 59. The opening remainder is 5. Action 142 and action 143 cannot meet a ceiling of 157.

The saved-prefix splice check ran once. A record is one state on each own route, including the opening and the solved end, plus one end state for each distinct `replay_ok` action list in the accepted #26 and #27 ledgers. That is 735 records, 664 exact physical matches, best total 158, and zero cheaper combinations. Those ledgers were read only. This check is not a search and does not prove that an unseen prefix is impossible.

## Commands

```text
py -3 -u tools/incumbent_suffix_optimisation.py authenticate
py -3 -u tools/incumbent_suffix_optimisation.py search --at-action 140 --time-limit 600 --max-unique 300000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/incumbent_suffix_optimisation.py search --at-action 130 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/incumbent_suffix_optimisation.py search --at-action 120 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
```

The output directory is `docs/research/incumbent_suffix_optimisation/`. The tool does not write the accepted method-capture ledger or the historical 158 and 164 files.

## Code and tests

The implementation commit is `17b7e9f30731ea9b252045b03f7d38abbf2ce09b`. Prefix-improve search is a separate mode. Cold continuation still refuses an incumbent and still does not install the admissible bound. The retained-memory accountant now charges each reference heap-tuple member once by object identity and counts a repeated object as a shared reference. Historical profile JSON was not regenerated. The erratum is in `docs/research/search_memory_efficiency/report.md`.

The maintained selection was the 31 files in `docs/strategic_continuity_v0_123.md` section 19, plus the later global-search, dependency, witness, cycle-escape, campaign, method-capture, packed-heap, and memory-profile modules, plus `tests/test_incumbent_suffix.py`. The command was `py -3 -m pytest -p no:cacheprovider` with `PYTHONPATH=src`. Result: 796 passed in 244.95 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` did not fail. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT` in a full suite, and it was not weakened. Eight modules that fail collection were not in this selection and were not edited:

- `tests/test_exact_state_policy_context_equivalence_v0_1.py`
- `tests/test_one_shot_natural_empty_service_v0_1.py`
- `tests/test_one_shot_natural_r3_service_v0_1.py`
- `tests/test_workspace_opportunity_service_lane_v0_1.py`
- `tests/test_workspace_service_generalisation_panel_v0_1.py`
- `tests/test_workspace_service_lag1_grace_v0_1.py`
- `tests/test_workspace_service_stock_guard_v0_1.py`
- `tests/test_workspace_service_stock_synchronous_v0_1.py`

This selection is not the whole suite.

## Not established

No search proved a shortest game. The closed components are only the three authenticated prefixes above. A capped or closed fixed prefix says nothing about a different opening path. The canonical 172, the autonomous 185, and g123 guidance were not loaded. No further campaign was started after the action-120 heap emptied.
