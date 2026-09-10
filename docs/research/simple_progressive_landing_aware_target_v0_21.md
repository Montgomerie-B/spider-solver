# Simple Progressive Search v0.21: Landing-Aware Target Clearance

## 1. Verdict

`LANDING_AWARE_BREAKS_FU7_BARRIER` — target FU fell below 7 but no complete reveal was reached.

The column-1 face-up stack is nine singleton blocks. After two peels (`c11` then `h12`)
the top block is the **King of spades**, legal destinations are none, and the seed empty
has been consumed. That FU7 state verifies the King/empty hypothesis. Landing-aware
search then reached **FU 5 / 5 blocks / relaxed 6**, past v0.20's FU7 floor, but did not
reveal the buried stack (`c10,d12,c6,s8`) inside 600 s / 408k unique.

RELAXED_CLEARANCE is a research heuristic with no proof or pruning authority.
Column 7 was not tested. Production identity is unchanged.

## 2. Root target audit (column-1 signature c10,d12,c6,s8)

- FU=9 blocks=9 top=11x1 legal_landing=True empties=[2] obstruction=0 relaxed=9
- face-up=[['c', 5], ['s', 4], ['d', 3], ['s', 2], ['c', 1], ['s', 11], ['s', 13], ['h', 12], ['c', 11]]
- blocks=[{'cards': [['c', 11]], 'head_rank': 11, 'length': 1}, {'cards': [['h', 12]], 'head_rank': 12, 'length': 1}, {'cards': [['s', 13]], 'head_rank': 13, 'length': 1}, {'cards': [['s', 11]], 'head_rank': 11, 'length': 1}, {'cards': [['c', 1]], 'head_rank': 1, 'length': 1}, {'cards': [['s', 2]], 'head_rank': 2, 'length': 1}, {'cards': [['d', 3]], 'head_rank': 3, 'length': 1}, {'cards': [['s', 4]], 'head_rank': 4, 'length': 1}, {'cards': [['c', 5]], 'head_rank': 5, 'length': 1}]

## 3. v0.20 vs v0.21

| Metric | v0.20 FU-only | v0.21 landing-aware |
|---|---:|---:|
| unique | 500000 | 408223 |
| generated | 1392280 | 1777043 |
| expansions | 198884 | 286614 |
| min FU | 7 | 5 |
| min blocks | — | 5 |
| min obstruction | — | 0 |
| min relaxed | — | 6 |
| target reveal | no | False |
| elapsed s | 406.0 | 600.0009750000027 |

- stall class: TARGET_STILL_TOO_FRAGMENTED (best expanded states still have many singleton blocks)
- FU7 witness: True — 2 primitives `(0,4,1) (0,2,1)`; top=`s13`; dests=`[]`; empties=`[]`; obstruction=1
- RSS 235 MiB; stop=`time limit`

## 4. Exits and downstream

- target exits=0 known_dead=0 new=0 off_target=0
- fd10=False foundation=False

## 5. Exactly one next recommendation

Landing awareness moved the column-1 metric but did not finish the reveal. Next: do not add another heuristic or raise this budget; reassess before trying column 7.

## Integrity

Verdict LANDING_AWARE_BREAKS_FU7_BARRIER. min_fu=5 min_blocks=5 min_obst=0 min_rel=6 exits=0 stall=TARGET_STILL_TOO_FRAGMENTED.

Base SHA `ac60bd3c0a8981b355f0d16cbc5c0f102c7661fb`. Deal `deals/4925153.txt`.
No column-7 arm. No extra heuristic. No production change.

