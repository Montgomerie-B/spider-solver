# Anytime Whole-Game Controller v0.6

**Status:** PARTIAL

**Base:** `agent/anytime-whole-game-controller-v0-5` at
`c147a59a4151678fe7945db18f8eccc7949a99c0`

**Rule profile:** MobilityWare four-suit, unrestricted Deal ON

## Outcome

v0.6 implements the missing distinction between stock supply and campaign
consumption. It adds physical supply provenance, legitimate copy substitution,
a deterministic dependency graph and a bounded same-epoch dependency-closure
realizer for one named campaign. Closure can expose a named source, create a
receiver, consume supplied material, clear a mixed overlay and bridge into the
unchanged terminal-assembly predicate. All of this is ordering, coverage and
telemetry. It has no proof authority.

The capability gates succeeded: supplied cards were not called fulfilled on
delivery, a consumed/integrated card could fulfil its contract, named overlay
closure replayed independently without a Deal, and natural Gate C consumed
supplied assets while closing 18 dependencies and clearing five overlays.
That evidence satisfied the task's hard capability decision and authorized one
untouched 180-second run.

The untouched run still removed only the first Spade foundation. Its selected
replay-valid prefix ended at corrected `g=72`, with one foundation, empty
stock, 25 face-down cards and campaign MUST burden 28. No second foundation was
removed. The verdict is therefore PARTIAL. No repeatability, foundation-#3,
whole-game or solution run was attempted.

## v0.5 blocker addressed

v0.5 reached a replay-valid `g=73` prefix with one foundation and no stock.
The leading Diamond #1 campaign retained two compulsory sources, a missing
rank-3 interval and mixed overlays over useful fragments. More fundamentally,
three post-foundation Deals could each be called fulfilled after supplying a
useful row-level asset even when that asset was never used by the named
campaign.

v0.6 replaces that interpretation with the lifecycle:

```text
PROMISED -> DELIVERED -> AVAILABLE -> CONSUMED -> INTEGRATED
                                      |             |
                                      +-- INVALIDATED / EXPIRED
```

Delivery records that the physical stock asset arrived. Consumption requires
an attributable campaign action. Integration requires that the action close a
named dependency, assemble required same-suit coverage, make a removal macro
reachable or remove the foundation.

## Supply-consumption API and provenance

`spider.planner.supply_consumption` provides:

- `SupplyConsumptionStage`;
- `CampaignSupplyObligation`;
- `CampaignSupplyEvidence`;
- `CampaignSupplyConsumption`;
- `SupplyConsumptionResult`;
- obligation derivation and lifecycle advancement helpers.

An obligation records the exact incoming row, destination column, physical
source key, card/rank dependency, named campaign, expected receiver and current
location. Replay follows the asset through later tableau moves instead of
assuming that it remains in its Deal column.

Duplicate cards are handled at the dependency level. If the originally
delivered copy is displaced but another interchangeable copy legitimately
satisfies the same dependency, the lifecycle accepts the substitution and
records the replacement provenance. Coordinates are evidence, not the identity
of the campaign obligation.

`CAMPAIGN_SUPPLY` is now fully `FULFILLED` only when all recorded obligations
are consumed and at least one has directly advanced the campaign. Mere arrival
remains `PARTIALLY_FULFILLED` within the horizon and becomes
`DELIVERED_BUT_UNCONSUMED` when the horizon ends. Integrated supply is retained
as success even if a later portfolio analysis no longer exposes the original
campaign label.

## Named dependency graph

`spider.planner.campaign_dependency_closure` supplies:

- `CampaignDependency` and `CampaignDependencyType`;
- `CampaignDependencyGraph`;
- `DependencyClosureConfig`;
- `DependencyClosureStep`, `DependencyClosureAssessment` and
  `DependencyClosureResult`;
- `DependencyClosureStatus` and `MixedOverlayBlocker`;
- deterministic graph construction and bounded realization.

The graph is rebuilt for one named campaign from exact current state. It uses
the following blocker types:

