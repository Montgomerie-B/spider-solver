# Deal 4925153 — Current Project State (July 2026)

## Authoritative status

Deal 4925153 is the sole optimisation focus.

- **Verified incumbent:** 172 MobilityWare moves.
- **Source:** original user-supplied complete trace in `solutions/4925153_canonical.moves`.
- **Trace contents:** 169 tableau moves, 5 stock deals, 174 explicit commands.
- **Solved:** yes; 8 foundations completed and stock exhausted.
- **Project-generated complete solution:** none yet.
- **Referenced Solvitaire result:** 167 moves.
- **First genuine improvement threshold:** 171.
- **Match Solvitaire:** 167.
- **Beat Solvitaire:** 166 or fewer.

A previously reported 163-move result is withdrawn. No distinct 163-move sequence exists.

## Move-accounting incident

The legacy function `mw_move_cost` incorrectly assigned zero cost whenever a move transferred the entire face-up stack to an empty column, even when face-down cards remained beneath that stack.

That defect fired eleven times in the complete trace and produced:

- explicit commands: 174
- legacy zero-cost moves: 11
- withdrawn legacy total: 163

The verified MobilityWare rule treats a move as free only when it relocates an entire fully open column to an empty column — that is, the source has no face-down cards remaining.

Only two commands in the trace qualify, so:

- explicit commands: 174
- verified free full-column relocations: 2
- corrected MobilityWare total: 172

Automatic foundation removals do not increment the move counter. All five stock deals cost one move.

See `docs/4925153_move_accounting_incident.md` for the full reconciliation.

## Corrected canonical milestones

| Milestone | Withdrawn `legacy_mw` | Verified `mobilityware_moves` |
|---|---:|---:|
| D1 | 84 | 90 |
| H20 | 131 | 139 |
| I1 | 141 | 150 |
| J8 | 149 | 158 |
| J11 | 152 | 161 |
| J17 | 158 | 167 |
| J22 solved | 163 | 172 |

`legacy_mw` is retained only for forensic compatibility and must not be used for incumbent comparison, optimisation ceilings or benchmark claims.

## Durable solution archive

Every future complete candidate must pass the central archive pipeline:

1. replay independently from the true initial deal;
2. verify legality, solved state, foundations and stock;
3. recalculate corrected `mobilityware_moves`;
4. compare strictly against the independently verified incumbent;
5. write immutable history and current-best files atomically;
6. read the move file back and replay it again.

Default external archive:

`C:\SpiderSolver\solutions\4925153`

Current verified files include:

- `4925153_best_solution.txt`
- `4925153_best_solution.moves.txt`
- `4925153_best_solution_metadata.json`
- `solution_archive.log`
- `history\`

The archive root can be overridden with `SPIDER_SOLUTION_ARCHIVE_ROOT`.

A solver improvement does not operationally exist until the distinct move sequence has been independently replayed and successfully stored in the external archive.

See `docs/solution_archive.md`.

## Valid infrastructure and findings

The accounting incident does not invalidate the following capabilities:

- rule-accurate replay of the complete user-supplied trace;
- canonical state hashing and scaffold reconstruction;
- stage classifier and diagnostic feature arbitration;
- experimental stage-aware move ordering;
- hybrid adapter throughput improvement of approximately 5.65x;
- transposition support;
- checkpoint and resume;
- durable incumbent capture and read-back verification.

Structural conclusions that depend only on legality or exact state comparison may remain useful. Numeric conclusions, search ceilings and benchmark comparisons based on `legacy_mw` require correction or rerun.

## Closed or historical branches

The following remain historical diagnostic findings, but any old move totals must be interpreted through the corrected metric:

- B5 shortcut — closed as first-foundation-only and continuation-incompatible;
- faster-third-foundation auxiliary branch formerly labelled MW144 — closed as structurally weaker;
- Exp005 early-deal branch — closed as auxiliary-only;
- W12 J8→J17 near-target — exhausted under its frozen continuation bound and closed as structurally deceptive.

## Current optimisation direction

Before resuming long search, all new runners must:

- use corrected `mobilityware_moves` only;
- load the incumbent from the independently verified external archive;
- call `record_solution_if_better(...)` immediately after a complete candidate replays successfully;
- never use `legacy_mw` for pruning, ranking, reporting or incumbent comparison.

The nine reveal moves that the legacy metric incorrectly treated as free are priority optimisation targets because earlier search had no cost incentive to avoid them:

`29, 43, 47, 51, 69, 79, 99, 129, 150`

A corrected-metric corridor scan around these transitions is the leading next optimisation direction. Any valid result below 172 would be the project’s first genuine improvement and must be captured automatically.

## Current goal

The immediate goal is a verified, archived solution at 171 or fewer.

The subsequent benchmark goals are:

- 167 — match the referenced Solvitaire result;
- 166 or fewer — beat it;
- 119 or fewer — long-term stretch target.

---

*Last updated: 11 July 2026.*
