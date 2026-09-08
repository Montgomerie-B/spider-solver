# StrategicProject Lifecycle v0.1

## 1. Verdict

`STRATEGIC_PROJECT_LIFECYCLE_READY`

The controller can now represent “continue pursuing this campaign” as one
persistent purpose across changing exact states.  In the migration arm, a
`StrategicProject` owns semantic target, candidates, lifecycle, progress and
the inherited bounded expiry contract.  `StateServiceRegistry` remains the
sole owner of exact arrivals, requests, versions, handles, deferral and
execution.  Projects contain no game states or `StrategicSearchNode` objects,
have no proof authority, and production defaults remain unchanged.

P1–P10 pass.  The frozen P0/P2/P7 panel completed all six 80-expansion arms
with replay integrity, zero handle-invariant errors and identical measured
Spider outcomes in face-down cards, stock rows and foundations.  Search
trajectories were not byte-identical; section 9 explains this expected
allocation-visible difference.

## 2. Existing same-campaign continuation model

The code authority at the starting commit behaved as follows.

1. A successful dependency-closure result creates a structural investment.
   Its `objective_id` is the closure result's `campaign_id`, currently the
   foundation-campaign label `{SUIT}#{COPY_INDEX}` (for example `H#1`).
2. A continuation credit is created only when that investment is not already
   harvested, contains actual harvest, and has campaign-specific value.
3. A successor is compatible only when its `source_project_id` exactly equals
   the live credit's `objective_id`.
4. Every live credit contributes its existing `ordering_key` to node priority.
   Frontier trimming sorts by the complete node priority and protects the
   first live continuation it encounters: the strongest live candidate.
5. The protected-frontier quota is one globally.  It does not add width,
   expansions, nodes or time.
6. Fresh campaign analysis rebuilds the named dependency graph.  The credit is
   harvested when the campaign has no outstanding non-terminal dependency,
   invalidated when that named campaign disappears, and expires at the first
   of: descendant depth greater than its allowance, elapsed time greater than
   or equal to its allowance, or corrected cost greater than its allowance.
   The reusable primitive also supports same-objective supersession, although
   the current controller caller does not supply that condition.
7. Changed named dependencies produce `REPLANNED`; generic novelty, workspace
   activity and strategic-credit widening do not.
8. After expansion, a compatible successor inherits the credit; a successful
   new closure can issue a new credit.  The associated investment ledger is
   harvested, invalidated, expired or superseded with the credit.
9. Milestone/residual-target priority precedes continuation priority.
   Target-grant lineage, campaign-epoch scheduling, protected conversion and
   completion/epoch reservations are separate mechanisms.  They may provide
   campaign facts or compete in global priority, but they do not define the
   continuation identity.

Thus the old mechanism already contained a small project-shaped contract, but
its durable purpose lived on whichever frontier node carried the credit.

## 3. StrategicProject contract

`StrategicProjectRegistry` supports exactly one v0.1 kind:
`SAME_CAMPAIGN_CONTINUATION`.  A project contains:

- a stable internal project ID;
- a semantic campaign target;
- a creation baseline of named outstanding dependencies, corrected cost,
  depth and elapsed time;
- references to one or more registry-owned `ServiceRequestKey` values;
- candidate-local copies of the existing continuation allowance/evidence and
  priority facts, but no node or state;
- at most one selected candidate;
- explicit activity and semantic-progress evidence;
- `RUNNABLE`, `BLOCKED`, `ACHIEVED`, `EXHAUSTED` and `INVALIDATED` lifecycle
  states;
- a hard `proof_pruning_allowed=False` contract.

No new score or numeric budget was introduced.  Candidate continuations retain
the old cost, descendant-expansion and elapsed-time allowances exactly.

## 4. Project identity

Identity is `(SAME_CAMPAIGN_CONTINUATION, campaign label)`, hashed only to form
the stable internal project ID.  The campaign label is not a digest, node ID or
path token: it is the existing semantic foundation target, suit plus physical
copy index.  The current compatibility predicate already compares this exact
label through `successor.source_project_id == credit.objective_id`.

