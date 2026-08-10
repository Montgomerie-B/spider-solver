# Opt013C — Exact cost-7 corridor result (commands 43–51)

## Outcome: **B. CORRIDOR EXHAUSTED**

Complete exact corrected-MobilityWare search at paid cost ≤ 7 drained with **no** exact reconnection to the canonical command-51 target.

Commands 43–51 are therefore **closed as a one-move optimisation corridor** (canonical segment cost 8; no exact ≤7 reconnect exists under the algebraic free-quotient backend).

## Authorised baseline

| Item | Value |
|------|-------|
| Branch | `opt013/algebraic-quotient-expansion` |
| Commit | `4c6768c9bb2ab314261562ee6127dc3992879ebf` |
| Backend | `opt013_algebraic_v1` (algebraic quotient) |
| Incumbent | 172 / `77d169da2538ba8c` (external archive independently verified) |

## Launch

```text
python -m spider.planner.diagnostics.opt012_compact_search --ceiling 7 --max-rss-gib 8
```

| Field | Value |
|-------|-------|
| PID | 194988 |
| Start (UTC) | 2026-08-10T20:41:05Z |
| Config fingerprint | `1f6a9fa77dc17a1d8db68cfe` |
| Artifacts | `artifacts/opt013/cost7/` (gitignored) |
| Checkpoint | `artifacts/opt013/cost7/opt013_quotient_checkpoint.json` (~1.3 MiB, 1445 nodes) |

## Result summary

| Metric | Value |
|--------|------:|
| Termination | `exhausted` |
| Status | `exhaustive_failure` |
| Quotient components (tt) | **1445** |
| Expanded | 1445 |
| Unique paid successors enumerated | 26144 |
| Peak frontier | 578 |
| Runtime | **~82 s** |
| Peak RSS | **~27.4 MiB** |
| Target found | **no** |
| Segment MW | null |
| Improvements | none |
| Genuine improvement | **false** |

### Prune counts

| Reason | Count |
|--------|------:|
| reveal_bound | 22853 |
| face_down_prefix | 420 |
| foundation | 0 |
| stock | 0 |
| accepted | 2871 |

### Layer context (prior Opt013B)

| Ceiling | Nodes | Runtime |
|---------|------:|--------:|
| 5 | 5 | ~0.5 s |
| 6 | 121 | ~8–9 s |
| **7** | **1445** | **~82 s** |

## Interpretation

- Exact free-quotient search with target-monotonic pruning fully exhausted the paid-cost-7 ball around command 42.
- No component at paid cost ≤ 7 contains the exact labelled command-51 state.
- The canonical 8-move corridor segment cannot be replaced by any corrected-MW path of length ≤ 7 under this model.
- **No solver improvement** was claimed or archived. Incumbent remains **172** / `77d169da2538ba8c`.

## Non-goals observed

- Did not merge PR #1, #2, or #3.
- Did not write a false improvement to the external archive.
