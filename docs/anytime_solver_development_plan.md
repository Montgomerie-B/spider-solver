# Anytime Spider Solver Development Plan

**Status:** Forward implementation plan; v0.14 source-completion propagation is verified, but selected-path conversion and the two-foundation gate remain partial
**Date:** 2026-08-30
**Architecture:** `docs/anytime_solver_architecture.md`  
**Primary benchmark:** MobilityWare 4-suit deal stored as `4925153` in the repository (leaderboard screenshot labels the same deal `492515`)  

## 1. Objective

Build a general perfect-information Spider solver that can:

1. analyse any legal 1-, 2- or 4-suit deal using full knowledge of hidden tableau cards and stock;
2. find a respectable complete solution quickly when one exists;
3. continue improving the incumbent as more compute is available;
4. use each incumbent as a global branch-and-bound ceiling;
5. eventually prove optimality where tractable; and
6. prove unsolvability only after exact exhaustion of the reachable state space.

The intended operating pattern is:

`analyse -> generate strategic options -> realise tactics -> first solve -> improve -> tighten bounds -> prove`

Deal 4925153 is the development benchmark, not the algorithm. No move, column, suit order, score, command number or hard-coded route from this deal may be embedded in generic strategy logic.

## 2. Why the plan changes now

Recent work substantially improved the tactical and proof machinery, but repeated local optimisation around the 172-move human route has not produced a better complete solution. Exact corridor searches have nevertheless been valuable because they established reliable accounting, state identity, quotienting and proof infrastructure.

The strategic model is now the main bottleneck.

Human play suggests that good Spider decisions are dominated by:

- exposing useful hidden cards rather than merely exposing as many cards as possible;
- making low-regret same-suit consolidations;
- creating empty columns;
- using empty columns as temporary working memory;
- recovering or replacing those spaces later;
- shaping the tableau to receive known future stock rows;
- building suit material before it is removable;
- removing foundations when removal improves the future tableau, not simply because a suit is currently closest to completion.

A perfect-information solver can do better than a human on these decisions because it knows every buried card and every future stock card in advance.

The benchmark evidence is also decisive. The project has a replay-verified 172 solution, the user's historical leaderboard best is 167, another leaderboard score is 154, and the recorded best is 119. The 119 route is not available, but its existence is credible benchmark evidence that the 172 route contains large strategic inefficiencies rather than merely a few isolated tactical inefficiencies.

## 3. Assets to preserve and reuse

The new development is additive. Existing correct infrastructure should be treated as reusable components rather than rewritten without cause.

### 3.1 Rules, state and replay

Reuse and keep stable unless an explicit correctness issue is found:

- `src/spider/engine.py`
- `src/spider/rules.py`
- deal loading/parsing
- canonical state representation
- replay validation
- corrected `mobilityware_moves` accounting

`legacy_mw` remains forensic only and must never control search, pruning, ranking or benchmark claims.

### 3.2 Existing strategic/planner work

The old layered planner is no longer the forward architecture, but it contains reusable components and diagnostics:

- `src/spider/planner/dependency.py`
- `src/spider/planner/plans.py`
- `src/spider/planner/scorer.py`
- `src/spider/planner/realizer.py`
- `src/spider/planner/controller.py`
- `src/spider/planner/plan_search.py`
- `src/spider/deal_analysis.py`
- historical human-solution analyser outputs and strategy notes

These modules should be mined, refactored or wrapped where useful. They must not dictate a deal-specific suit order or reproduce the human route by rote.

### 3.3 Exact tactical/proof machinery

Reuse the successful Opt011-Opt013 work:

- collision-safe structural state identity;
- exact 0-1 style corrected-cost search where applicable;
- free-column quotienting;
- algebraic quotient expansion;
- packed state representation;
- target-state compatibility checks;
- checkpoint/resume;
- compact transposition storage;
- exact corridor diagnostics.

The previous corridor work becomes a tactical/proof backend and a regression suite, not the main strategy.

### 3.4 Incumbent verification and archive

Preserve the external archive invariant:

1. candidate replays independently from the true deal;
2. every move is legal;
3. the game is solved;
4. corrected `mobilityware_moves` is recalculated independently;
5. the result is strictly better than the verified incumbent;
6. the candidate is written atomically to the external archive; and
7. the written move file is read back and independently replayed.

A result does not exist operationally until this pipeline succeeds.

### 3.5 Benchmark evidence

Use the following only as diagnostics/benchmarks:

- canonical 172 route and all canonical states;
- user's historical 167 leaderboard score;
- leaderboard 154 score;
- leaderboard 119 best score;
- exact negative corridor results;
- historical Solvitaire behaviour observed by the user: first solve often within minutes, then useful improvements over roughly the next 10-20 minutes before plateau.

None of this benchmark evidence may become hidden deal-specific strategy logic.

## 4. Solver architecture to implement

The implementation should keep three responsibilities distinct.

### Strategic planner

Chooses *what outcome to pursue next*.

Examples:

- expose a particular buried-card dependency chain;
- create a recoverable empty column;
- consolidate useful same-suit fragments;
- prepare a foundation candidate without necessarily removing it;
- shape the tableau for the exact next stock row;
- preserve a hidden region because its cards are not yet useful;
- prepare a multi-suit cascade;
- remove a foundation because the resulting space/freedom is valuable.

### Tactical realiser

