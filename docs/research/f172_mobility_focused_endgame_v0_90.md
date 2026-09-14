# f172_mobility_focused_endgame_v0_90

Verdict: `F172_MOBILITY_STRONG_F3_STALL`

F3 g=134 f=174 t=1.1730631000245921

Branch: `agent/f172-mobility-focused-endgame-v0-90`
Base: `01c1dee644dc3999e67a56e497743f94d17faef2`

One-root frozen stock-empty search from the v0.89 `f172_mobility` post-SD5 state. Canonical 172 was not a search input. Closed-state skip omitted for v0.74/v0.85 comparability.

## Root

ok=True source=NEW_G128_F2 prep_Δg=2 pre_g=130 post_g=131 h=41 f=172 slack=14 legal=10 deals=5 fd=2

vs Root A digest_diff=True ident_diff=True
vs 187 digest_diff=True ident_diff=True

Autonomy:

- opening→g123 is machine incumbent ancestry
- g123→F2 is generic machine tactical cash-out (v0.84 NEW_G128_F2)
- the preparation state came from generic tableau-only v0.88 search
- the f172 root was selected by the frozen v0.89 generic mobility/Pareto evaluation
- SD5 is the real engine Deal
- no human/canonical move entered the route

## Snapshots

| t | maxF | unique | exp | prunes | min_f | min_h | mobility | vis_runs | mixed |
| -: | ---: | -----: | --: | -----: | ----: | ----: | -------: | -------: | ----: |
| t5 | 3 | 0 | 0 | 0 | 172 | 31 | 46 | 35 | 25 |
| t10 | 3 | 0 | 0 | 0 | 172 | 28 | 49 | 31 | 22 |
| t30 | 3 | 0 | 0 | 0 | 172 | 19 | 149 | 22 | 14 |
| t60 | 3 | 0 | 0 | 0 | 172 | 19 | 149 | 22 | 13 |
| t120 | 3 | 0 | 0 | 0 | 172 | 19 | 149 | 22 | 13 |
| t300 | 3 | 0 | 0 | 0 | 172 | 19 | 149 | 22 | 13 |
| t600 | 3 | 0 | 0 | 0 | 172 | 16 | 154 | 19 | 10 |
| end | 3 | 97262 | 7510 | 62566 | 172 | 14 | 204 | 17 | 10 |

## F2–F8 frontier (cheapest g)

| F | g | h | f | slack | fd | empties | legal | vis_runs | mixed | time |
| -: | -: | -: | -: | ----: | -: | ------: | ----: | -------: | ----: | ---: |
| 2 | 131 | 41 | 172 | 14 | 2 | 0 | 10 | 45 | 35 | 0.0 |
| 3 | 134 | 40 | 174 | 12 | 2 | 1 | 13 | 43 | 34 | 9.9 |

first F3 g=138 h=35 f=173 t=1.2
cheapest F3 g=134 h=40 f=174 t=9.9
lowest-f F3 g=138 h=35 f=173 t=1.2

## Comparisons

v0.85 Root A: first F3 g=148/h=29/f=177 at 5.3s; cheapest F3 g=141/h=33/f=174; maxF=3
v0.74 187 root: post 130/h41/f171/legal5 terminal 187; F3 {'g': 156, 'h': 27, 'f': 183}

stop=`time limit` unique=97262 exp=7510 prunes=62566 wall=900.6
lanes={'cost': 609, 'reveal': 1554, 'construction': 1443, 'readiness': 1564, 'horizon': 0, 'economy': 980, 'completion': 1360} horizon_exp=0
closed_guard=False closed_hits=0 reopen=0

## Interpretation

The 10-second F3 signal reproduced and strengthened. First F3 arrived at 1.2 s (g138/h35/f173, legal=20, slack+13) versus Root A's 5.3 s (g148/h29/f177). Cheapest-g F3 is g134/h40/f174 at 9.9 s versus Root A's g141/h33/f174. Lowest-f F3 is f=173 versus Root A's cheapest f=174.

No F4 in 900 s (unique=97,262, same stall class as v0.85). Known-closed hits=0, so this F3 basin is new. Extra pre-Deal mobility bought a cheaper/faster F3, not a durable F4+ conversion under frozen global search.

Mid-run unique/expanded/prunes in the snapshot table are kernel-lag zeros; the end row is authoritative.

## Next recommendation

Make the best novel F3 the next proof-aware tactical bridge root.

