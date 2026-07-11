# Spider Solver

Project to build a human-like minimum-move solver for MobilityWare Spider Solitaire (4-suit).

## Current Status (July 2026)

**Deal 4925153** is the sole optimisation focus.

- **Verified incumbent:** 172 MobilityWare moves.
- The incumbent is the original user-supplied complete trace: 169 tableau moves plus 5 stock deals, or 174 explicit commands.
- MobilityWare counts two complete open-column relocations to an empty column as free, giving `174 - 2 = 172`.
- A previously reported value of 163 was caused by defective legacy move accounting and has been withdrawn. No distinct 163-move solution exists.
- The project has not yet generated its own complete solution or beaten the referenced Solvitaire result of 167 moves.
- The first genuine improvement threshold is 171; matching Solvitaire requires 167 and beating it requires 166 or fewer.
- The hybrid move-ordering adapter demonstrated approximately 5.65x higher throughput while preserving checkpoint ordering quality.
- A durable external solution archive now independently replays every candidate and writes strict improvements to `C:\SpiderSolver\solutions\4925153`.

A result is not accepted as an improvement until its distinct move sequence:

1. replays legally from the true initial deal,
2. solves with the corrected `mobilityware_moves` metric,
3. scores strictly below the current verified incumbent, and
4. is atomically written and read-back verified in the external archive.

See:

- [`docs/4925153_frozen_state.md`](docs/4925153_frozen_state.md) — authoritative current state
- [`docs/4925153_move_accounting_incident.md`](docs/4925153_move_accounting_incident.md) — 163/172 accounting incident and correction
- [`docs/solution_archive.md`](docs/solution_archive.md) — durable incumbent capture policy
- [`docs/layered_planner_accounting_amendment.md`](docs/layered_planner_accounting_amendment.md) — amendment superseding historical planner cost assumptions

## Goals

- Leverage full deal visibility
- Strong emphasis on move permanence and stability
- Minimum-move optimisation using verified MobilityWare accounting
- Incorporate reverse-engineering from known stock
- Capture every verified improvement automatically and durably

## Current Deal

`deals/4925153.txt`
