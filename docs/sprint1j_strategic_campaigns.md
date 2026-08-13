# Sprint 1J — Strategic Campaigns / Productive Investment

**Branch:** `dev/sprint1j-strategic-campaigns`  
**Baseline:** Sprint 1I @ `879cda3`

## Question

Can a generic campaign layer — reanalyse, realise one cheap sub-objective, repeat — turn atomic 1E/1F objectives into sustained intra-epoch investment?

Deal 3 is never taken. No suit, column, move-number, or fd-threshold constants in generic code.

## API

`src/spider/planner/strategic_campaigns.py`

- `CampaignKind`: `ACCESS`, `WORKSPACE_EXPLOIT`, `FOUNDATION_BUILD`, `STOCK_PREP`
- `StrategicCampaign`
- `generate_campaigns(state, analysis=...)` from `StrategicAnalysis`
- `campaign_subobjectives(...)` filters the 1E portfolio (`DEAL_NOW` excluded)

`src/spider/planner/campaign_realizer.py`

- `CampaignStep`, `CampaignResult`, `CampaignFrontier`
- `realize_campaign` — analyse → cheap 1F realise → reanalyse
- `run_campaign_frontier` — independent campaigns from one start; Pareto + stratified
- `prefix_at_budget`, `pareto_campaign_results`, `stratify_campaign_results`

Workspace creation alone is not success. Consuming an empty after a reveal/join still counts as productive (heuristic).

Miss / resource-limit ≠ impossible.

## Selection / execution

Generated from current analysis, not a scripted route:

- **ACCESS** — top 1B reveal columns; only shallow `EXPOSE_REVEAL_PREFIX` (`required_reveals ≤ 2`) plus optional workspace
- **WORKSPACE_EXPLOIT** — create if empty=0, then expose / consolidate / advance
- **FOUNDATION_BUILD** — top 1A frontier candidates by removal-if-theoretical, then build readiness; no hard-coded suit
- **STOCK_PREP** — `SHAPE_STOCK_RECEIVER` plus workspace

Diversity: one of each kind first, then priority.

Execution never deals. Every accepted step is independently replayed; the full action list is replayed from the start state.

## Tests

`tests/test_strategic_campaigns.py` — 12 tests:

- no benchmark / deal-3 constants
- repeated shallow reveals excavate a deeper synthetic chain
- workspace then productive use
- replay cost matches
- budget / plateau / resource stop
- generic foundation suit
- never deals (stock length unchanged)
- reanalyse after every sub-objective
- frontier has no deal; Pareto + stratified
- resource-limit is not impossible
- workspace-create-alone is not success

## Diagnostic (deal 4925153, reference only)

Runtime **51.8s** total. Seed searches + campaign realisations. No Deal 3.

Human snapshots:

| epoch | g | fd | e | ssL | mass |
|---|---|---|---|---|---|
| initial | 0 | 44 | 0 | 0 | 0 |
| pre-D1 | 50 | 12 | 0 | 10 | 30 |
| post-D1 | 51 | 12 | 0 | 10 | 31 |
| post-D2 | 89 | 8 | 0 | 12 | 51 |

### Opening +5 / +10 / +20

Campaign mix: ACCESS, WORKSPACE_EXPLOIT, FOUNDATION_BUILD, STOCK_PREP.

| campaign | +5 | +10 / +20 | notes |
|---|---|---|---|
| access_c6 | 0 / fd 44 | 0 / fd 44 | highest 1B column not cheaply realisable |
| workspace_exploit | +4 / fd 40 / ss 5 | +6 / fd 38 / ss 5 | exposes + advance; never created empty |
| foundation_h1 | +5 / fd 39 / ss 3 | +10 / fd 34 / ss 3 / mass 11 | **7 sequential shallow exposes** |
| stock_prep | 0 | 0 | no cheap receiver shape |

+20 did not extend past +10: the sequential expose chain plateaued after seven steps. Extra budget was not extra progress.

Best opening investment: **fd 44→34 in 10 paid moves** (eff = 1.0 fd/move).

