# whole_game_epoch_portfolio_v0_59

Verdict: `EPOCH_PORTFOLIO_AUTONOMOUS_SOLVE`

A generic epoch-portfolio scheduler, built on the v0.57 kernel with no
`simple_*` search dependencies, produced a complete independently replayed
solution of the 4925153 deal at **198 corrected MobilityWare moves**.

The route was not taken from the human 172 trace. It is an autonomous
machine solution.

---

## Envelope (one policy, one run)

- 900 s · 800,000 cumulative unique · 2.5 GiB RSS · MW ≤ 300
- portfolio width 256
- terminal: `state.is_solved()` only
- Deal is engine-legal but not expanded inside `run_search`

Stopped on **solved**. Unique 326,684. RSS 155 MB.

---

## Generic material horizon

`structural_analysis.suit_material_horizon` / `next_foundation_material`
count tableau ranks for the *next* foundation of each suit, then walk
engine Deal rows (`stock[-10:]` LTR) until a complete K–A set exists
outside stock. This is material availability, not operational reachability.

Independently derived on the untouched 4925153 opening:

| suit | deals until material |
|---|---|
| Spades | 2 |
| Hearts | 2 |
| Diamonds | 4 |
| Clubs | 5 |

This matches the historical audit oracle and was **not** used as search
seeding. Ready-suit ties are retained (opening nearest horizon is S and H
together at 2).

After a foundation is removed, the next-set count ignores cards already in
foundations.

---

## Scheduler

```
epoch roots → tableau-only run_search → 256-wide diverse portfolio
  → one engine Deal → cheapest-g identity dedup → next epoch
```

Post-stock (rows=0) uses remaining budget toward `is_solved()` with SPS1.

Intra-epoch lanes: cost, reveal, workspace, construction, readiness
(sparse: only if a suit is materially complete now), horizon (sparse: only
if none are). `None` keys skip that heap. v0.54–v0.58 callers still pass
full key dicts, unchanged.

---

## Resource allocation by epoch

Weight = 1 + 1 if any root is materially ready + 2 if stock-empty.

| rows | weight | alloc unique | alloc s | used unique | expanded | elapsed s | n_ready | max F | min fd |
|---|---|---|---|---|---|---|---|---|---|
| 5 | 1 | 100,000 | 112.5 | 61,053 | 8,098 | 112.5 | 0 | 0 | 18 |
| 4 | 1 | 105,563 | 112.5 | 58,436 | 4,127 | 112.5 | 0 | 0 | 10 |
| 3 | 2 | 194,431 | 192.7 | 67,832 | 14,784 | 192.7 | 2 (s,h) | **1** | 9 |
| 2 | 2 | 204,226 | 160.5 | 51,976 | 4,633 | 160.5 | 2 (s,h) | 1 | 6 |
| 1 | 2 | 224,281 | 128.3 | 36,884 | 3,041 | 128.3 | 3 (s,h,d) | **2** | 3 |
| 0 | remainder | 523,819 | 191.9 | 50,503 | 6,312 | 191.9 | 4 (all) | **8** | 0 |

DEAL_NOW controls were kept at every Deal boundary (1, 7, 6, 5, 4).

---

## Portfolio composition (selected)

Round-robin across cheap / foundations / min-fd / workspace /
construction / readiness / horizon / ready-suit diversity / Pareto /
deal-now. Width 159–256. After-Deal unique ≈ portfolio size (0–1
convergence per boundary).

---

## Cumulative totals

| | v0.59 | v0.58 |
|---|---|---|
| unique | 326,684 | 615,235 |
| expanded | 40,995 | 101,659 |
| generated | 695,832 | 1,182,487 |
| expanded/s | 45.5 | 113 |
| stale | 6,823 | 28,054 |
| max F | **8** | 0 |
| min fd | **0** | 13 |
| solved g | **198** | none |

Slower states/s because readiness scoring is heavier; the extra work
bought a foundation gradient.

