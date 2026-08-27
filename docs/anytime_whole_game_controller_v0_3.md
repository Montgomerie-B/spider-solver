# Anytime Whole-Game Controller v0.3

**Status:** STRONG PASS for the first-foundation capability gate; no complete solution
**Authoritative base:** `c7672bf370442650f3bdc440febef8351d6134a4`
**Rule profile:** MobilityWare 4-suit, Unrestricted Deal ON

## Outcome

The untouched benchmark deal now reaches its first foundation generically,
without an opening prefix, checkpoint, suit target, canonical action, or route
seed. The controller's live campaign portfolio selected `S#1@D2`; a protected
two-epoch corridor produced a replay-valid 21-action prefix at corrected cost
21 and removed one Spade foundation. The same deterministic configuration
repeated the exact result without tuning.

This passes the sprint's decisive capability gate and improves on the separate
legal cost-23 anchor, although the comparison was made only after the
prospective result was frozen. It does not prove that 21 is optimal and does
not make the Spade choice a production constant.

The single authorized 120-second whole-game attempt did not solve the deal. It
stopped at 120.124 seconds with one foundation, 24 face-down cards, no stock,
and no incumbent.

## v0.2 blocker addressed

v0.2 could remove a foundation from the cost-11 post-Deal-1 state but protected
only campaigns whose removal was at most one stock row away. From the true
opening, the primary campaign targeted Deal 2, so its identity was lost after
a one-epoch macro and local alternatives displaced it.

v0.3 adds a bounded hypothesis that survives the missing horizon:

`current tableau -> Deal -> refreshed campaign -> post-Deal work -> Deal -> removal`

The corridor does not embed those events as a script. Each epoch step is found
by an existing tactical realizer and the whole portfolio is regenerated after
the step.

## Campaign-corridor model

`src/spider/planner/campaign_corridor.py` defines:

- `CampaignCorridorConfig` — at most two epoch transitions, bounded corrected
  cost, nodes, wall time, beam width, source beam, and lane count;
- `CampaignCorridor` — live identity, target epoch, MUST sources,
  interchangeable physical copies, relevant exact stock cards, blocked and
  actionable dependencies, receiver/workspace obligations, current same-suit
  structure, excavation chains, rehandling liabilities, exits, milestones,
  confidence, and estimated spend;
- `CampaignCorridorMilestone` — a machine-testable structural predicate;
- `CampaignCorridorLane` — one deterministic member of a small portfolio;
- `CampaignCorridorStep` — one replayed tactical/epoch step plus lifecycle and
  revalidation evidence;
- `CampaignCorridorAssessment` and `CampaignCorridorResult` — typed outcome,
  alternative campaigns, exact actions, cost, nodes, elapsed time, Deals,
  foundations, hashes, and independent replay status; and
- `CampaignCorridorMarginalValue` — matched bounded total-cost comparison to
  the same milestone.

The production module contains no benchmark deal ID, suit bonus, column
constant, route fragment, leaderboard target, or canonical-file access.

## Structural milestones

Supported milestone kinds are:

- required source exposed;
- movable same-suit interval assembled;
- workspace available;
- exact receiver geometry direct or bounded-walkoff ready;
- campaign MUST dependencies satisfied;
- campaign readiness reached;
- stock epoch reached; and
- foundation count increased.

An economic score change is not a milestone. The successful gate records the
Deal-1 epoch milestone and then the Deal-2 foundation milestone.

## Revalidation and source substitution

After every accepted epoch step the solver regenerates the whole campaign
portfolio from the resulting `SpiderState`. The fixed suit/ordinal hypothesis
may continue, receive a new target epoch, wait for its exact row, switch an
interchangeable physical source, complete, or become invalid. Other campaign
labels remain in the assessment.

The true-opening corridor explicitly switched physical source copies after its
first epoch. That is evidence that continuity is attached to a campaign
objective, not to stale card coordinates.

A resource-limited tactical result is not admitted as a fresh strategic fact.
It is reported as a bounded miss and receives no proof authority.

## Corridor diversity

At clean credit the v0.3 gate protects one credible corridor before generic
Deal or raw branches. Higher credit widens deterministically to two or three
campaign lanes. The surrounding successor portfolio still contains direct
permanent work, current removal macros, Deal timing alternatives, economic
projects, and broad raw fallback.

