# g158_proof_aware_f4_v0_81

Verdict: `G158_BRIDGE_DEEP_ENDGAME`

viable F4 n=16 maxF=5

Proof-aware stock-empty tactical bridge from the more-assembled g158 F3. Canonical 172 was not a search input. The exhausted g161/g162 F4 roots were not reused.

Slack convention: `ceiling - f`. F3 slack = 6.

## g158 root verification

ok=True g=158 F=3 h=22 f=180 slack=6 fd=2 empties=3 legal=80 boundaries_recorded=18 visible_runs=25 stock_rows=0 can_deal=False discovery_s=10.889

Provenance: opening → autonomous g123 → v0.71 machine tactical → g128 F2 → SD5 → g129 stock-empty → v0.78 search → g158 F3

## Foundation / target ranking at g158

ready=['s', 'h', 'd', 'c'] n_ready=4 best=h second=c

| rank | suit | founded | cover | blockers | inacc joins | K | A | gap | merges | buried | exposed |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | h | 0 | 3 | 98 | 8 | 11 | 1 | 5 | 0 | 8 | 1 |
| 2 | c | 1 | 4 | 37 | 2 | 0 | 21 | None | 0 | 1 | 2 |
| 3 | d | 1 | 4 | 41 | 3 | 19 | 0 | 3 | 0 | 3 | 1 |
| 4 | s | 1 | 9 | 65 | 8 | 9 | 0 | 11 | 0 | 6 | 3 |

## Stage A (equal target probes)

| rank | suit | raw | viable | surplus | cheap raw g/f | cheap viable g/f | slack | prunes | unique | t s |
| ---: | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | h | 5 | 5 | 0 | 167/186 | 167/186 | 0 | 20697 | 32921 | 120.1 |
| 2 | c | 16 | 16 | 2 | 173/185 | 173/185 | 1 | 15114 | 31055 | 120.1 |
| 3 | d | 28 | 28 | 3 | 169/185 | 169/185 | 1 | 15261 | 30765 | 120.2 |
| 4 | s | 0 | 0 | 0 | None/None | None/None | None | 23225 | 35230 | 120.0 |

Stage B promoted: ['d', 'c']

[{'suit': 'd', 'viable': 20, 'surplus': 3, 'cheap_g': 169, 'best_f': 185}, {'suit': 'c', 'viable': 16, 'surplus': 2, 'cheap_g': 173, 'best_f': 185}]

Tactical 600.3s / budget 600.0. h-cache calls=247132 hits=83970 misses=163162 s=27.81. proof calls=169896 prunes=92835.
Raw=37 viable portfolio=16 surplus unique=5.
best f=185 best slack=1 cheapest g=167 lowest h=11.

## F4 economics vs g158/h22/f180

| g | h | f | slack | Δg | Δh | Δf | payback | class | target |
| -: | -: | -: | ----: | -: | -: | -: | ---: | --- | --- |
| 167 | 19 | 186 | 0 | 9 | -3 | 6 | 0.33 | VIABLE_TARGET_CASHOUT | h |
| 170 | 15 | 185 | 1 | 12 | -7 | 5 | 0.58 | SURPLUS_TARGET_CASHOUT | d |
| 174 | 11 | 185 | 1 | 16 | -11 | 5 | 0.69 | SURPLUS_TARGET_CASHOUT | c |
| 174 | 12 | 186 | 0 | 16 | -10 | 6 | 0.62 | VIABLE_TARGET_CASHOUT | c |
| 173 | 12 | 185 | 1 | 15 | -10 | 5 | 0.67 | SURPLUS_TARGET_CASHOUT | c |
| 171 | 14 | 185 | 1 | 13 | -8 | 5 | 0.62 | SURPLUS_TARGET_CASHOUT | d |
| 172 | 13 | 185 | 1 | 14 | -9 | 5 | 0.64 | SURPLUS_TARGET_CASHOUT | d |
| 167 | 19 | 186 | 0 | 9 | -3 | 6 | 0.33 | VIABLE_TARGET_CASHOUT | h |
| 168 | 18 | 186 | 0 | 10 | -4 | 6 | 0.40 | VIABLE_TARGET_CASHOUT | h |
| 168 | 18 | 186 | 0 | 10 | -4 | 6 | 0.40 | VIABLE_TARGET_CASHOUT | h |
| 168 | 18 | 186 | 0 | 10 | -4 | 6 | 0.40 | VIABLE_TARGET_CASHOUT | h |
| 169 | 17 | 186 | 0 | 11 | -5 | 6 | 0.45 | VIABLE_TARGET_CASHOUT | d |
| 170 | 16 | 186 | 0 | 12 | -6 | 6 | 0.50 | VIABLE_TARGET_CASHOUT | d |
| 170 | 16 | 186 | 0 | 12 | -6 | 6 | 0.50 | VIABLE_TARGET_CASHOUT | d |
| 170 | 16 | 186 | 0 | 12 | -6 | 6 | 0.50 | VIABLE_TARGET_CASHOUT | d |
| 170 | 16 | 186 | 0 | 12 | -6 | 6 | 0.50 | VIABLE_TARGET_CASHOUT | d |

