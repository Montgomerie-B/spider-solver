# operational_foundation_viability_v0_63

Verdict: `OPERATIONAL_VIABILITY_IMPROVES_LINEAGE`

One 900 s operational-readiness experiment on the frozen v0.59/v0.60
architecture did **not** produce a complete route below 198. The
autonomous incumbent remains 198. No
`solutions/4925153_autonomous_v0_63.moves` file was written.

Foundation milestones did occur on **better excavated boards** than
v0.60/v0.62 cheap-F states. The generic metric, evaluated after search
on the 172 route, distinguishes accessible Spade/Diamond cash-out from
awkward Hearts without suit-specific policy.

Base: `20c0388a211ee728e152fff44f1bd90479b8ebd0`
Branch: `agent/operational-foundation-viability-v0-63`

---

## Contract

- Search does not read `solutions/4925153_canonical.moves`
- Viability is a pure function of the current tableau
- Two histories to the same packed state yield identical facts
- SPK1/SPS1 and cheapest-g TT unchanged
- Ceiling 197; g is still corrected MW
- No DURABILITY lane; v0.62 telemetry/tests preserved
- No suit names and no `fd <= N` threshold in policy

---

## Operational viability

For each materially-ready next foundation, current-state facts:

**Excavation:** global fd, suit fd, required fd (min-cover), relevant
visible blockers above buried suit material, max blocker depth,
exposed vs buried components.

**Assembly:** cover, visible cover, component count, cond_len, merge
edges, longest, K/A lengths and gap, inaccessible joins, receiver
contention.

**Anchors:** every remaining K and A of the suit (tableau or stock):
visible/fd, column, blockers, in-component, exposed/movable.
`anchor_contention` is 1 when two same-rank anchors share a column
(generic duplicate-K/A entanglement). Access blockers for a K/A that
heads/tails an exposed same-suit component are 0.

**Mobility proxies:** empty columns, global visible components,
boundaries, legal same-suit merge hits. Full `tableau_actions` is used
in evaluation snapshots, not in the hot lane key.

**Dividend (secondary):** imminent K–A occupying a whole face-up;
would removal flip or empty. Does not outweigh accessibility.

Lexicographic key (lower better), documented:

1. `global_fd`
2. `cover` (INF if unavailable)
3. `relevant_blockers`
4. `max_blocker_depth`
5. `anchor_contention`
6. `k_min_blockers`, `a_min_blockers`
7. `−k_len`, `−a_len`
8. `−legal_merge_edges`
9. `−empty_n`, `−exposed_components`
10. `g`

Material-incomplete suits do not enter OPERATIONAL_READINESS.
HORIZON is unchanged until some suit is complete.

---

## Active lanes

`cost, reveal, construction, readiness, horizon, economy`

READINESS is sparse and uses the operational key over **all** ready
suits (best opportunity). HORIZON only when none are ready. No
DURABILITY.

Harvest keeps cheap, cheap_fd (excavation cohort), construction,
workspace, economy, horizon, readiness, ready_div, cheap_ready,
cheap_cover, cheap_viable, operational_alt, Pareto, DEAL_NOW,
incumbent. Width 256.

---

## Envelope / totals

900 s · 800k unique · 2.5 GiB · ceiling 197 · width 256.

Stopped on **time limit**. Unique 210,120.

| | v0.63 | v0.62 | v0.60 |
|---|---|---|---|
| unique | **210,120** | 153,717 | 213,274 |
| expanded | 34,405 | 21,501 | 41,164 |
| exp/s | **38.2** | 23.9 | 45.7 |
| max F | 4 | 4 | 7 |
| min fd | **0** | 2 | 0 |
| solved | none &lt; 198 | none | none |
| RSS MB | 115 | 93 | — |

Throughput recovered toward the v0.60 regime. Incumbent checkpoints
5/5.

---

## Lane expansions

| lane | expansions | pops | stale |
|---|---|---|---|
| construction | 8,752 | 9,126 | — |
| reveal | 7,606 | 9,127 | — |
| economy | 5,710 | 9,121 | — |
| **readiness** | **4,387** | 4,892 | — |
| cost | 3,995 | 9,127 | — |
| horizon | 3,955 | 4,231 | — |

REVEAL was not starved. READINESS is live once suits are ready
(rows≤3).

---

