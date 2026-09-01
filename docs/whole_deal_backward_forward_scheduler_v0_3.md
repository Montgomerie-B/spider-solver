# Whole-Deal Backward/Forward Scheduler v0.3

## Status

Scheduler v0.3 is implemented on top of authoritative scheduler v0.2 commit
`5e34e3b5fba2dfdfb3e2709607d88ab26166a2ef`. It adds Deal-causal arrival
conversion, bridge consumption and foundation-lane continuity without changing
the rules engine, exact state identity, corrected-cost dominance, admissible
bound, tactical budgets, frontier width, persistence or the four-objective
scheduler limit.

The result is a **PASS** under the task's third criterion: multiple natural
arrival conversions occur in Gate X and reduce foundation-lane fragment
partitions. Neither Gate X nor Gate Y reaches F2, so the result is not a strong
pass. The remaining architectural class is **F, multi-epoch sequencing
failure**: individual conversion works, but converted descendants do not yet
mature into a second foundation or a sustained untouched Deal rhythm inside
the fixed frontier.

## Pre-policy v0.2 audit

The required untouched v0.2 Gate-W trace was reproduced before integrated
search behaviour changed:

- 50 strategic expansions in 59.472 seconds;
- F0, stock 50, selected `g=6`;
- continuous scheduler transitions E0→E1→E2→E3→E4;
- nine bridge arrivals;
- nine high-leverage arrivals;
- four new-fragment opportunities.

All nine physical arrivals remained present in the fresh leverage analysis.
All nine were omitted from the fixed four-objective post-Deal schedule. On the
exact transition children, zero had an immediate legal conversion, while four
had a one-legal-preparation conversion. Because no equivalent conversion
objective or conversion successor was generated, zero correct exact-TT-
admitted conversion successors were later starved.

This fixes the diagnosis at the objective/actionability boundary, not at the
global frontier boundary. Consequently v0.3 does **not** add an arrival-
conversion representative. Its reserved/expanded counters remain zero.

## Causal arrival model

`PostDealConversionLedger` answers one question: what became structurally
possible because of this exact Deal? Each opportunity records:

- the source epoch and deterministic transition identity;
- the exact Deal row;
- the physical/value incoming card and destination column;
- the causal kind;
- the matched semantic suit/lane;
- pre-Deal missing adjacency requirements;
- post-Deal target adjacencies and lane state;
- immediate legal conversions;
- one legal preparation, if one exists;
- structural benefit, stable-edge debt and deadline;
- conversion class and actionability stage.

An incoming card becomes a conversion opportunity only when the exact
pre/post facts support a relevant reception, a leverage edge, a bridge, or a
specific temporal-floor crossing. Mere usefulness after the Deal is
insufficient. Unrelated row cards are excluded.

The conversion classes are:

- `CONSUME_NOW`;
- `PREPARE_THEN_CONSUME`;
- `FOUNDATION_CONVERT_NOW`;
- `DEFERRABLE_ARRIVAL`;
- `NO_CURRENT_CONVERSION`;
- `INVALIDATED_ARRIVAL`.

The lifecycle distinguishes planned future source, arrived, exposed,
actionable, consumable, consumed, integrated, foundation-convertible,
terminal and removed. A card need not traverse every stage.

## Existing machinery remains responsible for moves

The scheduler does not execute cards and has no recursive conversion search.
It may inspect immediate legal moves and one legal preparation. A
prepare-then-consume objective enters the controller only when that preparation
already exists among generated, replay-valid successors. Consumption and all
later continuation still use the inherited economic, construction, terminal,
milestone and source-completion machinery.

The arrival obligation maps into v0.2 saturation:

- profitable, next-Deal-sensitive direct conversion maps to `MUST_PRE_DEAL`;
- one bounded legal preparation maps to `MUST_PRE_DEAL` or
  `ADVANTAGE_PRE_DEAL` according to exact marginal economics;
- safe future work maps to `DEFERRABLE`;
- work without a credible current path maps to `NON_ECONOMIC` and does not
  block Deal.

Arrival objectives replace lower-ranked objectives within the existing limit;
they do not create a fifth slot.

## Conversion harvest and lane continuity

