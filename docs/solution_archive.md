# Durable Solution Archive

## Purpose

The solution archive is the authoritative capture path for complete solutions to deal 4925153.

A reported improvement is not accepted merely because a search runner, JSON file or internal metric says that one exists. The distinct move sequence must be independently replayed, counted with corrected `mobilityware_moves`, written to the external archive and read back successfully.

## Default location

The default Windows archive root is:

`C:\SpiderSolver\solutions`

Deal 4925153 is stored under:

`C:\SpiderSolver\solutions\4925153`

The root can be overridden with the environment variable:

`SPIDER_SOLUTION_ARCHIVE_ROOT`

The archive is intentionally outside the Git repository.

## Current incumbent

The archive was bootstrapped from `solutions/4925153_canonical.moves` by independent replay.

Current verified status:

- deal: 4925153
- corrected MobilityWare moves: 172
- source: user-supplied canonical trace
- solved: yes
- path hash: `77d169da2538ba8c`

## Files

The deal directory maintains:

- `4925153_best_solution.txt` — human-readable current best with metadata and complete move list
- `4925153_best_solution.moves.txt` — parser-ready commands only
- `4925153_best_solution_metadata.json` — machine-readable incumbent metadata
- `solution_archive.log` — append-only archive event log
- `history\` — immutable historical best-solution copies

Historical filenames include the deal, zero-padded move count, UTC timestamp and path hash.

## Central API

The shared entry point is:

```python
from spider.solution_archive import record_solution_if_better

result = record_solution_if_better(
    deal_id="4925153",
    moves=candidate_moves,
    source="experiment-id or runner name",
    experiment_id="optional-experiment-id",
)
```

The archive module independently determines whether the candidate is legal, solved and strictly better.

Runner-provided scores, filenames and `legacy_mw` are never trusted.

## Validation policy

Before a candidate can replace the incumbent, the archive:

1. loads the true initial deal;
2. parses the complete candidate command sequence;
3. replays every command through the rules engine;
4. verifies tableau moves and stock deals;
5. verifies automatic foundation removals;
6. verifies eight completed foundations and no remaining stock;
7. recalculates all counters;
8. derives corrected `mobilityware_moves`;
9. calculates a deterministic path hash and final state hash;
10. compares strictly with the verified incumbent.

The replacement rule is:

`candidate.mobilityware_moves < incumbent.mobilityware_moves`

Equal-score alternatives and worse candidates do not replace the current best.

## Atomic writes and recovery

Archive updates are crash-safe:

1. write immutable history first;
2. write temporary current-best and metadata files;
3. flush and `fsync` where supported;
4. atomically replace current-best files with `os.replace`;
5. read the parser-ready move file back;
6. verify its path hash;
7. replay it again and confirm the same score and solved state.

Only after read-back verification does the result report a successful archive update.

If the external archive write fails, the candidate is preserved where possible under:

`artifacts/solution_recovery/4925153/`

That fallback is an emergency recovery area, not the permanent incumbent archive. The system must not claim that an improvement was safely captured when the external write failed.

## Startup incumbent loading

Optimisation runners should load the incumbent in this order:

1. external current-best move file, independently replayed;
2. latest valid immutable history entry;
3. repository canonical trace.

Metadata alone is never sufficient. Any candidate incumbent must replay successfully.

If a current-best file is corrupt, it is preserved for diagnosis and the loader falls back to the latest valid history entry.

## Search integration requirement

Every code path capable of producing a complete solution must call `record_solution_if_better(...)` immediately after independent full replay succeeds.

Current integrations include:

- `optimizer_session._save_improvement`
- `macro.macro_solve_with_restarts`
- whole-deal solution export
- corridor splice success
- exact reconnection full-solution validation
- direct solved-state discovery

Future optimisation runners are not ready for unattended use until they integrate the same archive call.

When an improvement is safely archived, the runner may update its in-memory incumbent and tighten valid search ceilings, but it must preserve the written solution even if the process later crashes.

## Command-line interface

Bootstrap the repository canonical trace:

```text
python -m spider.solution_archive bootstrap --deal 4925153
```

Validate and consider another move file:

```text
python -m spider.solution_archive consider --deal 4925153 --moves <path>
```

Show the current best:

```text
python -m spider.solution_archive show --deal 4925153
```

Verify the archive:

```text
python -m spider.solution_archive verify --deal 4925153
```

List immutable history:

```text
python -m spider.solution_archive history --deal 4925153
```

## Operational invariant

A future improvement exists operationally only when all of the following are true:

- a distinct complete move sequence exists;
- it independently replays from the true deal;
- corrected `mobilityware_moves` is strictly below the incumbent;
- the external archive write succeeds;
- the written move file passes read-back replay verification.

Internal score reports are not evidence of a new incumbent.
