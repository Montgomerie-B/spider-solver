# Resource excavation natural-state shadow audit v0.1

**Status:** complete, shadow-only. No controller integration.

**Start SHA:** `7480dd26bc9506ba7467a764b51fd316b6e08fb6`

**Branch:** `agent/resource-excavation-natural-shadow-v0-1`

**Deal used as the current natural-state source:** `deals/4925153.txt` only.
No 172-move human route and no named historical nodes were used to choose
states. Observations from this deal are not production constants.

**Decision: C. NATURAL RESULTS REDUNDANT OR TOO EXPENSIVE**

Dominant problem: **redundancy**, not runtime. The planner is cheap on these
states. Every successful plan is a 1-ply `REALISE_CAMPAIGN_EDGE` whose
terminal canonical state and corrected cost already exist as a production
v0.8 successor from the same parent.

Recommended next step (not taken here):

> Do not integrate. Next: a coverage-anatomy diagnostic of operator
> generation on the already-captured natural states (why only `REALISE`
> fires; why `CREATE`/`INVEST`/`RESERVE`/`PREPAY`/`REWORK` never appear),
> without adding operators, without controller wiring, and without enlarging
> production search.

## Separation

- `anytime_controller.py` is unchanged and does not mention
  `resource_excavation`.
- The resource planner is never imported during production collection.
- Production successors, ordering, pruning, TT, scheduler, proof, incumbent
  and budgets are untouched. This is not v0.9.

Collection is two-stage: production v0.8 runs to completion, then the
resource planner is applied offline to cloned captured states.

## Production collection configuration

Existing Gate Z expansion/node envelope, with wall-clock raised only so the
expansion cap binds:

| knob | value |
| --- | --- |
| `max_strategic_expansions` | 25 |
| `max_tactical_nodes` | 300_000 |
| `wall_clock_limit_s` | 180.0 |
| scheduler | `enable_whole_deal_scheduler=True` |
| tactical allocation | `enable_tactical_resource_allocation=True` |
| random seed | 0 |

Stop reason on both runs: `strategic expansion limit` (not timeout).
Status: `RESOURCE_LIMIT`. Run A 28.3s, Run B 28.6s.

## Phase 2 — collection is behaviourally inert

Run A: production v0.8, no wrapper.

Run B: the same config, `PassiveCollector` wrapping `_record_transition`
only (clone parent/child, then call the original recorder).

Equal on:

- status, stop reason, expansion count, tactical nodes
- incumbent sequence (none)
- best-g / best canonical digest
- telemetry: generated/retained/TT, `successor_kinds`, scheduler objective
  and delta counts

If those had differed, the audit would have stopped (Decision D). They did
not.

Passive collection clones states. It does not add frontier nodes.

## Captured distribution

| quantity | value |
| --- | --- |
| captured unique states | 58 |
| captured transitions | 57 |
| expanded parents | 25 |
| eligible unique state-target pairs | 58 |
| eligibility rate | 58/58 = 1.0 |
| ineligible | none |
| audited | 58 (all; under the 128 cap) |

Game-stage span of captured states:

| axis | distribution |
| --- | --- |
| stock rows | 5: 3, 4: 14, 3: 26, 2: 15 |
| foundations | 0: 58 |
| face-down | 43: 45, 44: 13 |
| empties | 0: 58 |
| lead family | `MERGE_READY` 30, `FRAGMENT_BUILDING` 22, `BRIDGE_READY` 3, `FUTURE_GATED` 3 |

The 25-expansion opening envelope does span several stock-row depths, but it
never retains an empty column or a completed foundation. That is a property
of production v0.8 under this envelope, not a hand-picked slice.

Targets are the scheduler lead lane's first `missing_edges` pair, converted
to `CampaignTarget`. No rank enumeration, no success-oriented retargeting.

## Shadow results

| result | count |
| --- | --- |
| `REALISED_CAMPAIGN_PROGRESS` | 4 |
| `PREPAID_DEPENDENCY` | 0 |
| `NO_BOUNDED_PLAN` | 54 |
| `RESOURCE_DEADLOCK` | 0 |
| `RESOURCE_OVERRUN` | 0 |

`RESOURCE_DEADLOCK` is a bounded planner enum, not a proof that the Spider
state is globally deadlocked. It did not occur here.

Operator-family frequencies (only successes emit operators):

| operator | count |
| --- | --- |
| `REALISE_CAMPAIGN_EDGE` | 4 |

No `CREATE_WORKSPACE`, `INVEST_WORKSPACE`, `RECOVER_WORKSPACE`,
`RESERVE_RECEIVER`, `PREPAY_DEPENDENCY`, `TEMPORARY_REWORK`, or
`REPAY_REWORK` on any audited pair.

Visited local states: median 1, p90 2, p95 2, max 2.

