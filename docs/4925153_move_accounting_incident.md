# Move Accounting Incident — Deal 4925153

**Status:** Root cause identified and corrected.  
**Date:** 2026-07-10  
**Scope:** MobilityWare four-suit deal 4925153 only.

## Discovery

The project repeatedly reported that the canonical solution solved at **internal `MW=163`**, described as:

* the first complete project solve,
* four moves better than a referenced Solvitaire result of 167,
* a new 163-move canonical solution.

Those claims were **unverified and false as MobilityWare UI scores**.

The file presented as the “163-move solution” is **byte-identical** to the original user-supplied trace:

* **169** tableau `move` commands  
* **5** stock `deal` commands  
* **174** explicit player decisions  

The user records this same solution as **172 MobilityWare moves** in the app (also stated in `solution_extracted.txt`: “Deal solved in 172 moves.”).

## Impact

| Claim | Status |
|-------|--------|
| Distinct 163-move move file exists | **False** — same 174-command trace |
| Verified MW163 MobilityWare score | **Withdrawn** |
| Beats Solvitaire by 4 | **Withdrawn** (based on defective 163) |
| Project first generated complete solve | **Withdrawn** — only known complete path is user-supplied |
| Optimisation ceilings / incumbents using 163 | **Affected / invalidated for MW comparisons** |

Legal replay (solved, 8 foundations, empty stock) remains valid. Only the **move counter** was defective.

## Root cause

Legacy cost rule in `src/spider/rules.py` (`mw_move_cost`):

```text
cost = 0  if  dest empty AND cards_moved == entire face-up stack
cost = 1  otherwise
deal  = 1
```

That rule does **not** require the source column to be fully emptied. Moving all face-up cards onto an empty column **while face-down cards remain** (a reveal) was incorrectly free.

On the canonical trace there are **11** such “free” events under the legacy rule:

```text
legacy_mw = 174 − 11 = 163
```

Exact free command indices (1-based):  
`29, 43, 46, 47, 51, 69, 79, 99, 129, 142, 150`.

Automatic foundation removals (**8**) do **not** adjust the counter.  
All **5** stock deals cost **1** each under both systems.

### Why 172 (user-observed)

Corrected MobilityWare-emulating rule:

```text
cost = 0  only if dest empty AND entire face-up moved AND source face_down == 0
         (full-column relocate onto empty)
cost = 1  otherwise (including full face-up→empty that still reveals a buried card)
deal  = 1
```

Only **2** free commands under this rule (indices **46** and **142**):

```text
mobilityware_moves = 174 − 2 = 172
```

Discrepancy **163 vs 172 = 9** = the nine legacy-free reveal plays that should have cost 1.

### Why not 174

174 counts every explicit command as 1. MobilityWare does not charge for relocating an entire open column onto an empty column (2 cases on this deal).

## Correction

| Field | Meaning |
|-------|---------|
| `explicit_commands` | 174 on this trace |
| `tableau_moves` | 169 |
| `stock_deals` | 5 |
| `automatic_foundation_removals` | 8 |
| `legacy_mw` | 163 (defective historical) |
| `mobilityware_moves` | **172** (corrected, matches user) |
| `mobilityware_count_verified` | **true** (rule documented + ledger-tested) |

Code:

* `src/spider/rules.py` — corrected default; `legacy_mw_move_cost` preserved for audit  
* `src/spider/engine.py` — passes `source_face_down_count` into cost  
* `src/spider/metrics.py` — multi-counter API; `CANONICAL_MOBILITYWARE_MOVES = 172`

## Authoritative status

* Complete user-supplied solution: `solutions/4925153_canonical.moves`  
* Explicit structure: 169 tableau + 5 deals = 174 commands  
* User-reported and engine-corrected MobilityWare count: **172**  
* Internal value **163** is **legacy_mw only** and must not be cited as a MobilityWare result  

## Follow-up

1. Optimisation may resume using **`mobilityware_moves`**, not `legacy_mw`.  
2. Historical experiment reports that say “MW163 incumbent” are **superseded for scoring**; structural findings may still stand.  
3. Scaffold ladder / milestone numeric MW fields should be regenerated under the corrected counter when next edited.  
4. Do not claim a project-generated improvement over Solvitaire until a **distinct** shorter legal path is verified under `mobilityware_moves`.

## Artefacts

* `src/spider/planner/diagnostics/audit_4925153_move_accounting.py`  
* `src/spider/planner/diagnostics/experiments/4925153_move_accounting_ledger.{csv,json}`  
* `src/spider/planner/diagnostics/experiments/4925153_move_accounting_audit_report.md`  
* `tests/test_4925153_move_accounting_audit.py`  
