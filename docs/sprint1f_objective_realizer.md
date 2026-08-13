# Sprint 1F — Tactical Objective Realizer

**Branch:** `dev/sprint1f-objective-realizer`  
**Baseline:** Sprint 1E @ `e735dad`

## Predicate fix

`EXPOSE_REVEAL_PREFIX` now uses `column_face_down_le`:

- Face-down cards cannot move before exposure.
- Target = `len(column.face_down) <= start_fd - required_reveals`.
- Duplicate rank/suit face-up elsewhere does **not** satisfy.

## API

`realize_objective(state, objective, mode=, max_cost=, max_nodes=, time_limit_s=)`

Statuses: `already_satisfied | found | not_found_within_bound | unsupported | resource_limit`

Modes: `EXACT_BOUNDED` (0-1 BFS on corrected cost), `FAST_BOUNDED` (beam).

Found paths are replayed; cost independently recomputed.

## Lower-bound correction (record)

Sprint 1E: raw `face_down + deals` is **not** admissible.  
`h = deals + ceil(max(0, fd − 10·deals) / 2)`.

## Families realized

DEAL_NOW (exact deal), CREATE_WORKSPACE, SHAPE_STOCK_RECEIVER,  
EXPOSE_REVEAL_PREFIX, CONSOLIDATE / ADVANCE / REMOVE via same search.

## Reuse

Engine `move`/`deal`, `MW_RULES`, `replay_actions`, `canonical_state_key` TT.
