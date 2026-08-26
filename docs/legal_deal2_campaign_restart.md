# Legal Deal-2 Campaign Restart

## Verdict

From authoritative corrected-rules commit
`dec794eb5661defe3ff04e06e56a63e905ebbb93`, the preferred permanent-join
opening legally removes the first Spade foundation after Deal 2 at corrected
MobilityWare cost **23**. The route contains exactly two deals, every
multi-card move is a descending same-suit block, the automatic foundation is
exactly one 13-card Spade sequence, and a fresh replay from the true deal
reproduces the endpoint and cost.

This is an **EXCEPTIONAL** first-foundation gate result (`total <= 23`). It is
not a complete-solution improvement and does not establish anything about the
cost of the remaining seven foundations.

The old 23-, 47-, and 49-command machine states remain **invalid historical
evidence**. Their shared command 14 moved mixed-suit `7d-6c` as a two-card
block. None of those states or their descendants was reconstructed or used.

## Corrected legal restart

The diagnostic loads `deals/4925153.txt`, applies each arm's six benchmark
opening actions through `SpiderState.move`, asks the generic campaign planner
to select a portfolio, and asks the existing generic Deal-1 realizer to find
its own continuation. The resulting actions are then replayed independently.

The preferred B opening is:

1. `move 6 8 1`
2. `move 6 3 1`
3. `move 6 3 1`
4. `move 6 5 1` — `Qc -> Kc`
5. `move 6 2 1` — `Qs -> Kd`
6. `move 3 8 3` — legal same-suit `4s-3s-2s -> 5s`

The control A arm swaps only actions 4 and 5.

## Permanent Queen-placement rationale

The two variants have the same immediate corrected cost, but not the same
lifecycle cost.

| Opening fact (actions 4-6) | A — control | B — preferred |
|---|---:|---:|
| Immediate corrected cost | 3 | 3 |
| Stable same-suit joins created | 1 | 2 |
| Mixed-suit boundaries created | 2 | 1 |
| Estimated rehandling debt | 2 | 1 |
| Immediate cost through Deal 1 | 8 | 8 |
| Projected lifecycle cost through Deal 1 | 10 | 9 |

B creates permanent `Kc-Qc` and `5s-4s` joins and parks only `Qs` on `Kd`.
A parks `Qc` on `Kd` and `Qs` on `Kc`, retaining only the `5s-4s` permanent
join. The parked Queen has a bounded substitution exit through the exact
incoming Deal-2 `Ks`; in A, moving `Qc` to the then-exposed `Kc` is the second
rehandling obligation. The selected cost-23 route uses the interchangeable
other `Qs`, so this debt remains visible at the checkpoint.

No mixed park was found to override an otherwise comparable stable join. A
matched B's foundation result but supplied no downstream saving that exceeded
its extra unit of rehandling debt.

Lifecycle debt is used only as a local search-order tie-break in the campaign
beam. It never rejects a successor, changes the paid-cost transposition test,
or participates in proof pruning.

## Deal-1 reconstruction

Both arms rediscovered the same legal +5 continuation without production
constants:

1. `move 7 9 1`
2. `move 7 6 1`
3. `move 10 9 1`
4. `move 6 10 1`
5. `deal`

| Arm | Added cost | Nodes | Representative runtime | Independent replay |
|---|---:|---:|---:|---|
| B preferred | 5 | 37 | 0.39 s | yes |
| A control | 5 | 36 | 0.42 s | yes |

Each returned post-Deal-1 state is structurally equal to that arm's independent
replay. Both have 36 face-down cards, 40 stock cards, no foundation and no
empty column. Their top row is:

`Js 9d 4d Kh 4d 6d 9s 7d 8s 5c`

The states are not asserted equal to each other: their buried Queen placement
differs by design.

## Preferred post-Deal-1 portfolio

The full portfolio was recomputed from B's legal state. The objective column is
the planner's risk-adjusted ordering quantity (estimated cost, epoch delay and
confidence penalty); it is heuristic, not an admissible bound.

