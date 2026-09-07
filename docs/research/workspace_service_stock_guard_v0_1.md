# Stock-Aware Workspace-Service Guard Experiment v0.1

## 1. Verdict

`STOCK_GUARD_INERT`

The one-row stock-lag guard did not repair the previously observed P2/P7 tradeoff. It withheld 92 scheduled services, but only on P0 and P4. P2 and P7 always presented lag 1 at their scheduled opportunities, so every forced service remained allowed and both diagnostic pairs reproduced the unguarded N8 endpoints exactly.

Across the frozen ten-deal panel, face-down improved/tied/worsened on 1/9/0 deals and stock progression improved/tied/worsened on 0/9/1. The four-deal active subset classified as 1 WIN, 0 TRADEOFF, 3 NEUTRAL, and 0 LOSS. The sole WIN was P0's one-card face-down improvement with tied stock depth; P4 tied face-down but lost one stock row and is NEUTRAL under the predeclared rule.

The experiment started from `7444850e158619353df6e6ea18b190ef22d56b37` on branch `agent/workspace-service-stock-guard-v0-1`. All twenty searches completed and all integrity gates passed.

## 2. Exact stock guard

The treatment preserved the generic one-representative workspace lane, COMMON_STAGE0 ordering, STATE_LOCAL credit, N=8 service interval, frontier cap 256, successor portfolio 10, maximum credit 4, and the existing `ACTUAL_EMPTY` / `EMPTY_CREATABLE` qualification. It did not invoke the resource planner.

At each otherwise-due forced service, the harness deduplicated the live, non-stale ordinary frontier entries eligible for an ordinary pop and computed:

```text
stock_lag = workspace_stock_rows - min(live ordinary stock rows)
```

Forced service was withheld only when `stock_lag > 1`. Lag 0 or 1 was serviced normally. A withheld representative stayed live without cloning or reinsertion, the ordinary queue received that opportunity, the interval counter reset, and no catch-up entitlement accumulated. Natural workspace pops were never blocked.

The combined endpoint was frozen before search, using guarded-minus-N8 deltas (negative is better): WIN if stock improves with face-down no worse than +1, or face-down improves with stock no worse; LOSS if both worsen; TRADEOFF if stock improves while face-down worsens by more than 1, or face-down improves while stock worsens; NEUTRAL otherwise.

## 3. Reproduction of N8 baseline

The fresh causal baseline used the same ten frozen openings and the same 400-expansion, 300,000-tactical-node, 900-second envelope. All ten stock minima and all ten foundation maxima reproduced the previous panel exactly. Nine face-down minima reproduced exactly. P9 changed from historical 40 to fresh 43, but both new arms matched at 43 and neither had a service opportunity, identifying this as cross-run timing/environment drift rather than a guard effect.

| Deal | Prior N8 FD | Fresh N8 FD | Prior N8 stock | Fresh N8 stock | Prior/fresh foundations |
|---|---:|---:|---:|---:|---:|
| P0 | 37 | 37 | 3 | 3 | 0 / 0 |
| P1 | 40 | 40 | 1 | 1 | 0 / 0 |
| P2 | 26 | 26 | 4 | 4 | 0 / 0 |
| P3 | 41 | 41 | 1 | 1 | 0 / 0 |
| P4 | 36 | 36 | 1 | 1 | 0 / 0 |
| P5 | 41 | 41 | 0 | 0 | 0 / 0 |
| P6 | 36 | 36 | 3 | 3 | 0 / 0 |
| P7 | 32 | 32 | 5 | 5 | 0 / 0 |
| P8 | 38 | 38 | 3 | 3 | 0 / 0 |
| P9 | 40 | 43 | 1 | 1 | 0 / 0 |

Arm order was frozen before search: guard first on even-numbered deals and N8 first on odd-numbered deals.

## 4. Ten-deal paired table

FD and stock deltas are guarded minus N8; negative is better.

| Deal | N8 FD | Guard FD | ΔFD | N8 stock | Guard stock | Δstock | Class |
|---|---:|---:|---:|---:|---:|---:|---|
| P0 | 37 | 36 | -1 | 3 | 3 | 0 | WIN |
| P1 | 40 | 40 | 0 | 1 | 1 | 0 | NEUTRAL |
| P2 | 26 | 26 | 0 | 4 | 4 | 0 | NEUTRAL |
| P3 | 41 | 41 | 0 | 1 | 1 | 0 | NEUTRAL |
| P4 | 36 | 36 | 0 | 1 | 2 | +1 | NEUTRAL |
| P5 | 41 | 41 | 0 | 0 | 0 | 0 | NEUTRAL |
| P6 | 36 | 36 | 0 | 3 | 3 | 0 | NEUTRAL |
| P7 | 32 | 32 | 0 | 5 | 5 | 0 | NEUTRAL |
| P8 | 38 | 38 | 0 | 3 | 3 | 0 | NEUTRAL |
| P9 | 43 | 43 | 0 | 1 | 1 | 0 | NEUTRAL |

All maximum-foundation counts were 0 in both arms. The panel combined endpoint was 1 WIN, 0 TRADEOFF, 9 NEUTRAL, 0 LOSS.

## 5. Guard-event analysis

