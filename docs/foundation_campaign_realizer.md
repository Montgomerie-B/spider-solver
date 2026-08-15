# Foundation campaign realizer

## Scope

`spider.planner.foundation_campaign_realizer` turns one frozen
`FoundationCampaign` into a replay-verified tactical route through exactly its
next stock epoch. It does not call `plan_search`, search a whole game, change
campaign suit/copy/target epoch, or continue into a second deal.

The layer is intentionally bounded. `NOT_FOUND_WITHIN_BOUND` and
`RESOURCE_LIMIT` mean only that the configured experiment did not find a
route; neither status is an impossibility claim.

## Public model and API

The obligation model consists of:

- `CampaignObligationKind`: target-prefix excavation, rank usability,
  fragment preservation, receiver shaping, workspace preparation, exact deal,
  and post-deal verification.
- `CampaignObligation`: a stable obligation identifier plus its machine
  predicate data, deadline, optional source set, receiver, or fragment.
- `CampaignProgress`: an immutable snapshot after each tactical fragment.
- `CampaignIdentity`: fixed suit, foundation ordinal, and intended removal
  epoch.
- `CampaignRealizationStatus`: `FOUND`, `PARTIAL`,
  `NOT_FOUND_WITHIN_BOUND`, `RESOURCE_LIMIT`, and `INVALID_CAMPAIGN`.
- `CampaignRealizationResult`: legal actions, roles, corrected cost, resulting
  state, obligation accounting, receiver/workspace evidence, before/after
  campaign facts, resource use, and independent replay result.

The main entry points are:

```python
campaign_obligations_for_next_epoch(state, campaign, cards)
campaign_target_prefix_closure(state, campaign, rank)
obligation_is_satisfied(state, campaign, obligation)
realize_campaign_to_next_epoch(
    state,
    campaign,
    cards,
    max_added_cost=14,
    max_nodes=50_000,
    time_limit_s=30.0,
)
```

`campaign_target_prefix_closure` caps the existing excavation closure at the
selected rank. It exposes the selected provenance and interchangeable tableau
sources, exact reveals, target-relative destination prerequisites, max-unioned
helper tasks, temporary-space need, and current satisfaction. It does not
charge the rest of the source column.

## Hierarchy and reused tactics

The realizer executes the following loop:

1. Validate and freeze campaign identity.
2. Derive obligations for the next exact stock row.
3. Send each unsatisfied mandatory prefix to the exact bounded
   `objective_realizer` reveal backend.
4. Independently replay that fragment and verify its concrete predicate.
5. Reanalyse the same suit/copy/target epoch, allowing a cheaper equivalent
   physical source to replace the old one.
6. When the campaign treats an empty as working capital, offer bounded
   recreation to `workspace_tactics`; accept it only if all mandatory guards
   still hold on independent replay.
7. Freeze practical receiver conditions using exact `stock_reception` row
   geometry.
8. Apply one engine deal only after every mandatory pre-deal obligation holds.
9. Verify exact card-to-column mapping, replay the complete action sequence,
   and reanalyse the fixed campaign.

The implementation also reuses:

- `excavation_closure` for destination and helper dependencies;
- corrected MobilityWare accounting in `rules`/`metrics`;
- collision-safe structural keys and zero-cost handling inside the tactical
  backends; and
- `space_lifecycle` for observable empty-column events.

The existing committed-excavation design informed the fixed-target hierarchy,
but its public operation empties a complete column. The campaign realizer uses
the more precise reveal objective for a selected rank prefix rather than
overcharging or over-excavating the whole column.

## Facts and heuristics

Hard checks are engine move legality, stock epoch, exact next-row order,
campaign identity, target-relative face-down reduction, movable same-suit
rank usability, fragment presence, corrected move cost, and independent
structural replay equality.

Campaign scores, estimated campaign cost, readiness, receiver preference, and
workspace preference are diagnostic heuristics. They order or describe work;
they never proof-prune a legal state. Receiver shaping is best effort. The
deal gate depends only on mandatory excavation/usability/preservation facts.

