# Foundation campaign Deal-2 realizer

## Scope

`spider.planner.foundation_campaign_removal` extends the verified one-epoch
campaign layer through its fixed removal epoch. It accepts the replay-verified
post-Deal-1 state, applies at most one additional exact stock row, and stops
immediately when the selected foundation is removed or the bounded experiment
ends.

It does not call `plan_search`, search Deal 3, invoke a whole-game solver,
modify scoring, or write a partial route to the solution archive.

## Public API and data

The main API is:

```python
realize_campaign_to_removal_epoch(
    start_state,
    campaign,
    cards,
    max_added_cost=20,
    max_nodes=120_000,
    time_limit_s=60.0,
    beam_width=256,
) -> CampaignRemovalResult
```

Supporting public types are:

- `CampaignRemovalStatus`: `FOUNDATION_REMOVED`, `BAND_COMPLETE`, `PARTIAL`,
  `NOT_FOUND_WITHIN_BOUND`, `RESOURCE_LIMIT`, and `INVALID_CAMPAIGN`.
- `CampaignRemovalObligationKind` and `CampaignRemovalObligation`: explicit
  received-stock joins, band assembly/position/preservation, workspace, exact
  deal, post-deal connection, removal, and verification.
- `CampaignEpochResult` and `CampaignRemovalProgress`: per-phase actions,
  cost, nodes, bands, obligation state, workspace, and foundation facts.
- `CampaignRemovalResult`: fixed identity, full action sequence, corrected
  cost, pre/immediate-post/final states, exact row, obligations, receivers,
  workspace events, foundation delta, bounded resources, and independent
  replay verification.

The fixed identity is the campaign suit, foundation copy index, and target
removal epoch. Physical source provenance is not fixed: bands are rediscovered
from each structural state, so interchangeable physical cards may substitute
without changing the strategic campaign.

## Campaign bands

`CampaignBand` records:

- suit and exact descending card sequence;
- high/low ranks and length;
- tableau column and face-up interval;
- whether the band is currently movable;
- whether it is covered and by which exact cards; and
- campaign source keys associated with its ranks.

Public helpers locate maximal bands, test rank-interval containment, test
whether two bands can join, and summarize recovery of a covered intact band.
Consequently, an intact 6–2 band under one overlay is one structural recovery
project, not five unrelated raw MUST ranks.

The required pre-deal bands are derived generically. The exact campaign ranks
arriving in the target `CampaignEpochPlan` are removed from K–A; the remaining
maximal intervals become assembly obligations. In the benchmark this produces
Q–8 and 6–2 without naming their suit or columns in production logic.

## Receiver obligations

For each selected campaign card in the exact target row, the realizer derives
its receiver rank and column. A condition is satisfied by either:

- a direct same-suit landing onto the selected band; or
- a concrete bounded equivalent verified on an engine simulation of the exact
  row: clear at most one incoming overlay, then legally walk the campaign card
  onto the receiver band.

The incoming King is treated as the final base. Receiver success is structural
and replayable, not a heuristic score threshold.

## Search hierarchy

1. Validate that the campaign targets exactly the next remaining stock epoch.
2. Freeze identity, bands, obligations, and exact target row.
3. Run a bounded tableau-only beam to assemble the derived pre-deal bands and
   concrete receiver conditions.
4. Reanalyse the same suit/copy/target epoch.
5. Apply one engine deal and verify its exact stock slice and stock reduction.
6. Reanalyse the same fixed campaign before removal.
7. Run a second bounded tableau-only beam until the fixed suit foundation is
   automatically removed.
8. Independently replay the entire added route and require structural state
   equality and corrected-cost equality.

The tactical expansion uses the real engine, corrected zero-cost rules, and
collision-safe structural state keys. The heuristic order favours longer
movable campaign bands, uncovering intact bands, exact/bounded receivers, Q–A
completion, and actual removal. It does not proof-prune from campaign score,
estimated cost, readiness, or confidence. Beam truncation and resource limits
therefore never establish impossibility.

The module builds on the target-relative excavation, exact-row reception,
workspace, replay, and identity contracts established by the Deal-1 realizer.

## Prospective benchmark result

The diagnostic first reconstructs the supplied six-move state and calls the
existing `realize_campaign_to_next_epoch` API. It requires the independently
replayed Deal-1 result, then reanalyses and freezes S#1 with target Deal 2.
The complete post-Deal-1 state is never hard-coded into production strategy.

At that state the important structural bands are:

- covered 6♠–2♠ under one 7♦ overlay;
- movable 10♠–9♠;
- movable J♠;
- movable 8♠; and
- covered Q♠ alternatives.

The exact Deal-2 row is:

```text
K♠ A♠ 6♥ 7♠ A♦ A♦ A♥ 10♦ Q♥ J♦
```

The bounded results were:

| Added bound | Status | Added cost | Nodes | Runtime |
|---:|---|---:|---:|---:|
| 8 | PARTIAL | 8 | 835 | 3.53 s |
| 12 | FOUNDATION_REMOVED | 12 | 881 | 3.59 s |
| 16 | FOUNDATION_REMOVED | 12 | 881 | 3.56 s |
| 20 | FOUNDATION_REMOVED | 12 | 881 | 3.62 s |
| 28 | FOUNDATION_REMOVED | 12 | 881 | 3.57 s |

The best complete route from the true opening is:

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
```

The first six moves are fixture construction. The next five commands are the
existing generic Deal-1 result. From the verified post-Deal-1 state, the new
realizer pays 12 moves; total corrected cost from the true opening is 23.

Before Deal 2 it has produced movable Q♠–8♠ and 6♠–2♠ bands. Incoming 7♠
lands directly on the upper band. Incoming A♠ has an exact two-action
equivalent: move the 10♦ overlay onto incoming J♦, then move A♠ onto 2♠.
After the deal, the lower band moves onto 7♠, A♠ completes Q♠–A♠, and the
12-card run moves onto incoming K♠. The engine automatically removes the
complete K♠–A♠ foundation at zero additional automatic cost; the triggering
tableau move retains cost one.

The independently replayed final facts are:

- exactly two stock deals from the opening and no Deal 3;
- stock reduced from 50 to 30 cards across those deals;
- foundation count increased from zero to one;
- the only added foundation suit is Spades, matching the frozen identity;
- corrected added cost from post-Deal-1 is 12;
- corrected total cost from the opening is 23; and
- replayed and stored final states are structurally identical.

The hard-gate result is **STRONG PASS**.

Only after this prospective result is frozen does the diagnostic read the
canonical trace. Canonical validation reaches its first Spade foundation at
corrected cost 90 (command 91), versus prospective partial-route cost 23.
The prospective state has 32 face-down cards at removal versus canonical 8,
so this is explicitly not a complete-solution or canonical-reconnection
claim.

Run the diagnostic with:

```text
python src/spider/planner/diagnostics/foundation_campaign_deal2_report.py
```

## Limitations and next step

- The beam is deliberately tactical and truncated; missed bounds are not
  exhaustive proof results.
- Receiver equivalence currently proves at most one overlay-clear move before
  the incoming-card walk-off.
- The search stops on the first fixed-suit foundation and does not assess the
  long-term cost of the remaining tableau.
- Band source keys are diagnostic provenance; structural card equality and
  independent replay are authoritative.
- No result is written to the complete-solution archive.

The recommended next step is to review the 23-cost partial route and decide
whether to integrate the band/receiver obligations into a broader strategic
campaign layer. `plan_search` should remain unchanged until that integration
has its own bounded regression gate.
