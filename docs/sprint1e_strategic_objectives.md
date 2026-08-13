# Sprint 1E — Strategic Objectives + Admissible Lower Bounds

**Status:** Complete  
**Branch:** `dev/sprint1e-strategic-objectives`  
**Baseline:** Sprint 1D @ `ced22fe`  

## Modules

- `src/spider/planner/strategic_objectives.py` — portfolio generation
- `src/spider/planner/lower_bounds.py` — proof-safe h(s)

## Objective families

EXPOSE_REVEAL_PREFIX, CREATE_WORKSPACE, CONSOLIDATE_SAME_SUIT,
ADVANCE_FOUNDATION, REMOVE_FOUNDATION (only if theoretically available),
SHAPE_STOCK_RECEIVER, DEAL_NOW.

Each objective has a concrete target predicate, hard evidence, admissible LB,
and heuristic cost/benefit with transparent priority components.

## Diversity

Round-robin across kinds first (not global top-N), then fill by priority.
Deduplicate by `(kind, target_key, params)`.

Default size 6–12. Does **not** run 1D shaping BFS.

## Lower-bound proof result

**Naive `face_down + deals` is NOT admissible** under the real engine:

1. One paid tableau move can flip source **and** dest after foundation removal (≤2 flips).
2. A stock deal (cost 1) can foundation-flip up to 10 columns.

**Proof-safe:**

```text
h_deals = remaining_deals
h_reveal_paid = ceil(max(0, face_down - 10*deals) / 2)
h_admissible = h_deals + h_reveal_paid
```

Free full-column relocate requires `source_face_down_count==0` → cannot reveal.

Prune: improvement iff `g+h < U`; target T iff `g+h <= T` (prune when `g+h > T`).

## Tests

`tests/test_strategic_objectives.py`

## Deferred (1F)

Tactical realisation of objectives (exact/bounded paths to target predicates).
