# Simple Progressive Search v0.10: First-Visit Exact DFS

## 1. Verdict

`FIRST_VISIT_DFS_IMPROVES_HARD_PROGRESS` — B_2_0_1 achieved fd<14, an empty, or run>=10.

FIRST_VISIT_EXACT is heuristic first-solution coverage. It has no proof authority.
Production default remains DEPTH_AWARE_COVERAGE.

## 2. Replay-integrity explanation

v0.9 generic ProgressiveSearchResult.replay_ok was False because the local search root is the seed child and the best-fd witness is often that root (empty local path), so the generic replay check does not run. Combined prefix + root action + continuation witnesses replayed with ok=True. That is a reporting-label issue, not a rules-engine bug.

## 3. Seed

- ok=True digest `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925` cost=43 fd=14 stock=0 fnd=0

## 4. Unique coverage vs v0.9

| Root action | Old unique | New unique | Old run | New run | New min FD | New empties | New fnd |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| (2,0,1) | 11878 | 232576 | 8 | 9 | 13 | 1 | 0 |
| (2,3,1) | 9511 | 250000 | 7 | 7 | 14 | 0 | 0 |
| (2,8,1) | 13786 | 220604 | 9 | 9 | 13 | 1 | 0 |
| (4,1,1) | 11878 | 232719 | 8 | 9 | 13 | 1 | 0 |
| (7,2,1) | 10699 | 250000 | 8 | 8 | 14 | 0 | 0 |

## 5. Reopen vs first-visit skip

| Root action | Old reopen/exp | New duplicate-skip/encounter | Old states/s | New states/s |
| --- | ---: | ---: | ---: | ---: |
| (2,0,1) | 0.95 | 0.6960 | 492.6 | 387.6 |
| (2,3,1) | 0.96 | 0.7551 | 489.5 | 452.6 |
| (2,8,1) | 0.94 | 0.7174 | 455.7 | 367.6 |
| (4,1,1) | 0.95 | 0.6960 | 483.2 | 387.8 |
| (7,2,1) | 0.96 | 0.6535 | 458.0 | 419.2 |

## 6. First-visit arm detail

| Arm | Exp | Unique | Unique/exp | FV skips | Cycles | Sibling dup | Inverse | Depth | RSS | Stop |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| B_2_0_1 | 232576 | 232576 | 1.0000 | 532515 | 260574 | 0 | 211850 | 2000 | 1960.76953125 | time limit |
| B_2_3_1 | 250000 | 250000 | 1.0000 | 771028 | 201517 | 0 | 225421 | 398 | 2219.89453125 | node limit |
| B_2_8_1 | 220604 | 220604 | 1.0000 | 560152 | 311883 | 0 | 206090 | 2000 | 1957.45703125 | time limit |
| A_4_1_1 | 232719 | 232719 | 1.0000 | 532855 | 260777 | 0 | 211991 | 2000 | 1960.6953125 | time limit |
| B_7_2_1 | 250000 | 250000 | 1.0000 | 471586 | 162117 | 0 | 216951 | 692 | 1931.0703125 | node limit |

## 7. Hard progress

- B_2_0_1 run_ge_8: exp=7106 depth=41 run=8 fd=14 empty=0 replay=True
- B_2_0_1 run_ge_9: exp=93986 depth=42 run=9 fd=14 empty=0 replay=True
- B_2_0_1 fd_below_14: exp=136901 depth=64 run=6 fd=13 empty=0 replay=True
- B_2_0_1 first_empty: exp=136902 depth=65 run=6 fd=13 empty=1 replay=True
- B_2_3_1: none beyond seed structure.
- B_2_8_1 run_ge_8: exp=7097 depth=32 run=8 fd=14 empty=0 replay=True
- B_2_8_1 run_ge_9: exp=7114 depth=35 run=9 fd=14 empty=0 replay=True
- B_2_8_1 fd_below_14: exp=50065 depth=57 run=6 fd=13 empty=0 replay=True
- B_2_8_1 first_empty: exp=50066 depth=58 run=6 fd=13 empty=1 replay=True
- A_4_1_1 run_ge_8: exp=7106 depth=41 run=8 fd=14 empty=0 replay=True
- A_4_1_1 run_ge_9: exp=93986 depth=42 run=9 fd=14 empty=0 replay=True
- A_4_1_1 fd_below_14: exp=136901 depth=64 run=6 fd=13 empty=0 replay=True
- A_4_1_1 first_empty: exp=136902 depth=65 run=6 fd=13 empty=1 replay=True
- B_7_2_1 run_ge_8: exp=2044 depth=27 run=8 fd=14 empty=0 replay=True

## 8. B_2_8_1 special

- unique_at={'100000': 100000, '25000': 25000, '50000': 50000}
- run>=8 at 7097
- run>=9 at 7114
- run>=10: False
- fd<14: True
- empty: True
- foundation: False

## 9. Optional extension

- B_2_0_1: nodes=838569 unique=838569 fd=13 run=9 fnd=0 stop=time limit

## 10. Exactly one next recommendation

Keep first-visit as research-only first-solution coverage. A+B already produced fd 13 and an empty column; the 1M extension plateaued there with no foundation. Next: add Pass 2 (A+B+C) under first-visit on a hard-progress child; do not restore depth reopens and do not integrate whole-deal scheduling yet.

## Integrity

Verdict FIRST_VISIT_DFS_IMPROVES_HARD_PROGRESS. B_2_0_1: exp=232576 uniq=232576 ratio=1.000 skip=532515 run=9 fd=13 empty=1 fnd=0 depth=2000 rss=1960.76953125. B_2_3_1: exp=250000 uniq=250000 ratio=1.000 skip=771028 run=7 fd=14 empty=0 fnd=0 depth=398 rss=2219.89453125. B_2_8_1: exp=220604 uniq=220604 ratio=1.000 skip=560152 run=9 fd=13 empty=1 fnd=0 depth=2000 rss=1957.45703125. A_4_1_1: exp=232719 uniq=232719 ratio=1.000 skip=532855 run=9 fd=13 empty=1 fnd=0 depth=2000 rss=1960.6953125. B_7_2_1: exp=250000 uniq=250000 ratio=1.000 skip=471586 run=8 fd=14 empty=0 fnd=0 depth=692 rss=1931.0703125.

Base SHA `33fb9f10687959e4e9a7820727a62fe542f53f94`. Deal `deals/4925153.txt`.
Default TT remains depth-aware. first_visit is research-only and not proof-safe.

