# hierarchical_deep_campaign_v0_100

Verdict: `HIERARCHICAL_CAMPAIGN_186_VERIFIED`

Branch: `agent/hierarchical-deep-campaign-v0-100`
Base: `1a5a765ced06a01fdfa3ceb7f29659b6800e1c80`

## 186 recovery

- winner A recovered: `True`
- winner B recovered: `True`
- verified winner: `WINNER_A`
- harvest: `{'elapsed_s': 180.0003422000009, 'unique': 32041, 'expanded': 10220, 'generated': 92552, 'stop_reason': 'time limit', 'n_f2': 279, 'n_unique': 279, 'cheapest_g': 128}`
- g123: `{'ok': True, 'g': 123, 'foundations': 1, 'face_down': 2, 'stock_rows': 1, 'digest_ok': True, 'n_deal': 4, 'n_prefix': 127}`
- full replay g: `186`
- deals: `5`
- foundations: `8`
- solved: `True`
- incumbent before/after: 187 / `186`
- production ceiling before/after: 186 / `185`

## Architecture smoke

- opening root g=0 empty actions: `0 []`
- opening children: `12`
- g123 verified: `True g=123 deals=4`
- F2 children: `22`
- SD5 child: `STOCK_EMPTY`
- graph export/import: `True`
- timeout classification: `UNRESOLVED_TIME`

Timeout is UNRESOLVED_TIME, never PROOF_DEAD.

## Campaign-node design

A node stores: UUID, parent_ids, child_ids, deal ID, rules profile, ordered digest,
physical identity, absolute g, F, face-down, stock rows, deal count, full_actions
from the untouched opening, action count, ancestry_verified, source, timestamps,
solver SHA/version, status, run history, best consequence, proof metadata.

Kinds: OPENING, EPOCH, CHECKPOINT, PRE_STOCK, STOCK_EMPTY, SOLVED.

Graph not tree: parent/child edges. Same identity at lower g is LOWER_G_REOPENING;
both ancestries are retained. Pre-stock identity is ordered digest; stock-empty
uses pack_whole_game_identity. full_actions are never discarded.

Dispatch: STOCK_EMPTY -> run_stockempty_consequence; g123/PRE_STOCK -> harvest_f2_target;
OPENING/EPOCH -> search_epoch_portfolio; SD5 is an explicit child.

Progressive stages: 60s, 5m, 30m, 2h, 8h, 24h, UNTIL STOPPED.

Timeout => UNRESOLVED_TIME (with the actual budget). Never PROOF_DEAD.

Portability: nodes/edges/runs live in campaign.json and survive export/import.
Hardware profile remains machine-local.

GUI: Treeview hierarchy plus Create Opening / Create Known g123 / Generate Children /
Evaluate / Deepen Selected / Deepen All Unresolved / Step to Parent / Open Root/Node.
AUTO resources retained. Pause remains a job-boundary cooperative stop.

Acceptance-script repair: v0.99 script now calls a real test name and is ASCII-safe
for Windows PowerShell 5.1. v0.100 script added.

## Optiplex next campaign

On the Dell Optiplex: Create Known g123 Campaign, Generate Children (diamonds),
exact SD5, then Deepen All Unresolved with Round 2+ budgets. Do not treat
Round-1 60s timeouts as dead states. New production searches use ceiling 185.
Historical 186-ceiling runs remain valid evidence and must not be deleted.
