# v0.57 — Research search kernel consolidation

Engineering/consolidation only. No new solving campaign.
Base: `9ce1b5f90b6cc3fc3abf477ae176de03541009f5` (v0.56).
Branch: `agent/search-kernel-consolidation-v0-57`.

Verdict: `SEARCH_KERNEL_CONSOLIDATED`.

---

## Why

v0.56 closed the authorised shallow post-SD5 component-search line
(`COMPONENT_AWARE_SEARCH_IMPROVES_TOPOLOGY_NO_F2`). Reusable solver
functionality was still trapped in experiment-specific `simple_*`
modules. Every new experiment inherited historical accidents and risked
semantic drift (for example foundation accounting).

v0.57 extracts a small reusable research/search substrate without
changing rule, accounting, identity, or historical experiment semantics.

---

## Stage 1 — Dependency audit

### A. Stable domain/core

Verified in-tree; not rewritten:

| Module | Role |
|---|---|
| `cards.py` | ranks/suits |
| `deal.py` | deal loading |
| `engine.py` | `SpiderState`, legal moves, auto-foundation |
| `rules.py` | MobilityWare Unrestricted Deal, `mw_move_cost`, `deal_cost` |
| `metrics.py` | `Action`, `replay_actions` (authoritative corrected MW replay) |
| `packed_state.py` | ordered `SPK1` (`pack_state`) and post-stock `SPS1` (`pack_post_stock_symmetry_state`) |
| `state_identity.py` | canonical structural key used by the planner/TT |
| `search.py` | production optimisation search (heuristics, killers, DealAnalysis). **Not** the research kernel. Tableau-only `search.step_cost` remains distinct from Deal-aware `research_actions.step_cost` / `rules.mw_move_cost`. |

### B. Reusable concepts previously trapped in experiments

Relocated into generic modules:

| Concept | New home |
|---|---|
| apply/restore, MW step cost, tableau enumeration, RSS, action I/O | `research_actions.py` |
| face-down / empty / foundation occupancy | `research_actions.py` + `structural_analysis.tableau_occupancy` |
| same-suit components, cover, merge edges, K/A gap, condensation | `structural_analysis.py` |
| exact cheapest-g TT, parent/path, single- and multi-lane heaps | `search_kernel.py` |
| root replay, digest checks, cheapest-g dedup, provenance merge | `research_roots.py` |

### C. Experiment-specific (left in adapters / historical scripts)

- v0.54 UCS/F2 objective, `annotate_f2_order`, harvest buckets, 720+244 portfolio, MW≤110 envelope, verdicts
- v0.55 Pareto, harvest portfolio, audit reports, v0.53 universe wiring
- v0.56 six lane keys, topology progress vs v0.55 roots, F2==2 objective, verdicts
- Diamond 6D, Spade 4S/5S, Club/Diamond TAIL, H9, gates, resource envelopes of older versions

### D. Historical/legacy

All other `simple_*.py` retained. Not deleted. Historical tests/docs still import them.

### Cross-experiment generic leakage (before)

v0.56 obtained supposedly generic functionality from:

- `simple_progressive_solver` (`_capture`, `_restore`, `_rss_mb`, `apply_action`, `step_cost`)
- `simple_resource_aware_f2` (search loop, DEAL_NOW loader)
- `simple_sd5_component_audit` (component metrics)
- `simple_workspace_reachability` (tableau actions, fd/empty)
- `simple_diamond_c_bridge` (`as_actions` / `dump_actions`)
- `simple_final_deal_timing` (`foundation_suits`)
- `simple_deal1_preview` (`stock_rows`)

v0.54/v0.55 had the same pattern one layer down.

---

## Stage 2 — Dependency direction

After v0.57:

```
cards / deal
    → engine + rules
    → metrics / accounting
    → packed_state / state_identity
    → structural_analysis + search_kernel + research_actions + research_roots
    → experiment adapters (v0.54 / v0.55 / v0.56)
    → research scripts / reports
```

Hard rule, tested: generic modules **never** import `spider.simple_*`.

Recent adapters import generic modules only (no `simple_*`).

Historical `simple_*` modules still import each other. Left untouched except:

- `simple_progressive_solver` shims `_capture`/`_restore`/`apply_action`/`step_cost`/`_rss_mb`/`format_moves_text` through `research_actions` so there is one MW implementation.
- `simple_diamond_c_bridge.as_actions` / `dump_actions` delegate to `research_actions` so historical callers keep working.

---

## Stages 3–7 — What was extracted

### Canonical new modules

- `src/spider/structural_analysis.py` — deal-independent component geometry
- `src/spider/research_actions.py` — action apply/cost/I/O/RSS/tableau
- `src/spider/search_kernel.py` — bounded exact best-g kernel
- `src/spider/research_roots.py` — replay, digest checks, cheapest-g dedup