Chooses *how to achieve a strategic objective legally and cheaply*.

This should reuse exact quotient search where tractable and bounded heuristic search where exact realisation would be disproportionate.

### Proof/optimisation engine

Answers *whether a branch can still beat the incumbent* and eventually *whether the incumbent is optimal*.

Only admissible lower bounds may eliminate branches in proof mode.

## 5. Strategic analysis model

Phase 1 development should produce a single generic `StrategicAnalysis` view of any state. It should expose the following independent but interacting analyses.

### 5.1 Foundation-removal feasibility map

This becomes a primary strategic compass.

#### Static theoretical availability

Before search begins, compute for each suit and each of its two possible K-A foundations:

- which stock epoch first contains enough copies of every required rank for that foundation to exist in theory;
- therefore the earliest stock epoch at which removal is possible;
- foundations that are impossible before particular stock deals because required cards remain in future stock.

This is a hard availability constraint, not a heuristic.

#### Dynamic practical feasibility

At each state, for every theoretically available foundation candidate, estimate:

- required cards currently exposed;
- required cards buried and their dependency chains;
- existing same-suit fragments;
- number and quality of joins still required;
- blockers that must move;
- empty-column requirements;
- likely space consumption/recovery;
- interaction with the next known stock row;
- structural value of removing the sequence now.

The output should be a **removal frontier**, not a single fixed suit order.

The planner may maintain several plausible foundation schedules simultaneously. A schedule is guidance, not a hard commitment; a reveal or new space can change the best order immediately.

#### Build readiness versus removal readiness

Track these separately.

A suit can be strategically valuable to consolidate even when a missing card in later stock makes removal impossible. Compact same-suit material can reduce tableau complexity and be carried efficiently through later stock epochs.

### 5.2 Reveal dependency and downstream unlock analysis

For each current face-down frontier and buried card of strategic interest, compute:

- known card(s) beneath the frontier;
- minimum known blocking material above them;
- available destinations for blockers;
- whether space is required;
- subsequent cards made reachable if the line is pursued;
- same-suit joins enabled;
- spaces created or destroyed;
- foundation candidates advanced;
- stock-reception effects;
- approximate paid move cost.

A reveal has no information value to the machine. It should be pursued only for structural value.

Do not encode a generic King penalty. A King is evaluated by its actual downstream consequences, including whether consuming a space unlocks more valuable material and whether another space can later be recovered.

### 5.3 Space lifecycle / recoverability analysis

Model empty columns as strategic resources with a lifecycle:

`create -> use -> occupy -> recover/replace -> carry through stock -> reuse`

For each plausible empty-column opportunity calculate:

- apparent cost to create;
- whether occupation is temporary or effectively permanent;
- useful manipulations enabled while free;
- route to recover the same space;
- route to create a replacement space;
- expected state after the next stock deal;
- whether the incoming stock card on that column has a known immediate destination and therefore makes the space cheaply recoverable;
- whether using the space enables another foundation/reveal/space campaign.

Raw empty-column count is not enough. The planner needs **effective workspace** and **recoverability**.

### 5.4 Known-stock reception analysis

For each remaining stock row:

- know the exact ten incoming cards and destination columns;
- score current/pre-deal column endings for useful same-suit or rank connections;
- identify incoming cards that can be moved immediately;
- identify columns that should be short, empty or structurally prepared before the deal;
- identify opportunities where a stock card unlocks/recreates a space;
- identify suit fragments that should be built before the deal so the incoming row completes or advances them.

The strategic question is not simply `deal now?`; it is:

> what low-cost tableau should we prefer immediately before this exact row is dealt?

### 5.5 Admissible lower-bound interface

Define a generic API such as:

`lower_bound(state, objective=None) -> LowerBoundBreakdown`

Initial safe components should include:

- remaining face-down cards that must still be exposed;
- remaining mandatory stock deals;
- proven target-adjacency/breakpoint bounds where applicable;
- proven disjoint structural requirements.

Do not sum bounds unless additivity is proved. Conservative `max(...)` combinations are preferable to an unsafe stronger-looking bound.

For a complete-solution search with incumbent `U`, prune only when:

`g(state) + h(state) >= U`

For an explicit benchmark target such as 119, an experimental target-bounded search may use 119 as the ceiling, but the number must remain an input/benchmark parameter rather than generic solver logic.

## 6. Development phases and gates

### Phase 0 - Documentation and baseline alignment

**Work**

- adopt `docs/anytime_solver_architecture.md` as the forward architecture;
- adopt this file as the forward implementation plan;
- retain `docs/layered_planner_development_plan.md` as historical baseline;
- update root/planner README pointers and benchmark status;
- preserve Opt011-Opt014 experiment records as historical evidence.

**Gate**

Repository contains one unambiguous current architecture and one unambiguous current development plan.

### Phase 1 - Perfect-information strategic analyser

Implement the four strategic analyses plus lower-bound API described in section 5.

Suggested new modules under `src/spider/planner/`:

- `strategic_analysis.py` - aggregate state analysis;
- `foundation_feasibility.py` - static/dynamic removal frontier;
- `reveal_graph.py` - downstream reveal/dependency analysis;
- `space_lifecycle.py` - workspace creation/recovery analysis;
- `stock_reception.py` - known-stock pre/post-deal analysis;
- `lower_bounds.py` - admissible bound interface.

