# Anytime Whole-Game Controller v0.2

**Authoritative base:** `agent/anytime-whole-game-controller-v0-1` at
`93c408e43972798f494073624c5dbe597db3a25e`

**Prospective verdict:** **PASS**

**Scope:** probe control, exact analysis reuse, transparent strategic progress,
and Deal consequence priority. This is not a completed whole-game solver.

## Frozen rules and regression anchors

The v0.1 preflight is unchanged. The active MobilityWare 4-suit profile has
**Unrestricted Deal ON** and requires `MW_RULES.can_deal_into_empty is True`.
A legal Deal is therefore allowed with one or more empty columns. The engine
still uses five tail-first, left-to-right stock rows; corrected move/deal cost;
same-suit multi-card legality; automatic exact K-A removal; and the established
solved-state definition.

The isolated preflight passed both route anchors:

- canonical route: solved, corrected cost 172, 174 explicit commands, 169
  tableau commands, five Deals, eight foundations, path hash
  `77d169da2538ba8c`, final-state hash `4e9861540eac570cb`;
- legal machine first-foundation route: corrected cost 23, 23 actions, two
  Deals, first Spade foundation, stock 30, 32 face-down cards, independently
  replayed.

Prospective searches receive no action from either route. The diagnostic-only
cost-11 and cost-23 constructors return setup states; setup actions and future
routes are not handed to the controller.

## v0.1 failure diagnosis

The v0.1 production-like run expanded 55 strategic states, charged 80,000
tactical nodes, made 616 bounded-inaccessible checks, removed no foundation,
and reported a `g=6`, stock-empty, zero-foundation, 43-face-down state as best.
Its actionability cache had no effective reuse because arbitrary remaining
resource envelopes formed part of the key.

The defects were controller mechanics:

1. unsuccessful actionability checks could consume the shared tactical budget;
2. cache identity was not normalized;
3. Deal/stock advancement received an intrinsic priority benefit; and
4. a credible foundation macro could be starved behind ordinary clean-credit
   successors.

No economic weights, suit bonuses, benchmark columns, or known-route actions
were added in v0.2.

## Independent actionability allowance

Actionability checking now has independent limits:

- probes per expansion;
- probe nodes per expansion;
- probe time per expansion;
- probes per normalized tier; and
- a total probe-node ceiling.

The default per-expansion limits are six probes, 3,000 nodes and one second.
The measured gates used four probes per expansion. A tier's full fixed envelope
must fit before a probe begins, so a single call cannot silently overflow the
per-expansion allowance. Exhaustion is recorded and successor generation
continues with direct work, protected campaigns, and Deal already retained.

Probe nodes and seconds are reported separately. They never increment
`tactical_nodes`; that counter covers realization and campaign work. A failed
probe therefore cannot exhaust the realization allowance.

## Normalized tiers and cache semantics

The three fixed tiers are:

| Tier | Added cost | Nodes | Time |
|---|---:|---:|---:|
| SHALLOW | 2 | 256 | 0.08 s |
| MODEST | 4 | 750 | 0.20 s |
| BROAD | 6 | 1,500 | 0.40 s |

The actionability key is exact structural state + complete predicate/project
identity + normalized tier. A miss means only “not found in this tier.” The
same tier suppresses an immediate duplicate; a broader tier can retry and is
reported as an escalation.

Direct legal actions and already-satisfied structural predicates are checked
without bounded search. Predicates absent for the current epoch are rejected
cheaply. Economic value, current actionability, and route realization remain
separate facts; a bounded miss does not change project value.

## Intentional successor resource order

Each expansion now spends resources in this order:

1. direct legal economic projects;
2. protected credible foundation removal/campaign opportunities;
3. exact strategic Deal counterfactuals;
4. scheduled uncertain-project probes up to the independent quota;
5. realization of the best confirmed actionable work;
6. broader credit successors; and
7. raw legal fallback only at credit 4.

Probe scheduling favors current-epoch critical work, shallow reveals, bounded
exit routes, campaign excavation, and exact receiver/workspace work. Future,
deep, substitutable, and same-tier failed work is downranked for probing only;
its economic valuation is unchanged.

At clean credit, a credible, unblocked campaign whose removal epoch is at most
one epoch away receives one bounded removal attempt even when ordinary clean
campaign breadth is zero. This generic protection is what allowed Gate A to
exercise the already-existing removal API. No suit was specified.

## Strategic progress and best-state semantics

