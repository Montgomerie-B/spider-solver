# One-off A/B — Latent Workspace / Open-Column Geometry

**Branch:** `dev/open-column-geometry-ab`  
**Start:** `dev/sprint1m-workspace-tactics` @ `9d16dd2`

## Hypothesis

The planner spreads excavation too widely and should value completing
fully-open non-King columns as latent workspace.

## What changed (heuristic only)

- Quality facts: `fully_open_columns`, `fully_open_nonking_columns`,
  `min_column_fd`, `workspace_potential`. Not in dominance / proof pruning.
- One extra stratified beam slot: max `(nonking, -min_fd, potential, -g)`.
- ACCESS secondary sort: after interest and required_reveals, prefer lower
  remaining face-down. Blocked columns still fall through.
- CREATE_WORKSPACE uses the Sprint 1M improved backend at 800 nodes / 0.7s
  when `use_improved_workspace=True` (both A/B arms). Deep maturation
  budgets are unchanged.

## Result: FAILURE

Geometry-ON did not produce a materially different useful state.

| epoch | arm | g | fd | open | nk | minfd | e | ws | ssL |
|---|---|---|---|---|---|---|---|---|---|
| pre-D1 cheapest | both | 0 | 44 | 0 | 0 | 4 | 0 | miss | 0 |
| post-D1 cheapest | both | 1 | 44 | 0 | 0 | 4 | 0 | miss | 0 |
| post-D1 least-fd | OFF | 19 | 30 | 0 | 0 | 2 | 0 | miss | 5 |
| post-D1 least-fd | ON | 21 | 29 | 0 | 0 | 2 | 0 | miss | 5 |
| post-D1 best-geo | both | 8 | 40 | 0 | 0 | 1 | 0 | +3 | 3 |
| post-D2 cheapest | both | 2 | 44 | 0 | 0 | 4 | 0 | miss | 0 |
| post-D2 least-fd | OFF | 20 | 30 | 0 | 0 | 2 | 0 | miss | 6 |
| post-D2 least-fd | ON | 22 | 29 | 0 | 0 | 2 | 0 | miss | 5 |
| post-D2 best-geo | both | 12 | 39 | 1 | 1 | 0 | 0 | +2 | 3 |

Human reference still sits at pre-D1 fd=12 / 5 open non-kings / workspace +2.

- No machine line opened a column before Deal 1.
- Post-D2 both arms already had one fully-open non-King (same g=12 line).
- Workspace +3 post-D1 and +2 post-D2 on that best-geo line, both arms.
  The 1-fd least-fd delta is not a geometry win.

States diverged (post-D2 15 shared / 15 only-OFF / 14 only-ON) but the
useful geometry did not.

Runtime: 64.5s (OFF 26.7s + ON 23.8s + probes).

## Reassessment

A secondary ACCESS sort and one beam slot cannot concentrate excavation
when 1B interest already prefers a different column. Completing a
near-open pile is not what the current ACCESS ranker is optimizing.

Do not extend this branch. Reassess before another planner change.
Possible cheaper probes (not started): ACCESS persistence on the current
actionable focus until blocked or fd=0; or a bounded remaining-fd=1
expose preference that still yields to a blocked column.
