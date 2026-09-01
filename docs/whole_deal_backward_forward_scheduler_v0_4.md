# Whole-Deal Backward/Forward Scheduler v0.4

## Status

Scheduler v0.4 is implemented on authoritative v0.3 commit
`bc3c4e0656a52d3f4f3627927e222e22b8dc5369`. It adds current-state
foundation-lane cash-out assessment, cross-lane sequencing, compressed
maturation objectives, typed maturation-versus-Deal economics, and exact
post-successor progress traces. It does not change MobilityWare rules,
corrected accounting, exact state identity, exact-TT dominance, the admissible
bound, frontier width, tactical resources, persistence, closure limits, or the
four-objective scheduler portfolio.

The verified benchmark verdict is **FAIL** under the task's strict hard gate.
Natural maturation successors are generated, exact-TT admitted, selected, and
ordinarily expanded, but none is causally linked to an integrated arrival on
one continuous branch. Neither fixed gate produces a terminal transition or a
new foundation. The remaining architectural class is **G, cross-lane
portfolio failure**.

## v0.3 blocker and pre-policy audit

The required untouched v0.3 audit was run before sequencing policy changed.
It reproduced the cost-21 F1 Gate X and untouched Gate Y behavior:

- Gate X: 25 expansions, F1, total corrected `g=26`, stock 30, 32 face-down;
- 196 important arrivals: 39 direct consume, 41 prepare-then-consume, 85
  deferrable, and 31 without a current conversion;
- ten conversion successors generated, five exact-TT admitted and selected;
- five sources consumed and integrated, with five physical fragment-partition
  reductions;
- Gate Y: Deal E0→E1 followed by the natural `7d` arrival conversion and one
  partition reduction;
- zero terminal qualifications and zero new foundations in either gate.

The failure was principally that useful post-conversion structure ceased to
have a general scheduler representation when its Deal-scoped arrival
obligation ended. Generic scheduler intent also ranked too late. The audit did
not show a correct, strongly maturing exact-TT-admitted state repeatedly
starved by the global frontier, so it did **not** authorize a maturation
representative.

## Structural cash-out model

Every remaining semantic foundation lane is rebuilt from the current exact
tableau. Its maturation assessment records:

- temporal foundation floor and whether it has been reached;
- canonical current fragments and their satisfied K-A edges;
- missing and future-gated edges;
- already legal one-step bridge and merge evidence;
- buried-source, workspace, stable-break, rehandling, future-material, and
  terminal-gap work;
- exact one-step foundation and workspace consequences where present;
- a typed, explicitly non-proof cash-out estimate.

The maturity states are:

- `FUTURE_GATED`;
- `FRAGMENT_BUILDING`;
- `BRIDGE_READY`;
- `MERGE_READY`;
- `NEAR_TERMINAL`;
- `TERMINAL_READY`;
- `REMOVED`.

A floor crossing removes a temporal barrier but does not force completion.
`TERMINAL_READY` requires both a reached floor and an ordinary legal successor
that causes automatic foundation removal. Fragment count is one component,
not a hard priority: blocker, workspace, stable-break, and rehandling work can
make a two-fragment lane lose to a cheaper three-fragment lane.

## No sunk cost and lane symmetry

The ordering contains no historical paid cost, commitment age, lane history,
or suit reward. It compares only the current exact structural work and payoff.
A previous lead can lose immediately when its blocker or debt grows, a
competitor becomes cheaper, a Deal changes supply, or duplicate assignment is
rebuilt.

Duplicate lane ordinals are not persistent card identities. The structural
fingerprint excludes the lane number and history. A descendant is matched by
fresh structural fingerprint or maximum physical same-suit edge overlap.
Progress is measured on the physical same-suit partition, so column movement
or duplicate reassignment does not erase a real reduction.

## Lead-lane sequencing and objective integration

The scheduler orders all current lanes lexicographically by maturity and typed
cash-out work, then chooses one lead and one deterministic runner-up. All lane
signals are compressed into at most one maturation objective. That objective
reuses the inherited families and existing controller machinery:

- terminal work uses `PREPARE_TERMINAL_SEQUENCE`;
- actionable bridges use `CONSUME_BRIDGE_CARD`;
- buried work uses `EXPOSE_UNLOCK_CARD`;
- remaining useful construction uses `BUILD_FRAGMENT`.

The scheduler still creates no moves and starts no merge search. It only
inspects ordinary legal one-step outcomes already available from the engine.
The controller's existing construction, closure, terminal, economic, and raw
successors remain the realisers.

The total scheduler portfolio remains four. Same-suit redundant intent is
compressed so the lead objective does not crowd out a useful late/future lane.
Arrival obligations are likewise grouped by semantic lane while their full
event telemetry remains available.

## Conversion-to-maturation and progress

After every Deal or admitted tableau successor the schedule is rebuilt. An
integrated arrival can therefore hand off to the same suit lane's fresh
maturation objective even after the Deal-scoped obligation becomes consumed or
spent. Each admitted maturation successor records:

