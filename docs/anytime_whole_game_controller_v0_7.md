# Anytime Whole-Game Controller v0.7

**Status:** PARTIAL — all capability gates pass and Gate E authorizes an untouched run, but Gate F does not remove foundation #2  
**Date:** 2026-08-28  
**Authoritative implementation base:** `c96579f990487ad24f925fd6b03b2cc47a8222c4`  
**Branch:** `agent/anytime-whole-game-controller-v0-7`

## Combined authoritative base

The v0.7 branch starts exactly from the v0.6 implementation commit and then
integrates the structural-economics documentation commits in the required
order:

1. `19ac6a43361743db5c063d7cb9c7f61c74f845e9`;
2. `2c41a14ef51e0f3fe9e16af1d01becfb4f7355b7`;
3. `5050f43ec8ce470b8ec16d3593f833fc4f598a1c`.

The v0.6 implementation and historical plan record remain present. The
structural-economics companion, revised architecture and dated plan addendum
are all integrated.

## Rule profile and regression anchors

The active profile remains MobilityWare four-suit Spider with Unrestricted
Deal enabled. In particular, a Deal remains legal with empty tableau columns.
No move, proof rule, score rule or automatic-removal rule changed.

The three required anchors remain exact:

- canonical complete route: corrected 172, 174 commands, 169 tableau moves,
  five Deals, eight foundations, path `77d169da2538ba8c`, final state
  `4e9861540eac570cb`;
- machine first foundation: corrected 21, 21 actions, two Deals, Spades,
  stock 30, face-down 33, path `924bfd20deac96af`, structural state
  `b7522950ea41ad9a`, independent replay valid;
- independent first foundation: corrected 23, 23 actions, two Deals, Spades,
  stock 30, face-down 32, independent replay valid.

No anchor actions are available to prospective search.

## Structural-investment model

`structural_investment.py` introduces explicit ordering-only records:

- `StructuralInvestment`;
- `StructuralInvestmentKind`;
- `StructuralInvestmentEvidence`;
- `StructuralInvestmentStatus`;
- `StructuralHarvest`;
- `StructuralInvestmentLedger`;
- `SameCampaignContinuationCredit`.

The six investment kinds are removal campaign, run construction, excavation,
workspace, stock reception and dependency closure. An investment records its
exact starting state key, named objective, corrected paid cost, deliberately
spent stock rows, closed dependencies, consumed supply, removed overlays,
receiver/workspace effects, durable joins, fragment merges, temporary debt,
expected harvest, actual harvest and bounded continuation envelope.

All these fields have `proof_pruning_allowed=False`. They do not enter the
canonical state key or the exact transposition table.

### Harvest semantics

A closure creates harvest only from named consequences such as a closed
dependency, consumed campaign supply, removed overlay, permanent join or
foundation. A construction edge is harvested by the durable adjacency it
actually creates. Generic movement or elapsed search activity does not create
continuation credit.

## Same-campaign continuity

A successful campaign-specific harvest creates a bounded credit carrying:

- exact campaign/objective identity;
- latest harvest evidence;
- freshly recomputed unresolved dependencies;
- paid investment and further-cost limit;
- descendant-expansion and elapsed-time limits;
- lifecycle status and explicit expiry reason.

The lifecycle is `ACTIVE`, `REPLANNED`, `HARVESTED`, `SUPERSEDED`,
`INVALIDATED` or `EXPIRED`. Fresh state analysis rebuilds the named campaign
and dependency graph before each credited expansion. A contradictory campaign
portfolio invalidates the credit; a concrete dominating same-objective lane
can supersede it; the configured envelope expires it.

Continuity changes admission and ordering only. Solved/foundation precedence
is retained. At most the strongest live credit is protected during a bounded
frontier trim. Alternate campaigns, permanent construction, Deal,
workspace/reveal work and broad raw play remain represented.

## Coherent supply obligations

Each supplied asset is now classified as `CRITICAL`, `SUPPORTING` or
`OPTIONAL`; physical-copy substitution remains a separate property. The
contract derives the smallest row subset cited by the earliest actionable
critical-path milestone. One physical copy is selected for each critical
dependency, rather than treating interchangeable duplicates as independently
mandatory.

A campaign-supply contract is fully consumed when every critical obligation
is consumed or integrated and a critical asset directly advances the named
campaign. Unused supporting or optional assets do not block fulfilment or
terminal closure. An unconsumed critical asset still blocks fulfilment. A
genuinely multi-asset milestone can explicitly scope several distinct critical
dependencies.

## Dependency critical path

The closure graph now exposes `CampaignCriticalPathSummary`. Each entry
records prerequisites, source depth, receiver/workspace status, waiting supply
and transitive downstream unlock count. Closure ordering favours the actual
bottleneck and high-downstream-unlock dependencies before low-leverage cleanup.
The resulting weighted burden is inspectable and remains heuristic only.

## Construction economics

`structural_construction.py` exposes every legal durable same-suit join with:

- source fragment and receiver;
- adjacency and run-length change;
- corrected paid cost;
- reveal and workspace effects;
- important-receiver use;
- exact known future free-join epoch;
- carrying/interference cost;
- removal horizon and independent construction horizon;
- transparent disposition and rationale.

A useful two-card join has a positive `MAKE_NOW` prior. A perfect-information
row/column/card match with no meaningful opportunity cost can instead produce
`DEFER_FOR_FREE_FUTURE_JOIN`. Explicit critical receiver/workspace damage
down-orders the join. Late removal does not hide cheap current construction:
the admission policy preserves a representative late-removal construction
opportunity alongside nearer campaign work.

