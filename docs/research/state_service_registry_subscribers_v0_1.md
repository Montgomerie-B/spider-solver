# Registry Subscriber Consolidation v0.1

## 1. Verdict

`REGISTRY_SUBSCRIBERS_READY`

Completion cash-out, epoch transition, and ordinary search can now express
different interests in one registry-owned state/credit service request.  The
subscriber arm has one authoritative request and at most one execution handle,
preserves the existing reservation priorities and one-per-kind quotas, passes
S1–S7, retains the StateServiceRegistry arrival/reopening lifecycle, and leaves
production defaults unchanged.

The quantitative result is narrower than the architectural result.  Registry
v0.1 had already prevented multiple heap handles for one request, so this panel
found four independent reservation *ownership claims* but zero actual duplicate
live handles and zero executions to eliminate.  The migration removes the
remaining ambiguity about who owns protection and completion diagnostics; it
does not claim a search-speed improvement.

## 2. Old reservation ownership model

The registry owned ordinary `(state, credit)` request lifecycle and its only
live handle, but completion and epoch protection were still encoded directly
on `StrategicSearchNode` instances in the frontier.

At every controller iteration, `_reserve_completion_representative` selected at
most one eligible completion opportunity, changed its node-local status to
`RESERVED`, and rebuilt its heap priority.  `_reserve_epoch_transition_representative`
did the same for at most one eligible transition.  Frontier trimming then
searched those node-local markers and preserved the completion item first and a
different epoch item second.  Pop-time accounting also treated the marker as
the authority for spending the entitlement.

These functions did not create new nodes at the authoritative starting commit:
they annotated already-live registry handles.  Consequently the old model had
independent policy ownership, but Registry v0.1's one-handle invariant already
prevented an actual duplicate execution representation.

## 3. Subscriber contract

Subscriber identity is separate from the unchanged service identity:

`(canonical state, strategic credit, CURRENT_STRATEGIC_SUCCESSORS, BEST_ARRIVAL_STRATEGIC_NODE_V0_1)`

The bounded subscriber kinds are exactly `ORDINARY`, `COMPLETION_CASH_OUT`, and
`EPOCH_TRANSITION`.  A request stores at most one record per kind.  Each record
contains active/inactive state, the existing ordering facts, policy quota ID,
creation/removal reason, attachment/satisfaction counts, and the last shared
execution result.  It holds no `StrategicNode` and no scheduler/campaign state.

Duplicate attachment updates the existing record.  Removing one subscriber
does not affect the others.  Removing the final subscriber from unattempted
live work defers its single handle rather than marking it attempted.  A service
completion creates one immutable `ServiceExecutionResult` object and gives the
same object reference to every active subscriber diagnostic.

Cheaper arrival behavior remains request-scoped, not subscriber-scoped: the
arrival version advances once, the request reopens once, active interests stay
attached until the existing qualification logic revalidates them, and no
subscriber can activate a second handle.  Shared eviction retains subscriber
records and one later reactivation remains the maximum.

## 4. Completion migration

The existing completion selector remains the policy calculator: qualification,
freshness checks, lower-g supersession, `rank_completion_opportunities`, the
normal competitor diagnostic, and the global quota of one are unchanged.

In subscriber mode its chosen `RESERVED` result is immediately transferred to
the matching registry request as a `COMPLETION_CASH_OUT` subscriber containing
the existing rank tuple and opportunity ID.  The persistent frontier node is
returned to `QUALIFIED`, so it is no longer the owner.  Heap ordering and pop
execution transiently project the registry entitlement back to `RESERVED` for
the existing downstream adapter.  Completion-first trim protection reads the
registry subscriber, not the persistent node marker.

When the request executes, completion accounting and harvest assessment still
run once.  The subscriber receives the same execution result as ordinary
ownership and releases its active quota entitlement after satisfaction.
Legacy/arm-A mode continues to call the original node-owned path unchanged.

## 5. Epoch-transition migration

The existing epoch selector likewise retains qualification, exact-TT/lower-g
checks, `EpochTransitionOpportunity.ordering_key()`, authorization ID handling,
stock/epoch semantics, and the global quota of one.

