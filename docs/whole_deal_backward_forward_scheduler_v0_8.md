# Whole-Deal Backward/Forward Scheduler v0.8

## Status

Scheduler v0.8 graduates the bounded face-down lead-edge excavation macro
from `a2fa330` without changing its semantics, envelopes, or TT/proof policy.

## Capability stack

### v0.6

- Current-successor frontier economics:
  standing maturation priority uses the successor's already-attached
  `lead.ordering_key()`.
- Authorised Deal accounting: anonymous Deal debt discharges only for
  `RESERVED` / `SPENT` epoch-transition opportunity ids.
- Bounded receiver-uncover: a `MIXED_SUIT_PARK` may be admitted at CLEAN
  only when one-ply evidence shows an existing same-suit receiver, an exact
  immediate follow-up, fragment reduction ≥ 1, no stable join broken, and
  non-regressing canonical lead economics. `bounded_payoff` is a PAYOFF, not
  a parked-card EXIT.

### v0.7

A single CLEAN successor family `LEAD_SOURCE_EXCAVATION` for a short
post-stock tactical valley:

- stock is empty;
- the current canonical lead's first unresolved missing-edge needs a
  face-up source under exactly one immovable blocker;
- two legal `MIXED_SUIT_PARK` peels expose a same-suit receiver;
- a stable consume then exposes that face-up required source;
- global `lead.ordering_key()` after the complete three-action macro is
  non-worse than the parent.

### v0.8

A second CLEAN successor family `FACE_DOWN_LEAD_EDGE_EXCAVATION` for the
next short post-stock valley:

- stock is empty;
- an already scheduled foundation lane has an unresolved missing-edge rank
  whose useful physical copy is face-down;
- that column currently has exactly two face-up blockers above the next
  face-down card X;
- both blockers peel as legal `MIXED_SUIT_PARK` moves (k=1, no empty
  destination, no stable join broken);
- the second park flips X;
- X has an exact legal same-suit receiver;
- consuming X is a stable same-suit join that flips/exposes the required
  scheduled-lane rank;
- the complete three-action suffix is replay-valid;
- the **owning lane's** `ordering_key()` after the complete suffix is
  non-worse than the parent.

The controller emits only the replay-verified three-action successor.
Corrected g includes all three tableau moves. Individual parks are not
admitted merely because the pattern exists.

## Common architecture

All three bounded CLEAN families share the same shape:

```
strategic dependency
  -> short bounded tactical valley
  -> replay-verified macro
  -> ordinary production resumes
```

v0.6 uncover is one ply with a recorded follow-up. v0.7 and v0.8 are
three-action macros whose economics are evaluated only after the complete
suffix.

## Why v0.8 uses owning-lane economics

v0.7 required the global canonical lead key to stay non-worse because it
excavated a **current-lead** face-up source.

v0.8 excavates a **scheduled-lane** face-down rank. That is campaign work
for a lane already in the whole-deal schedule, not a claim that the global
lead must remain frozen:

- the global lead may legitimately rotate during excavation (for example
  when a mixed park occupies a different suit's receiver);
- admission still requires a concrete structural payoff on the owning lane;
- the required revealed rank must participate in that lane's unresolved
  edge structure;
- ordinary production must be able to resume (the next missing-edge join
  becomes legal).

This is not permission for arbitrary local improvement, mixed-park cap
widening, or a global-lead override. Category-2 cases (owning lane
non-worse, global lead temporarily worse) are admitted only when the
complete suffix remains replay-safe, breaks no stable join, and hands a
usable next join back to CLEAN.

## Explicit non-features

- no generic 3-ply search
- no generic excavation planning
- no arbitrary face-down-card targeting
- no empty-column planner
- no mixed-park cap increase
- no v0.7 lead-source excavation widening
- no global-lead override
- no forced foundation-lane persistence
- no benchmark-specific route
- no Td / c10 excavation
- no local-champion / CF / OPT-assignment change
- no TT / proof identity change
- no `_node_priority` reorder
- no resource / search-limit increase
