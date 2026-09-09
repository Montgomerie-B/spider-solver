# Simple Progressive Search v0.4: Reveal/Stock Coupling Audit

## 1. Verdict

`REVEAL_BRANCH_DEAL_STARVATION`

The coupling fails at the first stock transition. The best 0-deal exact state has face-down **16**, legal Deal, **zero empties**, and a Deal-now child that **keeps fd 16**. Search found that state on **Pass 0**, where Deal is tier D (`landing=-10`) and is not an allowed child (`deal_in_pass=false`, `n_children=0` A-only). No descendant of that lineage ever Deals (`lineage_dealt=false`). The actual 0→1 Deal parents have fd **31**.

Later stock depths (1–4) are already the degraded stock-progressing trajectories; their R4/R5/R7 codes do not explain why the fd-16 line never Deals. Depth 5 has no stock left (R8).

Per-depth codes remain: R3, R4, R5, R5, R7, R8. The **transition** that splits reveal from stock is R3/R1 at 0 deals.

Diagnostics only. Search order, saturation, TT, and Deal policy match v0.3 (unique 155653, Deals 15925).

## 2. Pareto progression

75 frontier improvements. First/last:

- first: {'node': 1, 'fd': 44, 'stock_rows': 5, 'foundations': 0, 'depth': 0, 'cost': 0}
- last: {'node': 478985, 'fd': 23, 'stock_rows': 0, 'foundations': 0, 'depth': 263, 'cost': 263}

## 3. Reveal quality by stock depth

| Stock depth | Best FD | Best FD that later dealt | Immediate pre-Deal FD | Post-Deal FD | Primary loss reason |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 16 | 31 | 31 | 31 | R3 |
| 1 | 29 | 29 | 29 | 29 | R4 |
| 2 | 29 | 29 | 29 | 29 | R5 |
| 3 | 23 | 23 | 23 | 23 | R5 |
| 4 | 23 | 24 | 24 | 24 | R7 |
| 5 | 23 | — | — | — | R8 |

## 4. Strong-reveal Deal legality

- depth 0: legal=True tier=3 landing=-10 pass3_index=8 empties=0 deal_now_fd=16 prep_fd=None.
- depth 1: legal=True tier=3 landing=-10 pass3_index=10 empties=0 deal_now_fd=29 prep_fd=None.
- depth 2: legal=True tier=3 landing=-10 pass3_index=4 empties=0 deal_now_fd=29 prep_fd=29.
- depth 3: legal=True tier=3 landing=-6 pass3_index=6 empties=0 deal_now_fd=23 prep_fd=None.
- depth 4: legal=True tier=3 landing=-12 pass3_index=13 empties=0 deal_now_fd=23 prep_fd=23.
- depth 5: legal=False tier=None landing=None pass3_index=None empties=0 deal_now_fd=None prep_fd=None.

## 5. Empty-column effects

Strong-reveal states with legal Deal: 5. Blocked by empties under search rules: 0.
MW_RULES.can_deal_into_empty is True, so empties do not make Deal illegal
in this profile unless a restricted rule set is used.

## 6. Deal ordering

Median Deal ordinal among ordered children: 7.
Deal summary: {'count': 15925, 'median_ordinal': 7, 'mean_delta_fd': 0.0, 'mean_parent_empties': 0.005337519623233909, 'mean_delta_same': 0.07792778649921507, 'tt_skip': 0, 'prep_followed': 0, 'pass_counts': {'3': 15925}}.

## 7. Deal-transition structural deltas

Executed Deals: 15925. Mean Δfd=0.0, mean Δsame-suit joins=0.07792778649921507, mean parent empties=0.005337519623233909.

## 8. Preparation conversion

Depths where prep preferred: [2, 4].
Depths where prep then Deal followed: [].

## 9. Post-Deal continuation

Deal children expanded: 15905; TT-skipped: 0.
Subtree expansions on linked pre-Deal parents: [None, None, 1, 1, 1, None].

## 10. Dominant causal diagnosis

The fd-16 / 0-deal witness is the one that matters. Deal is legal there and would not bury cards (`deal_now_fd=16`). Pass 0 cannot take Deal. Pass 3 Deals 15925 times, all from other states, median ordinal 7, never from this lineage. Empties do not block (0/5 strong reveals). TT skips 0 Deal children. Prep is not the 0-deal failure (`prep_preferred=false`).

That is Deal starvation on the strong-reveal branch, not a destructive known row and not empty-column legality.

## 11. Search/runtime overhead

Expanded 800000 in 891.6s (897.3/s), RSS 261.38671875 MiB. v0.3 P1 was 800k in 828s at 967.6/s.

## 12. Exactly one next recommendation

Keep the solver unchanged except one bounded experiment: when a new best-reveal exact state has legal Deal, try Deal (or its 1-ply prep) before remaining tableau siblings in that node only. Do not add quotas.

## Integrity

Base SHA `cb4c5bfecc874542dc01b06a1dece59b454fa1e5`. Deal `deals/4925153.txt`.
Audit hooks do not insert counterfactual moves into search.
Witness paths replay through `replay_actions`.

