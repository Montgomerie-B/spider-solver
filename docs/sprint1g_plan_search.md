# Sprint 1G — Limited Plan-Level Search (Opening → Deal 1)

**Branch:** `dev/sprint1g-plan-search`  
**Baseline:** Sprint 1F @ `549dea4`

## Scope

Search over **strategic objectives**, not raw moves, from the opening to the first stock deal only. Diagnostic, not a whole-game solver.

## API

`src/spider/planner/plan_search_v2.py`

- `PlanNode`, `QualityVector`, `PlanSearchResult`
- `search_opening_to_first_deal(...)`
- `canonical_opening_to_deal1(...)` — diagnostic human prefix only

## Quality

Transparent vector (Pareto + labelled heuristic beam key):

- g, face_down, empty_count, longest_same_suit, same-suit mass
- foundation build readiness
- pre-deal same-suit landings / outs / non-connecting

No proof pruning from quality. Admissible h only if incumbent/target supplied.

## Expansion

Portfolio (1E) → cheap 1F realization → branch on FOUND.  
Always retain DEAL_NOW. Deep EXPOSE prefixes skipped (`required_reveals > 2`).

## Lower bound

Uses Sprint 1E `h_admissible`, never `face_down + deals`.
