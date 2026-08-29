# Anytime Whole-Game Controller v0.9

**Status:** implemented and diagnostically verified; PARTIAL
**Base:** `374e21b4be2d61fdcaeecc515b3a7e2636a3a814` (`agent/anytime-whole-game-controller-v0-8`)
**Rule profile:** MobilityWare four-suit Spider with Unrestricted Deal ON

## Outcome

v0.9 adds bounded strategic milestones and duplicate-aware stock-epoch
progression without changing the v0.8 tactical allocator, benchmark ceilings,
rules, exact transposition identity or admissible proof bound.

The capability gates pass and the natural cost-21 Gate H authorizes the true
opening gate. Gate H completed 25 strategic expansions in 18.845 seconds,
retained its existing foundation, achieved 13 milestones across the explored
frontier and selected three purposeful stock transitions. It did not remove
foundation #2.

The untouched Gate I is replay-valid and now admits deliberate epoch
progression rather than remaining categorically at stock 50. Its selected route
still does not remove foundation #1 or #2. The hard-gate verdict is therefore
**PARTIAL**: milestone/epoch machinery works and eliminates the pure no-Deal
failure mode, but terminal conversion remains unsolved.

## v0.8 blocker

v0.8 fixed tactical resource monopolisation and raised untouched throughput to
50 strategic expansions in 35.444 seconds, but its selected route stayed at
stock 50 with no foundation. It produced 238 named primitive harvest events
without converting enough of them into a completed interval, terminal
qualification or deliberate epoch transition.

v0.9 addresses the missing aggregation and epoch-decision layers. It does not
restore the expensive whole-campaign/corridor work removed by v0.8.

## Strategic milestone model

`strategic_milestone.py` defines the eleven required milestone families, an
inspectable predicate, exact starting structural key, campaign/objective
identity, suit/rank/fragment requirements, prerequisites and progress. Every
target carries bounded cost, primitive-step, strategic-expansion, elapsed-time
and tactical-node envelopes, plus explicit completion and invalidation
conditions.

Milestone status is one of `ACTIVE`, `ADVANCED`, `ACHIEVED`, `REPLANNED`,
`BLOCKED_CURRENT_EPOCH`, `INVALIDATED`, `SUPERSEDED`, `EXPIRED` and
`BOUNDED_MISS`. A diverse plan/portfolio and conversion ledger retain
checkpoints without entering exact state identity. All milestone objects set
`proof_pruning_allowed=False`.

## Primitive versus milestone harvest

The v0.8 allocator continues to record primitive results such as one dependency
closed, overlay cleared, receiver created or permanent join made. A milestone
harvest requires its explicit predicate to become true after fresh analysis: a
complete interval, closed source chain, used/recovered workspace, purposeful
epoch transition, terminal qualification or foundation removal. Unrelated
primitive improvements are not combined into one milestone.

## Continuity and bounded conversion

Milestone continuity generalises v0.7's same-campaign continuation. A matching
descendant receives bounded priority only while fresh analysis still supports
the same target and its depth/time envelope remains live. Exact-state/lower-`g`
dominance is unchanged.

`milestone_conversion.py` is a coordinator, not another broad search engine.
It repeatedly performs:

`existing v0.8 primitive -> independent replay -> fresh analysis -> same target`

It stops on achievement, invalidation, supersession, lack of a relevant grant,
or the unchanged allocator envelope. The output is one replay-valid macro edge
or an explicit bounded partial result. A miss has no proof authority.

The controller adapter composes construction, dependency closure and terminal-
qualified foundation work. Alternative campaign, construction, workspace,
Deal and raw legal families remain available in the same expansion.

## Interval, source-chain and workspace semantics

Interval milestones describe a suit/rank interval rather than physical card
coordinates. Fresh evaluation accepts an interchangeable duplicate copy.
Source-chain milestones retain related overlay, exposure, receiver and
integration dependencies under one target while the current dependency graph
continues to support it.

A workspace target is not complete when an empty column merely appears. Its
progress records creation, intended use and recovery/replacement when required.
Focused fixtures verify that creation alone is incomplete and the full
lifecycle satisfies the target.

## Epoch availability and duplicate assignment

`epoch_progression.py` inventories each required `(suit, rank)` across face-up
tableau copies, hidden current-tableau copies and remaining stock rows in actual
deal order. It computes the earliest epoch with enough interchangeable
material. A future stock copy does not block a milestone when another usable
copy is already in the tableau. `BLOCKED_CURRENT_EPOCH` redirects planning; it
cannot prune the state or alter the lower bound.

## Pre-Deal work and purposeful Deals

Current work is classified as `MUST_BEFORE_DEAL`, `SHOULD_BEFORE_DEAL`,
`CAN_DEFER`, `DEFER_FOR_FREE_FUTURE_JOIN` or `AVOID_BEFORE_DEAL` using the
exact next row, current durable construction, receiver/workspace damage and
known free future joins.

