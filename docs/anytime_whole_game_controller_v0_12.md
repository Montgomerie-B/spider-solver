# Anytime whole-game controller v0.12

## Scope and verdict

v0.12 corrects completion detection and endpoint selection inside the existing
bounded dependency-closure realiser. It adds no search engine, campaign
corridor, global scheduler, benchmark route, prospective checkpoint, or
resource increase. Unrestricted Deal remains on.

The verified verdict is **FAIL** under the task's hard gate. All generic
capability Gates A-J pass and the closure now behaves correctly on controlled
multi-primitive chains. The natural cost-21 Gate K, however, still converted
three source-depth reductions into zero named source exposures or consumptions.
It reached neither a substantial source-chain completion, terminal
qualification, nor foundation #2. Gate L was therefore not authorized.

## v0.11 return-policy audit

The v0.11 closure already searched through multiple primitive moves. It did
not generally return immediately after the first depth reduction. Two semantic
defects nevertheless made useful prerequisite work look complete:

- completion was tested only by disappearance of the dependency ID, although
  `SOURCE_BURIED` can become `SOURCE_EXPOSED_BUT_BLOCKED` under the same
  `source:{rank}:{suit}` identity; and
- the result was labelled `DEPENDENCY_CLOSED` whenever any starting campaign
  dependency disappeared, even when the specifically requested dependency
  remained open.

Local endpoint ranking also used the latest move's progress evidence instead
of a cumulative assessment against the call's starting source geometry. The
controller treated broad milestone/prerequisite progress as closure success,
so the requested target's completion state was not directly inspectable.

## Completed versus advanced

`ClosureCompletionClass` now exposes:

- `DEPENDENCY_COMPLETED`;
- `SOURCE_EXPOSED`;
- `DEPENDENCY_ADVANCED`;
- `NO_TARGET_PROGRESS`;
- `STRUCTURAL_BLOCKER`;
- `RESOURCE_BOUND`; and
- `TARGET_INVALIDATED`.

`ClosureEndpointAssessment` records the requested dependency kind before and
after, semantic-target validity, physical source keys, depth and blocker
counts, exposure, actionability, consumption, prerequisite progress,
continuation availability, primitive count, and lifecycle summary. These are
all ordering and diagnostic facts with no proof authority.

For an initially buried source, fresh physical exposure completes that scoped
dependency immediately even if the graph retains the same ID as
`SOURCE_EXPOSED_BUT_BLOCKED`. Exposure and consumption are reported
separately. For other dependencies, the specifically requested ID must close
or its scoped predicate must be freshly satisfied. Depth reduction, receiver
creation, workspace preparation, bounded parking, stable rearrangement, or
copy substitution is `DEPENDENCY_ADVANCED`, not completion.

## Multi-primitive continuation and endpoint ordering

After every admitted move, closure applies the move to a fresh exact state,
rebuilds the campaign graph, relocates interchangeable source copies, rebuilds
the blocker description, recomputes lifecycle evidence, and classifies the
cumulative endpoint. An advanced state remains in the unchanged local beam
while the same target is valid and target-relevant continuation remains.

Within this one targeted call the heuristic endpoint order is:

1. naturally removed foundation;
2. requested dependency completed;
3. requested buried source exposed/actionable;
4. cumulative named-source progress;
5. prerequisite-only progress; and
6. unrelated structural change.

Lifecycle debt orders otherwise comparable endpoints inside a completion
class. It never proof-prunes a state. The call may stop on completion,
foundation removal, resource exhaustion, no target-relevant continuation,
fresh structural block, or invalidation. It does not stop merely because a
useful prerequisite occurred.

If completion is not reachable inside the existing grant, the best non-empty,
independently replayed advanced endpoint survives as a
`DEPENDENCY_ADVANCED` result. A separate `RESOURCE_BOUND` diagnosis is used
when cost, node, time, or deadline limits actually end an otherwise live
continuation. An advanced fallback is not reported as dependency closure.

## Outer milestone continuation

The milestone primitive boundary now carries the dependency identity,
coordinate-free semantic identity, completion class, completed flag, source
depth transition, primitive count, advanced-fallback flag, and any
restore/replace obligation. The existing milestone coordinator still performs
fresh analysis after each primitive. It records same-target continuation,
advanced fallbacks, completion timelines, and whether a persisted advanced
target later completed.

`DEPENDENCY_ADVANCED` remains eligible to produce a replay-valid strategic
successor. This preserves useful partial work without falsely counting the
requested dependency complete. Raw legal play, Deal, alternate campaigns, and
construction remain represented.

## Stable structure and temporary debt

Each selected closure sequence summarizes same-suit joins created and broken,
mixed-suit boundaries created and removed, maximum midpoint debt, final debt,
projected compensation accepted/rejected, and stable joins restored or
structurally replaced. A still-open restoration obligation is explicit.

