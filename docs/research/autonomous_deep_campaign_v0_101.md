# autonomous_deep_campaign_v0_101

Verdict: `AUTONOMOUS_DEEP_CAMPAIGN_READY`

Incumbent registry: g=186 ceiling=185 moves=solutions/4925153_autonomous_v0_100.moves replay_g=186.

Deepening next rounds from budgets 0/60/300/1800/7200/28800/86400: [1, 2, 3, 4, 5, 6, 7].

Packaged incumbent+v0.100 solution in spider_campaign.spec: True.

Autonomous SMOKE: {'profile': 'SMOKE', 'waves': 2, 'jobs_run': 4, 'f2_generated': 3, 'sd5': 3, 'incumbent_g': 186, 'production_ceiling': 185, 'nodes': 8, 'pending': 0}.

## Registry

`solutions/4925153_incumbent.json` is the current-incumbent source of truth.
`campaign_nodes.verified_incumbent()` no longer infers 186 from a moves filename.
`AUTONOMOUS_INCUMBENT_MW` remains 187 as the frozen v0.74 historical parent
(`V074_AUTONOMOUS_INCUMBENT_MW`). Current campaigns use `spider.incumbent`.

PyInstaller packages the registry plus `4925153_autonomous_v0_100.moves`.
A one-folder install without Git initialises campaigns at 186/185.

## Deepening

Each node advances to the next unattempted round from its own
`deepest_budget_s`. GUI Deepen Selected / Deepen All Unresolved no longer
hardcode Round 2 (5 min).

## Autonomous profiles

SCREEN, DEEP, OVERNIGHT, UNTIL_STOPPED. Start creates g123 if needed,
generates F2 children with full ancestry, applies SD5 in bulk, proof-filters
against the current ceiling, evaluates stock-empty descendants, deepens
unresolved nodes, and can generate more upstream F2s. Timeouts stay
UNRESOLVED_TIME. Promotion writes the registry overlay under
`%LOCALAPPDATA%\SpiderSolver\` so the install dir need not be writable.

## Optiplex

Create Known g123 Campaign (or just Start), choose DEEP or OVERNIGHT, press
Start, leave the machine. Pause/Stop remain job-boundary. New searches use
ceiling 185. Do not treat 60s screens as dead.
