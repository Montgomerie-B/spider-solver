# Spider Solver v0.43 — Final-Deal Timing Pivot

## 1. Verdict

`POST_SD5_SEARCH_STATE_EXPLOSION` — Foundation 2 not found before unique/RSS limit

A diverse 720-state post-SD4 union (Diamond-ready + Heart-H9 + Diamond multi-edge, **no pack_state overlap**) was dealt through SD5, including 103,513 exact pre-Deal receiving states (depth 0–4). Exact post-stock UCS then hit **600,000 unique symmetry states in 182 s** with **min live g = 81** and **zero Foundation-2 witnesses**. Peak RSS 2.46 GiB (under 3 GiB). SD5 was never expanded a second time.

This does **not** prove Foundation 2 is unreachable under MW<=120. It proves the 103k-seed fan-out exhausted the unique envelope while still sitting on cheap post-Deal g (closed below 81).

- Branch: `agent/final-deal-timing-pivot-v0-43`
- Base SHA: `bc90822314403744e15a2158387b5ef9bf0e6f5b`

## 2. Why we are not continuing G6_8

v0.42 showed G6_8 can start peeling (6–10 mixed cards) but exposure was not reached under MW<=100, while G6_9 cannot start until a rank-6 landing exists. SD5 injects another 2D and 5D, so the unique-card Diamond obligations cease to be globally compulsory. Forcing G6_8 further before testing SD5 would risk optimising a constraint that the known final row removes. This is horizon widening, not a proof that G6_8 is unreachable.

## 3. Source union

Replay from `deals/4925153.txt`: **720/720 ok**. Exact pack_state dedup: 720 unique (raw 720, **zero cross-lineage overlap**).

| Lineage | Raw | Unique | MW |
|---|---|---|---|
| diamond_ready (v0.39) | 256 | 256 | 75–77 |
| heart_h9 (v0.37) | 256 | 256 | 77–78 |
| diamond_multi_edge (v0.41) | 208 | 208 | 82–86 |

Cost counts: 75:16, 76:128, 77:144, 78:224, 82:96, 83:32, 84:8, 85:24, 86:48.

Every source: one Spade foundation, SD1–SD4 consumed, stock_rows=1, SD5 legal (Unrestricted Deal).

## 4. SD5 audit

Engine row, left-to-right:

`3H, 10H, 2D, 3C, 9H, 7C, 7H, AS, 3C, 5D`

Matches expected. Deal cost = 1. Immediate auto-removals on Deal: **0**.

## 5. Pre-Deal preparation

Tableau only, depth <= 4, MW increase <= 4. Completed (not unique-capped).

| | |
|---|---|
| Unique / candidates | 103,513 |
| Expanded / generated / dups | 41,187 / 300,236 / 197,443 |
| Runtime | 74.4 s |
| DEAL_NOW (depth 0) | 720 |
| PREP_THEN_DEAL | 102,793 |
| Depth 1 / 2 / 3 / 4 | 3,275 / 10,342 / 26,850 / 62,326 |
| SD5 during prep | never |

## 6. Post-stock symmetry

| | |
|---|---|
| Ordered children before symmetry | 103,513 |
| Exact symmetry classes after | 103,513 |
| Reduction | **1.0** (no column-permutation collapse) |

Physical columns after this SD5 row are distinct enough that whole-column permutation did not identify any pair. One ordered/replayable representative was kept per class (here, each class was a singleton).

## 7. Foundation search

Exact UCS. Identity = `pack_post_stock_symmetry_state`. No suit-specific ordering. Any suit valid. Foundation 2 terminal. Ceiling MW<=120.

| Metric | Value |
|---|---|
| Reached | **no** |
| First hit | none |
| Best full MW / suit / timing | none |
| Unique / expanded / generated / dups | 600,000 / 131,015 / 726,906 / 230,419 |
| Runtime / RSS | 181.5 s / 2458 MB |
| Stop | unique limit |
| Min live g | **81** |
| Exhausted below F | n/a (no F) |
| Second Deal | never |
| Suit heuristic | false |

UCS closed the live set below g=81 without a foundation removal. Remaining heap starts at 81. Cheapest Deal-now children are at 76 (75+1). So Foundation 2 is **not** among generated post-SD5 descendants with full MW < 81; it may still exist at 81–120.

## 8. Portfolio / best

Empty. No fixture.

## 9. Strategic interpretation

Deal-now vs prep-then-deal is **undecided** for Foundation 2 because neither timing produced a witness inside the unique envelope.

The prep envelope did its job as receiving-state diversity (103k exact children) and then **swamped** the UCS seed set. Unique 600k includes the 103k seeds; only ~500k additional states were expanded.

G6_8 work was bypassed by the horizon change as intended: SD5 was taken from Diamond-ready, Heart-H9, **and** the expensive multi-edge frontier. No second foundation appeared cheaply after that Deal.

## 10. Exactly one next recommendation

Post-SD5 UCS hit 600,000 unique with min live g=81 and no Foundation 2. The 103,513-seed fan-out consumed the envelope before any suit removed. Continue UCS from the live g>=81 frontier, or reseed only DEAL_NOW plus the cheapest prep children per source, rather than resuming G6_8. Do not raise MW above 120.

## Integrity

Pre-SD5 identity is ordered pack_state. Post-SD5 identity is exact column symmetry. No suit-specific ordering. No static receiving score. Foundation 2 would have been terminal. Production unchanged.