Consequently, changing from candidate state A to compatible state B preserves
project identity.  A different suit/copy target creates a different project.
The implementation detects inconsistent hash/index mappings as identity
collisions; the frozen panel recorded zero.  Campaign epoch is deliberately
not added to identity because the pre-existing continuation contract also
persists the suit/copy objective across fresh analysis.

## 5. Candidate/service relationship

A candidate is a `ServiceRequestKey`, so it always names a real canonical
state, state-local strategic-credit level, coverage mode and adapter context.
The project never copies the registry witness.  Multiple candidates may enter
one project, and the data model permits multiple projects to reference one
request without combining their state facts.

The existing complete node-priority tuple selects the globally strongest live
candidate.  Its project attaches a
`STRATEGIC_PROJECT_CONTINUATION` subscriber to that existing request.  Changing
the winner releases the old subscription and attaches the new one without
changing either project or state identity.  Completion and epoch interests can
share that request.  The registry still supplies one handle and one execution,
and the candidate stores the same immutable `ServiceExecutionResult` reference
seen by the other subscribers.

Strategic credit remains registry-owned service breadth.  Project identity is
purpose persistence.  Neither is derived from the other, and ordinary children
remain CLEAN under state-local propagation.

## 6. Lifecycle/expiry

`RUNNABLE` means at least one compatible request can represent the valid
target.  `BLOCKED` means the target persists but no compatible request is
currently live.  A later compatible candidate returns it to `RUNNABLE`.
`ACHIEVED` maps only to the historic named-campaign fully-harvested predicate.
No new terminal success was invented.  `INVALIDATED` maps to disappearance of
the exact named campaign (or the existing supersession result).

`EXHAUSTED` is the project-level terminal state for consumption of the old
continuation envelope without achievement.  Telemetry separately labels this
as an expiry.  The exact legacy predicate and reason are obtained by the same
`refresh_continuation_credit` function.  P8 proves equality at all three
boundaries.  Expiry removes only the project subscriber; the state and request
remain, ORDINARY or another subscriber may keep the request live, and no proof
prune occurs.

Cheaper arrival remains a registry operation: the arrival version advances,
affected requests reopen once, the stale handle is rejected, and the project
updates its candidate version without duplication.  Deferral likewise leaves
the project intact; current registry activation can later restore one handle.

## 7. Activity versus semantic progress

Project activity is one actual execution of the selected registry request.
Semantic progress is narrower: a named dependency must disappear while the
remaining dependencies are a subset of the prior set, or the existing
fully-harvested predicate must achieve the campaign.  The resulting evidence
records request, execution ordinal, exact dependency IDs closed and achievement.

New node IDs, new state digests, generic novelty, workspace creation/use,
strategic-credit widening and mere successor generation receive no progress
credit.  Across the frozen panel, eight selected project services produced one
semantic progress event and seven activity-without-progress events.  This 8:1
service/progress observation is diagnostic input for later allocation, not a
claim that the strategy is poor.

## 8. P1–P10 results

| Scenario | Result | Evidence |
|---|---:|---|
| P1 project creation | Pass | One project with the exact campaign target and no proof authority. |
| P2 compatible merge | Pass | Two request keys attach to one stable project; one reuse. |
| P3 incompatible separation | Pass | Different campaign labels create different projects. |
| P4 candidate replacement | Pass | The stronger existing-priority candidate replaces the subscription; project identity survives. |
| P5 shared request | Pass | ORDINARY, completion, epoch and project interests share one request, handle, execution and result object. |
| P6 cheaper arrival | Pass | One reopen, one version update, stale old handle rejection and no duplicate project. |
| P7 defer/reactivate | Pass | Project remains valid through DEFERRED; one reactivation and one execution. |
| P8 expiry | Pass | Depth, elapsed and corrected-cost boundaries exactly match legacy reasons; only project entitlement is removed. |
| P9 semantic progress | Pass | Removing one named dependency records exactly one progress event. |
| P10 activity only | Pass | Unchanged named prerequisites record one activity and zero progress. |

