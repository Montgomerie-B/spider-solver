# Opt012 — Compact free-quotient exact corridor search

Deal **4925153**, commands **43–51**. Metric: corrected `mobilityware_moves`.

## Problem

Raw exact 0–1 BFS retained full `SpiderState` / structural keys per node (~2–3 exp/s,
~30k states at paid cost 1). Cost-seven was resource-infeasible.

## Free relocation quotient

A **free relocation** costs 0 corrected MW when it:

* moves the entire source face-up column;
* has no face-down cards under the moved cards;
* targets an empty destination.

At the command-42 start state:

* **5** complete open free piles + **1** empty slot = **6** free slots;
* zero-cost closure size **720 = 6!**;
* **one** quotient component;
* every free edge is **reversible**.

The quotient key stores:

* packed fixed (non-free) columns;
* the invariant free-slot index set;
* sorted multiset of free pile sequences + empty count;
* stock and foundations.

## Paid graph

Edges between components are paid (cost 1). Search is layered BFS on paid cost
`0..ceiling`. Expansion enumerates paid moves from all free placements in a
component, then re-canonicalises successors.

## Target-monotonic pruning

Exact (not heuristic) filters:

* face-down prefix compatibility with the command-51 target;
* foundation / stock compatibility (no deals);
* admissible `remaining_required_reveals` lower bound (one paid move per required exposure).

At start, `remaining_required_reveals = 5`, so ceilings **0–4** cannot reach the target.

## Compact arena

Nodes store packed component keys, parent ids, free+paid transition scripts, and
one packed representative — not a full mutable state graph of all 720 members.

## Versions

* `ALGORITHM_ID = opt012_compact_quotient`
* `COMPONENT_KEY_VERSION = CQ01`
* `PRUNE_RULE_VERSION = target_monotonic_v1`
