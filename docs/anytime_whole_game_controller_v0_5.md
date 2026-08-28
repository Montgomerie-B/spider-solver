# Anytime Whole-Game Controller v0.5

**Status:** PARTIAL

**Base:** `agent/anytime-whole-game-controller-v0-4` at `299406e59238cc8afbb128cfde4f2896d00bb200`

**Rule profile:** MobilityWare four-suit, unrestricted Deal ON

## Outcome

v0.5 adds generic, proof-safe Deal-purpose contracts, one bounded protected
next-foundation lane, strict terminal-conversion diagnosis and pre-foundation
structural diversity. All new mechanisms are ordering, coverage and telemetry
only. Exact state identity remains the tableau/stock/foundation structure and
exact TT dominance remains lowest corrected `g`.

The decisive untouched Gate D did **not** remove foundation #2. It reached one
Spade foundation at `g=21`, continued to a replay-valid `g=73` state, consumed
all stock, and stopped with 25 face-down cards, MUST burden 28 and no second
foundation. The verdict is therefore PARTIAL. No longer run, weight tuning,
repeatability run, foundation-#3 continuation or whole-game run was attempted.

## v0.4 failure diagnosis

v0.4 could invest productively after foundation #1 but did not finish the
investment. Its best cost-21 continuation paid 14 without a Deal and changed:

- face-down `33 -> 27`;
- campaign MUST `26 -> 21`;
- stable joins `3 -> 9`;
- same-suit mass `6 -> 14`.

The true-opening run then treated many locally useful stock transitions as
strategic unlocks and consumed every remaining row without removing another
foundation. The missing control was not another general heuristic weight. It
was durable evidence of why a row was spent and which removal-relevant
consequence was owed afterward.

## Deal-purpose contracts

`spider.planner.deal_purpose` introduces:

- `DealPurposeKind`;
- `DealObjectiveType`;
- `DealPurposeEvidence`;
- `DealPurposeContract`;
- `DealPurposeOutcome` / `DealPurposeStatus`;
- `SuccessiveDealAuditEntry`.

Every Deal-producing strategic edge is normalized through the same contract
attachment step, including exact timing, raw fallback and Deals embedded in a
campaign/removal/corridor edge. Each contract records the exact canonical
parent, exact next row, named objective where available, pre-Deal evidence,
expected consequence, surrendered current work, predicted milestone, bounded
cost/benefit, validation horizon and expiry conditions.

Raw Deals remain legal and receive `INCONCLUSIVE` or `ESCAPE_ONLY` evidence.
Contracts never enter proof state, TT identity or the admissible lower bound.

### Stricter strategic unlock

The v0.5 controller invokes strict opportunity assessment. General mobility,
a new top card, stock-epoch advance, stable mass, a walk-off or generic project
actionability cannot by itself earn `STRATEGIC_UNLOCK`.

The strict classifier requires at least one removal-relevant consequence:

- a campaign MUST dependency decreases;
- a required source becomes actionable;
- same-suit target coverage improves;
- a named receiver obligation becomes ready;
- a bounded removal estimate decreases;
- a removal macro or corridor becomes credible;
- or a foundation is removed.

Exact row supply and exact receiver geometry have their own more descriptive
purpose kinds. The old residual helper retains its v0.4 default for archived
diagnostics; production controller calls explicitly enable strict semantics.

### Validation lifecycle and purpose obligation

A fresh descendant analysis classifies the promise as `FULFILLED`,
`PARTIALLY_FULFILLED`, `PENDING`, `INVALIDATED`, `FAILED` or
`ESCAPE_RECLASSIFIED`. Pending and partial promises create ordering-only
obligations. One credible matching successor is protected when resources
permit, while unrelated and raw legal descendants remain available.

A new Deal with an unresolved previous promise is down-ordered unless it has a
stronger concrete purpose. It is never proof-pruned or made illegal. Search
nodes retain selected-path contract and outcome histories, and the successive
Deal audit records the previous promise before another row is consumed.

## Protected conversion lane

`spider.planner.protected_conversion` represents one named campaign investment
with fixed cost, descendant-expansion and elapsed-time bounds. The lane can:

- continue within its envelope;
- replan after a removal-relevant milestone;
- succeed when the target foundation count increases;
- stop on explicit invalidation;
- expire at its fixed envelope;
- or yield to concretely better evidence for the same objective.

Recognized progress is deliberately campaign-specific: source exposure, MUST
reduction, interval assembly, receiver satisfaction, readiness improvement,
bounded removal-cost decrease, macro availability or foundation removal.
Face-down reduction, mobility, same-suit mass and mixed-boundary improvement
alone are insufficient.

