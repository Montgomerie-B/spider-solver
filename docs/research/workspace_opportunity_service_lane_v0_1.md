# Bounded Workspace-Opportunity Service Lane Experiment v0.1

## 1. Verdict

`WORKSPACE_SERVICE_EFFECTIVE`

The fixed `N = 8` lane converted naturally retained but unserved workspace opportunities into actual strategic expansions without changing production priority, frontier width, state-local credit, successor generation, TT policy, scheduler order, or tactical allocation. `EMPTY_CREATABLE` expansions increased from 0 to 13 and `ACTUAL_EMPTY` expansions from 0 to 1. The lane retained 57 productive workspace descendants; 2 of those descendants later expanded through the ordinary queue and 8 through later workspace service. This is broader, non-duplicate structural circulation rather than service activity alone.

The result is bounded rather than a strong solve-progress result. Neither arm reached a foundation, treatment minimum face-down was 37 versus control's 36, and no tracked chain reached all three allowed descendant generations. The positive structural evidence is the new actual-empty expansion, two-generation continuation, and downstream ordinary service.

## 2. Exact service mechanism

Qualification is state structural and engine-authoritative:

- `ACTUAL_EMPTY`: at least one tableau column is structurally empty.
- `EMPTY_CREATABLE`: zero empty columns and at least one enumerated, legal move transfers the entire movable contents of a fully revealed source column and leaves that source empty after replay.

The treatment maintains at most one reservation. It selects `min(existing ordinary queue priority, node_id)` from live qualifying entries that have not already received expansion at that exact `(state, strategic-credit)` identity. It preserves and later removes the exact existing frontier tuple; it never fabricates or clones an arrival.

After eight ordinary strategic expansions, an eligible reserved entry is serviced next. Natural expansion spends the reservation without forcing; loss of liveness or eligibility invalidates it; a replacement is then selected from the live frontier. The representative occupies the unchanged 256-entry frontier and may replace the worst unprotected retained entry during trimming. Overlap with existing protection is detected by node ID so the lane cannot add a duplicate.

The treatment is implemented only by the research observer around the unchanged production-style controller. No digest, action path, column, card, suit, rank, or deal-specific condition participates in qualification or selection.

## 3. Control reproduction

Both arms started from commit `12e8d9cb0af2212d37f9891f3f77df6ac220bd47` and used deal 4925153, seed 0, `COMMON_STAGE0`, `STATE_LOCAL`, 400 strategic expansions, 300,000 tactical nodes, 900 seconds, frontier cap 256, successor portfolio 10, maximum credit 4, scheduler and tactical allocation enabled, no incumbent, and the inherited diagnostic foundation stop.

Control reproduced the current behavior: 400 strategic expansions with credit distribution `90 / 81 / 77 / 76 / 76`. It naturally generated and retained workspace opportunities but expanded neither an `EMPTY_CREATABLE` nor an `ACTUAL_EMPTY` state. It stopped on the strategic expansion limit with no replay, corrected-cost, or proof-pruning integrity failure.

## 4. A/B metrics

| Metric | CONTROL | WORKSPACE_SERVICE_1 |
| --- | ---: | ---: |
| Stop reason | strategic expansion limit | strategic expansion limit |
| Expansions | 400 | 400 |
| Credit 0–4 | 90 / 81 / 77 / 76 / 76 | 93 / 79 / 77 / 76 / 75 |
| Tactical nodes | 51,389 | 55,886 |
| Time | 576.902 s | 599.998 s |
| Successors generated | 1,910 | 1,909 |
| Successors retained | 507 | 525 |
| TT new / improved / suppressed | 504 / 4 / 1,403 | 522 / 4 / 1,384 |
| Proof prunes | 0 | 0 |
| Replay failures | 0 | 0 |
| Corrected-cost inconsistencies | 0 | 0 |
| Minimum face-down | 36 | 37 |
| Foundations | 0 | 0 |
| Minimum buried depth | not available | not available |
| EMPTY_CREATABLE generated / retained | 22 / 10 | 136 / 45 |
| EMPTY_CREATABLE popped / expanded / trimmed | 0 / 0 / 2 | 13 / 13 / 7 |
| ACTUAL_EMPTY generated / retained | 0 / 0 | 49 / 12 |
| ACTUAL_EMPTY popped / expanded / trimmed | 0 / 0 / 0 | 1 / 1 / 5 |
| Max empties | 0 | 1 |
| Workspace representatives serviced | 0 | 52 (10 natural, 42 forced) |
| Productive workspace descendants retained | 0 | 57 |
| Stock rows expanded (5 / 4 / 3 / 2) | 1 / 5 / 394 / 0 | 1 / 7 / 392 / 0 |

Generated workspace counts include repeated lifecycle observations. Unique generated/retained states were 10/10 control versus 45/45 treatment for `EMPTY_CREATABLE`, and 0/0 versus 12/12 for `ACTUAL_EMPTY`.

R2 lifecycle counts were:

