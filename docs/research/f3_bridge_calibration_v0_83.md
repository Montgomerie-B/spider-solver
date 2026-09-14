# f3_bridge_calibration_v0_83

Verdict: `F3_CALIBRATION_ZERO_SLACK_ONLY`

next-foundation f=186 loss=12

Equal-budget proof-aware calibration of three NEW v0.82 Pareto F3s. No F3 harvest. No g141/g158 search. No exhausted v0.80/v0.81 F4/F5 roots. Stage A 60s/target exceeds the g141 first-viable time (48.8s). Canonical 172 was not a search input.

## Roots

| name | g | h | f | slack | fd | empties | legal | boundaries | ok |
| --- | -: | -: | -: | ----: | -: | ------: | ----: | ---------: | --- |
| A_high_slack | 142 | 32 | 174 | 12 | 2 | 2 | 47 | 35 | True |
| B_interior | 160 | 23 | 183 | 3 | 2 | 3 | 76 | 26 | True |
| C_assembled | 161 | 22 | 183 | 3 | 2 | 4 | 95 | 25 | True |

## Frozen controls

g141: f=174 best next f=186 loss +12
g158: f=180 best next f=185 loss +5

## Bridge-value table

| name | root g | root h | root f | target | terminal F | terminal g | terminal h | terminal f | slack | bridge loss |
| --- | -----: | -----: | -----: | ------ | ---------: | ---------: | ---------: | ---------: | ----: | ----------: |
| A_high_slack | 142 | 32 | 174 | h | 4 | 162 | 24 | 186 | 0 | 12 |
| B_interior | 160 | 23 | 183 | h | None | None | None | None | None | None |
| C_assembled | 161 | 22 | 183 | h | None | None | None | None | None | None |

## Root/target probes

| root g | root h | root f | target rank | target | stop | unique | exp | raw | viable | best g | best h | best f | slack |
| -----: | -----: | -----: | ----------: | ------ | ---- | -----: | --: | --: | -----: | -----: | -----: | -----: | ----: |
| 142 | 32 | 174 | 1 | h | time limit | 13515 | 974 | 5 | 1 | 162 | 24 | 186 | 0 |
| 142 | 32 | 174 | 2 | c | time limit | 12463 | 1020 | 0 | 0 | None | None | None | None |
| 142 | 32 | 174 | 3 | d | time limit | 14493 | 1106 | 0 | 0 | None | None | None | None |
| 142 | 32 | 174 | 4 | s | time limit | 13977 | 959 | 0 | 0 | None | None | None | None |
| 160 | 23 | 183 | 1 | h | complete | 11681 | 670 | 0 | 0 | None | None | None | None |
| 160 | 23 | 183 | 2 | d | complete | 11681 | 670 | 0 | 0 | None | None | None | None |
| 160 | 23 | 183 | 3 | c | complete | 11681 | 669 | 0 | 0 | None | None | None | None |
| 160 | 23 | 183 | 4 | s | complete | 11681 | 669 | 0 | 0 | None | None | None | None |
| 161 | 22 | 183 | 1 | h | complete | 5364 | 299 | 0 | 0 | None | None | None | None |
| 161 | 22 | 183 | 2 | c | complete | 5364 | 299 | 0 | 0 | None | None | None | None |
| 161 | 22 | 183 | 3 | d | complete | 5364 | 299 | 0 | 0 | None | None | None | None |
| 161 | 22 | 183 | 4 | s | complete | 5364 | 299 | 0 | 0 | None | None | None | None |

## g160 vs g161 at equal f=183

| metric | g160/h23 | g161/h22 |
| --- | ---: | ---: |
| root f | 183 | 183 |
| empties | 3 | 4 |
| legal | 76 | 95 |
| boundaries | 26 | 25 |
| best next F | None | None |
| best next g | None | None |
| best next h | None | None |
| best next f | None | None |
| bridge loss | None | None |
| time to first viable | None | None |
| proof prunes | 44395 | 20293 |

## Bridge summary

| root | best terminal | bridge loss | class | time |
| ---- | ------------- | ----------: | ----- | ---: |
| g142/h32/f174 | F4 f=186 | 12 | ZERO_SLACK | 240.3 |
| g160/h23/f183 | none | None | complete | 115.4 |
| g161/h22/f183 | none | None | complete | 53.1 |
| g141 control | f=186 | 12 | frozen | — |
| g158 control | f=185 | 5 | frozen | — |

raw=5 viable=1 surplus1=0 strong=0 closed_hits=1

## Continuation

portfolio n=0 sources=[] targets=[] stop=`None` unique=None exp=None generated=None maxF=4 exhausted=False



wall_s=408.8 reserve=150.0s no_stage_b=True

## Interpretation

g142 converts like g141: Hearts F4 g=162/h=24/f=186/loss=+12 at 46.9s, an exact known-closed v0.80 state, so continuation was correctly skipped. At equal f=183, neither g160 nor g161 can cash out; the more-assembled g161 exhausts a smaller proof-viable graph (5364 unique / 13s vs 11681 / 29s). g158 remains the only F3 that reached leftover slack (f=185).

## Next recommendation

g158 remains the only F3 that converted with leftover slack. Stop mining this g128 F3 family; produce a better post-SD5 F2/root. Do not resume closed F4/F5 roots.

