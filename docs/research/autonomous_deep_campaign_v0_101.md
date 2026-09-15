# autonomous_deep_campaign_v0_101

Verdict: `AUTONOMOUS_DEEP_CAMPAIGN_READY`

Branch: `agent/autonomous-deep-campaign-v0-101`
Base: `dcde6bc20ba898c45c37ac102c72e9326f33331d`

## Incumbent registry

`solutions/4925153_incumbent.json` is the current source of truth:

- incumbent **186**
- production ceiling **185**
- moves `solutions/4925153_autonomous_v0_100.moves`
- verified replay true

`campaign_nodes.verified_incumbent()` reads the registry. A local
`%LOCALAPPDATA%\SpiderSolver\incumbent.json` overlay wins only when its g is
**strictly better or equal** (lower g). A stale 187 overlay cannot hide 186.

`AUTONOMOUS_INCUMBENT_MW` remains 187 as frozen v0.74 historical parent
(`V074_AUTONOMOUS_INCUMBENT_MW`). Current campaigns use `spider.incumbent`.
Historical reports were not rewritten.

## Packaging

`spider_campaign.spec` includes the registry and v0.100 moves/json.
Frozen lookup uses `repo_root()` (`sys._MEIPASS`). Packaged-app test copies
those artefacts into a fake install tree and replays g=186 without Git.

## Generation

Generation is a first-class deepenable operation with `generation_runs`:
target suit, time/unique budgets, n_raw, n_unique, n_new, n_duplicate,
cheapest g, stop reason, elapsed. Timeout is `GENERATION_UNRESOLVED_TIME`,
not exhausted. Longer generation from the same parent adds only new children.

## Bulk SD5

All eligible PRE_STOCK F2s (stock_rows=1) get exact SD5 as an explicit graph
edge. Deal count becomes 5. Post-stock dedup uses whole-game identity.
Cheapest g is the search representative; other ancestries stay as
`alternate_ancestries`.

## Dedup / convergence

Same identity at same/worse g **reuses** the existing node and adds a parent
edge. Lower g is `LOWER_G_REOPENING` in place (searchable, not a second
redundant node). Pre-stock: ordered digest. Stock-empty: whole-game identity.

## Progressive rounds

60s / 5m / 30m / 2h / 8h / 24h / **REPEAT 24H** (honest 24h jobs).
Not a fake 7-day UNTIL STOPPED.

## Autopilot: G123_DIAMOND_DEEP

Persisted operations: GENERATE, TRANSITION_SD5, FILTER, EVALUATE, DEEPEN.

Production plan: G1 180s Diamond harvest (unique 250k, ~279 F2 reference) ->
T1 bulk SD5 -> F1 proof-filter 185 (`PROOF_DEAD_185`) -> D1 5m all live ->
G2 30m generation (new F2s only) -> T2/F2 -> D1b 5m new live -> D2 30m ->
D3 2h -> D4 8h -> D5 24h -> D6 REPEAT 24H until Stop/SOLVED/EXHAUSTED/PROOF_DEAD/KNOWN_CLOSED.

Build smoke: GENERATE 4s -> SD5 -> FILTER -> EVALUATE 1.5s -> DEEPEN 1.5s.
Smoke F2 count may be 0 on a 4s harvest; unit tests cover generation/SD5/dedup.

## Crash / restart

RUNNING operations are recovered to pending on the next Start. Completed ops
are not reapplied. Generation reuse and SD5 skip-existing prevent duplicate
scientific states. Atomic `campaign.json` save at each operation boundary.
A reboot costs at most the active operation. TT is never persisted.

## GUI

Start Autopilot / Resume Autopilot / Pause After Current Operation / Stop.
Default profile G123_DIAMOND_DEEP. Status line: incumbent, ceiling, autopilot
state, current op, F2/post-SD5/live/dead/unresolved/solved/hours.

## Optiplex launch

1. Rebuild one-folder app (`scripts/build_spider_app.ps1`).
2. Recalibrate if hardware mismatches.
3. Create Known g123 Campaign (or just Start Autopilot).
4. Profile **G123_DIAMOND_DEEP**.
5. Start Autopilot. Leave the machine.
6. Pause After Current Operation / Stop as needed.
7. New searches use ceiling 185. 60s timeouts are UNRESOLVED, not dead.
