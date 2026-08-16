# Post-primary residual campaign transition

## Scope

`spider.planner.foundation_campaign_transition` fixes one next-outstanding
foundation campaign and realizes one bounded transition. It either removes the
campaign without dealing, removes it across the next exact stock row, or
advances it through exactly one row and stops. It never calls `plan_search`,
runs a whole-game solver, takes more than one new deal, or treats a bounded
miss as an impossibility proof.

The layer reuses the existing Deal-1 realizer, Deal-2 removal realizer,
campaign-band model, real engine, corrected MobilityWare accounting, and
collision-safe tableau beam. The Deal-2 beam is now exposed as the public
`search_campaign_tableau` tactical primitive; no second search engine was
created.

## Public API and data model

The main entry point is:

```python
realize_residual_campaign_transition(
    start_state,
    campaign,
    cards,
    max_added_cost=24,
    max_nodes=120_000,
    time_limit_s=60.0,
    beam_width=512,
) -> CampaignTransitionResult
```

The public model includes:

- `CampaignTransitionMode`: `REMOVE_BEFORE_NEXT_DEAL`,
  `REMOVE_AT_NEXT_DEAL`, and `ADVANCE_ONE_EPOCH`;
- `CampaignTransitionStatus`: `FOUNDATION_REMOVED`, `NEXT_EPOCH_REACHED`,
  `CAMPAIGN_ADVANCED`, `PARTIAL`, `NOT_FOUND_WITHIN_BOUND`,
  `RESOURCE_LIMIT`, and `INVALID_CAMPAIGN`;
- `CampaignTransitionObligationKind` and `CampaignTransitionObligation` for
  source exposure, band recovery/preservation/joining, workspace, exact-row
  application, fixed-identity verification, Q-A connection, and removal;
- `CampaignTransitionProgress` and `CampaignTransitionResult` for actions,
  corrected cost, states, obligation accounting, bands, MUST-source changes,
  workspace events, exact row, foundation facts, portfolios, bounded resources,
  and independent replay; and
- `ResidualStateAudit` / `SuitBandAudit` for cheap tableau-quality facts.

The fixed identity is suit, next-outstanding foundation ordinal, and target
epoch. Equivalent physical copies may replace selected sources after
reanalysis.

## Mode selection and search hierarchy

Mode selection is a hard epoch comparison:

1. target at or before the current epoch: run the shared tableau beam toward
   actual fixed-suit foundation removal; do not deal;
2. target at the next epoch: use the existing exact target-row removal
   realizer; or
3. later target: use the existing next-epoch realizer, apply one exact row,
   reanalyse the fixed campaign, and stop.

Every route is independently replayed. Corrected cost and structural state
equality must agree, and the result rejects more than one new deal. A
foundation success additionally requires an exact count increase of one and
one added suit matching the frozen identity.

## Hard facts versus heuristics

Hard facts are engine legality, stock epoch and row, source/receiver structural
predicates, foundation ordinal, automatic removal, corrected cost, deal count,
and replay equality.

Campaign score, estimated cost, confidence, target schedule, portfolio order,
workspace preference, and beam order are diagnostic heuristics. They do not
proof-prune. `NOT_FOUND_WITHIN_BOUND` and `RESOURCE_LIMIT` remain
resource-relative statements.

## Verified cost-23 residual state

The diagnostic constructs the supplied six-move state, calls
`realize_campaign_to_next_epoch`, then calls
`realize_campaign_to_removal_epoch`. The complete route independently replays
from the true opening with these invariant facts:

- corrected total cost 23;
- exactly two stock deals and stock size 30;
- one completed foundation, Spades only;
- 32 face-down cards;
- no empty columns;
- two fully-open, non-King columns;
- cheapest verified workspace creation cost 2;
- six legal tableau moves;
- longest visible same-suit band 2 and total visible band mass 29; and
- stored and replayed residual states structurally equal.

The residual campaign order is:

| Role | Campaign | Target | Risk-adjusted objective | Campaign score | Cost estimate | MUST | Stock sources |
|---|---|---:|---:|---:|---:|---:|---:|
| Primary | H#1 | Deal 2 | 34.0 | 44.8 | 28.0 | 10 | 0 |
| Independent runner-up | D#1 | Deal 4 | 38.0 | 64.0 | 20.0 | 7 | 3 |
| Deferred | C#1 | Deal 5 | 52.0 | 34.1 | 28.0 | 6 | 7 |
| Deferred | S#2 | Deal 5 | 57.0 | 20.1 | 33.0 | 5 | 6 |

The primary-to-runner-up objective gap is 4.0. Completed S#1 cards remain
reserved, and S#2 is the next outstanding Spade ordinal. Canonical order is
not consulted during this selection.

H#1 is already at its heuristic target epoch, so the derived mode is
`REMOVE_BEFORE_NEXT_DEAL`. Its initial MUST ranks are J, 10, 9, 8, 7, 6, 5,
4, 3, and 2 of Hearts. Buried duplicate 2H and AH sources remain off-MUST.
The workspace policy is `CREATE_THEN_SPEND`, with a verified create estimate
of two.

