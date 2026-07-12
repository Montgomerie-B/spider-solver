# External Solution Archive

## Purpose

Every complete solution that is **genuinely better** than the current verified
incumbent must be:

1. Independently replayed from the true initial deal
2. Scored with corrected **`mobilityware_moves`** (never `legacy_mw`)
3. Written atomically to a durable external archive on disk
4. Preserved as immutable history

Internal score reports, JSON metrics, or filenames alone are **not** sufficient.

## Default path (Windows)

```
C:\SpiderSolver\solutions\<deal_id>\
```

Override with environment variable:

```
SPIDER_SOLUTION_ARCHIVE_ROOT
```

The archive is **outside** the Git repository.

## Files

| File | Role |
|------|------|
| `<deal>_best_solution.txt` | Human-readable current best + metadata header |
| `<deal>_best_solution.moves.txt` | Parser-ready commands only |
| `<deal>_best_solution_metadata.json` | Machine metadata |
| `history/` | Immutable historical copies |
| `solution_archive.log` | Append-only event log |

## Validation policy

Before archiving:

* Load deal file for the stated deal id
* Parse full command sequence
* Replay every move/deal through the rules engine
* Require `solved=true`, foundations=8, stock=0
* Derive `mobilityware_moves` independently
* Reject claim mismatches, illegal moves, incomplete paths
* **Never** use `legacy_mw` for comparison

Strict improvement only:

```
candidate.mobilityware_moves < incumbent.mobilityware_moves
```

Equal scores do not replace the incumbent.

## Atomic write policy

1. Write immutable history copies first  
2. Write current-best via temp file + `fsync` + `os.replace`  
3. Read back moves file, re-replay, re-hash  
4. Only then report success  

On failure: emergency copy under `artifacts/solution_recovery/<deal>/` (not the permanent archive).

## Startup incumbent loading

Optimisation runners should call `select_startup_incumbent(deal_id)`:

1. Validate external current-best  
2. Fall back to history  
3. Fall back to repository canonical  
4. Prefer lowest independently verified score  

Corrupt current-best files are preserved with a `.corrupt.*` suffix, not deleted.

## CLI

```bash
# From repo root with PYTHONPATH=src (or installed package)
python -m spider.solution_archive bootstrap --deal 4925153
python -m spider.solution_archive show --deal 4925153
python -m spider.solution_archive verify --deal 4925153
python -m spider.solution_archive history --deal 4925153
python -m spider.solution_archive consider --deal 4925153 --moves path/to/file.moves
```

## Integration requirements

All complete-solution success paths must call:

```python
from spider.solution_archive import record_solution_if_better

record_solution_if_better(
    deal_id,
    actions,
    source="...",
    experiment_id="...",
)
```

Wired at minimum:

* `optimizer_session._save_improvement`
* `macro.macro_solve_with_restarts`
* Opt007 whole-deal improved export
* Opt009B splice success
* Opt010 solved validation

## Authoritative incumbent (4925153)

* **172** `mobilityware_moves`
* Source: user-supplied `solutions/4925153_canonical.moves`
* Withdrawn: legacy internal 163

See also: `docs/4925153_move_accounting_incident.md`.
