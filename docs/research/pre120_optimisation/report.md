# Pre-120 optimisation — deal 4925153

Campaign result: a verified **146**-move game. The accepted 157-move route is unchanged. Optimality is not established.

Assistance is prefix/suffix-assisted. One worker used the compact representation, the captured seven-lane order, and advice off. Seed 0 is recorded and is not wired into successor order. There were no sampled reseeds. Saved branches are leaders only, not a full frontier. Suffix lengths are completion witnesses, not admissible lower bounds. Pruning removes a node only when `g + admissible_h` exceeds the absolute ceiling. Equality stays eligible.

## Verified 146

| Check | Value |
| --- | ---: |
| Corrected cost | 146 |
| Explicit commands | 146 |
| Tableau moves | 141 |
| Stock deals | 5 |
| Automatic foundation removals | 8 |
| Foundations | 8 |
| Stock and tableau | empty |
| Action hash | `0098156ecf32e95d` |
| File bytes | 1847 |
| Raw / CRLF SHA-256 | `99117ED9D1F5869FDC799220A8739E0BED96361D39FA831DFF7BE351E8EE9247` |
| LF SHA-256 | `C61C1C394D51D9150232E389288AF105133042F4DCE02B87B5AD5943C792B7FE` |

File: `docs/research/pre120_optimisation/4925153_assisted_146.moves`.

Full original-opening replay agrees with the file. The search witness is the 148 route at action 145, hash `c1b2a42d3974b207`, inside the launch ceiling 147. The route follows the 148 game for 112 actions, then plays `(0, 8, 1)` instead of `(3, 8, 2)`. It follows the 150 and 157 games for 90 actions, then plays `(5, 3, 2)` instead of `(8, 0, 1)`.

The ledger label is `VERIFIED_IMPROVEMENT` because 146 is below the campaign threshold of 157. That label is not an optimality claim.

## Other verified successors

Each file was replayed from the original opening. Sidecar `validated` was not the authority.

| Cost | Action hash | Tableau | Witness | Witness index | Launch ceiling |
| ---: | --- | ---: | --- | ---: | ---: |
| 156 | `bc0d3bd048a16c9d` | 151 | 157 `89c75b02b80f1271` | 117 | 156 |
| 151 | `aaf48d4d02aeb07a` | 146 | 157 `89c75b02b80f1271` | 112 | 155 |
| 150 | `b79fc5b356653898` | 145 | 156 `bc0d3bd048a16c9d` | 112 | 155 |
| 149 | `227cce1e69114f63` | 144 | 150 `b79fc5b356653898` | 147 | 149 |
| 148 | `c1b2a42d3974b207` | 143 | 150 `b79fc5b356653898` | 147 | 149 |
| 147 | `27f1a9102210c67c` | 142 | 148 `c1b2a42d3974b207` | 145 | 147 |
| 146 | `0098156ecf32e95d` | 141 | 148 `c1b2a42d3974b207` | 145 | 147 |

Every game has five Deals, eight automatic removals, eight foundations, and an empty stock and tableau. Working-tree SHA-256:

