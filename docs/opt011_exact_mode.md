# Opt011 / Opt011A — exact micro-corridor (commands 43–51)

Deal **4925153** only. Metric: corrected **`mobilityware_moves`** (never `legacy_mw`).

## Modes

| Mode | Completeness | Depth bound |
|------|--------------|-------------|
| `exact` (default) | Complete for corrected segment cost ≤ 7, no stock deals | **None** |
| `bounded` | Diagnostic only | Optional (e.g. 24); label: `bounded scan: corrected cost <= 7, explicit depth <= 24` |

Bounded mode **must never** report unrestricted corridor exhaustion.

## Algorithm (exact)

- **0–1 BFS** (deque: zero-cost edges to front, unit-cost to back).
- Edge costs are corrected MobilityWare tableau costs ∈ {0, 1}.
- Transposition: lowest corrected cost per Zobrist state key; equal-cost re-arrivals discarded.
- Zero-cost cycles terminate via transposition.
- Hybrid adapter orders successors only; full `enumerate_moves()` set is retained (deals stripped).
- Target success requires **Zobrist + full structural equality**.

## Completeness statement

Exact mode is complete for:

```text
corrected segment mobilityware_moves <= 7
no stock deals
exact start = canonical after command 42
exact target = canonical after command 51
```

The depth-24 production scan is **not** complete for unrestricted cost ≤ 7.

## Resume / lock

- Atomic checkpoint (temp + `os.replace`) with schema, algorithm version, hashes, ceiling, hybrid config, checksum.
- Single-writer lock (`opt011.lock`) under runtime dir.
- `--max-rss-gib` stops admitting work, writes checkpoint, exits Outcome C.

## Run (after tests)

```bat
set PYTHONPATH=src
python -m spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor --mode exact
```

Do not launch a second long run alongside an active bounded scan.
