# Anytime whole-game controller v0.14

## Scope and verdict

v0.14 is a proof-neutral audit of source-scoped completion propagation and
target expiry. It adds no search engine, resource, persistence, benchmark
preference, route seed, canonical future action or proof rule. Unrestricted
Deal remains on.

The verified verdict is **PARTIAL**. The v0.13 completion anomaly is diagnosed
and corrected: a scoped physical source completion previously stopped at the
closure assessment/legacy trace boundary. There was no typed event in
`DependencyClosureResult`, no source-satisfaction record in the fresh
milestone residual, and no durable source ledger on the strategic successor,
node or target lineage. Persistence of the same dependency ID after
`SOURCE_BURIED -> SOURCE_EXPOSED_BUT_BLOCKED` could consequently obscure that
the original buried predicate was already complete.

Natural Gate O now carries five trace-completed source facts through replayed
successor creation, exact-TT admission and target lineage. None is silently
reopened. The selected bounded route does not include or consume one, however,
and Gate P admits no source-completion state. Foundation #2 remains absent.

## Propagation architecture

`SourceCompletionEvent` is emitted from fresh physical closure analysis. It
records semantic target and dependency identity, original and fresh dependency
types, the physical satisfier, exact structural state and compact state hash,
replayed actions, completion class, source depths, exposure/actionability/
consumption/integration facts and evidence provenance.

`SourceCompletionPropagationTrace` then records these monotone funnel stages:

1. `TRACE_COMPLETED`;
2. `CONTROLLER_SUCCESSOR_CREATED`;
3. `CONTROLLER_ADMITTED_COMPLETION`;
4. `FRESH_RESIDUAL_PRESERVED`;
5. `LINEAGE_PRESERVED`;
6. `SELECTED_PATH_COMPLETION`;
7. `SOURCE_CONSUMED`;
8. `SOURCE_INTEGRATED`.

Repeated analysis merges stages by event ID. An earlier observation cannot
erase a later admission or consumption. A transient admission loss is cleared
if a lower-cost occurrence of the same exact event is subsequently admitted.
The event reaches `DependencyClosureResult`, `MilestonePrimitiveStep`,
`MilestoneRealizationResult`, `StrategicSuccessor`, `StrategicSearchNode`,
`TargetGrantLineageEntry` and final controller telemetry.

## Physical identity and monotonicity

`PhysicalSourceIdentity` separates an event-local suit/rank/copy provenance
key from its current zone, column and offset. Coordinates are location, never
identity and never canonical state. The repository represents `Card` as a
value object, so arbitrary duplicate-card moves cannot always be distinguished
globally; any inferred reassignment remains diagnostic and proof-neutral.

Fresh exact state is authoritative. Reanalysis of the same exact state cannot
downgrade an exposed physical fact or an integrated source. A same-state
contradiction is labelled `ANALYSIS_DEFECT`. Later legal obstruction is
labelled `SOURCE_BECAME_UNUSABLE` and creates a current blocker without
deleting the historical exposure. Sources removed into a foundation are
reconstructed as integrated.

## Semantic requirements and residuals

`SemanticSourceRequirement` is distinct from a physical copy and records its
target fingerprint, dependency, scope, suit/rank and required copy count.
`SourceRequirementSatisfaction` records the satisfying copy or copies, first
and current exact states, evidence, fresh preservation, copy reassignment and
any explicit reopening reason.

The available satisfaction states are `UNSATISFIED`,
`PARTIALLY_SATISFIED`, `EXPOSED`, `ACTIONABLE`, `CONSUMED`, `INTEGRATED`,
`SUPERSEDED` and `INVALIDATED`. A downgrade must name
`PHYSICAL_COPY_NO_LONGER_SATISFIES`, `REQUIREMENT_SCOPE_CHANGED`,
`ADDITIONAL_COPY_REQUIRED`, `SOURCE_BECAME_UNUSABLE`,
`SEMANTIC_REASSIGNMENT` or `ANALYSIS_DEFECT`.

