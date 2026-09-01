# Whole-Deal Structural Economics

**Status:** Forward strategic principle
**Date:** 2026-08-28
**Scope:** General perfect-information Spider strategy; deal-independent

## Purpose

This note sharpens the strategic objective of the solver.

Spider is not fundamentally a race to remove the next foundation. The game is the transformation of 104 cards into eight complete descending same-suit K-A sequences while progressively exposing all hidden tableau cards, introducing all stock cards, managing limited workspace, and minimising paid handling.

Foundation removal is one important conversion event, but it is not the only valuable form of progress.

The mature solver should therefore optimise the whole-deal structural transformation rather than greedily optimise foundation-removal timing.

## Core rule: same-suit construction is presumptively valuable

A same-suit descending join is a form of structural compression.

Two previously independent card fragments become one movable unit. Even a two-card run is generally more flexible than the same two cards kept separate, because it can be moved, extended and later incorporated into a larger sequence as one object.

The baseline strategic prior is therefore:

> If a legal move creates a new same-suit descending connection without sacrificing something demonstrably more valuable, treat the connection as presumptively beneficial.

This is an ordering prior, not a legality rule and not proof pruning.

The burden of justification normally lies on *not* making a cheap same-suit connection when one is available.

### Important exceptions

A same-suit join can be sub-optimal when a known counterfactual is better, for example:

- an imminent stock row will make the same adjacency for zero additional tableau cost;
- the join consumes the only high-value workspace needed for a more important excavation;
- building the run now forces expensive later disassembly;
- the selected physical copy creates poor receiver geometry compared with an interchangeable copy;
- the join blocks a significantly more valuable reveal, space-creation or campaign dependency;
- a temporary fragmentation has lower whole-deal handling cost than immediate construction.

The solver should compare those actual downstream consequences rather than apply a blanket bonus or prohibition.

## Build horizon is separate from removal horizon

Every prospective K-A sequence has at least two distinct timelines.

### Removal horizon

The earliest stock epoch at which all required physical ranks can exist in the tableau and the sequence could in principle be removed.

This is constrained by hidden-card and stock availability.

### Construction horizon

The epochs in which useful portions of that eventual sequence can economically be assembled.

A sequence may be impossible to remove until a late stock row while still offering highly valuable construction work much earlier.

Therefore:

> Earliest-removal epoch controls when a campaign can cash out; it must never determine when preparation for that campaign may begin.

A suit that cannot be removed until Deal 5 may still be a Deal-0, Deal-1, Deal-2, Deal-3 and Deal-4 construction campaign.

## Example strategic interpretation

Suppose one Club sequence cannot be removed before the final stock row because one or more required Club cards are unavailable until then.

The wrong inference is:

`Club removal impossible before Deal 5 -> ignore Clubs until Deal 5`

The correct analysis is:

`Club removal impossible before Deal 5 -> identify which Club adjacencies can be built cheaply before Deal 5, which should be deliberately deferred, and what tableau carrying cost those prepared fragments impose.`

A cheap early `9c-8c-7c-6c` construction may eliminate several later handling operations even though it has zero immediate foundation-removal value.

## Structural assets and liabilities

The global planner should reason about a whole-tableau balance sheet.

### Structural assets

- same-suit adjacencies;
- long movable same-suit runs;
- low-regret two-card and multi-card runs;
- exposed campaign sources;
- empty columns;
- recoverable workspace;
- prepared stock receivers;
- favourable fragment ordering;
- completed or near-completed K-A sequences.

### Structural liabilities

- buried compulsory cards;
- fragmented suit material;
- mixed-suit boundaries;
- temporary parks with future exit cost;
- rehandling obligations;
- occupied critical workspace;
- poor stock-reception geometry;
- overlays blocking useful same-suit fragments;
- dependencies that must be resolved before an eventual sequence can assemble.

A move should be evaluated by how it transforms this balance sheet over the whole known deal, not only by its immediate local score.

## The four universal strategic activities

A complete Spider solution necessarily requires all of the following.

### 1. Build runs

Reduce card fragmentation by establishing same-suit descending adjacencies.

Run construction can be valuable long before removal is possible.

### 2. Expose cards

Every hidden tableau card must eventually become accessible.