The same analysis exposes a structural balance sheet with permanent
adjacencies, durable runs, workspace, exposed sources, consumed stock assets,
prepared receivers, buried sources, mixed overlays, fragments, rehandling
debt, unresolved critical-path burden and carrying/interference cost.

## Capability gates

The dedicated v0.7 test file contains 46 tests matching Gates A-D and the
required proof/rules regressions.

- Gate A: PASS. Closure harvest creates exact bounded continuity; admission,
  alternate lanes, replan, invalidation, dominance and expiry are covered.
- Gate B: PASS. Single-critical, true multi-critical, optional-unused,
  critical-unconsumed and substitutable-copy cases behave as specified.
- Gate C: PASS. High downstream unlock, receiver creation and waiting supplied
  assets participate in critical-path ordering.
- Gate D: PASS. Two-card joins, late-removal construction, separate horizons,
  exact free-future joins, workspace conflict and proof-safety are covered.
- Unseen deals: PASS. Deterministic shuffled seeds 17 and 23 expose generic
  construction opportunities without a target suit or benchmark route.

The v0.6 capability file also remains green with 49 passing tests.

## Natural Gate E — cost-21 continuity

Configuration was unchanged from the prescribed ceiling: 90 seconds, 25
strategic expansions, 300,000 tactical nodes, frontier 256, and the v0.6
dependency-closure bounds.

The replay-valid selected result was:

- added corrected cost 32; total corrected cost 53 from the untouched deal;
- 32 descendant actions;
- one Spades foundation;
- stock 20;
- face-down 27;
- same-suit mass 19 and 14 stable joins;
- mixed-boundary/rehandling debt 19;
- six strategic expansions and 36,008 tactical nodes;
- descendant path `f9fab2e5d876aa96`;
- endpoint `ed4559cd2658465d`;
- elapsed 90.007 seconds.

Three closure successors and three credited children were admitted. Two
credited next steps were actually continued. The selected path preserved a
Hearts #1 closure investment that closed `ordering:h` and `receiver:h`, then
harvested a permanent Hearts join. Diamond #1 became the leading campaign with
only two compulsory sources, deepest depth three, missing interval 3-2 and one
mixed overlay.

Gate E did not remove foundation #2. It nevertheless met two independent
authorization conditions: durable selected same-campaign harvest and coherent
full supply fulfilment. Diamond readiness improved materially, but that
improvement is not attributed to the selected Hearts harvest for authorization
purposes. Gate F was therefore authorized.

## Decisive Gate F — untouched opening

Gate F started from the true untouched deal with no route seed, checkpoint,
canonical actions or suit preference. Its limits were exactly 180 seconds, 50
strategic expansions, 500,000 tactical nodes and frontier 256.

The replay-valid selected result was:

- corrected `g=53` in 53 actions;
- one Spades foundation;
- stock 20;
- face-down 27;
- same-suit mass 19 and 14 stable joins;
- mixed-boundary/rehandling debt 19;
- nine strategic expansions and 73,611 tactical nodes;
- path `29cc182f739283ba`;
- endpoint `ed4559cd2658465d`;
- elapsed 181.863 seconds.

The selected post-foundation history contains the Hearts dependency closure
and the permanent Hearts join. Across the run, three dependency-closure and
nine run-construction investments were created; four closures succeeded, eight
dependencies closed, seven critical supplied assets were consumed, six were
integrated, and two coherent supply contracts fully fulfilled. Ten
late-removal construction opportunities remained visible.

Foundation #2 was not removed. Repeatability, foundation #3 and whole-game
attempts were consequently not authorized.

## Proof and safety audit

- exact TT dominance remains canonical structural state to lowest corrected
  `g` only;
- the admissible lower bound is unchanged;
- construction, obligation scope, investment, credit, carrying cost and
  critical-path facts have no proof authority;
- unrestricted Deal remains legal with unresolved investment or supply;
- the terminal assembly predicate is unchanged;
- no benchmark score, target suit, route, checkpoint or future action appears
  in production strategy.

## Verification

- v0.7 capability tests: 46 passed;
- v0.6 capability tests: 49 passed;
- complete repository suite was invoked exactly once: 857 passed, 37 expected
  invalid cases remained xfailed, and two v0.2 compatibility assertions failed
  because exact-state deduplication exposed the new construction wrapper rather
  than the historical economic-project action kind;
- after the narrow representative-merge correction, the two failures plus all
  v0.6/v0.7 tests passed (97 tests), and the complete v0.1-v0.5 controller
  cohort passed (193 tests). The correction only preserves the historical
  public action kind while carrying the same construction metadata/category;
  no second complete-suite invocation was made, preserving the one-run rule;
- the existing unrelated warning and all 37 xfails remain unchanged.

## Verdict and next task

**PARTIAL.** v0.7 fixes the capability failure: successful same-campaign work
can survive, be continued and be harvested on the selected path, obligation
scope can fulfil coherently, and late-removal construction competes now. The
untouched hard gate still does not remove foundation #2.

The precise remaining blocker is resource allocation after a harvested
continuation. Gate F spent most of its wall time in repeated current-epoch and
removal realisers while expanding only nine strategic states. The next task
should make tactical resource allocation conditional on the fresh critical
path and terminal qualification: avoid repeated expensive removal attempts
when the named campaign still has an explicit receiver/interval/overlay
bottleneck, and spend that bounded budget on the selected high-unlock closure
or construction step. This must remain generic, ordering-only and subject to
the same proof and benchmark constraints.
