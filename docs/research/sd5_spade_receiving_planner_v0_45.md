# Spider Solver v0.45 — SD5 Spade Receiving Planner

## 1. Verdict

`SPADE_TRANSACTION_STATE_EXPLOSION` — TAIL4 not found before unique/RSS limit

The receiving law is exact: every pre-Deal column-8 `3S-2S` became `3S-2S-AS` after SD5 (3520/3520, pred_fail=0). Cheap v0.39/v0.37 lineages never grew that receiver. Prep from `diamond_multi_edge` made **more** TAIL3 states (3456) but the cheapest prepared TAIL3 is **86**, one more than the v0.44 DEAL_NOW control **85**. No Deal created TAIL4. Targeted 6-ply TAIL4 search from 512 states hit 250,000 unique in 144s with no 4S-3S-2S-AS.

- Branch: `agent/sd5-spade-receiving-planner-v0-45`
- Base SHA: `08c2433fcb04092d1a99fdaeac360216c35b52fb`

## 2. Sources

720/720 replayed. Unique remaining Spade ranks 2–K in tableau; remaining AS is SD5 column 8. Engine row matches.

| Lineage | n | MW |
|---|---|---|
| diamond_ready | 256 | 75–77 |
| heart_h9 | 256 | 77–78 |
| diamond_multi_edge | 208 | 82–86 |

## 3. Preparation (v0.43 bounds)

103,513 candidates in 73.6s (complete). Depth 0/1/2/3/4 = 720 / 3,275 / 10,342 / 26,850 / 62,326. DEAL_NOW 720, PREP_THEN_DEAL 102,793. Not enlarged.

## 4. Receiver analysis

Pre-Deal column-8 receiver length: **0: 99,993** and **2: 3,520**. Never length 1 (bare 2S) or ≥3.

Post-Deal Spade low-tail: **1: 99,993** (AS on a non-2S c8) and **3: 3,520** (`3S-2S-AS`). Never 4+.

R=2 → tail 3 held for all 3520. Deal cost +1.

| Tail ≥ | n | Cheapest MW | Timing |
|---|---|---|---|
| 2 / 3 | 3520 | **85** | DEAL_NOW |
| 4 / 5 | 0 | — | — |

All 3520 TAIL3 states are **diamond_multi_edge**. DEAL_NOW 64, PREP_THEN_DEAL 3456.

## 5. v0.44 control

Reproduced independently: **64** DEAL_NOW TAIL3, best **85**. Pre-Deal c8 top suffix `3S-2S` (sample `4S, 10D, 5S, 4H, 3S, 2S`). Post-Deal tail 3. 4S is in the same column **under mixed cards**, which is why the Deal cannot mint TAIL4.

## 6. Prep improvement

Cheapest prepared TAIL3: **86** (depth 1, one move `[0,6,1]`, same diamond_multi_edge lineage). Does **not** beat 85. Longest immediate tail remains 3. Cheaper v0.39/v0.37 sources were not prepared into a 2S receiver.

## 7. TAIL4

Reached **no**. Unique 250,000 / expanded 99,372 / generated 618,954 / 144s / RSS 2287 MB / unique limit. Already-at-source 0. 6-ply consolidation from the 512-state targeted portfolio (288 tail-3 + 224 tail-1) did not join 4S onto 3S-2S-AS.

## 8. TAIL5 preview

Not run (no TAIL4).

## 9. SD5 transaction

Successful TAIL3 pattern: `AS_RECEIVED_ON_3S_2S`. DEAL_NOW cheapest. Prep can relocate 3S-2S onto c8 at +1 MW from the same expensive lineage, not from cheaper ones.

## 10. Foundation

Not reached.

## 11. Exactly one next recommendation

DEAL_NOW `3S-2S-AS` at 85 remains the cheapest TAIL3. Prep from the same diamond_multi_edge lineage makes more TAIL3 states at 86, not cheaper, and never a TAIL4 from the Deal. Continue TAIL4 from the `3S-2S-AS` set only (4S sits under mixed cards in column 8). Do not flood UCS with 103k children.

## Integrity

Prep depth/cost ≤4. Did not seed 103k into UCS. Post-stock symmetry only after SD5. Production unchanged.
