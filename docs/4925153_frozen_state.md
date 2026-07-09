# Deal 4925153 - Frozen Diagnostic State (July 2026)

## Overview

This document records the stabilised diagnostic and control infrastructure for MobilityWare 4-suit Spider Solitaire deal 4925153 as of July 2026.

## Core Infrastructure (Frozen)

### 1. Whole-Deal Scaffold Ladder
- **Registry**: `src/spider/planner/diagnostics/scaffolds/4925153_deal_scaffold_ladder.json`
- **Decision Record**: `src/spider/planner/diagnostics/scaffolds/4925153_deal_scaffold_ladder_decision.md`
- Contains 12 milestones from start to solved with explicit continuation policies.

**Key Accepted Gold Scaffolds**:
- `canonical_J8_third_foundation_cascade_quality` (MW=149)
- `canonical_J17_pre_batch_cascade` (MW=158, cleanup ≥ 1593, cascade_firing)

**Auxiliary Seeds**:
- `beam_MW144_club_third_foundation` (MW=144) — faster third foundation but weaker cascade structure
- B5 shortcut — valid first-foundation-only optimisation, not continuation scaffold

### 2. Post-Deal-5 Diagnostics
- `cleanup_cascade_potential` — diagnostic-only
- `foundation_action_delta` — correctly distinguishes context-dependent exact foundations (J:8 club positive, J:11 hearts negative, J:17 firing)

### 3. Transition Benchmark Harness
- Manifest and comparison utility for canonical vs candidate transitions
- All 10 named transitions validated against expected metrics

### 4. Stage Classifier / Feature Arbitration
- `stage_classifier.py` with `classify_stage()`
- Encodes phase-specific diagnostic priorities and risks
- Calibrated on the full scaffold ladder

### 5. Controlled Experiment 001
- Bounded search from J:8 to J:17 (depth ≤ 10, beam ≤ 150)
- Result: **match-only** (reproduced teacher path)
- No replacement-candidate found
- No premature heart completions (delta policy worked correctly)

## Current Recommendation

- Keep `canonical_J17_pre_batch_cascade` as the gold pre-batch scaffold.
- Keep `canonical_J8_third_foundation_cascade_quality` as the gold third-foundation cascade scaffold.
- `beam_MW144` remains auxiliary MW seed only.

## Next Steps

Infrastructure is mature. Future work should use the stage classifier and transition benchmark harness for any new bounded experiments.

---
*Generated: July 2026*