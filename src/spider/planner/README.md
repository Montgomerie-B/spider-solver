# Planner Package (New Layered Development for Deal 4925153)

> **Authoritative status — 11 July 2026:** The only complete solution is the original user-supplied 172-MobilityWare-move trace. A previously reported 163-move result was caused by defective legacy move accounting and is withdrawn; no distinct 163-move solution exists. The project has not yet generated its own complete solution or beaten the referenced Solvitaire result of 167. See `docs/4925153_frozen_state.md`, `docs/4925153_move_accounting_incident.md` and `docs/layered_planner_accounting_amendment.md`.

**Read this first**: The historical master plan and progress log are maintained in:

→ **`docs/layered_planner_development_plan.md`**

The July 2026 accounting amendment supersedes the historical plan’s old move-cost assumptions:

→ **`docs/layered_planner_accounting_amendment.md`**

This package (`src/spider/planner/`) is the exclusive home for new code under the layered planner architecture.

## Mandatory result accounting

All new planner and optimisation work must:

- use corrected `mobilityware_moves`, never `legacy_mw`, for costs, ceilings and incumbent comparison;
- treat 172 as the current verified incumbent;
- independently replay every complete candidate from the true deal;
- call `record_solution_if_better(...)` immediately after successful full replay;
- require successful external archive write and read-back verification before claiming an improvement.

The durable archive is documented in `docs/solution_archive.md` and defaults to:

`C:\SpiderSolver\solutions\4925153`

The immediate thresholds are:

- 171 or fewer — first genuine project improvement;
- 167 — match the referenced Solvitaire result;
- 166 or fewer — beat it;
- 119 or fewer — long-term stretch target.

## Key Rules (from the approved plan, as amended)

- Legacy code, logs, solutions, analyser outputs and historical experiments remain preserved assets.
- New code here may import from legacy modules and mine human artefacts, but any use of historical `MW` values must be recalculated under corrected accounting.
- At the end of every logical piece of work or decision point, append a dated entry to the Progress Log section of the master plan or an explicit superseding amendment.
- The living todo list must stay synchronised with the phases and gates in the plan.
- A free move to an empty column requires relocation of the entire fully open source column with no face-down cards beneath it.

## Current State

See the Progress Log in the master plan for historical development and `docs/4925153_frozen_state.md` for the current authoritative state.

Phase 0 (infrastructure and baselining) is complete. Phase 1 (Layer 2 Dependency Analyser) is complete with diagnostics for the initial state and human checkpoints.

Phase 2 (Layer 3 Plan/Campaign) plus bridges to Layers 3/4/5 are complete with artefacts. The Layer 5 minimal plan beam-search skeleton is complete and tested on a human checkpoint.

The hybrid move-ordering adapter demonstrated approximately 5.65x higher throughput while preserving calibration rankings. Checkpoint/resume and the durable solution archive are available for future long runs.

## Package Structure

- `dependency.py` — Layer 2 dynamic dependency and exposure analysis
- `plans.py` — Layer 3 `PlanStep`, campaign proposal and labelled human trace
- `scorer.py` — plan-aware score composition
- `realizer.py` — plan-type-aware tactical realisation
- `controller.py` — early Layer 5 controller and deal decision
- `plan_search.py` — minimal plan-level beam search
- `test_macro_integration.py` — layered shaping followed by legacy macro continuation
- `diagnostics/` — human-readable reports, comparisons, validations and experiment artefacts

## Current Usage

Run dependency diagnostics:

```python
from spider.planner.dependency import run_full_phase1_gate_diagnostic
run_full_phase1_gate_diagnostic()
```

Generate proposals and labelled trace:

```python
from spider.planner.plans import run_phase2_example_diagnostic, label_human_opening_trace
run_phase2_example_diagnostic()
label_human_opening_trace()
```

Controller:

```python
from spider.planner.controller import tiny_plan_controller_demo
spaces, sw = tiny_plan_controller_demo()
```

Minimal plan beam:

```python
from spider.planner.plan_search import minimal_plan_beam_search
nodes = minimal_plan_beam_search()
```

Integration test:

```python
from spider.planner.test_macro_integration import test_layered_first_round_then_legacy
test_layered_first_round_then_legacy(use_checkpoint=False)
```

## Replay and solution capture

Any planner-generated `.moves` candidate must be replayed with the corrected rules engine. Historical files and reports that display an `MW` value may predate the accounting audit and must not be treated as verified MobilityWare scores without recalculation.

A complete candidate must be passed to the central archive API:

```python
from spider.solution_archive import record_solution_if_better

record_solution_if_better(
    deal_id="4925153",
    moves=candidate_moves,
    source="planner experiment",
    experiment_id="experiment-id",
)
```

The archive independently replays the candidate, calculates corrected `mobilityware_moves`, compares it strictly with the verified incumbent and writes any genuine improvement atomically to the external archive.

## Future Exposure

The planner remains additive. To expose it as a mode without removing the legacy path:

- add a GUI selector for layered planning during early rounds;
- add a CLI flag such as `--layered-shaper`;
- add a `MacroConfig` option such as `use_layered_planner`;
- retain the legacy solver for A/B testing and fallback.

All new completion paths must integrate the durable solution archive before unattended execution.

## Diagnostics and explainability

Outputs from this package should be human-readable where practical, especially diagnostics comparing planner decisions with human analyser data and canonical checkpoints.

Typical dependency-analysis setup:

```python
from spider.deal import tokens_from_file
from spider.engine import SpiderState
from spider.deal_analysis import build_deal_analysis
from spider.planner.dependency import DynamicDependencyAnalyser

tokens = tokens_from_file("deals/4925153.txt")
analysis = build_deal_analysis(tokens)
state = SpiderState.from_cards(...)
analyser = DynamicDependencyAnalyser(analysis)
print(analyser.summarize(state))
```

See the master plan for historical gates and `docs/4925153_frozen_state.md` for the current optimisation position.
