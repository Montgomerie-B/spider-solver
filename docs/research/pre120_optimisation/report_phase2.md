# Pre-120 optimisation, phase two — deal 4925153

Phase-two result: a verified **140**-move game. The accepted 146-move route and every earlier route remain in place. Optimality is not established.

This phase starts from commit `994f56a17586edde102a5f683415a42210fedd3b`. The incumbent was 146 and the absolute ceiling was 145. One worker used the compact representation, the captured seven-lane order, and advice off. The identity cap stayed at 2,000,000. Seed 0 is recorded and is not wired into successor order. There were no sampled reseeds. Saved branches are leaders only. Suffix lengths are completion witnesses, not admissible lower bounds.

The phase-one ledger entries `p1` through `p12` are unchanged. New attempts are `p13` through `p21`.

## Verified 140

| Check | Value |
| --- | ---: |
| Corrected cost | 140 |
| Explicit commands | 140 |
| Tableau moves | 135 |
| Stock deals | 5 |
| Automatic foundation removals | 8 |
| Foundations | 8 |
| Stock and tableau | empty |
| Action hash | `34a94de8e6edfa4b` |
| File bytes | 1774 |
| Raw / CRLF SHA-256 | `46AF376903B04A1AEB67ECCF24EDDE3BAD6BF54B8D5386517ABD99F51C66949D` |
| LF SHA-256 | `57DC0FFA2A1B21846811DD9A1DA1622D422811B739975B645A63A21655772300` |

File: `docs/research/pre120_optimisation/4925153_assisted_140.moves`.

Full original-opening replay agrees with the file. The search witness is the 142 route at action 92, hash `9101b2e1a8c8e087`, inside the launch ceiling 141. The route follows the 142 and 146 games for 84 actions, then plays `(2, 1, 2)` instead of `(1, 8, 9)`.

The ledger label remains `VERIFIED_IMPROVEMENT` because the runner compares with 157. Against this phase's starting incumbent, 140 is also below 146. Neither statement is an optimality claim.

## Other new verified games

Each file was replayed from the original opening. Sidecar metadata was not the authority.

| Cost | Action hash | Tableau | Witness | Witness index | Launch ceiling |
| ---: | --- | ---: | --- | ---: | ---: |
| 145 | `23fc6a7419463992` | 140 | 146 `0098156ecf32e95d` | 107 | 145 |
| 144 | `887c3714edebccc4` | 139 | 146 `0098156ecf32e95d` | 139 | 145 |
| 143 | `ba501439537ab20a` | 138 | 146 `0098156ecf32e95d` | 139 | 145 |
| 142 | `9101b2e1a8c8e087` | 137 | 146 `0098156ecf32e95d` | 143 | 145 |
| 141 | `30ba5b4524481618` | 136 | 142 `9101b2e1a8c8e087` | 87 | 141 |
| 140 | `34a94de8e6edfa4b` | 135 | 142 `9101b2e1a8c8e087` | 92 | 141 |

Every game has five Deals, eight automatic removals, eight foundations, and an empty stock and tableau.

| Cost | Bytes | Raw / CRLF SHA-256 | LF SHA-256 |
| ---: | ---: | --- | --- |
| 145 | 1835 | `2E980048054231A5ECFE271C62E1C6144C76009F86E4D78566275E19D1CF1F82` | `0D85B0A1D09645CC93EDA1338F5E5C94D94E776B36958279CDA9FE86A20A035C` |
| 144 | 1822 | `1BD36496ACD3A806C9E7F9F7F5C8DB7BD124D4EB11883DE972D6A4792EE17A81` | `8EDB0A42673BCACA071025DC0E993B35B57BB92BC13F78E8820C5C7636A33F63` |
| 143 | 1810 | `8EA92BDD445736B882BDEB305B0E7CC1A391BA04B9E9E44876C0F71A0A1B521A` | `B0B7C9708F4D5970F321AD6F98902B6FFD9173FEEF2019F616C26EC05F8B1AA7` |
| 142 | 1799 | `3DEC44E9DACD62FED42B7C7A15427304B6B14D476FB547FE6AE7DDC3D5A57980` | `5977AB21727A8C96F55895759B70299B809276FE6659F14B55AB330766036587` |
| 141 | 1786 | `DCC1073EF2AC735738AC2E17F16E9E842DE55DD050301B68DBE116729FB5C26F` | `4CFD7F8381A8EE1CF73F9ED5DE4444EC1B54B40707C62D9221AD75D6B622600D` |

