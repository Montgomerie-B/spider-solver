# Sprint 1L — ACCESS-Integrated Epoch Planning Through Deal 3

**Branch:** `dev/sprint1l-access-epoch-planner`  
**Baseline:** Sprint 1K @ `f80af23`

## Question

Does the proven 1K ACCESS campaign help as a *single* plan-search macro-edge from opening through Deal 3, compared with the same search without it?

Only ACCESS is integrated. WORKSPACE_EXPLOIT / FOUNDATION_BUILD / STOCK_PREP are not plan edges. No suit is forced.

## API

`search_to_stock_epoch(..., use_access_campaigns=False, access_max_paid_cost=10, ...)`

- `use_access_campaigns=True/False` is the A/B switch.
- Default is **False** so 1G–1I searches stay unchanged.
- `target_deals=3` uses the same epoch-aware loop (depth reset after each deal).

An ACCESS edge carries replay-valid actions, corrected MW cost, fd reduction, focus/fallback history, and the resulting state.

## Explosion control

- At most one ACCESS per epoch unless empty-count or foundations-removed increased.
- After DEAL_NOW, epoch depth and ACCESS allowance reset.
- Budget capped at 15 paid moves; results cached by `(state_key, budget)`.
- Zero-progress ACCESS is cached as unusable and is not a plan edge.

## Quality

Investment paid / fd reduced is recorded on the node as a **diagnostic**, not a dominance or proof key. Pareto + stratified axes are unchanged.

`REMOVE_FOUNDATION` is expandable whenever the 1E generator emits it (after Deal 2 for this benchmark, generically when theoretically available).

## Independent foundation rank (not forced)

At canonical post-D2 the 1A rank is **S#1 then H#1** (theo, rem 59.5 / 21.5). That is diagnostic only. 1L plan edges never include `FOUNDATION_BUILD`. Machine terminals show higher S readiness because that is what the analysis reports, not because an S campaign was selected.

## Tests

`tests/test_access_epoch_planner.py`: macro edge + replay cost, A/B off = atomic search, zero-progress not branched, cache hit on second probe, epoch reset, Deal 3 / no Deal 4, investment survives cheap deal, synthetic ACCESS-before-deal, no other campaign kinds.

## Diagnostic A/B (deal 4925153, reference only)

Runtime **124.6s**. Tiny / medium / larger × OFF/ON. Human: D1 g=51 fd=12; D2 g=89 fd=8; D3 g=101 fd=7 found=1.

Least face-down:

| config | D1 off/on | D2 off/on | D3 off/on |
|---|---|---|---|
| tiny | 42 / **35** | 42 / **35** | 42 / **38** |
| medium | 37 / **30** | 37 / **28** | 37 / **31** |
| larger | 35 / **28** | 36 / **28** | 37 / **30** |

Sprint 1H D2 machine terminals were fd 35–44. ACCESS-ON larger D2 is **fd 28**.

ACCESS efficiency by epoch (larger ON): epoch0 4 macros / +38 / fdΔ38; epoch1 15 / +57 / fdΔ31; epoch2 5 / +28 / fdΔ10.

No machine terminal removed a foundation. No Deal 4.

## Key questions

**A.** Yes. ACCESS before Deal 1 produces better Deal 2 states than Sprint 1H (fd 28 vs 35–44).

**B.** Yes at Deal 2: the fd≈33 wall is avoided (28) because more excavation happened before and just after Deal 1. The best D2 line is not always kept to D3 (beam), so D3 least-fd is 30–31 — still below 33, but slightly worse than the D2 peak.

**C.** Yes, ACCESS is applied between Deal 2 and Deal 3 (larger: 5 macros). Surviving D3 terminals more often end `… DEAL DEAL` than a late ACCESS.

**D.** No. Zero machine-path foundation removals. Human has removed S#1 by pre-D3.

**E.** Not really. Strongest D3 is g=16–20 (vs human 101) but fd=30, empty=0, ssL=5–7, found=0 versus human fd=7 / ssL=10 / found=1. Cheaper, not structurally credible as a substitute.

## Recommendation

Keep ACCESS **on** for Deal 1–3 planning.

**Strengthen the tactical workspace / search layer next** — do not attempt a bounded whole-game solve yet. The remaining gap is empty-column creation and post-D2 foundation realisation, plus beam loss of the best D2 investment line.