### vs human pre-D1

Human spent **50** to reach **fd 12 / ssL 10 / mass 30**.

Machine best at the same epoch (no deal): **+10, fd 34, ssL 3**. Cheaper and more efficient per move than Sprint 1G/1H one-shot terminals (those stayed fd 37–44), but **not a better investment curve** in the human sense: 10 reveals vs the human's 32, and no long same-suit spine.

### Post-D1 machine seeds

| seed | g | start fd | best campaign | end fd | Δ | paid |
|---|---|---|---|---|---|---|
| 0 deal-first | 1 | 44 | all plateau | 44 | 0 | 0 |
| 1 invested | 7 | 38 | workspace / S#1 | 36 | 2 | 4 |
| 2 invested | 5 | 40 | S#1 / workspace | 36 | 4 | 7–8 |

Deal-first is still dead. Invested D1 seeds continue a little (sequential exposes, one workspace+consolidate).

### Post-D2 machine +5 / +10 / +20

| seed | g | start fd | +5 | +10/+20 best | plateau <33? |
|---|---|---|---|---|---|
| 0 deal-first×2 | 2 | 44 | 44 | 44 | no |
| 1 | 12 | 36 | 36 | 36 | no |
| 2 | 13 | 36 | 36 | **33** (+6, empty 1) | **no** (touches 33) |
| 3 | 9 | 39 | 39 | 39 | no |

**The Sprint 1I fd≈33 plateau was not broken.** Larger budget did not keep making structural progress. Seed 2's +6 workspace create is the same class of one-shot improvement 1I already found.

### Human post-D2 (reference)

Generic selector **does independently favour S#1**:

- S#1 theo=yes epoch=2 build=80 rem=59.5 frag=12
- H#1 theo=yes epoch=2 build=57 rem=21.5 frag=8

`foundation_s1` then **removed a foundation at +2** (`REMOVE_FOUNDATION` + `CREATE_WORKSPACE`). That is only possible because the human already assembled the suit. No machine seed removed a foundation.

### Workspace productive-use examples

- Synthetic: `CREATE_WORKSPACE` then two sequential exposes, fd 2→0.
- Post-D1 seed 2: expose → consolidate → create empty; fd 40→36, mass 5→12, empty 0→1.
- Post-D2 seed 2: create empty then two consolidations; fd 36→33, mass 9→15, empty consumed (still productive under the corrected heuristic).

### Foundation removals

- Machine seeds: **none**
- Human post-D2 campaign: **one** (S#1), cost 2

### Unrelated fixture

ACCESS excavated the two-card synthetic chain (fd 2→0). No deal.

## Runtime / nodes

~52s end-to-end. Opening campaigns 3.5s / 4559 nodes. D1 seed search 2.7s. D2 seed search 19.1s. Individual campaigns typically 0.2–1.8s and a few hundred to ~2k tactical nodes.

## Concerns

1. ACCESS often locks onto the highest-1B column, fails the cheap bound, and does nothing — while a *different* campaign (foundation-labelled sequential exposes) excavates well.
2. `FOUNDATION_BUILD` at the opening degenerates to generic shallow exposes because no suit-specific objective is ready.
3. Cheap deal-first seeds remain unrecoverable by campaigns.
4. Extra budget after the first 1–3 successful steps usually plateaus — same qualitative failure as 1I.
5. Campaigns do not invent destinations that 1F cannot already realise cheaply.

## Recommendation

**Revise the campaign layer before integrating it into Deal 1–3 planning.**

Keep the reanalyse loop — it is the first component that produces *sequential* excavation (opening Δ10 vs 1G/1H one-shots). Before using it as the intra-epoch policy:

- ACCESS should fall through to the next 1B column when the focus column is resource-limited
- do not spend a diversity slot on a 0-progress campaign
- FOUNDATION_BUILD should stay on suit-relevant material once a candidate is chosen
- do not expect campaigns to repay a deal-first opening

Integrating as-is would mostly relabel Sprint 1I behaviour.
