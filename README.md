# Spider Solver

Project to build a human-like minimum-move solver for MobilityWare Spider Solitaire (4-suit).

## Current Status (July 2026)

**Deal 4925153** is the primary focus.

- **Best validated solution**: 163 moves
- This beats the referenced Solvitaire result of 167 moves.
- Extensive diagnostic infrastructure has been built (stage classifier, hybrid move-ordering adapter with ~5.65× speedup, transition benchmarks, checkpoint/resume, etc.).
- Most explored branches have been closed as non-viable for improvement.
- Current goal: Reach **119 moves or better** (world-record territory on this deal).

See `docs/4925153_frozen_state.md` for the detailed current state.

## Goals
- Leverage full deal visibility
- Strong emphasis on move permanence / stability
- Minimum moves optimization
- Incorporate reverse-engineering from known stock

## Current Deal
`deals/4925153.txt`