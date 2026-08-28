# Anytime Optimal Spider Solver Architecture

**Status:** Forward architecture / development roadmap  
**Date:** 2026-08-28  
**Scope:** General 1-, 2- and 4-suit perfect-information Spider, with deal 4925153/leaderboard deal 492515 used as the primary benchmark rather than as a hard-coded special case.  
**Strategic companion:** `docs/whole_deal_structural_economics.md`

## Purpose

The project goal is not to produce a solver that knows one special route through one deal. The goal is a general solver that can:

1. find a legal solution quickly when one exists;
2. improve that solution continuously as more search time is available;
3. exploit each incumbent to prune the remaining search more aggressively;
4. eventually prove optimality when computationally feasible; and
5. prove a deal unsolvable only after the complete reachable state space has been exhausted.

The intended operating model is **anytime optimisation**:

`analyse -> generate strategic options -> realise tactics -> first solve -> improve -> tighten bounds -> prove`

At any interruption point the best independently verified solution found so far remains useful.

## Benchmark evidence

The current benchmark deal is stored internally as `4925153`; the MobilityWare leaderboard screenshot labels the same deal **#492515**. Retain the historical repository identifier until a deliberate migration is undertaken.

Known benchmark evidence:

- verified replayable project incumbent: **172 corrected MobilityWare moves**;
- user's historical leaderboard best: **167**;
- leaderboard score: **154**;
- leaderboard best: **119**.

The 119 score is credible external existence evidence, not a route available to the project and not generic strategy input.

## Global strategic objective

The mature solver should not fundamentally optimise "which foundation can I remove next?"

Spider is the transformation of 104 cards into eight complete descending same-suit K-A sequences while:

- exposing every hidden tableau card;
- introducing all five stock rows;
- creating and exploiting workspace;
- minimising fragmentation and future rehandling;
- choosing when to construct, carry, merge and finally remove suit material.

The forward architectural objective is therefore:

> **Minimise the paid structural work required to transform the complete known deal into eight removable same-suit K-A sequences.**

Foundation removal is one major conversion event within that transformation, not the sole measure of progress.

Run construction, reveal/excavation, workspace management, stock timing and foundation removal are competing investments toward the same whole-deal objective.

## Core structural prior: build same-suit runs

A same-suit descending join is structural compression. Two separate card fragments become one movable unit.

Even a two-card run is normally more useful than two separate cards because it can be moved, extended and eventually incorporated into a larger sequence as one object.

The solver should therefore use the following baseline strategic prior:

> If a legal move creates a new same-suit descending connection without sacrificing something demonstrably more valuable, regard the connection as presumptively beneficial.

This is an ordering prior only. It is not a rule, forced move or proof-pruning condition.

Counterexamples must be evaluated explicitly. A join can be sub-optimal when, for example:

- a known future stock row will create the same adjacency for free;
- the join consumes critical workspace;
- it forces expensive later disassembly;
- another physical duplicate produces better downstream geometry;
- it blocks a more valuable reveal or campaign dependency.

The solver should compare these counterfactual consequences rather than attach a blind same-suit bonus.

## Build horizon and removal horizon are separate

For every prospective K-A sequence, distinguish at least:

### Removal horizon

The earliest stock epoch at which all required physical ranks can exist in the tableau and the sequence could in principle be removed.

### Construction horizon

The epochs in which useful portions of the eventual sequence can economically be assembled.

Therefore:

> **Earliest-removal epoch controls when a campaign can cash out; it must never determine when preparation for that campaign may begin.**

A Club sequence that cannot be removed until Deal 5 may still be a valuable Deal-0 through Deal-4 construction campaign.

The planner should track both build readiness and removal readiness. A late-removal suit is not a low-value suit if cheap permanent structure can be created now.

## Whole-tableau structural balance sheet

The strategic planner should reason about assets and liabilities across the entire tableau.

### Structural assets

- same-suit adjacencies;
- movable same-suit runs;
- exposed required sources;
- empty/recoverable workspace;
- prepared stock receivers;
- favourable fragment ordering;
- near-complete or complete K-A sequences.