The focused project, registry, subscriber and continuation suite passed 86
tests before the frozen run.  The broader continuation/registry/priority/
identity selection passed 873 tests with 12 expected failures.  One legacy
90-second, exact-node fixture missed its node under full-suite load and passed
immediately in isolation (59.87 seconds); the full remainder then passed 2,029
tests with 37 expected failures and one pre-existing return-value warning.
Combined, all 2,030 repository tests passed.

## 9. Frozen behavioural comparison

The plan froze P0/P2/P7, arm order and the inherited 80-expansion, 120,000-node,
240-second envelope before formal treatment.  A short implementation smoke
already showed natural P0 continuation creation, so no fourth fixture was
selected.

| Deal | Exp. delta | Service delta | Tactical-node delta | Runtime ratio B/A | Face-down delta | Stock-row delta | Foundation delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| P0 | 0 | 0 | +281 | 0.998 | 0 | 0 | 0 |
| P2 | 0 | 0 | -729 | 0.944 | 0 | 0 | 0 |
| P7 | 0 | 0 | -1,892 | 0.892 | 0 | 0 | 0 |

All best-progress routes replayed to the stored exact state and corrected cost;
all runs ended at 80 expansions; all maximum foundation counts were zero.

Decision traces differed on all three deals.  This is explainable and expected
for the explicit migration contract: legacy priority metadata exists on every
live credit-bearing node, while project mode grants the quota-of-one
continuation reservation only to the currently selected project candidate;
non-selected candidates remain ordinary services.  Time-bounded tactical work
also showed run-to-run sensitivity (P0's unchanged legacy digest differed
between two formal-development passes).  No priority tuning was used to force
trajectory equality.  The selected candidate's full old priority tuple,
completion/epoch projection, global quota, execution semantics and expiry are
preserved.  Outcome parity—not a speed gain—is the supported conclusion.

Natural project totals were: 9 created, 5 reused, 14 candidates attached, 4
candidate replacements, 19 project subscription events, maximum 4 concurrent
projects, maximum 2 candidates per project, and maximum observed lifetime 78
strategic expansions.  One cheaper-arrival revalidation occurred naturally.
Natural frontier trimming did not exercise defer/reactivate for a project
candidate; deterministic P7 supplies that required evidence.  One project
expired/exhausted, none achieved or invalidated, and no identity collision
occurred.

## 10. Memory/runtime cost

The deterministic shallow project footprint was 1,480 bytes on P0, 2,112 on
P2 and 2,232 on P7: respectively 0.64%, 1.06% and 0.94% of the already-enabled
registry footprint.  The summed three-run diagnostic is 5,824 bytes.  It does
not include duplicated nodes, states or witness graphs because none are stored.

Project/legacy runtime ratios were 0.998, 0.944 and 0.892 (median 0.944).  These
single, time-sensitive samples establish no slowdown signal and no speedup
claim.  The prior ORDINARY subscriber memory cost is intentionally unchanged.

## 11. Architectural findings

The experiment cleanly groups campaign target, concrete structural-investment
harvest, continuation allowance, named dependency progress, candidate
replacement and terminal expiry into one project lifecycle.  It also shows
that campaign milestones and residual targets can eventually contribute richer
project progress evidence, while target-grant lineage can contribute portable
commitment evidence.  Those concepts were not migrated here.

Foundation checkpoint diversity, pre-foundation geometry diversity, protected
conversion/residual maturation, the tactical resource planner, workspace
experiments, completion cash-out and epoch-transition ownership remain
unchanged.  Global priority still belongs to the controller.  The project
subscriber is only the current service representation; it is not project
identity.  This is therefore the intended first Stage-2 lifecycle extraction,
not a hidden portfolio allocator.

## 12. One next bounded migration task

Introduce a bounded `StrategicProject` portfolio/service allocator for the
existing continuation projects only: consume their lifecycle, candidate,
service-execution and semantic-progress records to choose the same single
registry entitlement, and add explicit inherited effort accounting without
adding project kinds or tuning Spider heuristics.