| Cost | Bytes | Raw / CRLF SHA-256 | LF SHA-256 |
| ---: | ---: | --- | --- |
| 156 | 1968 | `FDBFC35FE7663EC0A7AE0FB2A367F09BFF55DAC68512B7B4EEEEA17956C90429` | `8780A9F13704E6DEE9A53A48A1A12B46817CD5D5F75F2EF636DCFE787FD70F07` |
| 151 | 1904 | `AD33921F3AC3D8C08015A3C82104FE7D7C464A924FD0D75B7F574ACBDD5A71A9` | `9F9E116E47DCEA08DC1EEDFE4EF92BF4F80F246F628ADACBA350F8C8B405B0E0` |
| 150 | 1892 | `86093A2C0765BC4CEC758A0F2394C9372C60E403737F5DC610D55C9B3E408016` | `C572D0067B2079C06F496C0155FB00CFFE3F0C1012207FD68BFE3081BB031EC9` |
| 149 | 1879 | `9A54EBD60E2B0D4BAAE5D6302B1DDD5084DEBEE222AAD6D2C3FC4B987CF2EC8C` | `A01C5AD73C4E03E746E7CABF5FA04C0445926E09A51E66E06CB5E786DE3E03B4` |
| 148 | 1869 | `131D84CABDEAFF3AEB89C2A758B02295B28072C95D1FDD3E7BFDE5D3FB4D9890` | `2732086948A924D466481D73459AA8A1F153E68E0F233D7D0F741150FC42584C` |
| 147 | 1857 | `42C4F0F8DC49F95B2E5FF22899DE66CFC4ACD3C88C91BDD3CF27EC1A0E30BD3D` | `6CF5C98A235639CD0436E4B945C4D77356464EA4BFF9186AFA1A45BE603EB802` |

Departures, as replayed action prefixes:

- 156 leaves 157 at action 110: `(9, 3, 2)` instead of `(9, 5, 2)`.
- 151 leaves both at action 101: `(7, 0, 1)` instead of `(9, 5, 2)`.
- 150 follows 151 for 102 actions, then plays `(9, 3, 2)` instead of `(9, 5, 2)`.
- 149, 148, 147 and 146 leave 150 at action 90: `(5, 3, 2)` instead of `(8, 0, 1)`.
- 148 follows 149 for 109 actions, then plays `(7, 5, 1)` instead of `(0, 5, 9)`.
- 147 and 146 follow 148 for 112 actions, then play `(0, 8, 1)` instead of `(3, 8, 2)`.
- 147 and 146 share 121 actions, then 147 plays `(0, 9, 5)` and 146 plays `(4, 9, 1)`.

## Attempts

Output directory: `docs/research/pre120_optimisation/`. Schema `spider-incumbent-suffix-28`. Host: 8 CPUs, 17,054,756,864 bytes RAM. Requested RSS 3,000 MB. The cap stayed at 3,000 MB until free memory clamped it: p10 2,953.08 MB, p11 2,983.61 MB, p12 2,961.80 MB. No attempt aborted on RSS. Identity cap 2,000,000. Checkpoint interval 600 seconds. No attempt hit the identity cap.

The document source fingerprint is commit `e85ad7c61e4fc92831dfb92ad4b44912f6ee8d30`, dirty false, frozen from the first launch. Later attempts record the same commit with dirty true because this directory was untracked. Solver source hashes did not change.

