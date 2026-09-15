# autopilot_integrity_v0_102

Verdict: `AUTOPILOT_INTEGRITY_READY`

Branch: `agent/autopilot-integrity-v0-102`
Base: `198281f7e7ca18ce966d0fd12056d1c7062360df`

## Lower-g / symmetry

`pack_whole_game_identity` is post-stock column-permutation symmetry.
v0.101 could overwrite `full_actions` of ordered state B with a cheaper
prefix that ends at ordered state A.

v0.102: exact `ordered_digest` is the node. Same digest + cheaper g updates
in place and syncs the candidate. Same symmetry, different ordered digest:
a distinct searchable LOWER_G_REOPENING node, linked by `symmetry_group_id`.
No suffix remapping.

## Node / candidate source of truth

Graph node is authoritative. `sync_candidate_from_node()` runs on g/ancestry
changes. Jobs carry `node_id` and `operation_id`. Scheduler builds payloads
from the node. Ancestry replay is cached per (g, digest). Mismatch is
FAILED_CONTRACT.

## f after cheaper arrival

`assembly_f = new_g + assembly_h` (h is g-independent). Proof-dead can become
proof-live solely from a lower-g reopening of the same ordered state.

## Promotion re-filter

`promote_if_solved` immediately `refilter_graph`: registry, campaign ceiling,
all STOCK_EMPTY statuses, candidate flags, pending jobs skipped. REPEAT 24H
will not re-enqueue newly dead nodes.

## Worker failure

Non-zero exit, missing/unreadable result, or worker status=failed =>
FAILED_CONTRACT on job and node. Never UNRESOLVED_TIME.

## Operation failure

A FAILED operation blocks later plan steps. Autopilot state PAUSED_ERROR.
Retry Failed Operation returns that op to pending. Stale RUNNING still
recovers to pending / pending_partial (crash != scientific failure).

## Pause / resume

EVALUATE/DEEPEN tracks member job IDs. Pause at a job boundary leaves the
operation `pending_partial`. Resume finishes remaining members before G2.
`run_pending_jobs(..., operation_id=)` isolates members. GUI keeps
"Pause after current job".

## Deterministic pipeline

Fixture: F2 cut from the verified autonomous 186 solution (no canonical).
TRANSITION_SD5 produces STOCK_EMPTY with 5 Deals; job payload ancestry
matches the node; tiny evaluation returns a real campaign outcome.

## Incumbent portability

Import adopts a better verified incumbent only after replay. Worse or
unreplayable solutions cannot overwrite local 186.

## Optiplex

Rebuild the packaged app. Profile G123_DIAMOND_DEEP. Start Autopilot.
Pause after current job. Do not start a multi-day run on a build that
still reports FAILED_CONTRACT. Ceiling 185.
