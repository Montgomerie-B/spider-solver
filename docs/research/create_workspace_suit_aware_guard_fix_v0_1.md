# CREATE_WORKSPACE suit-aware singleton-high guard fix v0.1

**Status:** production-quality correction of the validated G1 counterfactual.

**Start SHA:** `b9ac35a98cc90648a25bc23bbbd11826c606e4fc`

**Branch:** `agent/create-workspace-suit-aware-guard-fix-v0-1`

**Decision: A. FIX VALIDATED**

Recommended next step (not taken):

> Bounded R2/R3 frontier-retention and priority experiment.

This does **not** change the current 400-expansion v0.8 solve trajectory.
The resource planner is still not integrated into the controller.  The
natural R3 parent remains unexpanded / frontier-trimmed.

## Exact production diff

In `_realise_create` only:

```python
# before
if len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank:
    continue

# after
# Protect the actual campaign-high card, not every same-rank singleton.
if (
    len(col.face_up) == 1
    and col.face_up[0].suit == target.suit
    and col.face_up[0].rank == target.high_rank
):
    continue
```

No other CREATE predicate changed. Controller unchanged.

## Historical harness (Gate 8)

The counterfactual JSON is not rewritten. Old reports remain historical.

Research `create_guard_mode("G0")` is now a **frozen rank-only** helper.
`G1` is current production CREATE.  That preserves the G0-rejects-Qs /
G1-accepts-Qs tests without monkeypatching production back globally.

## Permanent tests

`tests/test_resource_excavation_planner_create_suit_aware_guard.py`

C1 Qc protected; C2 Qs emitted; C3 unrelated rank; C4 other guards;
natural R3 P workspace lifecycle; S invariance; 69-pair G0/G1 shadow.

Hardened resource-focused tests: 123 passed. No existing expectation
rewrites. Historical counterfactual tests now compare frozen rank-only
G0 against current production G1.

Full pytest: `1893 passed, 37 xfailed, 0 failed in 1408.26s`.