### Structural liabilities

- buried compulsory cards;
- fragmented suit material;
- mixed boundaries;
- temporary parks and rehandling obligations;
- occupied critical workspace;
- poor stock reception;
- overlays blocking useful fragments;
- unresolved dependencies.

A move is strategically valuable when it improves the expected whole-deal transformation at acceptable cost, even if no immediate foundation becomes closer.

## Four universal strategic activities

Every solution must ultimately perform four kinds of work.

### 1. Build runs

Establish same-suit descending adjacencies and reduce fragmentation.

### 2. Expose cards

Every hidden tableau card must become accessible. Reveals have no information value to a perfect-information solver; their value is structural.

### 3. Create and exploit workspace

Empty columns and useful open columns enable excavation, rearrangement, temporary parking and assembly. Space must be modelled with creation, use, occupation, recovery and replacement costs.

### 4. Introduce and exploit stock

Every stock row must eventually be dealt. Timing should be judged against exact incoming cards, free construction opportunities, supplied dependencies, receiver geometry and current work surrendered.

Foundation removal converts completed construction into permanent tableau simplification and more freedom.

## Competing marginal returns

At any state, several objectively useful actions may compete:

- create a same-suit join;
- expose a compulsory card;
- create/recover an empty column;
- clear a campaign overlay;
- prepare the next known stock row;
- consume a supplied campaign source;
- complete a foundation.

The strategic question is:

> Which structural transformation has the highest marginal whole-deal value now, and when should the solver switch objectives?

The analyser should expose transparent components rather than collapse everything prematurely into one fitted score.

For a run-construction opportunity, relevant facts include:

- new same-suit adjacency;
- fragmentation reduced;
- future handling avoided;
- campaign dependency advanced;
- whether future stock creates the same join for free;
- workspace/carrying cost;
- interference with other campaigns.

For reveal, workspace and Deal opportunities, equivalent transparent cost/benefit facts should be available.

## Permanent adjacency accounting

Immediately before removal, every K-A sequence contains twelve same-suit adjacencies. Across eight completed sequences, 96 such relationships must exist at some point.

This is **not** by itself an admissible move lower bound because stock can create joins for free, duplicate assignments are flexible and paid moves can have multiple effects.

It is nevertheless a useful structural representation. The whole-deal analyser should eventually distinguish:

- final adjacencies already established;
- adjacencies cheap to build now;
- adjacencies likely to be created for free by known stock;
- adjacencies blocked by hidden cards/overlays;
- adjacencies whose early construction carries excessive workspace cost.

## Duplicate-card assignment

Each suit has two copies of each rank. Assignment of physical cards to sequence #1 versus sequence #2 is itself strategic.

Do not commit physical copies earlier than necessary. Campaign identities should permit interchangeable source substitution while that remains economically useful.

The future global planner should be able to compare alternative assignments according to excavation cost, receiver geometry, stock timing and carrying cost.

## Carrying cost of prepared runs

Prepared same-suit structure is valuable but can occupy useful tableau real estate.

A long run that cannot yet be removed may:

- reduce fragmentation and future handling;
- remain highly movable as one unit;

while also:

- occupying a critical column;
- covering a receiver;
- constraining workspace;
- interfering with another campaign.

Therefore the planner should evaluate **construction value versus carrying/interference cost**.

Sometimes the right answer is to build immediately; sometimes to build only a lower or upper fragment; sometimes to wait because later stock performs the join for free.

## Spaces as a first-class resource

An empty tableau column is a strategic asset with a lifecycle:

`create -> use -> occupy -> recover/replace -> carry through stock -> reuse`

The solver should model:

- cost to create a space;
- temporary versus permanent occupation;
- operations enabled while free;
- recoverability;
- replacement-space creation;
- exact interaction with known future stock.

Because stock is known, the solver can reason about:

`space before Deal -> incoming card lands -> incoming card has known destination -> space effectively recovered`

Raw empty-column count is therefore insufficient; effective workspace and recoverability matter.

