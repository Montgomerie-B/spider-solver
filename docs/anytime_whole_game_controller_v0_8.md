# Anytime Whole-Game Controller v0.8

**Status:** PARTIAL — tactical allocation is effective and the fixed expansion gates are saturated quickly, but the untouched run does not remove a foundation

**Date:** 2026-08-29

**Authoritative base:** `966bf7364b2f0c2485c945e0ab8cbc30ffe51a1c`

**Branch:** `agent/anytime-whole-game-controller-v0-8`

## Inherited verification and rule profile

Before implementation, the complete inherited v0.7 suite passed with 859
ordinary tests, 37 expected-invalid xfails and one existing warning in
1,138.47 seconds. This was the required separate pre-development invocation.

The active rules remain MobilityWare four-suit Spider. Unrestricted Deal is
on, including Deal into one or more empty columns. The next row remains
`state.stock[-10:]`, placed left to right. Move legality, corrected costs,
automatic same-suit K-A removal and the solved predicate are unchanged.

The regression anchors remain exact:

- canonical solution: corrected 172, 174 commands, 169 tableau commands, five
  Deals, eight foundations, path `77d169da2538ba8c`, state
  `4e9861540eac570cb`;
- machine first foundation: corrected 21 in 21 actions, two Deals, Spades,
  stock 30, face-down 33, path `924bfd20deac96af`, structural hash
  `b7522950ea41ad9a`, replay valid;
- independent first foundation: corrected 23 in 23 actions, two Deals,
  Spades, stock 30, face-down 32, replay valid.

No anchor action or canonical action is available to prospective search.

## Profiled v0.7 blocker

A fresh 30-second untouched v0.7 profile made three strategic expansions.
Campaign current-epoch work consumed 12.821 seconds and removal work consumed
10.126 seconds, approximately 75% of the run together. The broader historical
v0.7 Gate F spent approximately 130 of 182 seconds in those realisers. This
confirmed that tactical scheduling, rather than another general search engine,
was the appropriate v0.8 scope.

## Tactical allocator

`tactical_resource_allocator.py` adds an inspectable, proof-neutral model:

- `TacticalDemand` and `TacticalDemandPortfolio`;
- `TacticalResourceRequest` and `TacticalResourceGrant`;
- `TacticalResourceOutcome` and state-local `TacticalResourceEvidence`;
- `TacticalResourceLedger` and descriptive `TacticalHarvestRate`.

The objective kinds are dependency closure, receiver creation, interval
assembly, overlay clearing, supply consumption, run construction, excavation,
workspace, foundation removal, Deal preparation, Deal evaluation and raw
fallback. They describe why compute is requested; realiser kinds separately
identify the component receiving it.

The generic progressive tiers are:

| Tier | Added cost | Nodes | Seconds |
|---|---:|---:|---:|
| PROBE | 2 | 128 | 0.10 |
| SHALLOW | 4 | 512 | 0.35 |
| COMMITTED | 8 | 2,000 | 1.25 |
| TERMINAL | 18 | 8,000 | 2.00 |

An expansion may grant at most 12,000 tactical nodes and four tactical
seconds. These are internal reservations within the unchanged overall
controller ceilings, not extra budget.

## Critical-path-first allocation

The campaign critical-path summary now exposes the current blocker,
prerequisites, deepest source, receiver/workspace status, waiting supplied
asset, missing interval, overlay and terminal qualification. Fresh analysis
maps the leading blocker to closure, receiver, interval, overlay, supply,
excavation or workspace demand.

An explicit prerequisite prevents the expensive current-epoch and corridor
realisers from receiving a tranche for that campaign. Unqualified removal is
still represented as `REMOVAL_DIAGNOSTIC_ONLY`, but the allocator records the
decision without invoking the expensive realiser. This is resource policy,
not impossibility or pruning. Once the unchanged terminal predicate succeeds,
terminal assembly receives TERMINAL allocation and a promoted corridor may be
retained as an alternative.

This final policy corrects a problem found during the first v0.8 diagnostic:
campaign corridor setup consumed 55–72 seconds despite roughly five seconds
of grants. The corrected policy no longer calls that realiser while a named
prerequisite remains. In the accepted Gate G, 27.8 seconds were granted and
only 3.069 seconds were consumed.

## Promotion, demotion and memory

Promotion requires a named return: dependency/overlay/receiver/interval
closure, integrated supply, permanent adjacency, relevant source exposure,
workspace, concrete exact-row Deal unlock, terminal qualification or
foundation. More legal moves, elapsed work and node count are insufficient.

A first zero-harvest miss remains at the same tier. A second equivalent miss
suspends that exact context. COMMITTED requires prior named harvest; TERMINAL
requires terminal qualification. Keys contain exact structural state,
objective, campaign, realiser, allocator configuration, critical-path
fingerprint and qualification. Fresh state or blocker creates fresh
eligibility. None of this memory enters canonical identity or proof pruning.

The Deal evaluator also uses progressive compute. PROBE and SHALLOW inspect
the exact incoming row, current receivers and already selected campaign stock
sources without whole-state reanalysis. Only a promoted COMMITTED Deal demand
can launch the deeper counterfactual evaluator. The raw exact legal Deal edge
always remains available, including with empty columns.

## Return telemetry

Every invocation records grants and consumption, paid cost, legal successors,
named structural returns, blocker transition, decision and proof authority.
Controller telemetry aggregates requests, tiers, family nodes/time,
promotions, demotions, suspensions, repeated misses, zero-harvest calls and all
named harvest classes. Harvest events per second and per 1,000 nodes remain
descriptive metrics rather than a fitted scalar.

