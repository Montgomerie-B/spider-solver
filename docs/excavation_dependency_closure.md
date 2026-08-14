# Excavation dependency closure (one-off diagnostic)

**Branch:** `dev/excavation-dependency-closure`  
**Start:** `dev/backward-space-lifecycle` @ `f2ca9a8`  
**Not a search layer.** `plan_search` unchanged.

## Verdict: **PARTIAL**

The opening six-way tie is broken for generic reasons (King/space
projects drop; cheap one-prep emptyable columns rise). The canonical
first-empty column is **rank 4**, not a small top set. Stop; do not
tweak weights.

## Model

`src/spider/planner/excavation_closure.py`

- HARD hop sequence per column (current run, then each hidden card)
- Destinations are OR-nodes (any rank+1 copy; Kings need empty)
- Buried dests recurse, bounded (`MAX_RECURSE=5`) and memoised
- Shared dest-prep is unioned: `expose(col, k)` covers `expose(col, j<k)`
- HEURISTIC total = target peels + unique helper peels + space/stock extras

## Opening (validation after ranking)

Previous tied set 3/4/6/7/8/10. New order: **7, 8, 1, 10, 6, 9, 3, 5, 4, 2**.

| col | cost~ | emptyable | why |
|---:|---:|---|---|
| 7 | 6 | yes | 3/5 hops live; one peel of col 10 for Jc |
| 8 | 6 | yes | 3/5 hops live; one peel of col 6 for 3s |
| 1 | 8 | yes | high unlock; two helper peels |
| **10** | **6** | **yes** | 4/5 hops live; one peel of col 3 for Qs |
| 4, 2, 5 | 16–21 | no | King needs empty |

First-empty = col 10, rank 4. Same causal cost as 7/8; slightly less
backward card value.

## Runtime

2.8s including a tiny ACCESS snapshot. Focused tests: 7 passed.
