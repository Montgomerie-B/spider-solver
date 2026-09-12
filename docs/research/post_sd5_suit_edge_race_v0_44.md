# Spider Solver v0.44 — Post-SD5 Suit 2-A Edge Race

## 1. Verdict

`SPADE_POST_SD5_ENTRY_LEADS` — Spade 2-A is the operational post-SD5 entry

Club has the cheapest 2-A (full MW 76, already present on 712/720 DEAL_NOW roots) but that pair is **buried** and none of 128 harvested Club boundaries formed 3-2-A in 5 ply. Diamond 2-A is cheaper than Spade (80 vs 85) and often exposed, but also **LIVE_BEYOND_5** for 3-2-A. Spade 2-A is more expensive (85) and rarer (64/720, all `diamond_multi_edge`), yet **every** retained Spade boundary already has an **exposed `3S-2S-AS`**. That is continuation, not cheapest-edge, evidence.

Heart 2-A was not reached in 150s / 104k unique.

- Branch: `agent/post-sd5-suit-edge-race-v0-44`
- Base SHA: `ae78cb0f10ed83aa02091e6987415dd213e5e41d`

## 2. DEAL_NOW roots

720/720 pre-SD5 sources replayed. SD5 applied once. Deal cost +1. Auto-removals: 0. Post-stock symmetry: **720 classes** (reduction 1.0).

| Lineage | n |
|---|---|
| diamond_ready | 256 |
| heart_h9 | 256 |
| diamond_multi_edge | 208 |

Root MW: 76:16, 77:128, 78:144, 79:224, 83:96, 84:32, 85:8, 86:24, 87:48 (source+1). Cheapest 76 as expected.

SD5 row matches engine: `3H, 10H, 2D, 3C, 9H, 7C, 7H, AS, 3C, 5D`.

## 3. Material

`SPADE2_FULL_PHYSICAL_CHAIN_UNIQUE` = **true**. Remaining tableau Spades: exactly one copy of every rank. Foundation already holds the other set.

Hearts / Diamonds / Clubs: two tableau copies of A and of 2; no foundation.

This uniqueness is telemetry. It did **not** auto-prioritise Spades in the search budgets.

## 4. Source 2-A audit (before search)

| Suit | Already 2-A | Immediate join | Notes |
|---|---|---|---|
| Club | **712/720** | 0 | 2C-AC present but buried (sample col 3, not exposed) |
| Diamond | 200/720 | 0 | all 200 from `diamond_multi_edge` |
| Spade | 64/720 | 0 | all 64 from `diamond_multi_edge`; remaining AS is SD5 c8 top on many roots |
| Heart | 0/720 | 0 | 4H-3H-2H exists without Ace |

## 5. Four equal searches (150s / 150k / MW<=100 each)

### Spade

Reached **yes**. Already 64. Best **85**. First hit t=0 (already). Unique 133,054 / 150s. Bands 85:8, 86:24, 87:32 (n=64). Preview: **TAIL3_IMMEDIATE 64/64**. Longest tableau low-tail **3** (`3S-2S-AS` exposed on column 8). Lineage: diamond_multi_edge.

### Heart

Reached **no**. Unique 104,103 / 150s. No 2H-AH.

### Diamond

Reached **yes**. Already 200. Best **80**. Unique 96,275 / 150s. Bands 80:16, 81:64, 82:24, 83:24 (n=128). Preview: **LIVE_BEYOND_5 128/128**. Longest low-tail **2** (exposed `2D-AD` on sample col 3; 3D sits in a separate `4D-3D`). Lineage: diamond_multi_edge.

### Club

Reached **yes**. Already 712. Best **76**. Unique 101,570 / 150s. Bands 76:16, 77:48, 78:32, 79:32 (n=128). Preview: **LIVE_BEYOND_5 128/128**. Longest low-tail **2** (buried `2C-AC`). Lineage: diamond_ready.

No Foundation-2 surprise. No second Deal. No prep states. Equal envelopes (Club's unused harvest time was not donated).

## 6. Comparison

| | 2-A | Cheapest MW | TAIL3 | Low-tail |
|---|---|---|---|---|
| Club | yes | **76** | 0% in 5 ply | 2, buried |
| Diamond | yes | 80 | 0% in 5 ply | 2, often exposed |
| Spade | yes | 85 | **100% immediate 3-2-A** | **3, exposed** |
| Heart | no | — | — | — |

Leader is Spade because the next mandatory edge is already in hand. Club/Diamond win on local 2-A cost and lose on 3-2-A.

## 7. Foundation

Not reached. No fixture.

## 8. Files

- `docs/research/post_sd5_suit_edge_race_v0_44.md`
- `docs/research/post_sd5_suit_edge_race_v0_44.json`
- `docs/research/post_sd5_deal_now_roots_v0_44.json`
- `docs/research/post_sd5_edge_{spade,heart,diamond,club}_v0_44.json`

## 9. Exactly one next recommendation

Use Spades as the post-SD5 entry target. Next, test which pre-SD5 DEAL_NOW vs small prep most improves THAT suit's 2-A / 3-2-A gateway. Do not flood UCS with undirected prep children.

## Integrity

DEAL_NOW only. Post-stock symmetry identity. Equal budgets. Target progress not canonical. Production unchanged.