## Capability gates and unseen deals

Gates A–E pass:

- Gate A selects receiver, interval and overlay work before unqualified
  removal, then enables strong terminal allocation after qualification;
- Gate B verifies PROBE, harvest-based SHALLOW/COMMITTED promotion, exact
  repeated-miss suspension and fresh-state reset;
- Gate C records deterministic grants, consumption and seven named return
  classes with inspectable rates;
- Gate D retains prerequisite work, an alternate campaign, late-removal
  construction and Deal;
- Gate E gives a continued campaign fresh critical-path attention without
  granting it maximum compute or suppressing alternatives.

Two deterministic shuffled four-suit deals (seeds 31 and 47) completed two
strategic expansions in 1.682 and 1.932 seconds. Both used the unrestricted
profile, derived tactical demand, granted PROBE work, represented construction
and Deal, respected the short deadline and independently replayed their
selected prefixes.

## Gate F — cost-21 allocation diagnostic

Gate F used the replayed machine cost-21 state only as a diagnostic anchor. It
retained the prescribed ceilings: 90 seconds, 25 expansions, 300,000 tactical
nodes and frontier 256.

The replay-valid selected descendant:

- reached all 25 expansions in 16.963 seconds, versus six in 90.007 seconds
  for v0.7;
- used added corrected cost 5, for total corrected `g=26`;
- retained one Spades foundation, stock 30 and 32 face-down cards;
- had same-suit mass 11, seven stable joins and debt 9;
- used 334 controller tactical nodes;
- had descendant path `18843bfb94399fdb` and endpoint
  `30496cf7f013e61f`.

Per-family measured use was:

| Family | Nodes | Seconds |
|---|---:|---:|
| dependency closure | 334 | 1.470464 |
| run construction | 20 | 0.002866 |
| Deal evaluation | 0 | 0.000498 |
| unqualified current/removal/corridor | 0 | 0 |

The ledger recorded 97 named harvest events: 28 dependencies, six overlays,
nine receivers, 33 permanent joins and 21 exact-row Deal unlocks. This is
65.815 harvest events/second and 274.011 events/1,000 consumed allocator nodes.
Diamond compulsory sources fell from six to four, while Clubs fell from four
to three. Foundation #2 was not removed.

Gate F authorized Gate G because unqualified removal time was eliminated, the
expansion count increased materially, named dependency and construction
harvest remained present, one foundation was retained, and late-removal
construction remained represented.

## Gate G — true untouched deal

Gate G started from the untouched opening with `incumbent=None` and no route,
checkpoint, suit, campaign or canonical seed. Its ceilings remained 180
seconds, 50 expansions, 500,000 tactical nodes and frontier 256.

The replay-valid selected result:

- reached all 50 expansions in 35.444 seconds, versus nine in 181.863 seconds
  for v0.7;
- used corrected `g=8` in eight actions;
- retained stock 50 and had 38 face-down cards;
- had same-suit mass 6, five stable joins and debt 1;
- used 507 controller tactical nodes;
- had path `d2883a5e603062af` and endpoint `23413a4ad8d91f27`.

Per-family measured use was:

| Family | Nodes | Seconds |
|---|---:|---:|
| dependency closure | 507 | 3.058871 |
| run construction | 56 | 0.009001 |
| Deal evaluation | 0 | 0.001249 |
| unqualified current/removal/corridor | 0 | 0 |

There were 136 requests, 108 PROBE, 20 SHALLOW and eight COMMITTED grants,
110 harvest-qualified promotion decisions, 26 zero-harvest outcomes, 563
allocator-consumed nodes and 238 named harvest events. The ledger granted
27.8 seconds and consumed 3.069 seconds. The controller examined 102 unique TT
states; 27 exact duplicates were suppressed. Fifty-six construction
opportunities remained represented across Spades, Diamonds, Hearts and Clubs,
including late-removal horizons.

The fixed expansion ceiling arrived before a foundation. The leading Spades
campaign had one compulsory source at depth one and no mixed overlay, but
still lacked the K, J-8 and A intervals. Thus the new blocker is conversion of
cheap dependency/construction harvest into a continuous interval-building
lane and terminal qualification, not tactical component monopolisation.

Because neither F1 nor F2 was reached, repeatability, F3 and whole-game runs
were not authorized.

## Proof safety and genericity

Exact TT remains structural state to lowest corrected `g`. The admissible
Deal/reveal lower bound is unchanged. Allocation state, tier, history and
misses do not enter state identity; every allocation outcome has zero proof
authority. Raw legal play remains reachable after a bounded tactical miss.

Production policy contains no benchmark suit, rank, column, score, checkpoint,
external 119 target or canonical action. Tier defaults are generic and the
overall benchmark budgets were not increased.

## Verification and verdict

The focused v0.2–v0.8 controller cohort passes 281 tests. The v0.7/v0.8
focused pair passes 92 tests, and the broader v0.4/v0.7/v0.8 compatibility
selection passes 132 tests. The final complete repository invocation passed
905 ordinary tests with 37 expected-invalid xfails and the single existing
warning in 1,128.14 seconds.

Verdict: **PARTIAL**. Allocation productivity and strategic throughput improve
substantially, the unqualified-removal blocker is removed, construction is
preserved and proof/rules remain safe, but the untouched controller does not
remove a foundation within 50 strategic expansions.

The recommended next development task is a generic, bounded
milestone-conversion policy: preserve a harvested critical-path objective
across strategic expansions and assemble its remaining same-suit intervals
using primitive closure/construction successors, without reintroducing the
expensive whole-campaign corridor setup or increasing budgets. This task is
not started here.
