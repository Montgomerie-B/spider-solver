# Simple Progressive Search v0.29 — Deal-2 Timing Preview

## 1. Verdict

`DEAL2_TIMING_REACHES_FD10` — fd10 reached by ['MIDDLE', 'LATE']

At least one Deal-2 timing reaches replay-valid fd10 inside the depth-8 post-Deal envelope. This does not license a Deal-readiness heuristic.

- Branch: `agent/simple-progressive-deal2-timing-preview-v0-29`
- Base SHA: `3ba82cdd8c33c6d7e6253a923a78796efa9d6a28`
- Previous verdict: `POST_DEAL1_FD12_REACHES_FD11`
- No Deal 3. No extra pre-Deal preparation. No heuristic. Ordered pack_state.

## 2. Source audits

- EARLY: listed=8 distinct=8 replay_ok=True path=48-49 MW=48-49 fd=13 stock=4 deals=1
- MIDDLE: listed=16 distinct=16 replay_ok=True path=49-50 MW=49-50 fd=12 stock=4 deals=1
- LATE: listed=16 distinct=16 replay_ok=True path=51-52 MW=51-52 fd=11 stock=4 deals=1

## 3. Deal-2 incoming row

- s13,s1,h6,s7,d1,d1,h1,d10,h12,d11
- cards=[['s', 13], ['s', 1], ['h', 6], ['s', 7], ['d', 1], ['d', 1], ['h', 1], ['d', 10], ['h', 12], ['d', 11]]
- Same pending row for every source in all three groups.

## 4. Virtual Deal 2

- EARLY: sources=8 distinct_children=8 unmutated=True post_stock=3
- MIDDLE: sources=16 distinct_children=16 unmutated=True post_stock=3
- LATE: sources=16 distinct_children=16 unmutated=True post_stock=3

## 5. Post-Deal search

- EARLY: unique=17597 expanded=8398 generated=42278 dups=24689 cross_origin=501
  expanded_depth=7 generated_depth=8 stop=max depth min_fd=11 fnd=0 elapsed_s=9.788736600021366 rss_mb=30.37890625
  fd10=False fd10_classes=0 min_local=None min_path=None min_cost=None origins=[] first_fd12=6 first_fd11=8 first_fd10=None
- MIDDLE: unique=18772 expanded=8415 generated=42237 dups=23473 cross_origin=846
  expanded_depth=6 generated_depth=7 stop=progress layer complete min_fd=10 fnd=0 elapsed_s=9.71861120001995 rss_mb=36.5546875
  fd10=True fd10_classes=8 min_local=7 min_path=57 min_cost=57 origins=[0, 1, 2, 3, 8, 9, 10, 11] first_fd12=0 first_fd11=6 first_fd10=7
- LATE: unique=1666 expanded=700 generated=2930 dups=1264 cross_origin=0
  expanded_depth=3 generated_depth=4 stop=progress layer complete min_fd=10 fnd=0 elapsed_s=0.7188979999918956 rss_mb=37.60546875
  fd10=True fd10_classes=16 min_local=4 min_path=56 min_cost=56 origins=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] first_fd12=0 first_fd11=0 first_fd10=4

## 6. Common comparison

| Deal-2 timing | Pre-Deal fd | Source path range | Min post-Deal fd | Reaches fd10 | Best full path/MW to fd10 |
|---|---:|---:|---:|---:|---:|
| EARLY | 13 | 48-49 | 11 | False |  |
| MIDDLE | 12 | 49-50 | 10 | True | 57/57 |
| LATE | 11 | 51-52 | 10 | True | 56/56 |

## 7. Reception telemetry summary

{
  "EARLY": {
    "n": 8,
    "same_suit_joins_total": 0,
    "mixed_suit_joins_total": 0,
    "onto_empty_total": 0,
    "same_suit_joins_mean": 0.0,
    "mixed_suit_joins_mean": 0.0,
    "onto_empty_mean": 0.0,
    "pre_legal_tableau_mean": 9.0,
    "post_legal_tableau_mean": 4.0,
    "pre_longest_run_mean": 3.0,
    "post_longest_run_mean": 1.0
  },
  "MIDDLE": {
    "n": 16,
    "same_suit_joins_total": 0,
    "mixed_suit_joins_total": 0,
    "onto_empty_total": 0,
    "same_suit_joins_mean": 0.0,
    "mixed_suit_joins_mean": 0.0,
    "onto_empty_mean": 0.0,
    "pre_legal_tableau_mean": 9.0,
    "post_legal_tableau_mean": 4.0,
    "pre_longest_run_mean": 3.0,
    "post_longest_run_mean": 1.0
  },
  "LATE": {
    "n": 16,
    "same_suit_joins_total": 0,
    "mixed_suit_joins_total": 8,
    "onto_empty_total": 0,
    "same_suit_joins_mean": 0.0,
    "mixed_suit_joins_mean": 0.5,
    "onto_empty_mean": 0.0,
    "pre_legal_tableau_mean": 7.0,
    "post_legal_tableau_mean": 4.0,
    "pre_longest_run_mean": 3.0,
    "post_longest_run_mean": 1.0
  }
}

## 8. Cross-group exact convergence

{
  "post_deal_overlap_EARLY_MIDDLE": 0,
  "post_deal_overlap_EARLY_LATE": 0,
  "post_deal_overlap_MIDDLE_LATE": 0,
  "fd10_overlap": {
    "EARLY&MIDDLE": 0,
    "EARLY&LATE": 0,
    "MIDDLE&LATE": 0
  },
  "independent_seen_sets": true
}

## 9. Exactly one next recommendation

Deal 2 at fd11 reaches fd10 from every LATE source at path/MW 56 (local depth 4). Deal 2 at fd12 also reaches fd10, but only from 8 of 16 sources at path/MW 57 (local depth 7). Deal 2 at fd13 does not reach fd10 in the depth-8 envelope. Continue exact post-Deal search from the cheaper LATE fd10 portfolio. Do not add a heuristic and do not take Deal 3.

## Integrity

Verdict DEAL2_TIMING_REACHES_FD10. foundation=False.
elapsed_s=20.403303099999903 rss_mb=37.60546875.

Base SHA `3ba82cdd8c33c6d7e6253a923a78796efa9d6a28`. Deal `deals/4925153.txt`.
No Deal 3. No heuristic. No production change.

