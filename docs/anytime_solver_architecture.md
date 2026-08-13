# Anytime Optimal Spider Solver Architecture

**Status:** Forward architecture / development roadmap  
**Date:** 2026-08-12  
**Scope:** General 1-, 2- and 4-suit perfect-information Spider, with deal 4925153/leaderboard deal 492515 used as the primary benchmark rather than as a hard-coded special case.

## Purpose

The project goal is not to produce a solver that knows one special route through one deal. The goal is a general solver that can:

1. find a legal solution quickly when one exists;
2. improve that solution continuously as more search time is available;
3. exploit each new incumbent to prune the remaining search more aggressively;
4. eventually prove optimality when computationally feasible; and
5. prove a deal unsolvable when the complete reachable state space can be exhausted without a solution.

The intended operating model is therefore **anytime optimisation**, not a monolithic search that remains silent until it has proved an optimum.

A typical run should be able to progress conceptually as:

`analyse -> find incumbent -> improve -> tighten bounds -> improve -> prove`

At any interruption point the best verified solution found so far remains useful.

## Benchmark evidence

The current benchmark deal is stored internally as `4925153`; the MobilityWare leaderboard screenshot supplied by the user displays the same deal as **Deal #492515**. The project should retain the existing internal identifier until a deliberate repository-wide rename is undertaken.

Known benchmark evidence for this deal:

- verified replayable project incumbent: **172 corrected MobilityWare moves**;
- user's historical best shown on the leaderboard: **167**;
- leaderboard second place: **154**;
- leaderboard best: **119**;
- 119 is therefore treated as a credible existence bound for this benchmark deal, although no 119 move sequence is currently available to the project.

These numbers are benchmark evidence, not deal-specific rules. A general solver must work without knowing a leaderboard score in advance.

## Core strategic insight

A strong human does not primarily play Spider by selecting a suit and greedily trying to remove it. Human play is dominated by:

- exposing hidden cards;
- making permanent or low-regret same-suit consolidations;
- creating empty columns;
- using empty columns as temporary working space;
- recovering those spaces later;
- deciding when the tableau is sufficiently well shaped to receive the next stock row;
- avoiding expensive rearrangement that produces little future access.

The perfect-information solver has a major advantage over the human: it knows every hidden card and every future stock card. It should therefore replace human uncertainty heuristics with deterministic downstream analysis.

For example, exposing a King is not intrinsically good or bad. A human may avoid it because the consequence is unknown and a King may consume a valuable empty column. The solver knows exactly what lies beneath the King, what the exposure unlocks, whether another empty column can be created, and whether a consumed space can be recovered after a later stock deal. It should value the actual downstream consequence, not apply a generic King penalty.

Likewise, reveal count is not itself the objective. Humans gain information by revealing cards; the solver gains no information because it already knows them. The optimal perfect-information route may deliberately leave many cards hidden until they are actually useful.

## Spaces as a first-class resource

An empty tableau column should be treated as a strategic asset with a **lifecycle**, not merely counted as one legal destination.

The strategic model should distinguish:

- cost to create a space;
- temporary occupation of a space;
- permanent consumption of a space;
- ability to recover the same space;
- ability to create a replacement space elsewhere;
- ability to carry effective working space through a known stock deal;
- strategic operations enabled while the space exists.

Because the stock is known, the solver can analyse cases such as:

`space before deal -> incoming card lands -> incoming card has known immediate destination -> space effectively recovered`

This is a powerful perfect-information advantage and should become a first-class planning concept.

## Stock epochs

The game should be modelled strategically as six epochs:

`opening -> deal 1 -> deal 2 -> deal 3 -> deal 4 -> deal 5 -> finish`

For each epoch the solver knows:

- the exact current tableau;
- all still-hidden cards and their dependency chains;
- the exact next ten stock cards and their destination columns;
- which suit fragments are available for consolidation;
- which complete sequences can or cannot yet exist because required cards remain in later stock rows;
- which empty columns can be created or recovered;
- the minimum unavoidable work still remaining.

The strategic question before a stock deal is therefore not simply "is the tableau good enough?" It is:

> What low-cost tableau structure is best suited to receive this exact known next stock row while preserving or increasing future manoeuvrability?

A sequence may be worth building long before it can be removed. **Build now** and **remove now** are separate decisions.

## Three cooperating solver layers

The future solver should separate three responsibilities.

### 1. Strategic planner

Chooses desirable intermediate outcomes rather than individual moves.

Examples:

- expose a particular dependency chain;
- create a recoverable empty column;
- consolidate two same-suit fragments;
- preserve a space through the next stock deal;
- shape selected columns for known incoming stock cards;
- postpone an unnecessary reveal;
- assemble a suit fragment that cannot yet be removed;
- trigger a multi-suit cascade only when doing so increases overall freedom.

