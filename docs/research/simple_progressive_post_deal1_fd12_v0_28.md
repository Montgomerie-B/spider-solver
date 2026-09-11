# Simple Progressive Search v0.28 — Post-Deal-1 FD12-to-FD11 Boundary Audit

## 1. Verdict

`POST_DEAL1_FD12_REACHES_FD11` — replay-valid fd11 is reached before Deal 2

The productive Deal-1 cascade still has another tableau reveal before Deal 2. This is evidence of a genuine hard-progress cascade after the timed Deal 1. It does not imply Deal 2 must wait for every remaining reveal.

- Branch: `agent/simple-progressive-post-deal1-fd12-v0-28`
- Base SHA: `d1875b70cb775760c0addf41284ac5eb62ced13d`
- Previous verdict: `POST_DEAL1_WORK_REACHES_FD12`
- No Deal 2. No heuristic. Ordered pack_state while stock remains.

## 2. Source audit

- fd12 sources listed=16 distinct ordered=16 replay_ok=True
- path_range=49-50 MW_range=49-50
- stock_rows=4 fd=12 foundations=0 exactly_one_Deal=True
- identity=`pack_state` (no post-stock column symmetry)

## 3. Search

- unique=612 expanded=120 generated=1124 dups=512 cross_origin=280
- unique_sources=16 max_depth=2 expanded_depth=1
- stop=progress layer complete exhausted=False
- min_fd=11 fnd=0 progress_classes=16 progress_edges=16
- elapsed_s=0.29708960000425577 rss_mb=22.140625
- Deal 2 engine-legal, not expanded.

## 4. fd11 / stronger

- fd11=True min_local_depth=2 min_total_path=51 min_cost=51
- stock_at_fd11=4 fd11_classes=16 contributing_sources=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
- reveal_targets={'c10,d12': 16}
- column1_chain={'v026_reveal': 'c10,d12,c6,s8', 'v027_reveal': 'c10,d12,c6', 'continues_same_buried_stack': True, 'multiple_reveal_target_classes': False, 'physical_column_1_counts': {'1': 16}}
- foundation=False fd10_or_lower=False
- full_replay_ok=True fixture=solutions/4925153_simple_v0_28_fd11.moves.txt

## 5. Closure telemetry

{
  "exhausted": false,
  "unique": 612,
  "max_depth": 2,
  "empty0": 492,
  "empty1": 120,
  "empty_ge2": 0,
  "max_run": 6,
  "max_adjacencies": 21,
  "max_blocks": 5,
  "zero_legal_tableau": 0,
  "legal_count_hist": {
    "6": 20,
    "7": 12,
    "8": 8,
    "9": 48,
    "10": 16,
    "16": 8,
    "17": 8
  }
}

## 6. Exactly one next recommendation

The productive Deal-1 cascade still has another tableau reveal before Deal 2. Continue exact no-Deal search from the fd11 boundary. Do not preview Deal 2.

## Integrity

Verdict POST_DEAL1_FD12_REACHES_FD11. fd11=True exhausted=False.

Base SHA `d1875b70cb775760c0addf41284ac5eb62ced13d`. Deal `deals/4925153.txt`.
No Deal 2. No heuristic. No production change.