- source and child exact-state fingerprints and epochs;
- semantic lane fingerprint and any causal arrival conversion;
- replayed actions and corrected `g`;
- physical fragment and missing-edge counts before/after;
- blocker work before/after;
- bridge integration, merge/near/terminal transition, reassignment, and
  foundation removal events;
- generated, exact-TT-admitted, selected, and expanded status.

Continued presence is not progress. A substantial event requires a physical
fragment reduction, bridge integration, merge/near/terminal transition, or
foundation removal.

## Maturation versus Deal

The exact v0.2 Deal counterfactual remains authoritative. Maturation delays a
Deal only when its current marginal cash-out value is credible—for example, a
legal foundation conversion, a cheap merge that is materially worse after the
next row, or a workspace-relevant terminal step. Comparable or improved
post-Deal cash-out is `DEFERRABLE`; expensive stable breaks and rehandling are
`NON_ECONOMIC`. Ordinary stock coverage alone is not treated as material loss.

## Representative decision

No maturation representative was implemented. The pre-policy audit found no
post-TT starvation evidence at that boundary, and v0.4's natural gates produce
ordinary exact-TT-admitted maturation states without special coverage. The
required/reserved/expanded counters and representative timing remain zero.

## Natural Gate Z

Gate Z started from the independently replayed machine checkpoint at corrected
`g=21`, Spades F1, stock 30, and 33 face-down cards. Under the unchanged
90-second / 25-expansion / 300,000-node / frontier-256 / closure-beam-192 /
persistence-3 / four-objective envelope, it completed 25 expansions in 32.227
seconds with 99 tactical nodes. Its selected continuation remained F1 at total
`g=26`, stock 30, and 32 face-down cards.

The gate assessed 440 lanes across fresh schedules, made 55 lead selections,
generated 36 maturation objectives, and retained 32. One natural Diamond
maturation successor was generated, exact-TT admitted, and selected. It
reduced the physical suit partition from ten fragments to nine, reduced its
missing-edge count, and integrated a bridge. It was not expanded before the
25-expansion limit. Arrival conversion remained at the v0.3 baseline: five
selected/integrated reductions from 196 important opportunities. No
representative was used.

This corrected the audited representation/selection defect and authorized the
untouched gate under the task's natural substantial-maturation condition.

## Untouched Gate AA

Gate AA used the unchanged 180-second / 50-expansion / 500,000-node /
frontier-256 / closure-beam-192 / persistence-3 / four-objective envelope with
no prefix, target suit, foundation order, or incumbent. It completed all 50
expansions in 60.345 seconds with 147 tactical nodes. The selected best state
was replay-valid at corrected `g=6`, F0, stock 50, and 39 face-down cards.

It assessed 1,016 lanes, made 127 lead selections, generated and retained 117
maturation objectives, generated 11 maturation successors, exact-TT admitted
and selected two, and expanded both. Each expanded Spade successor reduced the
physical partition from six fragments to five, reduced one missing edge,
integrated a bridge, and reduced blocker work to zero. Arrival conversion also
remained healthy: 220 important opportunities, 22 conversion successors, 12
exact-TT-admitted/selected/consumed/integrated sources, and 12 partition
reductions. No terminal-ready transition or foundation occurred.

The run establishes natural lane sequencing and ordinary expansion, but both
expanded maturation traces are epoch-0 branches. Gate Z's selected Diamond
trace is at epoch 3 but is not causally linked to an integrated arrival and is
not expanded. The required continuous arrival-conversion → same-lane
maturation chain is therefore absent. Gate AA did not authorize repeatability
or an optional whole-game attempt.

## Proof, resources, and verification

Maturation assessment, cash-out estimates, lead choice, objectives, progress
deltas, and traces are absent from canonical identity. Exact TT remains
`structural Spider state -> lowest corrected g`; the admissible Deal/reveal
bound is unchanged; scheduler proof prunes remain zero. The implementation
adds no recursive completion search, tactical grant, persistence, or frontier
slot. Lane assessment, cash-out comparison, objective construction,
compression, and representative timing are reported separately.

The focused v0.4 suite contains 70 passing cases, covering all 69 required
behaviors plus controller propagation. The final complete repository suite
passed 1,678 ordinary tests with the unchanged 37 expected xfails and one
inherited warning in 1,256.31 seconds.

## Verdict and precise next boundary

The verdict is **FAIL** under the explicit hard-gate definition. Arrival
conversion and ordinary lane maturation each work naturally, but on different
branches; no integrated conversion receives further same-lane maturation.
This is architectural class **G, CROSS-LANE PORTFOLIO FAILURE**.

Do not start scheduler v0.5 automatically. If separately authorized, the next
task should trace every fresh schedule immediately after an integrated
conversion and determine why the affected semantic lane loses the lead or
objective handoff. It should preserve no-sunk-cost ordering and should not add
a representative or increase resources without new evidence of post-TT
starvation.
