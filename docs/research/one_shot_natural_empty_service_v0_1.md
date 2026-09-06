# One-Shot Natural Empty-State Service Experiment v0.1

Base: `5cda8eaeb6f230113be56d82c8ac0797c85d251a`

Deal: `4925153`; seed: `0`

All arms used `COMMON_STAGE0`, `STATE_LOCAL`, 400 strategic expansions,
300,000 tactical nodes, 900 seconds, frontier cap 256, successor portfolio 10,
maximum credit 4, the enabled scheduler and tactical allocator, no incumbent,
and the inherited two-foundation diagnostic stop.

## 1. Primary verdict

`EMPTY_SUCCESSOR_EXISTS_BUT_IS_SUPPRESSED`

The serviced natural empty parent generated one independently replay-valid
`PRODUCTIVE_EMPTY_USE` candidate through ordinary production. It consumed the
empty as workspace and carried existing dependency/campaign progress evidence.
It survived deduplication and every portfolio stage, but the exact TT suppressed
it because its endpoint was a previously reached state at higher corrected g.

Production also retained two `EMPTY_PRESERVED_PROGRESS` successors which made
same-suit structural gains without using the empty. One later received ordinary
service. These are useful downstream states, but they do not satisfy the narrower
claim that production retained a successor which productively used the workspace.

## 2. Exact experimental design

The preferred three-arm design was used:

1. `CONTROL`: no special service;
2. `R3_ONLY`: the exact inherited one-shot natural-R3 heap extraction;
3. `R3_THEN_EMPTY`: the same R3 extraction, followed by one extraction of the
   strongest naturally admitted live actual-empty node.

The R3 service implementation was imported unchanged from the preceding
experiment. Arms B and C used the same class and implementation SHA-256, and
selected the same R3 fingerprint: digest `bf5a42ecfefd5ff4`, g=7, credit 0,
legal move `(5,4,1)`, exactly one R3 service. The empty intervention was disabled
in B and enabled only as the second-stage treatment in C.

For empty service, live heap entries qualified only when their observer origin was
the ordinary `SUCCESSOR` path—which follows successful TT admission—and their
engine state contained a structurally empty tableau column. Selection used
`min(existing_queue_priority, node_id)`. The exact existing entry was extracted
for the next pop; no clone, new arrival, metadata change, reanalysis, priority
bonus, extra capacity, or special descendant service was introduced. The flag was
then permanently spent.

No resource excavation planner was invoked. COMMON_STAGE0, state-local credit,
scheduler order, frontier and portfolio widths, tactical grants, successor
families, TT, proof rules, and corrected-cost accounting were unchanged.

## 3. Control and R3-only reproduction

Control reproduced the established state-local behavior:

* credit expansions `[90, 80, 78, 77, 75]`;
* 10 unique R3 states retained, none popped or expanded, two trimmed;
* zero actual-empty events and zero foundations;
* minimum face-down 36.

R3-only reproduced the previous prerequisite treatment:

* credit expansions `[89, 79, 78, 77, 77]`;
* 23 unique R3 states retained and four popped/expanded;
* 11 empty events generated, three retained, none popped/expanded;
* zero foundations and minimum face-down 38.

Timing-sensitive counts were close to the preceding measurement: R3-only used
62,630 tactical nodes, generated 1,794 successors, retained 484, and recorded TT
478/7/1,310 new/improved/suppressed. The previous run recorded
61,126, 1,793, 483, and 477/7/1,310 respectively. The R3 and empty lifecycle,
credit distribution, selected prerequisite, stop reason, and causal boundary all
reproduced.

## 4. Selected empty-state anatomy

| Fact | Value |
|---|---:|
| Digest | `32d26205a312db97` |
| Node ID | 24 |
| Corrected g | 8 |
| Strategic credit | 0 (`CLEAN`) |
| Macro depth | 5 |
| Total face-down | 40 |
| Actual empty columns (zero-based) | `[5]` |
| Fully revealed non-empty columns | 0 |
| Stock rows undealt | 4 |
| Queue rank before intervention | 5 |
| Legal tableau moves | 16 |

This was the only eligible empty at selection time. It was an ordinary TT-admitted
successor of node 18 / `bf5a42ecfefd5ff4`, created by
`CAMPAIGN_DEPENDENCY_CLOSURE / dependency_closure`, action `(5,4,1)`, corrected
edge cost 1.

Its scheduler lead was spades lane 1 in `MERGE_READY` state at schedule epoch 1.
It had no incoming scheduled objective, incoming effect rank 2, no active
milestone or residual target, and a replanned `C#1` continuation. Full scheduler,
continuation, ordering, and candidate facts are in the JSON artefact.

The treatment removed the exact node from a 21-entry heap, leaving 20 entries;
frontier capacity remained 256 and state, g, credit, actions, history, and context
were unchanged.