## Generated obligations

The current-epoch transition generates machine predicates to:

- make an interchangeable source usable for each of the ten MUST ranks;
- create/spend workspace as an optional tactic;
- connect a movable QH-AH band;
- assemble and remove KH-AH; and
- verify exactly one new Hearts foundation.

No stock obligation is generated. The exact next row is therefore not applied:

```text
2C 10S QD KH 8H 9C 3S 5S 5D 4H
```

That row is shown only as known residual geometry for a later campaign. It is
not part of the frozen H#1 transition, and Deal 3 is not taken.

## Bounded prospective result

| Bound | Status | Added | Total | Nodes | Runtime | Obligations | Foundations | MUST | Remaining cost | Longest H band |
|---:|---|---:|---:|---:|---:|---:|---|---|---:|---:|
| 8 | CAMPAIGN_ADVANCED | 8 | 31 | 2,444 | 15.759 s | 5/14 | 1 to 1 | 10 to 7 | 20.0 | 3 |
| 12 | CAMPAIGN_ADVANCED | 12 | 35 | 4,770 | 19.079 s | 5/14 | 1 to 1 | 10 to 7 | 20.0 | 3 |
| 18 | CAMPAIGN_ADVANCED | 18 | 41 | 7,901 | 25.759 s | 6/14 | 1 to 1 | 10 to 6 | 18.0 | 4 |
| 24 | CAMPAIGN_ADVANCED | 24 | 47 | 11,138 | 37.447 s | 8/14 | 1 to 1 | 10 to 3 | 15.0 | 5 |
| 32 | CAMPAIGN_ADVANCED | 25 | 48 | 15,447 | 52.134 s | 8/14 | 1 to 1 | 10 to 3 | 15.0 | 5 |

The bound-24 route is preferred because bound 32 reaches the same measured
campaign burden at one additional paid move.

## Complete best route from the true opening

```text
move 6 8 1
move 6 3 1
move 6 3 1
move 6 2 1
move 6 5 1
move 3 8 3
move 7 9 1
move 7 6 1
move 10 9 1
move 6 10 1
deal
move 7 1 2
move 7 8 1
move 8 7 2
move 3 10 1
move 1 3 3
move 9 3 1
move 3 4 5
deal
move 8 10 1
move 8 4 5
move 2 4 1
move 4 1 12
move 9 4 1
move 7 1 1
move 9 10 3
move 7 9 2
move 7 2 1
move 4 7 2
move 4 2 1
move 4 2 1
move 10 7 5
move 10 9 2
move 2 10 4
move 10 2 6
move 10 2 1
move 1 10 2
move 8 1 1
move 6 8 1
move 6 7 1
move 8 6 2
move 8 2 1
move 10 8 1
move 10 1 2
move 10 1 1
move 7 10 6
move 1 10 5
```

The first 23 commands are the public-API-reconstructed first-foundation route.
The residual transition adds 24 paid moves, for corrected total cost 47. The
complete route has exactly two stock deals, independently replays, and reaches
the stored final state.

The transition reduces face-down cards from 32 to 21, raises simple legal
mobility from 6 to 13, creates and consumes workspace three times, and leaves
no empty. H#1 improves from score 44.8 / cost 28.0 / ten MUST sources to score
107.0 / cost 15.0 / three MUST sources. Its principal bands become 8H-4H,
KH-QH, 2H-AH, 10H, and 6H.

No second foundation is removed. Foundation count remains one, stock remains
30, and no Deal 3 or Deal 4 occurs.

## Canonical validation and verdict

All prospective fields above are frozen before the diagnostic parses the
canonical trace. Canonical foundation order is S, D, C, D, S, C, H, H. At its
comparable first-foundation milestone canonical cost is 90 with eight
face-down cards and run mass 53. The prospective transition ends at cost 47
with 21 face-down cards and run mass reflecting a much earlier, less excavated
tableau. Agreement with canonical's second foundation is neither expected nor
required, and no complete-solution improvement is claimed.

The hard-gate verdict is **PARTIAL**. Selection is coherent and the transition
is replay-valid with material H#1 progress, but the fixed campaign is not
removed and Deal 3 is not reached. Per the task boundary, work stops here:
there is no scoring patch, `plan_search` change, Deal 3, Deal 4, or archive
write.

## Limitations and next step

- The tactical beam is heuristic and truncated; its miss is not proof that a
  Hearts removal within the tested bounds is impossible.
- Initial current-epoch obligations deliberately retain every MUST structural
  predicate; a partial best state cannot satisfy terminal Q-A/removal checks.
- The early first foundation leaves a 32-card excavation debt. The residual
  state remains mobile and improves substantially, but its long-term solution
  quality is not established.
- Reported runtimes are environment-dependent.

The recommended next step is to review whether current-epoch target schedules
should require a structural readiness gate before portfolio promotion. That
should be a separate planner-quality task; this partial result must not be
converted into an ad-hoc scoring patch here.

Run the diagnostic with:

```text
python -m spider.planner.diagnostics.residual_campaign_transition_report
```