Existing modules may be reused/refactored instead where that is cleaner, but public responsibilities should remain clear.

**Diagnostics**

Produce human-readable reports for:

- initial benchmark state;
- every canonical state immediately before a stock deal;
- selected states immediately after a stock deal;
- a small set of unseen test deals.

**Gate**

The analyser is deal-independent, deterministic, explainable and covered by tests. It correctly reports hard foundation availability by stock epoch and can explain meaningful reveal/space opportunities without using the canonical route as an instruction set.

### Phase 2 - Strategic objective generation and evaluation

Build a small portfolio of candidate objectives from `StrategicAnalysis`.

Objective families:

- targeted reveal chain;
- create/recover workspace;
- permanent/low-regret consolidation;
- foundation-build campaign;
- foundation-removal campaign;
- pre-stock receiver shaping;
- multi-suit cascade preparation;
- deliberate postponement of low-value work.

Each objective should record:

- preconditions;
- target predicate;
- estimated paid cost;
- expected structural gain;
- stock epoch relevance;
- foundation/removal relevance;
- space effects;
- uncertainty/confidence of the estimate.

Keep several competing objectives. Never reduce the strategy to a single suit order.

**Human-trace diagnostic**

At canonical benchmark states, generate the legal alternatives and record where the human move/objective ranks. When the human move ranks poorly, inspect which structural property is missing from the evaluation. This is diagnostic calibration, not imitation learning.

**Gate**

The objective generator produces a small, diverse and sensible candidate set on both the benchmark and unseen deals. No benchmark-specific special cases.

### Phase 3 - Tactical realiser integration

Give each strategic objective a target predicate and ask the tactical engine to reach it cheaply.

Reuse:

- algebraic zero-cost quotient expansion;
- packed state representation;
- transposition/checkpoint machinery;
- legacy move ordering where useful;
- bounded beam/best-first search as a fallback.

Support two modes:

1. **fast realisation** - bounded approximate route to support first-solve search;
2. **exact realisation** - cheapest route/proof where the tactical subproblem is small enough.

**Gate**

Representative strategic objectives from initial and mid-game states can be converted into replay-valid legal subsequences with measured corrected cost.

### Phase 4 - Anytime first-solution controller

This is the first major product milestone.

Search primarily over strategic objective sequences, not raw moves. Raw move search remains inside the tactical realiser.

Controller responsibilities:

- maintain a beam/frontier of strategically distinct states;
- select/continue/switch objectives;
- decide when to take the next stock deal using known-stock reception and future opportunity;
- preserve diversity so one early suit hypothesis does not dominate every branch;
- detect transpositions/dead states;
- archive the first complete solution immediately;
- continue running after first solve.

**Performance target (engineering target, not proof claim)**

On contemporary consumer hardware, including the project's Optiplex-class machine, aim for a reliable first complete solution on ordinary solvable 4-suit deals in minutes rather than hours. On the primary benchmark, the first objective is simply to solve from scratch without using the 172 route as a prefix. Once that is reliable, drive first-solve time and score down.

**Benchmark milestones**

- M1: solver-generated complete solution, any score;
- M2: solver-generated solution <=172;
- M3: <172, first genuine project improvement;
- M4: <=167, reach user's historical level;
- M5: <=154, demonstrate materially better strategic play;
- M6: approach 119.

These are benchmark milestones only, not generic thresholds.

**Gate**

The solver can solve previously unseen deals from scratch and return the first incumbent without waiting for optimality.

**Verified v0.1 status (2026-08-26): gate not met.** A separate generic
strategic controller now provides replay-verified multi-action edges, first-class
deal timing, full post-edge reanalysis, credits 0–4, diverse successor retention,
exact lower-`g` transposition dominance, proof-safe incumbent budgeting and
bounded telemetry. The active benchmark profile explicitly has Unrestricted Deal
ON. In bounded prospective runs the controller reached every stock epoch but no
foundation, exhausted 80,000 tactical nodes after 55–56 strategic expansions and
found no complete solution. The immediate blocker is unbounded-per-expansion
actionability probing plus stock-heavy priority, not a rules discrepancy. See
`docs/anytime_whole_game_controller_v0_1.md`. Phase 4 remains in progress.

**Verified v0.2 status (2026-08-27): controller-resource gate passed; whole-game
gate not met.** Actionability now has fixed normalized shallow/modest/broad
tiers, an independent per-expansion node/time/count allowance and exact
state/project/predicate/tier cache semantics. Direct work, protected credible
foundation macros and Deal are admitted before uncertain probes. Exact
post-Deal economic/measurement facts are reused only under matching structural
identity and analysis fingerprint; incumbent budgets remain fresh. Transparent
strategic progress excludes stock count/epoch, and the result reports best
progress, lowest cost and deepest stock separately.

Gate A generically removed the first Spade foundation from the legal cost-11
state at added cost 12. Gate B reduced campaign MUST burden and rehandling debt
from the legal cost-23 state without consuming stock. A true-opening gate used
1,431 tactical plus 2,924 separately accounted probe nodes in 12 expansions,
versus v0.1's 20,008 charged tactical nodes in 19 smoke expansions, and no
longer selected the stock-empty disaster as best. Bounded production/research
runs still found no foundation or solution from the true opening. Their best
state had stock 30 and 39 face-down cards; their deepest-stock state was
reported separately. The remaining blocker is generic campaign continuity plus
non-interruptible full economic/deal-timing analysis, not probe exhaustion or a
rule discrepancy. See `docs/anytime_whole_game_controller_v0_2.md`. Phase 4
remains in progress; do not start score tuning until a true-opening foundation
and first complete solution are reliable.