Exact endpoint deduplication ignores corridor history. The TT remains:

`exact structural Spider state -> lowest corrected g`

## Deal timing and multi-epoch marginal value

Unrestricted Deal remains on. A corridor may Deal while legal tableau moves
remain, and both successful Deals did so.

Shallow H1/H2 timing may order Deal alternatives but cannot reject a credible
longer corridor merely because an immediate probe is flat. A matched marginal
comparison includes preparation cost:

`prepared total = preparation paid cost + post-Deal cost to the same milestone`

The difference from the Deal-now total is bounded evidence for or against the
preparation. It is ordering evidence only.

Every corridor tableau action has a lifecycle record: placement class,
same-suit joins created/broken, mixed boundaries created/removed, future exit,
estimated rehandling, and any concrete reason for overriding a permanent join.
Lifecycle debt never enters proof pruning.

## Staged analysis

The controller now separates analysis into three stages.

### Stage 0 — exact cheap facts

Every generated child immediately receives exact identity/hash, `g`, stock,
foundations, face-down count, mobility, empty/open columns, same-suit run facts,
mixed boundaries, rehandling proxy, and the existing admissible incumbent
budget. The child can enter the frontier with Stage 0 only.

### Stage 1 — strategic core

When a child becomes a real expansion candidate it receives a fresh bounded
campaign/economic portfolio and structural measurement for that exact state.
No parent portfolio is used after Deal or foundation removal.

### Stage 2 — expensive optional work

Full Deal counterfactuals, uncertain actionability, corridor realization, and
other bounded tactical work run only for decisions that need them. A raw exact
Deal successor remains first-class when full Deal timing is skipped.

In the decisive gate the controller performed five Stage-0 analyses, two
Stage-1 analyses, and zero Stage-2 Deal-timing analyses. The corridor itself
was the protected optional decision. Full analyses per expansion fell to 1.0.

## Deadline and resource handling

`SearchDeadline` carries one monotonic absolute deadline, remaining wall time,
optional analysis-node allowance, per-component caps, cancellation state, and
component timing counters. Callers check it before starting optional work and
pass its remaining slice to bounded helpers.

The campaign tableau beam now checks time inside child expansion. Residual
transition analysis also uses the configured physical-source beam and does not
start unbounded post-result campaign enumeration after a rejected tactical
slice expires. This was the concrete cause of the earlier continuation
overrun.

Verified deadline observations:

- decisive gate: approximately 10.4 seconds under a 120-second limit;
- repeat: approximately 10.5 seconds under the same limit;
- 15-second continuation: 15.862 seconds, an overrun of 0.862 seconds;
- production-like attempt: 120.124 seconds, an overrun of 0.124 seconds.

Both bounded-limit observations are below the two-second objective. No unsafe
thread termination is used.

## Exact reuse

Stage-1 facts are cached only under exact canonical state identity plus a
configuration/rule fingerprint. The fingerprint includes campaign source
limits, corridor horizon, Unrestricted Deal, and corrected empty-column cost
semantics. Prepared and Deal-now states cannot share facts unless structurally
identical. Incumbent-dependent budgets are rebuilt on every use.

## True-opening gate

Configuration:

- `incumbent=None`;
- 120-second wall limit;
- 30 strategic expansions;
- 50,000 tactical nodes;
- 128-state frontier;
- eight successors per expansion;
- all five credit levels;
- two corridor lanes available;
- two epoch transitions;
- corrected added cost 24;
- 30,000 corridor nodes;
- 12-second corridor slice; and
- source-combination beam 64.

Observed result:

- first foundation: Spades;
- corrected cost: 21;
- explicit actions: 21;
- Deals: 2;
- stock after removal: 30;
- face-down after removal: 33;
- strategic expansions: 2;
- tactical/corridor nodes: 1,875;
- actionability probe nodes: 0;
- path hash: `924bfd20deac96af`;
- controller endpoint hash: `fbea39bb5e2a3a47`;
- structural/Zobrist endpoint hash: `b7522950ea41ad9a`; and
- independent replay: passed.

Exact machine prefix:

