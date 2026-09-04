# Whole-Deal Backward/Forward Scheduler v0.7

## Status

Scheduler v0.7 graduates the bounded lead-source excavation macro from
`c893ef2` without changing its semantics, envelopes, or TT/proof policy.

## What remains from v0.6

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

## What v0.7 adds

A single CLEAN successor family `LEAD_SOURCE_EXCAVATION` for a short
post-stock tactical valley:

- stock is empty;
- the current canonical lead's first unresolved missing-edge needs a
  face-up source under exactly one immovable blocker;
- a same-suit receiver for that blocker is covered by exactly two face-up
  cards;
- those two cards peel as legal `MIXED_SUIT_PARK` moves that break no
  stable join and do not use an empty column;
- the blocker then makes an exact stable same-suit join onto the receiver;
- that consume exposes the required current-lead source;
- `lead.ordering_key()` after the complete three-action macro is non-worse
  than the parent.

The controller emits only the replay-verified three-action successor.
Corrected g includes all three tableau moves. Individual peels are not
admitted merely because the pattern exists.

## Explicit non-features

- no generic depth-3 search
- no empty-column planner
- no general excavation campaign
- no mixed-park cap increase
- no receiver-uncover widening
- no benchmark-specific route
- no TT / proof identity change
- no local-champion / CF / OPT-assignment change
- no `_node_priority` reorder
- no resource / search-limit increase