Departures, as replayed action prefixes:

- 145 leaves 146 at action 100: `(9, 0, 1)` instead of `(2, 6, 2)`.
- 144 leaves 145 at action 100: `(2, 6, 2)` instead of `(9, 0, 1)`, and follows 146 for 103 actions.
- 143 follows 144 for 109 actions, then plays `(0, 8, 1)` instead of `(1, 6, 1)`.
- 142 follows 145 for 102 actions, then plays `(9, 8, 1)` instead of `(9, 0, 1)`.
- 141 and 140 leave 142 at action 84: `(2, 1, 2)` instead of `(1, 8, 9)`.
- 141 follows 140 for 86 actions, then plays `(1, 8, 1)` instead of `(2, 3, 2)`.

## Attempts

The requested RSS cap was 3,000 MB. Free memory clamped it. No attempt aborted on RSS. The identity cap was not raised: at 2,000,000 identities the action-58 search peaked at 2,342 MB under a 2,707 MB clamp, leaving about 366 MB. That headroom does not support a larger identity cap on this host.

Phase-two attempts record commit `994f56a17586edde102a5f683415a42210fedd3b`. `p13` was fingerprinted with a clean tree. Later attempts are dirty because the growing ledger and new games were untracked. Solver source files were not edited.

| ID | Route | Index | g / h / f | Prefix hash | Stop | Wall s | Unique | Expanded | Generated | Proof prunes | Hits | Accepted | Peak MB |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| p13 | 146 | 110 | 110 / 30 / 140 | `b92a506b01977eec` | complete | 206.186 | 23,177 | 23,206 | 412,597 | 298,590 | 30 | 0 | 95.9 |
| p14 | 146 | 100 | 100 / 33 / 133 | `047a785ab1161918` | time limit | 5402.962 | 822,632 | 850,461 | 14,208,617 | 8,330,595 | 73 | 4 | 1643.8 |
| p15 | 142 | 119 | 119 / 21 / 140 | `c73979617f5f373b` | complete | 4.475 | 16 | 16 | 409 | 362 | 2 | 0 | 32.0 |
| p16 | 142 | 116 | 116 / 23 / 139 | `f0305e45b262b8d0` | complete | 2.711 | 207 | 207 | 7,499 | 6,129 | 5 | 0 | 33.0 |
| p17 | 142 | 110 | 110 / 27 / 137 | `e9cfe850aa4a5d75` | complete | 16.781 | 2,218 | 2,225 | 43,917 | 32,768 | 11 | 0 | 39.8 |
| p18 | 142 | 80 | 80 / 44 / 124 | `61dbbe4ea1f9825b` | time limit | 5403.453 | 1,813,256 | 578,842 | 11,716,639 | 5,186,382 | 30 | 2 | 2347.9 |
| p19 | 140 | 116 | 116 / 22 / 138 | `cb59704d57d52df1` | complete | 4.587 | 21 | 21 | 497 | 439 | 4 | 0 | 32.7 |
| p20 | 140 | 110 | 110 / 26 / 136 | `5d77c2632930c3f3` | complete | 5.662 | 615 | 617 | 15,187 | 12,317 | 11 | 0 | 34.8 |
| p21 | 140 | 58 | 58 / 59 / 117 | `44f3e6c60669c816` | unique limit | 5243.538 | 2,000,000 | 472,590 | 10,317,961 | 4,091,833 | 24 | 0 | 2341.6 |

Phase-two search wall time is 16,290.355 seconds. Duplicate and stale skips are in `status.json`.

What each stop means:

