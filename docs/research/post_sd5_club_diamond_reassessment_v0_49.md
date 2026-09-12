# Spider Solver v0.49 — Post-SD5 Club vs Diamond TAIL3_READY Race

## 1. Verdict

`CLUB_AND_DIAMOND_BOTH_VIABLE` — both suits reach TAIL3_READY with live TAIL4-ready continuation

Club and Diamond both cross the compulsory predecessor for 3-2-A inside an equal envelope, and both stay live toward TAIL4_READY. Diamond is cheaper at TAIL3 (already present at MW85). Club is slower to TAIL3 (READY 87, join 88) but **96/128** TAIL3 states are immediately TAIL4_READY. Neither should be dropped. Spades stay deferred.

- Branch: `agent/post-sd5-club-diamond-tail3-ready-v0-49`
- Base SHA: `45c8aa9feffb7fd559eba7286667834c9f656a66`
- Revised target: **BOTH**

## 2. Roots

720/720 DEAL_NOW post-SD5 roots replay. Stock 0. One Spade foundation. Symmetry-unique 720.

MW: 76:16, 77:128, 78:144, 79:224, 83:96, 84:32, 85:8, 86:24, 87:48.

| Suit | 2-A raw | Symmetry-unique |
|---|---|---|
| Club | **712** | 712 |
| Diamond | **200** | 200 |

Not restricted to the old 128-state harvests.

## 3. Club audit

Every Club 2-A source is `PACKET_BLOCKED_3_READY`.

- 2C-AC exists on 712/712 and is **buried on all 712** (never movable at the root).
- 3C is **already top on 712/712** (two physical 3Cs; 1424 occurrences).
- 3C is not one-move exposable because it is already exposed.

v0.44's qualitative picture is confirmed: Club 2-A is commonly buried; SD5's 3C is already the receiving resource.

One-move scan: 3,752 legal actions. **96 TAIL3_READY** children at cheapest **MW87**. Zero one-move TAIL3 (the join is the next move).

## 4. Diamond audit

| Category | n |
|---|---|
| TAIL3_ALREADY_PRESENT | **72** |
| BOTH_BLOCKED | 128 |

- 2D-AD exists on 200/200. At these roots the 2-A pair is not a free top packet (often sitting inside a longer / buried run).
- 3D is **never already top** on the 200 (0/200). 400 rank-3 occurrences, none one-move exposable.
- 72 sources already contain 3D-2D-AD somewhere (not necessarily exposed).

v0.44's "2D-AD often exposed, 3D missing" is **not** the current-root picture: 2-A is not a free movable packet, 3D is not exposed, and 72 states already have a (possibly buried) TAIL3.

One-move scan: 1,192 actions. READY hits 0. The 552 one-move "TAIL3" counts are from already-present TAIL3 sources remaining TAIL3 after a child move, not new creations from BOTH_BLOCKED.

## 5. Club READY search

First hit **6.04s**, g=**87**, unique 3,969.

| | |
|---|---|
| Unique / expanded / generated | 34,609 / 18,132 / 87,848 |
| Duplicate skips | 53,867 |
| Time / RSS | 193.8s / 62 MB (time limit at L3) |
| Boundary | **96** states, bands 87:24 / 88:72 |

TAIL3 join: **128** states, cheapest **MW88**.

TAIL4-READY preview: **IMMEDIATE 96**, LIVE_BEYOND_5 32. No exact-dead. No completed 4-3-2-A join in the optional one-shot.

## 6. Diamond READY search

First hit **0s** (72 already-TAIL3 at source), g=**85**.

| | |
|---|---|
| Unique / expanded / generated | 20,076 / 12,110 / 53,765 |
| Duplicate skips | 33,437 |
| Time / RSS | 131.2s / 63 MB (time limit at L3) |
| Boundary | **192** states, bands 85:8 / 86:64 / 87:80 / 88:40 |

TAIL3: **192** states, cheapest **MW85** (the already-present class).

TAIL4-READY preview: **WITHIN_5 64**, LIVE_BEYOND_5 128. No exact-dead. No completed TAIL4 join.

## 7. Comparison

| | Club | Diamond |
|---|---|---|
| TAIL3_READY | yes | yes |
| Cheapest READY | 87 | **85** |
| Cheapest TAIL3 | 88 | **85** |
| First-hit effort | 6s / 4k unique | 0s (already) |
| READY diversity | 96, two cost bands | 192, four cost bands |
| TAIL4_READY | **96 immediate** | 64 within 5 |
| Live beyond 5 | 32 | 128 |
| Exact-dead | 0 | 0 |
| Cheapest TAIL4 | none joined | none joined |

Diamond wins local TAIL3 cost (ties Spade's MW85 with 72 already-complete tails). Club wins next-gate access: most retained Club TAIL3 states are already TAIL4_READY. That is exactly the lesson Spades taught — do not pick on cheapest 3-2-A alone.

## 8. Revised target

**BOTH.** Preserve Club and Diamond TAIL3_READY / TAIL3 portfolios. Next experiment should run equal TAIL4_READY searches from those boundaries.

## 9. Reference (telemetry only)

- Spade TAIL3 best MW85, but v0.45–v0.48 never manufactured LAND5_READY after a dedicated 160k search.
- Heart 2-A was not reached in v0.44 (~104k unique / 150s). Deferred, not impossible.

## 10. Files

- `docs/research/post_sd5_club_diamond_reassessment_v0_49.md`
- `docs/research/post_sd5_club_diamond_reassessment_v0_49.json`
- `docs/research/post_sd5_club_2a_sources_v0_49.json`
- `docs/research/post_sd5_diamond_2a_sources_v0_49.json`
- `docs/research/post_sd5_club_tail3_ready_v0_49.json`
- `docs/research/post_sd5_diamond_tail3_ready_v0_49.json`
- `docs/research/post_sd5_club_tail3_v0_49.json`
- `docs/research/post_sd5_diamond_tail3_v0_49.json`

No TAIL4 join files. No Spade/Heart/Foundation-3/rank-5 search. Production unchanged.

## 11. Exactly one next recommendation

Keep both Club and Diamond TAIL3_READY portfolios. Next: equal TAIL4_READY searches from those boundaries. Do not resume the Spade 4S/LAND5 tunnel.