- `SOURCE_BURIED`;
- `SOURCE_EXPOSED_BUT_BLOCKED`;
- `MISSING_SAME_SUIT_INTERVAL`;
- `MIXED_OVERLAY`;
- `RECEIVER_MISSING`;
- `WORKSPACE_REQUIRED`;
- `SUPPLIED_NOT_CONSUMED`;
- `FRAGMENT_ORDERING`;
- `TERMINAL_ASSEMBLY_PREREQUISITE`.

Edges state which concrete dependency must be resolved before another source,
receiver, interval or terminal prerequisite can be consumed. Node identities
and ordering are deterministic and contain no benchmark suit, rank, column,
deal-number or route constants.

## Same-epoch closure and overlay clearing

Closure is a bounded local beam search, not a second whole-game solver. Its
production default permits tableau actions only, added cost 14, at most 4,000
nodes, a two-second slice and beam 192. A Deal is neither generated nor
silently performed unless an explicit non-default configuration permits a
stock transition. A typed bounded miss leaves the campaign legal elsewhere
and has no proof meaning.

Every selected action cites the named dependency it advances. The realizer may
move a legal single card or same-suit run, create a receiver, expose a source,
remove a mixed overlay, join a missing interval or use workspace. It does not
clean unrelated tableau structure merely because the result looks better.

Temporary mixed/workspace parks require a bounded exit in the local result.
Each step records stable same-suit joins created or broken, mixed boundaries
created or removed, its future exit route and estimated rehandling debt.
Permanent same-suit joins dominate otherwise comparable parks; a temporary
mixed park survives only with a concrete campaign benefit. Lifecycle debt
orders this search and never becomes admissible proof pruning.

Successful results are independently replayed from the closure start state.
Possible results include foundation removal, dependency closure, supply
consumption, milestone progress, typed blocker failures and resource limits.

## Controller integration

The protected lane carries its unresolved dependency set. After a
removal-relevant milestone, the controller can reanalyse and replan the same
objective rather than reducing the event to generic frontier telemetry. Only
one matching descendant remains protected; other campaigns, ordinary play and
Deal successors remain available.

Before considering another Deal for a protected post-foundation campaign, the
controller offers bounded dependency closure when an earlier supply obligation
is delivered or available but unconsumed. A useful closure successor competes
in the normal frontier. A bounded miss may justify a later purpose-bearing
Deal, but never makes that Deal illegal.

Fresh analysis follows a closure edge. If the existing near-removal predicate
then qualifies the campaign, the unchanged terminal assembler may run. v0.6
does not weaken that predicate to manufacture apparent terminal progress.

Search nodes retain supply, contract, outcome, protected-lane and closure
history on the selected path. The successive-Deal audit records the previous
dependency and consumption stage, whether closure was attempted and its
result, why another row was considered, and the new exact row and purpose.

## Proof and cache safety

Exact identity remains canonical tableau/stock/foundation structure. Exact TT
dominance remains lowest corrected `g`. Contract, supply, dependency graph,
closure history, lifecycle debt and protected-lane state do not enter TT
identity and cannot override lower-cost exact-state dominance.

The admissible bound remains:

```text
h_deals = remaining_deals
h_reveal_paid = ceil(max(0, face_down - 10*remaining_deals) / 2)
h_admissible = h_deals + h_reveal_paid
```

Closure misses, terminal misses, supply stages and rehandling estimates have no
proof authority. The closure cache is local to a solve and keyed by exact
state, campaign identity, configuration and supply-stage fingerprint. A cached
bounded miss is still only a heuristic resource result.

## Regression anchors

All required anchors remained exact:

- canonical solution: solved, corrected 172, 174 explicit commands, 169
  tableau commands, five Deals, eight foundations, path
  `77d169da2538ba8c`, final state `4e9861540eac570cb`;
- machine first foundation: corrected 21, 21 actions, two Deals, Spades, stock
  30, face-down 33, path `924bfd20deac96af`, state
  `b7522950ea41ad9a`, replay valid;
- independent first foundation: corrected 23, 23 actions, two Deals, Spades,
  stock 30, face-down 32, replay valid.

