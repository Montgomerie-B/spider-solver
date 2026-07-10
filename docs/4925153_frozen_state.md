# Deal 4925153 - Current Project State (July 2026)

## Overview

This document summarises the current status of work on MobilityWare 4-suit Spider Solitaire deal 4925153 as of July 2026.

## Major Achievement

- **Validated solution**: 163 MobilityWare moves
- This is the first complete, legal solved trace produced by the project.
- It beats the referenced Solvitaire result of 167 moves by 4 moves.
- MW 163 remains the accepted incumbent / best validated result.

## Diagnostic & Infrastructure Layer (Mature)

### Key Components
- Whole-deal scaffold ladder with 12 milestones and explicit continuation policies
- `cleanup_cascade_potential` and `foundation_action_delta` (diagnostic-only)
- `stage_classifier` with phase-aware feature arbitration
- Experimental Stage-Aware Move Ordering Adapter (including hybrid mode)
- Transition benchmark harness
- Checkpoint / resume infrastructure for long runs

### Hybrid Adapter Performance
- Phase A of Opt009A demonstrated **5.65× throughput improvement** over full adapter while preserving ordering quality at all key checkpoints.
- Hybrid mode is now the recommended frozen configuration for future search work on this deal.

## Branch Status

Most explored branches have been closed as non-viable for improvement:

- **B5 shortcut**: Closed (first-foundation-only, non-continuation)
- **MW144**: Closed (faster third foundation but weaker cascade structure)
- **Exp005 early-deal branch**: Closed as auxiliary-only
- **W12 near-target (J8→J17)**: Closed as structurally deceptive (Opt010)

## Search Summary

Extensive bounded search has been performed:
- Multiple controlled experiments (Exp001–Exp006A)
- Whole-deal incumbent challenge (Opt007)
- Focused first-foundation work (Opt008)
- Corridor shortcut scan + targeted recovery (Opt009B + Opt010)

**Result**: No complete solution below MW 163 has been found. The canonical path remains the strongest validated route.

## Current Goal

User target: **119 moves or better** (current world-record territory on this deal).

## Recommended Next Direction

Given diminishing returns on broad search, the most productive paths forward are:

1. Further targeted segment improvement on high-value windows (if specific near-miss signals emerge).
2. Additional throughput / efficiency work on the hybrid adapter to enable more effective long runs.
3. Documentation and archival of current 163-move solution as a strong baseline.

---
*Last updated: July 2026*