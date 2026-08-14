# POC — Committed excavation project search

**Branch:** `dev/committed-excavation-poc`  
**Start:** `dev/excavation-dependency-closure` @ `cdd094a`  
**Not wired into plan_search.** No deal.

## Verdict: **EXCEPTIONAL** (cost 5 < 19)

From the true opening, a committed project empties **column 6** in **5**
corrected MobilityWare moves. Column 10 also found at cost **6**.

Human first empty is column 10 at cost 19. The solver chose a *different,
cheaper* target. That column was selected generically (emptyable, est. cost
in the cheapest band), not as a constant.

## Portfolio (reported before canonical comparison)

| col | est | dest-prep |
|---:|---:|---|
| 7 | 6 | 10 |
| 8 | 6 | 6 |
| 10 | 6 | 3 |
| 1 | 8 | 6, 10 |
| 6 | 9 | 3, 10 |

## Best route (col 6, cost 5)

`6→8 k=1`, `6→3 k=1`, `6→3 k=1`, `6→2 k=1`, `6→5 k=1`

All five are target peels. Live dests: 5s→6s, 3s→4s, 2s→3s, Qc→Kd, Qs→Kc.

Follow-on: same-suit consolidate at cost 1.

Generic CREATE_WORKSPACE also found cost 5 (831 nodes / 0.6s vs 402 / 0.3s).
Commitment helped nodes, not the cost.

Cols 7, 8, 1: RESOURCE_LIMIT through bound 25 (not impossibility).