**Verified v0.3 status (2026-08-27): true-opening foundation gate passed;
whole-game gate not met.** A generic two-epoch campaign corridor now preserves
live campaign identity across Deal, revalidates the whole portfolio after each
step, permits interchangeable physical-source substitution, and gives one
credible lane protected opportunity before generic stock/raw branches. From
the untouched benchmark with `incumbent=None`, no route/suit seed and
Unrestricted Deal ON, it deterministically removed the first Spade foundation
at corrected cost 21 in 21 actions, two Deals, two strategic expansions and
1,875 tactical nodes. Independent replay, repeatability, path hash and endpoint
hash all passed. This prospective result was frozen before comparison with the
separate legal cost-23 checkpoint.

Controller analysis is now staged: every generated child receives exact cheap
Stage-0 facts, fresh bounded strategic-core facts are computed before
expansion, and full Deal timing/corridor/probe work is optional Stage 2. Exact
analysis reuse requires canonical state plus analysis/rule fingerprint, while
incumbent budgets remain fresh. A cooperative monotonic deadline and inner
campaign-beam checks reduced observed bounded-run overruns to 0.862 seconds on
a 15-second continuation and 0.124 seconds on the single 120-second production
attempt, versus v0.2's 9.05/19.42-second overruns.

The machine-generated post-foundation continuation retained stock 30 while
reducing face-down cards 33 to 27 and total campaign MUST burden 26 to 21, but
did not remove a second foundation. The single authorized whole-game attempt
stopped at 120.124 seconds with one foundation, 24 face-down cards, empty
stock, and no solution. Phase 4 therefore remains in progress. The next gate
is generic current-epoch residual-campaign conversion to a second foundation;
score tuning remains premature. See
`docs/anytime_whole_game_controller_v0_3.md`.

**Verified v0.4 status (2026-08-27): residual-conversion gate partial; two-
foundation and whole-game gates not met.** A new generic residual-campaign
layer now represents next-foundation readiness, exact next-row opportunity,
foundation checkpoint profiles, bounded checkpoint diversity, Deal purpose
and investment between consecutive removals. Distinct checkpoint states are
retained by transparent dimensions rather than immediate `g` alone; exact
structural-state/lower-`g` TT dominance and the established admissible proof
bound remain unchanged.

Under one frozen 90-second configuration, the cost-21 checkpoint improved
face-down cards `33 -> 27` and MUST burden `26 -> 21` without consuming stock,
whereas the cost-23 checkpoint improved face-down cards `32 -> 27` but consumed
one row and increased MUST burden to 30. Neither removed foundation #2. The
unseeded untouched-opening 180-second gate independently rediscovered the
cost-21 Spade foundation, then reached `g=72`, face-down 25, same-suit mass 42
and stock empty without another removal. Independent replay passed; wall
overrun was 0.591 seconds. The run generated 22 residual lanes, realised 11,
and recorded 20 bounded conversion failures. Only one distinct first-
foundation checkpoint was discovered and retained.

Per the hard gate, repeatability, third-foundation continuation and a new
whole-game run were not started. Phase 4 remains in progress. The verified
blocker is terminal conversion: bounded residual lanes improve structure but
do not expose and assemble the remaining campaign sources into foundation #2
before stock-advance branches take over. The next task should propagate
transparent stock-purpose evidence to all Deal successors, protect a
current-epoch lane until a removal-relevant milestone is reached or
invalidated, and diversify pre-foundation search enough to discover distinct
checkpoint geometries. It should remain bounded and generic; no longer search
or benchmark weight tuning is justified. See
`docs/anytime_whole_game_controller_v0_4.md`.

### Phase 5 - Incumbent-guided improvement

Once any solution exists, turn the entire run into optimisation rather than launching a disconnected optimiser.

- load verified incumbent globally;
- apply `g+h>=U` pruning wherever `h` is admissible;
- keep multiple strategic histories alive;
- search alternative foundation schedules, reveal plans and space lifecycles;
- use canonical/scaffold reconnection when available, but never require it;
- run local exact optimisation only where strategic analysis identifies a promising subproblem;
- archive every strict improvement.

The desired runtime behaviour is Solvitaire-like but stronger:

- first solution quickly;
- several meaningful improvements over the next minutes;
- diminishing returns thereafter;
- exact/proof machinery continuing after heuristic improvements plateau.

**Gate**

On a benchmark suite, longer compute budgets yield non-increasing best scores and increasingly strong lower bounds.

### Phase 6 - Stronger admissible bounds and proof search

Develop proof-quality heuristics separately from heuristic strategic scoring.

Candidates:

- target adjacency/breakpoint bounds;
- disjoint reveal requirements;
- stock/foundation availability constraints;
- pattern databases over selected card/column abstractions;
- structural matching bounds;
- exact target-state distances for compact subproblems.

Then integrate A*, IDA*, branch-and-bound or an equivalent exact framework.

Report:

- incumbent score;
- proven lower bound;
- optimality gap;
- nodes/states expanded;
- memory/time.

**Gate**

Small/medium cases can be proven optimal, and the proof path never relies on non-admissible heuristic scores.