Intrinsic strategic progress is an inspectable tuple, not one fitted score. Its
component order is:

1. solved;
2. realized foundations plus ready removals;
3. ready-removal campaigns;
4. realized foundations;
5. credible current-epoch campaigns (READY, EXCAVATION-led or ASSEMBLY-led;
   deferred late-epoch campaigns do not count);
6. total campaign MUST burden;
7. minimum heuristic campaign remaining estimate;
8. critical dependencies pending;
9. critical-next-epoch projects and actionable high-value work;
10. face-down count;
11. longest run, same-suit run mass and stable joins;
12. empty workspace and legal mobility;
13. mixed boundaries and rehandling debt; and
14. corrected paid cost.

Stock count and stock epoch are absent. The campaign estimate is ordering-only
and has no proof authority.

For queue ordering, an explicit `DEAL_REQUIRED_FOR_ACTIONABILITY` fact may
interrupt the intrinsic order after foundation/readiness facts. Other timing
preferences break ties only after intrinsic structure and the exact Deal delta.
The delta records foundation change, critical dependencies removed, actionable
high-value change, MUST reduction, exact receiver successes, same-suit mass,
stable joins, mixed-boundary removal, rehandling-debt reduction, workspace and
mobility. This preserves Deal as first-class without rewarding the epoch.

The result exposes separate `best_progress_node`, `lowest_g_node`,
`deepest_stock_node`, `most_foundations_node`, and
`lowest_dependency_node`. In the final production gate the best-progress state
had stock 30; the deepest-stock state had stock 20 and was not reported as best.

## Safe analysis reuse

Incumbent-independent analysis facts are cached by exact canonical structural
key and analysis-configuration fingerprint. The cache holds economics,
campaign summary, structural measurement and cheap actionability partition.
Incumbent budgets are rebuilt on every request and are never stored as reusable
facts.

Deal counterfactuals already contain post-Deal economics and measurement. A
child reuses those objects only when both the exact state key and configuration
fingerprint match. Any mismatch performs fresh analysis and increments a
mismatch counter. Deal/foundation children still receive complete analysis
snapshots; reuse avoids duplicate economic/measurement work rather than
skipping child analysis.

Exact analysis-cache hits were zero in the measured whole-game corridors
because exact lower-`g` TT admission usually prevents a repeated state from
reaching analysis. Post-Deal counterfactual reuse was material: 23 production
and 18 research analyses avoided recomputing the supplied post-Deal facts.

## Capability-gate results

### Gate A — legal cost-11 checkpoint

Configuration: 60 seconds, five of at most 40 allowed expansions, 20,000
tactical nodes, four probes/3,000 probe nodes per expansion, campaign cost 12,
2,000 campaign nodes.

Observed: 23.65 seconds, five expansions, 328 tactical nodes and 368 probe
nodes. The generic protected S#1 macro removed one foundation at added cost 12,
giving the independently replayed total cost-23 event. The first foundation
timeline entry is `(added g=12, foundations=1, epoch=2, suits=(s,))`. The best
state after five expansions had added `g=13`, one foundation, 33 face-down and
stock 30. Result: **PASS**.

### Gate B — legal cost-23 checkpoint

Configuration: 60 seconds, ten expansions, 25,000 tactical nodes, four
probes/3,000 probe nodes per expansion, campaign cost 18, 3,000 campaign nodes.

Observed: 53.08 seconds, ten expansions, zero realization/campaign tactical
nodes and 468 probe nodes. At added cost two, without consuming stock, the best
state retained one foundation and 32 face-down while:

- reducing total MUST burden 25 -> 23;
- increasing same-suit run mass 6 -> 9;
- increasing stable joins 3 -> 5;
- reducing mixed boundaries 12 -> 10; and
- reducing rehandling debt 12 -> 10.

No second foundation was found. The verified no-Deal structural improvement is
material but limited. Result: **PASS**.

### Gate C — true opening

Configuration: 80 seconds, at most 14 expansions, 30,000 tactical nodes.

Observed: 80.66 seconds, 12 expansions, 1,431 tactical nodes and 2,924 probe
nodes. Best progress was `g=10`, zero foundations, 40 face-down and stock 30,
with same-suit mass 9 and six stable joins. The deepest-stock node had stock 20
and was reported separately. No stock-empty disaster was selected as best.

Compared with the v0.1 60-second smoke (19 expansions and 20,008 charged
tactical nodes), v0.2 materially reduces project-checking work and improves
structure, but it finds no foundation. Result: **PASS for throughput/progress;
not the stronger foundation target**.

