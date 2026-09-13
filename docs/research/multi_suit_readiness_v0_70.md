# multi_suit_readiness_v0_70

Verdict: `MULTI_SUIT_READINESS_HYPOTHESIS_FALSE`

The autonomous 192 rows=1 cash-out suit was **operational rank 1 at every step**. Alternate-rank lanes were live and did not recover a pre-SD5 F2.

## 192 rows=1 forensic audit (evaluation only)

13 tableau states from epoch-entry g=123 / F=1 / fd=2 until SD5.

| | |
| --- | --- |
| Entry ready suits | hearts, diamonds |
| Best (rank 1) throughout | diamonds |
| Suit cashed | diamonds at **g=130** |
| Rank of that suit | **1 / 13 states (100%)** |
| Classification | `TARGET_SUIT_WAS_PRIMARY` |

Diamonds was already the READINESS-lane target. Hearts was rank 2; it was never the cashed suit. The missing mechanism is not “search the other ready suit”. It is converting the already-best ready suit in a short, cheap sequence before Deal.

## Multi-suit architecture

`readiness` = operational rank 1 (unchanged, all epochs).  
`readiness_r2` / `readiness_r3` = `operational_viability_key(ranked[1|2], g)`, **rows=1 only**. Rank identity, not suit names. Harvest categories, Pareto, preview, assembly bound, ceiling 191 unchanged.

## Preflight (192 rows=1 checkpoint, 4 s)

23 expansions. r1=4, **r2=2 (live)**, r3=0. max F=1. Identity/accounting clean.

## Whole-game envelope

Untouched opening, 900.2 s, unique 90,593, expanded 21,487, ceiling 191, width 256.

## Rows=1 vs v0.69

| | v0.69 | v0.70 |
| --- | ---: | ---: |
| expanded | 1600 | 1001 |
| unique | 9062 | 6569 |
| exp/s | 12.5 | 7.8 |
| max F | 1 | 1 |
| cheapest pre-SD5 F2 | none | none |
| F2 post-stock | 135 | 135 |
| F3 | none | none |
| terminal | none | none |
| preview s | 42.2 | 32.3 |
| Pareto s | 10.9 | 10.1 |

Throughput did not collapse. Extra lanes share round-robin, so primary expansions fall (expected).

### Rank-lane expansions (rows=1)

| lane | expansions |
| --- | ---: |
| readiness (r1) | 154 |
| readiness_r2 | 144 |
| readiness_r3 | 166 |
| construction | 169 |
| reveal | 168 |

Rank swaps among consecutive rows=1 visits: 983. Ready≥2: 6897/6897. Ready≥3: 3992.

## Checkpoint descendants

2895 rows=1 previewed states from the g=123 F=1 checkpoint. **Zero** reached F=2 before SD5.

## Best pre-SD5 F2

None. Cheapest F2 remains g=135 / fd=2 / rows=0 / Spades+Diamonds / h=39.

## F1–F8

F1 = 71 / fd 10 / rows 3 Spades. Proof-prunes 2620.

**Best complete g:** none. No v0.70 solution file.

## Interpretation

v0.69 restored coverage. v0.70 asked whether the solver was expanding the wrong ready suit. The 192 route says no: it cashed the already-primary diamonds in seven MW from the epoch-entry. Alternate-rank expansion is the wrong next lever.

## Next recommendation

Do not add more suit-diversity lanes. Move to a generic bounded pre-Deal cash-out search. Do not widen runtime. Do not copy the canonical route.
