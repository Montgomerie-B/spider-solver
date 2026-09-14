# f2_quality_frontier_v0_84

Verdict: `F2_FRONTIER_FINDS_SUPERIOR_ROOT`

n=2 maxF=3

Pre-SD5 F2 quality harvest from autonomous g123, exact final Deal, frozen v0.76-style rollout. Canonical 172 was not a search input. The exhausted g128 F3 family was not rerun.

## g123 root

{'ok': True, 'g': 123, 'foundations': 1, 'face_down': 2, 'stock_rows': 1, 'digest_ok': True}

ready=['d', 'h'] n_ready=2 per_target_s=180.0

## Harvest

raw=279 unique_pre=279 F2=279 deeper=0 t=358.7s

## Post-Deal Pareto

| pre g | F | target | fd | post g | post h | post f | slack | legal | boundaries | tag |
| ----: | -: | ------ | -: | -----: | -----: | -----: | ----: | ----: | ---------: | --- |
| 128 | 2 | d | 2 | 129 | 42 | 171 | 15 | 5 | 46 |  |
| 129 | 2 | d | 2 | 130 | 41 | 171 | 15 | 5 | 45 | g187_f2 |
| 133 | 2 | d | 2 | 134 | 40 | 174 | 12 | 5 | 44 |  |
| 133 | 2 | d | 2 | 134 | 40 | 174 | 12 | 5 | 44 |  |
| 133 | 2 | d | 2 | 134 | 40 | 174 | 12 | 5 | 44 |  |
| 133 | 2 | d | 2 | 134 | 40 | 174 | 12 | 5 | 44 |  |
| 134 | 2 | d | 2 | 135 | 40 | 175 | 11 | 6 | 44 |  |
| 134 | 2 | d | 2 | 135 | 40 | 175 | 11 | 6 | 44 |  |
| 135 | 2 | d | 2 | 136 | 42 | 178 | 8 | 8 | 46 |  |
| 138 | 2 | d | 2 | 139 | 41 | 180 | 6 | 9 | 45 |  |

proof-viable=279 proof-dead=0

## F2 cost-vs-quality

| pre g | F | target | fd | post g | post h | post f | legal | boundaries | rollout maxF | best rollout f |
| ----: | -: | ------ | -: | -----: | -----: | -----: | ----: | ---------: | -----------: | -------------: |
| 128 | 2 | d | 2 | 129 | 42 | 171 | 5 | 46 | 3 | 177 |
| 133 | 2 | d | 2 | 134 | 40 | 174 | 5 | 44 | 2 | 174 |
| 138 | 2 | d | 2 | 139 | 41 | 180 | 9 | 45 | 2 | 180 |
| 133 | 2 | d | 2 | 134 | 40 | 174 | 5 | 44 | 2 | 174 |
| 129 | 2 | d | 2 | 130 | 41 | 171 | 5 | 45 | 2 | 171 |
| 128 | 2 | d | 2 | 129 | 43 | 172 | 5 | 47 | 3 | 180 |
| 129 | 2 | d | 2 | 130 | 42 | 172 | 5 | 46 | 2 | 172 |
| 129 | 2 | d | 2 | 130 | 42 | 172 | 5 | 46 | 2 | 172 |
| 129 | 2 | d | 2 | 130 | 42 | 172 | 5 | 46 | 3 | 179 |
| 129 | 2 | d | 2 | 130 | 42 | 172 | 5 | 46 | 2 | 172 |
| 130 | 2 | d | 2 | 131 | 41 | 172 | 5 | 45 | 2 | 172 |
| 130 | 2 | d | 2 | 131 | 41 | 172 | 5 | 45 | 2 | 172 |

## Stage A ranking

[{'role': 'lowest_f', 'post_g': 129, 'max_F': 3, 'min_f': 171, 'stop': 'time limit', 'beats_g128': True}, {'role': 'fill', 'post_g': 130, 'max_F': 3, 'min_f': 172, 'stop': 'time limit', 'beats_g128': True}, {'role': 'fill', 'post_g': 129, 'max_F': 3, 'min_f': 172, 'stop': 'time limit', 'beats_g128': False}, {'role': 'fill', 'post_g': 130, 'max_F': 2, 'min_f': 171, 'stop': 'time limit', 'beats_g128': False}, {'role': 'fill', 'post_g': 130, 'max_F': 2, 'min_f': 172, 'stop': 'time limit', 'beats_g128': False}, {'role': 'fill', 'post_g': 130, 'max_F': 2, 'min_f': 172, 'stop': 'time limit', 'beats_g128': False}, {'role': 'fill', 'post_g': 130, 'max_F': 2, 'min_f': 172, 'stop': 'time limit', 'beats_g128': False}, {'role': 'fill', 'post_g': 131, 'max_F': 2, 'min_f': 172, 'stop': 'time limit', 'beats_g128': False}, {'role': 'fill', 'post_g': 131, 'max_F': 2, 'min_f': 172, 'stop': 'time limit', 'beats_g128': False}, {'role': 'pareto_balanced', 'post_g': 134, 'max_F': 2, 'min_f': 174, 'stop': 'time limit', 'beats_g128': False}, {'role': 'lowest_h', 'post_g': 134, 'max_F': 2, 'min_f': 174, 'stop': 'time limit', 'beats_g128': False}, {'role': 'highest_mobility', 'post_g': 139, 'max_F': 2, 'min_f': 180, 'stop': 'time limit', 'beats_g128': False}]

Stage B promoted: ['lowest_f', 'fill', 'fill', 'fill']

## Controls

g128 historical post g=129 h=43 f=172 F3~158/180
187 historical post g=130 h=41 f=171
rediscovered=['g128_tactical', 'g187_f2']

## Continuation

portfolio n=24 closed_hits=0 stop=`time limit` unique=43336 exp=2090 maxF=3 exhausted=False

wall_s=900.2

## Interpretation

A new diamonds F2 at pre-g=128 (distinct from the v0.71 g128 control) deals to post g=129/h=42/f=171, then reaches F3 g=148/f=177 in ~5s — cheaper and faster than the historical g128 control (F3 g=158/f=180 ~10s). Paying more for lower-h or higher-mobility F2s (pre 133–138) stalled at F2 in bounded rollout. Hearts produced no F2 in 180s. Continuation from 24 live descendants was time-limited at maxF=3.

## Next recommendation

Make the new post-SD5 F2/root the next focused endgame control; do not return to the g128 F3 family.

