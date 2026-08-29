# Anytime Whole-Game Controller v0.10

**Status:** implemented and diagnostically verified; PARTIAL
**Base:** `61b76bd50b33557e2f1d3c7cf01aae2f0bee440d` (`agent/anytime-whole-game-controller-v0-9`)
**Rule profile:** MobilityWare four-suit Spider with Unrestricted Deal ON

## Outcome

v0.10 adds semantic same-target persistence, residual-predicate rebuilding and
a narrow fresh-descendant actionability adapter above the existing v0.8
realisers. It also separates primitive results, stock-transition checkpoints,
substantial structural milestones and foundations, and makes a purposeful Deal
create a post-Deal conversion obligation.

All eight capability gates pass. The natural cost-21 Gate I and authorized
untouched Gate J independently replay, preserve exact scoring and stay inside
their unchanged search envelopes. Gate J generated two substantial interval
outcomes across its explored frontier instead of counting one-action joins or
Deals as substantial completion. Its selected route nevertheless stopped with
no foundation and an actionable source-chain residual at two of three scoped
requirements. Foundation #2 was absent, so the hard-gate verdict is
**PARTIAL**.

## v0.9 blocker

v0.9 aggregated cheap tactical work into milestones and admitted purposeful
stock progression, but an interval or source-chain target normally disappeared
after the first primitive because fresh analysis regenerated a different
physical graph or portfolio shape. The untouched selected route consequently
took all five Deals to stock zero without a foundation. Transition checkpoints
also contributed to the same generic milestone count as structural
construction, allowing stock movement to look like completion.

v0.10 addresses these two representation failures without restoring expensive
whole-campaign search, changing the allocator ceilings or adding another broad
search engine.

## Semantic target identity

`MilestoneTargetIdentity` describes the structural objective rather than its
current tableau coordinates. Depending on target type it carries campaign,
objective, suit, rank interval, structural dependency roles, receiver
requirement, workspace lifecycle, supply requirement or terminal goal.
Column numbers and transient physical locations are excluded.

The same target may therefore survive changed columns, changed fragments and
interchangeable duplicate-card assignment. Copy substitution is explicit
telemetry rather than target invalidation. The identity is planning metadata;
it does not enter canonical Spider state or the transposition key.

## Residual predicates

After every accepted primitive, conversion independently replays the action,
builds a fresh state, reanalyses campaign, dependency and construction facts,
evaluates the original semantic predicate and derives only the unsatisfied
requirements. `MilestoneResidualTarget` records progress, blockers, available
realisers, status and the next bounded candidate.

A residual can be `ACTIONABLE`, `STOCK_BLOCKED`, `COMPLETE` or `INVALID`.
Fresh portfolio failure alone is not invalidation. Invalidation requires a
contradictory exact fact, loss of the structural objective, an expired envelope
or another explicit invalidation condition.

## Fresh-descendant actionability and blocker remapping

`milestone_actionability.py` is a thin adapter over existing v0.8 mechanisms.
It does not search. It maps a fresh residual blocker to an existing tactical
demand and realiser:

- buried source, exposed obstruction, mixed overlay and absent receiver map to
  dependency closure;
- available fragments, a missing interval and supplied-but-unconsumed material
  map to same-suit construction;
- workspace lifecycle debt maps to existing workspace demands;
- terminal assembly maps to the existing terminal-qualified foundation path;
- future-only exact material maps to epoch progression.

Conversion continues when a useful primitive changes blocker type even if a
single scalar progress measure is unchanged. The bounded loop remains
`existing primitive -> replay -> fresh analysis -> residual remap`; step,
expansion, time and tactical-node envelopes are unchanged.

## Outcome classes and substantial completion

Every realized milestone is classified as one of:

- `PRIMITIVE_RESULT`;
- `TRANSITION_CHECKPOINT`;
- `SUBSTANTIAL_STRUCTURAL_MILESTONE`;
- `FOUNDATION`.

A one-action same-suit join remains desirable construction but is only a
primitive result. A substantial outcome requires coherent multi-step structure:
a multi-rank interval, a multi-requirement source chain, a completed receiver
or workspace/supply lifecycle, terminal qualification or foundation removal.
A Deal is a transition checkpoint and never earns substantial-completion
credit merely by reducing stock.

Substantial scope is derived from the campaign graph, fragments, receiver and
workspace/supply context. It contains no benchmark suit, interval, column or
route constants.

## Persistent-target continuity and admission

The controller carries a live semantic identity, fresh residual target,
bounded conversion history and post-Deal obligations across strategic
expansions. A target-compatible child is preferred while the target remains
actionable and inside its envelope, but alternative construction, campaign,
workspace, Deal and raw legal families remain admitted.

Same-target ordering prefers lower corrected cost, more predicate progress,
less remaining debt, fewer mixed-suit boundaries, more stable joins, better
workspace and better next-row reception. These are heuristic ordering rules,
not proof pruning. Exact-state admission remains lower corrected `g`; contextual
milestone completion is attached to the cheaper exact-state route before TT
admission rather than creating a second structural state identity.

## Post-Deal obligations and successive-Deal discipline

A purposeful Deal records the promised semantic target, exact row, reason,
material status and a bounded post-Deal obligation. Fresh analysis refreshes
that obligation to `MATERIAL_AVAILABLE`, `ACTIONABLE`, `CONVERTED`,
`STOCK_BLOCKED`, `INVALID` or `EXPIRED`.

An actionable obligation creates ordering debt and is placed ahead of another
purposeful Deal when an existing realiser can consume it. A stock-blocked
obligation does not make Deal illegal, and Unrestricted Deal remains ON. Deal
itself is not structural fulfilment, and transition credit is binary rather
than cumulative stock reward. Raw legal Deal and fallback successors remain
available.

