# integrated_whole_game_v0_68

Verdict: `INTEGRATED_WHOLE_GAME_LINEAGE_NOT_REDISCOVERED`

The integrated solver ran from the untouched opening with incumbent 192 and ceiling 191. It autonomously rediscovered the healthy F1 (g=71, rows=3, fd=10, Spades) but did not rediscover the g=130 rows=1 F2 or a complete line below 192.

## Incumbent 192

Replay of `solutions/4925153_autonomous_v0_67.moves` from untouched opening: legal, g=192, five Deals, eight foundations, stock empty, tableau empty, solved. Header comment corrected to v0.67; moves unchanged.

`RECORD_MW_COST = 119`, `CANONICAL_MW_COST = 172` unchanged. Autonomous ceiling is 191.

## Lower-bound telemetry

v0.67 reported `post_stock_prunes = 0` because the thin “solved” epoch record omitted kernel lower-bound fields. Every epoch exit (abort, solved, harvest) now copies prune/call/second/`prunes_by_F` fields.

This run: cumulative prunes 8418 = sum of epoch prunes. Calls and seconds also reconcile.

## Preview performance

Memoisation by exact whole-game identity, overlaying `pre_g`. Ranking and Deal semantics unchanged.

This run: 886 calls, 6 hits, 880 misses, 3.14 s compute. Rows=1 visited almost-unique states, so cache barely helped. Rows=1 still only expanded **86** states in 129 s — the starved epoch.

## Architecture (from opening)

- Epoch scheduler (v0.59)
- Operational viability (v0.63)
- Frozen v0.66 final-Deal preview at rows=1
- v0.67 assembly bound + COMPLETION after stock empty
- Machine 192 checkpoints: 1 per epoch, exact prefix g
- No DURABILITY, no canonical policy reads

## Envelope

900.2 s / unique 140,082 / expanded 33,177 / 36.9 exp/s / ceiling 191 / width 256 / RSS not aborting.

## Epoch allocation (actual)

| rows | alloc s | used s | unique | expanded | max F | notes |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 5 | 112 | 113 | 29188 | 9250 | 0 | |
| 4 | 112 | 113 | 27706 | 2888 | 0 | incumbent ckpt survived |
| 3 | 193 | 193 | 33335 | 11260 | 1 | F1=71 rediscovered |
| 2 | 161 | 161 | 29652 | 7472 | 1 | |
| 1 | 128 | 129 | 875 | **86** | 1 | preview harvest starved |
| 0 | 191 | 191 | 19326 | 2221 | 2 | 8418 proof-prunes |

## Checkpoints

Injected 5, survived 5. Cheapest F1/F2 have `incumbent_control = null` — they were found autonomously, not as the checkpoint state.

## F1–F8 vs v0.67 references

| metric | v0.67 incumbent | v0.68 whole-game |
| --- | ---: | ---: |
| best g | 192 | none |
| F1 g/fd/rows | 71 / 10 / 3 Spades | **71 / 10 / 3 Spades** |
| F2 g/fd/rows | 130 / 2 / 1 | 135 / 2 / **0** |
| post-SD5 entry | ~135 F=2 | cheapest F2 already post-stock |
| F3 | 173 | none |
| F5 | 185 | none |
| F7 | 191 | none |
| F8 | 192 | none |
| proof-prunes | 57270 | 8418 (F1 7279, F2 1139) |

No complete g. No `solutions/4925153_autonomous_v0_68.moves`.

## 198 → 192 forensic savings (after search)

Net **6 MW**. Exclusive-bucket rehandle 126 → 110 (Δ16). Tagged rehandle MW 133 → 118. Mixed-park 10 → 15. Primary progress 15 → 19.

Epoch waterfall (198 minus 192):

| epoch | 192 Δg | 198 Δg | 192 vs 198 |
| --- | ---: | ---: | --- |
| pre-SD1 | 32 | 32 | 0 |
| SD1-SD2 | 31 | 25 | 192 +6 |
| SD2-SD3 | 8 | 14 | 192 −6 |
| SD3-SD4 | 48 | 10 | 192 +38 (F2 investment) |
| SD4-SD5 | 11 | 45 | 192 −34 |
| post-SD5 | 57 | 67 | 192 −10 |

192 is closer to 172 than 198 is in one respect: it enters post-SD5 already at F=2. It is still a distinct machine strategy: post-SD5 remaining 57 vs 172’s 22; rehandle 110 vs 102. Do not copy 172.

## Generality

Demonstrated together from move zero: epoch scheduler, operational viability, Deal preview, assembly bound. The **focused** F2-continuation success of v0.66/v0.67 did not automatically become a whole-game rediscovery: rows=1 was starved, and the cheap F2 found here is a post-stock g=135 / h=39 board, not the g=130 rows=1 F2 that 192 was built from.

## Next recommendation

Focus on whole-game portfolio survival / Deal-transition reasoning rather than endgame search. Do not widen runtime. Do not copy the canonical route.