- `p13` is the same physical root as the earlier 180-second search, prefix hash `b92a506b01977eec`. This run used ceiling 145 and emptied the heap. That prefix has no completion at 145 or below.
- `p14` is a different position from the phase-one action-100 search. It published 145, 144, 143, and 142. The final ceiling was 141. The time limit leaves every total below 142 unknown.
- `p15`, `p16`, and `p17` emptied the heap under ceiling 141. Those three prefixes of the 142 route have no in-ceiling completion. `p17` is not the closed `p13` root.
- `p18` is the shared action-80 position, prefix hash `61dbbe4ea1f9825b`. It published 141 and 140. The final ceiling was 139. The time limit leaves every total below 140 unknown.
- `p19` and `p20` emptied the heap under ceiling 139. Those two prefixes of the 140 route have no in-ceiling completion.
- `p21` is the shared stock-empty action-58 position, the same pack on the 140 and 146 routes. It stopped at the identity cap with no publication. The ceiling stayed 139. This is a capped unknown, not exhaustion. Repeating the same 2,000,000 cap does not accumulate progress.

RSS caps recorded on the attempts were 3,000.00, then 2,777.26, 2,759.18, 2,744.16, 2,733.70, 2,726.07, 2,718.65, and 2,707.48 MB as free memory changed.

## Authentication

The historical four-route fixture is unchanged: 220 distinct physical states, shared prefix 130, splice records 735, exact matches 664, best total 158, improving combinations 0.

`witness_manifest_phase2.json` was written by `authenticate_campaign(..., incumbent=140, ceiling=139)`. The campaign CLI still defaults to incumbent 157 and ceiling 156, so it was not used for this file. The phase-one manifest was not overwritten.

Expanded measurement: 474 distinct physical states, shared prefix of all adopted routes 84, saved-branch records 87, splice records 2,808, exact matches 2,737, best total 140, improving combinations 0, publication null. The manifest source fingerprint is commit `994f56a` and dirty true, because it was written before this phase-two evidence commit.

`last_eligible_index` 107 in that manifest is action 107 of the pinned 157 route under ceiling 139. It is not a searched root and it is not a closure.

## Commands

```text
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 110 --incumbent 146 --ceiling 145 --time-limit 3600 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 146 --at-action 100 --incumbent 146 --ceiling 145 --time-limit 5400 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 142 --at-action 119 --incumbent 142 --ceiling 141 --time-limit 180 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 142 --at-action 116 --incumbent 142 --ceiling 141 --time-limit 180 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 142 --at-action 110 --incumbent 142 --ceiling 141 --time-limit 300 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 142 --at-action 80 --incumbent 142 --ceiling 141 --time-limit 5400 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 140 --at-action 116 --incumbent 140 --ceiling 139 --time-limit 180 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 140 --at-action 110 --incumbent 140 --ceiling 139 --time-limit 300 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 140 --at-action 58 --incumbent 140 --ceiling 139 --time-limit 6600 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
```

Continuation for a later campaign, not started here. Action 100 of the 140 route is a different position from `p14`, prefix hash `f31a4c22419c97db`, `g=100`, `h=32`, `f=132`. The 140 route leaves the older routes at action 84, so its action 90 is not the earlier action-90 search.

```text
py -3 -u tools/pre120_optimisation.py search --route 140 --at-action 100 --incumbent 140 --ceiling 139 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
py -3 -u tools/pre120_optimisation.py search --route 140 --at-action 90 --incumbent 140 --ceiling 139 --time-limit 1800 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600
```

A continuation of action 58 needs a higher identity cap on a host whose RSS clamp leaves more than the measured 366 MB above 2,342 MB at 2,000,000 identities. Repeating `--max-unique 2000000` on this prefix does not accumulate progress.

## Tests

Solver code is unchanged since `8e883ed137648bf076e245e3b9b9fed8769fb711`. The phase-one evidence still stands: `tests/test_incumbent_suffix.py` passed 16 tests in 4.34 seconds, and the maintained selection passed 800 tests in 238.39 seconds across 63 files. That selection is not the whole suite. It was not run again. The known `PLANNING_STALL` / `TIME_LIMIT` variability and the eight historical collection failures are unchanged. Each new route in this phase was replayed from the original opening.

## Not established

- A 139-move game is not ruled out. Action 58 stopped on the identity cap, and action 80 stopped on its time limit.
- Heap-empty results cover only the prefixes named above.
- The saved-prefix splice found no combination below 140. The splice does not search.
- Canonical 172, autonomous 185, and g123 reference guidance were not used.
- No further campaign was started.
