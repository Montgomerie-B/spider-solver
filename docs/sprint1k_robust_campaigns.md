# Sprint 1K — Robust / Actionability-Aware Campaigns

**Branch:** `dev/sprint1k-robust-campaigns`  
**Baseline:** Sprint 1J @ `3b85575`

## Question

Can ACCESS fall through blocked 1B columns, and can campaign kinds keep their meaning, without turning FOUNDATION_BUILD back into generic excavation?

Deal 3 is never taken. No suit, column, route, or fd-threshold constants in generic code.

## ACCESS fallback / actionability

At every step the campaign:

1. reanalyses;
2. ranks shallow reveal objectives from several columns by 1B interest (shallowness is a tie-break, not the score);
3. probes each with a small bounded 1F realisation;
4. on miss/resource-limit, caches `(state, objective)` and the objective id until workspace changes;
5. executes the first FOUND result;
6. reanalyses and may change focus.

A resource limit on one column does **not** stall the campaign. Probe failure is not proof pruning.

## Semantic fixes

| Kind | 1J failure | 1K rule |
|---|---|---|
| ACCESS | locked on top 1B column | multi-column ranked fallback; success requires fd reduction |
| WORKSPACE_EXPLOIT | became generic reveals | create first if empty=0; else exploit; no create → stop, do not excavate |
| FOUNDATION_BUILD | opening H#1 was generic ACCESS | emit only if theo / fragment≥2 / removal>0; accept only suit-relevant objectives |
| STOCK_PREP | empty slot | shape receivers only; zero-progress is allowed |

Zero-progress results stay in diagnostics as `zero_progress` / `blocked`. Pareto and stratified fronts use **productive** results only.

Stop reasons: `budget`, `plateau`, `all_candidates_blocked`, `resource_limit`, `no_relevant_subobjective`, `success`.

## Tests

`tests/test_strategic_campaigns.py` — 24 tests (12 inherited + 12 new 1K).

## Opening +5 / +10 / +20 / +30

No FOUNDATION_BUILD generated (the 1J H#1 label is gone).

| Campaign | +5 | +10 | +20 / +30 | notes |
|---|---|---|---|---|
| **access** | +5 / fd 39 / ss 3 | +10 / fd 34 / ss 3 | **+12 / fd 32 / ss 5 / mass 9** | 10 exposes, 5 fallbacks, 7 focus changes |
| workspace_exploit | 0 | 0 | 0 | cannot create empty; correctly **not** a reveal campaign |
| stock_prep | 0 | 0 | 0 | blocked; excluded from productive frontier |

Focus history: columns 1, 3, 7, 9, 3, 10, 6, 7 (0-based: 0,2,6,8,2,9,5,6).

+30 did not beat +12. The chain plateaued after ten cheap exposes.

### Old opening fd=34 plateau

**Broken, modestly.** 1J stopped at seven steps / fd 34. 1K ACCESS continues to **fd 32** (+12, ten steps) by falling through blocked columns.

### vs human pre-D1

Human: **g=50, fd=12, ssL=10, mass=30**.  
Machine best: **+12, fd=32, ssL=5, mass=9**.

Still far from the human curve. Efficiency is 1.0 fd/move on the first 12, then the cheap frontier is empty.

## Post-D1 (invested seeds)

| Seed | g | start fd | ACCESS | notes |
|---|---|---|---|---|
| 0 deal-first | 1 | 44 | +5 / fd 42 (Δ2) | 1J was Δ0 — fallback now finds *some* work |
| 1 invested | 7 | 38 | **+13 / fd 29 (Δ9)** | 7 exposes, 6 focus changes |
| 2 invested | 5 | 40 | +6 / fd 36 (Δ4); S#1 +9 / fd 35 | better than 1J's Δ2–4 |

Fallback ACCESS continues excavation on invested D1 seeds. Workspace still usually cannot be created.

## Post-D2

| Seed | g | start fd | best | <33? |
|---|---|---|---|---|
| 0 deal-first×2 | 2 | 44 | fd 41 (Δ3) | no |
| 1 | 12 | 36 | fd 36 (Δ0) | no |
| 2 | 13 | 36 | **fd 33** (workspace +10) | no |
| 3 | 9 | 39 | fd 38 (Δ1) | no |

**The fd≈33 plateau was not broken.** Extra budget still does not keep paying structural progress.

Human post-D2: ACCESS +7 fd 8→6; S#1 removes a foundation at +3.

## Foundation post-D2

Generic selector **still independently favours S#1** (theo, rem 59.5 / build 80 vs H#1 rem 21.5 / build 57).

Accepted S#1 steps on the human state: `remove_s_1` then a suit-filtered expose. Diagnostic flag `all_found_steps_suit_relevant=True`.

Machine S#1 steps are exposes of columns that contain buried spades (next card may be another suit). That is the current relevance rule; it is looser than “next card is the focus suit”.

Machine seeds: **no foundation removals**. Human post-D2 campaign: **one** (S#1).

## Workspace productive use

- Opening: correctly refused to excavate without an empty.
- Post-D2 seed 2: `CREATE_WORKSPACE` then two consolidations; fd 36→33, mass 9→15, empty consumed.
- Synthetic: create empty, two sequential exposes, fd 2→0.

## Unrelated fixture

ACCESS excavated the two-card chain (fd 2→0) and then created workspace. STOCK_PREP stayed zero-progress. No deal.

## Runtime / nodes

**52.8s** end-to-end. Opening ACCESS 1.4s / 1191 nodes. D1 search 2.7s. D2 search 19.1s.

## Concerns

1. After the first 10–13 cheap exposes, extra budget still plateaus.
2. CREATE_WORKSPACE remains resource-limited from the true opening and most machine seeds.
3. Suit-relevant expose = “column contains a buried focus-suit card”, so a clubs jack can be accepted on an S#1 campaign.
4. Deal-first seeds improve slightly (Δ3) but stay structurally weak.
5. Post-D2 fd 33 is unchanged.

## Recommendation

**Integrate ACCESS fallback into Deal 1–3 intra-epoch planning as the excavation operator.** It is the first policy that continues past a blocked 1B column and past the 1J seven-step / fd 34 stop.

**Do not treat the full campaign mix as a Deal 1–3 planner yet.** WORKSPACE_EXPLOIT and FOUNDATION_BUILD still cannot create opening space or break the post-D2 fd 33 wall. Those need a stronger tactical/search layer, not another relabel.