The historical v0.5 `g=73` prefix was not committed as an action artifact.
Only its documented hashes were available, which is insufficient to recreate a
legal state. Diagnostic Gate D was therefore omitted exactly as instructed;
neither its state nor guessed actions were used as a seed.

## Capability Gates A and B

The supply fixture delivered a promised Club 5 into its expected row geometry.
Its highest stage was `AVAILABLE`, and contract validation remained
`PARTIALLY_FULFILLED`. After the card was actually moved onto its promised
same-suit consumer, the stage became `INTEGRATED` and the contract became
`FULFILLED`.

The overlay fixture represented a named required source under one card. The
closure realizer removed the named overlay in one legal campaign-attributed
action, returned `DEPENDENCY_CLOSED`, performed no Deal and passed independent
replay. The focused fixtures also cover receiver creation, missing-interval
joining, supplied-card consumption, temporary parks with explicit exits,
typed no-progress failure and the closure-to-terminal-assembly bridge.

## Unseen-deal capability gate

Deterministic shuffled four-suit seeds 8301 and 8302 both passed unrestricted
preflight and safely invoked the generic controller/lifecycle path. Seed 8301
completed in 0.775 seconds, retained one replay-legal successor and created one
Deal contract. Seed 8302 completed in 0.646 seconds, retained two replay-legal
successors and created one Deal contract. No benchmark constant or canonical
future action was available to either run.

## Natural Gate C — cost-21 residual

Gate C began only from the independently replayed machine first-foundation
anchor; it received no known future route. Its fixed controller envelope was
90 seconds, 25 strategic expansions, frontier 256 and the existing corridor
resources. Each closure call was bounded to added cost 14, 4,000 nodes, two
seconds, beam 192 and no Deal.

Observed selected result:

- elapsed 90.435 seconds, overrun 0.435 seconds;
- seven strategic expansions and 35,303 tactical nodes;
- added cost 14, total corrected cost 35, 14 actions;
- one Spade foundation, stock 30, face-down 27, MUST burden 21;
- stable joins 9, same-suit mass 14;
- mixed boundaries/rehandling debt 12;
- path `caa8017cc64f59e8`;
- endpoint `ffb07b08c7a2ebb4`;
- structural/Zobrist hash `2ea3e89983e13e3a`;
- independent replay valid.

The selected endpoint therefore matched the useful v0.5 investment rather
than removing foundation #2. Its leading Heart #1 campaign had six compulsory
sources, deepest direct depth four, missing J, 9 and 5-2 intervals, and no
remaining mixed overlay in that fresh diagnosis. It was not near terminal.

The broader bounded Gate C search nevertheless demonstrated the new
capability. Seven closure attempts produced six successes, visited 1,071
closure nodes, closed 18 named dependencies and cleared five overlays. Closure
used 6.218 seconds in total with a 2.015-second maximum call. The only typed
failure was one `BLOCKED_BY_OVERLAY` result. Twenty-one dependency graphs were
built.

The closure timeline included:

- Heart #1 ordering and receiver closure;
- Diamond #1 consumption of a promised supply obligation, source/receiver and
  ordering closure, and removal of two named overlays;
- a later Diamond ordering/receiver closure;
- Club #1 consumption of two promised supply obligations and removal of a
  named overlay;
- later Club ordering/receiver closure; and
- later Heart ordering/receiver/source closure with two more overlays removed.

Across Gate C, five supply contracts promised 16 assets. All 16 were delivered;
23 availability observations were recorded as assets moved or substituted, 10
assets were consumed and six integrated. No asset was invalidated. Two
contracts ended delivered-but-unconsumed and zero multi-asset supply contracts
were fully fulfilled. Delivery was therefore visibly not treated as lifecycle
success.

This supplied-card consumption was a Section 28 major-capability result even
though the selected endpoint retained six Heart compulsory sources. It
authorized exactly one untouched Gate E.

## Gate D — unavailable