### Adapters

- **v0.54** `simple_resource_aware_f2.py` — portfolio, UCS lane `(g,)`, F2 `foundations > 1`, harvest, verdicts. Search loop is `run_search`.
- **v0.55** `simple_sd5_component_audit.py` — audit/Pareto/portfolio/verdict. Component math is `structural_analysis`.
- **v0.56** `simple_component_aware_f2.py` — v0.55 portfolio + 720 DEAL_NOW, six lane keys, F2 `foundations == 2`, topology telemetry, verdicts. Shared TT / path / resources are `run_search`.

Kernel knowledge: none of Clubs, Hearts, Diamonds, Spades, Foundation 2, deal 4925153, or component cover.

Default action generator remains tableau-only (`tableau_actions`). Callers may pass `actions_fn` later; default behaviour is unchanged.

### Compatibility notes

- v0.54 heap secondary key used to be incoming `annotate_f2_order` rank. The kernel UCS lane is `(g, seq, node)`. Sibling order is still `annotate_f2_order` via `action_order`. Cheapest-g dominance is unchanged. Full 420s counter equality was not re-run; compact fixtures prove F2 terminal, path replay, and determinism.
- v0.56 lane keys and shared TT live in the kernel; adapter counters on a tiny unique-capped envelope are deterministic across two runs. Dummy lane keys are **not** expected to match component-key expansion counts (ordering only).

Historical JSON/reports/fixtures were not regenerated.

---

## Stage 8 — Regression contracts

Proven by tests (see below):

- engine/rules/MW accounting remain green; canonical 4925153 replay is still 172 corrected MW; auto-foundation remains 0 explicit MW; full-column-to-empty free-move unchanged
- ordered `SPK1` and post-stock `SPS1` identities unchanged; symmetric column permutations still collide; non-equivalent states do not
- structural metrics on frozen synthetic states, including the v0.56 Club class (cover 4, edges 2, gap 2, k_len 7, a_len 4, cond_len 8) and Hearts class (cover 6, edges 3, gap 11, cond_len 6)
- kernel: cheapest-g, reopen, stale multi-lane suppression, single-lane path reconstruction, round-robin shared TT, provenance, unique/time/cost stop reasons, engine terminal predicate
- v0.54/v0.55/v0.56 tests remain green without weakening

---

## Stage 9 — Rat's-nest inventory

39 files matching `src/spider/simple_*.py`. None deleted.

### Active reusable candidates (now adapters, not generic)

| File | Status |
|---|---|
| `simple_resource_aware_f2.py` | v0.54 adapter |
| `simple_sd5_component_audit.py` | v0.55 adapter |
| `simple_component_aware_f2.py` | v0.56 adapter |

### Historical but still imported (do not delete)

| File | Why it still lives |
|---|---|
| `simple_progressive_solver.py` | Research solver + shims; imported by 31 `simple_*` modules |
| `simple_workspace_reachability.py` | fd/empty/tableau helpers; imported by 29 |
| `simple_deal1_preview.py` | `stock_rows` etc.; imported by 25 |
| `simple_foundation_horizon.py` | pretty-print / SD5 constants; imported by 24 |
| `simple_foundation_race.py` | imported by 14 |
| `simple_diamond_c_bridge.py` | action I/O shim + Diamond C experiment; imported by 13 |
| `simple_current_horizon.py` | imported by 11 |
| `simple_final_deal_timing.py` | v0.43 universe helpers; imported by 4 |
| `simple_sd5_resource_runway.py` | v0.53 reconstruction; used by v0.55 **script** |
| others with 1–7 importers | experiment chain |

### Historical experiment (little or no remaining `simple_*` importer)

`simple_club_diamond_tail5`, `simple_diamond_6d_access`, `simple_diamond_cut`, `simple_diamond_g6_exposure`, `simple_fd13_portfolio`, `simple_fd14_boundary`, `simple_gate2`, `simple_sd5_resource_runway`, `simple_spade_5s_landing`, `simple_two_gate`.

### Candidate for eventual archival/deletion

The same historical-experiment set, plus helpers whose only remaining job is `_capture`/`stock_rows`/`as_actions`. Not this task.

### Uncertain / later review

`simple_post_deal_audit`, `simple_reveal_stock_audit`, `simple_legacy_fd13_alternatives`, `simple_target_clearance` — still used as libraries by older experiments.

### Active import graph, recent solver lineage

**Before (v0.56 HEAD `9ce1b5f`):**

```
v0.56 → v0.54, v0.55, progressive_solver, workspace_reachability,
         diamond_c_bridge, final_deal_timing, deal1_preview
v0.54 → deal1_preview, diamond_c_bridge, final_deal_timing,
         progressive_solver, workspace_reachability
v0.55 → diamond_c_bridge, foundation_horizon, progressive_solver,
         sd5_resource_runway, workspace_reachability
```