| Campaign | Epoch -> target | Campaign score | Objective | Remaining cost | Confidence / readiness | MUST | Stock |
|---|---:|---:|---:|---:|---|---:|---:|
| S#1 | 1 -> 2 | 91.30 | 26.0 | 14.0 | LOW / excavation-led | 6 | 3 |
| H#1 | 1 -> 2 | 27.54 | 44.0 | 32.0 | LOW / deferred | 10 | 2 |
| D#1 | 1 -> 4 | 46.60 | 49.0 | 25.0 | LOW / excavation-led | 4 | 5 |
| C#1 | 1 -> 5 | 20.68 | 61.0 | 31.0 | LOW / deferred | 4 | 8 |

S#1 therefore remains a credible primary campaign with a Deal-2 removal
target. It was selected prospectively; the canonical route was not read.

### Exact S#1 sources

MUST sources:

- `Qs@c2`, one face-up peel, due by Deal 2;
- `6s@c8`, `5s@c8`, `4s@c8`, `3s@c8`, `2s@c8`, represented by one max-unioned
  two-peel project that must be ready before Deal 2.

Stock-supplied sources derived from the exact next row:

- `Ks@D2/c1`;
- `As@D2/c2`;
- `7s@D2/c4`.

Interchangeable/deferred sources:

- `Ks@c5`, `Qs@c3`, `8s@c1`, `7s@c3`, `6s@c9`, the alternate `4s@c8`, and
  `2s@c1`.

The successful route legitimately substitutes the shallow `Qs@c3` for the
initially selected parked `Qs@c2`. That is generic physical-copy substitution,
not a benchmark exception.

## Reveal value

Perfect-information reveal has zero information value. The selected B route
was audited for what each newly accessible known card actually enables:

| Exposure | Classification | Structural value |
|---|---|---|
| `7c`, then flipped `6c`, then flipped `8h` | critical-now chain | clears the former 10s column and creates the exact receiver used to park `7d`, which exposes the `6s-2s` band |
| `2s` at the end of the covered `6s-2s` band | required-before-next-deal | certifies the whole lower Spade band is accessible for its post-deal join |
| alternate `Qs@c3` | critical-now | receives `Js-8s`, producing the permanent `Qs-8s` upper band before Deal 2 |
| flipped `7s@c3` | replaceable-by-stock/duplicate | the exact selected Deal-2 `7s` supplies the campaign rank instead |
| flipped alternate `4s@c8` | useful but deferrable | duplicate material for a later Spade campaign, not needed for S#1 |
| exposed `9d` and `Kh` at removal | strategically irrelevant at this epoch | no dependency in the selected S#1 checkpoint |

The pre-deal excavation uses three units of gross temporary-placement debt in
the lifecycle audit. It creates no empty column. The important mixed placement
`Kh-Qs` has a concrete exit: final action 23 moves the completed `Qs-As` block
onto the exact incoming `Ks`, removes the mixed boundary, and triggers the
foundation.

## Fresh Deal-2 obligations

The obligations are derived from B's current bands and campaign rank sources,
not copied from the invalid historical route.

Current useful Spade bands include:

- covered `6s-2s@c8`, with `7d` as one covering group;
- movable `10s-9s@c7`;
- movable `Js@c1`;
- movable `8s@c9`;
- covered Queen alternatives at c2 and c3.

Mandatory pre-deal structure:

- assemble movable `Qs-8s`;
- assemble/recover movable `6s-2s`;
- preserve the existing lower and `10s-9s` fragments;
- shape receiver geometry for the incoming `As` and `7s`;
- then apply exactly one stock row.

The exact Deal-2 row, obtained from `next_stock_row(post_deal1)`, is:

`Ks As 6h 7s Ad Ad Ah 10d Qh Jd`

Receiver requirements:

- `Ks@c1`: final King base; direct;
- `As@c2`: needs an exposed/movable `2s` receiver or bounded walk-off;
- `7s@c4`: needs `8s` at c4; the initial analysis already identifies a
  bounded equivalent walk-off, and the successful shaping route makes it
  direct before the deal.

