# Spider Solver v0.41 — Diamond Missing-Core Bridge (6D–5D)

## 1. Verdict

`DIAMOND_C_NOT_FOUND_IN_ENVELOPE` — C = 6D-5D not reached under MW<=100

The v0.40 multi-edge frontier reconstructs cleanly to **208 exact unique states**. A directed tableau-only search from every category (`B+D`, `A+B`, `A+D`, `A+B+D`) did not form current `6D-5D` within full MW <= 100, 300,000 unique states, or 450 seconds. No CORE4, no lower tail, no Diamond foundation.

This is **not** a proof that C is unreachable under MW<=100: the search stopped on the time limit at L3 with a live heap. Unique 235,788 stayed below the 300,000 cap; RSS 169 MB stayed below 3 GiB.

- Branch: `agent/diamond-missing-core-bridge-v0-41`
- Base SHA: `6f3d7edb27e6dc54307c16b5c6284ceb53025910`

## 2. Persistence audit

| Item | Value |
|---|---|
| v0.40 file | `docs/research/diamond_core_two_edge_v0_40.json` |
| Local / git blob | 1,431,605 bytes, populated, `n=208`, 208 unique digests |
| GitHub Contents API | `encoding=none`, empty `content` (file > 1 MB) |
| v0.40 C portfolio | `n=0` |
| v0.40 construction | appends A/B/C/D witnesses with >=2 current edges; **no pack_state dedup** of the combined list |

**Do not trust 208 as a unique-state count from the v0.40 report alone.** Reconstruction from populated A/B/D portfolios is authoritative.

| Reconstruction | Count |
|---|---|
| Raw A+B+D candidates | 360 |
| Multi-edge after replay / >=2 current edges | 208 |
| Exact unique `pack_state` (cheapest full g) | **208** |
| Replay failures | 0 |

After exact dedup the unique count **coincides** with the reported 208: v0.40's combined list happened to contain no cross-portfolio pack_state duplicates. The GitHub-empty appearance is the Contents API 1 MB limit, not an empty blob.

## 3. Source categories

All four expected categories exist. No unexpected category. Every source: one Spade foundation, SD1–SD4 consumed, `stock_rows=1`, SD5 not consumed, unique current 2D=1, unique current 5D=1. Replay from the original deal succeeded for all 208. Sources are ordered by full MW then digest — **not** by A-ancestry.

| Category | Exact n | Full MW range | Cheapest | Lineage | Replay |
|---|---|---|---|---|---|
| A+B | 32 | 84–86 | 84 | A:32 | ok |
| A+D | 8 | 86–86 | 86 | A:8 | ok |
| B+D | 128 | 82–83 | 82 | D:128 | ok |
| A+B+D | 40 | 85–86 | 85 | A:40 | ok |

Cheapest two-edge class is **B+D at 82**. The search seeded from that class first.

## 4. C dependency (current state)

Unique 5D is always present (count=1). Both current 6D copies are always face-up, always in **columns 8 and 9**. Every source already has a **7D-6D** component (column 8). **Zero** immediate legal C joins.

Principal blockers (208/208):

- `6D_not_exposed_destination` — mixed-suit covers of 6–14 cards sit on every 6D
- `no_immediate_C_join`
- `5D_packet_not_movable` on 176/208 (all categories except A+B, where D is not currently satisfied)

A+B: unique 2D already in `3D-2D`; D is **not** current; 5D is typically a singleton and more mobile, but still has no exposed 6D landing.

A+D: unique 2D in A, unique 5D in D; 5D-4D exists but is not a legal mover onto 6D.

B+D: cheapest class; 2D-AD and 5D-4D exist; 5D-4D cannot move now; 6D buried.

A+B+D: three unique-core edges already current; same 6D burial as the others. 24 of 208 sources already carry `5D-4D-3D-2D-AD` as a same-suit packet — joining that packet onto an exposed 6D would be the lower tail in one C move. The 6D is never exposed.

Sample B+D (MW 82): 5D-4D exposed in column 9 but not movable; column 8 is `7D-6D` under `5C,4S,10D,5S,4H,8C`; column 9 has a second 6D under 11 cards including the 5D-4D packet itself.

What currently prevents C is a **dynamic landing problem**, not historical edge order: 6D is never a legal destination *now*.

## 5. C search

| Metric | Value |
|---|---|
| Reached | **no** |
| First hit | none |
| Best full MW | none |
| Best source category | none |
| Unique | 235,788 |
| Expanded | 342,500 |
| Generated | 1,870,094 |
| Duplicate skips | 1,585,759 |
| Runtime | 450.0 s (time limit) |
| Peak RSS | 169 MB |
| Levels | 0, 1, 2, 3 |
| SD5 expanded | false |
| Heuristic prune | false |
| A-ancestry preference | false |
| Cost ceiling | 100 |
| Unique cap | 300,000 |

C is terminal in the primary search; no C child was ever recorded, so the terminal rule was never exercised on a hit.

## 6. C boundaries / CORE4 / bridge preview

| Band | Count |
|---|---|
| C0 / C0+1 / C0+2 / C0+3 | 0 / 0 / 0 / 0 |
| C+D | 0 |
| C+A+B | 0 |
| CORE4 | 0 |

CORE4 cheapest: n/a. 4D-3D already satisfied among CORE4: n/a.

Bridge preview not run (no CORE4):

| Status | Count |
|---|---|
| LOWER_TAIL_WITHIN_6 | 0 |
| BRIDGE_E_WITHIN_6 | 0 |
| LIVE_BEYOND_6 | 0 |
| EXACT_DEAD_TO_BRIDGE | 0 |

## 7. Foundation

Not reached. No fixture.

## 8. Cross-target Heart telemetry (descriptive only; Hearts were not searched)

Measured on the 208 reconstructed sources:

| Signal | Count |
|---|---|
| AH current copies | 2 (none top) |
| QH-JH currently adjacent | 136 / 208 |
| Original 9H still face-down | 208 / 208 |
| Original column-2 top face-down still JH | typical |
| Heart release physically plausible | 172 / 208 |

## 9. Files

- Report: `docs/research/diamond_missing_core_bridge_v0_41.md`
- Result: `docs/research/diamond_missing_core_bridge_v0_41.json`
- Corrected sources: `docs/research/diamond_multi_edge_sources_v0_41.json`
- C portfolio: `docs/research/diamond_edge_C_v0_41.json` (empty)
- CORE4: `docs/research/diamond_core4_v0_41.json` (empty)
- Lower tail: none
- Foundation fixture: none

## 10. Exactly one next recommendation

Every reconstructed multi-edge source already contains 7D-6D, but 6D is never an exposed destination (mixed covers of 6–14 cards, always columns 8 and 9). Make 6D exposure the next directed cut from this 208-state frontier. Do not raise MW above 100. Do not take SD5. Do not search Hearts.

## Integrity

SD5 never expanded. Edge history is not canonical identity. A-ancestry is not a hard preference. Production solver and MW contract unchanged.