Only one matching descendant carries the protected lane. Other descendants do
not inherit protection automatically, and protection has no proof authority.

## Terminal conversion analysis and assembly

The terminal diagnosis reports, for every live candidate:

- each remaining selected MUST source and its exact tableau/stock provenance;
- exposed, buried and dependency-blocked status;
- assembled bands and missing rank intervals;
- receiver, workspace and mixed-overlay blockers;
- exact next-row contributions;
- bounded tactical blockers;
- and the exact reason the removal macro is unavailable.

Inspection of the historical `g=35` residual state showed no genuine terminal
assembly gap: its leading Heart campaign still had six compulsory excavations,
deep dependencies and only a three-card band. The new micro-realizer is
therefore narrowly guarded by a transparent predicate: few MUST sources,
shallow known dependencies, substantial same-suit coverage, bounded receiver
geometry, low estimated removal cost and assembly-led/ready status. It performs
a same-epoch bounded tableau beam by default, independently replays successes,
honours the shared deadline and gives misses no proof authority.

## Pre-foundation structural diversity

Before foundation #1 the controller retains three to six material geometries.
Profiles include campaign identity/readiness, stock epoch, exposed tops,
same-suit run topology, mixed-boundary topology, workspace columns, receiver
geometry, dependency burden, debt and bounded first-removal estimate. The key
contains neither action history nor paid cost.

Exact structural equality first keeps the cheaper representative. Materially
different higher-cost states can still survive under readiness, permanent
structure, debt, reveal/dependency, alternate-campaign and receiver/deal-timing
dimensions.

## Regression anchors

All anchors remained exact:

- canonical solution: corrected 172, 174 explicit commands, 169 tableau
  commands, five Deals, eight foundations, path `77d169da2538ba8c`, final state
  `4e9861540eac570cb`;
- machine first foundation: corrected 21, 21 actions, two Deals, Spades, stock
  30, face-down 33, path `924bfd20deac96af`, state `b7522950ea41ad9a`;
- independent first foundation: corrected 23, 23 actions, two Deals, stock 30,
  face-down 32, independently replay-valid.

## Gate A — finish the cost-21 investment

Frozen configuration: 90 seconds, at most 25 strategic expansions, frontier
256, campaign corridors and residual conversion enabled, target two
foundations.

Observed:

- elapsed 90.478 seconds; overrun 0.478 seconds;
- seven strategic expansions and 35,211 tactical nodes;
- best added cost 14, total cost 35;
- one foundation, stock 30;
- face-down 27, MUST 21, stable joins 9, same-suit mass 14;
- mixed boundaries/rehandling debt 12;
- residual path `caa8017cc64f59e8`;
- endpoint `ffb07b08c7a2ebb4`;
- independent replay valid.

The best selected residual path used no additional Deal and exactly reproduced
the useful v0.4 investment. Five removal-relevant lane milestones were
recorded, but no campaign qualified for terminal assembly and foundation #2
did not appear.

The precise leading blocker at this state was:

- Heart #1: six compulsory sources, deepest direct source depth four, missing
  intervals J, 9 and 5-2, best assembled band 8-6;
- Diamond #1: five compulsory sources, deepest depth six, missing Q, 5 and 3-2,
  plus one receiver blocker;
- Club #1: four compulsory sources, deepest depth nine;
- Spade #2: six compulsory sources.

This is not a terminal join-only problem.

## Gate B — purpose controls

The natural opening profile and exact next row were used with controlled
post-Deal structural evidence:

- decreasing a named campaign MUST dependency produced
  `STRATEGIC_UNLOCK`, named that campaign and validated `FULFILLED`;
- increasing only general activity/mobility produced `ESCAPE_ONLY`, not
  `STRATEGIC_UNLOCK`;
- omitting post-Deal consequence evidence produced `INCONCLUSIVE`.

## Gate C — pre-foundation diversity

The policy and configuration were frozen before checkpoint comparison: 90
seconds, at most 25 expansions, frontier 192, no incumbent, route, checkpoint,
suit or campaign seed.

Observed:

- elapsed 91.271 seconds; overrun 1.271 seconds;
- seven strategic expansions and 36,237 tactical nodes;
- four materially distinct pre-foundation geometries retained;
- the geometries included two distinct current-epoch top/source layouts, the
  untouched layout, and a different stock-epoch/receiver layout;
- one first-foundation checkpoint was discovered: Spades at `g=21`, stock 30,
  face-down 33, MUST 26, stable joins 3 and debt 11.

This is an acceptable diversity result under the task gate: multiple material
pre-foundation lanes survived, although only one reached removal.

## Gate D — untouched opening to two foundations

