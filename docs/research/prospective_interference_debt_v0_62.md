# prospective_interference_debt_v0_62

Verdict: `INTERFERENCE_DEBT_NO_GAIN`

One 900 s DURABILITY experiment on the frozen v0.59/v0.60 architecture
did not produce a replay-valid complete route below 198. The autonomous
incumbent remains 198. No `solutions/4925153_autonomous_v0_62.moves`
file was written.

The state-local interference metric is **aligned** with the v0.61
198-vs-172 gap (canonical post-SD5 has 13 unresolved boundaries vs 26).
Using it as a search lane did not convert that signal into a cheaper
whole game inside the existing envelope.

Base: `6c729be374de4f570e78cffad3a6062403ee4822`
Branch: `agent/prospective-interference-debt-v0-62`

---

## Contract

- Search does not read `solutions/4925153_canonical.moves`
- `interference_debt(state)` is a pure function of the current tableau
- Two histories that reach the same packed state yield identical debt
  (regression tested)
- SPK1/SPS1 identity and cheapest-g TT are unchanged
- Past handling is not added to g; corrected MW is still g
- Candidate ceiling 197; remaining-Deal bound retained
- v0.59 `LANES` / `HARVEST_CATS` defaults unchanged

A first 900 s attempt completed the search (`unique=155585`, no
terminal) and then crashed in post-run forensics (card `id()` labels
taken from a second deal load). The same policy was re-run after that
write-path fix. This report uses the completed artefact run. Policy
was not retuned.

---

## Generic metric

Walk each face-up column into maximal same-suit descending components.

| fact | meaning |
|---|---|
| `off_suit_boundaries` | adjacent components, rank-continuous, different suit |
| `rank_break_boundaries` | adjacent components whose ranks are not consecutive |
| `accessible_boundaries` | interface immediately under the exposed run |
| `buried_boundaries` | interfaces under one or more visible components |
| `component_layers` | extra stacked components (`n−1` per column) |
| `max_layer_depth` | max components in any column |
| `mixed_supports` | exposed movable run sitting on a visible non-continuation |
| `visible_components` | fragmentation; not raw bond count |

`boundaries_total = off_suit + rank_break`.

DURABILITY lexicographic order (universal lane):

1. more foundations
2. fewer unresolved boundaries
3. fewer component layers
4. fewer mixed-supports
5. fewer face-down
6. better ready cover (INF if none ready)
7. lower g

No historical rehandle counter. No 172-fit weights.

Harvest additions (round-robin, do not monopolise 256): `durability`,
`cheap_debt` (low g then low boundaries), `cheap_durable` (cheapest g
in a debt-tier class). DEAL_NOW, incumbent, cost, reveal, construction,
readiness, horizon, economy, Pareto retained.

---

## Sanity: 198 vs 172 (analysis only, metric frozen first)

Post-SD5 is the conversion cliff from v0.61 (67 vs 22 remaining MW;
65 vs 54 bonds). The new metric explains the bond inversion:

| | autonomous 198 | canonical 172 |
|---|---|---|
| post-SD5 g | 131 | 150 |
| observed remaining | 67 | 22 |
| same-suit bonds | 65 | 54 |
| **boundaries** | **26** | **13** |
| **layers** | **26** | **13** |
| mixed-supports | 7 | 7 |
| visible components | 36 | 23 |
| max layer depth | 8 | 4 |
| fd / F | 3 / 0 | 1 / 2 |

Canonical has *fewer* bonds and *half* the unresolved boundaries.
Bond count was counting long stacked runs that still have to be
separated.

Earlier epochs (selected):

| boundary | 198 b / layers / mixed / fd | 172 b / layers / mixed / fd |
|---|---|---|
| pre-SD1 | 10 / 10 / 5 / 18 | 10 / 10 / 4 / **12** |
| post-SD2 | 23 / 23 / 10 / 10 | **16 / 16 / 9 / 8** |
| pre-SD5 | 19 / 19 / 5 / 3 | **7 / 7 / 3 / 1** (F=2) |

Canonical is not uniformly lower-debt early (post-SD1 is 19 vs 17).
The gap opens by SD2 and is large by SD5. Signal: **aligned**.
Metric was not edited after these numbers.

---

## Search architecture

Frozen: epoch portfolio, tableau-only intra-epoch, Deal at the
boundary, material horizon, readiness, SPK1/SPS1, cheapest-g TT,
width 256, v0.59 incumbent checkpoints, ceiling 197.

Changed one dimension: prospective interference debt.

Lanes: `cost, reveal, construction, readiness, horizon, economy, durability`.

---

## Envelope

900 s · 800k unique · 2.5 GiB · ceiling 197 · portfolio 256 ·
`harvest_slack=-1` · remaining-Deal bound.

Stopped on **time limit**. Unique 153,717.

---

## Cumulative totals

| | v0.62 | v0.60 | v0.59 |
|---|---|---|---|
| unique | 153,717 | 213,274 | 326,684 |
| expanded | 21,501 | 41,164 | 40,995 |
| generated | 267,044 | 434,754 | 695,832 |
| exp/s | 23.9 | 45.7 | 45.5 |
| stale | 6,539 | 13,488 | 6,823 |
| max F | **4** | 7 | 8 |
| min fd | 2 | 0 | 0 |
| solved g | none &lt; 198 | none &lt; 198 | **198** |
| RSS MB | 93 | — | 155 |

Throughput dropped because every expansion computes interference_debt
and a seventh lane. Unique coverage is below v0.60.

Incumbent checkpoints: injected 5, survived 5. Class displacement 25.

---

## Lane expansions

