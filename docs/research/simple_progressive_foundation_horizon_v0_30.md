# Simple Progressive Search v0.30 — Foundation Horizon and First-Foundation Audit

## 1. Verdict

`SPADE_FIRST_FOUNDATION_REACHED` — first Spade foundation by ['MIDDLE']

MIDDLE reached a replay-valid first Spade foundation after Deal 2 from the fd12 frontier. That operational result supersedes v0.29's fd10 ranking, where LATE was cheapest. EARLY used its full 900s without a foundation. LATE did not receive a full 900s group envelope: the global 1800s cap left only the leftover time after EARLY and MIDDLE, so LATE's non-result is bounded, not a proof of unreachability.

- Branch: `agent/foundation-horizon-first-foundation-v0-30`
- Base SHA: `f55c5ccf38cebf129bb37e47b3c82e6d7bf31dfc`
- Objective: first foundation, not fd reduction.
- No Deal 3. No suit heuristic. Ordered pack_state.

## 2. Exact foundation material horizons

- Final Deal row (SD5): 3H,10H,2D,3C,9H,7C,7H,AS,3C,5D
- SD5 matches expected: True
- Max foundations by horizon: [0, 0, 2, 2, 3, 8]
- Impossible before SD5: ['second Spades', 'second Hearts', 'second Diamonds', 'first Clubs', 'second Clubs']
- Material audit matches expected: True

- Spades: first SD2 (missing before: ['A']; supplied: [{'card': 'AS', 'column_1': 2, 'rank': 1, 'suit': 's'}]); second SD5 (missing before: ['A'])
- Hearts: first SD2 (missing before: ['Q']; supplied: [{'card': 'QH', 'column_1': 9, 'rank': 12, 'suit': 'h'}]); second SD5 (missing before: ['3', '7', '9', '10'])
- Diamonds: first SD4 (missing before: ['2']; supplied: [{'card': '2D', 'column_1': 4, 'rank': 2, 'suit': 'd'}]); second SD5 (missing before: ['2', '5'])
- Clubs: first SD5 (missing before: ['3']; supplied: [{'card': '3C', 'column_1': 4, 'rank': 3, 'suit': 'c'}, {'card': '3C', 'column_1': 9, 'rank': 3, 'suit': 'c'}]); second SD5 (missing before: ['3', '7'])

Material horizon is not operational horizon.

## 3. Source audits

- EARLY: listed=8 distinct=8 replay_ok=True path=48-49 fd=13 virtual_children=8 unmutated=True post_stock=3
- MIDDLE: listed=16 distinct=16 replay_ok=True path=49-50 fd=12 virtual_children=16 unmutated=True post_stock=3
- LATE: listed=16 distinct=16 replay_ok=True path=51-52 fd=11 virtual_children=16 unmutated=True post_stock=3

- Deal-2 row: KS,AS,6H,7S,AD,AD,AH,10D,QH,JD

## 4. First-foundation search

- EARLY: unique=1362375 expanded=762836 generated=3861513 dups=2499146 stop=time limit expanded_depth=13 generated_depth=15 min_fd=9 elapsed_s=900.0163265000156 rss_mb=651.85546875
  foundation=False suits=[] classes=0 local=None path=None MW=None stock=None fd_at_removal=None origins=[] replay=True fixture=None
- MIDDLE: unique=850386 expanded=409327 generated=2423719 dups=1573341 stop=progress layer complete expanded_depth=11 generated_depth=12 min_fd=8 elapsed_s=525.6555949999893 rss_mb=751.0390625
  foundation=True suits=['s'] classes=4 local=12 path=62 MW=62 stock=3 fd_at_removal=9 origins=[1, 9] replay=True fixture=solutions/4925153_simple_v0_30_middle_first_foundation.moves.txt
- LATE: unique=531480 expanded=291549 generated=1788452 dups=1256988 stop=time limit expanded_depth=12 generated_depth=14 min_fd=8 elapsed_s=373.9479299999948 rss_mb=751.54296875
  foundation=False suits=[] classes=0 local=None path=None MW=None stock=None fd_at_removal=None origins=[] replay=True fixture=None

## 5. Comparison

| Deal-2 timing | Pre-Deal fd | First foundation | Suit | Full path/MW |
|---|---:|---|---|---:|
| EARLY | 13 | False |  |  |
| MIDDLE | 12 | True | Spades | 62/62 |
| LATE | 11 | False |  |  |

Envelope note: EARLY used the full 900s group cap. MIDDLE stopped on the first foundation layer. LATE received only the global-1800s leftover and is not a full 900s non-result.

## 6. Exactly one next recommendation

MIDDLE reaches the first Spades foundation most cheaply (path/MW 62/62, local depth 12). That operational target supersedes fd count. Continue exact search from this first-foundation portfolio. Do not add a suit heuristic yet and do not take Deal 3.

## Integrity

Verdict SPADE_FIRST_FOUNDATION_REACHED. elapsed_s=1800.1625272999809 rss_mb=751.54296875.

Base SHA `f55c5ccf38cebf129bb37e47b3c82e6d7bf31dfc`. Deal `deals/4925153.txt`.
No Deal 3. No fd-target. No production change.