Frozen configuration: 180 seconds, at most 50 strategic expansions, 500,000
tactical nodes, frontier 256, no incumbent or seed of any kind.

Observed:

- elapsed 180.037 seconds; overrun 0.037 seconds;
- nine strategic expansions and 59,456 tactical nodes;
- first foundation: Spades at `g=21`, after two Deals;
- final selected prefix: corrected `g=73`, 73 explicit actions;
- foundations 1, stock 0, face-down 25, MUST 28;
- stable joins 28, same-suit mass 41;
- mixed boundaries/rehandling debt 25;
- path `a4a22d9fc67ef2a4`;
- endpoint `e3fa5ce9513a487f`;
- continuous independent replay valid.

Five stock rows occur on the selected prefix. Their exact pre-Deal audit is:

1. at action 5 / `g=4`, objective Spade #1 campaign supply, row
   `Js 9d 4d Kh 4d 6d 9s 7d 8s 5c`;
2. at action 17 / `g=16`, objective Spade #1 campaign supply, row
   `Ks As 6h 7s Ad Ad Ah 10d Qh Jd`; the foundation follows at `g=21`;
3. at action 36 / `g=35`, next-foundation campaign supply, row
   `2c 10s Qd Kh 8h 9c 3s 5s 5d 4h`;
4. at action 51 / `g=50`, next-foundation campaign supply, row
   `9d Js Qh 2d 4c Qc Kc 8c Jh 9s`;
5. at action 57 / `g=56`, next-foundation campaign supply, row
   `3h 10h 2d 3c 9h 7c 7h As 3c 5d`.

Across the bounded search, nine Deal contracts were admitted: eight
`CAMPAIGN_SUPPLY` and one raw `INCONCLUSIVE`. Five observed supply contracts
validated a named consequence. No contract or lane entered proof pruning.
The controller now preserves selected-path contract/outcome history and emits
a successive-Deal audit even when an earlier contract was fulfilled, so a
chain of individually fulfilled promises remains visible as a lifecycle.

Protected-lane telemetry recorded eight creations/replans and five
removal-relevant milestones. No lane completed, invalidated or exhausted its
envelope before the wall deadline. The selected path nevertheless shows that
milestone-by-milestone supply validation is still too weak to guarantee
conversion before the next Deal.

### Final blocker

The best final candidate was Diamond #1. It was not terminal-qualified:

- two compulsory sources remained;
- rank 3 was the remaining missing same-suit interval;
- the deepest direct source depth was three;
- several Diamond bands were covered by mixed-suit overlays, including the
  10, 9, 2 and Ace fragments;
- stock was empty, so no later row could repair reception geometry.

The controller needs a bounded same-epoch dependency-closure/overlay-clearer
that carries one named campaign from its last meaningful milestone to either
removal or explicit bounded failure. Simply calling each supply milestone
fulfilled permits campaign switching and further stock expenditure without a
terminal conversion guarantee.

## Proof safety and deadlines

The admissible lower bound is unchanged:

```text
h_deals = remaining_deals
h_reveal_paid = ceil(max(0, face_down - 10*remaining_deals) / 2)
h_admissible = h_deals + h_reveal_paid
```

Contracts, outcomes, protected lanes, terminal estimates/misses and diversity
profiles do not change this bound and do not enter TT identity. Gate C and D
overruns were 1.271 and 0.037 seconds, both within the two-second tolerance.

## Tests and unseen deals

The focused v0.5 suite contains 47 passing cases covering the 46 requested
areas; the extra case is the second parameterized unseen deal. The broader
focused regression selection passed 431 tests. The single completed full
repository run passed **764 tests**, preserved **37 expected-invalid xfails**,
and emitted one pre-existing pytest return-value warning in 18m28s. Two
deterministic unseen four-suit deals passed unrestricted preflight, generated
purpose contracts, exercised generic controller/lane setup, retained legal
replay behavior and stayed within the deadline tolerance. The full repository
suite did not weaken or convert any historical expected-invalid case.

## Limitations and verdict

Verdict: **PARTIAL**.

The architectural controls are present, generic and proof-safe. Gate A
preserved the useful investment, Gate C retained real structural diversity,
and all stock actions are now attributable. But Gate D still drained stock
after individually plausible campaign-supply milestones and did not remove
foundation #2.

Recommended next development task, if explicitly authorized later: implement
a bounded same-epoch campaign dependency-closure realizer for the named
protected lane, and strengthen contract fulfilment so `CAMPAIGN_SUPPLY` remains
partial until its promised source/receiver is actually consumed by the named
campaign. Test first on generic synthetic overlay/source fixtures and unseen
deals. Do not change benchmark weights or wall-clock limits.
