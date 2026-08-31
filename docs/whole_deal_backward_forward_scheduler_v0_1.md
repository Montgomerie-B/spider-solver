# Whole-deal backward/forward structural scheduler v0.1

## Scope and verdict

This phase implements the first generic whole-deal itinerary above the mature
v0.15 local controller. It is not controller v0.16 and adds no search engine,
frontier capacity, tactical nodes, strategic expansions, closure width,
resource tier or target persistence. Unrestricted Deal remains on.

The verified verdict is **PARTIAL**, architectural class **D — schedule-
economics failure**. The blueprint is coherent, scheduler objectives naturally
enter and survive the controller, and existing tactical machinery advances
them. Gate S selected and advanced eight scheduled objectives and recorded
eight permanent structural harvests. It did not reach F2. The authorized
untouched Gate T repeatedly advanced useful fragments but selected no Deal,
ending at F0 with stock 50. The remaining problem is a bounded fragment-
saturation / epoch-transition criterion, not more search resource.

## Why v0.15 ended local-controller development

v0.15 proved the local execution chain through exact admission and one bounded
cash-out expansion. Natural Gate Q produced five trace completions, four
qualified exact representatives, four selected expansions, four genuine
same-suit construction harvests and one dependency-chain advance. It produced
no source consumption, source integration, substantial source-chain
completion, terminal qualification or second foundation. Repeating local
continuity refinements would not supply the missing whole-deal itinerary.

Scheduler v0.1 instead asks what useful structure should exist before each
known future Deal and which current cards are the highest-leverage
prerequisites of it.

## Architecture

The implementation separates two proof-neutral objects.

`WholeDealBlueprint` is mostly static for one search root. It contains:

- exact temporal card references for current face-up, current face-down,
  future stock and removed foundations;
- every remaining stock row in the engine's next-first order with fixed
  card-to-column correspondence;
- per-suit/rank cumulative multiplicity by epoch;
- non-proof foundation availability floors for each remaining symmetric lane;
- maximal backward fragments split at every temporally unavailable rank.

`WholeDealSchedule` is rebuilt from each exact successor state. It contains:

- freshly canonicalised symmetric lane assignments;
- satisfied, missing, future-gated and planned-future-free adjacency edges;
- current contributing fragments;
- exact next-Deal reception opportunities;
- current and future high-leverage sources;
- at most four ordered semantic objectives;
- a Deal-Now economic indication.

The blueprint and schedule are ordinary planning metadata. Neither enters
`CanonicalStateKey`, exact TT dominance, the admissible lower bound, legality,
or proof pruning.

## Epoch and temporal availability

The epoch is derived as `5 - len(stock) // 10`. The engine remains authoritative
for row order: the next row is `stock[-10:]`, dealt left to right to tableau
columns 1 through 10.

Every remaining physical card is classified as one of:

- `CURRENT_EXPOSED`;
- `CURRENT_FACEUP_BURIED`;
- `CURRENT_FACEDOWN_KNOWN`;
- `FUTURE_STOCK(epoch)`;
- `REMOVED_TO_FOUNDATION`.

A current tableau card has the current temporal floor even when tactically
expensive to uncover. A stock card has its exact arrival epoch and never emits
an impossible excavation objective.

## Foundation floors and symmetric duplicate lanes

For each suit and epoch the blueprint counts every available copy of every
rank. If `r` foundations of a suit are already removed, the next remaining
lane with ordinal `j` has copy threshold `r + j`. Its availability floor is
the first epoch where the minimum count over all thirteen ranks reaches that
threshold. Limiting ranks are those below threshold in the preceding epoch.

This is only a temporal material floor. It does not prove exposure,
actionability, assembly or removal.

The two physical copies of a rank are not permanently named. Remaining lanes
are symmetric. Current stable-fragment contribution signatures are sorted into
a canonical lane representation and may change after every move or Deal.

## Backward adjacency and fragments

Each remaining lane has the twelve K-Q through 2-A adjacency targets. For a
given epoch, ranks whose cumulative multiplicity is below the lane's copy
threshold split the chain. The blueprint records every maximal attainable
interval, not only the longest visible run.

This works for any rank. A synthetic case with both copies of a rank arriving
in the final row produces the natural upper and lower fragments on both sides
of that rank. A one-copy-early/one-copy-late fixture lets the first lane cross
the rank while retaining a split second lane.

Late removal does not suppress useful construction. When the first remaining
lane is temporally gated, the bounded suit-diverse schedule reserves its best
surrounding `BUILD_FRAGMENT` objective.

## Stock reception and future-free adjacency

The scheduler analyses all future rows for temporal dependencies but performs
precise column shaping only for the next row. Each next-row card is classified
as:

- `SAME_SUIT_FREE_JOIN`;
- `FOUNDATION_TRIGGER`;
- `BRIDGE_RECEPTION`;
- `USEFUL_ISOLATION`;
- `NEUTRAL_RECEPTION`;
- `HARMFUL_RECEPTION`.

