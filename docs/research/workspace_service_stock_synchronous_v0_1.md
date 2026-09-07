# Stock-Synchronous Workspace Service Experiment v0.1

## 1. Verdict

`STOCK_SYNCHRONY_MIXED`

Exact stock synchrony restored stock progression on the two diagnostic deals, but it did so by almost eliminating the workspace mechanism whose local benefit the experiment was intended to preserve. Relative to unguarded N8, both zero-tolerance arms produced one `BALANCED_WIN` (P0), one `NEUTRAL` result (P4), and two `STOCK_TRADEOFF` results (P2 and P7). No arm completed a foundation.

On P2, A reached FD 26 / stock 4, B reached 39 / 0, and C reached 37 / 0. C retained only 2 of the 13 cards of historical local advantage over no-workspace FD 39. On P7, A reached 32 / 5 while both B and C reached 34 / 1, erasing A's two-card local advantage. C selected no representative and provided no forced or natural workspace service on any deal.

The reservation distinction was mechanically real but not causally productive in this panel. B held one lagging representative to the end on every deal, with a maximum block span of 395 strategic expansions. C had zero persistent ownership by construction. However, B blocked zero observed lag-0 workspace opportunities, so releasing the old reservation did not uncover same-epoch service that HOLD had hidden.

The experiment started from `8f9e181d28bc2e46e2b9a52c4199ec3acd84c0bc` on branch `agent/workspace-service-stock-synchronous-v0-1`. All twelve searches completed under the frozen envelope, and all integrity gates passed.

## 2. Exact A/B/C semantics

All arms used COMMON_STAGE0, STATE_LOCAL credit, N=8, one representative maximum, the existing `ACTUAL_EMPTY` / `EMPTY_CREATABLE` definition, frontier cap 256, successor portfolio 10, maximum credit 4, scheduler and tactical allocation enabled, controller seed 0, no incumbent, 400 strategic expansions, 300,000 tactical nodes, a 900-second wall-clock limit, and the same diagnostic foundation stop. The resource planner was never invoked.

- **A — `N8_UNGUARDED`:** the exact existing workspace-service lane, with no stock guard.
- **B — `ZERO_TOLERANCE_HOLD`:** at a due service, withhold when `workspace_stock_rows - best_live_stock_rows > 0`; retain the reservation; let ordinary search take the opportunity; reset the interval; grant no catch-up service.
- **C — `STOCK_SYNCHRONOUS_RESELECT`:** service eligibility requires lag 0. A lagging reservation is released without cloning, removing, penalising, or suppressing its frontier node. Selection considers only live qualifying workspace states at the best live stock depth and chooses by the existing ordinary priority, then node ID. If none exists, the lane stays empty.

The frozen order was P0 A/B/C, P2 B/C/A, P4 C/A/B, and P7 A/C/B. Negative paired deltas are improvements. `BALANCED_WIN` requires improved stock with FD no worse than +1, or improved FD with stock no worse; improved stock with FD worse by more than 1 is `STOCK_TRADEOFF`.

## 3. Four-deal table

Each endpoint is shown as minimum face-down / minimum stock rows in an expanded state.

| Deal | A N8 | B HOLD | B vs A | C RESELECT | C vs A |
|---|---:|---:|---|---:|---|
| P0 | 37 / 3 | 36 / 3 | `BALANCED_WIN` | 36 / 3 | `BALANCED_WIN` |
| P2 | 26 / 4 | 39 / 0 | `STOCK_TRADEOFF` | 37 / 0 | `STOCK_TRADEOFF` |
| P4 | 36 / 1 | 36 / 1 | `NEUTRAL` | 36 / 1 | `NEUTRAL` |
| P7 | 32 / 5 | 34 / 1 | `STOCK_TRADEOFF` | 34 / 1 | `STOCK_TRADEOFF` |

Both treatments improved face-down on P0 without losing stock depth, tied A on P4, and exchanged local uncovering for stock progress on P2/P7. This inconsistent response is the direct basis for the predeclared mixed verdict.

## 4. P2/P7 balance result

P2's historical no-workspace endpoint was FD 39 / stock 0. A reproduced FD 26 / stock 4, a 13-card local gain with four undealt stock rows. B exactly reproduced the no-workspace endpoint. C dealt through the stock and reached FD 37 / stock 0, retaining only a two-card local gain over the historical control (15% of A's 13-card advantage). Its zero workspace expansions show that this residual difference was ordinary-search path variation, not preserved workspace circulation.