Because the solver has perfect information, reveals have no information value. Their value is structural: they expose required material, create space, change receivers or unlock later dependencies.

### 3. Create and exploit workspace

Empty columns and useful open columns allow rearrangement, excavation, temporary parking and sequence assembly.

Workspace has a lifecycle and a carrying/recovery cost.

### 4. Introduce and exploit stock

Every stock row must eventually be dealt.

Stock timing should be chosen by exact downstream consequences: what current work is surrendered, what incoming cards build for free, what dependencies are supplied, and what receiver geometry is created or destroyed.

Foundation removal sits across all four activities. It converts a completed run into permanent tableau simplification and additional freedom.

## Competing marginal returns

At any state, several good objectives may compete:

- make a same-suit join;
- expose a required card;
- create an empty column;
- prepare the next stock row;
- clear an overlay;
- consume a supplied campaign source;
- finish a foundation.

The strategic problem is not determining whether these are useful in isolation. It is deciding:

> Which structural transformation has the highest marginal whole-deal value now, and when should the solver switch objectives?

A useful implementation model should expose transparent components such as:

### Run construction value

- new permanent adjacency;
- fragmentation reduced;
- expected future handling avoided;
- campaign dependency advanced;
- future receiver obligations reduced;
- future stock may create the same join for free;
- workspace consumed;
- carrying cost until removal.

### Reveal value

- compulsory hidden card exposed;
- dependency depth reduced;
- workspace created;
- useful receiver exposed;
- campaign source unlocked;
- temporary rehandling required.

### Space value

- manoeuvrability gained;
- tactical operations enabled;
- recoverability after occupation;
- opportunity cost of carrying the space;
- stock-row impact.

### Deal value

- exact incoming joins created for free;
- campaign supplies delivered and consumed;
- receivers improved;
- current opportunities buried or blocked;
- additional mixed boundaries introduced;
- irreversible stock row spent.

These are heuristic ordering facts unless a separate admissibility proof exists.

## Permanent adjacency accounting

Immediately before eight sequences are removed, each K-A sequence contains twelve same-suit adjacencies.

Across eight completed sequences, 96 same-suit adjacency relationships must therefore exist at some point before removal.

This does not by itself produce an admissible move lower bound because:

- stock placement may create adjacencies without a paid tableau move;
- one tableau move may create more than one useful relationship through later automatic effects;
- duplicate cards make final sequence assignment flexible;
- a useful adjacency may be broken and rebuilt.

However, it provides a powerful structural planning representation.

The whole-deal analyser should eventually estimate:

- final adjacencies already established;
- adjacencies constructible cheaply now;
- adjacencies likely to arrive for free from known stock;
- adjacencies blocked by hidden cards or overlays;
- adjacencies whose early construction carries excessive workspace cost.

This is a structural-progress measure, not proof authority.

## Duplicate-card assignment

Each suit has two copies of every rank, so the final partition into sequence #1 and sequence #2 is itself a planning problem.

The solver should avoid committing physical copies too early when interchangeable alternatives remain useful.

A future backward planner may maintain alternative assignments such as:

- which physical `7c` belongs naturally with which Club fragment;
- whether an incoming stock copy should replace a buried tableau copy in the preferred construction;
- which copy minimises excavation, receiver and carrying cost.

Campaign identity should therefore describe a structural objective while allowing physical-source substitution until commitment becomes economically justified.

## Carrying cost of prepared runs

A prepared run is valuable but not free.

A long same-suit run that cannot yet be removed:

- reduces fragmentation;
- reduces future handling;
- is highly movable as a unit;

but may also:

- occupy a strategically important column;
- cover a useful receiver;
- constrain workspace;
- interfere with another campaign.

Therefore run construction should consider both:

`construction value`

and

`carrying/interference cost`.

The correct decision may be:

- build immediately;
- build only a lower or upper fragment;
- deliberately leave fragments separate until a particular stock epoch;
- choose another physical copy;
- build now and later move the complete run as a unit.

## Whole-deal backward/forward planning

The future global strategic planner should use both backward and forward reasoning.

### Backward pass

Starting from the requirement for eight complete K-A sequences, derive flexible structural requirements backwards through known stock epochs:

- which physical ranks can only appear after particular stock rows;
- which fragments should ideally already exist before those rows;
- which overlays must be cleared earlier;
- which receivers/workspaces must be preserved;
- which adjacencies are cheap now but expensive later;
- which final-sequence copy assignments remain interchangeable.

The backward result should be a dependency schedule and portfolio of candidate foundation/construction schedules, not one rigid suit order.

### Forward pass

Play from the current exact tableau while continually re-evaluating:

- actual tactical cost of predicted construction;
- reveals and newly available sources;
- workspace geometry;
- stock reception;
- campaign dependencies;
- carrying cost of prepared runs;
- whether another construction/removal order has become cheaper.

When realised geometry differs from the prior estimate, replan.

The intended loop is:

`whole-deal analysis -> backward structural schedule -> forward realisation -> exact reanalysis -> schedule revision`

## Relationship to foundation campaigns

Foundation campaigns remain important, but their role is narrower than the whole-deal objective.

A campaign should distinguish at least:

### Removal state

- impossible before epoch N;
- theoretically available;
- practically reachable;
- near removal;
- removable now.

### Construction state

- fragmented;
- useful joins available;
- economically assemblable now;
- substantially preassembled;
- staged for later completion.

### Carrying/interference state

- cheap to retain;
- occupies valuable workspace;
- blocks another campaign;
- deliberately fragmented because later construction is cheaper.

A late-removal campaign may therefore deserve substantial current construction resources.

## Relationship to the anytime controller

The controller should progressively evolve from foundation-centric milestones toward whole-deal structural economics.

Near-term controller work may continue to use foundation gates because they are useful capability tests. However, development decisions should not infer that the best state is the one closest to the next removal.

The strategic frontier should eventually retain distinct states representing different combinations of:

- permanent run construction;
- reveal progress;
- workspace quality;
- stock-reception quality;
- campaign readiness;
- residual handling debt;
- foundation progress.

Foundation count is one important dimension, not the sole strategic objective.

## Architectural rule

The forward architecture adopts the following principle:

> The solver's global objective is to minimise the paid structural work required to transform the complete known deal into eight removable same-suit K-A sequences. Run construction, reveal/excavation, workspace management, stock timing and foundation removal are competing investments toward that objective. Earliest removal controls when a sequence can cash out, not when useful construction may begin.

This principle is heuristic strategy architecture. It does not alter Spider legality, corrected MobilityWare scoring, exact state identity, transposition dominance or admissible proof bounds.

## Persistent structural projects

Controller v0.10 represents a near-term structural project by semantic target
and fresh residual debt rather than by one tableau geometry. This permits useful
interval, source-chain, workspace and supply investment to survive ordinary
rearrangement and duplicate-card substitution. The target remains bounded and
competes with alternative campaign and late-removal construction; persistence
does not imply tunnel vision or exclusive successor generation.

Economic completion credit is separated from transition bookkeeping. A small
same-suit join is still presumptively valuable primitive construction, a
purposeful Deal is a bridge with a post-Deal conversion obligation, and only a
coherent multi-step result is a substantial structural milestone. An unresolved
actionable obligation is debt, not progress.

Permanent-move dominance applies within this model: at equal immediate
corrected cost and comparable reveal, workspace, stock-reception and campaign
effects, a stable same-suit join dominates a mixed-suit park. Mixed-suit parking
retains its exit route and estimated rehandling debt and requires a concrete
forward benefit to override the permanent join. These lifecycle estimates may
order the frontier but never proof-prune it.

## Current-state foundation-lane cash-out

Scheduler v0.4 establishes a general sequencing principle for the global
planner: compare foundation lanes by the remaining structural work and exact
current cash-out consequences, never by historical investment. A lane's
current fragment partition alone is insufficient. Temporal gates, actionable
bridges and merges, buried-source work, workspace need, stable-break debt,
rehandling debt, terminal gap, and the exact workspace effect of a legal
foundation completion all participate in typed lexicographic ordering.

Only one lead lane becomes a compressed maturation objective in the bounded
scheduler portfolio. Duplicate physical copies remain symmetric, and the lead
is rebuilt after every admitted state. A previous lead receives no persistence
credit merely because work was already spent on it. This cash-out model is
planning evidence only: it is excluded from exact state identity, exact-TT
dominance, admissible bounds, and proof pruning.