Permanent same-suit dominance is unchanged. A stable break remains admissible
only with named target progress and a bounded exit/compensation route. A mixed
or workspace park still requires a concrete exit. Endpoint selection may look
through a temporary awkward midpoint to a reachable source exposure and may
recognize a superior replacement rather than demanding exact reversal. It
does not require restoration before exposure.

## Capability and smoke results

All generic Gates A-J pass with independent replay where actions are selected:

- A: two separately movable blockers complete in one two-move closure;
- B: receiver creation plus two blockers completes in one three-move closure;
- C: workspace creation plus a two-card blocker run completes in two moves;
- D: a two-park path records midpoint debt and selects exposure;
- E: stable break and later restore/replace are distinguished;
- F: a one-cost grant returns replay-valid `DEPENDENCY_ADVANCED` with
  `RESOURCE_BOUND` rather than false completion;
- G: the same dependency ID resumes from that endpoint and exposes the source;
- H: fresh source-copy substitution completes without stale coordinates;
- I: exposure is recorded on the blocker-removal state with no registration
  move; and
- J: completed/exposed endpoints outrank prerequisite-only endpoints, while
  lifecycle debt orders alternatives within a completion class.

The focused v0.12 file adds 73 passing cases, exceeding the required 52. The
combined v0.7-v0.12 controller cohort passes 366 tests. Two deterministic
unseen four-suit smokes retained unrestricted rules and replay-valid selected
prefixes; one naturally produced a three-primitive source exposure and the
other returned a typed advanced/resource-bound result.

The definitive complete repository suite passed **1,179 ordinary tests with
37 expected historical xfails and the one inherited warning in 1,137.10
seconds**. No historical xfail was weakened.

## Natural cost-21 Gate K

Gate K started from the independently replayed machine F1 checkpoint at
corrected `g=21`. The configured envelope was exactly 90 seconds, 25 strategic
expansions, 300,000 tactical nodes, frontier 256, with the inherited allocator
and closure tranches unchanged. It stopped at the 25-expansion ceiling after
22.970 seconds.

The selected five-action suffix independently replayed at corrected added
`g=5`. It retained one Spade foundation, stock 30, and 32 face-down cards. Its
path hash was `18843bfb94399fdb`, endpoint hash
`30496cf7f013e61f`, and structural/Zobrist hash `31659973bc6dba50`.

Across the explored frontier Gate K recorded:

- 38 targeted closure calls and 200 closure nodes;
- 35 `DEPENDENCY_ADVANCED`, two `DEPENDENCY_COMPLETED`, and one
  `NO_TARGET_PROGRESS` classification;
- 35 advanced states continued inside calls and 35 advanced fallbacks;
- 11 advanced targets persisted across outer boundaries, with zero later
  completions;
- 36 selected closure primitives, average 0.947 per call and maximum two;
- three source-depth reductions and three copy substitutions;
- zero source exposures and zero source consumptions;
- 22 bounded temporary-park exits;
- two stable joins broken, zero restored/replaced in selected endpoints, and
  two accepted projected compensation records;
- zero substantial source-chain completions, zero terminal qualifications,
  and no F2; and
- 2.555 seconds total closure time with 0.119 seconds maximum per call.

Gate K independently reproduced its corrected cost, stock, foundation count,
endpoint, path hash, and structural hash. It shows that typed advancement and
same-target persistence now work naturally, but they still do not complete a
natural buried source.

## Gate L decision

None of the five authorization conditions held. Gate K did not remove F2,
expose or consume a natural named source after prerequisite/depth progress,
complete a substantial source chain, reach terminal qualification, or later
complete one of the 11 persisted advanced targets. The untouched 180-second
Gate L was not run. Repeatability, optional F3, and optional whole-game runs
were therefore not authorized.

## Proof safety and genericity

Unrestricted Deal remains on. Exact TT remains `exact structural state ->
lowest corrected g`. Completion class, endpoint preference, lifecycle debt,
source history, continuation count, and advanced fallback metadata do not
enter structural identity. The admissible Deal/reveal lower bound is
unchanged. No closure status or bounded failure may proof-prune.

Production policy contains no benchmark route hash, canonical solution load,
external 119 target, fixed suit order, rank/column path, or prospective future
action. No wall-clock, expansion, tactical-node, closure, beam, milestone, or
allocator ceiling increased.

## Precise remaining blocker and next task

The remaining blocker is no longer completion detection on a generic chain.
It is natural completion conversion: Gate K generated 35 advanced fallbacks
and preserved 11 of their targets across strategic boundaries, yet none later
reached exposure. Natural closure sequences selected at most two primitives,
and their three depth reductions ended as further advanced/resource-bound
states rather than completed source chains.

If a later task is explicitly authorized, it should perform a trace-level
audit of those 11 persisted natural target identities and their next fresh
candidate sets. The goal should be to identify whether target turnover,
candidate attribution after a bounded park/stable break, or restore/replace
ordering loses the concrete next blocker action. Preserve every current
resource and proof limit. Do not begin a new general search engine or global
scheduler.