| lane | expansions | pops | stale |
|---|---|---|---|
| reveal | 4,317 | 4,676 | 359 |
| **durability** | **4,143** | 4,671 | 528 |
| construction | 3,987 | 4,673 | 686 |
| economy | 2,754 | 4,671 | 1,917 |
| readiness | 2,451 | 2,695 | 244 |
| cost | 1,994 | 4,676 | 2,682 |
| horizon | 1,855 | 1,978 | 123 |

DURABILITY is a live competitor, not a no-op.

---

## Portfolio

Every epoch kept DEAL_NOW and (from SD1) the incumbent slot.
Durability cats were populated throughout, e.g. rows=5:
durability 31, cheap_debt 8, cheap_durable 7, class_cheap 35,
horizon 40, deal_now 1. Post-stock: durability 24, cheap_debt 19,
cheap_durable 20, incumbent 1.

---

## Epoch telemetry

| rows | roots | unique | exp | min g | max F | min fd | debt min / median / selected | best durability |
|---|---|---|---|---|---|---|---|---|
| 5 | 1 | 25,145 | 6,835 | 0 | 0 | 15 | 0 / 6 / 0 | g=5, b=0, fd=39 |
| 4 | 193 | 26,888 | 1,845 | 2 | 0 | 9 | 5 / 17 / 5 | g=29, b=5, fd=28 |
| 3 | 217 | 31,633 | 4,935 | 3 | 0 | 9 | 11 / 24 / 11 | g=41, b=11, fd=27 |
| 2 | 245 | 25,537 | 3,771 | 4 | 1 | 9 | 12 / 26 / 12 | g=70, F=1, b=12, fd=20 |
| 1 | 256 | 18,979 | 2,261 | 5 | 1 | 3 | 13 / 22 / 13 | g=87, F=1, b=13, fd=20 |
| 0 | 256 | 25,535 | 1,854 | 6 | 4 | 2 | 5 / 19 / 5 | g=150, F=4, b=5, fd=11 |

Best durability states are low-boundary but **high face-down**. The
lane can prefer a clean shallow tableau over excavation. That is the
opposite of the 172 opening investment (fd 12 at g=50).

---

## F1 / F2 milestones (search, not a complete solution)

| F | cheapest g | rows | fd | boundaries | layers | mixed | t |
|---|---|---|---|---|---|---|---|
| 1 | 60 | 2 | **23** | 14 | 14 | 5 | 442 s |
| 2 | 94 | 0 | 19 | 20 | 20 | 6 | 712 s |
| 3 | 120 | 0 | 17 | 12 | 12 | 5 | 811 s |
| 4 | 148 | 0 | 11 | 7 | 7 | 4 | 898 s |
| 5–8 | not under 197 | | | | | | |

Cheap F1 is still a dirty board (fd=23), worse excavation than
canonical F1 (g=90, fd=8) and worse than v0.60 cheap F1 (g=41, fd=17)
on face-down. Cheapest F2 at g=94 is far cheaper than v0.60’s F2 at
190, but F8 was unaffordable. Cheap F is not success.

---

## Best complete g

None under 197. Incumbent 198 retained.

Post-stock min_g=6 again shows cheap Deal-heavy prefixes; they did
not finish eight foundations. Best recorded state: F=4, g=149, fd=10,
boundaries=8. Best durability: F=4, g=150, fd=11, boundaries=5.
Incumbent post-SD5 is F=0, g=131, fd=3, remaining **67**.

---

## Realised rehandling

No complete candidate, so exclusive REHANDLE cannot be compared on a
new route. Incumbent remains:

| | autonomous 198 |
|---|---|
| exclusive REHANDLE | 126 |
| rehandle actions | 133 |
| mean paid / card | 6.56 |
| paid after attach | 85 cards |
| mixed-park identities | 79 |
| post-SD5 remaining | **67** |

Search-best F4 at g≈150 with fd=11 is not a viable substitute for the
incumbent’s post-SD5 conversion at fd=3.

---

## Hearts (evaluation only)

v0.61 post-SD5 hearts: canonical cover 3 / K 6 / A 8 / gap −1;
autonomous cover 7 / K 3 / A 1 / gap 9. Not used in v0.62 search.
No new complete route to re-measure.

---

## Interpretation

The metric is a valid *description* of why 172 is cheaper than 198:
fewer stacked unresolved boundaries at SD5, not more bonds.

It is not a sufficient *search gradient* under this envelope.

Likely reasons, not forced to a 26-MW identity:

1. DURABILITY’s lex order can keep low-boundary high-fd states
   (best durability at rows=5 is g=5, fd=39, b=0). That starves the
   early excavation the 172 route paid for.
2. Extra lane + metric cut unique coverage vs v0.60 (154k vs 213k,
   24 vs 46 exp/s).
3. Cheap midgame F still arrives on buried boards (F1 fd=23).
   Material availability is not operational viability — the same
   v0.61 lesson, now seen on the machine side.

Do not increase the weight. Do not copy 172.

---

## Next recommendation

Move to the next v0.61 hypothesis: **excavation-gated foundation
cash-out / operational viability**. Gate F-seeking on face-down and
mobility, not cheapest-g F1 and not interference weight. Keep the
frozen architecture. Do not widen runtime.

---

## Files

New: `src/spider/prospective_debt.py`,
`research/prospective_interference_debt_v0_62.py`,
`tests/test_prospective_interference_debt_v0_62.py`,
docs JSON/MD/progress.

Changed: `structural_analysis.py` (state-local debt facts),
`whole_game_epoch_scheduler.py` (optional `enrich_fn`, debt telemetry;
defaults unchanged).
