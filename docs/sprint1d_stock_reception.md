# Sprint 1D — Known-Stock Reception / Pre-Deal Shaping

**Status:** Complete  
**Branch:** `dev/sprint1d-stock-reception`  
**Baseline:** Sprint 1C @ `4b4995b`  
**Date:** 2026-08-12  

## Objective

Exploit perfect knowledge of the next ten stock cards and their destination columns to analyse **reception quality** and small **pre-deal shaping** opportunities.

Question is not only “deal now?” but:

> What low-cost tableau shape should we prefer *before* dealing these exact ten cards?

## API / data model

Module: `src/spider/planner/stock_reception.py`

| Type | Role |
|------|------|
| `IncomingCardFact` | Card → column mapping for next row |
| `ColumnReceptionFact` | Landing kind, outs, foundation tags |
| `LandingKind` | same_suit / mixed / non_connecting / empty |
| `ImmediateOutMove` | Post-deal one-move of the dealt top |
| `ReceptionConflict` | Competing outs to one destination |
| `RowReceptionSummary` | Aggregate counts + joint-status |
| `ReceiverTarget` / `PreDealShapingObjective` | Shape goals |
| `BoundedShapingResult` | Cost-bounded BFS result |
| `StockReceptionAnalysis` | Full view |

`StrategicAnalysis` now includes `stock_reception`.

## Hard facts vs heuristics

### HARD

- Exact next row = `state.stock[-10:]` (engine truth)
- Landing relation to pre-deal top
- Simulated post-deal immediate out-moves + corrected MW cost
- Empty landing + one-move same-column recovery link (1C)
- Destination conflicts among independent out-lists
- Bounded probe **found** paths with exact cost
- Foundation limiting / enables tags from 1A cumulative tables

### HEURISTIC / UNKNOWN

- Joint simultaneous realisation of multiple out-moves
- Soft targets like “avoid mixed boundary” without exact predicate
- Probe **miss** = not found within bound, not impossible
- Receiver “quality” is multi-feature, not one score

## Bounded shaping probe

BFS over legal moves, corrected MW cost ≤ N (default diagnostic 2–3), expansion cap 4000.

Statuses: `already_satisfied` | `found` | `not_found_within_bound`

## Tests

`tests/test_stock_reception.py` — mapping, landings, outs, recovery, conflicts, probe, aggregate, fixtures.

## Canonical Deal 1–5

See diagnostic output from:

```text
python -m spider.planner.diagnostics.stock_reception_report
```

Key expected diagnostic themes (computed, not hard-coded):

- Deal 2 row completes theoretical availability for H#1 / S#1 limiting cards
- Deal 4 interacts with D#1 earliest epoch
- Deal 5 interacts with C#1 / second copies
- Pre-deal empties rare on this human route (per 1C)

## Deferred

- Multi-move joint out-move simulation
- Full “deal now?” decision policy
- Anytime controller / objective portfolio (Sprint 1E+)