## Portfolio

rows=5/4: cheap_fd + horizon + workspace + DEAL_NOW (no readiness).
rows=3: operational_alt 40, readiness 37, cheap_fd 10, cheap_viable 9,
incumbent 1, deal_now 6. Excavation slots remain alongside operational
foundation states.

---

## F milestones vs baselines

| F | v0.63 g / fd / rows | v0.62 | v0.60 | canonical |
|---|---|---|---|---|
| 1 | **71 / 10 / 3** (s) | 60 / **23** / 2 | 41 / **17** / 3 | 90 / 8 / 3 (s) |
| 2 | 183 / **2** / 0 | 94 / **19** / 0 | 190 / — | 139 / 3 / 1 (d) |
| 3 | 194 / **0** / 0 | 120 / 17 / 0 | — | 158 / 0 |
| 4 | 197 / **0** / 0 | 148 / 11 / 0 | — | 168 / 0 |

Cheap F1 is no longer a fd=17–23 board. It is still 2 fd worse than
canonical F1 and 30 MW more expensive than v0.60’s false-friend F1.
F2–F4 reach fd=0 but only at g=183–197, so they cannot beat 198.
max F remains 4.

Best operational ready state at rows=3: g=71, fd=10, cover=2, suit s,
k_min_blockers=0.

Post-stock min_g=6, max_g=197, min fd=0, max F=4. No terminal.

---

## After-run canonical evaluation (policy frozen)

Measured **immediately before** each foundation, not after (after F1
the founded suit is gone, so “best=hearts” would be a false invalid).

**Q1. Spades/Diamonds vs Hearts without suit policy?** Yes.

Canonical pre-F1 (g=89, fd=8, rows=3), ready `{s,h}`:

| | cover | blockers | k_min | a_len | merges |
|---|---|---|---|---|---|
| **spades (founded)** | **2** | **7** | **0** | 12 | 1 |
| hearts | 6 | **79** | 8 | 8 | 0 |

Best = spades. Hearts is the awkward ready suit: 10× blocker burden,
K buried, cover 6.

Pre-F2 (g=138, fd=3): diamonds cover 2, merge 1; hearts cover
unavailable, **anchor_contention=2**. Best = diamonds.

**Q2. v0.60 g=41 F1?** After that F1 only hearts remain ready, cover
10, global_fd=17, blockers=29, gap=11. Operationally sick. Explains
why cheap F1 did not convert.

**Q3. v0.62 F2 g=94 fd=19?** Not unpacked here; v0.63’s own F2 at
fd=2 is the operational contrast: same F-count on a nearly cleared
board, too late in g.

**Q4. Canonical F1 g=90 fd=8?** Pre-state fd=8, spades cover 2,
blockers 7, K/A access 0, one legal merge. That is an excavated,
assemblable cash-out.

**Q5. Hearts before/after SD5?** After SD5 hearts has cover 3, a_len 8,
k_len 6, gap −1, blockers 16 — prepared but not the cheapest
operational next (clubs cover 2 ranked first, and canonical founds
clubs next). Hearts wait until F7–F8 when blockers hit 0.

The metric treats materially-ready-but-awkward suits as weak
opportunities. `metric_signal=ok`.

---

## Interpretation

Operational viability is a real distinction: same material-ready bit,
wildly different blocker/cover/K-access. Using it as READINESS plus
keeping cheap_fd/reveal recovered throughput and produced a **healthier
F1** (fd=10 vs 17/23).

It did not produce a sub-198 game. Late F2 at g=183 still leaves no
budget. The remaining gap is less “which suit is ready” and more
**when** the tableau is cheap enough to cash out and how Deal reception
sets up that moment.

Do not add another lane or increase runtime.

---

## Next recommendation

Analyse this healthier F1 lineage (g=71, fd=10, rows=3, spades) and
post-stock conversion. If the next experiment is a new hypothesis
rather than a lineage dive: **Deal-reception shaping**. Do not copy
172.

---

## Files

New: `src/spider/operational_viability.py`,
`src/spider/operational_policy.py`,
`research/operational_foundation_viability_v0_63.py`,
`tests/test_operational_foundation_viability_v0_63.py`,
docs JSON/MD/progress.

Unchanged active v0.59/v0.60 lane names. v0.62 DURABILITY remains as
unused experimental code.
