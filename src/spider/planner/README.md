# Planner Package

**Forward architecture:** `docs/anytime_solver_architecture.md`  
**Forward implementation plan:** `docs/anytime_solver_development_plan.md`

The older `docs/layered_planner_development_plan.md` is retained as a historical baseline and source of reusable ideas. It is no longer the authoritative forward plan.

This package (`src/spider/planner/`) remains the natural home for generic strategic-planner code.

## Reusable existing assets

The previous layered-planner work is not discarded. The following modules contain useful building blocks and diagnostics that should be reused, refactored or wrapped where appropriate:

- `dependency.py` — dynamic dependency/exposure analysis
- `plans.py` — plan/campaign representation and proposal machinery
- `scorer.py` — plan-aware scoring experiments
- `realizer.py` — tactical plan realisation experiments
- `controller.py` — early plan controller and deal-decision logic
- `plan_search.py` — plan-level beam-search skeleton
- `test_macro_integration.py` — integration experiments and replayable shaper output
- `diagnostics/` — human-readable traces and comparison artifacts

Legacy rule, replay, accounting, solution, GUI and historical experiment assets remain valuable and should not be rewritten casually.

## New direction

The planner is being developed into a general perfect-information anytime solver rather than a deal-specific campaign engine.

The immediate implementation sequence is:

1. ~~foundation-removal feasibility and build/removal readiness~~ (**Sprint 1A done** — `foundation_feasibility.py`);
2. ~~reveal/dependency downstream-value analysis~~ (**Sprint 1B done** — `reveal_graph.py`);
3. ~~empty-column lifecycle and recoverability~~ (**Sprint 1C done** — `space_lifecycle.py`);
4. ~~exact known-stock reception analysis~~ (**Sprint 1D done** — `stock_reception.py`; `strategic_analysis.py` aggregates 1A–1D);
5. admissible lower-bound API / strategic objective generation;
6. strategic objective generation;
7. tactical realisation using the existing exact quotient machinery;
8. anytime first-solution search;
9. incumbent-guided improvement and eventual proof.

Deal `4925153` remains the primary benchmark, but no generic planner logic may depend on its deal number, specific columns, move numbers, suit order or leaderboard scores.

## Correctness invariants

- Optimisation metric is corrected `mobilityware_moves` only.
- `legacy_mw` is forensic only.
- Heuristic scores may order search but may not prune proof search unless admissibility is proved.
- Every claimed complete solution must independently replay from the true deal.
- Every strict improvement must pass the external archive write/read-back verification pipeline.

See `docs/anytime_solver_development_plan.md` for phase gates and the immediate Sprint 1A specification.