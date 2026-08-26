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
5. ~~admissible lower-bound API / strategic objective generation~~ (**Sprint 1E done** — `lower_bounds.py`, `strategic_objectives.py`);
6. ~~tactical realisation of objectives~~ (**Sprint 1F done** — `objective_realizer.py`);
7. ~~first limited plan-level objective search~~ (**Sprint 1G done** — opening→Deal 1);
8. ~~two-epoch plan search~~ (**Sprint 1H done** — Deal 2);
9. ~~post-Deal-2 maturation~~ (**Sprint 1I done** — `search_epoch_maturation`);
10. ~~strategic campaigns / productive investment~~ (**Sprint 1J done** — `strategic_campaigns.py`, `campaign_realizer.py`);
11. ~~robust / actionability-aware campaigns~~ (**Sprint 1K done** — ACCESS fallback, semantic integrity);
12. ~~ACCESS-integrated epoch planning through Deal 3~~ (**Sprint 1L done** — `use_access_campaigns` in `plan_search_v2`);
13. ~~tactical workspace breakthrough~~ (**Sprint 1M done** — `workspace_tactics.py`);
14. ~~economic project / reveal-value / incumbent-budget analysis~~ (**ordering-only shared layer done** — `economic_projects.py`, `incumbent_budget.py`);
15. anytime first-solution search;
16. incumbent-guided improvement and eventual proof.

Deal `4925153` remains the primary benchmark, but no generic planner logic may depend on its deal number, specific columns, move numbers, suit order or leaderboard scores.

## Correctness invariants

- Multi-card tableau moves must be descending same-suit blocks. See the
  authoritative [same-suit block legality audit](../../../docs/same_suit_block_legality_audit.md)
  before reusing historical campaign or quotient results.
- Immediate move cost is not strategic equivalence: permanent same-suit joins
  dominate otherwise-comparable temporary parks. Rehandling debt is an
  ordering heuristic only and must never prune admissible proof search.
- Optimisation metric is corrected `mobilityware_moves` only.
- `legacy_mw` is forensic only.
- Heuristic scores may order search but may not prune proof search unless admissibility is proved.
- Every claimed complete solution must independently replay from the true deal.
- Every strict improvement must pass the external archive write/read-back verification pipeline.

See `docs/anytime_solver_development_plan.md` for phase gates and the immediate Sprint 1A specification.
