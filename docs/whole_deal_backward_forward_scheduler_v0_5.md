# Whole-Deal Backward/Forward Scheduler v0.5

## Status

Scheduler v0.5 keeps the class-E post-conversion **handoff emit** and removes
the later conversion-child **coverage reservation**.

Arrival conversion does **not** imply same-lane continuation. After
integration, fresh whole-tableau cash-out ordering is authoritative.

## What remains

When a naturally expanded converted child has:

- matched converted fingerprint still the lead;
- its maturation objective in the four-slot portfolio / one maturation slot;
- an already-legal one-step from lane assessment;

the controller emits and tags that existing successor. No new tactical search.
No extra portfolio slot. Exact TT/proof unchanged.

Non-lead converted lanes are not forced (class B). One-slot maturation
compression is unchanged.

## What was removed

One-shot conversion-child coverage (reserve/expand an integrated child that
was otherwise starved post-TT) is gone.

Gate Z showed five natural integrated children (1 Qd + 4 Qc). Coverage
expanded Qd. Fresh schedules at admission showed **none** had the converted
semantic lane as lead:

- Qd loses to another diamond `MERGE_READY` lane (future-gate 4 vs 2);
- four Qc cases lose to hearts `MERGE_READY` (future-gate 3 vs 0).

Coverage spent an expansion only to rediscover that another lane is better.
That is not a handoff.

## Architectural conclusion

Same-lane continuation after conversion is justified only when **fresh**
economics already make that fingerprint the lead. Sunk conversion cost does
not keep a lane in the maturation slot.

## Remaining diagnostic

If a later search naturally expands a converted child that **is** the fresh
lead, confirm the retained class-E emit produces a causally tagged maturation
successor that exact-TT admits. Do not reintroduce conversion-child coverage
without that evidence.