Subscriber mode transfers the selected opportunity ID and ordering tuple into
an `EPOCH_TRANSITION` subscriber, neutralizes the persistent node marker, and
uses transient projection for the identical priority, trim, and pop behavior.
The completion entitlement still wins a direct protected-slot conflict; an
epoch entitlement on another request receives the next protected slot.  If
both interests name one request, both quota entitlements refer to its one live
handle and one execution.

## 6. S1–S7 results

| Scenario | Result | Deterministic evidence |
|---|---|---|
| S1 ordinary + completion | Pass | One request, two interests, one handle, one execution. |
| S2 ordinary + epoch | Pass | One request, two interests, one handle, one execution. |
| S3 completion + epoch | Pass | Both special records receive the identical immutable result object from one execution. |
| S4 ordinary + completion + epoch | Pass | Three active interests still produce one handle and one execution; three subscriber satisfactions are recorded. |
| S5 subscriber expiry | Pass | Completion may expire while epoch remains and vice versa; the remaining entitlement keeps the request live. |
| S6 cheaper shared arrival | Pass | One request/version reopening, unchanged three-record subscriber set, one replacement handle, and the old shared handle rejected before analysis. |
| S7 shared eviction/reactivation | Pass | One `DEFERRED` request retains all three subscribers, receives one reactivation handle, and executes once. |

Additional tests cover duplicate subscriber coalescing, last-subscriber defer,
exact legacy/subscriber priority equality, subscriber-based trim protection,
one-per-kind selection quotas, switch constraints, and unchanged defaults.
The 14 new subscriber tests plus all 13 StateServiceRegistry v0.1 tests passed
(`27 passed`).  The full relevant completion, epoch, controller, priority,
STATE_LOCAL, and exact/collision-safe identity selection passed (`261 passed in
91.79s`).  The final repository-wide suite passed (`2017 passed, 37 xfailed,
1 pre-existing warning in 1457.71s`).

## 7. Priority/quota preservation

Before migration, completion status inserted bounded representative rank 0 in
`_node_priority`; epoch status inserted rank 1; absence of either used rank 2.
Completion trim protection was selected first, followed by a distinct epoch
representative.  Each selector chose only its single strongest eligible item.

After migration, `_subscriber_node_priority` transiently reconstructs the same
node status and delegates to the unchanged `_node_priority`.  A deterministic
test proves tuple-for-tuple equality when completion and epoch both apply.
Subscriber-mode trimming directly checks the authoritative subscriber kinds
but preserves the same completion-first/epoch-second entitlement order.

The frozen peak active quota usage was exactly one completion and one epoch,
never above one.  A request subscribed by both may account against both policy
entitlements, but has one live handle and consumes one execution.  Frontier
capacity and all configured quota values are unchanged.

## 8. Duplicate representation reduction

The three subscriber runs measured four special ownership claims: one
completion and three epoch.  All four attached to existing ordinary registry
requests and all four executions satisfied more than one subscriber.  The
quantitative breakdown is:

- duplicate service submissions already coalesced by the registry: 740;
- special interests sharing an existing request/handle: 4;
- independent live representations in the old registry arm: 0;
- duplicate live representations actually prevented by this migration: 0;
- special-subscribed live representations actually used: 4;
- shared executions / executions satisfying multiple subscribers: 4 / 4;
- executions avoided relative to arm A: 0.

This is not contradictory.  The old completion/epoch code independently owned
priority/protection annotations, but the preceding registry migration already
forced those annotations onto one request handle.  Subscriber consolidation
therefore removes ownership ambiguity and centralizes diagnostics without
claiming nonexistent work elimination.  It also coalesced 744 repeated
subscriber attachment attempts into existing records.

Natural observed request combinations were 613 ordinary, one
ordinary+completion, and three ordinary+epoch.  No frozen state carried both
special interests simultaneously; S3/S4 provide deterministic overlap evidence
without adding an outcome-selected fourth fixture.

## 9. Frozen behavioural comparison

