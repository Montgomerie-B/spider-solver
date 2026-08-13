# Sprint 1I — Post-Deal-2 Maturation

**Branch:** `dev/sprint1i-post-d2-maturation`  
**Baseline:** Sprint 1H @ `d76a342`

## Question

Can deferred excavation after Deal 2 be repaid cheaply enough to catch the human, or was early investment necessary?

## API

`search_epoch_maturation(seeds, deals_done=2, max_added_cost=..., ...)`

- Never expands `DEAL_NOW`
- Tracks `added_cost` separately from absolute `g`
- Full action lists replay from the original deal
- TT by structural key / cheapest g

`select_stratified_seeds(nodes)` — cheapest, least face-down, strongest same-suit, strongest H/S, balanced.

## Expose ordering

Heuristic only: prefer target-column blockers, workspace create/relocate, same-suit placements. Skip unrelated zero-cost orbits for `column_face_down_le`.
