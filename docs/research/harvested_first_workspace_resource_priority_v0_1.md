# Harvested first-workspace resource and priority v0.1

**Status:** complete. Diagnostic only. No production or planner changes.

**Start SHA:** `c396d96160350bf336422f3652a30eb02f40c041`

**Branch:** `agent/harvested-first-workspace-resource-priority-v0-1`

**Decision: E. SECONDARY TARGETS ONLY**

The engine can create the first empty from the natural R3 state by
`Qs: col5 → col1`. Unchanged `CREATE_WORKSPACE` **rejects** that move for the
production-primary P target (`c 12-11`) as `EXCLUDED_SINGLETON_CAMPAIGN_HIGH`
(singleton rank equals campaign high rank, suit-blind).

The same move is **accepted** for the next scheduler-native clubs edge
(`c 11-10`). There the unchanged planner produces

`CREATE → INVEST → RECOVER`

(`[5,1,1], [9,5,1], [5,6,1]`), a prepaid nontrivial success whose terminal
is **counterfactually novel** versus ordinary `generate_strategic_successors`
on that node (which only emits a 2-action dependency closure and Deal).
First CREATE action `(5,1,1)` is absent from ordinary successors.

All four R2 parents remained unexpanded (one trimmed ~exp 210; three still
live at 400). Priority is a second bottleneck, but the P vs S split is the
resource-capability finding.

Recommended next step (not taken):

> Bounded scheduler target-selection experiment.

## Reconstruction

The 400-expansion continuous audit was rerun once with R2/R3 capsule capture.
Headline match: 400 CLEAN expansions; R2 4/4 generated/retained; R3 1/1;
R4 0; first child `1c3d3ec77bf164ad`; expansion 116; path length 5.

First R2 also reconstructs from the stored path
`(5,7,1), (2,7,1), (5,7,1), (5,7,1), (5,4,1)`.

## R2 corpus

| digest | exp | g | fd | revealed | legal first-empty | R3 |
| --- | --- | --- | --- | --- | --- | --- |
| `1c3d3ec77bf164ad` | 116 | 5 | 39 | 1 | **1** `(5,1,1)` Qs | yes |
| `edb1f739a3100867` | 128 | 6 | 38 | 1 | 0 | no |
| `de13114dc57870d7` | 131 | 7 | 37 | 1 | 0 | no |
| `f729fad6e19cb5b5` | 134 | 8 | 37 | 1 | 0 | no |

R3 legal first-empty: source 5 → dest 1, k=1, packet Qs, cost 1, empties 1,
joins 0/0, terminal `19e9e5d1326854ed`. Engine replay OK.

## CREATE coverage

**P:** 1 legal move, **0 accepted**. Reject: `EXCLUDED_SINGLETON_CAMPAIGN_HIGH`
(P is clubs queen-jack; packet is a singleton queen of spades).

**S:** 17 legal-move×target pairs, **15 accepted**, 2 rejected
`OCCUPIES_UNIQUE_RECEIVER` (diamond king-queen targets).

## Resource results

| | P (4) | S (65) |
| --- | --- | --- |
| REALISED | 0 | 0 |
| PREPAID | 1 | 1 |
| NO_BOUNDED_PLAN | 3 | 62 |
| RESOURCE_DEADLOCK | 0 | 2 |
| FIRST_EMPTY_CREATED | 0 | 1 |
| WORKSPACE_INVESTED | 0 | 1 |
| WORKSPACE_RECOVERED | 0 | 1 |
| NONTRIVIAL_RESOURCE_SUCCESS | 1 | 1 |

P nontrivial is `TEMPORARY_REWORK` `[2,7,2]` on a non-R3 state,
`CF_EXACT_DUPLICATE` of ordinary `SAME_SUIT_CONSTRUCTION`. Not first-empty.

S nontrivial is Pattern B on the R3 state, target `c 11-10`.

## Workspace trace (S, R3, `c 11-10`)

`CREATE [5,1,1]` empties=1, obligations 0  
`INVEST [9,5,1]` empties=0, workspace live  
`RECOVER [5,6,1]` empties=1, workspace cleared  

Result `PREPAID_DEPENDENCY`. Final empty remains. Unresolved 0. Replay OK.

## Counterfactual ordinary successors

R3 node would generate only:

* `CAMPAIGN_DEPENDENCY_CLOSURE` `[7,9,5]+[9,3,5]` cost 2
* `RAW_DEAL` cost 1

CREATE `(5,1,1)` is not in that set.

Overlap: P duplicate 1; S `CF_NOVEL_RESOURCE_TERMINAL` 1.

## First-action overlap

S CREATE first action `[5,1,1]`: **absent** from ordinary successors
(new primitive coverage, then sequenced).  
P rework first action `[2,7,2]`: already a production successor.

## Frontier lifespan

| digest | insert rank (first seen) | best | popped | trimmed | live@200 | live@400 | lifetime exp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `1c3d3e…` R3 | 149 | 149 | no | yes ~210 | yes | no | 95 |
| `edb1f7…` | 32 | **11** | no | no | yes | yes | 273 |
| `de1311…` | 169 | 169 | no | no | yes | yes | 270 |
| `f729fa…` | 172 | 172 | no | no | yes | yes | 267 |

None popped. The R3 node is trimmed. `edb1f7` reaches rank 11 and still
never expands: new CLEAN children keep occupying ranks 1–10.

Matched insertion neighbourhood was not snapshotted at the exact push
(observer saw the node on the next expansion). Dominant measured components
from the four-state comparison: **g / later-arriving CLEAN descendants**
outrank a fully-revealed column; scheduler-effect of ordinary closures/deals
beats the R3 parent.

## Why E

- Not A: P CREATE rejects the only legal first-empty.
- Not B: S resource terminal is counterfactually novel, not an ordinary duplicate.
- Not C: CREATE accepts the move for the next clubs edge.
- Not D: post-CREATE INVEST/RECOVER succeeds on that S target.
- **E:** production-primary P cannot open the empty; a scheduler-native later
  edge can, and the parent is still unexpanded.

## Pytest

`1872 passed, 37 xfailed in 1281.97s`

0 unexpected failures. Node-78 was not modified.
