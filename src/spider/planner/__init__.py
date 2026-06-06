"""
Layered Planner (new development track) for deal 4925153.

This package contains the new 5-layer human-style planner architecture.

Governing rules (per docs/layered_planner_development_plan.md):
- All previous assets are preserved exactly as-is (legacy beam, macro.py,
  heuristics, deal_analysis, engine, all solutions/*.moves, all cli_test_v*.log,
  analyzer, GUI, harness, tests, docs/strategy_insights.md, etc.).
- New code lives here and *calls into* / *mines from* the legacy modules.
- The legacy path remains fully runnable for baselines, A/B comparison,
  and fallback at all times.
- Everything stays on the same deal (4925153).
- MW costing, replay validity, full-stock simulation, prefix bootstrap,
  and the existing 5-deal macro skeleton are non-negotiable.

See docs/layered_planner_development_plan.md for the baselined high-level plan,
phases, gates, and reuse strategy.

This file and the planner/ package were created as Phase 0 scaffolding.
No legacy files were modified.
"""

# Intentionally minimal at creation time.
# Concrete modules (dependency.py, plans.py, scorer.py, realizer.py, controller.py, ...)
# will be added incrementally per the baselined plan.

__all__ = []  # populated as modules are added
