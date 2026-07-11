# Deal 4925153 Move-Accounting Incident

## Summary

A previously reported 163-move result for deal 4925153 was incorrect.

There is no distinct 163-move solution file. The alleged 163-move file was the same 174-command, user-supplied trace already stored as `solutions/4925153_canonical.moves`.

The verified status is:

- 169 tableau moves
- 5 stock deals
- 174 explicit commands
- 8 automatic foundation removals
- 172 verified MobilityWare moves
- solved=true

The user-supplied trace remains the only complete solution. The project has not yet generated its own complete solution.

## Root cause

The legacy move-cost implementation treated this class of move as free:

> Move the entire face-up stack from a column to an empty column.

That condition was too broad. It granted zero cost even when face-down cards remained beneath the moved stack.

The defective rule fired on eleven commands:

`29, 43, 46, 47, 51, 69, 79, 99, 129, 142, 150`

This produced:

`174 explicit commands - 11 legacy free moves = 163 legacy moves`

## Correct MobilityWare rule

A zero-cost relocation applies only when the move transfers the entire fully open source column to an empty column. The source must have no face-down cards remaining.

Only commands 46 and 142 satisfy that rule.

Therefore:

`174 explicit commands - 2 verified free moves = 172 MobilityWare moves`

The other nine commands were reveal plays. They moved the current face-up stack but exposed face-down cards underneath, so each costs one move.

## Stock deals and foundation removals

- All five stock deals cost one move each.
- Automatic completed-sequence removals do not add a move.
- The move that triggers an automatic removal retains its normal move cost.

## Code correction

The accounting model now separates concepts that were previously conflated:

- `explicit_commands`
- `tableau_moves`
- `stock_deals`
- `automatic_foundation_removals`
- `engine_actions`
- `mobilityware_moves`
- `legacy_mw`

The default rules implementation now receives the source face-down count and grants a free move only for a genuine complete open-column relocation.

`legacy_mw` remains available only for forensic compatibility. It must not be used for:

- incumbent comparison
- search ceilings
- pruning
- optimisation claims
- benchmark comparison
- filenames purporting to contain a verified score

## Corrected milestones

| Milestone | Old `legacy_mw` | Corrected `mobilityware_moves` |
|---|---:|---:|
| D1 | 84 | 90 |
| H20 | 131 | 139 |
| I1 | 141 | 150 |
| J8 | 149 | 158 |
| J11 | 152 | 161 |
| J17 | 158 | 167 |
| J22 solved | 163 | 172 |

## Withdrawn claims

The following claims are withdrawn:

- a verified 163-move solution exists;
- the project produced its first complete solved trace;
- the project beat the referenced Solvitaire result of 167;
- MW163 is the accepted incumbent.

## Current authoritative status

- Verified incumbent: 172 MobilityWare moves.
- Source: user-supplied canonical trace.
- First genuine improvement: 171 or fewer.
- Match referenced Solvitaire result: 167.
- Beat referenced Solvitaire result: 166 or fewer.

Every future complete candidate must be independently replayed, counted using corrected `mobilityware_moves`, and successfully stored by the durable solution archive before it is accepted.

See:

- `docs/4925153_frozen_state.md`
- `docs/solution_archive.md`

## Experiment impact

Legality, state hashes and exact-state structural findings may remain useful. Results that depended on legacy move totals, incumbent ceilings or claims of an improvement below 172 are numerically affected or invalidated and must be recalculated before reuse.

The nine reveal plays incorrectly treated as free are particularly important. Earlier optimisation had no cost incentive to avoid them, so corrected-metric searches should revisit windows around:

`29, 43, 47, 51, 69, 79, 99, 129, 150`

---

Incident status: resolved at the accounting layer; optimisation may resume only with corrected `mobilityware_moves` and durable solution capture.