| ID | Route | Index | g / h / f | Prefix hash | Stop | Wall s | Unique | Expanded | Generated | Proof prunes | Hits | Accepted | Peak MB |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| p1 | 157 | 119 | 119 / 28 / 147 | `fe338a201ddf71d3` | time limit | 1801.244 | 359,474 | 224,425 | 4,538,504 | 2,659,063 | 43 | 0 | 681.4 |
| p2 | 157 | 110 | 110 / 31 / 141 | `8e11d88223ff95ac` | time limit | 3602.752 | 1,331,800 | 426,072 | 7,686,184 | 3,029,933 | 93 | 1 | 1789.7 |
| p3 | 156 | 116 | 116 / 28 / 144 | `69beebf4f29c2ee0` | time limit | 1801.671 | 648,698 | 192,113 | 3,796,516 | 1,694,006 | 48 | 0 | 830.3 |
| p4 | 156 | 100 | 100 / 34 / 134 | `2136a2ef67ca414e` | time limit | 1801.740 | 783,256 | 172,042 | 3,232,978 | 870,593 | 64 | 2 | 976.1 |
| p5 | 150 | 119 | 119 / 26 / 145 | `79d014bb0666af8a` | complete | 31.278 | 2,833 | 2,970 | 66,847 | 54,059 | 17 | 0 | 40.6 |
| p6 | 150 | 116 | 116 / 27 / 143 | `4dba4df6a97a145f` | complete | 101.782 | 11,809 | 12,078 | 232,203 | 174,581 | 18 | 0 | 63.1 |
| p7 | 150 | 90 | 90 / 37 / 127 | `6fd39cead842c8c6` | time limit | 900.767 | 236,551 | 80,041 | 2,037,071 | 1,094,254 | 10 | 2 | 366.1 |
| p8 | 148 | 119 | 119 / 26 / 145 | `2aeabbdc47c458e0` | complete | 2.413 | 172 | 174 | 4,030 | 3,398 | 6 | 0 | 32.0 |
| p9 | 148 | 116 | 116 / 27 / 143 | `7d7966aac8e78d83` | complete | 63.044 | 5,990 | 6,043 | 161,574 | 124,571 | 8 | 0 | 56.2 |
| p10 | 148 | 110 | 110 / 30 / 140 | `b92a506b01977eec` | time limit | 180.572 | 25,775 | 16,910 | 457,487 | 314,130 | 16 | 2 | 93.7 |
| p11 | 146 | 119 | 119 / 24 / 143 | `34bb03cb4990cb1c` | complete | 3.317 | 218 | 218 | 7,616 | 6,216 | 10 | 0 | 32.3 |
| p12 | 146 | 116 | 116 / 26 / 142 | `5ac997d84ddd4571` | complete | 6.508 | 615 | 617 | 15,187 | 12,316 | 15 | 0 | 34.0 |

Search wall time is 10,297.088 seconds. Duplicate and stale skips are in `status.json`.

Launch ceilings and what each stop means:

- p1 started at incumbent 157 and ceiling 156. Time limit. No publication. Unknown for that prefix.
- p2 started at the same ceiling, published 156, and finished at ceiling 155. Time limit after the publication. Unknown below 156.
- p3 used the 156 route at action 116, which is the same position as action 117 of the 157 route. Ceiling 155. Time limit. Unknown.
- p4 used action 100, the same position on the 156 and 157 routes. It published 151 and then 150. The final ceiling was 149. Time limit. Unknown below 150.
- p5 and p6 emptied the heap under ceiling 149. Those two prefixes of the 150 route have no in-ceiling completion.
- p7 published 149 and then 148. The final ceiling was 147. Time limit. Unknown below 148.
- p8 and p9 emptied the heap under ceiling 147. Those two prefixes of the 148 route have no in-ceiling completion.
- p10 published 147 and then 146. The final ceiling was 145. Time limit. Unknown below 146.
- p11 and p12 emptied the heap under ceiling 145. Those two prefixes of the 146 route have no in-ceiling completion.

A `complete` stop scopes exhaustion to that authenticated prefix, physical root, absolute g, deal 4925153, MobilityWare rules, and the compatible absolute ceiling. A time limit does not prove that an earlier departure is required. Repeating the same cap does not accumulate progress.

Pack identities that must not be launched again as the same search:

- 156 at action 119 equals the closed action-120 root of the 157 route.
- 150 at action 110 equals 156 at action 116 and 157 at action 117.
- 146 at action 90 equals the time-capped p7 root.
- 146 at action 110 equals the time-capped p10 root.
- 146 at actions 116 and 119 are the exhausted p12 and p11 roots.

## Authentication

The historical four-route fixture is unchanged: 220 distinct physical states, labels 164 / 162 / 160 / 158, shared prefix 130, splice records 735, exact matches 664, best total 158, improving combinations 0.

The pre-search manifest, commit `e85ad7c`, measured the expanded inputs before any successor existed: 248 distinct physical states, shared prefix of 157 and 158 equal to 121, splice records 893, exact matches 822, best total 157, improving combinations 0. No splice was published.