## Benchmark through Deal 1

The fixture-only diagnostic constructs the supplied six-move state at
corrected cost 6 from the true opening. The generic portfolio freezes S#1 as
primary, with removal targeted for Deal 2. Its next-epoch obligations contain:

- mandatory target-relative exposure and usability of the selected 10♠ rank;
- mandatory preservation of the 6♠–2♠ fragment;
- desired Deal 1 receiver conditions for J♠, 9♠, and 8♠;
- workspace preparation; and
- exact Deal 1 plus fixed-campaign verification.

All tested bounds found the same route:

| Added bound | Status | Added cost | Nodes | Runtime |
|---:|---|---:|---:|---:|
| 6 | FOUND | 5 | 42 | 0.66 s |
| 10 | FOUND | 5 | 42 | 0.66 s |
| 14 | FOUND | 5 | 42 | 0.66 s |
| 18 | FOUND | 5 | 42 | 0.67 s |
| 24 | FOUND | 5 | 42 | 0.66 s |

The full replay-valid route from the opening is:

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
```

The first six commands are fixture construction only. From that state, the
realizer spends two paid moves on the campaign-critical prefix, uses two paid
moves to recreate column 6 as workspace, and pays one for the exact deal.
Added cost is 5; total corrected cost from the opening is 11.

Immediately before Deal 1, 10♠ is exposed on column 7 for the incoming 9♠,
the lower 6♠–2♠ band remains intact, both an exposed Q♠ walk-off receiver for
J♠ and the exact-row 9♠ parent for 8♠ are available, and column 6 has been
regenerated. The exact incoming row is:

```text
J♠ 9♦ 4♦ K♥ 4♦ 6♦ 9♠ 7♦ 8♠ 5♣
```

After Deal 1, S#1 remains the generic primary campaign for Deal 2. Estimated
remaining campaign cost falls from 19.0 to 14.0 and campaign score rises from
85.1 to 91.3; readiness/confidence remain excavation-led/LOW. The apparent
MUST set grows from the single pre-deal 10♠ source to Q♠ plus the temporarily
covered lower fragment. This is the expected one-row overlay effect: the
fragment is still structurally intact, but the planner now records the peel
needed before Deal 2.

The prospective result passes the hard gate as **STRONG PASS**: the exact row
is reached on independent replay, all mandatory obligations and all three
practical receiver conditions hold, the critical rank is usable, workspace is
spent and recreated, S#1 remains primary for Deal 2, and estimated remaining
burden improves materially.

Run the frozen diagnostic from the repository root with:

```text
python src/spider/planner/diagnostics/foundation_campaign_realizer_report.py
```

Only after that result was frozen did the diagnostic open the canonical trace.
For broad validation, the prospective route costs 11 through Deal 1 versus 51
for the canonical trace, and both identify Spades as the first foundation
campaign. No tableau hash, route resemblance, or canonical reconnection is
required.

## Limitations and next step

- The hierarchy currently realizes mandatory tableau prefixes plus optional
  workspace recreation; it recognizes useful receiver walk-offs but does not
  launch an expensive receiver-shaping search when the condition is already
  practical.
- A target-relative closure reports existing dependency facts but does not
  prove that every helper combination is jointly schedulable.
- The improved workspace backend is bounded/heuristic, so a miss remains
  resource-relative.
- Post-deal stock overlays can make an intact fragment appear as several MUST
  rank sources in campaign diagnostics; project union, rather than raw source
  count, is the meaningful burden.
- Realisation intentionally stops immediately after Deal 1.

The recommended next step is a reviewed Deal-2 extension that first turns the
post-Deal-1 receiver obligations into explicit before/after-deal joins, while
retaining the fixed-identity, one-epoch, replay-verification boundary. It
should remain outside `plan_search` until similarly bounded tests pass.
