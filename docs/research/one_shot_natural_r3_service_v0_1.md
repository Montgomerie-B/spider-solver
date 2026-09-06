# One-Shot Natural R3 Service Experiment v0.1

Base: `60d83bd7823aebffed9fe8ecf83e311046641c76`

Deal: `4925153`; seed: `0`

Both arms used `COMMON_STAGE0`, `STATE_LOCAL`, 400 strategic expansions,
300,000 tactical nodes, 900 seconds, frontier cap 256, successor portfolio 10,
maximum credit 4, the enabled scheduler and tactical allocator, no incumbent,
and the inherited two-foundation diagnostic stop.

## 1. Verdict

`R3_SERVICE_SUFFICIENT`

One ordinary expansion of the strongest naturally admitted live R3 caused the
unchanged production generator to emit its engine-legal empty-creating move
exactly. The successor independently replayed, passed every portfolio stage,
was admitted as a new TT state, and was retained as the first actual-empty node.

This establishes service sufficiency for this natural state. It does not establish
a production reservation policy: the retained empty itself received no ordinary
pop or expansion during the remaining budget.

## 2. Exact intervention

The treatment used a research-harness-only heap extraction. At the next ordinary
strategic pop, it examined current frontier entries and admitted only nodes that:

* originated as ordinary `SUCCESSOR` admissions;
* were still present in the live heap;
* had zero actual empty columns; and
* exposed at least one move returned by `SpiderState.enumerate_moves()`, confirmed
  by `SpiderState.can_move()`, which moved all face-up cards from a fully revealed
  source and left that source structurally empty after `SpiderState.move()`.

The selected entry was `min(existing_queue_priority, node_id)` among those
candidates. The exact existing tuple was removed from the 16-entry heap and
returned as the next pop, leaving 15 entries. No node was cloned, no arrival was
fabricated, and no state, g, actions, depth, credit, analysis/context, scheduler
data, TT status, or node identity was changed. The service flag was then
permanently spent. Frontier capacity remained 256 and exactly one special service
occurred.

Control installed the same observer with service disabled and recorded zero
interventions. The resource excavation planner was never called and is not
referenced by the production controller.

## 3. Control reproduction

Control closely reproduced the previous state-local arm:

* credit expansions were `[90, 80, 78, 77, 75]`, versus the prior
  `[90, 81, 77, 76, 76]`;
* 400 strategic expansions reached the expansion limit;
* 10 unique R3 states were retained, none popped or expanded, and two were
  trimmed;
* no actual empty and no foundation was generated; and
* minimum face-down remained 36.

The small credit, tactical-node (52,397 versus 52,516), generated-successor
(1,905 versus 1,909), and TT-suppression (1,398 versus 1,402) differences are
timing-sensitive. Retention (507), TT new/improved (504/4), structural outcome,
and stop reason reproduced. There is no material divergence that prevents causal
interpretation.

## 4. Selected R3 anatomy

The selected natural parent was:

| Fact | Value |
|---|---:|
| Digest | `bf5a42ecfefd5ff4` |
| Node ID | 18 |
| Corrected g | 7 |
| Strategic credit | 0 (`CLEAN`) |
| Macro depth | 4 |
| Total face-down | 40 |
| Fully revealed columns | 1 |
| Actual empties | 0 |
| Stock rows undealt | 4 |
| Queue rank before intervention | 3 |

Two eligible candidates were live at selection time. The existing ordinary key
ranked `bf5a42ecfefd5ff4` / node 18 at rank 3 and
`5481589d5f04c257` / node 17 at rank 4; both had g=7, credit 0, and the same legal
empty-creating move. No digest participated in qualification or selection.

The selected node's current scheduler lead was spades lane 1 in `MERGE_READY`
state at schedule epoch 1. It had no incoming scheduled objective, incoming
scheduler effect rank 2, no active milestone or residual target, and an active
same-campaign continuation for `C#1`. The complete ordering key and scheduler
objects are preserved in the JSON artefact.

## 5. Legal empty-creating moves

Engine-authoritative enumeration found exactly one full-column relocation:

`(5, 4, 1)`

Columns are zero-based in this research trace. The engine enumerated the move,
`can_move(5, 4, 1)` accepted it, the source contained one face-up card and no
face-down cards, and replay left source column 5 empty.

Ordinary production represented the move **exactly**, not merely as the beginning
of a macro. It appeared as raw candidate 4 in the
`CAMPAIGN_DEPENDENCY_CLOSURE / dependency_closure` family. It survived
deduplication, the diverse portfolio, obligation retention, and final portfolio;
the TT had no previous entry and admitted it at child g=8; the controller retained
it.

## 6. Production successor autopsy

The selected parent's ordinary production pipeline contained six raw candidates,
five after exact-state deduplication, and five after each of the diverse,
obligation, and final portfolio stages. Every raw edge independently replayed to
the recorded digest and corrected cost. The unchanged portfolio cap of 10 did not
truncate this expansion.