The final manifest was regenerated with `authenticate_campaign(..., incumbent=146, ceiling=145)` after the searches. The campaign CLI hardcodes incumbent 157 and ceiling 156, which would have treated the already verified successors as improving splices. The direct call compares against the verified 146. Result: 394 distinct physical states, shared prefix of all adopted routes 90, shared prefix of 157 and 158 still 121, saved-branch records 87, splice records 1,947, exact matches 1,876, best total 146, improving combinations 0, publication null. The manifest source fingerprint is commit `e85ad7c` and dirty true, because it was written before this evidence commit.

`last_eligible_index` 117 in that manifest is action 117 of the pinned 157 route under ceiling 145 (`g=117`, `h=28`, `f=145`). It is not a searched root and it is not a closure.

## Commands

Pre-search authentication:

```text
py -3 -u tools/pre120_optimisation.py authenticate
```

Searches, from the repository with `PYTHONPATH=src`:

```text
py -3 -u tools/pre120_optimisation.py search --at-action 119 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --at-action 110 --time-limit 3600 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 156 --at-action 116 --incumbent 156 --ceiling 155 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route best --at-action 100 --incumbent 156 --ceiling 155 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route best --at-action 119 --incumbent 150 --ceiling 149 --time-limit 900 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 150 --at-action 116 --incumbent 150 --ceiling 149 --time-limit 900 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 150 --at-action 90 --incumbent 150 --ceiling 149 --time-limit 900 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 148 --at-action 119 --incumbent 148 --ceiling 147 --time-limit 300 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 148 --at-action 116 --incumbent 148 --ceiling 147 --time-limit 240 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 148 --at-action 110 --incumbent 148 --ceiling 147 --time-limit 180 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 119 --incumbent 146 --ceiling 145 --time-limit 120 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 116 --incumbent 146 --ceiling 145 --time-limit 90 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
```

The first two commands use the tool defaults: route 157, incumbent 157, ceiling 156. `--route best` selected 156 and then 150 at the times those commands ran.

Continuation for a later campaign, not started here. Adopt the verified 146 route, keep ceiling 145, and leave the closed and time-capped prefixes above alone. Action 100 of the 146 route is a different position from the capped action-100 search. Actions 80 and 58 have not been searched. Index 120 and later is refused.

```text
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 100 --incumbent 146 --ceiling 145 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 80 --incumbent 146 --ceiling 145 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 58 --incumbent 146 --ceiling 145 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
```

If a cheaper verified game is adopted, set the incumbent to that cost, the ceiling to incumbent minus one, and the route to `best`.

## Tests

The implementation was frozen at `8e883ed137648bf076e245e3b9b9fed8769fb711` before the searches. No solver code changed after that commit.

- `tests/test_incumbent_suffix.py`: 16 passed in 4.34 seconds.
- Maintained regression selection: 63 files, 800 passed in 238.39 seconds. This selection is not the whole suite.
- `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` instead of `TIME_LIMIT`. It did not fail in this run. The test was not weakened.
- Eight historical collection failures remain and were not edited: `tests/test_exact_state_policy_context_equivalence_v0_1.py`, `test_one_shot_natural_empty_service_v0_1.py`, `test_one_shot_natural_r3_service_v0_1.py`, `test_workspace_opportunity_service_lane_v0_1.py`, `test_workspace_service_generalisation_panel_v0_1.py`, `test_workspace_service_lag1_grace_v0_1.py`, `test_workspace_service_stock_guard_v0_1.py`, `test_workspace_service_stock_synchronous_v0_1.py`.

## Not established

- A 145-move game is not ruled out. The action-110 search that found 146 stopped on its time limit.
- Heap-empty results cover only the prefixes named above.
- The historical action-120 component of the shared 157/158 route stays closed only for that earlier search. This campaign did not rerun actions 120, 130, or 140.
- The saved-prefix splice found no combination below 146. The splice does not search.
- Canonical 172, autonomous 185, and g123 reference guidance were not used.
- No further campaign was started.
