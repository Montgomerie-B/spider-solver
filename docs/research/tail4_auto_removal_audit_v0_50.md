# Spider Solver v0.50 — TAIL4 Auto-Removal Audit

## 1. Verdict

`TAIL4_ACCOUNTING_BUG_CONFIRMED_NO_REAL_FOUNDATION` — the v0.49 join helper would miss a K-A auto-removal, but no v0.49 READY state actually has a K-through-4 receiver.

v0.49's 96 Club "TAIL4_READY_IMMEDIATE" states were **depth-1 children**, not already-READY parents. The helper then tried the 3-2-A → 4 join on the parent, which was not yet READY, so it reported zero joins. Reconstructing those 96 children and executing the join with the corrected classifier yields **visible 4C-3C-2C-AC** every time. The receiving 4C is **4 only**, never K-through-4. Diamond is the same: 125 reconstructed READY joins all persist TAIL4. Foundation 2 was not hidden.

- Branch: `agent/tail4-auto-removal-audit-v0-50`
- Base SHA: `1d8537e28094729dd37f312ade6868dace1e41c2`

v0.49 reports were not rewritten.

## 2. Bug reproduction

Synthetic Club `KC-QC-JC-10C-9C-8C-7C-6C-5C-4C` plus exposed `3C-2C-AC`:

| Check | Result |
|---|---|
| TAIL4_READY before | true |
| Legal 3-2-A → 4 | 1 |
| After engine move | Club foundation +1, KC-AC removed |
| `tail4_present` after | **false** |
| v0.49 `optional_tail4_join` | **None** |
| Corrected classifier | `FOUNDATION_AUTO_REMOVED` |

The accounting defect is real on that structure.

## 3. Club

128/128 v0.49 TAIL3 states replay. None is already TAIL4_READY (4C is never top on the parent).

Reconstructed first TAIL4_READY within 5 ply (v0.49 labelled depth≤1 as IMMEDIATE):

| Status | n |
|---|---|
| TAIL4_READY_IMMEDIATE (depth ≤ 1) | **96** |
| LIVE_BEYOND_5 | 32 |

96 legal 3C-2C-AC → 4C joins:

| Class | n |
|---|---|
| TAIL4_PERSISTS | **96** |
| FOUNDATION_AUTO_REMOVED | 0 |
| CONTRACT_FAILURE | 0 |

Receiving-run below 4C: **4 only × 96**. Never K-through-4. Cheapest Foundation 2: none.

## 4. Diamond

192/192 v0.49 TAIL3 states replay. Immediate READY on the parent: 0.

Reconstructed first TAIL4_READY within 5 ply:

| Status | n |
|---|---|
| TAIL4_READY_IMMEDIATE | 13 |
| TAIL4_READY_WITHIN_5 | 112 |
| LIVE_BEYOND_5 | 67 |

(125 READY children vs v0.49's 64: this run persisted actual children without the 0.25s per-state cutoff.)

125 legal 3D-2D-AD → 4D joins:

| Class | n |
|---|---|
| TAIL4_PERSISTS | **125** |
| FOUNDATION_AUTO_REMOVED | 0 |
| CONTRACT_FAILURE | 0 |

Receiving-run below 4D: **4 only × 125**. Cheapest Foundation 2: none.

## 5. Foundation 2

Reached: **no**. No fixture.

The second v0.49 failure mode: even after reconstructing READY children, the join produces a visible 4-3-2-A because the 4 is isolated. Auto-removal never fires on this frontier.

## 6. Files

- `docs/research/tail4_auto_removal_audit_v0_50.md`
- `docs/research/tail4_auto_removal_audit_v0_50.json`
- `docs/research/club_tail4_transition_v0_50.json`
- `docs/research/club_tail4_ready_v0_50.json`
- `docs/research/diamond_tail4_ready_v0_50.json`
- `docs/research/diamond_tail4_transition_v0_50.json`

No Foundation-2 portfolio. No solution fixture. Future `optional_tail4_join` uses the corrected classifier. Production engine unchanged.

## 7. Exactly one next recommendation

v0.49 TAIL4_READY comparison stands. Next: equal Club/Diamond TAIL4_READY searches from those boundaries, using the corrected join classifier. Do not resume Spades.
