# Spider Solver v0.42 — Diamond 6D Exposure Gateway

## 1. Verdict

`6D_EXPOSURE_NOT_FOUND_IN_ENVELOPE` — neither physical 6D became exposed/top under MW<=100

The 208-state v0.41 frontier reconstructs exactly. Two equal tableau-only searches, one per physical 6D, did not produce a G6_ANY witness (a current 6D as column top) within full MW <= 100, 175,000 unique, or 225 seconds each.

This is not a unique-limit explosion: SEARCH 8 stopped at 37,207 unique / 224 s; SEARCH 9 at 50,995 unique / 224 s. RSS stayed under 62 MB. L3 heaps were still live.

The blocker audit is the result. G6_8 can start peeling; G6_9 cannot, because its covering packet is the unique 5D-4D and legally needs a rank-6 landing.

- Branch: `agent/diamond-6d-exposure-gateway-v0-42`
- Base SHA: `31e5f979712e41f85c7a2045b029b6b230922e3c`

## 2. Sources

208/208 replayed from `deals/4925153.txt`. Defensive pack_state dedup left 208. One Spade foundation, SD1–SD4 consumed, stock_rows=1, SD5 unused, unique current 2D=1, unique current 5D=1, both 6D copies face-up in tableau.

| Category | n | Full MW |
|---|---|---|
| B+D | 128 | 82–83 (96 @ 82, 32 @ 83) |
| A+B | 32 | 84–86 |
| A+B+D | 40 | 85–86 |
| A+D | 8 | 86 |

Cost counts: 82:96, 83:32, 84:8, 85:24, 86:48.

## 3. Blocker audit

Both 6Ds are face-up and never top at every source. Zero empties in the sample B+D state.

### G6_8 (initial column 8, 7D-6D)

| | |
|---|---|
| Cover depth | 6:56, 7:40, 8:64, 9:40, 10:8 |
| Mean depth by category | B+D 7.12, A+B 8.0, A+B+D 8.2, A+D 9.0 |
| Movable covering packet | **208/208** |
| 7D-6D component | **208/208** |
| Sample cover | `5C, 4S, 10D, 5S, 4H, 8C` |
| Sample top packet | `8C` → legal dest column 1 |

### G6_9 (initial column 9)

| | |
|---|---|
| Cover depth | 8:16, 9:100, 10:16, 11:40, 12:16, 13:4, 14:16 |
| Mean depth by category | B+D 9.5, A+B 9.0, A+B+D 12.4, A+D 12.0 |
| Movable covering packet | **0/208** |
| 7D-6D | 0 |
| Sample cover | `8S, 7H, 6H, 5C, QH, JD, 10D, 9D, 8D, 5D, 4D` |
| Sample top packet | `5D-4D`, need_rank **6**, dests none |
| Would break | D, if that packet were moved |

G6_9's first peel requires an exposed 6 as landing. The only current 6D copies are G6_8 and G6_9, both buried. G6_9 therefore cannot begin until G6_8 (or a later 6) is already a destination.

## 4. SEARCH 8

| Metric | Value |
|---|---|
| Exposure reached | **no** |
| First hit | none |
| Best full MW | none |
| Unique / expanded / generated / dups | 37,207 / 35,471 / 217,283 / 167,034 |
| Runtime / RSS | 224.2 s (time limit) / 55 MB |
| Levels | 0–3 |
| Portfolio | empty |
| SD5 | never |

## 5. SEARCH 9

| Metric | Value |
|---|---|
| Exposure reached | **no** |
| First hit | none |
| Best full MW | none |
| Unique / expanded / generated / dups | 50,995 / 48,589 / 242,567 / 182,712 |
| Runtime / RSS | 224.2 s (time limit) / 62 MB |
| Levels | 0–3 |
| Portfolio | empty |
| SD5 | never |

Identical mechanics and resource caps. Column 8 was not proof-preferred.

## 6. C preview / lower tail / edges

No exposure boundary, so no C preview and no lower-tail immediate. The 24 v0.41 `5D-4D-3D-2D-AD` packets were not re-tested at an exposure state because none was reached.

## 7. Gateway comparison

Leader: **NONE**. Evidence beyond local cost: G6_8 is the only physical 6D whose covering packet is currently legal to move (208/208). G6_9's covering packet needs rank 6. That is a structural ordering fact, not a search-cost ranking, and it was not used to prune SEARCH 9.

## 8. Foundation / cross-target

Foundation 2 not reached. Hearts not searched. On the 208 sources: AH current=2 never top; QH-JH adjacent; original 9H still face-down; original col-2 top face-down still JH; Heart release still physically plausible.

## 9. Files

- `docs/research/diamond_6d_exposure_gateway_v0_42.md`
- `docs/research/diamond_6d_exposure_gateway_v0_42.json`
- `docs/research/diamond_g6_8_v0_42.json` (empty portfolio)
- `docs/research/diamond_g6_9_v0_42.json` (empty portfolio)
- `docs/research/diamond_g6_combined_v0_42.json` (empty)
- No C-from-G6 file, no lower-tail file, no foundation fixture

## 10. Exactly one next recommendation

G6_9's covering packet is the unique 5D-4D and legally needs a rank-6 landing, so it cannot start until some 6D is already exposed. G6_8 has 7D-6D under a mixed 6–10 card cover whose top packet is movable on all 208 sources. Spend the next envelope on finishing G6_8 exposure (workspace/empty creation plus column-8 peeling) from this 208-state frontier. Do not split the budget with G6_9. Do not raise MW above 100. Do not take SD5.

## Integrity

SD5 never expanded. Physical 6D identity is search bookkeeping, not canonical state. Column 8 is not proof-preferred. Production solver and MW contract unchanged.