Import edges: **17**. Unique `simple_*` dependencies: **9**.

**After:**

```
v0.54 → research_actions, research_roots, search_kernel, structural_analysis
v0.55 → structural_analysis
v0.56 → research_actions, research_roots, search_kernel, structural_analysis
generic → (no simple_*)
```

Import edges from recent adapters to `simple_*`: **0**.

Research scripts may still import historical helpers for report formatting (`format_moves_text`, `opening_state`). That is below the adapter layer.

---

## Stage 10 — Forward architecture recommendation

### 1. Canonical modules now

| Concern | Module |
|---|---|
| Game semantics | `engine.py` + `rules.py` |
| Move accounting | `rules.mw_move_cost` / `deal_cost`; replay via `metrics.replay_actions`; research apply/cost via `research_actions` |
| Identity | ordered `packed_state.pack_state` (SPK1); post-stock `pack_post_stock_symmetry_state` (SPS1); planner `state_identity.canonical_state_key` |
| Structural analysis | `structural_analysis.py` |
| Research search execution | `search_kernel.run_search` |

`search.py` remains the production optimiser with heuristics. Do not mix it with the exact research kernel.

### 2. `simple_*` no future solver should import

Do not import any `simple_*` for generic apply/cost/RSS/action-I/O/components/search.

In particular never:

- `simple_progressive_solver` for `_capture` / `_restore` / `step_cost` / `apply_action` / `_rss_mb`
- `simple_diamond_c_bridge` for `as_actions` / `dump_actions`
- `simple_workspace_reachability` / `simple_deal1_preview` / `simple_final_deal_timing` for tableau telemetry
- `simple_sd5_component_audit` for cover/gap/edges
- `simple_resource_aware_f2` for a search loop

Historical experiments may keep their graph.

### 3. Ready for a whole-game anytime solver from the opening?

**Not yet, but the substrate is now the right place to build it.**

What exists: legal engine, corrected MW, exact identity, structural analysis, cheapest-g multi-lane kernel, root replay.

What the kernel still does not do by default: Deal/stock expansion (post-SD5 experiments omitted Deal on purpose). `actions_fn` is the hook; default remains tableau-only. Anytime scheduling, opening-to-solved policy, and the production `simple_progressive_solver` / planner lineages are separate.

v0.56 showed shallow post-SD5 component search improves topology without reaching Foundation 2. A whole-game solver must start from the opening, include Deal as a caller policy, and not reopen the exhausted SD5 excavation.

### 4. Smallest remaining architectural cleanup

Keep historical `simple_*` until a later archival pass. The only kernel-shaped gap before a whole-game solver is: pass a Deal-inclusive `actions_fn` from an opening-state adapter, with corrected MW Deal cost already in `research_actions.step_cost`. Do not invent a new heuristic first. Do not start that solver in this task.

---

## Tests

Focused (this branch): **174 passed**.

- new `tests/test_search_kernel_consolidation_v0_57.py` (20)
- v0.54 / v0.55 / v0.56 experiment contracts
- rules / MobilityWare / metrics / identity / canonical replay / deal / SPS1 / progressive v0.1

Full `tests/` with `PYTHONPATH=src;research`: **3030 passed, 37 xfailed, 3 failed**.

The three failures are not kernel-contract breaks:

- `test_workspace_service_generalisation_panel_v0_1.py` and `test_workspace_service_stock_guard_v0_1.py` fail on base `9ce1b5f` as well (frozen panel SHA drift).
- `test_face_down_lead_edge_excavation_v0_8.py::test_post_hearts_peel_emits_exact_suffix` uses the production anytime planner, not the research kernel. It passed isolated on this branch (and on base). The full-suite miss is a 90s envelope under a 23-minute run, not a rules/accounting change.

No tests were weakened or deleted to accommodate the refactor. Inspect assertions that named pre-kernel identifiers were retargeted at `run_search` / `replay_root` / `tableau_actions` while keeping the behavioural contracts.

---

## Files materially changed

New: `research_actions.py`, `research_roots.py`, `search_kernel.py`, `structural_analysis.py`, `tests/test_search_kernel_consolidation_v0_57.py`, this report.

Adapters: `simple_resource_aware_f2.py`, `simple_sd5_component_audit.py`, `simple_component_aware_f2.py`.

Shims: `simple_progressive_solver.py`, `simple_diamond_c_bridge.py`.

Tests: v0.54 and v0.56 inspect tests retargeted at the kernel.

Script: `research/sd5_component_aware_f2_search_v0_56.py` no longer imports v0.54 for generic search infrastructure.