After required work is complete, unavailable or boundedly exhausted, a later-
stock requirement makes Deal a strong candidate even while tableau moves
remain legal. Every selected purposeful Deal records its exact row, benefiting
campaigns, completed/deferred work, surrendered opportunities, reason and
mandatory fresh post-Deal milestone analysis. Deal legality remains
unconditional under the active Unrestricted profile.

Purposeful epoch transitions are recorded as achieved milestone checkpoints.
That is the strategic evidence used for continuation; raw stock count remains
absent from the structural progress score.

## Whole-deal construction preservation

The portfolio admits leading and alternate campaigns, durable run construction
(including late-removal suits), workspace/reveal work, preparation/epoch
transition and raw fallback. A near-removal campaign does not erase
construction for other suits. Durable same-suit joins retain their v0.8
presumption unless exact future assistance, workspace conflict or another
concrete counterfactual dominates.

## Capability gates

- **A:** a two-primitive run milestone performs two fresh reanalyses, achieves
  its predicate and independently replays.
- **B:** contradictory fresh analysis invalidates the stale target.
- **C:** future-only material blocks the current epoch without proof pruning;
  a current duplicate removes the false block.
- **D:** pre-Deal classification and completed-preparation promotion pass.
- **E:** a purposeful Deal remains eligible while tableau moves remain and
  carries an exact row/purpose.
- **F:** workspace creation alone is insufficient; use and recovery complete
  the lifecycle.
- **G:** the whole-deal portfolio retains construction, epoch work and raw
  fallback alongside campaign milestones.

Two shuffled four-suit smokes generate generic milestones and epoch facts,
retain late-removal construction/Deal eligibility, replay legally and respect
their short deadlines.

## Gate H: cost-21 state

The unchanged configuration is a 90-second wall limit, 25 strategic
expansions, 300,000 tactical nodes, frontier 256 and 4 seconds / 12,000 granted
nodes per expansion.

The completed diagnostic reached all 25 expansions in 18.845 seconds. The
selected endpoint retained one Spade foundation, exhausted the three remaining
stock rows and had 32 face-down cards, with a replay-valid added cost of 11
(`g=32`). Across the explored frontier it achieved 13 milestones from 14
primitive conversion steps. Its three selected Deals occurred at route actions
4, 5 and 9; all three have exact purpose contracts and achieved epoch-transition
checkpoints. The adjacent first two transitions are justified by material first
available two epochs beyond the cost-21 state, rather than by stock-count
reward. It did not reach terminal qualification or foundation #2.

This satisfies true-opening authorization through non-trivial milestone
completion and purposeful epoch progression.

## Gate I: untouched deal

The untouched configuration retains `incumbent=None`, 180 seconds, 50
strategic expansions, 500,000 tactical nodes and frontier 256, with no prefix,
route, checkpoint, suit, campaign or canonical action seed.

After epoch-transition checkpoints were incorporated into ordering metadata,
the selected route advanced deliberately instead of stalling at stock 50. It
reached 50 expansions in 44.259 seconds with replay-valid `g=24`, 24 actions,
654 tactical nodes, stock 0 and 38 face-down cards. The five Deals occurred at
actions 10, 13, 15, 18 and 22, interleaved with 19 tableau actions. Selected-
path audit verifies that all five have both an achieved epoch-transition
checkpoint and an exact purpose contract. Across the explored frontier the run
achieved 19 milestones from 20 primitive conversion steps and retained
construction activity for Spades, Diamonds, Hearts and Clubs. No foundation
was removed.

Because F2 was absent, deterministic repeat, F3 continuation and optional
whole-game run were not authorized.

The complete repository suite passed: **955 passed, 37 xfailed, 1 existing
warning in 1120.21 seconds**.

## Proof safety and genericity

The exact TT remains `canonical structural Spider state -> lowest corrected g`.
Only the existing mandatory-Deal/paid-reveal admissible bound may proof-prune.
Milestones, epoch plans, pre-Deal classifications, resource history and bounded
misses do not enter TT identity or proof logic.

Production milestone modules contain no benchmark deal, suit preference, rank
interval, column, route, external score or canonical action sequence.

## Limitations and precise blocker

Milestone conversion now completes cheap construction and epoch-transition
targets, but interval attempts usually make at most one useful primitive before
fresh analysis cannot obtain another matching grant. Source/receiver/overlay
milestones are represented, yet the controller still does not convert them into
terminal qualification inside the strategic expansion cap.

The precise remaining blocker is **same-target interval/source-chain tactical
actionability after the first fresh step**. The next task should improve the
mapping from a live milestone predicate to the appropriate existing closure or
construction primitive on its fresh descendant while retaining all current
budgets and proof rules. Per the hard gate, do not begin that work, v0.10 or the
full eight-foundation scheduler automatically.