### Phase 7 - Unsolvability proof

For deals where heuristic search finds no solution:

- exact deadlock detection;
- quotient zero-cost equivalences;
- dominance/transposition;
- exhaustive reachability when feasible.

Only report `proven unsolvable` after exhaustive exact closure. Otherwise report `unknown within resource budget`.

### Phase 8 - General benchmark corpus and overfitting protection

Build a corpus containing:

- 1-suit, 2-suit and 4-suit deals;
- easy, medium and hard solvable examples;
- known-unsolvable examples where available;
- deals with external/human scores;
- unseen holdout deals not used during heuristic tuning.

Track at minimum:

- first-solve time;
- first-solve score;
- best score at 1, 5, 15, 30 and 60 minutes where practical;
- proven lower bound;
- optimality gap;
- peak RSS;
- raw and quotient states expanded;
- solve/proof status.

No strategic change should be accepted solely because it improves deal 4925153.

### Phase 9 - Performance and parallelisation

Only after strategic quality is demonstrated:

- profile hot paths;
- parallelise independent strategic branches/restarts;
- improve packed-state and successor throughput;
- consider C++/Rust/C extensions for proven bottlenecks;
- retain deterministic replay/proof invariants.

Do not use low-level optimisation to compensate for a poor strategic model.

## 7. Immediate development sprint

Controller v0.8 now allocates the existing tactical budget from each fresh
campaign critical path. The scheduler distinguishes closure, receiver,
interval, overlay, supply, construction, excavation, workspace, removal, Deal
and fallback demand; grants PROBE, SHALLOW, COMMITTED or TERMINAL tranches;
and promotes only named structural return. Repeated misses are remembered only
for the exact state/objective/realiser/blocker context and have no proof
authority.

A fresh profile confirmed that v0.7 current-epoch/removal work consumed about
75% of a 30-second sample. In the accepted v0.8 policy, an explicit
prerequisite gates current-epoch, removal and corridor execution. The cost-21
Gate F reached its 25-expansion ceiling in 16.963 seconds, compared with six
expansions in 90.007 seconds for v0.7. The authorized untouched Gate G reached
all 50 expansions in 35.444 seconds, compared with nine in 181.863 seconds.
Gate G granted 27.8 tactical seconds but consumed 3.069, retained 56 generic
construction opportunities and recorded 238 named harvest events. The fixed
runtime and node ceilings, unrestricted rules, exact TT and admissible bound
are unchanged.

The result remains partial. Gate F retained its existing Spades foundation but
did not remove F2. The untouched Gate G did not remove F1; its leading Spades
campaign had one shallow compulsory source and no overlay, but still lacked
the K, J-8 and A intervals when the 50-expansion ceiling arrived. The next
authorized sprint should therefore convert harvested primitive
closure/construction work into a continuous interval-building milestone and
terminal qualification, without restoring expensive whole-campaign setup or
increasing any budget. See `docs/anytime_whole_game_controller_v0_8.md`.

### Verified v0.14 status

Controller v0.14 diagnoses and corrects the v0.13 source-completion boundary.
Fresh closure analysis now emits a typed, exact-state-provenanced
`SourceCompletionEvent`; the fact crosses dependency closure, milestone
primitive/residual, strategic successor/node, target lineage and bounded
telemetry. Physical card identity is separated from location, semantic
requirements are separated from interchangeable physical copies, and
`SOURCE_BURIED -> SOURCE_EXPOSED_BUT_BLOCKED` completes the original buried
predicate while retaining the distinct follow-on blocker. No satisfied
requirement may silently reopen.

Trace completion, exact-TT controller admission, fresh-residual preservation,
lineage preservation and selected-path completion are counted separately.
Repeated analysis merges event stages and cannot double count or erase later
admission. Exact state remains authoritative; all history is proof-neutral and
excluded from TT identity. The three-expansion persistence envelope, allocator
tiers, closure limits, beam, controller limits, unrestricted rules and
admissible bound are unchanged.

All generic capability Gates A-K pass. The focused v0.14 suite adds 72 passing
cases. Two unseen deterministic four-suit smokes retained legal replay and
unrestricted raw/Deal/construction coverage; one naturally produced a typed
source-completion successor.

Natural Gate O used the exact 90-second/25-expansion/300,000-node/
frontier-256/beam-192 cost-21 envelope. It reached all 25 expansions and a
replay-valid total `g=26`, F1, stock 30 and 32 face-down endpoint. Five natural
trace source completions became five controller-admitted and five
lineage-preserved completions, with no residual reopening or attribution loss.
None reached the selected route or source consumption, and F2 remained absent.
Its 24 expiry boundaries classified as six completed-before-expiry, eight
legitimate no-progress and ten resource-limit.

That durable controller admission authorized untouched Gate P. Under the exact
180-second/50-expansion/500,000-node/frontier-256/beam-192 envelope it reached
two substantial interval milestones but no foundation. One Hearts source
completion produced a successor and lineage evidence but was rejected at
strategic admission; the selected replay-valid route ended at corrected
`g=11`, stock 40 and 38 face-down. The verified verdict is PARTIAL.
Repeatability, F3 and whole-game runs were not authorized.

