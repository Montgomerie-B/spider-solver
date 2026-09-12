# Spider Solver v0.46 — Spade 4S Access Ratchet

## 1. Verdict

`SPADE_BLOCKER_RATCHET_PROGRESS` — B4 decreased and boundaries persisted, 4S not yet exposed

The 3,520 immediate `3S-2S-AS` states reconstructed exactly (64 DEAL_NOW / 3,456 PREP). Two physical stacks sit on the unique 4S. Direct B4-reducing moves lowered the count from 8/6 down to **B4=2** at full MW 89. The remaining cover is always `10D, 5S`. TAIL3 was usually split to get there. 4S was not exposed. TAIL4 preview was not started.

- Branch: `agent/spade-4s-access-ratchet-v0-46`
- Base SHA: `c1776413e2082bebab01925b6626dcb8cfaeb6fe`

## 2. Source audit

| | |
|---|---|
| Raw TAIL3 | **3520** (matches v0.45) |
| Symmetry-unique | **3520** (no collapse) |
| DEAL_NOW / PREP | 64 / 3456 |
| Uniqueness fail | 0 |
| MW | 85:8, 86:70, 87:274, 88:642, 89:1010, 90:910, 91:606 |

Initial B4: **6: 1760** and **8: 1760**.

Signatures (universal, not just the v0.45 sample):

| B4 | Cards above unique 4S | n |
|---|---|---|
| 6 | `10D, 5S, 4H, 3S, 2S, AS` | 1760 |
| 8 | `10D, 9D, 8D, 5S, 4H, 3S, 2S, AS` | 1760 |

TAIL3 sits **above** 4S in both families. 4S is not in a fixed column after permutation; it is located dynamically.

## 3. Ratchet

All harvested hits were `B4_REDUCE`. Multi-card TAIL3 moves skipped counts (6→3, 8→5, etc.). Skipped levels were not fabricated.

### Stage 0 (from B4=6/8)

First hit 0.86s: **6→4** at g=86. Unique 70,985 / 120s. Boundaries 128 each at B4=3,4,5,6,7. TAIL3 preserved 192 / split 448.

### Stage 1

First **5→4** at g=87 (0.18s). Unique 36,589 / 120s. Achieved down to **B4=2**. TAIL3 preserved 184 / split 456.

### Stage 2 (partial, 51s remaining)

First **3→2** at g=89 (0.54s). Unique 12,377. Still B4=2..5. Global time ended.

No B4=0. Lowest remaining cover: **128 states at B4=2, cheapest 89**, signature always `10D, 5S`. TAIL3 gone on that portfolio (0/128 intact). Mix 64 DEAL_NOW / 64 PREP.

## 4. Exposure / TAIL4 / Foundation

4S not exposed. TAIL4 preview not run. Foundation 2 not reached.

## 5. Bottleneck

Controlling structure is the unique 4S buried under:

1. the `3S-2S-AS` packet (moved off in the ratchet — that is the skip from 6→3 / 8→5);
2. then `4H`;
3. then **`10D` and `5S`**, which still sit on 4S at B4=2.

The live bottleneck is therefore **landing/moving 10D then 5S** (or 5S-headed packet), not TAIL3 itself.

## 6. Files

- `docs/research/spade_4s_access_ratchet_v0_46.md`
- `docs/research/spade_4s_access_ratchet_v0_46.json`
- `docs/research/spade_tail3_sources_v0_46.json`
- `docs/research/spade_4s_blockers_{2,3,4,5,6,7}_v0_46.json`

No exposure, TAIL4, or foundation fixture.

## 7. Exactly one next recommendation

Keep the lower-B4 boundary portfolio and continue the 4S access ratchet. Do not search TAIL4 directly.

(The B4=2 file is the operational frontier: 128 exact states at MW≥89, cover `10D, 5S`.)

## Integrity

TAIL3 sources only. B4 is not canonical identity. L3 admits all tableau moves. No new Deal. No Foundation 3. Production unchanged.