| Deal | Opportunities | Forced | Withheld | Distinct affected | Max lag | Median lag | Later natural | Later forced | Never serviced |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 | 49 | 0 | 49 | 1 | 2 | 2 | 0 | 0 | 1 |
| P1 | 0 | 0 | 0 | 0 | — | — | 0 | 0 | 0 |
| P2 | 13 | 13 | 0 | 0 | 1 | 1 | 0 | 0 | 0 |
| P3 | 0 | 0 | 0 | 0 | — | — | 0 | 0 | 0 |
| P4 | 47 | 4 | 43 | 1 | 3 | 3 | 0 | 0 | 1 |
| P5 | 0 | 0 | 0 | 0 | — | — | 0 | 0 | 0 |
| P6 | 0 | 0 | 0 | 0 | — | — | 0 | 0 | 0 |
| P7 | 43 | 43 | 0 | 0 | 1 | 1 | 0 | 0 | 0 |
| P8 | 0 | 0 | 0 | 0 | — | — | 0 | 0 | 0 |
| P9 | 0 | 0 | 0 | 0 | — | — | 0 | 0 | 0 |

All 92 withholds repeatedly affected one representative on each of P0 and P4. Both representatives remained live at the end; neither expanded naturally, was later forced, was replaced, nor was trimmed. This confirms the intended no-catch-up semantics, but it also reveals that repeated reevaluation can spend all later service opportunities asking the same unchanged question.

The prior null set P1/P3/P5/P6/P8/P9 remained behaviourally inert: zero opportunities and exact fresh-arm endpoint matches on every deal.

## 6. Face-down versus stock-progression tradeoff

The guard did not produce the intended pattern of deeper stock progress with preserved face-down progress. Panel-wide stock had no improvements, nine ties, and one worsening; face-down had one improvement, nine ties, and no worsening.

On P0, suppressing the lane entirely changed EC/AE expansions from 13/1 to 0/0 and improved minimum face-down from 37 to 36, while stock tied at 3. On P4, substantial suppression changed EC/AE expansions from 8/3 to 3/0, face-down tied at 36, and stock worsened from 1 to 2. The effects therefore do not support stock lag greater than one as a useful balance signal.

## 7. P2/P7 diagnostic analysis

P2 historical no-workspace was FD 39 / stock 0, while prior and fresh N8 were FD 26 / stock 4. The guarded result was also FD 26 / stock 4. All 13 scheduled events had lag 1 and were serviced. No stock recovery occurred, all 13 cards of historical face-down advantage survived, and no event was withheld.

P7 historical no-workspace was FD 34 / stock 1, while prior and fresh N8 were FD 32 / stock 5. The guarded result was also FD 32 / stock 5. All 43 scheduled events had lag 1 and were serviced. No stock recovery occurred, both cards of historical face-down advantage survived, and no event was withheld.

Thus the diagnostic gate is unambiguous: the chosen threshold does not engage on either target tradeoff. The unchanged endpoints are faithful consequences of the predeclared policy, not evidence that stock-aware gating in general cannot work.

## 8. Workspace-circulation impact

| Deal | Arm | EC expanded | AE expanded | Representatives | Forced / natural | Productive retained | Ordinary-serviced | Workspace-serviced |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| P0 | N8 | 13 | 1 | 53 | 42 / 10 | 57 | 0 | 8 |
| P0 | Guard | 0 | 0 | 1 | 0 / 0 | 0 | 0 | 0 |
| P2 | N8 | 51 | 18 | 282 | 13 / 268 | 506 | 3 | 68 |
| P2 | Guard | 51 | 18 | 282 | 13 / 268 | 505 | 3 | 68 |
| P4 | N8 | 8 | 3 | 43 | 42 / 0 | 64 | 1 | 8 |
| P4 | Guard | 3 | 0 | 12 | 4 / 7 | 18 | 1 | 2 |
| P7 | N8 | 10 | 2 | 52 | 43 / 8 | 76 | 1 | 11 |
| P7 | Guard | 10 | 2 | 52 | 43 / 8 | 76 | 1 | 11 |

Ordinary-serviced productive descendants totaled 5 in both arms panel-wide and 5 in both arms on the active subset. The guard therefore did not improve ordinary recirculation. It either left circulation unchanged (P2/P7 and all null deals) or sharply curtailed it around a single persistently lagging representative (P0/P4).

## 9. Cost and search balance

Panel-wide, the median guarded/N8 tactical-node ratio was 0.9869 and the median elapsed-time ratio was 0.9955. Across the four active deals the corresponding medians were 0.9647 and 0.9633. The large tactical reduction on P4 (ratio 0.5184) reflects workspace suppression, but it accompanied a one-row stock regression rather than improved whole-game progress. P0's tactical ratio was 0.9580; P2 and P7 were approximately unchanged at 1.0056 and 0.9714.

All arms completed 400 strategic expansions. There were no credit-balance flags, replay failures, corrected-cost inconsistencies, proof prunes, duplicate node IDs, frontier-width violations, or resource-planner calls. Tactical cost was bounded, but lower cost did not translate into the intended stock endpoint improvement.

The 13 focused guard tests plus the existing 255-test relevant regression selection passed on the final tree: `268 passed in 137.48s`.

## 10. What this proves

The experiment answers the stated question negatively for this exact guard: it does not keep the useful empty-column intelligence while restoring stock progression. The rule is mechanically sound and truly active where lag exceeds one, but the two known stock-stalled successes operate at lag exactly one. Meanwhile, on P0 and P4 the rule repeatedly suppresses a single lagging representative without producing stock recovery.

This narrows the causal diagnosis. The issue is not merely unlimited forced service to representatives two or more rows behind. The relevant interaction lies at the one-row boundary, or in how a withheld representative is reconsidered, and must be tested separately rather than inferred from this result.

## 11. One next bounded experiment

Run the same frozen two-arm P0–P9 panel with the sole change that forced service is withheld when `stock_lag > 0` (a fixed zero-row tolerance), retaining N=8, all budgets, and every other mechanism unchanged. This directly engages the lag-1 P2/P7 events and tests whether stock recovery can be obtained without erasing their historical face-down advantages.
