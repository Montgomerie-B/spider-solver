# Simple Progressive Search v0.2: Depth-Banded Backtracking

## 1. Verdict

`DEPTH_BANDING_CORRECTS_DFS_DIVE`

At a matched 1,000,000-state envelope, depth bands stopped the v0.1 5000-move dive, executed ~65× more Deals, and reached stock remaining 0 on a replay-valid path. No foundation. Best reveal worsened (face-down 16 vs v0.1 6): the node budget moved from one deep uncovering lineage onto many shallower Deal-including trajectories.

Depth discipline only. A–D tiers, ordering, Deal scoring, and preparation are unchanged from v0.1. Competing solver, not a controller patch.

## 2. Depth-aware TT contract

Exact key is packed canonical identity (tableau, stock, foundations). Path provenance is not in the key.

For each `(state, relaxation pass)` the TT stores the maximum remaining-depth budget already started (`seen`) and completely searched (`done`). Broader passes subsume narrower at the same remaining depth.

A revisit is pruned only when:

```text
max_covered_remaining(state, pass) >= current_remaining_depth
```

A state exhausted with 10 plies remaining is eligible again with 100 plies remaining. Incomplete expansions are `seen`, not `done`. Active-path cycle suppression is a separate `path_keys` set and is independent of this contract.

## 3. Band/pass schedule

Bands: `80 → 160 → 320 → 640 → 1280`. For each band, Pass 0 then 1 then 2 then 3. Remaining node/time budget is split across remaining `(band, pass)` cells so a huge shallow A-graph cannot starve later bands.

P1 (1M) used all five bands; each cell got 50k expansions and stopped on `budget`, never on graph exhaustion.

Deal executions are almost entirely Pass 3 (A–D). Pass 0–2 executed 0 Deals in every band except the tiny later-band Pass 3 leftovers. That is the unchanged Deal-tier policy, not a new quota.

Later-band Pass 0–2 slices often have `unique_new=0` and `reopens=expanded`: they re-walk already covered A/B prefixes with a larger remaining-depth allowance and then prune.

## 4. Throughput

| | P1 1M (v0.1 comparison) | P2 3M (optional) |
| --- | ---: | ---: |
| Expanded | 1,000,000 | 3,000,000 |
| Unique | 147,139 | 453,956 |
| Generated | 3,094,491 | 10,739,795 |
| Time | 1043.8s | 3301.3s |
| States/s | 958.0 | 908.7 |
| TT hits (rate) | 1,862,606 (0.651) | 6,876,014 (0.696) |
| Depth-aware prunes | 1,862,606 | 6,876,014 |
| Deeper-budget reopens | 852,339 | 2,545,522 |
| Peak RSS MiB | 138.9 | 391.7 |
| Max depth | 356 | 1221 |

Unique ≪ expanded because later bands reopen earlier exact states under a larger remaining-depth budget. Memory is not the limiter.

## 5. Depth distribution

Expansions at primitive depth:

| Depth | P1 1M | P2 3M |
| --- | ---: | ---: |
| 0–79 | 677,822 | 1,515,833 |
| 80–159 | 133,735 | 784,383 |
| 160–319 | 185,389 | 593,250 |
| 320–639 | 3,054 | 68,083 |
| 640+ | 0 | 38,451 |

v0.1 E2 max depth was 5000, with the best replay only 80 deep. v0.2 P1 max depth is 356 and more than two-thirds of expansions sit in 0–79.

## 6. Deal-depth distribution

| | v0.1 E2 | P1 1M | P2 3M |
| --- | ---: | ---: | ---: |
| Deals considered | 697,597 | 764,855 | 2,267,308 |
| Deals executed | 244 | 15,928 | 51,770 |
| Per 100k expansions | 24.4 | 1592.8 | 1725.7 |

P1 unique states by deals already done 0..5: `[57982, 34, 83, 12139, 47915, 28986]`.

P1 expansions by deals already done 0..5: `[750185, 170, 237, 15220, 54951, 179237]`.

P1 Deal executions from stock-dealt 0..5: `[5, 5, 85, 4914, 10919, 0]`.

P1 unique Deal-parent states 0..5: `[1, 1, 59, 4240, 9899, 0]`.

Stock row 5 (all five Deals done) is a large unique set (28,986 at 1M; 92,750 at 3M). v0.1’s best joint path still held 4 stock rows.

## 7. Joint replayable game progress

P1 1M witnesses (independently replayed; not mixed extrema):

- Best reveal: fd=16, foundations=0, stock remaining=5, depth=33, MW=33, replay OK.
- Best stock-progress: fd=24, foundations=0, stock remaining=0, depth=159, MW=159, replay OK.
- Best foundation: same as reveal (0 foundations).

P2 3M witnesses:

- Best reveal: fd=14, foundations=0, stock remaining=5, depth=36, MW=36, replay OK.
- Best stock-progress: fd=23, foundations=0, stock remaining=0, depth=160, MW=160, replay OK.

The uncovering champion and the Deal champion are different states. v0.1 reported one joint path (fd 6 / stock 4 / 80 moves). v0.2’s uncovering champion is worse; its Deal champion is far deeper into the stock.

## 8. First foundation

No replay-valid foundation on P1 or P2.

## 9. Complete solution

No complete solution.

## 10. Comparison with v0.1

Primary comparison is P1 vs v0.1 E2 at 1,000,000 expansions.

| | v0.1 E2 | v0.2 P1 |
| --- | ---: | ---: |
| Expanded | 1,000,000 | 1,000,000 |
| Unique | 999,478 | 147,139 |
| States/s | 865.7 | 958.0 |
| Max depth | 5000 | 356 |
| Foundations | 0 | 0 |
| Best reveal fd | 6 | 16 |
| Best stock remaining | 4 | 0 |
| Best reveal path length | 80 | 33 |
| Best reveal MW | 78 | 33 |
| Deals executed | 244 | 15,928 |
| Peak RSS | ~0.5 GiB projected | 138.9 MiB |

Optional P2 (3M) did not produce a foundation. Reveal improved only from 16 to 14. Stock remaining 0 was already present at P1.

## 11. Search-space interpretation

Depth banding did what the hypothesis asked: the 1M budget is no longer one 5000-move A/B shuffle. Most expansions are shallower than 80, Deals actually happen (almost only on Pass 3), and many distinct exact states exist after 3–5 stock rows.

It did **not** preserve v0.1’s strong reveal (fd 6). Shallow combinatorics plus Pass-3 Deal dumping reach the empty stock with face-down still in the mid-20s. Later bands waste large slices reopening A/B prefixes (`unique_new=0`). That is redistribution, not a foundation.

So v0.1’s primary problem really was DFS commitment — and fixing only that is not enough to cash out a suit.

## 12. Exactly one next recommendation

Keep depth banding. The next bounded change is to skip later-band A/B (Pass 0–2) slices once `unique_new` is 0, so leftover nodes stay on Pass 3 / unseen states. Do not add Deal quotas or new heuristic weights.

## Integrity

Base SHA `de33d1468301afdb9072d6454ae68cf5a8297898`. Deal `deals/4925153.txt`.
Human canonical line was not used to seed or guide search.
Witness paths replay through `replay_actions`. Solver does not import planner policy. Anytime controller is unchanged.

Focused tests: `tests/test_simple_progressive_depth_bands_v0_2.py` (10) plus existing simple-progressive, rules, metrics, canonical-moves, and state-identity tests (61 passed).