## 5. Complete production successor autopsy

The ordinary expansion produced six raw candidates, four exact-state-deduplicated
candidates, and four candidates after the diverse, obligation, and final portfolio
stages. The portfolio cap of 10 did not truncate this expansion. Every raw edge
independently replayed to its recorded endpoint and corrected cost.

| Raw | Family / category | Actions | Cost | End digest | Empty before→after | Empty use | Existing measured progress | Pipeline / TT / retention |
|---:|---|---|---:|---|---|---|---|---|
| 0 | `SAME_SUIT_CONSTRUCTION` / `run_construction` | `(0,4,1)` | 1 | `d7d7c36cdf81718e` | 1→1 | neither consumed nor used | stable joins +1; same-suit mass +2; campaign-specific investment evidence | merged into the raw-3-derived deduplicated representative |
| 1 | `SAME_SUIT_CONSTRUCTION` / `run_construction` | `(8,6,1)` | 1 | `3166ccb1c4ee0379` | 1→1 | neither consumed nor used | stable joins +1; same-suit mass +2; mixed boundaries −1; rehandling debt −1; mobility +1; campaign-specific evidence | merged into the raw-2-derived deduplicated representative |
| 2 | `ECONOMIC_PROJECT` / `permanent_structure` | `(8,6,1)` | 1 | `3166ccb1c4ee0379` | 1→1 | neither consumed nor used | same structural facts as raw 1 | retained as enriched `ECONOMIC_PROJECT / run_construction`; TT new/admitted |
| 3 | `ECONOMIC_PROJECT` / `permanent_structure` | `(0,4,1)` | 1 | `d7d7c36cdf81718e` | 1→1 | neither consumed nor used | stable joins +1; same-suit mass +2 | retained as enriched `ECONOMIC_PROJECT / run_construction`; TT new/admitted |
| 4 | `CAMPAIGN_DEPENDENCY_CLOSURE` / `dependency_closure` | `(4,5,1)` | 1 | `bf5a42ecfefd5ff4` | 1→0 | empty used as destination and consumed; not restored | mixed boundaries −1; rehandling debt −1; three dependencies closed; one overlay cleared; campaign-specific evidence | final; TT suppressed g=9 versus existing g=7; not retained |
| 5 | `RAW_DEAL` / `deal_timing` | `deal` | 1 | `3bb9efffbe83a745` | 1→0 | empty filled/consumed; not restored | none; mixed boundaries, rehandling, and mobility worsen | final; TT new/admitted; retained |

There were no obligation-gate losses. Exact-state deduplication merged the two
same-suit/economic representations into enriched `ECONOMIC_PROJECT /
run_construction` representatives. The only post-portfolio loss was raw 4 at TT.

## 6. Workspace-exploitation classification

Raw candidates classified as:

* `PRODUCTIVE_EMPTY_USE`: 1;
* `EMPTY_PRESERVED_PROGRESS`: 4, including two duplicate representations;
* `EMPTY_CONSUMED_NO_MEASURED_PROGRESS`: 1;
* `EMPTY_UNUSED`: 0.

Retained candidates classified as:

* `PRODUCTIVE_EMPTY_USE`: 0;
* `EMPTY_PRESERVED_PROGRESS`: 2;
* `EMPTY_CONSUMED_NO_MEASURED_PROGRESS`: 1;
* `EMPTY_UNUSED`: 0.

Raw 4 is the sole genuine empty-exploitation candidate. In broad resource-operator
terms it performs `invest workspace` plus `campaign-edge realisation`: it moves
into the empty and production reports dependency/overlay progress. However, it
exactly reverses the empty-creating relocation and returns to the earlier R3
structural state at higher cost. The unchanged exact TT therefore suppresses it.
The evidence may represent context that the state-only TT cannot carry, or it may
be a contextually decorated undo; this experiment establishes the gate but does
not decide between those interpretations.

The two retained same-suit constructions preserve the empty but do not use it as
a destination. The retained raw Deal consumes it without measured improvement.
No selected-parent successor exposed source excavation, receiver creation/use,
temporary rework, or workspace recovery. Ordinary production therefore exposes
a nominal workspace-invest/campaign operator, but does not retain coordinated
empty use or recovery at this parent.

## 7. Downstream lifecycle

No retained `PRODUCTIVE_EMPTY_USE` child existed, so no such child could receive
ordinary service, widen, recover an empty, expose a card, progress stock, or reach
a foundation.

Of the two retained `EMPTY_PRESERVED_PROGRESS` children:

* node 27 / `d7d7c36cdf81718e` was naturally popped and expanded at CLEAN; its
  credit-1 widening node 33 was queued but not popped/expanded. It generated and
  retained one further empty state and one lower-stock successor, but no
  face-down reduction or foundation successor.
