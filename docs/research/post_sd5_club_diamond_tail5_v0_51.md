# Spider Solver v0.51 — Club vs Diamond TAIL5_READY Race

## 1. Verdict

`DIAMOND_TAIL5_CONTINUATION_LEADS` — only Diamond crossed TAIL5_READY

Club’s 96 visible 4C-3C-2C-AC states are all `FIVE_BLOCKED`: the TAIL4 packet is movable, but both 5Cs sit 7–12 cards deep and never became TAIL5_READY in 180s / 19.5k unique. Diamond collapses to 59 symmetry-unique TAIL4 states, **32 of which are already TAIL5_READY at MW89** (exposed 5D, isolated “5 only”). The join produces visible 5D-4D-3D-2D-AD at MW90. TAIL6_READY is live beyond 5 ply, not exact-dead. No Foundation 2: no K-through-5 receiver.

- Branch: `agent/post-sd5-club-diamond-tail5-ready-v0-51`
- Base SHA: `a8a8719b58cd8f9fa9b1bbe036a6bfc17d2a00b1`
- Revised target: **DIAMOND**

## 2. Sources

| | Club | Diamond |
|---|---|---|
| Raw TAIL4_PERSISTS | 96 | 125 |
| Symmetry-unique | **96** | **59** |
| MW | 90:32 / 91:64 | 89:24 / 90:8 / 93:24 / 94:3 |
| TAIL4 exposed/movable | 96/96 | 59/59 |
| Replay | all OK | all OK |

## 3. Rank-5 audit

**Club** — 192 fives (two copies × 96). Top: **0**. One-move exposable: **0**. Depths 7–12. K_THROUGH_5: 0. Category: FIVE_BLOCKED × 96.

**Diamond** — 118 fives on 59 states. Top: **32 sources**. One-move exposable: 24. Depths: 0:32, 1:51, 2:16, plus 5/7. Exposed upper-run: **5 only × 32**. K_THROUGH_5: 0. Categories: TAIL5_READY_AT_SOURCE 32 / FIVE_BLOCKED 27.

## 4. One-move scan

| | Club | Diamond |
|---|---|---|
| Actions | 1008 | 394 |
| READY hits | 0 | 0 (already-READY skipped) |
| F2 surprise | 0 | 0 |

## 5. Club TAIL5_READY

Reached: **no**.

| Unique / exp / gen | 19,506 / 12,343 / 112,731 |
| Dups | 93,217 |
| Time / RSS | 185.8s / 40 MB (time limit) |
| First hit | none |

5C remains buried. No TAIL5 join, no Foundation 2.

## 6. Diamond TAIL5_READY

Reached: **yes**, first hit **0s** (32 already-READY), g=**89**.

| Unique / exp / gen | 29,344 / 9,644 / 96,735 |
| Dups | 66,729 |
| Time / RSS | 204.2s / 49 MB (time limit) |
| Boundary | **192** states, 89:18 / 90:76 / 91:65 / 92:33 |

## 7. TAIL5 transitions

Diamond: **199** legal 4-3-2-A → 5 joins.

| Class | n |
|---|---|
| TAIL5_PERSISTS | **199** |
| FOUNDATION_AUTO_REMOVED | 0 |
| CONTRACT_FAILURE (join) | 0 |

Receiving-run: **5 only × 199**. Cheapest visible TAIL5: **MW90**. Cheapest Foundation 2: none.

## 8. TAIL6 preview

Diamond 199 TAIL5 states: **LIVE_BEYOND_5 × 199**. READY_AT_SOURCE 0, WITHIN_5 0, EXACT_DEAD 0. Optional 5→6 join not reached. Continuation is live, not a dead-end.

## 9. Revised target

**DIAMOND.** Evidence beyond local cost:

- Club’s next 5C is a deep buried-resource problem (depth ≥ 7, zero one-move exposure), the same shape as Spade’s failed LAND5_READY.
- Diamond already has the 5D receiver on 32 cheapest (MW89) states; the 4-3-2-A → 5 join is immediate and persists 5-4-3-2-A.
- TAIL6_READY is live beyond 5, so the chain is not obviously stuck the way Spade 4S was.

No Foundation 2 yet: every 5D is isolated.

## 10. Reference

Spade TAIL3 MW85 then LAND5_READY failed after dedicated 160k searches. Heart 2-A not reached in v0.44. Both deferred.

## 11. Files

- `docs/research/post_sd5_club_diamond_tail5_v0_51.md`
- `docs/research/post_sd5_club_diamond_tail5_v0_51.json`
- `docs/research/club_tail4_sources_v0_51.json`
- `docs/research/diamond_tail4_sources_v0_51.json`
- `docs/research/diamond_tail5_ready_v0_51.json`
- `docs/research/diamond_tail5_v0_51.json`

No Club READY/TAIL5 files (none reached). No TAIL6 READY. No Foundation-2 fixture.

## 12. Exactly one next recommendation

Adopt Diamond as the revised post-SD5 target from its TAIL5 / TAIL5_READY portfolio. Continue toward TAIL6_READY with the corrected join classifier. Do not resume Spades.
