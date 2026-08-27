# Anytime Whole-Game Controller v0.4

**Status:** PARTIAL; residual structure improved, but the true-opening run did
not remove a second foundation
**Authoritative base:** `cef33e88b39008fba6d9e6aa9ed26f7861b45730`
**Rule profile:** MobilityWare 4-suit, Unrestricted Deal ON

## Outcome

v0.4 adds a generic residual-campaign layer, next-foundation readiness,
foundation-checkpoint diversity, transparent stock opportunity assessment and
investment accounting between foundations. These records have no proof
authority. The controller still uses exact structural-state/lower-`g`
transposition dominance and only the established admissible incumbent bound
for proof pruning.

The decisive untouched-opening run used `incumbent=None`, no prefix or
checkpoint seed, no suit target, no canonical actions and a fixed 180-second
limit. It independently rediscovered the cost-21 Spade foundation, retained
that checkpoint, and then improved face-down count from 33 to 25 and
same-suit run mass from 6 to 42. It did not remove foundation #2. All three
remaining stock rows were consumed, MUST burden rose from 26 to 28, mixed
boundaries rose from 11 to 24 and rehandling debt rose from 11 to 24. The
bounded result is therefore `PARTIAL`, and no repeatability, third-foundation
or whole-game run was authorized.

## v0.3 remaining blocker

v0.3 proved that a live campaign identity can survive two epochs and remove a
first foundation from the untouched deal. Its cost-21 continuation then
reduced face-down cards `33 -> 27` and campaign MUST burden `26 -> 21` without
using stock, but failed to convert that investment into another removal. A
separate 120-second attempt reached one foundation with face-down 24 and empty
stock. v0.4 addresses the representation and retention problem explicitly;
the bounded results show that terminal next-foundation conversion remains the
unsolved part.

## Residual campaign conversion

`src/spider/planner/residual_campaign.py` is an analysis/orchestration layer,
not another whole-game search. It provides:

- `ResidualCampaignAssessment` and `ResidualConversionStatus`;
- a bounded, diverse `ResidualCampaignLane` portfolio for current-epoch
  removal, alternate campaign, permanent structure, Deal-now and
  prepare-then-Deal hypotheses;
- `FoundationCheckpointProfile` and `FoundationCheckpointPortfolio`;
- `NextFoundationReadiness`;
- `ExactNextRowPreview` and `StockOpportunityAssessment`; and
- `ResidualInvestmentAccounting`.

Every lane derives its target as `current foundation count + 1`. Campaigns and
physical sources come from fresh state analysis. Foundation increase is the
terminal success condition; MUST reduction and same-suit mass alone are not
foundation completion.

After any foundation increase the controller performs a fresh Stage-1
analysis of the exact child state, regenerates the complete campaign and
economic portfolios, builds a new residual profile, and generates new lanes.
It may change campaign or physical source after reanalysis.

## Foundation checkpoint profile and diversity

Each checkpoint records corrected cost, foundation identities, stock/epoch,
face-down cards, empty/open columns, mobility, permanent same-suit structure,
mixed boundaries, rehandling debt, campaign MUST burden, minimum remaining
campaign estimate, ready/near campaigns, current and next-epoch projects,
readiness records, exact next-row per-column impacts and residual lane IDs.

Distinct states are retained through transparent dimension representatives:

- lowest `g`;
- lowest MUST burden;
- best next-foundation readiness;
- lowest face-down burden;
- strongest permanent same-suit structure;
- best workspace/liquidity; and
- best concrete next-row stock opportunity.

The bounded portfolio preserves one frontier descendant per retained
checkpoint where space permits. A higher-`g` distinct state can therefore
survive. An identical structural state at higher/equal `g` is still suppressed
by the exact TT. The portfolio itself never proof-prunes.

The decisive run found only one distinct first-foundation checkpoint: Spades
at `g=21`, stock 30, face-down 33, MUST 26, stable joins 3, debt 11. Its best
readiness was `D#1`, excavation-led, six MUST dependencies, two assembled rank
positions, three exact stock dependencies, target epoch 4, estimated bounded
cost 21 and no bounded removal macro. The retained candidate lanes were Heart
and Diamond campaign corridors, one permanent move, Deal-now and
prepare-then-Deal.

## Why the cheapest first foundation is not assumed globally best

