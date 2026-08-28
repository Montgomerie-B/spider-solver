# Anytime Solver Development Plan — Structural Economics Update

**Status:** Forward implementation addendum  
**Date:** 2026-08-28  
**Parent plan:** `docs/anytime_solver_development_plan.md`  
**Architecture:** `docs/anytime_solver_architecture.md`  
**Strategic companion:** `docs/whole_deal_structural_economics.md`

## Why this addendum exists

The existing development plan correctly separates build readiness from removal readiness and already recognises same-suit consolidation, reveals, workspace and stock reception as strategic concerns.

Subsequent discussion sharpened the governing principle further:

> Spider should be planned as a whole-deal structural transformation, not primarily as a sequence of earliest foundation removals.

This addendum records the resulting changes to how the forward plan should be interpreted and implemented. Historical v0.x controller reports remain unchanged.

## Updated strategic objective

The forward implementation objective is:

> Minimise the paid structural work required to transform the complete known deal into eight removable same-suit K-A sequences.

The solver must therefore choose among competing structural investments:

- same-suit run construction;
- reveal/excavation;
- workspace creation and recovery;
- stock reception/timing;
- dependency/overlay closure;
- foundation completion/removal.

Foundation count remains an important progress dimension and capability gate, but not the sole strategic objective.

## New baseline prior: same-suit joins

A legal same-suit descending connection, including a two-card run, should normally be treated as presumptively beneficial when it does not sacrifice something demonstrably more valuable.

The implementation should expose each construction opportunity with facts such as:

- paid cost now;
- permanent adjacency created;
- fragmentation reduced;
- expected future handling avoided;
- campaign dependency advanced;
- whether future stock creates the same adjacency for free;
- workspace consumed;
- carrying/interference cost;
- duplicate-copy alternatives.

This remains heuristic ordering evidence only.

## Build horizon versus removal horizon

The parent plan's `Build readiness versus removal readiness` distinction becomes a first-class requirement.

For each prospective foundation copy, track separately:

### Removal horizon

Earliest stock epoch at which the required physical ranks can all be available and removal is theoretically possible.

### Construction horizon

Epochs in which useful fragments can be economically assembled.

A campaign that cannot be removed until a late Deal must still compete for early construction work when cheap permanent adjacencies are available.

The implementation must not infer:

`late removal -> low current value`.

## Construction state and carrying state

Extend campaign analysis beyond removal readiness.

Each campaign should eventually expose:

### Construction state

- fragmented;
- cheap joins available;
- partially assembled;
- substantially preassembled;
- staged for later completion.

### Carrying/interference state

- cheap to retain;
- occupies valuable workspace;
- blocks a receiver;
- conflicts with another campaign;
- deliberately left fragmented because future assembly is cheaper.

This enables the planner to distinguish valuable early preparation from premature over-consolidation.

## Whole-deal adjacency model

A complete K-A sequence contains twelve same-suit adjacencies. Eight completed sequences therefore require 96 same-suit relationships immediately before their respective removals.

Do not convert this directly into an admissible move lower bound.

Instead, the strategic analyser should eventually classify these inevitable structural relationships as:

- already established;
- cheap to establish now;
- likely to be created for free by known stock;
- blocked by hidden cards/overlays;
- expensive to carry if built too early;
- ambiguous because duplicate physical copies remain interchangeable.

This gives the planner a whole-deal construction map rather than a foundation-only frontier.

## Duplicate assignment remains flexible

The two copies of each rank in a suit create alternative physical assignments to the two final K-A sequences.

The planner should preserve interchangeable-source flexibility until a particular assignment becomes economically justified.

Future backward analysis should be able to compare physical-copy assignments by:

- excavation cost;
- stock availability;
- receiver geometry;
- existing same-suit fragments;
- workspace/carrying cost.

## Changes to strategic analysis responsibilities

The parent plan's `StrategicAnalysis` view should now include these additional or strengthened fields:

- same-suit construction opportunity map;
- build horizon per campaign;
- removal horizon per campaign;
- final-adjacency coverage/availability;
- duplicate-copy assignment alternatives;
- run carrying/interference cost;
- free-future-join counterfactuals from known stock;
- structural balance-sheet summary.

Existing reveal, space-lifecycle, stock-reception, campaign and lower-bound analyses remain required.

## Changes to objective generation

The strategic objective portfolio must explicitly include:

- create a two-card or larger same-suit run;
- extend an existing run;
- merge same-suit fragments;
- deliberately defer a join because future stock performs it more cheaply;
- construct a late-removal campaign early;
- preserve workspace rather than over-build a run;
- reveal/excavate a compulsory source;
- create/recover workspace;
- prepare exact stock reception;
- complete/remove a foundation.

A foundation campaign should therefore compete with construction projects belonging to suits that cannot yet be removed.

## Changes to state/frontier evaluation

Future strategic frontiers should retain diversity across multiple dimensions rather than rank primarily by foundation proximity.

Relevant dimensions include:

- foundations removed;
- permanent same-suit adjacencies;
- same-suit fragment count / fragmentation;
- late-removal campaign construction;
- face-down/dependency burden;
- effective workspace;
- stock-reception quality;
- mixed-boundary/rehandling debt;
- carrying cost of prepared runs;
- next-foundation readiness.

No opaque scalar should become proof authority.

## Changes to Deal analysis

Known stock should be analysed not only for campaign supply and receiver effects, but also for **free future construction**.

Before paying for a same-suit join now, the planner should be able to ask whether an upcoming Deal creates the same or better adjacency automatically.

Conversely, before dealing, it should know which cheap current joins will become expensive or impossible afterward.

This strengthens the existing Deal-purpose and exact-reception work without changing Deal legality.

## Whole-deal backward/forward scheduler — future phase

Once the controller can chain multiple foundations reliably, add a dedicated global scheduling layer.

### Backward pass

From eight required K-A sequences and all known stock/hidden cards, derive:

- earliest removal epochs;
- desirable construction epochs;
- cheap-now versus cheap-later joins;
- overlay-clearing dependencies;
- workspace/receiver requirements;
- flexible duplicate-card assignments;
- candidate construction/removal schedules.

### Forward pass

Realise the current schedule while continuously measuring actual tactical cost and tableau geometry.

After every significant reveal, Deal, workspace change or foundation removal:

- refresh structural facts;
- compare predicted versus realised costs;
- revise the schedule when another construction/removal order becomes cheaper.

The scheduler should maintain several plausible schedules rather than one fixed suit order.

## Implication for current v0.x development

The current v0.6 dependency-closure work remains appropriate.

Foundation #2 is still a useful capability gate because the present blocker is concrete tactical/strategic conversion.

However, later controller work must avoid interpreting repeated foundation gates as the ultimate objective.

The architectural progression should be:

1. finish named campaign dependency closure;
2. demonstrate reliable multi-foundation chaining;
3. expose late-removal run-construction economics explicitly;
4. add the whole-deal backward/forward scheduler;
5. obtain the first complete machine solution;
6. optimise complete-solution cost using incumbents and exact proof machinery.

## Proof boundary

Nothing in this addendum changes proof semantics.

The following remain heuristic/order-only unless separately proved admissible:

- run-construction value;
- adjacency coverage;
- carrying cost;
- late-removal construction readiness;
- free-future-join estimates;
- whole-deal schedule quality;
- duplicate assignment preferences.

Exact structural-state TT dominance and the established admissible lower bound remain authoritative for proof pruning.

## Documentation authority

For forward work:

1. `docs/anytime_solver_architecture.md` defines the high-level architecture;
2. `docs/whole_deal_structural_economics.md` defines the detailed strategic principles introduced here;
3. `docs/anytime_solver_development_plan.md` remains the main implementation/audit plan;
4. this addendum updates the interpretation of its strategic-analysis, objective-generation and future whole-deal planning sections without rewriting historical v0.x records.
