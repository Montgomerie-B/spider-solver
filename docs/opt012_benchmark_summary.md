# Opt012 benchmark summary

Compared with Opt011 raw exact backend (deal 4925153, corridor 43–51).

## Old backend (Opt011B feasibility)

| Ceiling | TT states | Time | Throughput | Peak RSS |
|---------|-----------|------|------------|----------|
| 0 | 720 exhausted | ~265 s | ~2.7 exp/s | ~44 MiB |
| 1 | ~30 960 (partial) | hours-scale | ~2.4 exp/s | growing |

## New quotient backend (Opt012)

| Ceiling | Quotient nodes | Raw free members represented | Time | Peak RSS | Notes |
|---------|----------------|------------------------------|------|----------|--------|
| 0 | **1** | 720 | **~5 s** | ~70 MiB | exhaust; 720→1 |
| 1 | **1** | 720 | **~46 s** | ~70 MiB | exhaust; 42 paid outs, all pruned |
| 2–4 | 1 | 720 | ~45 s | ~70 MiB | exhaust (reveal bound) |
| 5 | **5** | — | ~46 s | ~70 MiB | exhaust |
| 6 | **121** | — | ~857 s | ~111 MiB | exhaust |

Paid expansion from start free component: **30 240** raw unique paid successors → **42** quotient components (exactly 720× compression).

## Compression

* Cost-0 closure: **720 → 1** component (6! free-slot permutations).
* Cost-1 raw space matches old ~30k: 42×720 = 30 240.

## Projections (paid cost layers)

* Min admissible cost ≥ **5** reveals.
* c5 = 5 nodes, c6 = 121 nodes (~24×).
* c7 (not launched): rough **O(10³–10⁴)** quotient nodes if growth softens; RSS likely **≪ 12 GiB** if expansion cost is dominated by free-closure recompute rather than retention.
* Main bottleneck: recomputing free closures (~720 BFS) per expanded component (~45 s at start size).

## Goals

| Goal | Status |
|------|--------|
| ≤2 KiB / quotient node incremental | **met** at low ceilings (RSS almost flat vs baseline) |
| ≥10× effective progress | **met** on c0 (265 s → 5 s) and c1 space (30k → 1 retained component) |
| Collapse 720 correctly | **met** (1 component, reversible free) |
| Exhaust c0 and c1 | **met** |

## Recommendation

Cost-seven production remains **not authorised** until free-closure expansion is optimised (enumerate free-slot permutations algebraically instead of BFS of 720). Quotient correctness is validated; runtime for c7 is still dominated by per-node free-closure cost.