P7's historical no-workspace endpoint was FD 34 / stock 1. A reproduced FD 32 / stock 5. B and C both reached 34 / 1: they recovered four stock rows and surrendered all two cards of A's local advantage. Again C provided no workspace service.

Zero tolerance therefore moved stock materially downward on both diagnostic deals, but it did not preserve a substantial fraction of the useful local uncovering. C narrowly avoids the frozen `ZERO_TOLERANCE_OVER_SUPPRESSES` gate because P2 retained two cards relative to historical no-workspace, while the per-deal pattern still contains a P0 win and P4 neutral result; the applicable predeclared verdict is `STOCK_SYNCHRONY_MIXED`.

## 5. Stale-reservation analysis

| Deal | B withholds | B maximum / median span | B blocks >32 | B survives to end | C maximum / median span |
|---|---:|---:|---:|---:|---:|
| P0 | 49 | 395 / 395 | 1 | 1 | 0 / 0 |
| P2 | 49 | 391 / 391 | 1 | 1 | 0 / 0 |
| P4 | 47 | 374 / 374 | 1 | 1 | 0 / 0 |
| P7 | 49 | 392 / 392 | 1 | 1 | 0 / 0 |

B reproduced stale ownership decisively: four representatives were selected in total, one per deal, and every one remained live and lagging at experiment end without natural or forced expansion. The observed lag ranges were P0 2, P2 1–4, P4 1–4, and P7 1–5. The panel maximum span was 395.

C's maximum span was zero. More precisely, C selected zero representatives, so there was no lagging owner to release and consequently zero release/reselection events. At every selection point, the live leading stock epoch contained no qualifying workspace candidate. This validates the empty-lane semantics but does not demonstrate a beneficial release/reselection cycle.

## 6. Current-epoch opportunity blocking

While B's stale owners occupied the lane, the instrumented pre-expansion snapshots found:

- lag-0 candidate occurrences blocked: **0**;
- unique blocked candidate states: **0**;
- blocked states later expanded naturally: **0**.

Long stale ownership is therefore confirmed as a mechanical defect, but current-epoch opportunity blocking is not confirmed on these four runs. C could not restore same-epoch service because no such opportunity appeared. The two-card P2 endpoint difference between B and C arose without any C workspace selection or expansion and should not be attributed to released candidates being serviced.

## 7. Workspace circulation

The table records representatives, forced/natural service, withheld/released reservations, `EMPTY_CREATABLE` / `ACTUAL_EMPTY` expansions, productive descendants retained, and productive descendants reached through ordinary/workspace-serviced parents.

| Deal | Arm | Reps | Forced / natural | Withheld / released | EC / AE expanded | Productive retained | Ordinary / workspace serviced |
|---|---|---:|---:|---:|---:|---:|---:|
| P0 | A | 53 | 42 / 10 | 0 / 0 | 13 / 1 | 58 | 0 / 8 |
| P0 | B | 1 | 0 / 0 | 49 / 0 | 0 / 0 | 0 | 0 / 0 |
| P0 | C | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 | 0 / 0 |
| P2 | A | 282 | 13 / 268 | 0 / 0 | 51 / 18 | 504 | 3 / 68 |
| P2 | B | 1 | 0 / 0 | 49 / 0 | 0 / 0 | 0 | 0 / 0 |
| P2 | C | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 | 0 / 0 |
| P4 | A | 43 | 42 / 0 | 0 / 0 | 8 / 3 | 65 | 1 / 8 |
| P4 | B | 1 | 0 / 0 | 47 / 0 | 2 / 0 | 6 | 1 / 0 |
| P4 | C | 0 | 0 / 0 | 0 / 0 | 2 / 0 | 6 | 1 / 0 |
| P7 | A | 52 | 43 / 8 | 0 / 0 | 10 / 2 | 74 | 1 / 11 |
| P7 | B | 1 | 0 / 0 | 49 / 0 | 0 / 0 | 0 | 0 / 0 |
| P7 | C | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 | 0 / 0 |
| **Total** | **A** | **430** | **140 / 286** | **0 / 0** | **82 / 24** | **701** | **5 / 95** |
| **Total** | **B** | **4** | **0 / 0** | **194 / 0** | **2 / 0** | **6** | **1 / 0** |
| **Total** | **C** | **0** | **0 / 0** | **0 / 0** | **2 / 0** | **6** | **1 / 0** |