The portfolio does not collapse the cost-21/face-down-33 and
cost-23/face-down-32 diagnostic states by their immediate cost. Gates A and B
use identical strategy and budgets, are frozen independently, and are only
then compared. Exact TT dominance applies only to identical structural
states. No code embeds either checkpoint.

Under the bounded v0.4 comparison, the cheaper checkpoint was also the better
residual state: Gate A preserved stock and reduced both face-down and MUST
burden; Gate B consumed a row and increased MUST burden. This is evidence for
these two frozen runs, not a generic cheapest-checkpoint rule.

## Next-foundation readiness

Readiness is inspectable rather than a scalar. It records campaign status,
MUST dependencies, deepest required source, exact stock dependencies,
assembled same-suit coverage, workspace need, receiver readiness, bounded
estimated cost, bounded removal-macro availability and target epoch. Its
ordering protects promising work but has no proof authority.

## Stock opportunity cost and Deal purpose

The exact next row is previewed per column. The profile records the incoming
card and receiver, same- or mixed-suit adjacency, whether permanent structure
is buried, whether the selected campaign receives a rank, and immediate legal
walk-offs after applying the row to a clone.

The before/after assessment separately records dependencies supplied,
projects unlocked/blocked, exact receivers, readiness improvements, permanent
joins created/lost, walk-offs, workspace changes, buried exposed structure and
new mixed boundaries. It assigns one transparent purpose:

- `STRATEGIC_UNLOCK`;
- `PREPARATION_PAYOFF`;
- `CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY`;
- `ESCAPE_ONLY`; or
- `INCONCLUSIVE`.

There is no arbitrary fixed Deal penalty. Deal remains legal with empty
columns and remains available at broad/raw credit. Purpose affects ordering,
not admissibility or proof pruning.

## Residual investment accounting

Between successive checkpoints the controller records paid cost, reveals,
MUST burden removed, permanent structure created, mixed debt incurred,
workspace delta, stock rows consumed, rehandling-debt delta and resulting
next-foundation cost. Because no second foundation occurred in the bounded
gates, no checkpoint-to-checkpoint investment record could be completed.

## Regression anchors

- canonical solution: solved, corrected 172, 174 explicit commands, 169
  tableau commands, five Deals, eight foundations, path
  `77d169da2538ba8c`, final state `4e9861540eac570cb`;
- machine anchor: 21 actions/cost 21, two Deals, one Spade foundation, stock
  30, face-down 33, path `924bfd20deac96af`, structural endpoint
  `b7522950ea41ad9a`, replay valid; and
- independent anchor: 23 actions/cost 23, two Deals, one Spade foundation,
  stock 30, face-down 32, replay valid.

## Gate A — cost-21 checkpoint

Frozen configuration: 90 seconds, 25 strategic expansions, 300,000 aggregate
tactical nodes, frontier 256, ten successors, five progressive credit levels,
five residual lanes at broad credit, corridor horizon two epochs, added cost
30, 120,000 nodes, 20-second slice and beam 512.

Observed result:

- no second foundation;
- added cost 14; total cost from opening 35;
- 14 actions and no additional Deal;
- stock `30 -> 30`, face-down `33 -> 27`, MUST `26 -> 21`;
- stable joins `3 -> 9`, same-suit mass `6 -> 14`;
- mixed boundaries `11 -> 12`, debt `11 -> 12`;
- 90.470 seconds, seven expansions, 32,157 tactical nodes;
- path `caa8017cc64f59e8`, endpoint `ffb07b08c7a2ebb4`, structural hash
  `2ea3e89983e13e3a`; and
- independent replay passed.

## Gate B — cost-23 checkpoint

The exact same strategy and resource values were used.

Observed result:

- no second foundation;
- added cost 25; total cost from opening 48;
- 25 actions and one additional Deal;
- stock `30 -> 20`, face-down `32 -> 27`, MUST `26 -> 30`;
- stable joins `3 -> 11`, same-suit mass `6 -> 19`;
- mixed boundaries `12 -> 20`, debt `12 -> 20`;
- 90.142 seconds, nine expansions, 22,260 tactical nodes;
- path `f0f71469b966bd61`, endpoint `5f7d3342e3f21eda`, structural hash
  `a0efb50076b6b72e`; and
- independent replay passed.

