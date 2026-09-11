# Simple Progressive Search v0.26 — Perfect-Information Deal-1 Preview

## 1. Verdict

`DEAL1_PREPARATION_BEATS_DEAL_NOW` — preparation before Deal 1 found hard progress that Deal-now did not

DEAL TIMING MATTERS. Perfect-information receiving-position search beat Deal-now.

- Branch: `agent/simple-progressive-deal1-preview-v0-26`
- Base SHA: `f66d3f861c3e27b368b26872bd504e057cbcf05a`
- No Deal heuristic. No Deal 2. No fd13 descent.

## 2. D1 root

- path=38 fd=14 stock_rows=5 foundations=0 empties=[] legal_tableau=9 deal_legal=True
- ordered=`53504b310100003204053a2c36083504230231050415191b11282d0c2b1a01073b27061534233231000314131200012d00020d0c040718360a2a2807060504030200011200083d3c3b3a3938372600021716131a2233193717013325290b1c22343c3d381b09320a2c1d1839030525140d0116072121112a1c2b0b29241d242609270835`
- incoming row=[['s', 11], ['d', 9], ['d', 4], ['h', 13], ['d', 4], ['d', 6], ['s', 9], ['d', 7], ['s', 8], ['c', 5]]
- control Deal-1 child match: True

## 3. Phase 1 — pre-Deal candidates

- unique=60 expanded=60 generated=492 dups=433
- completed_expanded=4 generated_depth=4 stop=frontier empty
- pre-Deal progress classes=0 min_fd=14
- elapsed_s=0.11038800000096671 rss_mb=21.76171875

## 4. Phase 2 — virtual Deal

- candidates_dealt=60 distinct_children=60
- control_post_digest match=True root_unmutated=True
- join totals={'same_suit_joins': 0, 'mixed_suit_joins': 100, 'onto_empty': 0, 'pre_empty_ge1': 0, 'n': 60}

## 5. Phase 3 — post-Deal preview (no Deal 2)

- unique=750000 expanded=276408 generated=2328102 dups=1578153
- completed_expanded=6 generated_depth=8 stop=unique limit
- Deal-now progress=0 prepared progress=8 distinct hard-progress classes=8
- best preparation depth=1 best post-Deal depth=8
- reveal-target distribution: `c10,d12,c6,s8` × 8 (column-1 stack, not the later c11 singleton)
- elapsed_s=400.6857862000179 rss_mb=389.85546875
- unique-limit bound while generating post-Deal depth 8; last fully expanded layer=6. Prepared fd13 still appeared among generated depth-8 children. Deal-now had zero hits in the expanded set.

| Timing | Hard progress | Min pre-Deal depth | Min post-Deal depth | Classes |
|---|---|---:|---:|---:|
| No Deal | False | n/a | n/a | 0 |
| Deal now | False | 0 | None | 0 |
| Prepare then Deal | True | 1 | 8 | 8 |

## 6. Exactly one next recommendation

DEAL TIMING MATTERS: perfect-information receiving-position search found a better Deal-1 moment than the historical immediate Deal. Next: treat Deal 1 as a previewed commitment from prepared candidates. Do not inspect Deal 2 yet.

## Integrity

Verdict DEAL1_PREPARATION_BEATS_DEAL_NOW. control_ok=True.

Base SHA `f66d3f861c3e27b368b26872bd504e057cbcf05a`. Deal `deals/4925153.txt`.
No Deal heuristic. No Deal 2. No production change.