### Gate D — bounded whole-game attempts

Production configuration: 180 seconds, at most 40 expansions and 60,000
tactical nodes. Observed: 189.05 seconds, 18 expansions, 1,820 tactical nodes,
7,151 probe nodes and no solution/foundation. Best was `g=13`, face-down 39,
stock 30, same-suit mass 12, nine stable joins, 12 mixed boundaries and debt 12.
The final analysis call caused a 9.05-second wall-limit overrun.

Research configuration: scalar incumbent 172 only, 120 seconds, at most 30
expansions and 60,000 tactical nodes. Observed: 139.42 seconds, 15 expansions,
1,596 tactical nodes, 5,037 probe nodes and the same best state. No proof prune,
machine solution or <=171 solution occurred. A non-interruptible analysis call
caused a 19.42-second overrun. The incumbent supplied no route.

No solution was archived and the canonical file was not modified.

## Throughput comparison

| Measure | v0.1 production-like | v0.2 Gate D production |
|---|---:|---:|
| Strategic expansions | 55 | 18 |
| Charged tactical nodes | 80,000 | 1,820 |
| Tactical nodes / expansion | 1,454.5 | 101.1 |
| Inaccessible/probe attempts | 616 | 34 |
| Probe attempts / expansion | 11.2 | 1.9 |
| Separately reported probe nodes / expansion | unavailable | 397.3 |
| Realizations attempted/succeeded | unavailable | 6 / 0 |
| Analysis misses / expansion | 1.31 full analyses | 3.33 calls |
| Foundations / 10k tactical nodes | 0 | 0 |

The principal v0.1 pathology is removed: probes no longer consume the tactical
budget, their per-expansion count is bounded, and exact same-tier misses are
suppressed. Total wall throughput remains limited by full economic/deal-timing
analysis rather than tactical search.

## Telemetry and proof safety

Gate D production recorded 60 analysis misses, 23 post-Deal fact reuses, 60 new
TT entries, no lower-`g` replacement, 19 exact-state suppressions, no proof
prunes and no frontier trim. Research recorded 46 analysis misses, 18 post-Deal
reuses, TT `(46 new, 0 improved, 15 suppressed)` and zero proof prunes.

The exact TT remains `exact structural state -> lowest g`. Only the established
admissible deal/reveal bound can set `budget.proof_prunable`. Probe failure,
economic value, campaign estimates, progress tuples, Deal deltas and timing
preferences cannot proof-prune. The external 119 and canonical route do not
appear in generic controller code.

## Unseen-deal genericity

The v0.2 test suite runs two deterministic shuffled four-suit deals. Each passes
the active preflight with unrestricted Deal enabled and makes bounded legal
progress. Completion is not required. Generic controller source contains no
benchmark deal ID, route hash, suit target, or external score constant.

## Verification

The dedicated v0.2 controller file contains 33 passing tests. The combined
v0.2 and preserved v0.1 controller run passed 86/86 tests. The complete
repository suite passed **637 tests**, retained all **37 expected-invalid
xfails**, and emitted one warning in 1,082.55 seconds. No expected-invalid case
was weakened or reclassified.

## Verdict and remaining blocker

**PASS.** Gate A generically removes a foundation; Gate B makes material
no-Deal structure; probe-budget pathology is eliminated; Deal remains
first-class; and stock depletion is no longer intrinsic progress. There is no
solution, <=171 route, or true-opening foundation, so this is not STRONG PASS.

The precise blocker is campaign continuity and analysis throughput from the true
opening. The controller can realize a removal from the legal cost-11 state, but
its generic opening corridor does not reach and preserve an equivalent
removal-ready state before analysis time expires. Full next-state economic and
Deal timing analysis costs roughly three calls per strategic expansion, and the
current APIs are not fully interruptible at the controller wall deadline.

## Recommended next task

Build a v0.3 campaign-continuity and interruptible-analysis sprint:

1. preserve a bounded current campaign identity and its achieved obligations
   across generic strategic edges, revalidating it on exact child states;
2. prioritize obligation-reducing preparation toward the next removal without
   suit/route constants;
3. cache or incrementally reuse exact Deal-timing facts beyond the immediate
   post-Deal economic measurement;
4. make full child analysis honor a hard remaining-time token; and
5. rerun short opening gates before any longer attempt.

Do not retune economic weights or seed the known cost-23 route.
