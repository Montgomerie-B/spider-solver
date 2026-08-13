# Sprint 1H — Two-Epoch Plan Search (Opening → Deal 2)

**Branch:** `dev/sprint1h-two-epoch-search`  
**Baseline:** Sprint 1G @ `21a7e12`

## API

`search_to_stock_epoch(start, target_deals=2, ...)`

`search_opening_to_first_deal` remains as `target_deals=1`.

`PlanNode` now tracks `deals_done` and `epoch_depth` (reset after each deal).
`dealt` / `objective_depth` remain as compatibility properties.

## Diversity

Stratified beam: cheapest, most reveal progress, strongest same-suit, best
workspace, best foundation readiness, best stock reception, balanced.

Heuristic order key puts **structure before g** so immediate-deal cannot
crowd out investment branches. Scalar is HEURISTIC ONLY.

## Tactical budgets

- DEAL_NOW exact
- cheap expose/shape/consolidate ≤3
- CREATE_WORKSPACE ≤5–6, limited attempts per node
- deeper expose only if `empty_count > 0` (cap +1)

## Human comparison

`replay_canonical_epochs` snapshots pre/post Deal 1 and Deal 2.