The results were frozen before comparison. Gate A produced better bounded
residual economics, but neither state converted to foundation #2.

## Gate C — untouched opening

Frozen configuration: `incumbent=None`, 180 seconds, 50 strategic expansions,
500,000 aggregate tactical nodes, frontier 256, ten successors, progressive
credit, six checkpoint representatives, five broad-credit residual lanes, and
the same two-epoch/cost-30/120,000-node/20-second/beam-512 corridor bounds.
The helper accepts only the duration and constructs no seed.

Observed result:

- one Spade foundation at `g=21`; no second foundation;
- best one-foundation endpoint `g=72`, 72 actions, five Deals total;
- stock 0, face-down 25, MUST 28;
- stable joins 29, same-suit mass 42, mixed boundaries 24, debt 24;
- 180.591 seconds, nine expansions, 54,707 tactical nodes;
- path `5b5119a747d02366`, endpoint `2d181fa8403ffa09`, structural hash
  `25183eddbac04c78`; and
- independent replay cost/state equality passed.

The first foundation reused the generic 21-action discovery. Its independent
anchor run took 10.664 seconds, two expansions and 1,875 tactical/corridor
nodes. No foundation-#2 time, expansions or nodes exist because it was not
found.

Residual telemetry recorded 22 lanes generated, 11 realised and 20 bounded
conversion failures. Corridor outcomes were one completion (the first Spade
foundation), 14 bounded misses and six resource-limit misses. Deal assessment
recorded 12 strategic-unlock alternatives, zero classified escape-only
alternatives and eight current-epoch opportunities lost. The aggregate stock
timeline includes alternatives generated from multiple branches; the selected
best path consumed all five rows.

Checkpoint telemetry recorded one generated and one retained checkpoint, with
zero diversity suppressions. TT telemetry recorded 34 new states, zero
improvements and zero suppressions. Staged analysis counts were 34/9/6,
analysis cache counts were six hits, nine misses and nine avoided full
analyses, and the deadline overrun was 0.591 seconds. Proof and heuristic prune
counts were both zero.

## Repeatability and optional gates

Gate C did not reach two foundations. Per the hard gate, the deterministic
repeat, optional third-foundation continuation and optional whole-game run
were not started. There is no complete machine solution and no verified
machine solution at 171 or below.

## Proof safety

The residual module, stock assessment, readiness records and checkpoint
portfolio all declare no proof authority. Production proof pruning remains
limited to the existing admissible `remaining Deals + unavoidable paid
reveals` lower bound under an incumbent. The decisive run had no incumbent and
made zero proof prunes. Stock consumption, campaign failure, readiness,
checkpoint diversity and rehandling debt do not proof-prune.

## Unseen-deal genericity

Deterministic shuffled four-suit deals 31 and 47 both passed unrestricted
preflight and exercised the residual API without benchmark constants. Their
bounded one-expansion smokes completed in 0.820 and 0.939 seconds, with no
deadline overrun and two replay-legal successors retained. Their residual
campaign identities differed (`S#1` versus `D#1`) while each portfolio
retained campaign, permanent-structure and Deal-now lane families.

## Limitations and precise blocker

The new layer can describe and retain residual investment, but its bounded
lanes do not yet expose and assemble the remaining campaign sources into a
second K-A removal before stock-advance branches take over. Only one distinct
first-foundation checkpoint was discovered in Gate C, so the new portfolio did
not get an empirical opportunity to protect an alternative first-foundation
geometry. Several stock branches were transparently useful in isolation, yet
their lifecycle still ended with greater MUST/debt and empty stock.

## Verdict and next task

**PARTIAL.** Structure and next-foundation inspectability improved, deadline
behaviour remained healthy, replay/proof safety held, and the generic APIs
worked on unseen deals. The decisive two-foundation milestone was not met.

The next development task should be a bounded terminal-conversion sprint:
propagate stock-purpose evidence to every raw Deal successor, protect at least
one genuinely current-epoch lane until a removal-relevant milestone is either
reached or explicitly invalidated, and diversify the *pre-foundation*
frontier enough to discover distinct first-foundation geometries. Measure each
lane against an exact next-foundation milestone, not a stock epoch or a generic
structural gain. Do not tune benchmark weights or increase wall time before a
short bounded fixture demonstrates the conversion.
