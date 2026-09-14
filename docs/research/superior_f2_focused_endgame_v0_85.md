# superior_f2_focused_endgame_v0_85

Verdict: `SUPERIOR_F2_STRONG_F3_STALL`

F3 g=141 f=174 t=5.276078299968503

Focused stock-empty search from the v0.84 superior g128 F2. One root. Frozen COST/REVEAL/CONSTRUCTION/READINESS/ECONOMY/COMPLETION. Canonical 172 was not a search input. Closed-state skip omitted for v0.74 comparability.

## Root

ok=True pre_g=128 post_g=129 h=42 f=171 slack=15 deals=5 fd=2

vs old g128 digest_diff=True ident_diff=True
vs 187 digest_diff=True ident_diff=True

## Snapshots

| t | maxF | unique | exp | prunes | min_f | min_h |
| -: | ---: | -----: | --: | -----: | ----: | ----: |
| t5 | 2 | 0 | 0 | 0 | 171 | 30 |
| t10 | 3 | 0 | 0 | 0 | 171 | 25 |
| t30 | 3 | 0 | 0 | 0 | 171 | 21 |
| t60 | 3 | 0 | 0 | 0 | 171 | 21 |
| t120 | 3 | 0 | 0 | 0 | 171 | 21 |
| t300 | 3 | 0 | 0 | 0 | 171 | 18 |
| t600 | 3 | 0 | 0 | 0 | 171 | 18 |
| end | 3 | 98513 | 11451 | 55232 | 171 | 18 |

## F2–F8 frontier (cheapest g)

| F | g | h | f | slack | fd | empties | legal | boundaries | time |
| -: | -: | -: | -: | ----: | -: | ------: | ----: | ---------: | ---: |
| 2 | 129 | 42 | 171 | 15 | 2 | 0 | 5 | 46 | 0.0 |
| 3 | 141 | 33 | 174 | 12 | 2 | 2 | 43 | 28 | 868.2 |

first F3 g=148 f=177 t=5.3
cheapest F3 g=141 f=174 t=868.2

## Comparisons

v0.78 old g128: first F3 g=158/f=180, cheapest F3 g=141/f=174, maxF=3
v0.74 187 root: post 130/h41/f171 terminal 187; F3 156/183

stop=`time limit` unique=98513 exp=11451 prunes=55232 wall=900.3
lanes={'completion': 1935, 'construction': 2337, 'cost': 870, 'economy': 1600, 'horizon': 0, 'readiness': 2363, 'reveal': 2346}
closed_guard=False

## Interpretation

The v0.84 10s signal reproduced: first F3 g=148/h=29/f=177 at 5.3s. Cheapest F3 later is g=141/h=33/f=174 at 868s — same numbers as the old g128 family but a different digest. No F4 in 900s. Versus the 187 root (same f=171, h=41), extra g slack bought a cheaper/faster F3 but not deep conversion; the 187 root still reached F8. Short-rollout superiority is real at F3 and does not persist to F4+.

## Next recommendation

Analyse this new F3 quality/bridge in isolation; do not mix it with the exhausted old g128 F3 family.

