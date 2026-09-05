# Resource excavation coverage anatomy v0.1

**Status:** complete, diagnostic only. No controller integration, no operator
changes, no v0.9.

**Start SHA:** `0f4b920df14b40931bd03935f3537a9231b5bdcc`

**Branch:** `agent/resource-excavation-coverage-anatomy-v0-1`

**Decision: B. NATURAL GAME STAGE / RESOURCE GEOMETRY IS THE BOTTLENECK**

The previous natural-state audit sampled a phase in which the resource model
is largely dormant. Every captured column still has face-down cards. There
are no idle empties. CREATE/INVEST/PREPAY therefore cannot fire, regardless
of which scheduler-native CampaignTarget is supplied.

Recommended next step (not taken here):

> Identify a principled way to test the same unchanged planner on later
> natural game phases that production v0.8 itself retains once an empty
> column or a fully-revealed column appears, without enlarging the search
> envelope and without using the 172-move route as a selector.

## Source states

The previous JSON stored identities, not reconstructable tableaus. The
exact previous passive collector was rerun once:

- 25 strategic expansions / 300_000 tactical nodes / 180s wall-clock
- whole-deal scheduler on, tactical allocation on, seed 0
- `deals/4925153.txt`
- stop reason `strategic expansion limit`

All 58 canonical captured-state identities matched the previous audit.
Run A/B inertness was not repeated.

Production files `anytime_controller.py` and
`resource_excavation_planner.py` are unchanged.

## Structural game-stage anatomy (58 states)

| metric | value |
| --- | --- |
| empties | 0 in 58/58 |
| fully revealed (zero face-down) columns | 0 in 58/58 |
| zero-fd AND whole-column movable | 0 in 58/58 |
| legal emptying moves | 0 in 58/58 |
| foundations | 0 in 58/58 |
| min face-down on any non-empty column | 4 (57 states), 3 (1 state) |
| stock rows | 5: 3 · 4: 14 · 3: 26 · 2: 15 |

Some states have face-up packets that are one movable run (including 3
states with 10 such packets), but those packets still sit on face-down
cards, so they cannot CREATE an empty.

## Primary P operator funnel (58 lead-lane first missing edges)

| operator | structurally eligible | ≥1 realisation | survived filters | in a successful plan |
| --- | --- | --- | --- | --- |
| `RESERVE_RECEIVER` | 7 | 7 | 7 | 0 |
| `REALISE_CAMPAIGN_EDGE` | 4 | 4 | 4 | 4 |
| `CREATE_WORKSPACE` | 0 | 0 | 0 | 0 |
| `INVEST_WORKSPACE` | 0 | 0 | 0 | 0 |
| `PREPAY_DEPENDENCY` | 0 | 0 | 0 | 0 |
| `TEMPORARY_REWORK` | 2 | 2 | 2 | 0 |
| `RECOVER_WORKSPACE` | 0 (`REQUIRES_WORKSPACE_DEBT`) | 0 | 0 | 0 |
| `REPAY_REWORK` | 0 at root | 2 reachable | 0 survived | 0 |

INVEST and PREPAY are `BLOCKED_BY_NO_IDLE_EMPTY` on every P state.

## CREATE gateway funnel

Across 58×10 = 580 source columns:

| stage | count |
| --- | --- |
| `SOURCE_HAS_FACE_DOWN` | **580** |
| fully movable whole-column packets with zero face-down | 0 |
| legal empty-creating destinations | 0 |
| actual `CREATE_WORKSPACE` candidates | 0 |

Nearest miss is not destination filtering or receiver protection. The
funnel never leaves the first predicate: **no fully revealed source
column exists**.

## REWORK funnel (P targets)

| stage | P states |
| --- | --- |
| no same-suit join boundaries | 28 |
| joins present, not target-relevant | 21 |
| target-relevant, no legal dest | 7 |
| qualifying `TEMPORARY_REWORK` at root | 2 |
| appearing in a successful plan | 0 |

Rework does **not** require an empty. Two P states generate a legal
rework, and those children make `REPAY_REWORK` reachable, but the bounded
operator search never converts that into `REALISED_CAMPAIGN_PROGRESS`.
That is a bounded-success gap on 2/58 states, not evidence that CREATE
geometry exists.

## Reachable operator graph (P)

Diagnostic traversal matched `plan_resource_excavation` on every P/L/A
target (Decision D did not fire).

Generated at P: `RESERVE_RECEIVER` 7, `REALISE_CAMPAIGN_EDGE` 4,
`TEMPORARY_REWORK` 2, `REPAY_REWORK` 2 (after rework).

Never generated: `CREATE_WORKSPACE`, `INVEST_WORKSPACE`,
`PREPAY_DEPENDENCY`, `RECOVER_WORKSPACE`.

Threat-gate (`RESERVE` exclusive while a consuming threat exists) fires
on 7 P states. That only explains reserve-first behaviour; it does not
hide CREATE, because CREATE has no candidates even when diagnosed
independently of the gate.

## P / L / A comparison

| | P | L | A |
| --- | --- | --- | --- |
| targets | 58 | 596 | 406 |
| `REALISED_CAMPAIGN_PROGRESS` | 4 | 34 | 4 |
| `PREPAID_DEPENDENCY` | 0 | 0 | 0 |
| `NO_BOUNDED_PLAN` | 54 | 562 | 402 |
| `RESOURCE_DEADLOCK` | 0 | 0 | 0 |
| `NONTRIVIAL_RESOURCE_PLAN` | 0 | 4 | 0 |
| `NOVEL_RESOURCE_SUCCESSOR` | 0 | 5 | 0 |
| nontrivial novel | 0 | 0 | 0 |

L sequences: 30× `REALISE` only, 4× `RESERVE+REALISE`.
A sequences: 4× `REALISE` only, all exact production duplicates.

The four L nontrivial plans are `RESERVE_RECEIVER` then
`REALISE_CAMPAIGN_EDGE` on later spade edges (5-4 or 8-7). Three are
`EXACT_DUPLICATE`; one parent was not expanded. None is a nontrivial
novel terminal.

The five L novels are trivial 1-ply `REALISE` only.

Later scheduler-native edges increase 1-ply realise count. They do not
awaken CREATE/INVEST/PREPAY/REWORK-to-success. Target mapping is not the
dominant bottleneck.

## Why B, not A/C/D

- **Not A:** L/A do not produce meaningful workspace behaviour. Zero
  nontrivial novel terminals. The four L `RESERVE+REALISE` hits are
  production-known or unexpanded.
- **Not C:** CREATE is not “too narrow” here. The useful geometry (a
  fully revealed emptyable column, or an idle empty) is absent. Rework
  predicates *accept* 2 P states; they are not the CREATE failure mode.
- **Not D:** identities reproduced; traversal matched the real planner;
  no illegal replay / false success / mutation.
- **B:** this 25-expansion opening envelope never retains an empty or a
  fully-revealed column. The resource model is dormant in this phase.

## Pytest

Complete suite after this diagnostic:

`1834 passed, 37 xfailed in 1242.62s`

0 unexpected failures. The node-78 test was not modified.

## Production non-changes

Unchanged: production v0.8, controller, resource planner operators and
bounds, TT, proof, scheduler, incumbent. No deal-specific constants.
