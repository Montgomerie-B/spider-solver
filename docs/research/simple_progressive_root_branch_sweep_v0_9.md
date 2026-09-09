# Simple Progressive Search v0.9: Seeded Root-Branch Sweep

## 1. Verdict

`ROOT_BRANCH_DIVERSIFICATION_IMPROVES_PROGRESS` — previously untested B branch(es) outperform A: [('B_2_8_1', 'run')].

v0.8 established run 1→8 and adjacencies 16→33 with fd 14→14 and empties 0→0.
This sweep isolates each root action under a matched A+B budget so the four
Tier-B siblings are actually searched.

## 2. Seed

- replay ok=True digest `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`
- path 43 / cost 43 / fd=14 stock=0 fnd=0 empties=0
- census A/B/C/D=1/4/0/0

## 3. Root children

| Action | Tier | Child digest | Equivalent |
| --- | --- | --- | --- |
| (2,0,1) | 1 | `53504b3101000000040b3a2c…` | False |
| (2,3,1) | 1 | `53504b3101000000040a3a2c…` | False |
| (2,8,1) | 1 | `53504b3101000000040a3a2c…` | False |
| (4,1,1) | 0 | `53504b3101000000040a3a2c…` | False |
| (7,2,1) | 1 | `53504b3101000000040a3a2c…` | False |

## 4. Matched A+B arms

| Root action | Tier | Exp | Unique | Min FD | Max empties | Longest run | Max adj | Max fnd |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| (2,0,1) | B | 250000 | 11878 | 14 | 0 | 8 | 33 | 0 |
| (2,3,1) | B | 250000 | 9511 | 14 | 0 | 7 | 37 | 0 |
| (2,8,1) | B | 250000 | 13786 | 14 | 0 | 9 | 36 | 0 |
| (4,1,1) | A | 250000 | 11878 | 14 | 0 | 8 | 33 | 0 |
| (7,2,1) | B | 250000 | 10699 | 14 | 0 | 8 | 35 | 0 |

## 5. Efficiency

| Arm | Unique/exp | TT reopens | Reopen/exp | RSS MiB | s/s | Stop |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| B_2_0_1 | 0.0475 | 238122 | 0.95 | 1800.41015625 | 492.6 | node limit |
| B_2_3_1 | 0.0380 | 240489 | 0.96 | 1801.22265625 | 489.5 | node limit |
| B_2_8_1 | 0.0551 | 236214 | 0.94 | 1801.22265625 | 455.7 | node limit |
| A_4_1_1 | 0.0475 | 238122 | 0.95 | 5573.1328125 | 483.2 | node limit |
| B_7_2_1 | 0.0428 | 239301 | 0.96 | 5573.1328125 | 458.0 | node limit |

Reopen/exp is 0.94-0.96 on every arm, so the v0.8 unique-collapse is common to all root branches, not A-first specific. Sequential process peak RSS grew from ~1800 to ~5573 MiB; later arms inherit process peak.

## 6. Hard progress events

- B_2_0_1 run_ge_8: exp=115022 depth=41 run=8 fd=14 empty=0 replay_ok=True
- B_2_3_1: none.
- B_2_8_1 run_ge_8: exp=130880 depth=32 run=8 fd=14 empty=0 replay_ok=True
- B_2_8_1 run_ge_9: exp=130927 depth=35 run=9 fd=14 empty=0 replay_ok=True
- A_4_1_1 run_ge_8: exp=115022 depth=41 run=8 fd=14 empty=0 replay_ok=True
- B_7_2_1 run_ge_8: exp=17680 depth=27 run=8 fd=14 empty=0 replay_ok=True

## 7. Combined replay of best run witnesses

- B_2_0_1: {'adjacencies': 29, 'blocks': 5, 'cost': 85, 'empties': 0, 'fd': 14, 'foundations': 0, 'longest_run': 8, 'ok': True, 'path_length': 85, 'stock_rows': 0}
- B_2_3_1: {'adjacencies': 26, 'blocks': 5, 'cost': 57, 'empties': 0, 'fd': 14, 'foundations': 0, 'longest_run': 7, 'ok': True, 'path_length': 57, 'stock_rows': 0}
- B_2_8_1: {'adjacencies': 32, 'blocks': 4, 'cost': 79, 'empties': 0, 'fd': 14, 'foundations': 0, 'longest_run': 9, 'ok': True, 'path_length': 79, 'stock_rows': 0}
- A_4_1_1: {'adjacencies': 29, 'blocks': 5, 'cost': 85, 'empties': 0, 'fd': 14, 'foundations': 0, 'longest_run': 8, 'ok': True, 'path_length': 85, 'stock_rows': 0}
- B_7_2_1: {'adjacencies': 30, 'blocks': 5, 'cost': 71, 'empties': 0, 'fd': 14, 'foundations': 0, 'longest_run': 8, 'ok': True, 'path_length': 71, 'stock_rows': 0}

## 8. Optional extensions

- B_2_8_1: nodes=705528 fd=14 run=9 fnd=0

## 9. Ranking (interpretation only)

B_2_8_1 > B_7_2_1 > B_2_0_1 > A_4_1_1 > B_2_3_1

## 10. Exactly one next recommendation

B_2_8_1 beat the A-first child on run length (9 vs 8). Its 1M extension stayed at fd 14, 0 empties, 0 foundations. Next: return to whole-deal scheduling and preserve Pass-0 budget so this seed can be generated and granted Pass 1; do not add production branch quotas.

## Integrity

Seed ok=True fd=14 stock=0 fnd=0 empties=0. Distinct root children=5 B-searched=4. B_2_0_1: exp=250000 uniq=11878 fd=14 empty=0 run=8 adj=33 fnd=0 ratio=0.0475 reopen=0.95. B_2_3_1: exp=250000 uniq=9511 fd=14 empty=0 run=7 adj=37 fnd=0 ratio=0.0380 reopen=0.96. B_2_8_1: exp=250000 uniq=13786 fd=14 empty=0 run=9 adj=36 fnd=0 ratio=0.0551 reopen=0.94. A_4_1_1: exp=250000 uniq=11878 fd=14 empty=0 run=8 adj=33 fnd=0 ratio=0.0475 reopen=0.95. B_7_2_1: exp=250000 uniq=10699 fd=14 empty=0 run=8 adj=35 fnd=0 ratio=0.0428 reopen=0.96. Verdict ROOT_BRANCH_DIVERSIFICATION_IMPROVES_PROGRESS.

Base SHA `46f43c8b756205715a0b3b284b3da17038ab5a32`. Deal `deals/4925153.txt`.
Production `solve_progressive` defaults unchanged. Arms used start_pass=1,
A+B only, fresh TT, depth 320, no Deal probe, no branch quotas.