Fresh admitted conversion edges classify consequences as source consumed,
source integrated, bridge merge, fragment extension, fragments joined, lane
completed, terminal qualified, foundation removed, workspace unlocked, new
reveal, dependency-chain advance or explicit no harvest. The Deal itself and
mere continued card presence are never conversion harvest.

After a conversion, each affected remaining suit lane is rebuilt from exact
structure. Its record contains all K-A target edges, satisfied/missing edges,
temporal floor, canonical duplicate assignment, current fragment partition,
merge work, next bridge and terminal state. The lane states are fragmented,
bridge-ready, merge-ready, terminal-ready and removed. Duplicate copies remain
symmetric; no physical lane identity enters the transposition key.

Value is not double-counted. A single integration may carry several semantic
labels, but telemetry counts a fragment reduction once on the
`FRAGMENTS_JOINED` event. When exact duplicate-lane reassignment changes which
fragments are displayed under a particular lane number, the reduction is
measured on the canonical physical same-suit partition; the diagnostic labels
that basis explicitly instead of pretending lane numbers are persistent card
identities.

## Natural benchmark gates

### Gate X — machine cost-21 F1

The replayed anchor remains exact: corrected total `g=21`, 21 actions, two
Deals, Spades F1, stock 30, 33 face-down cards and path
`924bfd20deac96af`.

Under the unchanged 90-second / 25-expansion / 300,000-node / frontier-256 /
closure-beam-192 / persistence-3 envelope, Gate X completed 25 expansions in
31.216 seconds and used 101 tactical nodes. The selected continuation remains
F1 at relative `g=5` (total 26), stock 30 and 32 face-down cards.

Arrival funnel:

- 196 important causal opportunities across admitted Deal children;
- 39 `CONSUME_NOW`;
- 41 `PREPARE_THEN_CONSUME`;
- 85 `DEFERRABLE_ARRIVAL`;
- 31 `NO_CURRENT_CONVERSION`;
- ten generated conversion successors;
- five exact-TT-admitted and selected conversions;
- five sources consumed and integrated;
- five fragment joins and five partition reductions;
- zero terminal qualifications or foundation removals.

One selected Qd line records a one-preparation dependency-chain advance and
later source integration. Four selected Qc lines also integrate and reduce
their exact partitions. This satisfies Gate-Y authorization without a route
hint.

### Gate Y — untouched

The untouched 180-second / 50-expansion / 500,000-node envelope completed all
50 expansions in 58.188 seconds and used 188 tactical nodes. The selected best
state is replay-valid at `g=6`, F0, stock 50 and 39 face-down cards. The deepest
stock state reaches E1 at `g=1`.

One exact E0→E1 transition is reserved, expanded and spent. On its descendant,
one 7d arrival conversion is generated, exact-TT admitted, selected, consumed
and integrated; it creates a fragment extension and one fragment-partition
reduction. Gate Y does not expand a later Deal on that converted branch and
does not reach F1/F2.

This is a real improvement over v0.2's arrival-only evidence, but not yet a
continuous prepare→Deal→convert→later-Deal rhythm.

## Proof and resource safety

The exact TT remains:

`exact structural Spider state -> lowest corrected g`.

Arrival events, obligations, lifecycle status, lane conversion state and
harvest history are absent from canonical identity. The admissible bound is
unchanged. Scheduler proof prunes remain zero. Unrestricted Deal remains on.

Arrival analysis is separately timed. It enumerates ordinary legal moves and
at most one preparation ply, grants no tactical nodes, starts no recursive
search and adds no persistence. The pre-policy evidence did not authorize a
conversion representative, so special frontier coverage remains unchanged.

## Verification and next boundary

The focused v0.3 file contains 68 collected cases, covering all 65 required
behaviours plus generic suit/rank parameterization. Historical v0.2, v0.1,
v0.15 and v0.14 behaviour remains under regression coverage. The final complete
suite passed 1,608 ordinary tests with the unchanged 37 expected xfails and one
inherited warning in 1,218.58 seconds.

The next separately authorized scheduler task should address only the newly
demonstrated global problem: cross-epoch foundation-lane sequencing and
converted-descendant maturation inside the existing capacity. It should not
return to a local-controller micro-sprint, add resources or begin automatically.
