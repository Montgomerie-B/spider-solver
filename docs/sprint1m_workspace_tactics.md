# Sprint 1M — Tactical Workspace Breakthrough

**Branch:** `dev/sprint1m-workspace-tactics`  
**Baseline:** Sprint 1L @ `9881504`

## Technique

`workspace_tactics.py` — dedicated CREATE_WORKSPACE backend.

- Target: `empty_count` increases by ≥ 1
- 0-1 BFS on corrected MW cost
- **Quotient TT**: free open piles + empties are interchangeable; permutations are one class
- **Ordering**: prefer emptying short/open columns onto non-empty same-suit/rank+1 dests; deprioritize 0-cost relocates (1F prefers them and explodes)
- 0-cost edges that do not raise empty_count are skipped
- Miss = not-found-within-bound or resource_limit. Not impossibility.

Legacy 1F `_search_exact` is unchanged and used as the comparison backend.

## Success gate

**PASS via C** (productive follow-on). A and B did not fire on important 1L machine states.

Post-D2 least-fd (g=22, fd=30): both backends find workspace at **cost 4**. Follow-on: expose and consolidate both succeed. Independent top foundation stays S#1; removal readiness 20→24, build 42→41.

Pre-D1 / post-D1 / post-D3 / post-D2-best-ss: **both miss** at ceilings 3–12.

Human checkpoints: both find cost **2**; improved uses fewer nodes (pre-D1 45 vs 99).

## Recommendation

**Integrate the improved backend into the epoch planner and raise workspace time/node caps** (1L’s 0.25s / ~350 nodes is at the edge of the cost-4 find). Do not claim the hard fd≈28 machine positions are solved — they still miss at cost 12.
