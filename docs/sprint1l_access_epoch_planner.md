# Sprint 1L — ACCESS-Integrated Epoch Planning Through Deal 3

**Branch:** `dev/sprint1l-access-epoch-planner`  
**Baseline:** Sprint 1K @ `f80af23`

## Question

Does the proven 1K ACCESS campaign help as a *single* plan-search macro-edge from opening through Deal 3, compared with the same search without it?

Only ACCESS is integrated. WORKSPACE_EXPLOIT / FOUNDATION_BUILD / STOCK_PREP are not plan edges.

## API

`search_to_stock_epoch(..., use_access_campaigns=False, access_max_paid_cost=10, ...)`

- `use_access_campaigns=True/False` is the A/B switch.
- Default is **False** so 1G–1I searches stay unchanged.
- `target_deals=3` uses the same epoch-aware loop (depth reset after each deal).

An ACCESS edge carries replay-valid actions, corrected MW cost, fd reduction, focus/fallback history, and the resulting state.

## Explosion control

- At most one ACCESS per epoch unless empty-count or foundations-removed increased.
- After DEAL_NOW, epoch depth and ACCESS allowance reset.
- Budget capped at 15 paid moves; results cached by `(state_key, budget)`.
- Zero-progress ACCESS is cached as unusable and is not a plan edge.

## Quality

Investment paid / fd reduced is recorded on the node as a **diagnostic**, not a dominance or proof key. Pareto + stratified axes are unchanged.

`REMOVE_FOUNDATION` is expandable whenever the 1E generator emits it (after Deal 2 for this benchmark, generically when theoretically available).

## Tests

`tests/test_access_epoch_planner.py` plus existing 1G–1K planner tests.

## Diagnostic A/B (deal 4925153, reference only)

Runtime **51.2s**. Two identical Deal-3 searches, 32 plan nodes, 40s cap each.

Human: pre-D3 g=100 fd=7 found=1 (S#1 already gone); post-D3 g=101 fd=7.

| mode | cheapest g | least fd | ACCESS terminals | foundations |
|---|---|---|---|---|
| off | 3 (deal×3) | **38** | 0/8 | 0 |
| on | 3 (deal×3) | **34** | 2/4 | 0 |

ACCESS contribution: 15 macros applied, 98 paid, 65 fd reduced during expansion. Best on-path: `ACCESS(+10, fdΔ10) → Deal×3` ends fd=34, investment 1.0 paid/fd.

No Deal 4. No other campaign kinds as edges. `REMOVE_FOUNDATION` was generated after D2 (8/4 attempts) but never realised on these cheap terminals.

Unrelated synthetic: 3 deals, ACCESS used internally (7 applied), terminal was still deal-first.

## Recommendation

ACCESS as a plan edge **does** improve the Deal-3 excavation frontier versus the same search without it (fd 38→34) while preserving the cheap deal-first stratum. It is worth keeping **on** for Deal 1–3 planning.

It does **not** yet approach the human D3 position (fd 7, one foundation). Workspace still fails; foundations are not removed on machine terminals. Do not turn the rest of the campaign mix into plan edges until those operators work.
