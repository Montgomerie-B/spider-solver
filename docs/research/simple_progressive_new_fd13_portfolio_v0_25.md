# Simple Progressive Search v0.25 — New FD13 Boundary-Portfolio Conversion

## 1. Verdict

`NEW_FD13_PORTFOLIO_NO_SHORT_FD12` — no fd12 boundary exit through the depth-12 envelope

No short conversion in this envelope. The 16 states are not proven dead.

- Branch: `agent/simple-progressive-new-fd13-portfolio-v0-25`
- Base SHA: `9936014b24b8b7523b216f162cb07c27504c954f`
- Previous verdict: `FD14_BOUNDARY_FINDS_NEW_FD13_EXIT`
- No new heuristic. No fresh fd14 search. No untouched-root expansion.

## 2. Source audit

- sources=16 distinct_sym=16 path_range=123-124 MW_range=123-124
- current_fd13_path=101 current_to_fd12=+9

| Source set | fd13 total path | Local search | FD12 exits | New FD12 regions | Reaches fd10 |
|---|---:|---:|---:|---:|---:|
| Historical/current | 101 | known +9 | known | 0 established | no established |
| v0.24 new portfolio | 123-124 | <=12 BFS | 0 | 0 | no |

## 3. Known-dead cache

{
  "set_a": 41472,
  "set_b": 89856,
  "union": 131328,
  "overlap": 0,
  "disjoint": true,
  "a_stop": "frontier empty",
  "b_stop": "frontier empty",
  "a_min_fd": 11,
  "a_max_foundations": 0,
  "a_exhausted": true
}

## 4. Phase 2

- unique=366733 expanded=258101 generated=2104172 dups=1737455 cross_origin=488422
- completed_expanded=11 generated_depth=12 stop=max depth exhausted=False
- fd12 edges=0 classes=0 known_dead=0 new=0
- current_fd13_hits=0 empty1_hits=0
- elapsed_s=374.6219133999839 rss_mb=257.44921875

## 5. Phase 3

Skipped: no NEW_FD12_REGION

## 6. Exactly one next recommendation

No short conversion in this envelope; the 16 states are not proven dead. Next: either a deeper exact fd13 probe of this portfolio or more fd14 exits. Do not add a heuristic.

## Integrity

Verdict NEW_FD13_PORTFOLIO_NO_SHORT_FD12. fd10=False foundation=False.

Base SHA `9936014b24b8b7523b216f162cb07c27504c954f`. Deal `deals/4925153.txt`.
No new heuristic. No fresh fd14 search. No production change.

