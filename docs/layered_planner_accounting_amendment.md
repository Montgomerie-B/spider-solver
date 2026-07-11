# Layered Planner Accounting Amendment — Deal 4925153

## Status

This amendment supersedes historical move-cost assumptions in `docs/layered_planner_development_plan.md` and related pre-audit diagnostics.

The original plan remains a useful architectural and historical record, but its move-counting statements must not be treated as authoritative after the July 2026 forensic audit.

## Superseded assumptions

The following historical statements are withdrawn or amended:

- “full face-up run to empty = 0”
- “save any solved even >163”
- “hunt for first low-cost or <163 solve”
- any claim that the canonical trace solves at 163
- any benchmark comparison based on `legacy_mw`

## Correct MobilityWare accounting

A move to an empty column has zero MobilityWare cost only when it relocates the entire fully open source column and there are no face-down cards beneath the moved stack.

Formally, the free relocation requires:

- destination is empty;
- the moved cards are the complete face-up contents of the source column; and
- `source_face_down_count == 0`.

Otherwise the tableau move costs one.

Additional rules:

- each stock deal costs one;
- automatic foundation removal costs zero separately;
- the player move that triggers a removal retains its normal cost.

## Authoritative incumbent

The current complete trace is the user-supplied `solutions/4925153_canonical.moves`:

- 169 tableau moves
- 5 deals
- 174 explicit commands
- 2 verified free complete-column relocations
- 172 corrected MobilityWare moves

No distinct 163-move solution exists.

## Required terminology

New planner and optimisation work must distinguish:

- `explicit_commands`
- `tableau_moves`
- `stock_deals`
- `automatic_foundation_removals`
- `engine_actions`
- `mobilityware_moves`
- `legacy_mw`

`legacy_mw` is audit-only and must not drive search or reporting.

## Required search behaviour

All future planner experiments must:

1. use corrected `mobilityware_moves` for cost, ceilings and incumbent comparison;
2. load the current incumbent from the durable external archive when available;
3. independently replay every complete candidate;
4. call `record_solution_if_better(...)` immediately after successful full replay;
5. avoid claiming an improvement until the archive write and read-back validation succeed.

## Revised objectives

- first genuine improvement: 171 or fewer;
- match referenced Solvitaire result: 167;
- beat referenced Solvitaire result: 166 or fewer;
- long-term stretch target: 119 or fewer.

## Historical diagnostics

Historical planner reports remain useful for architecture, legality and structural analysis, but any old `MW` field may refer to `legacy_mw`.

Before reusing a historical numeric conclusion:

- replay the relevant path under corrected accounting;
- regenerate milestone costs;
- revise any pruning or incumbent ceiling derived from the old total.

The nine reveal moves wrongly treated as free by the legacy metric are:

`29, 43, 47, 51, 69, 79, 99, 129, 150`

These transitions deserve renewed corrected-metric optimisation because earlier searches had no incentive to eliminate them.

## References

- `docs/4925153_move_accounting_incident.md`
- `docs/4925153_frozen_state.md`
- `docs/solution_archive.md`

---

Effective date: 11 July 2026.
