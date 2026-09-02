# Post-conversion lane handoff audit

**Branch:** `agent/post-conversion-lane-handoff-audit`  
**Base:** whole-deal scheduler v0.4 @ `92e6278`  
**Production sequencing is unchanged. No v0.5 implementation.**

## Verdict

Primary boundary: **B — converted lane is assessed, then loses the lead
on fresh cash-out ordering.**

No representative is justified. There is no proven post-TT starvation of a
correct same-lane maturation successor.

## Lineages

| Lineage | What was scanned | Integrated conversions rebuilt |
|---|---|---|
| Opening path to cost-21 | existing 5-expansion / 40s anchor | **8** continuous-path consume/integrate events, including Deal-1 `Js`, `9s`, **`7d`** |
| Gate Z / X from cost-21 | existing 25-expansion / 90s envelope | telemetry: 5 selected/integrated; **none** lie on retained summary-node paths, so their child schedules were not rebuilt (no branch splicing) |
| Gate Y / AA from opening | existing 50-expansion / 180s envelope | selected endpoint **never Deals** (stock 50); no extra E0→E1 child |

The natural `7d` conversion is present on the opening-anchor Deal-1
sequence (`7d` onto column 8, `CONSUME_NOW`).

## Post-conversion tables (continuous opening path)

### 1–2. `Js` col 1 — class E (was tagged G only by next-action presence)

Spades **remain lead** (`MERGE_READY`). Maturation objective
`CONSUME_BRIDGE_CARD` is generated and occupies the four-slot portfolio.
Legal one-step evidence exists. No maturation trace is tagged with this
arrival id, so there is no TT-admitted successor to starve.

Fragment join: 7 spade fragments → 6, then 6 → 5.

### 3. `9s` col 7 — class B

After the join, the affected spade lane is `FUTURE_GATED` and loses to
clubs `MERGE_READY`. Fresh economics, not a lost semantic identity.

### 4. `7d` col 8 — class B (the requested E0→E1 diamond conversion)

Physical join happens (`7d`+`6d`). Cash-out **worsens**:

| | future | gap | blocker | workspace | rehandling | fragment_merges |
|---|---:|---:|---:|---:|---:|---:|
| before | 4 | 12 | 5 | 0 | 0 | 3 |
| after | 4 | 12 | 5 | **1** | **5** | 2 |

Lead becomes clubs `MERGE_READY`. No diamond maturation objective is
emitted because only the lead gets one. This is the designed one-slot
compression following a lost lead, not four-slot overflow (not D).

### 5–6. `10d` / `Jd` — class B

Same pattern: diamond join, then `FUTURE_GATED` with worse rehandling,
spades `MERGE_READY` keep the lead.

### 7. `7s` col 4 — class B (duplicate-lane)

Converted spade fingerprint loses to a **different** spade lane that is
also `MERGE_READY` with a better cash-out key `(0,12,…)` vs `(1,2,…)`.
Lane ordinals are not identities; fingerprints differ. A maturation
objective for the converted fingerprint exists but is not the lead slot.

### 8. `As` col 2 — class E

Converted spades become **`TERMINAL_READY` and lead**. Objective
`PREPARE_TERMINAL_SEQUENCE` is in the four-slot portfolio and a legal
successor exists. The next path move is untagged; no TT-admitted
maturation successor is recorded.

## Lead / objective / successor summary

| # | arrival | converted lead? | maturation obj | in 4-slot | legal 1-step | TT / selected / expanded |
|---|---|---|---|---|---|---|
| 1 | Js | yes | CONSUME_BRIDGE | yes | yes | no / no / no |
| 2 | Js | yes | CONSUME_BRIDGE | yes | yes | no / no / no |
| 3 | 9s | **no** (clubs) | no | — | no | — |
| 4 | **7d** | **no** (clubs) | no | — | no | — |
| 5 | 10d | **no** (spades) | no | — | no | — |
| 6 | Jd | **no** (spades) | no | — | no | — |
| 7 | 7s | **no** (other spade lane) | yes, not lead | no | yes | — |
| 8 | As | yes, TERMINAL_READY | PREPARE_TERMINAL | yes | yes | no / no / no |

## Class counts

| A | B | C | D | E | F | G | H |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 0 | 0 | 3 | 0 | 0 | 0 |

No class A remapping. No class D four-slot eviction of a lead objective.
No class F/G post-TT starvation.

## Primary boundary

**B.** After a real physical join, the converted semantic lane often
ceases to be the current-state lead. Only the lead may emit the single
maturation objective, so same-lane maturation cannot start.

On the 7d/diamond events the cash-out key moves **against** the converted
lane (rehandling/workspace rise) even though fragments joined. That may
be honest debt or a measurement artifact; v0.5 should inspect that
estimator, not add coverage.

The three class-E events show the opposite: the converted lane **does**
win the lead and **does** get a portfolio objective with a legal one-step,
but expansion never tags/emits that successor as a maturation child of
the conversion. That is a handoff/generation gap, still not post-TT
starvation.

## Representative

**NO.** Zero TT-admitted same-lane maturation successors were later
starved by the frontier.

## Smallest recommended v0.5 correction (not implemented)

1. After an integrated conversion, compare the *matched converted
   fingerprint* to the fresh lead. If it loses, record the cash-out
   delta (especially rehandling/workspace immediately after a join) so
   the estimator can be checked.
2. If it wins, map the already-legal one-step (`actionable_merges` /
   bridge) onto the existing maturation objective so expansion actually
   emits that successor. Keep one-slot compression and no sunk cost.

Do not add a representative, persistence, bonus, or extra search.
