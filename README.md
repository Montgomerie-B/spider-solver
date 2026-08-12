# Spider Solver

Project to build a human-like minimum-move solver for MobilityWare Spider Solitaire (4-suit), progressing toward a general perfect-information solver that can find solutions quickly, improve them continuously, and prove optimality or unsolvability when feasible.

## Forward Architecture

The current forward development architecture is:

- [`docs/anytime_solver_architecture.md`](docs/anytime_solver_architecture.md) — deal-independent anytime solver strategy and roadmap

The older [`docs/layered_planner_development_plan.md`](docs/layered_planner_development_plan.md) is retained as a historical baseline and source of reusable planner ideas, but it is no longer the forward strategic architecture.

## Current Status (August 2026)

**Deal 4925153** remains the primary development benchmark. The MobilityWare leaderboard screenshot supplied by the user displays the same benchmark deal as **Deal #492515**; the repository retains the existing internal identifier pending any deliberate repository-wide rename.

- **Verified replayable incumbent:** 172 corrected MobilityWare moves.
- The incumbent is the original user-supplied complete trace: 169 tableau moves plus 5 stock deals, or 174 explicit commands.
- MobilityWare counts two complete open-column relocations to an empty column as free, giving `174 - 2 = 172`.
- A previously reported value of 163 was caused by defective legacy move accounting and has been withdrawn. No distinct 163-move solution exists.
- Leaderboard evidence for this benchmark includes the user's historical 167, another 154 result, and a best score of **119**. The 119 is treated as credible evidence that a radically shorter route exists, not as a deal-specific rule for the general solver.
- The project has not yet generated its own complete solution below 172.
- Recent exact-search work produced collision-safe structural identity, algebraic zero-cost quotient expansion, corrected-metric corridor proof searches, checkpoint/resume, and durable solution verification.
- The next strategic development phase is a generic perfect-information analyser for downstream reveal value, empty-column lifecycle/recoverability, known-stock reception, and global incumbent-guided branch-and-bound.
- A durable external solution archive independently replays every candidate and writes strict improvements to `C:\SpiderSolver\solutions\4925153`.

A result is not accepted as an improvement until its distinct move sequence:

1. replays legally from the true initial deal,
2. solves with the corrected `mobilityware_moves` metric,
3. scores strictly below the current verified incumbent, and
4. is atomically written and read-back verified in the external archive.

See:

- [`docs/anytime_solver_architecture.md`](docs/anytime_solver_architecture.md) — forward architecture and development roadmap
- [`docs/4925153_frozen_state.md`](docs/4925153_frozen_state.md) — authoritative benchmark state
- [`docs/4925153_move_accounting_incident.md`](docs/4925153_move_accounting_incident.md) — 163/172 accounting incident and correction
- [`docs/solution_archive.md`](docs/solution_archive.md) — durable incumbent capture policy
- [`docs/layered_planner_accounting_amendment.md`](docs/layered_planner_accounting_amendment.md) — amendment superseding historical planner cost assumptions

## Goals

- Generalise to arbitrary perfect-information Spider deals rather than hard-code the benchmark deal
- Leverage full hidden-card and stock visibility
- Treat downstream reveal value and empty-column lifecycle as strategic planning concepts
- Find a legal solution quickly, then improve it iteratively under a tightening incumbent ceiling
- Use only admissible lower bounds for proof pruning
- Preserve exact corrected MobilityWare accounting and replay verification
- Eventually prove optimality where tractable, or prove unsolvability by exhaustive exact search

## Current Benchmark Deal

`deals/4925153.txt`