The committed plan used P0/4925153, P2, and P7 with 80 strategic expansions,
120,000 tactical nodes, 240 seconds, frontier 256, successor cap 10, credit 0–4,
seed 0, scheduler and tactical allocation enabled, `COMMON_STAGE0 +
STATE_LOCAL`, StateServiceRegistry enabled in both arms, and no workspace or
resource-planner experiment.

| Deal | Arm | Strategic/service | Tactical | Elapsed (s) | TT new/improved/suppressed | Min FD | Stock rows | Foundations | Best progress |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 | Registry ownership | 80/80 | 19,756 | 177.301 | 142/0/235 | 38 | 3 | 0 | `57e776f099a0b7c6` |
| P0 | Subscribers | 80/80 | 19,399 | 178.967 | 142/0/235 | 38 | 3 | 0 | `57e776f099a0b7c6` |
| P2 | Registry ownership | 80/80 | 24,548 | 122.148 | 120/12/279 | 41 | 4 | 0 | `4d67539f2e5b6949` |
| P2 | Subscribers | 80/80 | 24,239 | 124.272 | 120/12/278 | 41 | 4 | 0 | `4d67539f2e5b6949` |
| P7 | Registry ownership | 80/80 | 3,706 | 104.769 | 151/0/211 | 38 | 1 | 0 | `4dcad73819bb4098` |
| P7 | Subscribers | 80/80 | 3,875 | 106.746 | 151/0/211 | 38 | 1 | 0 | `4dcad73819bb4098` |

Every pair preserved strategic expansions, service executions, credit
distribution, retained successors, face-down, stock, foundations, and best
replayable progress.  P0 and P7 had identical trajectory digests.  P2 changed
one generated/suppressed successor while preserving all endpoints and its
12 cheaper arrivals and 16 request reopenings; no shared stale handle arose.
Because exact projected priority is regression-tested and the subscriber arm
adds bookkeeping time inside bounded tactical realisers, the P2 difference is
most consistent with time-sensitive tactical allocation jitter.  That is an
inference, not a claimed policy improvement or a duplicate-removal effect.

All replay/corrected-cost checks passed, proof-prune counts were unchanged at
zero in this envelope, and no run reached a foundation.

## 10. Runtime/memory effect

Subscriber/control elapsed ratios were `1.00940`, `1.01739`, and `1.01887`;
median `1.01739`, range `1.00940–1.01887`.  This is a measured 0.94–1.89%
increase, not a performance gain.  Tactical-node deltas were -357, -309, and
+169 respectively under time-bounded tactical work.

The shallow registry footprint was 669,884 bytes across subscriber arms versus
477,368 bytes across ownership arms: +192,516 bytes, or +40.33%, approximately
314 bytes per service request.  Most of this is the explicit ordinary
subscriber record and observed-combination set on all 613 requests; only four
special records were added.  The estimate excludes shared witness object
graphs and no `StrategicNode` is duplicated into a subscriber.

## 11. Remaining independent ownership mechanisms

In subscriber mode, completion and epoch selection functions remain solely as
unchanged policy calculators; their returned `RESERVED` markers are immediately
neutralized, and registry entitlements own priority, trim preservation, pop
execution, shared results, expiry, and diagnostics.  Legacy/arm-A mode retains
the old path for controlled comparison.

Other frontier-preservation owners remain outside this migration: foundation
checkpoint diversity, pre-foundation geometry diversity, strongest live
same-campaign continuation, protected conversion/residual maturation, and
ordinary bounded frontier capacity.  Their identities and quotas remain
unchanged.  This task also leaves scheduler strategy, tactical allocation,
successor generation, exact TT dominance, proof logic, resource planning,
workspace policies, and the known foundation-demand gap untouched.

## 12. One next bounded migration task

Migrate the strongest-live same-campaign continuation reservation into one new
registry subscriber kind while preserving its current global quota of one and
its exact priority/expiry behavior.  The experiment should compare ownership
only, prove shared handling with ordinary/completion/epoch interests, and add no
portfolio allocation policy.
