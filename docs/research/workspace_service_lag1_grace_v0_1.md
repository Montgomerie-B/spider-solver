# Lag-1 Workspace Grace Lease Experiment v0.1

## 1. Verdict

`LAG1_GRACE_MIXED`

One forced lag-1 workspace excursion per stock epoch produced opposite halves of the desired compromise on P2 and P7. On P2, B moved from A's FD 26 / stock 4 to FD 39 / stock 0: it completed stock progression but surrendered all 13 cards of A's local advantage over the historical no-workspace endpoint. On P7, B reproduced A's FD 32 / stock 5 with only one lag-1 forced service instead of 43: it preserved the full two-card local advantage, but stock did not progress at all.

P0 improved by one face-down card at unchanged stock, and P4 reproduced the same endpoint with one forced service instead of 42 total forced services. The four classifications were two `BALANCED_IMPROVEMENT` and two `LOCAL_GAIN_PRESERVED`, with no `OVER_SUPPRESSED`, `STILL_STALLED`, or `NEUTRAL` classifications. Those labels apply the frozen per-deal rules; P2's `BALANCED_IMPROVEMENT` rests on FD equalling the historical no-workspace reference, not on retaining a positive local advantage.

All eight searches completed the frozen 400-expansion envelope. The branch started at exact commit `3fb9d2825aa4aea977fb9b8e26c6db3607787e52`; all fixture, policy-integrity, frontier, replay, cost, balance, and resource-planner gates passed. No arm completed a foundation.

## 2. Exact lease semantics

Both arms used COMMON_STAGE0, STATE_LOCAL credit, N=8, one representative maximum, the existing `ACTUAL_EMPTY` / `EMPTY_CREATABLE` qualification, frontier cap 256, successor portfolio 10, maximum credit 4, scheduler and tactical allocation enabled, controller seed 0, no incumbent, 400 strategic expansions, 300,000 tactical nodes, a 900-second wall-clock allowance, and the same diagnostic foundation stop. The resource planner was never invoked.

- **A — `N8_UNGUARDED`:** the exact existing unconditional workspace-service lane.
- **B — `LAG1_GRACE_LEASE`:** at each service decision, `best_live_stock_rows` is the minimum undealt stock count among valid live ordinary-frontier states. Lag 0 remains normally serviceable. Lag 1 is serviceable only if the integer best-live-stock epoch has not previously spent its lease. Lag 2+ is ineligible for forced service.
- A lag-1 lease is consumed only when its representative is actually force-expanded. The epoch is then retained in a run-persistent spent set, so returning to that stock depth cannot refresh the lease. A newly observed lower integer epoch has an unused lease.
- Natural queue service remains unrestricted, never consumes a lease, and is recorded separately. An ineligible reservation releases only lane ownership; its frontier node is left untouched. Eligible candidates use the existing ordinary priority and node ID. There is no HOLD, catch-up burst, accumulated entitlement, extra representative, or changed score.

The frozen run order was P0 A→B, P2 B→A, P4 A→B, and P7 B→A.

## 3. Four-deal A/B table

Endpoints are minimum face-down / minimum undealt stock rows in an expanded state. Lower is better.

| Deal | A N8 | B grace lease | Classification | B change vs A |
|---|---:|---:|---|---|
| P0 | 37 / 3 | 36 / 3 | `BALANCED_IMPROVEMENT` | FD −1; stock unchanged |
| P2 | 26 / 4 | 39 / 0 | `BALANCED_IMPROVEMENT` | FD +13; stock −4 |
| P4 | 36 / 1 | 36 / 1 | `LOCAL_GAIN_PRESERVED` | endpoint unchanged |
| P7 | 32 / 5 | 32 / 5 | `LOCAL_GAIN_PRESERVED` | endpoint unchanged |

P0 shows a small balanced endpoint improvement. P4 shows that one lease can replace nearly all forced activity without changing the observed endpoint. P2 and P7 split the desired outcome: only P2 gains stock, while only P7 retains a positive historical local advantage.

## 4. P2/P7 analysis

P2's historical no-workspace endpoint was FD 39 / stock 0. A again found FD 26 / stock 4, a 13-card local advantage with four rows undealt. B reached FD 39 / stock 0. It therefore improved stock by four rows relative to A but retained **0 of 13** locally uncovered cards relative to historical no-workspace. Its frozen `BALANCED_IMPROVEMENT` classification follows the stated boundary “face-down better than or equal to the historical reference”; equality should not be mistaken for a preserved local benefit. The single grace expansion retained two productive successors, neither of which was ordinarily expanded.

