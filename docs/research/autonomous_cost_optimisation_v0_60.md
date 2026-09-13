# autonomous_cost_optimisation_v0_60

Verdict: `AUTONOMOUS_INCUMBENT_HELD`

One 900 s optimisation of the v0.59 autonomous 198-move solution found **no**
replay-valid complete route with corrected MW &lt; 198. The machine incumbent
remains 198. No v0.60 solution file was written.

Policy: whole-game candidate ceiling started at 197. Remaining Deal costs
were subtracted per epoch (`g + stock_rows <= 197`). Intra-epoch
`harvest_slack = -1` would have tightened the ceiling on any sub-198
terminal. None appeared, so the ceiling stayed 197.

---

## Verified incumbent

`solutions/4925153_autonomous_v0_59.moves` independently replayed:

- corrected MW **198**
- 203 tableau commands, 5 Deals, 10 zero-cost tableau moves
- solved, stock empty, tableau empty, eight foundations

Command count ≠ MW cost. All comparison uses corrected g.

### Incumbent epoch prefix map (derived by replay)

| epoch | enter g | exit g | paid Δ | zero-cost | tableau cmds | fd Δ | F in/out |
|---|---|---|---|---|---|---|---|
| pre-SD1 (rows 5) | 0 | 32 | 32 | 3 | 35 | −26 | 0 / 0 |
| post-SD1 (4) | 33 | 58 | 25 | 5 | 30 | −8 | 0 / 0 |
| post-SD2 (3) | 59 | 73 | 14 | 1 | 15 | 0 | 0 / 0 |
| post-SD3 (2) | 74 | 84 | 10 | 0 | 10 | −1 | 0 / 0 |
| post-SD4 (1) | 85 | 130 | 45 | 1 | 46 | −6 | 0 / 0 |
| post-SD5 (0) | 131 | **198** | **67** | 0 | 67 | −3 | 0 / 8 |

The incumbent completes **all eight foundations after SD5**. Search-time F1
in v0.59 (g=51) was another branch, not this solution’s own first removal.

---

## Architecture changes (v0.59 frozen)

Retained: epoch tableau-only search, generic horizon/readiness, sparse
lanes, SPK1/SPS1, diverse portfolio, Deal as a boundary action.

Added:

- strict candidate ceiling `incumbent_g - 1` plus remaining-Deal bound
- ECONOMY lane with **g first**, then foundations/cover/fd/construction
- cost-conditioned harvest: cheapest-ready, cheapest-cover, cheapest
  construction, cheapest-fd, class-cheap, incumbent checkpoint
- split Pareto (ready vs not-ready) including g
- one protected v0.59 checkpoint per epoch (not a monopoly)
- `harvest_slack=-1` so a sub-198 solve would keep searching cheaper

Did not read `solutions/4925153_canonical.moves` for policy.

---

## Envelope

900 s · 800k unique · 2.5 GiB · ceiling 197 · portfolio 256.

Stopped on **time limit**. Unique 213,274.

---

## Cumulative totals

| | v0.60 | v0.59 |
|---|---|---|
| unique | 213,274 | 326,684 |
| expanded | 41,164 | 40,995 |
| generated | 434,754 | 695,832 |
| exp/s | 45.7 | 45.5 |
| stale | 13,488 | 6,823 |
| max F | 7 | 8 |
| min fd | 0 | 0 |
| solved g | none &lt; 198 | **198** |

The ceiling cut expensive children (max_g=197). COST stale 6,248 / 10,933
pops — cheap-g copies of structural states.

### Lane expansions

| lane | expansions | pops | stale |
|---|---|---|---|
| cost | 4,685 | 10,933 | 6,248 |
| reveal | 9,038 | 10,932 | 1,894 |
| construction | 10,187 | 10,930 | 743 |
| readiness | 6,569 | 6,731 | 162 |
| horizon | 3,924 | 4,198 | 274 |
| economy | **6,761** | 10,928 | 4,167 |

ECONOMY is a live competitor, not a no-op.

---

## Portfolio economics

DEAL_NOW retained every epoch. Incumbent checkpoint: injected 5, survived
5 (opening already present). Class-cheap displaced 13 expensive structural
twins. Ready epochs harvested cheap_ready / cheap_cover / ready_div /
economy together with structural extremes.

---

## Foundation milestones (search, not the held incumbent)

| F | cheapest g | rows | t |
|---|---|---|---|
| 1 | **41** | 3 | 226 s |
| 2 | 190 | 0 | 851 s |
| 3–7 | 191–197 | 0 | ~852 s |
| 8 | not under 197 | | |

Cheaper F1 than v0.59’s search milestone (51), but F2 collapsed to 190
and F8 was unaffordable at the ceiling.

---

## Epoch-by-epoch savings vs incumbent

No complete candidate, so prefix savings are undefined.

Search still spent real budget in every epoch (rows 5→0), with extra
weight once S/H were materially ready (rows 3–1) and at stock-empty.

Post-stock min_g=6 shows cheap Deal-heavy prefixes exist; they did not
convert eight foundations inside the remaining 197−prefix budget.
Incumbent post-stock itself costs **67 MW**. Entering SD5 at 131 leaves
only 66 MW to beat 198 — one move tighter than the incumbent conversion.

---

## Replay / accounting

Incumbent 198 re-verified. No new solution to replay. Contract green.
Canonical 172 tests untouched (accounting only).

---

## After-run evaluation (not search targets)

- Human canonical 172 — not used for optimisation.
- Historical machine F1 g=21 — not seeded.
- Autonomous incumbent 198 stands.

---

## Files

New: `src/spider/autonomous_cost.py`,
`research/autonomous_cost_optimisation_v0_60.py`,
`tests/test_autonomous_cost_optimisation_v0_60.py`,
docs JSON/MD/progress.

Changed: `whole_game_epoch_scheduler.py` optional kwargs (defaults preserve
v0.59).

No `solutions/4925153_autonomous_v0_60.moves`.

---

## Interpretation

Cost-awareness ran (ECONOMY 6.7k expansions, class displacement, ceiling
197) and even found a cheaper F1 (g=41). It did **not** find a cheaper
complete game. The held 198 route spends 67 MW after SD5 converting zero
foundations into eight. Under a 197 cap that conversion has no slack, and
alternate cheap-F1 lineages failed to finish (F2 at 190). The bottleneck
is late completion / lineage survival, not missing Deal-now or an inert
foundation lane.

**Next recommendation:** Do not widen the envelope. Keep autonomous
whole-game cost optimisation and focus on **post-stock conversion and
cheap-F1 lineage survival through later portfolios** — not card/rank
excavation and not copying the human 172 trace.