Fresh residual derivation now starts from exact unsatisfied work plus prior
source satisfactions. Exposure completes the original `SOURCE_BURIED`
subrequirement even when the same semantic dependency becomes the different
follow-on predicate `SOURCE_EXPOSED_BUT_BLOCKED`. The follow-on remains active;
completion of that subrequirement does not complete the whole source chain.
One-copy satisfaction survives an interchangeable-copy preference change,
while a genuine two-copy requirement remains partial until both copies satisfy
it.

## Controller, lineage and portfolio semantics

A replay-valid source-completing successor carries the typed event, current
satisfaction, residual/follow-on blocker and lineage evidence. Only exact-TT
admission awards `CONTROLLER_ADMITTED_COMPLETION`. A trace-completed duplicate
rejected by exact lower-cost dominance is diagnosed as
`STRATEGIC_ADMISSION_LOSS`; metadata loss after admission would be
`CONTROLLER_PROPAGATION_LOSS`.

Lineage stores completed source event IDs, current satisfactions and explicit
follow-on requirement IDs. Scoped completion contributes portable named
harvest without automatically completing the broader target. Portfolio
reanalysis reconstructs current satisfaction from exact state; history helps
interpret the semantic target but cannot override exact facts or protect a
more expensive duplicate.

The full loss vocabulary also distinguishes telemetry-only loss, dependency
type-transition loss, physical attribution loss, residual reopening,
portfolio rescoping, legitimate expiry and an explicit fallback. All records
are bounded diagnostics and planning context.

## Expiry audit

The three-expansion persistence envelope is unchanged. Every natural expired
target boundary is classified as `COMPLETED_BEFORE_EXPIRY`,
`LEGITIMATE_NO_PROGRESS_EXPIRY`, `RESOURCE_LIMIT_EXPIRY`,
`TARGET_TURNOVER_EXPIRY`, `ATTRIBUTION_LOSS_EXPIRY`, `LIFECYCLE_EXPIRY` or
`SUPERSEDED_EXPIRY`. Source-requirement expiry inside a milestone ledger is
reported separately from target-lineage expiry, avoiding mixed counts.

Gate O recorded 24 expiry boundaries: six completed-before-expiry, eight
legitimate no-progress and ten resource-limit. It recorded no target-turnover,
attribution-loss, lifecycle or superseded expiry. This audits the natural
v0.13 population without changing its policy.

## Capability gates and unseen deals

All generic capability Gates A-K pass. They cover the buried-to-exposed-blocked
transition, same-state physical monotonicity, interchangeable and two-copy
requirements, residual removal/no-silent-reopening, admitted versus trimmed
completion, selected-path distinction, lineage transition, true later
re-obstruction, all expiry classes, exposure-to-integration and unchanged
lower-g exact TT dominance.

The focused v0.14 file contains 65 test functions and 72 parameterised cases.
Two deterministic unseen four-suit smokes retained unrestricted Deal, legal
replay and bounded raw/Deal/construction coverage. Seed 14014 naturally
produced a typed source-completion successor; seed 14041 produced no natural
source event in its short envelope. No foundation was required.

## Natural Gate O

Gate O began at the independently replayed machine F1 checkpoint at corrected
`g=21`. Its exact limits remained 90 seconds, 25 strategic expansions,
300,000 tactical nodes, frontier 256, closure beam 192, the existing allocator
tiers and closure limits, and persistence three.

It reached all 25 expansions in about 28 seconds. The selected five-action,
no-Deal suffix added corrected `g=5` and ended replay-valid at total `g=26`,
one Spade foundation, stock 30 and 32 face-down cards. Its path hash is
`f176dd9013e3fdb1`, endpoint hash `30496cf7f013e61f`, and structural hash
`31659973bc6dba50`.

The completion funnel was:

- 40 source-targeted closure attempts;
- 18 source-depth/prerequisite advances;
- five typed trace completions/exposures;
- five replay-valid successors;
- five controller-admitted completions;
- five lineage-preserved completions;
- zero fresh-residual-preservation stages reached by an expanded descendant;
- zero selected-path completions;
- zero reopenings, physical-attribution losses or copy reassignments;
- zero consumptions/integrations, substantial source chains or terminal
  qualifications;
