# Move Accounting Forensic Audit — Deal 4925153

## A. Executive finding

- **Is 163 a real distinct solution?** **No.**
- **Is the alleged 163 file different from the original?** **No** — same 174-command trace.
- **Actual complete trace:** `solutions/4925153_canonical.moves` (169 tableau + 5 deals).
- **User-observed MobilityWare:** **172**.
- **Legacy engine total:** **163** (withdrawn as MobilityWare).
- **Corrected mobilityware_moves:** **172**.
- **Verified:** yes — rule reproduces 172.

## B. File provenance

- `C:/Users/Codex/Documents/Grok Build/spider-solver-opt011a/deals/4925153.txt`: size=339 sha256=`c0b70979b3e6b90e…` move=0 deal=0 explicit=0 identical_to_canonical=False
- `C:/Users/Codex/Documents/Grok Build/spider-solver-opt011a/solutions/4925153_canonical.moves`: size=8497 sha256=`2b4676e804e4cb2f…` move=169 deal=5 explicit=174 identical_to_canonical=True
- `C:\Users\Codex\Documents\Grok Build\spider-solver-opt011a\solutions\4925153_canonical.moves.txt`: missing
- `C:\Users\Codex\Documents\Grok Build\spider-solver-opt011a\4925153.txt`: missing
- `\mnt\data\4925153.txt`: missing
- `\mnt\data\4925153_canonical.moves.txt`: missing
- `\mnt\data\4925153_163_move_solution.txt`: missing

## C. Counting taxonomy

| Counter | Definition |
|---|---|
| explicit_commands | every replay line (move+deal) |
| tableau_moves | tableau-to-tableau only |
| stock_deals | stock deals |
| automatic_foundation_removals | auto K→A removals |
| engine_actions | player command + auto removals |
| legacy_mw | defective full-face-up→empty free cost |
| mobilityware_moves | corrected UI count |

## D. Replay ledger summary

```json
{
  "explicit_commands": 174,
  "tableau_moves": 169,
  "stock_deals": 5,
  "automatic_foundation_removals": 8,
  "engine_actions": 182,
  "legacy_mw": 163,
  "mobilityware_moves": 172
}
```
- solved=True foundations=8 stock=0
- first legacy vs mobilityware divergence at command **29**

## E. Root cause of 163

- Legacy free moves (full face-up→empty, **ignoring** face-down): **11**
- Indices: [29, 43, 46, 47, 51, 69, 79, 99, 129, 142, 150]
- Arithmetic: `174 − 11 = 163`
- Code: `rules.mw_move_cost` + `engine.SpiderState.move` + `metrics.replay_actions`
- Auto-removals (**8**): **do not** alter MW
- Stock deals (5): each +1 in both systems

### Discrepancy vs user 172

- Legacy 163 vs user 172 = **9**
- Those 9 are legacy-free moves that still leave face-down cards (reveal plays), incorrectly treated as free: [29, 43, 47, 51, 69, 79, 99, 129, 150]
- Corrected free moves (full column empty, fd=0): **2** → `174−2=172`

## F. Reconciliation

| Source | Total |
|---|---:|
| explicit_commands | 174 |
| user-observed MobilityWare | 172 |
| legacy_mw (engine) | 163 |
| mobilityware_moves (corrected) | 172 |

## G. Corrected implementation

- `src/spider/rules.py`: `mobilityware_move_cost`; zero-cost only if empty dest **and** entire face-up moved **and** source face_down==0
- `src/spider/engine.py`: pass face_down into cost
- `src/spider/metrics.py`: expose multi-counter summary; rename CANONICAL claim
- `legacy_mw` preserved as named defective field for historical comparison

## H. Milestone corrections

| Milestone | old MW | mobilityware_moves | legacy_mw | Δ old→corrected |
|---|---:|---:|---:|---:|
| D1 | 84 | 90 | 84 | 6 |
| H20 | 131 | 139 | 131 | 8 |
| I1 | 141 | 150 | 141 | 9 |
| J8 | 149 | 158 | 149 | 9 |
| J11 | 152 | 161 | 152 | 9 |
| J17 | 158 | 167 | 158 | 9 |
| J22_solved | 163 | 172 | 163 | 9 |

## I. Experiment impact

- **canonical_replay_legality**: unaffected — legality/solved independent of cost
- **Opt007/008/009/010 MW ceilings**: invalidated — ceilings and incumbent used legacy MW=163
- **Exp001-006A structure**: numerically_affected — used MW for reporting; structural conclusions may stand
- **beats Solvitaire 167**: invalidated — based on withdrawn 163 claim
- **scaffold ladder MW fields**: requires_rerun — milestone MW values need regeneration under corrected counter

## J. Documentation corrections

- See `docs/4925153_move_accounting_incident.md`
- Withdrawn: verified 163 solution; four better than Solvitaire; MW163 incumbent

## K. Authoritative status

**Choice 1:** Corrected engine reproduces the externally observed MobilityWare 172 count with a fully documented rule.

## L. Recommendation

**Choice 1:** Accounting fixed and verified; optimisation may resume using the corrected mobilityware_moves counter (not legacy_mw).

## Policy

- No optimisation run during this audit
- Canonical move file not overwritten
- 163 is not a verified MobilityWare result for this trace
