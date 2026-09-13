# healthy_f2_cost_to_go_v0_65

Verdict: `HEALTHY_F2_STRUCTURE_LIMITED`

Focused search from the exact autonomous F2 (g=130, rows=1, fd=2,
Spades+Diamonds) used the full 900 s envelope and **52,450 expansions**
(31k of them post-stock). It lowered the F2→F3 jump from 63 MW to **49
MW** (F3 at 179) and reached F6 at g=197. It did **not** produce a
terminal below 198.

Cheap post-stock states exist at g=131 (F=2). COST never found an F3
near that g. The remaining topology is expensive, not merely
under-searched.

Base: `1a3fc6b30b3efdd66ff35f556df2485d39d008dd`
Branch: `agent/healthy-f2-cost-to-go-v0-65`

---

## Verified autonomous F2

Reconstructed from the stored v0.64 F1 prefix plus the same continuation
policy, aborting at the recorded milestone (480.85 s, vs original
480.79 s). Independently replayed from the untouched opening.

| | |
|---|---|
| g | **130** |
| rows | **1** |
| fd | **2** |
| F | **2** (s, d) |
| deals | 4 |
| actions | 134 |
| empty | 1 |
| legal tableau | 15 |
| visible components | 35 |
| bonds | 31 |
| interference boundaries / layers | **26 / 26** |
| mixed-supports | 8 |
| n_ready | 1 (hearts) |
| solved | no |

Hearts (only ready suit): blockers 48, k_len 2, a_len 6, gap 5,
anchor_contention 1, no legal merge. Clubs not material-ready; K-side
length 10 but contention 1.

---

## Focused envelope

900 s · 800k unique · 2.5 GiB · ceiling 197 · remaining budget **67**
(including SD5). Width 256. Frozen v0.63 lanes. No new heuristic.

Stopped on time. Unique 168,787. Expanded **52,450** (58.3/s). Stale
37,221. Duplicate 238,933. RSS 218 MB.

Lanes (expansions): construction 15,252 · readiness 12,403 · economy
9,820 · reveal 8,280 · cost 6,695 · horizon 0.

---

## SD5 portfolio

rows=1: 1 F2 root → 75,332 unique / 21,134 expanded in 360 s. Harvested
**187** post-SD5 descendants (all lineage-tagged). Deal-now kept.
max F still 2 before SD5. min g 130, max 170.

Immediate Deal on the exact F2 board (evaluation): 0 rank-ok, 0
same-suit, 9 mixed blocks, legal 15→**5**.

---

## Post-stock totals

187 roots · 93,455 unique · **31,316 expanded** · 540 s. min g=131
(prefix+Deal). max F=**6**. min fd=0. Ceiling 197.

---

## F3–F8 frontier (true F2 descendants)

| F | min g | ΔF2 | fd | empty | boundaries | t after start |
|---|---|---|---|---|---|---|
| 2 | 130 | 0 | 2 | 1 | 26 | 0 |
| 3 | **179** | **49** | 2 | 2 | 9 | 371 s |
| 4 | 186 | 56 | 2 | 2 | 7 | 373 s |
| 5 | 194 | 64 | 1 | 3 | 3 | 376 s |
| 6 | 197 | 67 | 0 | 5 | 2 | 377 s |
| 7–8 | none ≤197 | | | | | |

v0.64’s descendant F3 was 193 (Δ63). Focused search saved **14 MW** on
F3 and reached two extra foundations, then hit the ceiling.

---

## F2→F3 diagnosis

The 63-MW cliff is real and only partly search-coverage. With more than
the entire v0.64 post-stock budget spent here, cheapest F3 is still
**+49 MW**. COST would have preferred any F3 near g=140–160; none
appeared.

After F3 the cascade is cheap (F3→F6 = 18 MW) but too late: 197 leaves
no slack for F7/F8.

Structural obstacles visible on the F2 snapshot (before SD5):

* 35 visible components / 26 unresolved boundaries (high fragmentation)
* Hearts ready but cover unavailable, 48 blockers, gap 5, no merge
* Clubs K-side 10 with duplicate-K contention
* 1 empty, legal 15

SD5 on this board is hostile (0 compatible landings, legal 15→5), which
can force reconstruction after the Deal.

---

## Coverage vs structure vs heuristic

**STRUCTURE_LIMITED**, with a coverage footnote.

Evidence for structure: cheapest F3 at 179 after 31k post-stock
expansions and a live COST lane; min_g=131 never acquired a third
foundation.

Evidence against pure coverage: F3–F6 appear in a 6-second burst at
t≈371–377 s, then 160 s more of search only pushes F6 to the ceiling.

Heuristic-limited is possible for *Deal shaping before SD5* (rows=1
spent 360 s and never raised F), but that is still a property of this
F2: the pre-Deal F3 was not found either (max F=2 until after SD5).

---

## Best complete g

None under 197. No `solutions/4925153_autonomous_v0_65.moves`.

---

## After-run autonomous vs canonical F2

Both: F=2, suits s+d, rows=1. Auto g=130 fd=2 empty=1. Canon g=139 fd=3
empty=2.

| | auto 130 | canon 139 |
|---|---|---|
| legal | **15** | **31** |
| boundaries | **26** | **13** |
| visible components | **35** | **21** |
| bonds | 31 | 44 |
| hearts blockers / gap / a_len | 48 / 5 / 6 | 36 / 2 / 8 |
| clubs K/A/gap | 10 / 2 / 1 | 10 / 2 / 1 |
| SD5 rank_ok / ss / mixed / legal_after | 0 / 0 / 9 / 5 | 1 / 1 / 7 / 7 |

Canonical is *less* excavated (fd=3 vs 2) but twice as mobile and half
as fragmented. Clubs look similar. Hearts is more assembled on the
canonical board. Deal lands better on canonical (still not great).

---

## Ranked generic differences

1. **Mobility 15 vs 31** — large; remaining-cost impact high; policy
   measures legal count only weakly (empty/reveal). PLAUSIBLY_GENERAL.
2. **Fragmentation 35 vs 21 components, 26 vs 13 boundaries** — v0.62
   debt already measures this but is not in the active v0.63 ranking.
   PLAUSIBLY_GENERAL.
3. **Heart gap/blockers** — auto worse; operational viability measures
   it and still ranks hearts as the only ready suit. PLAUSIBLY_GENERAL.
4. **SD5 reception 0 vs 1 compatible landings** — not in active policy.
   PLAUSIBLY_GENERAL; Deal-row identity is deal-specific.
5. **Empty 1 vs 2** — small; already in reveal/workspace harvest.
6. **fd 2 vs 3** — auto better; excavation is not the gap.

---

## Interpretation

Giving the F2 the whole envelope does **not** unlock a sub-198 finish.
The F2 is cheaper and cleaner than the 198 incumbent’s midgame, but it
is a **fragmented, low-mobility** s+d board. Canonical’s F2 at +9 MW
has half the boundaries and double the legal moves. The next lever is
a generic post-stock / pre-Deal assembly signal (fragmentation,
mobility, reception), not more time on COST.

---

## Next recommendation

One generic **post-stock assembly / cost-to-go** signal using
fragmentation (visible components / unresolved boundaries) and mobility,
optionally Deal-landing quality at the last stock row. Do not copy 172
moves. Do not widen runtime.

---

## Files

New: `src/spider/healthy_f2.py`, research script, tests, docs
JSON/MD/progress. Policy modules otherwise unchanged.