### Lane expansions (v0.59 vs v0.58 FOUNDATION)

| lane | expansions | pops | stale |
|---|---|---|---|
| cost | 9,558 | 9,566 | 8 |
| reveal | 5,554 | 9,565 | 4,011 |
| workspace | 8,006 | 9,565 | 1,559 |
| construction | 8,769 | 9,561 | 792 |
| readiness | **6,584** | 6,819 | 235 |
| horizon | **2,524** | 2,742 | 218 |

v0.58 FOUNDATION: 39 expansions from 18,531 pops. Readiness is a real
lane. Horizon is used only before material completion (epochs 5 and 4),
then drops out (sparse).

---

## Foundation milestones

| F | first g | stock rows | fd | t (s) | suits |
|---|---|---|---|---|---|
| 1 | 51 | 3 | 14 | 226 | s |
| 2 | 73 | 1 | 13 | 593 | s, d |
| 3 | 191 | 0 | 1 | 801 | c, d, s |
| 4 | 192 | 0 | 1 | 801 | +h |
| 5 | 194 | 0 | 0 | 802 | |
| 6 | 195 | 0 | 0 | 802 | |
| 7 | 197 | 0 | 0 | 802 | |
| 8 | **198** | 0 | 0 | 802 | 2 of each suit |

F1 appears in the first epoch where Spades/Hearts are materially ready
(after SD2). F2 appears once Diamonds are materially ready (after SD4).
F3–F8 cascade in about one second at stock 0.

Cheapest g at each count equals first g (no cheaper later hit).

---

## Best readiness / best state

Best ready topology during search reached cover 2 with merge edges and
long condensation after F2. Best whole-game ranking ended at the solved
state (F=8, fd=0, empty=10, g=198).

---

## Solution

`solutions/4925153_autonomous_v0_59.moves`

- 203 tableau commands + 5 Deals = 208 explicit actions
- corrected MW **198** (free full-column-to-empty accounts for the gap)
- independent `metrics.replay_actions` from the untouched opening:
  legal, stock empty, tableau empty, 8 foundations, `is_solved()`, cost 198

Not derived from `solutions/4925153_canonical.moves`.

---

## Replay / accounting

Contract green. Deal-illegal: false. Canonical 172 regression tests
untouched and still passing.

---

## v0.58 comparison

v0.58 burned stock in 0.16 s inside one global Deal-inclusive frontier
and never scored a foundation. v0.59 forced tableau work inside each
epoch, kept DEAL_NOW controls, and spent extra budget where material
was actually available. Readiness produced 6,584 expansions versus 39.
The machine finished the game.

Historical machine F1 was g=21. This F1 is g=51 — worse, but autonomous
and followed by a complete 198-move solution (canonical 172 remains an
evaluation benchmark, not a search target).

---

## Files

New: `src/spider/whole_game_epoch_scheduler.py`,
`research/whole_game_epoch_portfolio_v0_59.py`,
`tests/test_whole_game_epoch_portfolio_v0_59.py`,
`docs/research/whole_game_epoch_portfolio_v0_59.md`,
`.json`, `whole_game_epoch_progress_v0_59.json`,
`solutions/4925153_autonomous_v0_59.moves` (+ metadata JSON).

Changed: `structural_analysis.py` (horizon/readiness),
`research_actions.py` (`stock_deal_rows`), `search_kernel.py` (sparse
`None` lane keys).

v0.58 left in place.

---

## Interpretation

Epoch portfolios plus a material-readiness gradient turned an unsolved
opening search into a complete game. The important mechanism is
structural: do not expand Deal as an ordinary child; spend tableau
effort where a next foundation is materially possible; keep a diverse
Deal-now/prepare portfolio.

---

## Next recommendation

Stay on the whole-game path and begin **autonomous move-count
optimisation** of this 198-move solution class. Do not return to
individual-card excavation. Do not chase 172 by copying the human trace.