## Stock epochs

Model the game strategically as:

`opening -> Deal 1 -> Deal 2 -> Deal 3 -> Deal 4 -> Deal 5 -> finish`

For every epoch the solver knows:

- exact tableau;
- hidden-card dependency chains;
- exact future stock rows;
- current and potential same-suit fragments;
- which sequences cannot yet be removed;
- which sequences can still be profitably constructed;
- space creation/recovery opportunities;
- unavoidable remaining work.

Before a Deal, ask:

> What low-cost tableau is best suited to receive this exact row while preserving or increasing whole-deal structural value?

Deal remains a first-class option even while tableau moves remain legal under the active Unrestricted Deal profile.

## Whole-deal backward/forward planning

The mature strategic planner should combine backward and forward passes.

### Backward pass

Starting from the requirement for eight complete K-A sequences, derive flexible requirements backwards through known stock epochs:

- which ranks/copies cannot appear before particular Deals;
- which fragments should ideally be prepared before those Deals;
- which overlays must be cleared earlier;
- which receivers/workspaces should be preserved;
- which same-suit joins are cheap now but expensive later;
- which physical-copy assignments should remain flexible.

The output is a dependency schedule and portfolio of candidate construction/removal schedules, not one rigid suit order.

### Forward pass

Realise the current plan from the exact tableau while continually measuring:

- actual tactical cost of predicted construction;
- reveal consequences;
- workspace geometry;
- stock reception;
- campaign dependency closure;
- carrying cost of prepared runs;
- whether another campaign/order has become cheaper.

Then replan.

The intended loop is:

`whole-deal analysis -> backward structural schedule -> forward realisation -> exact reanalysis -> schedule revision`

## Relationship to foundation campaigns

Foundation campaigns remain important, but each should expose multiple independent states.

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
- occupies useful workspace;
- blocks another campaign;
- deliberately fragmented because later assembly is cheaper.

A campaign impossible to remove now may still deserve substantial current investment.

## Three cooperating solver layers

### 1. Strategic planner

Chooses desirable intermediate outcomes and whole-deal structural investments.

Examples:

- create a cheap same-suit run even for a late-removal suit;
- expose a particular dependency chain;
- create/recover workspace;
- shape columns for known stock;
- clear an overlay blocking a named source;
- preserve an incoming free adjacency rather than pay for it now;
- prepare a sequence long before removal;
- remove a foundation when cashing out structure improves future freedom.

The planner should maintain several competing objectives and campaign schedules.

### 2. Tactical exact engine

Finds the cheapest legal way to realise a strategic objective.

Reuse corrected accounting, exact/quotient search, replay verification, tactical beams and local bounded realisers.

### 3. Proof / optimisation engine

Uses incumbents, admissible lower bounds, transposition and exact search to answer whether a branch can still beat the incumbent and eventually prove optimality or unsolvability.

Heuristic structural economics may order search but never acquire proof authority without a formal admissibility argument.

## Global branch-and-bound

Once any complete legal solution of cost `U` is known:

- `g(s)` = corrected paid cost already spent;
- `h(s)` = admissible lower bound on remaining corrected cost.

Prune for strict improvement only when:

`g(s) + h(s) >= U`

For the benchmark the verified incumbent is 172. The external 119 score may be used as an explicit experimental target input, never as hidden generic strategy logic.

Current safe lower-bound components include mandatory remaining Deals and the established paid-reveal bound:

`h_deals = remaining_deals`

`h_reveal_paid = ceil(max(0, face_down - 10*remaining_deals) / 2)`

`h_admissible = h_deals + h_reveal_paid`

Do not naively add overlapping heuristic components.

## Canonical solutions as safety nets, not scripts

The verified 172 route provides:

- an incumbent;
- legal successful states;
- suffix-cost evidence;
- regression anchors;
- diagnostic human strategy evidence.

It is a scaffold, not the machine's strategy. New search may diverge immediately when whole-deal analysis finds a better path.

## Development roadmap

### Phase A — Baseline architecture and correctness