A receiver target records the incoming card, fixed column, desired same-suit
rank-above top or empty state, estimated preparation cost, rehandling debt,
expected saving, feasibility and `BEFORE_NEXT_DEAL` deadline. Preparation is
selected only when its cost plus debt is credibly covered by avoided work and
permanent leverage. Otherwise Deal Now remains competitive.

An exact receiver already present marks the adjacency
`PLANNED_FUTURE_FREE`. That is heuristic ordering only. It becomes a realised
free join only after exact Deal replay confirms the receiver immediately below
the incoming card. A changed receiver invalidates the plan; a missed tracked
reception records no impossibility claim.

## High-leverage cards and deadlines

Leverage is represented by typed facts rather than one stacked scalar:

- desired edges enabled;
- fragments joined;
- lane-completion potential;
- downstream requirements unlocked;
- receiver/workspace value;
- blocker depth or arrival epoch;
- estimated structural work.

A two-sided bridge orders ahead of an equal-work one-edge extension. A current
buried bridge may emit `EXPOSE_UNLOCK_CARD`; a future bridge emits surrounding
fragment preparation with `ON_SOURCE_ARRIVAL`, never excavation.

Supported deadlines are `BEFORE_NEXT_DEAL`, `BY_EPOCH_N`,
`ON_SOURCE_ARRIVAL`, `BEFORE_STOCK_EMPTY` and `NO_HARD_DEADLINE`. Fresh
replanning removes expired pre-Deal targets.

## Forward realisation and replanning

The scheduler does not execute moves. It matches at most one scheduled target
per expansion to an existing independently replayed construction, economic,
campaign or Deal successor. The annotation stays within the existing
successor limit and category portfolio. It preserves alternate campaigns,
raw legal play, ordinary construction, workspace/reveal work, purposeful Deal
and completion cash-out.

Scheduler intent is a tie-breaker after the controller's established
structural, milestone and continuation order. It cannot make a fresh target a
compulsory script. A child schedule is rebuilt from its exact state after
admission. The recorded delta vocabulary includes target satisfaction,
advance, invalidation and reassignment; deadline advance; realised/missed
reception; bridge exposure/consumption; foundation-floor arrival; Deal-Now
preference; and new leverage sources.

## Correctness and capability gates

The pre-implementation identity audit passed. Swapping two tableau columns
without permuting a nonsymmetric remaining stock row creates distinct
canonical keys, and the exact TT admits both entries. Stock positions and
column order are therefore safe for column-specific next-row reasoning.

Capability Gates A-M all pass:

- temporal foundation floors and per-rank counts;
- generic missing-rank fragments;
- one-copy-early/one-copy-late lanes;
- useful construction for late suits;
- realised same-suit free reception;
- rejection of uneconomic preparation;
- unrestricted empty-column reception;
- two-sided bridge leverage;
- future-key-card surrounding preparation;
- fresh replan after Deal;
- fresh replan after structural change;
- bounded portfolio diversity;
- exact TT and admissible-bound safety.

Three deterministic unseen four-suit deals produced five exact future rows,
eight lane floors, backward fragments, next-row receptions and leverage
sources. Two smokes admitted scheduler objectives; the third correctly retained
ordinary/Deal play without admitting one. All three retained Deal and raw legal
tableau alternatives, independently replayed a state transition and produced a
distinct fresh schedule.

## Untouched benchmark blueprint

The exact future rows are:

| Epoch | Columns 1-10 |
|---:|---|
| 1 | Js, 9d, 4d, Kh, 4d, 6d, 9s, 7d, 8s, 5c |
| 2 | Ks, As, 6h, 7s, Ad, Ad, Ah, 10d, Qh, Jd |
| 3 | 2c, 10s, Qd, Kh, 8h, 9c, 3s, 5s, 5d, 4h |
| 4 | 9d, Js, Qh, 2d, 4c, Qc, Kc, 8c, Jh, 9s |
| 5 | 3h, 10h, 2d, 3c, 9h, 7c, 7h, As, 3c, 5d |

The opening temporal floors are:

| Suit | Lane 1 | Limiting ranks | Lane 2 | Limiting ranks |
|---|---:|---|---:|---|
| Clubs | 5 | 3 | 5 | 7, 3 |
| Diamonds | 4 | 2 | 5 | 5, 2 |
| Hearts | 2 | Q | 5 | 10, 9, 7, 3 |
| Spades | 2 | A | 5 | A |

The user-observed Club fact is confirmed by parsing: both 3c cards occur in
the final row, in columns 4 and 9. The generic backward pass therefore derives
pre-final Club lane-1 fragments K-4 and 2-A where surrounding material is
available. Production policy contains no Club/rank/column special case.

The untouched opening has no immediately worthwhile exact receiver
preparation under the conservative v0.1 economics; all ten next-row landings
are neutral. Deal Now is preferred. The highest opening buried bridge facts
include 8c and 3s at blocker depth one. Future two-sided bridge candidates
include 5s and 3s in epoch 3 and 8c in epoch 4.

