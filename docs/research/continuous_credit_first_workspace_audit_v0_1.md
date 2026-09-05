# Continuous-credit first-workspace audit v0.1

**Status:** complete. One continuous production v0.8 search. No resource
planner, no restart forest, no production source changes.

**Start SHA:** `e7342067e22696600ec92696a3b325f26849d8b0`

**Branch:** `agent/continuous-credit-first-workspace-audit-v0-1`

**Decision: A. PRODUCTION NATURALLY REACHES WORKSPACE GEOMETRY**

Within one continuous 400-expansion run, production generated and
**retained** fully-revealed-column (R2) and empty-creatable (R3) children.
The first such successor is an unchanged CLEAN `ECONOMIC_PROJECT` /
`run_construction` move at expansion 116. Opening-path replay matches.

Those R2/R3 children were **not expanded** in the remaining 284 expansions.
No idle empty (R4) and no foundation (R5) appeared.

Credit 1 was pushed on every expansion and **never popped**. Frontier trim
then discarded almost all widened nodes (100 live credit-1 at expansion 100
→ 1 at expansion 400). That is real credit starvation, but it is not what
created the first R2/R3: those arrived at credit 0.

Recommended next step (not taken here):

> Offline resource-planner shadow on the harvested continuous-run R2/R3
> geometry.

## Gate 1 — calibration

25-expansion observer run reproduced the known control exactly:

25 expansions, all credit 0; live 33×c0 + 25×c1; 25 widened pushes; 0
widened pops; expansion-limit stop; generated 65; retained 57; TT new 58 /
suppressed 8; kinds CLOSURE 3 / ECONOMIC 29 / RAW_DEAL 25.

## Long run

| knob | value |
| --- | --- |
| expansions | 400 |
| tactical nodes | 300_000 (used 1049) |
| wall clock | 900s (used 499s) |
| stop | `strategic expansion limit` |

## Milestones (same search)

| n | expanded c0–c4 | live c0/c1 | widened live | frontier | min fd | min col fd | max revealed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | 25/0/0/0/0 | 33/25 | 25 | 58 | 43 | 3 | 0 |
| 50 | 50/0/0/0/0 | 65/50 | 50 | 115 | 43 | 3 | 0 |
| 100 | 100/0/0/0/0 | 129/100 | 100 | 229 | 40 | 2 | 0 |
| 200 | 200/0/0/0/0 | 251/5 | 5 | 256 | 37 | 0 | 1 |
| 400 | 400/0/0/0/0 | 255/1 | 1 | 256 | 37 | 0 | 1 |

TT totals at end: new 915, improved 0, suppressed 191. (During-search
`telemetry.tt_new` is only copied from the TT object at process end.)

## Credit ladder

| event | c0 | c1 | c2 | c3 | c4 |
| --- | --- | --- | --- | --- | --- |
| first push (expansion) | 0 | 1 | never | never | never |
| first pop | 0 | never | never | never | never |
| first expand | 1 | never | never | never | never |

Widened: pushed 400, popped 0, expanded 0, live 1.

Best live credit-1 node is **rank 256 of 256**, with 255 CLEAN nodes ahead.
`max_frontier_size` 256 trims the credit-1 copies away.

## Geometry lifecycle

| flag | generated | retained | expanded |
| --- | ---: | ---: | ---: |
| R1 reveal | 20 | 20 | 9 |
| R2 fully revealed column | 4 | 4 | 0 |
| R3 empty-creatable | 1 | 1 | 0 |
| R4 idle empty | 0 | 0 | 0 |
| R5 foundation | 0 | 0 | 0 |

All of the above at **credit 0**. Credits 1–4 contributed nothing because
they were never expanded.

## First events

**R1** expansion 1, credit 0, `ECONOMIC_PROJECT` / `run_construction`,
actions `[[2,5,1]]`, cost 1, fd 44→43. Replay from opening OK, child digest
match. Lifecycle RETAINED (later R1 children were expanded).

**R2 and R3** (same successor) expansion 116, credit 0, `ECONOMIC_PROJECT`
/ `run_construction`, actions `[[5,4,1]]`, edge cost 1, path length 5 from
opening, fd 40→39, still 5 stock rows, 0 empties. Replay OK. Lifecycle
RETAINED, never expanded.

**R4, R5** never.

## Credit-4 raw fallback

0 credit-4 nodes expanded. Raw P0–P3 = empty. Raw R1–R4 = 0.

## Why A, not B/C/E

- **A** is met: R2 and R3 states are production-retained, replay-valid,
  CLEAN `ECONOMIC_PROJECT` children.
- **B** would require the signal to die at portfolio or TT. It survives
  both (4/4 R2 retained). Non-expansion is a later priority issue on those
  children, not generation/retention failure.
- **C** is true of the credit *ladder* (never pops credit 1) but false as
  the reason geometry is absent: geometry appears without the ladder.
- **E** is weaker: R1 does occur (min fd 44→37, min column fd → 0) *and*
  matures into an R2/R3 child; that child is just not expanded.
- **D** does not apply: credit 4 never runs.

Production can create the resource planner's prerequisite geometry. It has
not yet *used* that geometry as an expansion parent in this envelope.

## Pytest

`1863 passed, 37 xfailed in 1277.14s`

0 unexpected failures. Node-78 was not modified.
