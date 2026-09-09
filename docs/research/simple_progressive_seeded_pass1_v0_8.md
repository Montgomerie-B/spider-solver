# Simple Progressive Search v0.8: Seeded Pass-1 Continuation

## 1. Verdict

`SEEDED_PASS1_MAKES_STRUCTURAL_PROGRESS` — A+B continuation improved fd/run/adjacency/empties without a foundation.

## 2. Seed reproduction

- Fixture `solutions/4925153_simple_fd14_stock0_seed.moves.txt`
- digest `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`
- replay ok=True path_length=43 cost=43
- fd=14 stock_rows=0 foundations=0
- legal A/B/C/D=1/4/0/0
- immediate foundation=False
- longest run=1

## 3. Local Pass-0 control

- expanded=5 unique=5 stop=band envelope
- min fd=14 max foundations=0 max depth=3
- longest run=3

## 4. Local Pass-1 treatment

- expanded=837832 unique=30776 unique/exp=0.03673290110666578
- states/s=465.4 time s=1800.2 RSS=6267.5234375
- min fd=14 max foundations=0 max depth=277 stop=time limit
- first foundation node=None local depth=None pass=None

## 5. Four root Tier-B moves

| Action | Child fd | Novel | Expanded | Descendants | Best desc fd | Fnd | Run | Cut |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| [2, 0, 1] | 14 | False | False | None | None | None | 1 | None |
| [2, 3, 1] | 14 | False | False | None | None | None | 1 | None |
| [2, 8, 1] | 14 | False | False | None | None | None | 1 | None |
| [7, 2, 1] | 14 | False | False | None | None | None | 1 | None |
Pass-1 ordering puts the single Tier-A child first. DFS dived there and did not return to the four root B siblings before the time limit. Run/adjacency gains come from later B moves under that A child.

## 6. Structural witnesses

- best fd: fd=14 fnd=0 run=1 adj=16 empties=0 mixed=17 depth=0 exp=1 path_len=0
- best foundations: fd=14 fnd=0 run=1 adj=16 empties=0 mixed=17 depth=0 exp=1 path_len=0
- longest run: fd=14 fnd=0 run=8 adj=29 empties=0 mixed=23 depth=42 exp=115023 path_len=42
- best adjacencies: fd=14 fnd=0 run=3 adj=33 empties=0 mixed=28 depth=65 exp=115419 path_len=65
- best empties: fd=14 fnd=0 run=1 adj=16 empties=0 mixed=17 depth=0 exp=1 path_len=0
- lowest mixed: fd=14 fnd=0 run=1 adj=16 empties=0 mixed=17 depth=0 exp=1 path_len=0

## 7. Foundation / concatenated replay

- combined replay={'adjacencies': 29, 'cost': 85, 'fd': 14, 'foundations': 0, 'longest_run': 8, 'ok': True, 'path_length': 85, 'solved': False, 'stock_rows': 0}
- 3M not run: run length 8 appeared at local expansion 115023; the remaining 1M-time-limit search did not improve fd or reach a foundation.

## 8. Optional larger / solve runs

- not run.

## 9. Exactly one next recommendation

The good state is worth widening. Next: return to whole-deal scheduling and preserve Pass-0 budget in deeper bands so this seed can be generated and then granted Pass 1; do not add foundation heuristics.

## Integrity

Seed digest=53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925 ok=True fd=14 stock=0 fnd=0 cost=43. Pass0 nodes=5 unique=5 min_fd=14 fnd=0. Pass1 nodes=837832 unique=30776 min_fd=14 fnd=0 run=8 B expanded=0/4. Combined replay={'ok': True, 'cost': 85, 'fd': 14, 'foundations': 0, 'stock_rows': 0, 'solved': False, 'path_length': 85, 'longest_run': 8, 'adjacencies': 29}. Verdict SEEDED_PASS1_MAKES_STRUCTURAL_PROGRESS.

Base SHA `260fecd38e5fa70924b0d63714be647431dc752d`. Deal `deals/4925153.txt`.
Production `solve_progressive` default `start_pass=0`. Local arms used a
single depth band 320, fresh TT, A-only or A+B, no C/D, no Deal probe,
no Deal preparation, no whole-deal scheduler change.