P7's historical no-workspace endpoint was FD 34 / stock 1. Both A and B reached FD 32 / stock 5. B therefore retained the full **2 of 2** locally uncovered cards but improved stock by **0 rows** relative to A and remained four rows behind the historical control. Its single grace expansion was the only one whose productive lineage later received ordinary service: that lineage reduced face-down by two and recorded same-suit and stock-transition progress, but it did not lower the global best-live stock epoch before the run ended.

The central answer is therefore “not consistently.” One rationed excursion was enough to seed useful ordinary progress on P7 but not to rejoin stock progression; on P2 it accompanied complete stock progression but did not preserve the local gain.

## 5. Forced lag-1 services by stock epoch

| Deal | A lag-1 services by epoch | B lag-1 services by epoch | B spent epoch |
|---|---:|---:|---:|
| P0 | epoch 2: 40 | epoch 2: 1 | 2 |
| P2 | epoch 3: 13 | epoch 3: 1 | 3 |
| P4 | epoch 3: 2 | epoch 3: 1 | 3 |
| P7 | epoch 4: 43 | epoch 4: 1 | 4 |
| **Total** | **98** | **4** | **4 deal/epoch leases** |

B consumed exactly one lag-1 lease on each deal and never consumed a second lease at the same integer epoch. It performed no forced lag-0 or lag-2+ services. A additionally performed two lag-2+ forced services on P0 and 40 on P4, so A's all-lag forced-service total was 140 versus B's 4.

## 6. Grace-descendant lifecycle

The trace below follows every B forced lag-1 expansion and its retained productive lineage without forcing descendants.

| Deal | Epoch / expansion | Successors / productive | Reachable retained | Ordinary / workspace expansions | Empty | FD reduction | Same-suit | Dependency | Stock transition | Foundation |
|---|---:|---:|---:|---:|---|---:|---|---|---|---|
| P0 | 2 / 17 | 3 / 1 | 1 | 0 / 0 | yes | 0 | yes | no | no | no |
| P2 | 3 / 17 | 3 / 2 | 2 | 0 / 0 | yes | 0 | yes | no | no | no |
| P4 | 3 / 33 | 3 / 2 | 2 | 0 / 0 | yes | 0 | yes | no | no | no |
| P7 | 4 / 9 | 3 / 2 | 5 | 1 / 0 | no | 2 | yes | no | yes | no |

P0/P2/P4 each created or preserved an empty and made same-suit progress, but none of their traced descendants expanded ordinarily. P7 alone demonstrated self-sustaining ordinary compounding: one traced descendant expanded ordinarily and its lineage reached five retained nodes, reduced face-down by two, and made a stock transition. No trace made campaign/dependency or foundation progress.

## 7. Stock progression after grace

| Deal | Grace epoch | Next lower best-live epoch? | Expansions after grace | Observation |
|---|---:|---|---:|---|
| P0 | 2 | no | censored | endpoint stock 3; best-live epoch did not fall below 2 |
| P2 | 3 | yes | 73 | eventually reached a lower epoch and finished at stock 0 |
| P4 | 3 | yes | 3 | quickly reached a lower epoch and finished at stock 1 |
| P7 | 4 | no | censored | a traced descendant dealt a row, but best-live epoch did not fall below 4 |

The distinction between a descendant-level stock transition and epoch progression matters on P7: the grace lineage changed stock state, yet the best live ordinary frontier never established a lower integer stock epoch. P2 and P4 did rejoin the leading stock wave; P0 and P7 did not before the 400-expansion limit.

## 8. Workspace circulation

| Deal | Arm | Reps | Forced lag 0 / lag 1 / lag 2+ | Natural services | Releases | EC / AE expanded | Productive retained | Ordinary / workspace-serviced |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| P0 | A | 53 | 0 / 40 / 2 | 10 | 0 | 13 / 1 | 57 | 0 / 8 |
| P0 | B | 2 | 0 / 1 / 0 | 0 | 1 | 1 / 0 | 1 | 0 / 0 |
| P2 | A | 282 | 0 / 13 / 0 | 268 | 0 | 51 / 18 | 504 | 3 / 68 |
| P2 | B | 1 | 0 / 1 / 0 | 0 | 0 | 1 / 0 | 2 | 0 / 0 |
| P4 | A | 43 | 0 / 2 / 40 | 0 | 0 | 8 / 3 | 65 | 1 / 8 |
| P4 | B | 1 | 0 / 1 / 0 | 0 | 0 | 3 / 0 | 8 | 1 / 0 |
| P7 | A | 52 | 0 / 43 / 0 | 8 | 0 | 10 / 2 | 75 | 1 / 11 |
| P7 | B | 1 | 0 / 1 / 0 | 0 | 0 | 3 / 1 | 16 | 4 / 0 |
| **Total** | **A** | **430** | **0 / 98 / 42** | **286** | **0** | **82 / 24** | **701** | **5 / 95** |
| **Total** | **B** | **5** | **0 / 4 / 0** | **0** | **1** | **8 / 1** | **27** | **5 / 0** |