* node 28 / `3166ccb1c4ee0379` remained live and was not popped or expanded.

Across the complete treatment, two actual-empty states were popped/expanded: the
one specially serviced parent and one naturally serviced descendant. The arm
generated 87 empty events and retained 52, versus 11/3 in R3-only. It also
generated 450 R3 events, retained 112, popped 60, and expanded 56. This large
trajectory change shows that one empty expansion can unlock much wider ordinary
search circulation even though its direct productive-empty edge was suppressed.

No selected-parent candidate reduced face-down cards or restored an empty during
its macro. Treatment minimum face-down remained 38, stock advanced normally, and
no foundation was reached.

## 8. Arm comparison

Counts below are event counts.

| Metric | A: control | B: R3 only | C: R3 then empty |
|---|---:|---:|---:|
| Stop reason | expansion limit | expansion limit | expansion limit |
| Strategic expansions | 400 | 400 | 400 |
| Credit 0/1/2/3/4 expansions | 90/80/78/77/75 | 89/79/78/77/77 | 91/79/78/76/76 |
| Tactical nodes | 53,085 | 62,630 | 83,298 |
| Elapsed seconds | 584.016 | 583.336 | 575.005 |
| Successors generated / retained | 1,903 / 507 | 1,794 / 484 | 1,870 / 532 |
| TT new / improved / suppressed | 504/4/1,396 | 478/7/1,310 | 526/7/1,338 |
| Minimum face-down | 36 | 38 | 38 |
| R2 generated / retained / popped / expanded | 1,891/498/91/87 | 1,771/472/90/86 | 1,771/471/90/86 |
| R3 generated / retained / popped / expanded | 22/10/0/0 | 31/23/4/4 | 450/112/60/56 |
| Empty generated / retained / popped / expanded | 0/0/0/0 | 11/3/0/0 | 87/52/2/2 |
| Retained productive empty-use successors | 0 | 0 | 0 |
| Maximum foundations | 0 | 0 | 0 |
| Final frontier credit 0/1/2/3/4 | 241/10/2/1/2 | 244/10/1/1/0 | 241/12/1/2/0 |
| Replay failures / cost inconsistencies / proof prunes | 0/0/0 | 0/0/0 | 0/0/0 |

Stock-row distributions (`rows: count`) were:

| Stage | A: control | B: R3 only | C: R3 then empty |
|---|---|---|---|
| Generated | 5:2, 4:15, 3:1,419, 2:467 | 5:2, 4:19, 3:1,275, 2:498 | 5:2, 4:21, 3:1,351, 2:496 |
| Retained | 5:2, 4:13, 3:374, 2:118 | 5:2, 4:17, 3:344, 2:121 | 5:2, 4:17, 3:389, 2:124 |
| Expanded | 5:1, 4:5, 3:394 | 5:1, 4:6, 3:393 | 5:1, 4:7, 3:392 |

## 9. What this proves—and does not prove

For this exact commit, deal, seed, and budget, ordinary production does generate
a replay-valid candidate that uses the selected natural empty and carries its own
existing campaign/dependency progress evidence. Lack of family coverage,
deduplication, portfolio truncation, obligation handling, replay, or proof pruning
does not remove it. The exact demonstrated gate is TT dominance: the endpoint is
the earlier R3 state at g=9 while TT already holds it at g=7.

The experiment does not prove that bypassing TT is correct, that the contextual
progress survives a return to an exact structural state, that the edge is more
than a decorated undo, or that resource-planner integration is now justified. It
also does not show direct face-down or foundation progress from empty use.

It separately shows that servicing an empty can alter ordinary circulation:
empty-preserving same-suit progress was retained, one such child received natural
service, and empty/R3 coverage expanded sharply. That is not equivalent to
retained productive workspace exploitation, so the primary verdict remains the
suppression classification.

The known cheaper-arrival reopening, TT-after-eviction, and duplicate-protection
defects remained unchanged. The observed raw-4 suppression is ordinary
higher-cost exact-state dominance, not evidence by itself that those known bugs
fired.

## 10. One next bounded experiment

A/B exactly one context-aware TT admission override for a naturally generated
`PRODUCTIVE_EMPTY_USE` successor only when it carries demonstrably new existing
dependency/structural-investment evidence relative to the cheaper exact-state
representative, then give it ordinary queue treatment to test whether that context
produces non-duplicate structural progress; add no priority bonus and do not
invoke the resource planner.

## Tests run

* Focused natural empty-service tests: 9 passed.
* Previous comparator/state-local/R3/controller/natural-resource/resource-integrity
  regression selection: 217 passed.
* Total distinct tests: 226 passed.

Machine-readable results:
`docs/research/one_shot_natural_empty_service_v0_1.json`.
