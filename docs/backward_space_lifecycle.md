# Backward strategic dependency / space-lifecycle (one-off diagnostic)

**Branch:** `dev/backward-space-lifecycle`  
**Not a search layer.** `plan_search` is unchanged.

## Verdict: **B — PARTIAL SIGNAL**

Space is working capital, not a prize. That part of the model has lead time.
Which *column* to excavate at the opening is still too flat to stop the
machine's cheap-spread ACCESS habit.

## What the model is

Generic helpers in `src/spider/planner/backward_strategy.py`:

| Piece | Role |
|---|---|
| `locate_all_cards` | HARD locations; duplicates interchangeable |
| `analyze_buried_cards` | urgency `useful_now / before_next_deal / later / low_value` |
| `analyze_excavation_projects` | columns ranked by unlock / difficulty, not raw fd |
| `analyze_space_liquidity` | spaces_now, create cost, regain-if-consumed, option uses |
| `analyze_stock_backward` | exact next row; **fill → deal → recreate** is allowed |
| `rank_projects_meet_in_middle` | forward feasibility × backward need |

## Canonical checks (4925153, validation tape only)

| Checkpoint | What the analyser saw | What the human did |
|---|---|---|
| Opening | top-3 cols 3/4/6 (tied with 7/8/10); 22 cards `useful_now` | starts 3,3,8,6… |
| First space (g=19, empty col 10) | consume plausible, regain 1 | uses it 3 actions later |
| First use (g=22, e=0, 3 open nk) | one-move create cost 1 | immediately builds another space |
| Pre-D1 | e=0, cheapest ws **2**, 6 open / 5 nk | deals with e=0 |
| Pre-D2 | e=0, one-move create, 8 open / 6 nk | deals with e=0 |
| Pre-D5 | only buried card **Ac col 4**; deal-now, post ws **2** | works col 4; deals with e=0 |
| Post-D5 | cheapest ws **2** | human empty in **2** moves |

All five deals have pre-deal empty = 0. The model does **not** recommend
creating a space just to carry it through a deal. If a space exists and
incoming would occupy it, fill-then-recreate is an explicit option.

## Opening vs machine spread

Meet-in-the-middle demotes *blocked* columns (5, 9: no dest) but leaves
six startable columns tied at 0.66. That is not enough to stop ACCESS
from spreading. `useful_now` is still too wide at the opening.

## Runtime

1.2s for eight checkpoints (tight workspace probes only).