| R2 metric | CONTROL | WORKSPACE_SERVICE_1 |
| --- | ---: | ---: |
| Generated | 1,898 | 1,848 |
| Retained | 498 | 504 |
| Popped | 91 | 93 |
| Expanded | 87 | 89 |
| Trimmed | 172 | 183 |
| Unique generated / retained | 494 / 494 | 500 / 500 |
| Unique popped / expanded | 87 / 87 | 89 / 89 |

## 5. Workspace lifecycle

Treatment selected 53 representatives: 48 `EMPTY_CREATABLE` and 5 `ACTUAL_EMPTY`. Outcomes were 42 forced expansions, 10 natural expansions, and 1 live reservation at the experiment end. There were 52 replacements, no invalidations, and a maximum of one outstanding reservation.

Every forced expansion occurred after exactly eight ordinary expansions. Natural service occurred after zero ordinary expansions nine times and after five once. No trim protection was needed in this run. The lane introduced zero duplicate entries, and no pre-existing duplicate occurrence was observed.

Successors of the 52 serviced workspace states had these structural effects. A successor may contribute to more than one row.

| Effect | Successor occurrences |
| --- | ---: |
| Preserves an empty | 5 |
| Consumes an empty | 23 |
| Creates an empty | 44 |
| Reduces face-down | 0 |
| Improves same-suit structure | 122 |
| Closes scheduler/campaign dependencies | 20 |
| Reaches another workspace opportunity | 169 |
| Reaches a foundation | 0 |

Of these successors, 57 productive workspace descendants were retained. Two later received ordinary expansion without workspace intervention; eight later received workspace-lane expansion.

## 6. Structural progress

The lane opened a structural class absent from control expansion: treatment created up to one actual empty and expanded one actual-empty state. It also expanded 13 `EMPTY_CREATABLE` states that control left entirely unexpanded. Treatment retained 18 more successors and admitted 18 more TT-new arrivals while suppressing 19 fewer arrivals.

This did not yet compound into face-down or foundation progress. Control reached 36 face-down while treatment reached 37, both remained at zero foundations, and neither arm expanded a state with only two stock rows remaining. A generic buried-depth scalar does not exist in the current controller measurement, so no value is inferred.

## 7. Descendant analysis

The diagnostic recorded one chain per serviced workspace expansion. Of 52 chains, 37 had a retained strongest successor: 28 continued for one generation and 9 for two generations; 15 had no retained continuation and none reached the three-generation observation limit.

The key architectural signal is present in bounded form: workspace service produced useful retained successors, some returned to workspace eligibility, and two descendants were subsequently selected by the unchanged ordinary queue. The signal is not yet sustained face-down progress: no serviced successor reduced face-down or reached a foundation, and most retained descendants did not receive later expansion within the 400-expansion envelope.

## 8. Search-balance analysis

State-local widening remained balanced. Control devoted 90 expansions to credit 0 and 310 to credits 1–4; treatment devoted 93 and 307 respectively. The largest per-credit shift was three expansions, so the service lane did not recreate an inherited-credit avalanche or collapse broad-credit circulation.

Forced service occupied 42 of 400 expansions (10.5%), below the one-in-eight maximum because reservations were sometimes consumed naturally or unavailable. Ordinary priority controlled all non-service pops. Tactical work increased by 4,497 nodes (8.75%) and elapsed time by 23.096 seconds (4.00%), while both arms stopped at the same strategic limit. Frontier size ended at 255 control and 256 treatment, never exceeded the fixed cap, and contained no duplicate node IDs.

## 9. What this proves

Under this fixed deal and envelope, lack of reliable queue service is causally sufficient to explain part of the workspace-opportunity starvation. Changing only bounded service raised workspace expansions from zero to 14 across the two structural classes, exposed and expanded an actual empty, retained productive continuations, and allowed two of those continuations to re-enter ordinary search. Existing production generation therefore has useful capability behind the queue bottleneck.

It does not prove a global ranking policy, generalization beyond this deal, a solving advantage, or sustained reduction of hidden cards. It also does not overturn the exact-state TT result: the lane preserves existing TT dominance and services exact existing entries rather than reopening dominated arrivals.

All mechanical gates passed: generic qualification, one reservation, bounded service, fixed capacity, no lane duplicates, replay/cost integrity, unchanged production defaults, and zero resource-planner calls. The result therefore supports a generic structural-service component as a research direction, while the absence of face-down and foundation gains limits the claim to early compounding rather than endgame progress.

## 10. One next bounded experiment

Run the identical fixed `N = 8` CONTROL/WORKSPACE_SERVICE_1 comparison, without tuning or additional policy changes, on a predeclared ten-deal four-suit panel and use ordinary-serviced productive descendants plus minimum face-down as the primary generalization endpoints.

**Verification.** The 12 focused service-lane gates and the requested comparator, state-local, R3, empty-state, exact-context, controller, and resource regression selection passed: `245 passed in 134.77s`.

Machine-readable evidence is in `docs/research/workspace_opportunity_service_lane_v0_1.json`.