| Raw | Family / category | Actions | Cost | End digest | Empty | Pre-final disposition | TT | Retained / later lifecycle |
|---:|---|---|---:|---|---:|---|---|---|
| 0 | `SAME_SUIT_CONSTRUCTION` / `run_construction` | `(0,5,1)` | 1 | `4a9c3b4f295f77f2` | 0 | final | new/admitted | yes; later popped and expanded |
| 1 | `SAME_SUIT_CONSTRUCTION` / `run_construction` | `(8,6,1)` | 1 | `460a56320ea0e31e` | 0 | final | new/admitted | yes; live, not popped |
| 2 | `ECONOMIC_PROJECT` / `permanent_structure` | `(3,4,1)` | 1 | `cc26b5f6bd1bafb4` | 0 | final | new/admitted | yes; live, not popped |
| 3 | `ECONOMIC_PROJECT` / `permanent_structure` | `(8,6,1)` | 1 | `460a56320ea0e31e` | 0 | removed by exact-state deduplication in favour of raw 1 | not reached | no |
| 4 | `CAMPAIGN_DEPENDENCY_CLOSURE` / `dependency_closure` | `(5,4,1)` | 1 | `32d26205a312db97` | 1 | final | new/admitted | yes; live, not popped |
| 5 | `RAW_DEAL` / `deal_timing` | `deal` | 1 | `16ca20ca70a2f2cf` | 0 | final | new/admitted | yes; live, not popped |

Thus there was no family-cap, final-portfolio, TT, replay, or proof gate suppressing
the legal empty edge. The only pre-final removal was an unrelated exact duplicate
of `(8,6,1)`.

## 7. A/B outcome

Counts below are event counts; R2/R3 unique counts are noted afterward.

| Metric | A: control | B: one-shot R3 service |
|---|---:|---:|
| Stop reason | expansion limit | expansion limit |
| Strategic expansions | 400 | 400 |
| Credit 0/1/2/3/4 expansions | 90 / 80 / 78 / 77 / 75 | 89 / 79 / 78 / 77 / 77 |
| Tactical nodes | 52,397 | 61,126 |
| Elapsed seconds | 597.217 | 603.017 |
| Successors generated / retained | 1,905 / 507 | 1,793 / 483 |
| TT new / improved / suppressed | 504 / 4 / 1,398 | 477 / 7 / 1,310 |
| Minimum face-down | 36 | 38 |
| R2 generated / retained / popped / expanded | 1,893 / 498 / 91 / 87 | 1,770 / 471 / 90 / 86 |
| R3 generated / retained / popped / expanded / trimmed | 22 / 10 / 0 / 0 / 2 | 31 / 23 / 4 / 4 / 0 |
| Actual empties generated / retained / popped / expanded | 0 / 0 / 0 / 0 | 11 / 3 / 0 / 0 |
| Maximum foundations | 0 | 0 |
| Final frontier credit 0/1/2/3/4 | 241 / 10 / 2 / 1 / 2 | 244 / 10 / 1 / 1 / 0 |

Control R2 generated/retained/popped/expanded unique digests were
494/494/87/87; treatment was 464/464/86/86. Control R3 unique counts were
10/10/0/0; treatment was 23/23/4/4. The one special R3 expansion therefore
altered the reachable search trajectory enough that three additional R3 expansion
events received ordinary service.

Stock-row distributions (`rows: count`) were:

| Stage | A: control | B: one-shot R3 service |
|---|---|---|
| Generated | 5:2, 4:15, 3:1,421, 2:467 | 5:2, 4:19, 3:1,274, 2:498 |
| Retained | 5:2, 4:13, 3:374, 2:118 | 5:2, 4:17, 3:343, 2:121 |
| Expanded | 5:1, 4:5, 3:394 | 5:1, 4:6, 3:393 |

The first empty was raw candidate 4 from the serviced parent:

* family: `CAMPAIGN_DEPENDENCY_CLOSURE / dependency_closure`;
* actions: `(5,4,1)`;
* corrected edge cost: 1; resulting g: 8;
* result digest: `32d26205a312db97`;
* empty count: 1; face-down: 40; stock rows: 4;
* independent replay: true;
* TT: new/admitted;
* retained: true as node 24;
* end state: still live, never trimmed, but not naturally popped or expanded.

Search continued to 400 expansions. Treatment generated 11 empty-state events
and retained three, but none received a pop or expansion; minimum face-down was
38 and foundations remained zero. R3 service exposed existing empty-producing
capability, while downstream empty-state service remains unresolved.

## 8. What this proves

For this exact commit, deal, seed, and budget, lack of service—not lack of
successor coverage—prevented this natural R3 from producing the first empty.
One within-capacity expansion opportunity was sufficient for unchanged production
machinery to expose, replay, admit, and retain the legal primitive.

The experiment does not show that the chosen state is globally best, that a
persistent R3 bonus is desirable, that the resulting search is stronger by global
progress metrics, or that empty retention guarantees useful continuation. In
fact, the first empty remained unserviced, treatment minimum face-down regressed,
and no foundation was reached. The known reopening, TT-after-eviction, and
duplicate-protection defects were held constant.

## 9. One next bounded experiment

A/B exactly one within-capacity ordinary service reservation for the strongest
naturally retained actual-empty state under the same `COMMON_STAGE0 + STATE_LOCAL`
configuration, to test whether existing production successors can exploit the
workspace after it is retained; do not add a priority bonus or resource planner.

## Tests run

* Focused one-shot R3 service tests: 8 passed.
* Comparator/state-local/controller/natural-resource/resource-integrity regression
  selection: 209 passed.
* Total distinct tests: 217 passed.

Machine-readable results:
`docs/research/one_shot_natural_r3_service_v0_1.json`.