The remaining blocker is post-admission selection and next-expansion
continuity, not missing source metadata. A later explicitly authorized task
should compare the exact structural economics and priority of admitted
completion states with their equal/lower-cost competitors and audit a bounded
completion representative without increasing resources or persistence,
weakening exact TT, tuning the benchmark or beginning the global scheduler.
See `docs/anytime_whole_game_controller_v0_14.md`.

The definitive complete repository suite passed 1,316 ordinary tests with the
same 37 historical expected-invalid xfails and one inherited warning in
1,110.34 seconds.

### Verified v0.13 status

Controller v0.13 confirms that v0.12's coordinate-free semantic target crossed
the outer milestone boundary while the v0.8 allocator's earned evidence did
not: an exact-state change restarted an otherwise valid, progressed target at
`PROBE`. The correction adds proof-neutral target-grant lineage. Only named,
target-specific harvest can retain or promote the next bounded opportunity;
misses, contradiction, supersession, uncompensated debt and expiry decay or
reset it. `TERMINAL` still requires fresh qualification. No unused grant is
carried and all tier, per-expansion, controller, closure, beam and proof limits
remain unchanged.

All generic capability Gates A-K pass. The focused v0.13 suite adds 65 passing
cases and the combined v0.8-v0.13 controller cohort passes 385. Two unseen
four-suit smokes retain unrestricted Deal, raw/Deal/construction coverage and
legal replay.

Natural Gate M used the exact cost-21 90-second/25-expansion/300,000-node/
frontier-256/beam-192 envelope. It reached all 25 expansions in about 23.4
seconds and selected the same replay-valid added-`g=5` endpoint at total
`g=26`, F1, stock 30 and 32 face-down cards. It demonstrated retained
`SHALLOW`/`COMMITTED` target opportunities and execution of a formerly lost
same-target next-action class, authorizing untouched Gate N under condition 5.
It still produced zero actual source exposures/consumptions, no substantial
source-chain completion, no terminal qualification and no F2.

Gate N started untouched under the exact 180-second/50-expansion/500,000-node/
frontier-256/beam-192 limits. It reached 50 expansions and two substantial
interval milestones, but no source exposure, F1 or F2. The verified verdict is
PARTIAL; repeatability, F3 and whole-game runs were not authorized. A later
explicitly authorized task should trace why executed retained candidates still
expire or turn over before controller-level named-source exposure, without
increasing resources or beginning the global scheduler. See
`docs/anytime_whole_game_controller_v0_13.md`.

The definitive complete repository suite passed 1,244 ordinary tests with the
same 37 historical expected-invalid xfails and one inherited warning in
1,146.43 seconds.

### Verified v0.12 status

Controller v0.12 distinguishes completion of the specifically requested
dependency from useful advancement. A buried source is completed immediately
when fresh physical analysis exposes it, including the case where the same
semantic dependency ID survives as `SOURCE_EXPOSED_BUT_BLOCKED`. Advanced
receiver, workspace, park, depth, stable-rearrangement and copy-substitution
states continue inside the unchanged closure envelope; the best replay-valid
advanced endpoint survives as fallback when that envelope ends.

Cumulative completion-first endpoint ordering, explicit midpoint/final
lifecycle debt, restore/replace obligations, and outer milestone continuation
metadata are ordering and diagnostics only. Exact TT, admissible bounds,
Unrestricted Deal ON, raw/Deal/construction coverage, and all controller,
closure, beam, milestone and allocator limits are unchanged.

All generic capability Gates A-J pass. The focused v0.12 suite adds 73 passing
cases, and the combined v0.7-v0.12 controller cohort passes 366 tests. Two
unseen deterministic four-suit smokes retained legal replay; one naturally
exposed a named source in a three-primitive local chain.

The natural cost-21 Gate K used the exact 90-second/25-expansion/300,000-node/
frontier-256 envelope and stopped at the expansion ceiling after 22.970
seconds. Its replay-valid five-action, added-`g=5` suffix retained F1, stock 30
and 32 face-down cards. Across 38 targeted calls it recorded 35 advanced
fallbacks, two completed dependencies, 35 inside-call continuations and 11
outer-boundary persisted targets. It nevertheless converted three natural
source-depth reductions into zero source exposures/consumptions, zero
substantial source-chain completions, zero terminal qualifications and no F2.
Gate L was not authorized. The verified hard-gate verdict is FAIL.

The definitive complete repository suite passed 1,179 ordinary tests with the
same 37 historical expected-invalid xfails and one inherited warning in
1,137.10 seconds.

The remaining blocker is natural target completion after persistence, not
generic completion detection. A later explicitly authorized task should audit
the exact next-candidate sets for the 11 persisted targets, especially after
bounded parks and stable breaks, without increasing resources or starting a
global scheduler. See `docs/anytime_whole_game_controller_v0_12.md`.

### Verified v0.11 status

Controller v0.11 adds a bounded, typed autopsy for the existing named
`SOURCE_BURIED` closure path. The tactical demand's exact dependency identity
now reaches closure and its cache key. Fresh physical-source enumeration and
progress attribution recognize direct blocker removal, receiver/workspace
prerequisites, bounded parks and interchangeable source copies. Local beam
retention preserves progress-class diversity inside the unchanged width. All
facts remain ordering/diagnostic evidence; exact TT, admissible bounds,
Unrestricted Deal ON and all v0.8-v0.10 resource envelopes are unchanged.

