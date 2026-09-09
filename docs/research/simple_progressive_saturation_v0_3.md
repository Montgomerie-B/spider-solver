# Simple Progressive Search v0.3: Saturation-Aware Depth Bands

## 1. Verdict

`SATURATION_SKIP_IMPROVES_COVERAGE` — unique 155653 (0.195/exp) vs v0.2 147139 (0.147/exp); skipped 10 slices.

Scheduling only. A–D classification, ordering, Deal policy, depth bands,
and the depth-aware TT contract are unchanged from v0.2.

## 2. Saturation contract

The accounting unit is the existing v0.2 `(depth band, relaxation pass)`
budget cell (remaining band nodes split across remaining live passes).
No extra micro-quantum is used, and none was tuned on 4925153.
If a completed cell has `unique_new == 0`, that pass is saturated:
later equivalent slices of the same pass are not allocated; leftover
band budget goes to broader unsaturized passes. Saturation does not
mark states exhausted beyond the depth-aware TT.

Skipped slices: 10. Redirected allocation: 849998. Saturated passes: [0, 1, 2, 3].

## 3. Coverage efficiency

- Expanded: 800000 (200000 of the 1M envelope unspent after pass 3 saturated and band 1280 skipped)
- Unique: 155653
- Unique/expanded: 0.1946 (v0.2 P1: 0.1471)
- States/s: 967.6
- Max depth: 610
- Peak RSS MiB: 241.64453125
- Unique by pass A–D: [47541, 7441, 3000, 97671]

## 4. Band/pass productivity

- band 80 pass 0: expanded=50000 unique_new=47541 rate=0.9508 sat=False skipped=False redir=0 reopens=2459 stop=budget.
- band 80 pass 1: expanded=50000 unique_new=7441 rate=0.1488 sat=False skipped=False redir=0 reopens=42558 stop=budget.
- band 80 pass 2: expanded=50000 unique_new=3000 rate=0.0600 sat=False skipped=False redir=0 reopens=46516 stop=budget.
- band 80 pass 3: expanded=50000 unique_new=44354 rate=0.8871 sat=False skipped=False redir=0 reopens=5609 stop=budget.
- band 160 pass 0: expanded=50000 unique_new=0 rate=0.0000 sat=True skipped=False redir=0 reopens=50000 stop=budget.
- band 160 pass 1: expanded=50000 unique_new=0 rate=0.0000 sat=True skipped=False redir=0 reopens=50000 stop=budget.
- band 160 pass 2: expanded=50000 unique_new=0 rate=0.0000 sat=True skipped=False redir=0 reopens=50000 stop=budget.
- band 160 pass 3: expanded=50000 unique_new=42701 rate=0.8540 sat=False skipped=False redir=0 reopens=7299 stop=budget.
- band 320 pass 0: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=50000 reopens=0 stop=saturated.
- band 320 pass 1: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=66666 reopens=0 stop=saturated.
- band 320 pass 2: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=100000 reopens=0 stop=saturated.
- band 320 pass 3: expanded=200000 unique_new=10616 rate=0.0531 sat=False skipped=False redir=0 reopens=189384 stop=budget.
- band 640 pass 0: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=50000 reopens=0 stop=saturated.
- band 640 pass 1: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=66666 reopens=0 stop=saturated.
- band 640 pass 2: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=100000 reopens=0 stop=saturated.
- band 640 pass 3: expanded=200000 unique_new=0 rate=0.0000 sat=True skipped=False redir=0 reopens=200000 stop=budget.
- band 1280 pass 0: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=50000 reopens=0 stop=saturated.
- band 1280 pass 1: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=66666 reopens=0 stop=saturated.
- band 1280 pass 2: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=100000 reopens=0 stop=saturated.
- band 1280 pass 3: expanded=0 unique_new=0 rate=0.0000 sat=False skipped=True redir=200000 reopens=0 stop=saturated.

## 5. TT reopening behaviour

- Depth-aware prunes: 2609963
- Deeper-budget reopens: 643825
- TT hits: 2609963 (rate 0.765)
- v0.2 P1 prunes/reopens: 1862606 / 852339

## 6. Stock-depth distribution

- Deals considered/executed: 314607/15925
- Deals per 100k: 1990.62
- Unique states by deals 0..5: [57982, 34, 83, 12139, 47919, 37496]
- Expansions by deals 0..5: [300148, 136, 209, 15101, 54921, 429485]

## 7. Joint face-down-by-stock-depth table

| Deals completed | Best face-down | Stock remaining | Depth | MW | Replay |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 16 | 5 | 33 | 33 | True |
| 1 | 29 | 4 | 43 | 43 | True |
| 2 | 29 | 3 | 71 | 71 | True |
| 3 | 23 | 2 | 159 | 159 | True |
| 4 | 23 | 1 | 160 | 160 | True |
| 5 | 23 | 0 | 263 | 263 | True |

- Best reveal: fd=16 stock=5 fnd=0 depth=33 MW=33 replay=True
- Best stock: fd=23 stock=0 fnd=0 depth=263 MW=263 replay=True
- Best foundation: fd=16 stock=5 fnd=0 depth=33 MW=33

## 8. First foundation

No replay-valid foundation.

## 9. Complete solution

No complete solution.

## 10. v0.1/v0.2/v0.3 comparison

| | v0.1 E2 | v0.2 P1 | v0.3 P1 |
| --- | ---: | ---: | ---: |
| Expanded | 1000000 | 1000000 | 800000 |
| Unique | 999478 | 147139 | 155653 |
| Unique/exp | 0.999 | 0.147 | 0.195 |
| States/s | 865.7 | 958.0 | 967.6 |
| Max depth | 5000 | 356 | 610 |
| Deals executed | 244 | 15928 | 15925 |
| Best reveal fd | 6 | 16 | 16 |
| Best stock remaining | 4 | 0 | 0 |
| Foundations | 0 | 0 | 0 |

## 11. Search interpretation

Saturation skipped 10 later-band slices (mostly Pass 0–2 after band 160, then Pass 3 at band 1280) and left 200k of the 1M envelope unspent. Unique 155653 / 800000 = 0.1946 versus v0.2 P1 147139 / 1000000 = 0.1471. Absolute unique rose only ~8.5k; the gain is not paying for unique_new=0 A/B reopenings. Reveal fd 16 and stock remaining 0 match v0.2. The joint table still splits: best uncovering is at 0 deals (fd 16); after 5 deals the best exact state is still fd 23. Verdict SATURATION_SKIP_IMPROVES_COVERAGE.

## 12. Exactly one next recommendation

Keep saturation skipping. The remaining divergence is reveal vs stock progression on the same trajectory; measure that without adding heuristics.

## Integrity

Base SHA `1aa42a3b969947992807ad52ab2c9fbfd83504e8`. Deal `deals/4925153.txt`.
Human canonical line was not used to seed or guide search.
Witness paths replay through `replay_actions`. Solver does not import
planner policy. Anytime controller is unchanged.