The strategic planner should generate several competing objectives rather than commit greedily to a single suit.

### 2. Tactical exact engine

Finds the cheapest legal way to realise a strategic objective.

Existing work on:

- corrected MobilityWare accounting;
- collision-safe structural state identity;
- zero-cost free-column quotienting;
- algebraic quotient expansion;
- exact corridor search;
- checkpoint/resume;
- durable solution verification;

belongs here and should be reused rather than discarded.

### 3. Proof / optimisation engine

Uses incumbents, admissible lower bounds, transposition and exact search to answer:

- can this branch still beat the incumbent?
- can this target score still be achieved from this state?
- has a claimed optimum been proved?
- has the entire reachable state space been exhausted without a solution?

This layer converts a strong heuristic solver into an optimiser and, eventually, an optimality/unsolvability prover.

## Global branch-and-bound

Once any complete legal solution of cost `U` is known, every state has:

- `g(s)`: corrected moves already spent;
- `h(s)`: an admissible lower bound on corrected moves still required.

For strict improvement, prune when:

`g(s) + h(s) >= U`

Every improved solution reduces `U` and automatically tightens the whole search.

For a fresh deal the solver first seeks any incumbent. For the current benchmark we already have a verified 172 incumbent. The 119 leaderboard score can additionally be used in experiments explicitly targeting a 119-or-better route, but must not be hard-coded into the general solver.

### Initial admissible lower-bound components

Only mathematically safe bounds may be used for proof pruning. Candidate components include:

- remaining face-down cards that must still be exposed;
- remaining mandatory stock deals;
- proven target-adjacency or breakpoint bounds;
- proven unavoidable structural repairs;
- proven foundation/stock availability constraints.

Bounds must not be naively summed when a single paid move can satisfy more than one component. Use `max(...)`, matching, disjoint abstractions, additive pattern databases, or another formally justified combination.

## Canonical solutions as safety nets, not scripts

A known complete human route is valuable, but the solver must not assume the optimum resembles it locally.

A canonical solution provides:

- a verified incumbent;
- exact legal states throughout a successful route;
- known suffix costs from each canonical state;
- useful training/diagnostic evidence about human strategy;
- safe reconnection points for deviation searches.

The canonical route should therefore be treated as a **scaffold or network of safe harbours**, not as the strategy the machine must imitate.

If a new path reaches a canonical state more cheaply, its known suffix immediately gives a complete improvement. Conversely, a strategic search may diverge from the canonical path very early if perfect-information analysis indicates a better route.

## Development roadmap

### Phase A — Baseline the new architecture

- Preserve historical planner and experiment documents as audit history.
- Adopt this document as the forward architecture.
- Keep rules, accounting, replay verification and archive invariants frozen unless explicitly audited.
- Keep benchmark-specific data outside generic strategy code.

**Gate:** repository documentation clearly separates historical deal-specific planner work from the new general architecture.

### Phase B — Perfect-information strategic analyser

Build a deal-independent analyser that can, for any state:

- construct reveal/dependency chains for every hidden card;
- estimate minimum work needed to reach useful buried cards;
- identify same-suit consolidations and their permanence;
- model empty-column creation, use and recoverability;
- model exact next-stock reception;
- determine earliest stock epoch in which suit material can become removable;
- identify candidate strategic objectives and explain why they matter.

The analyser must use actual known downstream consequences rather than human uncertainty penalties.

**Benchmark diagnostic:** replay the opening of the 172 human route and compare each human move with the analyser's ranked alternatives. Determine which strategic properties the human move improves and whether some human reveals were informational rather than necessary.

**Gate:** the analyser produces stable, human-readable strategic explanations and does not contain deal-number-specific rules.

### Phase C — Generic strategic objective generator

Generate a small, diverse set of candidate macro objectives from the analyser rather than selecting a single preferred suit.

Candidate families:

- targeted reveal chain;
- create/recover space;
- same-suit consolidation;
- pre-stock shaping;
- preserve useful hidden structure;
- prepare multi-suit cascade;
- foundation removal when removal itself increases future freedom.

Each objective records estimated cost, expected structural benefit, stock epoch relevance and required tactical conditions.

**Gate:** the same objective library operates on arbitrary deals without special cases.

### Phase D — Tactical realisation using exact quotient search

Generalise the existing exact quotient machinery from corridor reconnection to strategic objectives.

The realiser should answer questions such as:

- cheapest way to expose this target card;
- cheapest way to create a recoverable empty column;
- cheapest way to reach one of several acceptable pre-stock receiver states;
- cheapest way to consolidate selected fragments.

Use exact search where tractable and bounded/heuristic realisation where exactness would be disproportionate, while retaining replay verification.