## Iterative bounds

Both arms used identical resources: bounds `(8, 12, 16, 22, 30)`, 120,000
nodes, 45 seconds per bound and beam width 256. Each arm stopped at its first
actual removal, so bounds above 12 were not run.

| Arm | Bound | Status | Deal-2 added | Total | Deals | Face-down | Empty | Nodes | Representative runtime | Foundations |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B | 8 | CAMPAIGN_ADVANCED | 8 | 19 | 1 | 33 | 0 | 833 | 3.9 s | 0 |
| B | 12 | FOUNDATION_REMOVED | 12 | 23 | 1 | 32 | 0 | 877 | 3.9 s | 1 |
| A | 8 | CAMPAIGN_ADVANCED | 8 | 19 | 1 | 33 | 0 | 833 | 3.9 s | 0 |
| A | 12 | FOUNDATION_REMOVED | 12 | 23 | 1 | 32 | 0 | 877 | 4.1 s | 1 |

The bound-8 result is material legal campaign progress and retains a precise
remaining assembly blocker. It is not evidence of impossibility.

## Complete preferred route

The complete B route from the true opening is:

```text
 1. move 6 8 1
 2. move 6 3 1
 3. move 6 3 1
 4. move 6 5 1
 5. move 6 2 1
 6. move 3 8 3
 7. move 7 9 1
 8. move 7 6 1
 9. move 10 9 1
10. move 6 10 1
11. deal
12. move 9 7 1
13. move 7 1 3
14. move 7 9 1
15. move 8 7 1
16. move 3 10 1
17. move 1 3 4
18. move 3 4 5
19. deal
20. move 8 10 1
21. move 8 4 5
22. move 2 4 1
23. move 4 1 12
```

Costs are opening 6, Deal-1 continuation 5, and Deal-2 realization 12, for a
corrected total of **23**. Action 23 places the legal same-suit `Qs-As` block
on `Ks`, and the engine automatically removes the 13-card Spade foundation.

## A/B result

Both A and B reach the same headline cost and use the same number of bounded
nodes. Their S#1 remaining estimate and MUST burden are also equal after Deal
1. A does not beat B and supplies no compensating downstream evidence for its
extra mixed boundary. B therefore remains preferred by permanent-move
dominance without claiming that the heuristic proved a lower bound.

## Canonical comparison

Only after B and A were frozen was the canonical move file parsed. Its first
foundation is also Spades, at corrected cost 90 and command 91, after Deal 2,
with 8 face-down cards, no empty column and five current mixed descending
boundaries. The prospective checkpoint is cost 23 after Deal 2, with 32
face-down cards, no empty column and seven current mixed descending boundaries.

The canonical complete solution's corrected score 172 remains the sole
complete incumbent context. No canonical future move or 172-derived heuristic
estimate guided or pruned either prospective arm.

## Tests and limitations

Focused tests cover both legal openings, Queen lifecycle classification,
independent Deal-1 replay, deterministic reconstruction and portfolio
reanalysis, state-derived obligations and stock row, same-suit legality for
every multi-card action, no Deal 3, exact foundation verification, equal-cost
full replay, bounded-miss semantics, absence of benchmark constants from
production strategy, ordering-only lifecycle debt, and comparable A/B
resources.

Limitations:

- the campaign score, lifecycle debt and beam ordering are heuristic;
- the search is bounded and does not prove optimality or impossibility;
- some temporary non-campaign parks retain explicit exit obligations at the
  first-foundation checkpoint;
- no broad reveal-economics framework was added;
- no post-foundation, second-foundation or whole-game search was attempted.

## Recommended next step

Preserve B's replay-verified cost-23 state as the new legal first-foundation
checkpoint. The next task should start a separately bounded post-foundation
campaign transition from that state, reanalyse all remaining suits/copies, and
retain the current lifecycle obligations. It must not reconstruct or inherit
the invalid cost-47 or cost-49 historical descendants.
