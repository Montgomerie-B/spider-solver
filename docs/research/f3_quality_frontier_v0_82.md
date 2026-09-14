# f3_quality_frontier_v0_82

Verdict: `F3_FRONTIER_SEARCH_LIMITED`

promising new F3 branches remain resource-limited

Quality-diverse F3 harvest from autonomous g129, then short proof-aware next-foundation screening. Canonical 172 was not a search input. Exhausted v0.80/v0.81 F4/F5 roots were not resumed.

## g129 root

{'ok': True, 'g': 129, 'foundations': 2, 'face_down': 2, 'stock_rows': 0, 'assembly_h': 43, 'assembly_f': 172, 'v076_digest_match': True}

## F3 harvest

unique=83897 expanded=7403 generated=192129 F3=499 pareto=17 stop=`time limit` t=240.0s prunes=50033

## F3 Pareto frontier

| F3 |  g |  h |  f | slack | fd | empties | legal | boundaries | tag |
| -- | -: | -: | -: | ----: | -: | ------: | ----: | ---------: | --- |
| 3 | 141 | 33 | 174 | 12 | 2 | 2 | 41 | 36 | g141_control |
| 3 | 142 | 32 | 174 | 12 | 2 | 2 | 47 | 35 |  |
| 3 | 144 | 31 | 175 | 11 | 2 | 2 | 47 | 34 |  |
| 3 | 158 | 22 | 180 | 6 | 2 | 3 | 80 | 25 | g158_control |
| 3 | 154 | 28 | 182 | 4 | 2 | 1 | 30 | 31 |  |
| 3 | 155 | 27 | 182 | 4 | 2 | 1 | 37 | 30 |  |
| 3 | 161 | 22 | 183 | 3 | 2 | 4 | 95 | 25 |  |
| 3 | 157 | 27 | 184 | 2 | 2 | 2 | 55 | 30 |  |
| 3 | 163 | 21 | 184 | 2 | 2 | 2 | 75 | 24 |  |
| 3 | 163 | 22 | 185 | 1 | 2 | 5 | 67 | 25 |  |
| 3 | 164 | 21 | 185 | 1 | 2 | 3 | 100 | 24 |  |
| 3 | 165 | 20 | 185 | 1 | 2 | 1 | 59 | 23 |  |
| 3 | 166 | 19 | 185 | 1 | 2 | 2 | 96 | 22 |  |
| 3 | 163 | 23 | 186 | 0 | 2 | 5 | 104 | 26 |  |
| 3 | 165 | 21 | 186 | 0 | 2 | 4 | 115 | 24 |  |
| 3 | 166 | 20 | 186 | 0 | 2 | 3 | 107 | 23 |  |
| 3 | 167 | 19 | 186 | 0 | 2 | 3 | 129 | 22 |  |

Controls: g141 cheapest F3 (f174, later bridge loss +12); g158 assembled F3 (f180, later bridge loss +5). Active six exclude those exact digests.

## Selected new F3s

[{'role': 'lowest_f', 'g': 142, 'h': 32, 'f': 174, 'empties': 2, 'legal': 47, 'boundaries': 35}, {'role': 'lowest_h', 'g': 166, 'h': 19, 'f': 185, 'empties': 2, 'legal': 96, 'boundaries': 22}, {'role': 'highest_mobility', 'g': 167, 'h': 19, 'f': 186, 'empties': 3, 'legal': 129, 'boundaries': 22}, {'role': 'most_empties', 'g': 163, 'h': 23, 'f': 186, 'empties': 5, 'legal': 104, 'boundaries': 26}, {'role': 'pareto_balanced', 'g': 160, 'h': 23, 'f': 183, 'empties': 3, 'legal': 76, 'boundaries': 26}, {'role': 'fill', 'g': 141, 'h': 34, 'f': 175, 'empties': 1, 'legal': 26, 'boundaries': 37}]

## Bridge-value table

| root g | root h | root f | target | terminal F | terminal g | terminal h | terminal f | slack | bridge loss |
| -----: | -----: | -----: | ------ | ---------: | ---------: | ---------: | ---------: | ----: | ----------: |
| 166 | 19 | 185 | h | None | None | None | None | None | None |
| 167 | 19 | 186 | h | None | None | None | None | None | None |
| 160 | 23 | 183 | h | None | None | None | None | None | None |
| 163 | 23 | 186 | h | None | None | None | None | None | None |
| 142 | 32 | 174 | h | None | None | None | None | None | None |
| 141 | 34 | 175 | h | None | None | None | None | None | None |

Stage B promoted roots/targets: [[166, 'h'], [166, 'd'], [167, 'h'], [167, 'd'], [160, 'h'], [160, 'd'], [163, 'h'], [163, 'd']]

raw=0 viable=0 surplus1=0 strong=0 closed_hits=0

## Frozen controls

g141: root f=174 best next f=186 bridge loss +12
g158: root f=180 best next f=185 bridge loss +5

## Continuation

portfolio n=0 stop=`None` unique=None exp=None maxF=3 exhausted=False recommend_continue=False



## Interpretation

Harvest found a diverse F3 Pareto including both frozen controls. 10s/target screening did not beat g158: F3s already at f>=185 exhaust immediately (no conversion slack), while cheap/interior F3s hit the time limit before F4, consistent with the g141 control needing ~49s.

## Next recommendation

Reallocate the 900s envelope to v0.80-length proof-aware probes of the already-harvested cheap/interior F3s (especially g142 f=174 and g160 f=183); do not resume closed F4/F5 roots and do not widen wall time.

