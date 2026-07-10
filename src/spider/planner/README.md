# Planner Package (New Layered Development for Deal 4925153)

> **Current Status Note (July 2026)**: Work on deal 4925153 has produced a validated 163-move solution (beats Solvitaire's 167). Most branches have been closed. The hybrid adapter (5.65× speedup) is now the recommended frozen configuration. See `docs/4925153_frozen_state.md` for the latest summary. The long-term goal remains reaching 119 moves or better.

**Read this first**: The master plan and all progress is maintained in the root-level authoritative document:

→ **`docs/layered_planner_development_plan.md`**

This package (`src/spider/planner/`) is the exclusive home for new code under the layered planner architecture.

## Key Rules (from the approved plan)
- Legacy code, logs, solutions, analyzer, experiments (v1–v39+), GUI, harness, etc. are **frozen assets**. Do not modify them.
- New code here may import from legacy modules (`spider.engine`, `spider.deal_analysis`, `spider.heuristics`, etc.) and mine human artifacts, but must not change their behavior.
- At the end of every logical piece of work or decision point, append a dated entry to the **Progress Log** section of the master plan document.
- The living todo list must stay synchronized with the phases/gates in the plan.

## Current State
See the Progress Log in the master plan.

Phase 0 (infrastructure + baselining) complete. Phase 1 (Layer 2 Dependency Analyser) complete with diagnostics for initial + human checkpoints.

Phase 2 (Layer 3 Plan/Campaign) + bridges to 3/4/5 (generator, labeled human trace, realizer/scorer stubs, controller with deal decision + validation) complete with artifacts. Layer 5 minimal plan beam search skeleton complete and tested on human checkpoint (explores sequences like Create_Gold_Spaces, Clearance_C).

First 'layered + legacy macro' integration test complete (test_macro_integration.py): beam shapes round 0 via explicit campaigns, legacy macro for rest. Modest budgets: layered start spaces=4/sw=15 (improved), legacy continues with [strategy] (incl low-sw best_deal at 7), overall 9999/no solve. High budget hunt (35s/6000/50k like old vN) launched in bg for measurable 'does campaign-shaped start help solve/cost vs pure legacy?' data.

All per the baselined plan. Hunt in progress (bg task ~468s at last check, no output yet; modest baseline recorded).

## Package Structure (growing)
- `dependency.py` — Layer 2 (dynamic per-state dependency & exposure analysis + diagnostics)
- `plans.py` — Layer 3 (PlanStep dataclass, propose_campaigns_from_dependencies, human opening labeled trace)
- `scorer.py` — Phase 3 (plan_aware_score composition: legacy space_work + plan progress + space_opp conversion)
- `realizer.py` — Phase 4 (simple_realize_plan with plan-type-aware scoring for space vs clearance)
- `controller.py` — Early Layer 5 (tiny_plan_controller_demo with explicit 'deal now?' using scorer)
- `plan_search.py` — Layer 5 (minimal_plan_beam_search skeleton over plan choices + realize, using scorer)
- `test_macro_integration.py` — Phase 6 direction (first layered beam shape round 0 + legacy macro rest; supports high_budget for hunt)
- `diagnostics/` — human-readable artifacts (initial/human reports, comparisons, validation, beam traces, integration test runs)

## Current Usage (stubs + tests; see master plan for gates)
Run diagnostics:
```python
from spider.planner.dependency import run_full_phase1_gate_diagnostic
run_full_phase1_gate_diagnostic()  # initial + human pre-deal1, writes reports + comparison
```

Generate proposals + trace:
```python
from spider.planner.plans import run_phase2_example_diagnostic, label_human_opening_trace
run_phase2_example_diagnostic()
label_human_opening_trace()
```

Controller (campaign-driven shaping + deal decision):
```python
from spider.planner.controller import tiny_plan_controller_demo
spaces, sw = tiny_plan_controller_demo()  # from human checkpoint; uses scorer for 'deal now?'
```

Minimal plan beam (Layer 5 search over campaigns):
```python
from spider.planner.plan_search import minimal_plan_beam_search
nodes = minimal_plan_beam_search()  # explores sequences, prints top with histories
```

Integration test (layered for round 0 + legacy rest):
```python
from spider.planner.test_macro_integration import test_layered_first_round_then_legacy
test_layered_first_round_then_legacy(use_checkpoint=False)  # full from initial
# For high budget hunt (per plan): test_... (high_budget=True)  -- see script comment
```

Produce replay-valid .moves candidate from shaper (Phase 6/7):
```python
# In the test with use_shaper=True it auto-exports to diagnostics/planner_shaper_*.moves
# (shape moves + res.actions combined via legacy metrics.export_actions_to_moves_file)
# Then replay-validate with metrics.replay_actions or tools/replay_moves_file.py
# Modest example artifacts (after fix): planner_shaper_full_from_initial_modest.moves (90 actions, verified MW 89 non-solve playout)
# and planner_shaper_from_human_checkpoint_modest.moves (delta cost 76 from ck). High-budget variants on high runs.
```

See master plan Progress Log for exact artifacts, runs, and comparisons (modest: layered campaign start helps shape; high hunt in bg for solve/cost data vs pure legacy).

## Future Exposure (Phase 6 per plan)
The planner is additive. To expose as mode (without touching legacy):
- In optimizer_gui: add checkbox "Use layered planner for early rounds" that swaps the shaper in optimizer_session/macro for one or more rounds (use controller or beam to shape, then legacy for rest/finisher).
- In CLI (optimize_deal.py): --layered-shaper or --use-planner flag to enable for round 0 (or until deal heuristic).
- In MacroConfig: add use_layered_planner: bool or shaper_fn.
This keeps legacy default and 100% compatible.

See master plan for full Phase 6 wiring.

All output from this package should be human-readable where possible, especially for diagnostics that can be compared to the human analyzer CSVs and `strategy_insights.md`.

## How to Run Early Diagnostics (once implemented)
Typical pattern (from plan):
```python
from spider.deal import tokens_from_file
from spider.engine import SpiderState
from spider.deal_analysis import build_deal_analysis
from .dependency import DynamicDependencyAnalyser

tokens = tokens_from_file("deals/4925153.txt")
analysis = build_deal_analysis(tokens)
state = SpiderState.from_cards(...)  # or load prefix
analyser = DynamicDependencyAnalyser(analysis)
print(analyser.summarize(state))
```

See the master plan for exact gates and validation targets (initial layout + human deal-1 point, reference/post_deal2 checkpoints, etc.).