## Whole-deal construction and permanent-move dominance

Current and late-removal suit construction remains in the portfolio alongside
the active target. Small same-suit joins are retained as valuable primitive
work even though they are not substantial milestones.

Stable same-suit joins dominate equal-immediate-cost mixed-suit parks when
reveal, workspace, stock reception and campaign effects are comparable. A
mixed-suit park must expose a concrete compensating benefit and retains an exit
route and estimated rehandling debt. Same-suit joins, mixed boundaries and
lifecycle debt are telemetry/order features only; none is an admissible proof
bound.

## Capability gates

- **A — fresh remapping:** a coordinate-free interval identity persists from
  two-of-three to completion across a fresh descendant.
- **B — blocker transition:** mixed-overlay/receiver/missing-interval debt maps
  through dependency closure to run construction and replays to achievement.
- **C — copy substitution:** an interchangeable physical fragment completes
  the same semantic identity.
- **D — outcome classification:** a one-join result is primitive while a
  coherent two-join interval is substantial.
- **E — transition semantics:** Deal is a checkpoint, creates an obligation and
  is not structural completion.
- **F — actionable debt:** fresh post-Deal debt selects construction while Deal
  remains legally available; stock-blocked debt is distinguished.
- **G — bounded continuity:** a target survives multiple strategic expansions
  and reaches achievement without removing raw Deal/fallback families.
- **H — terminal conversion:** a legal three-primitive K-A bridge reaches the
  unchanged terminal predicate and independently replays to a foundation.

Two shuffled four-suit smokes construct generic identities and residual facts,
retain Deal/fallback availability, respect their short deadlines and replay
legally.

## Gate I: natural cost-21 state

Gate I retains the v0.9 configuration: 90 seconds, 25 strategic expansions,
300,000 tactical nodes, frontier 256 and 4 seconds / 12,000 allocator nodes per
expansion. It starts from the independently replayed machine first-foundation
state with corrected `g=21` and no route seeding.

The final bounded run used all 25 strategic expansions and selected a
replay-valid three-action route with added `g=3` (`g=24`). It retained the
existing Spade foundation, stock 30 and 32 face-down cards. Across the frontier
it recorded 22 primitive outcomes, eight executed conversion primitives, four
blocker-type transitions, two transition checkpoints, no substantial milestone
and no terminal qualification. The selected route made no Deal, materially
reducing transition-driven stock progression while preserving real tableau
progress. This is authorization condition 5 for Gate J; it is not F2 success.

## Gate J: untouched deal

Gate J was therefore authorized with the unchanged v0.9 untouched envelope:
180 seconds, 50 strategic expansions, 500,000 tactical nodes, frontier 256 and
the same per-expansion allocator ceilings. It used no prefix, checkpoint,
campaign, suit, column or action seed.

The bounded run used all 50 strategic expansions and selected a replay-valid
eight-action, corrected-`g=8` route ending at stock 40 with 38 face-down cards.
Its path hash was `7471e6f65911e7b3` and endpoint hash
`5149eacdafc4635e`. Across the explored frontier it recorded 24 primitive
outcomes, 24 executed conversion primitives, 13 transition checkpoints and two
substantial interval outcomes. The selected persistent source-chain conversion
performed two primitives at cost four, then remained an actionable bounded
miss at two of three scoped requirements with `SOURCE_BURIED` debt. Its
post-Deal obligation remained actionable rather than being falsely marked
converted.

No foundation was removed. F1, F2, deterministic F2 repeat, F3 and optional
whole-game continuation were therefore not authorized.

## Proof safety and genericity

Canonical exact state, corrected MobilityWare cost and lower-`g` TT dominance
are unchanged. The only proof pruning remains the pre-existing admissible
mandatory-Deal/paid-reveal bound. Semantic identities, residual blockers,
obligations, outcome classes, rehandling debt and bounded misses have
`proof_pruning_allowed=False` and may order search only.

Production code contains no benchmark deal, route, suit preference, rank
interval, column, external score or canonical action sequence. Tests and the
diagnostic contain fixtures and expected hashes only as verification data.

## Verification

The 52 focused v0.10 tests pass. The combined v0.10 through v0.7 controller
cohort passes 194 tests. Wider focused cohorts passed 434 controller/epoch/deal
tests, 225 construction/workspace/campaign/removal tests with the same 37
historical expected-invalid xfails, and 131 engine/replay/accounting/identity
tests. The complete repository suite passed **1007 tests with 37 xfails and the
one existing warning in 1146.78 seconds**.

## Verdict, limitation and precise next task

The verified verdict is **PARTIAL**. Fresh-descendant remapping works, blocker
type can change without collapsing the semantic target, two coherent
substantial intervals were completed across the untouched frontier, and
transition-only stock progression was materially reduced. F2 remains absent.

The precise blocker is selected-route conversion of an actionable substantial
source-chain residual after it reaches two of three scoped dependencies. The
adapter continues to identify `SOURCE_BURIED`, but the existing dependency
closure grant does not consume the final requirement inside the unchanged
four-step/three-expansion envelope, and the post-Deal obligation consequently
does not reach structural conversion.

The recommended next development task is a focused audit of dependency-closure
candidate selection for the final buried-source requirement, including why the
fresh exact graph exposes the blocker but the existing realiser cannot consume
it. Preserve all current budgets, broad successor families, permanent-move
dominance and proof rules. Per the hard gate, do not start v0.11 or the global
backward/forward scheduler automatically.