B and C retained 0.9% of A's productive descendants (6/701) and 20% of A's ordinary-serviced productive descendants (1/5). C did not preserve meaningful service circulation. The only B/C workspace-class expansions were two ordinary P4 `EMPTY_CREATABLE` expansions; neither treatment expanded an `ACTUAL_EMPTY` state.

Structural telemetry supports the same interpretation. P2/P7 treatment arms made zero R2 expansions versus 386/385 in A. The treatment arms did record stronger maximum stable same-suit joins and run mass on P7 (15 and 24 versus A's 6 and 11), but this accompanied no empty creation, no foundation, and no retained workspace circulation. Across all arms, maximum foundations remained 0, so no independent foundation replay was applicable.

## 8. Cost/search balance

| Deal | B/A tactical | C/A tactical | B/A time | C/A time |
|---|---:|---:|---:|---:|
| P0 | 0.950 | 0.921 | 0.939 | 0.956 |
| P2 | 0.501 | 0.440 | 0.576 | 0.468 |
| P4 | 0.852 | 0.889 | 0.941 | 0.952 |
| P7 | 0.141 | 0.143 | 1.117 | 1.129 |
| **Median** | **0.677** | **0.665** | **0.940** | **0.954** |

Lower tactical cost largely reflects suppressed workspace circulation, not better balanced progress. P7 is the clearest warning: both treatments used only about 14% of A's tactical nodes but took roughly 12% longer in wall time. All arms completed 400 strategic expansions.

Expansion counts by credit level 0/1/2/3/4 were:

| Deal | A | B | C |
|---|---|---|---|
| P0 | 93/79/77/76/75 | 90/81/77/76/76 | 90/81/77/76/76 |
| P2 | 98/82/76/72/72 | 93/79/78/76/74 | 94/80/79/74/73 |
| P4 | 96/79/77/75/73 | 97/76/76/76/75 | 97/76/76/76/75 |
| P7 | 86/82/78/78/76 | 93/78/78/77/74 | 93/78/78/77/74 |

The largest single-credit share was 24.5%, and the largest shift from A was 1.75 percentage points. Neither search-balance threshold (60% concentration or 25-point shift) was approached. All twelve runs stayed within frontier width, had no duplicate-node, replay, corrected-cost, or resource-planner violations, and recorded the full successor and TT telemetry in the machine-readable result.

The 14 focused stock-synchronous tests plus the prior 268-test relevant regression selection passed on this tree: `282 passed in 141.14s`. The focused suite was repeated after result/report generation: `14 passed in 0.92s`.

## 9. What this proves

For these four previously active deals, forced workspace entitlement cannot be restricted to exact leading-stock synchrony while retaining the mechanism's known local benefit. The useful P2/P7 workspace states arise behind the leading stock wave; excluding them from forced service makes search behave approximately like the historical no-workspace condition. Earlier-epoch membership does not make those states bad—their ordinary queue access remained unchanged—but exact lag-0 eligibility makes the service lane practically empty.

The experiment separately proves that HOLD semantics can create extreme stale ownership, and that releasing/emptying the lane removes that ownership. It does **not** prove that stale ownership blocked later lag-0 service: no qualifying current-epoch opportunity was observed behind any held representative. In this panel, the dominant cause is an over-strict eligibility boundary, not competition for the lane from the stale owner.

Accordingly, workspace service should not follow only the exact leading stock wave. A lagging reservation should still not own the lane indefinitely, but release semantics need to be paired with a bounded allowance for useful one-row-behind work rather than exact synchrony.

## 10. One next bounded experiment

Test a **one-shot lag-1 grace lease** on the same four frozen deals: a qualifying workspace state at `stock_lag == 1` may receive at most one forced service within each stock epoch, after which its reservation is released and it has only ordinary queue access until the leading stock depth changes. Compare this single treatment with A under the same N=8 and search envelope. This isolates whether a tightly capped amount of one-row-behind service can retain P2/P7 local uncovering without recreating unconditional N8 stock stall or indefinite HOLD ownership; do not change priority, workspace definitions, or any other mechanism.