```text
 1. move 3 6 1
 2. move 7 9 1
 3. move 10 9 1
 4. move 7 10 1
 5. deal
 6. move 3 10 1
 7. move 1 3 1
 8. move 7 3 2
 9. move 9 3 1
10. move 6 8 1
11. move 7 9 1
12. move 8 7 2
13. move 6 8 2
14. move 6 8 1
15. move 1 8 1
16. move 3 4 5
17. deal
18. move 8 10 1
19. move 8 4 5
20. move 2 4 1
21. move 4 1 12
```

All displayed columns are one-based. The production actions are stored and
executed zero-based, as elsewhere in the engine.

## Repeatability

An untouched second run under the identical configuration produced the same
Spade foundation, corrected cost 21, exact action sequence, path hash, and
endpoint. No configuration or weight changed between runs.

## Post-freeze cost-23 comparison

Only after both prospective runs were frozen was the legal cost-23 checkpoint
opened for comparison.

- both routes remove Spades after exactly two Deals;
- v0.3 costs 21 versus 23;
- v0.3 Deals at explicit actions 5 and 17 versus 11 and 19;
- v0.3 retains 33 face-down cards versus 32 at the anchor;
- v0.3 therefore optimizes the immediate removal corridor differently rather
  than reproducing the known opening; and
- every temporary park in the machine prefix retains an explicit lifecycle
  exit and rehandling estimate.

The comparison changed no behavior and is not an optimality claim.

## Optional continuation

Starting from the machine-generated cost-21 state—not the cost-23 checkpoint—a
15-second run found a replay-valid added-cost-14 state with:

- one foundation retained;
- stock still 30 (no uncontrolled draining in the selected progress state);
- face-down reduced from 33 to 27; and
- campaign MUST burden reduced from 26 to 21.

No second foundation was removed. This is meaningful continuation evidence,
but the current-epoch Heart corridor still returned bounded/resource misses.

## Optional whole-game attempt

The single authorized production-like attempt used `incumbent=None`, a
120-second wall limit, 30 strategic expansions, and a 200,000 tactical-node
ceiling. It stopped at the wall limit after 15 expansions and 34,266 tactical
nodes. The best reported progress node had corrected `g=79`, one foundation,
24 face-down cards, and empty stock. No complete solution or incumbent was
found. No longer research run was started.

## Unseen-deal genericity

Two deterministic shuffled legal four-suit deals receive short corridor and
controller smokes under the same unrestricted profile. Their live primary
corridors differ (`C#1` and `S#1` for the frozen seeds), successors replay, and
deadlines remain bounded. No solve is required and no benchmark constant is
available to these runs.

## Proof-safety boundary

Unchanged:

- exact lower-`g` structural-state TT dominance;
- only the existing admissible remaining-Deal/reveal lower bound may set
  `proof_prunable`;
- corridor identity is not proof-state identity; and
- campaign estimates, economic scores, Deal timing, rehandling debt, analysis
  incompleteness, and bounded misses never proof-prune.

All v0.3 prospective runs used `incumbent=None`, so incumbent proof pruning was
disabled.

## Tests

Forty focused v0.3 tests cover every requested corridor, staging, deadline,
cache, Deal, proof, seed-isolation, replay, and unseen-deal property. The v0.1,
v0.2, Deal-timing, economic, campaign/removal, engine/rules, accounting,
lifecycle, workspace, state-identity, and expected-invalid historical suites
remain part of the complete repository run. Final result: **677 passed, 37
xfailed, 1 pre-existing pytest warning** in 1,114.92 seconds. The 37 expected
invalid historical tests were not weakened.

## Limitations and next task

The decisive foundation corridor is reliable, but current-epoch residual
campaigns still spend most continuation time on bounded tableau assembly and
do not reliably convert six useful reveals/MUST reduction into a second
foundation. In the whole-game run, later branches can still consume all stock
with only one removal.

The next task should therefore be **Anytime Whole-Game Controller v0.4:
Current-Epoch Residual Corridor Conversion and Stock-Preservation Discipline**.
It should retain the proven cost-21 opening discovery, improve machine-testable
same-epoch assembly milestones and partial-progress admission, and require a
second-foundation gate before any score optimization. It must not tune weights
to this route or start from its prefix.
