# Spider Solver v0.47 — Spade 4S Final Access Transaction

## 1. Verdict

`SPADE_FINAL_ACCESS_STATE_EXPLOSION` — unique/RSS limit before a useful Gate1/Gate2 boundary

unique/RSS limit before a useful Gate1/Gate2 boundary. Sources 128 B4=2 cover 10D,5S. Fast-path 2->1=0 1->0=0 MW91=0. Gate1 n=0 cheap=None. Gate2 n=0 cheap=None. Exposed n=0 cheap=None. No TAIL4. No Foundation 2.

- Branch: `agent/spade-5s-10d-release-v0-47`
- Base SHA: `341895b38ea49f0b517d976c0865a9e50c07413f`

## 2. Source audit

- Loaded **128** v0.46 B4=2 states (expected 128).
- Replay OK: **True**. Order OK: **True**.
- Symmetry-unique: **128**.
- MW: `{'89': 16, '90': 112}`. Timing: `{'DEAL_NOW': 64, 'PREP_THEN_DEAL': 64}`.
- Cover is universally `['10D', '5S']` with top **5S** (engine face_up last element).
- 10D+5S movable together: **0**.
- Immediate 5S dests / rank-6 / empty / Jack: 0 / 0 / 0 / 0.
- Categories: `{'BOTH_GATES_BLOCKED': 128}`.

Hard retained-frontier lower bound to exposure is **source_g + 2 = 91**.

## 3. Fast path

- Legal 2→1 (5S) moves: **0**.
- Immediate 1→0 continuations: **0**.
- MW91 witnesses: **0**. Cheapest two-move: **None**.

## 4. Gate 1 (5S release, B4=1)

- Reached: **False**. First hit t=None unique=None g=None.
- Cheapest: **None**. Boundary n=0 bands `{}`.
- Gate2 capability: `{}`.
- Dominant 5S landing: `{}`. Stop: unique limit.

## 5. Gate 2 (10D release, B4=0)

- Reached: **False**. First hit t=None unique=None g=None.
- Cheapest: **None**. Dominant 10D landing: `{}`.
- Stop: skipped.

## 6. Exposure

- Reached: **False**. n=0. Cheapest full MW: **None**.
- Hard LB91 matched: **False**. Fast-path: **False**.

## 7. Resources

- Elapsed: 213.7s. Peak RSS: 161.84375 MB.
- Gate1 unique/exp/gen: 180000 / 99734 / 808199.
- Gate2 unique/exp/gen: 0 / 0 / 0.

## 8. Files

- `docs/research/spade_final_access_transaction_v0_47.md`
- `docs/research/spade_final_access_transaction_v0_47.json`
- Gate1: `None`
- Exposure: `None`

No TAIL4 search. No Foundation-2 search. No new Deal. Production unchanged.

## 8b. Bottleneck

Every retained B4=2 state is `BOTH_GATES_BLOCKED`: no exposed 6, no empty, no Jack, so 5S cannot leave in one move and 10D cannot leave in the next. Gate1 then generated 180,000 unique descendants without a first B4=1 crossing. The controlling obligation is therefore creating a rank-6 or empty landing for 5S, not moving 5S itself and not rebuilding TAIL4.

## 9. Exactly one next recommendation

Gate1 hit 180k unique with no B4=1. From the cheapest 16 MW89 B4=2 sources, excavate an exposed rank-6 or empty as an explicit 5S-landing project. Do not flood UCS and do not search TAIL4.