Runtime: median 0.000295s, p90 0.000666s, p95 0.000866s, max 0.001031s.

Plan cost on the 4 successes: 1 (all).

Per-call 5s wall-clock is recorded as `RESOURCE_OVERRUN` if exceeded, but
calls are not forcibly killed in-process on Windows. Structural bounds
(`MAX_OPERATORS=8`, `MAX_UNRESOLVED_OBLIGATIONS=2`, `MAX_REALISER_MOVES=4`)
were not raised. No overrun occurred.

## Replay / integrity

On every audited pair:

- captured parent canonical identity unchanged after `plan_resource_excavation`
- local transposition key remains `(canonical_state_key, obligations)` and
  does not write production/global TT
- `proof_pruning_allowed` is False
- the 4 realised plans replay legally, reported cost equals replay cost,
  intended Kh–Qh edge count increases 0→1, unresolved obligation count is 0

No illegal replay, false `REALISED` success, obligation leakage, input
mutation, or TT contamination. Not Decision D.

## Production overlap

Restricted to expanded parents (unexpanded captured children are not claimed
as novel):

| class | count |
| --- | --- |
| `EXACT_DUPLICATE` | 4 |
| `DOMINATED_DUPLICATE` | 0 |
| `BETTER_DUPLICATE` | 0 |
| `NOVEL_RESOURCE_SUCCESSOR` | 0 |
| `NO_SUCCESS` | 54 |

Distinct novel terminal states: **0**.

All 4 successes have `first_action_known=true`: the first (and only) resource
action was already a production successor from that parent. This is
repackaging of a 1-ply v0.8 move, not new strategic reach.

## Representative examples

Taken from the hash-ordered sample after the experiment, not cherry-picked
beforehand. The four realised rows plus four hash-order misses that add a
new `(stock_rows, family)`:

1. `565d1de7d0f17f9e` · `h MERGE_READY missing 13-12` · stock 3, fd 43 ·
   `REALISE (0,3,1)` cost 1 · terminal `75cf1236074f5eeb` ·
   `EXACT_DUPLICATE` · first action already a production successor.
2. `564b6aa649b89649` · same Kh–Qh realise · stock 3 · terminal
   `021a7380370396fe` · `EXACT_DUPLICATE`.
3. `fdf7553894fecea5` · same Kh–Qh realise · stock 3 · terminal
   `61ebc2f2c8e30267` · `EXACT_DUPLICATE`.
4. `83c12885305d41e5` · same Kh–Qh realise · stock 3 · terminal
   `19c46c7c31b84cc8` · `EXACT_DUPLICATE`.
5. `021a7380370396fe` · `d MERGE_READY missing 13-12` · stock 3, fd 43 ·
   `NO_BOUNDED_PLAN` · visited 2 · expanded parent with 1 production child.
6. `c06565c127ccbc7a` · `s BRIDGE_READY missing 13-12` · stock 5 ·
   `NO_BOUNDED_PLAN` · visited 1.
7. `64a8ca698cc303e9` · `s FRAGMENT_BUILDING missing 13-12` · stock 2 ·
   `NO_BOUNDED_PLAN`.
8. `97344b73f31f2e05` · `s FUTURE_GATED missing 13-12` · stock 4 ·
   `NO_BOUNDED_PLAN`.

Machine-readable identities, targets, classifications and aggregates:
`research/results/resource_excavation_natural_shadow_v0_1.json`.

## Why this is C, not A/B/D

- **Not A:** 58 pairs were audited and 4 states realised a campaign edge, but
  **zero** realised terminals are `NOVEL_RESOURCE_SUCCESSOR`. A requires at
  least 3 distinct novel realised terminals.
- **Not B:** scheduler→`CampaignTarget` mapping is common (58/58), and there
  are more than 32 eligible pairs. Coverage does not fail at targeting. It
  fails at *novelty*: the only thing the model realises, production already
  realises.
- **Not D:** collection is inert; replay/integrity checks pass.
- **C:** every success is an exact production duplicate. Runtime is not the
  limiter (max 2 local states, ~1ms). Redundancy is.

Secondary observation, not used to widen the model: every captured state has
0 empties, so workspace operators have no idle empty to invest. That is why
operator generation is almost only immediate realise. This audit does not
add operators or enlarge the production envelope to manufacture later-game
empties.

## Pytest

Complete suite after this audit:

`1822 passed, 37 xfailed in 1256.28s`

0 unexpected failures. The node-78 test was not modified.

## Production non-changes

Unchanged: production v0.8, `anytime_controller.py`, exact TT
(`canonical_state_key`), proof semantics (`proof_pruning_allowed` still
False on the resource planner), scheduler behaviour, incumbent logic, search
budgets, `MAX_OPERATORS` / `MAX_UNRESOLVED_OBLIGATIONS` /
`MAX_REALISER_MOVES`.