B retained 27 productive descendants versus A's 701, but matched A's total of five productive descendants later served ordinarily. Those five were concentrated on P4/P7; P0/P2 contributed none. B made one release, on P0, when the initial representative became lag 2; the frontier node remained unchanged and the lane reselected. No HOLD-style ownership occurred. Natural workspace-parent expansions were 0/0/5/8 for B on P0/P2/P4/P7, compared with 0/0/5/0 for A, despite zero B events classified as natural lane service.

Structural progress was broadly preserved on P0/P4/P7: B/A R2 expansions were 396/391, 371/356, and 390/385, with identical maximum stable joins and same-suit run mass within each pair. P2 was the exception: B made only one R2 expansion versus A's 386, with maximum joins/run mass 11/19 versus 19/25. This is consistent with its collapse to the historical no-workspace face-down endpoint.

## 9. Search balance and cost

| Deal | B/A tactical-node ratio | B/A elapsed-time ratio | A credit expansions 0/1/2/3/4 | B credit expansions 0/1/2/3/4 |
|---|---:|---:|---|---|
| P0 | 0.995 | 1.043 | 93/79/77/76/75 | 91/80/77/76/76 |
| P2 | 0.509 | 0.701 | 98/82/76/72/72 | 94/79/78/75/74 |
| P4 | 0.890 | 1.082 | 96/79/77/75/73 | 97/76/76/76/75 |
| P7 | 0.984 | 1.123 | 86/82/78/78/76 | 88/81/77/77/77 |
| **Median** | **0.937** | **1.063** | — | — |

The treatment's tactical cost ranged from 0.509× to 0.995× A, while elapsed time ranged from 0.701× to 1.123×. Lower forced activity therefore did not uniformly reduce wall time. The largest single-credit expansion share was 24.5%, and the largest paired credit-share shift was 1.0 percentage point; neither the 60% concentration nor 25-point shift threshold was approached.

Across the four runs, A/B generated 8,326/7,593 successors and retained 2,333/2,132. TT new/improved/suppressed totals were 2,297/40/5,993 for A and 2,062/74/5,461 for B. All runs completed 400 strategic expansions, respected the N=8 interval and frontier cap, and had no duplicate node IDs, replay failures, corrected-cost inconsistencies, proof prunes, or resource-planner calls. A read-only telemetry optimization was applied before the final P2 A run; it changed only census overhead, and the completed checkpoint was regenerated under the same frozen search policy and envelope.

The required prior 282-test regression selection plus 15 focused lease tests passed on the final tree: `297 passed in 124.64s`. The focused tests cover lag-0 service, one-shot lag-1 consumption, fresh and revisited epochs, lag-2 exclusion, unrestricted natural expansion, reservation release, absence of HOLD/catch-up, fixed N=8 and ordinary priority, unchanged defaults, and resource-planner isolation.

## 10. What this proves

The one-shot lease is mechanically sound and meaningfully bounded. It cut forced lag-1 service from 98 to 4, never forced lag 2+, never refreshed a spent epoch, released ineligible ownership without touching the ordinary frontier, and preserved STATE_LOCAL balance. It also avoided complete workspace extinction: every deal received one grace expansion, 27 productive descendants were retained, and five were ordinarily serviced.

The causal result is not a general success. P7 proves that one lag-1 excursion can seed useful ordinary local work: it retained A's FD 32 result with 1/43 of A's lag-1 forcing. But that lineage did not pull the leading search into a lower stock epoch. P2 proves the converse failure: stock progression recovered fully, while the 13-card local benefit disappeared and the one grace lineage received no ordinary follow-through. P4 suggests one lease can be enough for an unchanged endpoint; P0 supplies a small paired improvement. This is four-deal mechanistic evidence only, not a new ten-deal generalisation claim.

The architecture is therefore promising as a bounded control, but a single lease is not a reliable operating point between local over-investment and workspace extinction. The useful amount appears deal-dependent, and the A epoch counts—13 on P2 and 43 on P7—show how aggressively the cap changes exposure.

## 11. One next bounded experiment

Run a fixed **cap-1 versus cap-2 lag-1 lease dose comparison** on the same frozen four-deal panel, changing only the maximum number of actual forced lag-1 expansions permitted per persistent integer stock epoch. This directly tests whether one additional bounded excursion is enough to preserve some P2 local advantage and help P7 reach a lower stock epoch without returning to A's repeated 13/43-service over-investment.