Gate D was not run. The v0.5 branch had no replayable 73-action artifact, and
the documented path/state hashes cannot reconstruct a state. No attempt was
made to infer the prefix, seed it, or initialize production search from it.

## Decisive Gate E — untouched opening

Gate E began from the true untouched deal with `incumbent=None`. It had no
cost-21/cost-23 actions, v0.5 state, suit/campaign target, checkpoint or
canonical future action. It used the unchanged v0.5 whole-controller envelope:
180 seconds, at most 50 strategic expansions, 500,000 tactical nodes and
frontier 256, with unrestricted Deal and v0.6 closure enabled.

Observed selected result:

- elapsed 180.570 seconds, overrun 0.570 seconds;
- nine strategic expansions and 59,705 tactical nodes;
- corrected `g=72`, 72 explicit actions;
- one Spade foundation; no second foundation;
- five Deals, stock 0, face-down 25, MUST burden 28;
- stable joins 29, same-suit mass 42;
- mixed boundaries/rehandling debt 24;
- path `5b5119a747d02366`;
- endpoint `2d181fa8403ffa09`;
- structural/Zobrist hash `25183eddbac04c78`;
- independent replay reproduced cost and exact state.

The selected path consumed these exact stock rows in order:

1. `Js 9d 4d Kh 4d 6d 9s 7d 8s 5c`;
2. `Ks As 6h 7s Ad Ad Ah 10d Qh Jd`;
3. `2c 10s Qd Kh 8h 9c 3s 5s 5d 4h`;
4. `9d Js Qh 2d 4c Qc Kc 8c Jh 9s`;
5. `3h 10h 2d 3c 9h 7c 7h As 3c 5d`.

The first foundation remained the generic Spade removal at corrected `g=21`,
after two Deals, with stock 30 and 33 face-down cards. The runtime emits the
selected-path purpose, supply stage, closure-before-next-Deal result and final
contract status for each row. No second-foundation timestamp, suit, route or
between-foundation investment record exists because foundation #2 did not
occur.

The `g=72` endpoint equals the historical v0.4 selected structural endpoint
and is one move cheaper, with slightly better permanent structure and debt,
than the v0.5 `g=73` endpoint. It still exhausted stock without converting a
second campaign.

## Tests and deadlines

The focused v0.6 suite contains 49 passing tests, including the two unseen
deals. The combined v0.5/v0.6 run passed 96 tests. The single completed full
repository run passed **813 tests**, preserved **37 expected-invalid xfails**,
and emitted one pre-existing pytest return-value warning in 18m39s.

Gate C and Gate E exceeded their nominal walls by 0.435 and 0.570 seconds,
both inside the established two-second tolerance. Closure's maximum observed
call was 2.015 seconds. No total tactical envelope or benchmark wall time was
increased.

## Genericity, limitations and verdict

No benchmark deal number, target suit, target rank/column, historical action,
119-move information or terminal state enters production strategy. The active
119 absence remains irrelevant to proof and pruning. Pre-foundation diversity
was held steady. Unrestricted Deal remains ON, including Deals with empty
columns.

Verdict: **PARTIAL**.

The lifecycle and local closure mechanism are working: supply delivery is no
longer mislabeled as consumption, supplied assets were genuinely consumed,
named dependencies and overlays were closed, all successful local routes
replayed, and proof semantics stayed exact. But those wins occurred on
alternative bounded lanes and did not become a durable selected campaign
through foundation #2. The selected cost-21 continuation still ended with
Heart #1 at six compulsory sources; the untouched continuation still ended
with one foundation, empty stock, 25 face-down cards and MUST burden 28. Zero
multi-asset supply contracts became fully fulfilled before later stock
transitions.

The precise next development task, only if explicitly authorized, is to improve
strategic admission and continuity so a successful dependency-closure
descendant remains a competitive investment in the same named campaign until
one campaign is fully closed or explicitly bounded out. Tighten dependency
source/receiver ordering and scope multi-asset Deal obligations to the assets a
campaign can realistically consume within its horizon. Do not increase runtime,
tune benchmark weights, seed a route or begin v0.7 automatically.