- F1, not F2.

The five physical event rows comprise two Hearts 6 exposed-blocker completion
states and three Diamonds 13 buried-to-exposed-blocked states. This explains
the v0.13 discrepancy: the physical facts were real, but no typed object
previously crossed the controller boundary. Under v0.14 they are durable
through admission and lineage, though the selected route still chooses other
work.

## Untouched Gate P

Gate P was authorized because natural Gate O trace events became durable
controller-admitted completion events. It started from the untouched deal with
`incumbent=None` and no prefix, suit, rank, source, candidate or canonical
action. Its exact limits remained 180 seconds, 50 expansions, 500,000 tactical
nodes, frontier 256, beam 192 and unchanged tier/closure/persistence settings.

It reached all 50 expansions in about 55 seconds and used roughly 441 tactical
closure nodes. The selected replay-valid route had corrected `g=11`, one Deal,
stock 40, 38 face-down cards and no foundation. Its path hash is
`1af0219baaeca71c`, endpoint hash `5149eacdafc4635e`, and structural hash
`4ed5d1c43e1f383f`.

Gate P produced one Hearts trace-completed source event and one replay-valid
successor with lineage evidence, but bounded strategic selection/admission
retained other work. It therefore recorded one
`STRATEGIC_ADMISSION_LOSS`, zero admitted/selected source completions and zero
consumptions/integrations. Two substantial interval milestones completed, but
there was no source-chain completion, terminal qualification, F1 or F2. Its 45
expiry boundaries classified as 21 legitimate no-progress, 23 resource-limit
and one target-turnover expiry. F2 repeatability, optional F3 and optional
whole-game runs were not authorized.

## Proof safety, performance and genericity

Exact TT remains `exact structural Spider state -> lowest corrected g`.
Physical provenance, semantic requirements, event history, propagation traces,
lineage and expiry diagnoses do not enter canonical identity. The only
admissible bound remains mandatory Deals plus the established paid-reveal
bound. Heuristic source history cannot proof-prune.

The allocator tier fingerprint, per-expansion ceilings, dependency-closure
limits and beam are unchanged. Propagation and expiry-audit overhead are
measured separately and remain far below one millisecond in the decisive runs.
Production policy contains no benchmark deal, fixed suit/rank/column, route,
hash, external 119 target or prospective canonical action.

The canonical corrected-172 solution remains replay-valid at 174 explicit
commands, 169 tableau commands, five Deals, F8, path hash
`77d169da2538ba8c` and final-state hash `4e9861540eac570cb`. The machine F1
anchor remains corrected `g=21`, 21 actions, two Deals, Spades, stock 30, 33
face-down, path `924bfd20deac96af`, endpoint `fbea39bb5e2a3a47` and structural
hash `b7522950ea41ad9a`. The independent F1 remains corrected `g=23`, 23
actions, two Deals, stock 30 and 32 face-down.

The definitive complete repository suite passed **1,316 ordinary tests, 37
expected historical xfails and the single inherited warning in 1,110.34
seconds**. No xfail was weakened.

## Precise blocker and next task

The propagation defect is fixed. The remaining natural blocker is downstream:
Gate O admits and preserves completion states in lineage, but none receives the
next fresh expansion and none appears on the selected best-progress route;
Gate P's one trace-completed successor is lost at strategic admission. The
controller therefore does not yet convert durable source exposure into source
consumption, terminal qualification or foundation #2.

If a later task is explicitly authorized, it should audit post-admission
selection and next-expansion continuity for typed source-completion states.
Compare their exact structural economics and candidate priority with the
equal/lower-cost competitors that displace them, and determine whether one
bounded completion representative can be retained without increasing runtime,
nodes, beam, tiers or persistence and without weakening exact TT dominance.
Do not begin the global scheduler automatically.