- keep rules, scoring, replay and archive invariants frozen;
- keep benchmark-specific data out of generic strategy;
- preserve historical planner/experiment documents as audit evidence.

### Phase B — Perfect-information structural analyser

For any state, compute:

- hidden-card dependency chains;
- same-suit construction opportunities;
- build horizon versus removal horizon;
- potential final adjacencies and duplicate-copy alternatives;
- run carrying/interference cost;
- space lifecycle/recoverability;
- exact stock reception;
- candidate strategic objectives.

### Phase C — Strategic objective portfolio

Generate diverse objective families:

- run construction;
- targeted reveal;
- create/recover workspace;
- overlay/dependency closure;
- stock receiver preparation;
- campaign construction;
- campaign removal;
- deliberate postponement when future stock performs work more cheaply.

### Phase D — Tactical realisation

Use exact search where tractable and bounded heuristic realisers elsewhere. Every realised strategic edge must independently replay.

### Phase E — First-solution anytime controller

Search over strategic outcomes, not raw moves alone. Maintain diverse whole-deal states and return the first complete legal solution immediately, then continue improving.

### Phase F — Whole-deal backward/forward scheduler

Once local campaign chaining is reliable, add the global structural schedule:

1. analyse all eight prospective K-A sequences and duplicate assignments;
2. derive backward construction/dependency requirements across stock epochs;
3. retain multiple plausible suit/construction schedules;
4. realise forward while re-evaluating exact geometry;
5. revise the schedule whenever actual tactical cost changes the economics.

This phase should explicitly value early construction for suits that cannot be removed until late stock epochs.

### Phase G — Incumbent-guided improvement

Use each complete solution to tighten branch-and-bound, search cheaper structural histories and archive every strict verified improvement.

### Phase H — Optimality / unsolvability proof

Use exact search, stronger admissible abstractions and complete state-space exhaustion where feasible. Otherwise report the best incumbent and proof gap or `unknown within resource budget`.

### Phase I — General benchmark suite

Expand to diverse 1-, 2- and 4-suit deals and track time to first solve, score over time, proven lower bound, optimality gap and memory.

## Near-term controller guidance

Current v0.x foundation gates remain useful capability tests because they expose missing planning/realisational machinery.

However, they must not cause architecture drift toward foundation count as the sole progress measure.

Near-term work should preserve and increasingly expose:

- same-suit construction opportunity;
- late-removal suit preparation;
- run carrying cost;
- reveal/dependency progress;
- effective workspace;
- exact stock opportunity;
- campaign readiness;
- foundation progress.

The future transition to the whole-deal backward/forward scheduler should occur once the controller can reliably chain multiple foundation campaigns without route seeding.

## Non-negotiable correctness rules

- `mobilityware_moves` is the optimisation metric; `legacy_mw` is forensic only.
- Every claimed solution must independently replay legally from the true deal.
- Automatic foundation removal remains zero cost.
- Stock Deals cost one.
- Active benchmark rule profile retains Unrestricted Deal ON.
- Multi-card tableau movement requires descending same-suit blocks.
- A free empty-column relocation applies only under the corrected tested whole-open-column rule.
- Every strict improvement must pass durable archive write and read-back replay.
- Heuristic estimates may order search, but only admissible bounds may proof-prune.
- Benchmark scores, routes, suits and columns must never become hidden generic strategy constants.

## Relationship to companion and historical documents

`docs/whole_deal_structural_economics.md` is the detailed strategic companion to this architecture and is authoritative on the separation of build horizon from removal horizon, presumptive run-construction value, carrying cost and whole-deal backward/forward planning.

`docs/anytime_solver_development_plan.md` remains the forward implementation/audit plan and should interpret foundation-oriented milestones under this broader structural objective.

`docs/layered_planner_development_plan.md` remains a historical baseline. It is not deleted or rewritten.

Historical v0.x controller documents remain useful evidence and regression history. New development choices should be evaluated against this whole-deal, deal-independent architecture rather than against any single benchmark route or foundation order.