## Continuation

mode=viable_f4 maxF=5 unique=2353 exp=124 generated=4710 stop=`complete` solution_g=None

exhausted=True resource_limited=False recommend_continue_from_these_roots=False

the proof-viable continuation subgraph from the admitted roots was exhausted.

## g141 vs g158

| field | g141 cheapest F3 | g158 assembled F3 |
| --- | ---: | ---: |
| root g/h/f | 141/33/174 | 158/22/180 |
| root slack | 12 | 6 |
| best F4 f | 186 | 185 |
| best slack | 0 | 1 |
| cheapest F4 g | 161 | 167 |
| lowest F4 h | 24 | 11 |
| continuation stop | complete | complete |
| exhausted | yes | True |

## Raw F3–F8 frontier

| F |  g |  h |  f | slack | target | provenance | time |
| - | -: | -: | -: | ----: | ------ | ---------- | ---: |
| 3 | 158 | 22 | 180 | 6 |  | v078_first_f3 | 10.9 |
| 4 | 167 | 19 | 186 | 0 | h | VIABLE_TARGET_CASHOUT | 3.3 |
| 5 | 173 | 12 | 185 | 1 | c | SURPLUS_TARGET_CASHOUT | 29.3 |
| 4 | 169 | 17 | 186 | 0 | d | VIABLE_TARGET_CASHOUT | 2.5 |
| 4 | 169 | 17 | 186 | 0 | d | VIABLE_TARGET_CASHOUT | 2.5 |
| 5 | 173 | 12 | 185 | 1 | c | SURPLUS_TARGET_CASHOUT | 29.2 |

## Proof-viable F3–F8 frontier

| F |  g |  h |  f | slack | target | provenance | time |
| - | -: | -: | -: | ----: | ------ | ---------- | ---: |
| 3 | 158 | 22 | 180 | 6 |  | v078_first_f3 | 10.9 |
| 4 | 167 | 19 | 186 | 0 | h | viable | 3.3 |
| 5 | 173 | 12 | 185 | 1 | c | viable | 29.3 |
| 4 | 170 | 15 | 185 | 1 | d | viable | 2.5 |
| 4 | 170 | 15 | 185 | 1 | d | viable | 2.5 |
| 5 | 173 | 12 | 185 | 1 | c | viable | 29.2 |

## Search accounting

wall_s=611.2 tactical_s=600.3 continuation_s=10.8 peak_rss_mb=61.7
tactical unique/exp/gen=163162/9252/404540
continuation unique/exp/gen=2353/124/4710
bound prunes/calls=2368/2492

Incumbent remains 187. RECORD_MW=119 CANONICAL_MW=172 incumbent_updated=False.

## Interpretation

g158 produced surplus F4/F5 at f=185 (slack +1) and continuation reached F5. That outperforms the g141 zero-slack F4 ridge (f=186, maxF=4). the proof-viable continuation subgraph from the admitted roots was exhausted.

## Next recommendation

Do not rerun global continuation from these exact F4/F5 roots; the proof-viable subgraph is exhausted. Next hierarchical step is a proof-aware tactical cash-out from a surplus F5 (f<=185), preserving assembled F3 quality rather than cheapest-F3 g.