All generic capability Gates A-I pass. The original receiver-prerequisite
failure now executes a permanent receiver join, moves the blocker and closes
the named source with independent replay. The natural cost-21 Gate J used all
25 expansions and ended replay-valid at total corrected `g=26`, F1, stock 30
and 32 face-down cards. Its 31 buried-source attempts contained 286 legal
target-relevant candidates, 500 generated candidates, zero generator misses
and zero beam discards. It executed 15 receiver prerequisites, 10 source-depth
reductions and 32 bounded parks, but exposed/consumed zero named sources and
reached neither substantial completion, terminal qualification nor F2.

The definitive complete repository suite passed 1,106 ordinary tests with the
same 37 historical expected-invalid xfails and one inherited warning in
1,169.60 seconds.

The exact v0.10 2/3 residual had no committed replayable artifact, so it was
not reconstructed. Gate K was not authorized. The verified verdict is
PARTIAL. The next task is to audit why natural multi-primitive closure returns
after prerequisite/depth progress instead of carrying the same fresh named
source through exposure/consumption, especially across stable-run
restore/replace compensation and the outer milestone primitive boundary. Do
not widen budgets or begin a global scheduler. See
`docs/anytime_whole_game_controller_v0_11.md`.

### Verified v0.10 status

Controller v0.10 adds coordinate-free semantic target identity, fresh residual
predicate rebuilding, blocker-to-existing-realiser actionability and persistent
post-Deal obligations. It separates primitive results, transition checkpoints,
substantial structural milestones and foundations, so stock movement cannot
self-award structural completion. Exact state identity, lower-corrected-cost TT
dominance, proof bounds, search ceilings and Unrestricted Deal ON are unchanged.

All eight capability gates pass. The 52 focused v0.10 tests and the combined
194-test v0.10-through-v0.7 controller cohort pass. Natural cost-21 Gate I used
all 25 strategic expansions and selected a replay-valid added-`g=3` route with
no Deal, retaining its existing foundation, stock 30 and 32 face-down cards.
Across the frontier it recorded four blocker transitions, 22 primitive
outcomes, two transition checkpoints, no substantial milestone and no terminal
qualification. Its real tableau progress with less transition-driven stock
authorized Gate J under condition 5.

Untouched Gate J used all 50 unchanged strategic expansions and selected a
replay-valid corrected-`g=8` route ending at stock 40 and 38 face-down cards.
Across its frontier it recorded two substantial interval outcomes without
counting one-action joins or Deals as substantial. The selected source-chain
target survived two primitives but remained actionable at two of three scoped
requirements with buried-source debt; its post-Deal obligation was not falsely
credited as converted. It removed no foundation.

The final complete repository run passed 1007 ordinary tests with the same 37
historical expected-invalid xfails and one existing warning in 1146.78 seconds.

The verified verdict is PARTIAL. F2 is absent, so repeatability, F3 and the
whole-game continuation are not authorized. The precise next task is to audit
why the existing dependency-closure realiser cannot consume the final
`SOURCE_BURIED` requirement exposed by fresh analysis inside the unchanged
envelope. Do not increase budgets, tune benchmark weights, start v0.11 or begin
the global scheduler automatically. See
`docs/anytime_whole_game_controller_v0_10.md`.

### Verified v0.9 status

Controller v0.9 adds bounded, inspectable strategic milestones above the v0.8
tactical allocator and duplicate-aware stock-epoch analysis. Milestone
continuity is ordering context only; the exact TT remains structural state to
lowest corrected `g`, and current-epoch blocks and bounded conversion misses
have no proof authority. Pre-Deal work is classified against the exact next
row, and a selected purposeful Deal records its material/economic reason and
requires fresh post-Deal milestone analysis. Unrestricted Deal remains ON.

The 50 focused v0.9 capability tests pass. A wider targeted cohort passed 428
ordinary tests with the same 37 historical expected-invalid xfails. Natural
cost-21 Gate H reached all 25 expansions in 18.845 seconds, achieved 13
milestones across the explored frontier and selected three purpose-audited
Deals, but retained only its existing foundation. This authorized the untouched
Gate I. After recording epoch transitions as achieved strategic checkpoints,
Gate I selected a replay-valid `g=24` route with five purpose-audited Deals at
actions 10, 13, 15, 18 and 22 instead of the v0.8 stock-50/no-Deal route. It
reached all 50 expansions in 44.259 seconds and used 654 tactical nodes under
the unchanged 500,000-node/180-second ceilings. It removed no foundation.

The final complete repository run passed 955 ordinary tests with the same 37
expected-invalid xfails and one existing warning in 1120.21 seconds.

The verified verdict is PARTIAL. The no-Deal failure is corrected, but fresh
same-target interval/source-chain actionability still fails to reach terminal
qualification. Do not increase budgets, tune benchmark weights, start v0.10 or
begin the full scheduler automatically. See
`docs/anytime_whole_game_controller_v0_9.md`.

### Historical v0.7 status

Controller v0.7 now preserves objective-specific structural investment across
fresh state analysis. Successful dependency closure can issue bounded
same-campaign continuation credit, and the strategic portfolio explicitly
retains an alternate campaign, durable run construction, Deal,
workspace/reveal work and broad raw play. Supply contracts are scoped to their
smallest coherent critical subset; supporting and optional assets no longer
block fulfilment. Campaign closure exposes a downstream-unlock critical path.
The first whole-deal construction view records durable joins, independent build
and removal horizons, exact future free-join deferral, receiver/workspace
conflict and a structural balance sheet. All of these additions are ordering
and coverage evidence only.

