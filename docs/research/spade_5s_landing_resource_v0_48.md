# Spider Solver v0.48 — Spade 5S Landing-Resource Cut

## 1. Verdict

`SPADE_LAND5_RESOURCE_STATE_EXPLOSION` — unique/RSS/time limit before a LAND5 boundary

All 128 B4=2 sources replay. None already has an exposed 6, empty, or Jack. A complete one-move scan of 1,412 legal actions produced **zero** LAND5_READY children. Exact search then hit **160,000 unique** without a first exposed-6 or empty crossing. 4S was not exposed. TAIL4 was not searched.

- Branch: `agent/spade-5s-landing-resource-v0-48`
- Base SHA: `3b520c38366c93366925f4da9b787c6a3f6f0b36`

## 2. Sources

- Loaded **128** B4=2 states. Replay OK. Symmetry-unique **128**.
- MW: 89:16 / 90:112. Timing: 64 DEAL_NOW / 64 PREP_THEN_DEAL.
- Cover universally `10D, 5S` with top **5S**.
- LAND5 absent: **true**. No empty. No exposed 6. No exposed Jack.
- First support cannot be zero-cost (no empty). Hard exposure LB: **source_g + 3 = MW92**.

## 3. Rank-6 audit

Seven tableau sixes per source (896 total). All face-up. None already top. **None one-move exposable.**

Depth (cards above): 3:119, 4:183, 5:42, 6:134, 7:13, 8:111, 9:27, 10:110, 11:93, plus a long tail to 17.

Principal signatures:

| n | 6 | depth | cards immediately above (prefix) |
|---|---|---|---|
| 128 | 6D | 4 | 5C, 4S, 10D, 5S — **inside the 4S column** |
| 77 | 6H | 8 | 5C, QH, JD, 10D |
| 77 | 6D | 11 | 8S, 7H, 6H, 5C |
| 76 | 6S | 10 | 5H, 4C, 3D, 2C |
| 76 | 6C | 6 | KS, 2C, AH, 9D |
| **69** | **6H** | **3** | **KH, QS, 3C** |
| **50** | **6C** | **3** | **KC, QH, 7H** |

The 6D under `5C, 4S, 10D, 5S` is the unique-4S column itself. It cannot become a 5S landing without first exposing 4S — circular.

Nearest usable sixes are the depth-3 6H and 6C. Their covering packets are **not** a single movable run (`top_packet_k = 1` while `cards_above = 3`), so exposing them needs a multi-card peel, not one move. Packet-need ranks observed: 6 and 8.

## 4. Empty audit

One-move-clearable columns: **0**.

Face-down-zero columns exist (fu lengths 4–25) but the whole exposed content cannot leave in one legal packet.

## 5. Jack telemetry

896 Jacks, none already top. Shallowest: 90 at depth 1, 161 at depth 2. Future Gate-2 capability, not the LAND5 target.

## 6. One-move fast path

- Actions enumerated: **1,412** (every legal tableau action from all 128 sources).
- LAND5 hits: **0**. SIX / EMPTY / BOTH: none. Simultaneous JACK_READY: 0.

## 7. Resource search

Reached: **no**.

| | |
|---|---|
| First hit | none |
| Unique / expanded / generated | **160,000 / 73,499 / 476,636** |
| Duplicate skips | 287,493 |
| Stop | unique limit |
| Time / RSS | 141.7s / 150 MB |

L0–L2 ran. No LAND5_READY child.

## 8. 5S / 10D preview

Not started (no LAND5 boundary).

## 9. Exposure / cost bands

Reached: **no**. MW92 matched: **no**. Best from MW89 / MW90: none.

## 10. Files

- `docs/research/spade_5s_landing_resource_v0_48.md`
- `docs/research/spade_5s_landing_resource_v0_48.json`
- `docs/research/spade_5s_resource_audit_v0_48.json`

No LAND5 portfolio. No exposure portfolio.

No TAIL4 search. No Foundation-2 search. No new Deal. Production unchanged.

## 11. Exactly one next recommendation

Nearest 6s sit at depth 3 (6H under KH-QS-3C; 6C under KC-QH-7H) and are not one-move packets. Next: a directed peel of those depth-3 6-covers from all 128 B4=2 sources. Do not flood UCS and do not search TAIL4.
