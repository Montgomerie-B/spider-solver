# Sprint 1C — Empty-Column Lifecycle / Recoverability

**Status:** Complete  
**Branch:** `dev/sprint1c-space-lifecycle`  
**Baseline:** Sprint 1B @ `e8d0cac`  
**Date:** 2026-08-12  

## Objective

Model empty columns as **workspace** with lifecycle:

`create -> use -> consume/relocate -> recover/replace -> carry through stock -> reuse`

Using the exact next stock row for **space recovery** analysis is in scope.  
General pre-stock tableau shaping is Sprint 1D.

## API / data model

Module: `src/spider/planner/space_lifecycle.py`

| Type | Role |
|------|------|
| `SpaceFact` | Current empties / fully-open / face-down columns |
| `SpaceMoveEffect` | Simulated legal move + corrected MW cost + effect |
| `WorkspaceEffectKind` | `creates` / `consumes` / `relocates` / `preserves` / `other` |
| `SpaceCreationOpportunity` | One-move empty-count increases |
| `SpaceConsumptionFact` / `SpaceRelocationFact` | Classified move subsets |
| `PostDealColumnRecovery` | Per pre-deal empty after next deal |
| `SpaceRecoveryForecast` | Next-stock recoverability |
| `RevealWorkspaceContext` | 1B reveal prefix + workspace labels |
| `SpaceLifecycleAnalysis` | Full state view |

Aggregator: `src/spider/planner/strategic_analysis.py` → `StrategicAnalysis(foundation, reveal, space)`.

## Hard facts vs heuristics

### HARD

- Empty indices/count from actual state
- Every legal move simulated via `clone` + `move(MW_RULES)`
- Corrected MobilityWare cost from engine (not reimplemented)
- Free full-open-column→empty only when `source_face_down_count == 0`
- Entire face-up→empty with face-down remaining is **paid**
- Foundation removal adds **0** cost; post-state can create empties
- Next-deal incoming card on each pre-deal empty
- One-move post-deal same-column recovery (simulated)
- Multi-empty **simultaneous** recovery is **not** a hard joint fact

### HEURISTIC / UNKNOWN

- `heuristic_workspace_burden` / `heuristic_recovery_outlook` on reveal contexts
- Simultaneous multi-space recovery status when ≥2 pre-deal empties
- Multi-move excavation cost for whole reveal chains

## Corrected cost handling

Uses existing `SpiderState.move(..., rules=MW_RULES)` only.  
Tests protect:

- full-open → empty: cost 0, relocates
- face-up-all → empty with face-down under: cost 1, not free
- foundation removal: 0 extra cost

## Canonical human findings

Full-trace move classifications (deal 4925153 canonical):

| Effect | Count |
|--------|------:|
| creates | 43 |
| consumes | 38 |
| relocates | 2 |
| preserves | 86 |
| zero-cost relocate | 2 |
| foundation-related moves | 8 |

**All five stock deals were taken with pre-deal empty count = 0.**  
The human route on this deal does **not** illustrate “carry empty through deal then recover” as a deal-entry pattern; temporary spaces are created and consumed **between** deals.

Representative patterns from the event log:

- Temporary create/consume pairs (e.g. cmd 19 creates col10 empty, cmd 22 consumes it)
- Zero-cost relocate cmd 46: `9→8 k=1 cost=0` empties `[8]→[9]`
- Foundation-linked space swings occur (8 foundation events)

## Next-stock recovery

On synthetic layouts with a pre-deal empty, incoming card mapping and one-move same-column recovery work as hard facts.  
On the canonical deal checkpoints inspected (initial, pre/post deal 1, pre deal 2), there were **no pre-deal empties**, so recovery forecasts are vacuously empty.

## Interaction with Sprint 1B

At pre-Deal 1:

- empty_count = 0
- Top 1B chains (cols 2, 1, 5, 4) mostly have **no empty to spend**
- Col 5 (`Ks→6d` residual) has at least one immediate non-empty destination in the snapshot; deep col 2 often has **zero** immediate legal excavation starts
- Space economics therefore **partially explains** 1B vs human disagreements: high structural interest ≠ currently actionable without multi-move space creation
- It does **not** fully vindicate the human route or 1B ranking; multi-move tactical cost remains open (1D/realizer)

## Tests

`tests/test_space_lifecycle.py` — creation/consume/relocate/cost/stock recovery/multi-empty policy/1A+1B smoke.

## Deferred to Sprint 1D

- Pre-deal **tableau shaping** for known stock rows (not only space recovery)
- Joint multi-space recovery search
- Multi-move excavation cost of reveal prefixes
- Richer strategic objective generation from `StrategicAnalysis`