**Gate:** strategic objectives can be converted into concrete legal move sequences with measured cost and outcome.

### Phase E — First-solution anytime search

Search over strategic objective choices while the tactical layer realises them.

Primary goal: obtain a complete legal solution quickly on an arbitrary deal.

Use:

- beam/best-first/MCTS or another plan-level search;
- multiple strategic alternatives;
- stock-epoch planning;
- transposition and dead-state detection;
- incumbent capture as soon as any solve appears.

Do not wait for optimality before returning a useful answer.

**Gate:** previously unseen benchmark deals can produce replay-valid solutions without hand-coded deal logic.

### Phase F — Incumbent-guided improvement

Once an incumbent exists:

- enable global branch-and-bound;
- improve admissible lower bounds;
- search for cheaper strategic histories;
- use canonical/scaffold reconnections opportunistically;
- continuously archive every strict improvement.

The solver should naturally progress through better incumbents rather than run a separate unrelated optimiser.

**Gate:** the solver demonstrates monotonic incumbent improvement on benchmark deals under increasing compute budgets.

### Phase G — Optimality proof mode

For a strong incumbent, switch increasing effort toward proof:

- A*, IDA*, branch-and-bound or equivalent exact search;
- strong admissible abstractions / pattern databases;
- compact/disk-backed transposition when required;
- parallel exact expansion where deterministic correctness can be retained.

If all states capable of beating incumbent `U` are eliminated, `U` is proven optimal.

Report both best solution and best proven lower bound so an optimality gap is always visible.

Example:

`best known = 123; proven lower bound = 118; gap <= 5`

**Gate:** at least small/medium benchmark cases reach mathematically proved optimum.

### Phase H — Unsolvability proof

For deals with no incumbent:

- apply exact deadlock detection;
- quotient zero-cost equivalences;
- use transposition/dominance aggressively;
- exhaust the reachable state space when feasible.

If no solved state exists after complete exhaustion, the deal is proven unsolvable.

Otherwise report `unknown within resource budget` rather than claiming impossibility without proof.

### Phase I — General benchmark suite

After the architecture works on the primary benchmark, expand to a corpus containing:

- 1-suit, 2-suit and 4-suit deals;
- easy, difficult and known-unsolvable examples where available;
- deals with known human/solver scores;
- deals unseen during heuristic development.

Track:

- time to first solve;
- first-solve score;
- best score over time;
- proven lower bound;
- optimality gap;
- memory;
- states/quotient states expanded;
- whether result is solved, optimal, unsolvable, or unknown.

This phase is the protection against overfitting to deal 492515/4925153.

## Immediate next development work

Do **not** continue local corridor optimisation as the main programme.

The next implementation work should be Phase B: a perfect-information strategic analyser, beginning with two generic concepts that current code does not model deeply enough:

1. **downstream reveal value** — analyse the actual known chain beneath a face-down card and the structural opportunities it enables;
2. **space lifecycle / recoverability** — analyse not only how to create an empty column, but how it can be used, recovered, replaced, or carried through known future stock rows.

The first benchmark experiment should analyse the opening through the first stock deal and compare the human 172 route against all legal alternatives. This is diagnostic work: the goal is to learn what the present evaluation function fails to value, not to hard-code the human route.

In parallel, define the first generic admissible lower-bound API so every future search can use a known incumbent globally rather than only applying local corridor ceilings.

## Non-negotiable correctness rules

- `mobilityware_moves` is the optimisation metric; `legacy_mw` is forensic only.
- Every claimed solution must independently replay legally from the true deal.
- Automatic foundation removal remains zero cost.
- Stock deals cost one.
- A free empty-column relocation applies only to a complete fully open source column under the corrected rule.
- Every strict improvement must pass durable archive write and read-back replay.
- Heuristic estimates may order search, but only admissible bounds may prune branches in proof mode.
- Benchmark knowledge such as the 119 score must never become a hidden deal-specific rule in generic solver logic.

## Relationship to historical planner documents

`docs/layered_planner_development_plan.md` remains an important historical baseline. It captured the earlier five-layer human-style planner direction and drove useful dependency, campaign and tactical work. It is not deleted or rewritten.

This document supersedes it as the **forward strategic architecture** because subsequent work established:

- corrected move accounting;
- durable incumbent verification;
- exact free-column quotienting;
- a practical algebraic tactical engine;
- strong evidence that local optimisation of the 172 route is insufficient;
- credible leaderboard evidence that a 119 solution exists;
- a clarified requirement that the eventual solver generalise to arbitrary deals.

Historical experiments remain useful as evidence and reusable implementation assets, but new development decisions should be evaluated against this anytime, deal-independent architecture.