The v0.7 capability gates are verified. In the natural cost-21 Gate E, a
selected Hearts closure closed ordering/receiver dependencies and was followed
by a permanent Hearts join; Diamond #1 reached a two-source critical path and
coherent supply contracts fulfilled. This authorized one untouched 180-second
run. That Gate F remained replay-valid but ended at corrected `g=53`, one
foundation, stock 20 and 27 face-down cards after only nine strategic
expansions. Foundation #2 was not removed, so repeatability and later optional
gates were not run.

The next sprint should address bounded tactical resource allocation after a
harvested continuation. Current-epoch/removal realisers should not repeatedly
consume most of the deadline while fresh analysis still identifies a concrete
receiver, interval or overlay bottleneck. Allocate the existing fixed budget
to the selected high-downstream-unlock closure or construction step, without
adding a new search engine, increasing benchmark limits, or changing proof
semantics. See `docs/anytime_whole_game_controller_v0_7.md`.

### Historical v0.6 status

The original Phase 1A work below has been completed by the subsequent strategic
analysis sprints. Controller v0.6 now distinguishes delivered stock supply from
campaign consumption, follows physical/substituted supply provenance, builds a
deterministic dependency graph for one named campaign, and runs a bounded
same-epoch dependency/overlay closure before another Deal where appropriate.
It retains v0.5's purpose contracts, protected conversion, terminal predicate
and pre-foundation diversity. These changes are ordering/coverage only and
preserve exact TT and admissible-bound safety.

The capability is verified. Generic fixtures held a delivered-only contract at
partial, fulfilled it only after integration, and independently replayed a
named overlay closure without a Deal. In the 90-second cost-21 diagnostic,
closure consumed supplied assets, closed 18 dependencies and cleared five
overlays. Two deterministic unseen deals passed unrestricted preflight and
legal bounded smokes. This evidence authorized one untouched opening run under
the unchanged v0.5 envelope.

The untouched result remains partial: Spades was removed at corrected `g=21`,
but the replay-valid selected prefix ended at `g=72` with one foundation, empty
stock, 25 face-down cards and MUST burden 28. The run took 180.570 seconds,
performed nine strategic expansions and 59,705 tactical nodes, and did not
remove foundation #2. Supply/closure successes occurred on alternative lanes
without becoming a durable selected campaign; zero multi-asset supply contracts
were fully fulfilled before later stock transitions.

The next authorized sprint should improve strategic admission and continuity
for successful same-campaign closure descendants, plus dependency
source/receiver ordering and realistic multi-asset obligation scoping. It must
retain the current benchmark weights, runtime, unrestricted rule profile and
proof semantics. Do not begin that sprint without explicit authorization. See
`docs/anytime_whole_game_controller_v0_6.md`.

### Historical Phase 1A plan

Begin with **Phase 1A: foundation-removal feasibility** because it supplies a high-level goal structure for the rest of the analyser and is largely deterministic.

### Sprint 1A deliverables

1. Create a generic foundation availability table from the full deal:
   - for every suit;
   - for foundation copy 1 and 2;
   - earliest stock epoch at which all required ranks are in play in theory.
2. Add dynamic analysis for the current state:
   - available required cards;
   - buried required cards;
   - current same-suit fragments;
   - blocker/reveal dependencies;
   - preliminary space requirement;
   - build-readiness and removal-readiness separately.
3. Emit a human-readable `removal frontier` diagnostic rather than a fixed suit order.
4. Run it on:
   - initial benchmark state;
   - pre-deal canonical checkpoints;
   - at least one unrelated deal fixture.
5. Add tests proving:
   - a foundation is never reported removable before all required ranks have entered play;
   - duplicate cards are handled correctly;
   - two foundations of one suit require two copies of every rank;
   - later stock cards correctly delay theoretical availability;
   - no benchmark deal number/column assumption exists in the implementation.

### Sprint 1A gate

We can answer, for any deal and any stock epoch:

- which foundations are impossible yet for hard card-availability reasons;
- which are theoretically possible;
- which are practically attractive to build/remove from the current tableau;
- why.

After this gate, implement reveal graph and space lifecycle next, then combine them into the first full `StrategicAnalysis` object.

## 8. Development discipline

- Keep changes modular and reviewable.
- Prefer new generic modules over editing legacy experiment code.
- Preserve old experiment outputs and historical docs.
- Add regression tests before long searches.
- Do not run multi-hour searches until the relevant phase gate is satisfied and a shorter benchmark demonstrates the intended effect.
- Record exact negative results as closures; do not repeatedly reopen them without new evidence.
- Heuristics may order and prioritise; proof pruning requires admissibility.
- Corrected MobilityWare scoring and archive verification are non-negotiable.

## 9. Definition of success

### Near term

A generic perfect-information analyser that can explain foundation timing, reveal value, workspace and stock reception better than the current flat heuristics.

### Medium term

A solver that reliably finds respectable full solutions in minutes and then improves them iteratively under a tightening incumbent ceiling.

### Long term

A high-performance general Spider solver that can approach record-quality solutions, prove optimality on tractable deals, and prove unsolvability where exact exhaustion is feasible.

The benchmark deal is successful when the solver reaches progressively better scores because the general architecture improved - not because a route for that deal was encoded by hand.