## Natural Gate S

Gate S started from the independently replayed machine F1 at total corrected
`g=21`, Spades F1, stock 30 and 33 face-down cards. Its envelope remained 90
seconds, 25 strategic expansions, 300,000 tactical nodes, frontier 256,
closure beam 192 and persistence three.

It reached all 25 expansions in 21.281 seconds and used 99 tactical nodes. The
best continuous replay-valid route added five actions/corrected cost five and
ended at total corrected `g=26`, Spades F1, stock 30, 32 face-down cards and
seven stable same-suit joins. The continuous path hash is
`b62dc41af62d6b5f`, endpoint hash `30496cf7f013e61f`, and structural hash
`31659973bc6dba50`.

The scheduler funnel was:

`100 generated -> 100 actionable -> 15 entered -> 11 exact-admitted -> 8 selected -> 8 advanced -> 0 fully satisfied -> 8 structural harvests -> F1`.

Six selected `BUILD_FRAGMENT` and two selected
`PREPARE_TERMINAL_SEQUENCE` objectives advanced. Deltas recorded eight target
advances, eight symmetric-lane reassignments, eight bridge consumptions and
two bridge exposures. No tracked free reception was planned or realised. Gate
S did not reach F2, but this natural temporal/fragment effect authorized Gate
T under the task's late-suit/high-leverage progress criteria.

## Decisive untouched Gate T

Gate T started from the true untouched deal with `incumbent=None`, no prefix,
target suit, known foundation order, source, route or prospective action. Its
envelope remained 180 seconds, 50 expansions, 500,000 tactical nodes, frontier
256, closure beam 192 and persistence three.

It reached all 50 expansions in 45.226 seconds and used 191 tactical nodes.
The replay-valid best selected state had corrected `g=6`, six actions, F0,
stock 50, 39 face-down cards and four stable joins. Its path hash was
`ef2672d82858f51c`, endpoint hash `0ed30387a75f4ada`, and structural hash
`657542e8bd03b734`.

The funnel was:

`200 generated -> 200 actionable -> 42 entered -> 19 exact-admitted -> 13 selected -> 13 advanced -> 0 satisfied -> 13 structural harvests -> F0`.

The selected schedule stayed at epoch zero. It recorded thirteen target
advances/reassignments, fourteen bridge-consumption consequences, three bridge
exposures and seven newly recognised leverage sources. Deal remained generated
and admitted as an ordinary exact alternative, but no Deal belonged to the
best selected route. No useful stock reception, F1 or F2 occurred.

Because Gate T did not reach F2, no repeat or optional 240-second run was
authorized. No complete machine route, verified score below 172, archive write
or leaderboard comparison was produced.

## Proof safety, performance and tests

Exact TT remains `exact structural Spider state -> lowest corrected g`. The
admissible lower bound remained five before and after scheduler analysis on the
opening state. Scheduler proof-prune count is zero.

In Gate S the scheduler built one blueprint and 51 exact schedules. Measured
time was approximately 0.001 seconds for the blueprint and 0.182 seconds total
for schedule reconstruction, including 0.014 seconds reception, 0.050 seconds
duplicate assignment and 0.038 seconds leverage analysis. Gate S exact TT
recorded 51 new entries, zero improvements and nine suppressions; proof prunes
were zero.

Gate T built one blueprint and 111 schedules. Total schedule reconstruction
was 0.303 seconds, approximately 0.0061 seconds per strategic expansion;
reception used 0.033 seconds, duplicate assignment 0.104 seconds and leverage
analysis 0.095 seconds. Exact TT recorded 105 new, six improved and 70
suppressed arrivals; proof prunes were zero.

The scheduler-focused file passes 95 cases. The requested historical
controller/closure/construction/workspace/lifecycle/Deal/rules/identity cohort
passes 570 ordinary tests with 13 expected historical xfails. The definitive
complete-suite count is recorded below after the final run.

The definitive complete suite passed **1,473 tests**, with **37 expected
historical xfails** and one pre-existing pytest warning, in 1,164.15 seconds
(19:24).

## Precise blocker and next task

Blueprint derivation is not the observed blocker: temporal floors, generic
fragments, Club-3 consequences, leverage and reception facts are coherent.
Objective integration and tactical realisation also work: scheduled targets
enter, survive, are selected and produce stable structural advances.

The failure is schedule economics. Receding-horizon fragment objectives can
continue to find another locally permanent adjacency without recognising that
the marginal remaining fragment work should yield to an epoch transition. A
separately authorized scheduler v0.2 should add an explicit, inspectable
fragment-saturation / Deal-readiness criterion that compares the next bounded
permanent join against the known next-row and later-epoch unlocks. It must keep
the same resource, identity, proof and unrestricted-Deal rules.

Stop after this v0.1 report. Do not start scheduler v0.2 or controller v0.16
without a new explicit task.
