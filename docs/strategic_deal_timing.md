# Strategic deal timing and epoch transitions

## Status

Hard-gate verdict: **PASS**, not STRONG PASS.

The implementation makes the next exact stock deal a first-class strategic
alternative. It compares `DEAL NOW` with a small, replay-verified H1/H2 set of
`PREPARE THEN DEAL` states. Preparation cost is charged before any downstream
saving is claimed. Legal tableau moves do not have to be exhausted first.

The benchmark evidence is deliberately not weight fitting. No economic weight,
frontier threshold, incumbent rule, or benchmark-specific strategy was changed
after observing these results.

## Exact MobilityWare deal legality

MobilityWare documents two modes:

- normal play requires all ten tableau columns to contain a card; and
- the separate **Unrestricted Deal** setting permits dealing when tableau
  columns are empty.

The user confirmed that **Unrestricted Deal is enabled for this benchmark**.
The authoritative `MW_RULES` profile therefore retains
`can_deal_into_empty=True`. Evidence for the product distinction is the
[MobilityWare Spider help page](https://mobilityware.helpshift.com/hc/en/11-spider/faq/586-how-do-i-play-spider-solitaire/),
which describes both the populated-column rule and the Unrestricted Deal
exception.

`SpiderState.can_deal()` now exposes legality explicitly. `deal()` also enforces
the supplied rules profile: it permits empty-column dealing under `MW_RULES`
and rejects it if a caller explicitly supplies a restricted
`MobilityWareRules(can_deal_into_empty=False)` profile.

An **empty column** has neither face-down nor face-up cards. A **fully open
non-empty column** has no face-down cards but still has at least one face-up
card. The latter is populated and is not an empty-column legality case.

## Deal as a strategic project

`src/spider/planner/deal_timing.py` adds:

- `DealTimingStatus`, `DealTimingDecisionKind`, and `DealTimingReason`;
- `DealTimingConfig`;
- `IncomingRowImpact`;
- `DealPreparationCandidate`;
- `DealCounterfactual`;
- `ActionabilityTransition`;
- `DownstreamCostComparison` and `MarginalPreparationValue`;
- `DealTimingAssessment` and `DealTimingDecision`; and
- `DealEconomicProjectAdapter` for later controller integration.

Important public operations are:

- `analyze_exact_incoming_row`;
- `generate_preparation_candidates`;
- `build_preparation_candidate`;
- `simulate_deal_counterfactual`;
- `marginal_preparation_value`;
- `choose_deal_timing`;
- `assess_deal_timing`; and
- `deal_as_economic_project`.

The adapter is intentionally not wired into a whole-game controller yet.

## Exact incoming-row impact

The next row is always `state.stock[-10:]`, in engine column order. Production
logic contains no benchmark row constant.

For every incoming card the analysis records:

- destination column, card, and current receiver;
- same-suit, mixed-descending, non-connecting, or empty landing;
- whether permanent structure is buried;
- whether a new mixed boundary is formed;
- campaign MUST-dependency and stock-duplicate consequences;
- automatic foundation consequence;
- exact immediate walk-off moves and same-suit outs;
- workspace occupation/recovery consequence; and
- exact receiver success.

These remain transparent components. There is no opaque “stock quality”
scalar.

## Counterfactual protocol

For a state `S`, H0 is:

```text
clone(S) -> exactly one deal -> full structural/economic reanalysis
```

H1 and H2 are:

```text
clone(S) -> one or two bounded, non-redundant projects -> exactly one deal
         -> identical structural/economic reanalysis
```

Every preparation and post-preparation deal independently replays from `S`.
Structurally equal preparation states are deduplicated. The diagnostic uses:

| Resource | Value |
|---|---:|
| Preparation horizon | H0, H1, H2 |
| Maximum preparation cost | 8 |
| Diagnostic hard cap | 12 |
| H1 candidates retained | 3 |
| H2 candidates retained | 1 |
| Tactical objective cost | 4 |
| Tactical nodes / seconds | 5,000 / 2 |
| Downstream objective cost | 10 |
| Downstream nodes / seconds | 10,000 / 3 |

The generic defaults permit up to 50,000 downstream nodes and 15 seconds. The
benchmark diagnostic used the smaller matched limits above because they were
already sufficient to discriminate Checkpoint B.

## Preparation generation

Candidates come from currently actionable work only:

- Tier-1 and Tier-2 economic projects with bounded tactical progress;
- exact receiver-shaping probes for the actual next row;
- structural workspace/permanent-join fallback moves; and
- non-redundant pairs of those projects.

Future-epoch projects, bounded-inaccessible targets, and arbitrary long legal
sequences are not preparation candidates. The search does not “play until
stuck.”

## Marginal preparation value

The comparison reports the preparation investment separately from post-deal
return.

Preparation investment includes:

- corrected paid cost;
- added rehandling debt;
- stable joins broken; and
- workspace consumed.

Post-deal return includes:

- stable joins and same-suit mass retained;
- mixed liabilities avoided;
- exact receiver successes;
- campaign MUST burden and critical dependencies removed;
- high-value projects newly actionable;
- workspace and mobility changes; and
- estimated remaining-work change.

The decisive bounded calculation is:

```text
bounded net gain
  = DEAL-NOW downstream cost
  - prepared-state downstream cost
  - preparation paid cost
```

A visually cleaner tableau cannot win without concrete comparable evidence.
If no common downstream target is found, the result is `COMPARISON_INCONCLUSIVE`.

## Actionability transition

Value and actionability remain separate. Each deal arm records high-value
projects that are actionable or blocked before the deal and those newly
actionable or blocked afterward. This lets a deal receive explicit strategic
credit for advancing the epoch without pretending that an inaccessible
high-value excavation was executable before the deal.

## Checkpoint A — preferred opening before Deal 1

Exact reconstruction:

```text
corrected cost = 6
actions = 6
deals consumed = 0
stock = 50
face-down = 39
foundations = 0
empty columns = column 6
legal tableau moves = 18
independent replay = verified
```

Because Unrestricted Deal is enabled, the empty column does not make Deal 1
illegal. The bounded comparison recommends `DEAL_NOW_PREFERRED`: sampled
preparations did not repay their paid cost. This supersedes the earlier
assumption that the empty column had to be filled for legality; it does not
claim that the known later route is globally timing-optimal.

## Checkpoint B — legal post-Deal-1 cost 11

Exact reconstruction:

```text
corrected cost = 11
actions = 11
deals consumed = 1
stock = 40
face-down = 36
foundations = 0
empty columns = 0
fully open non-empty columns = column 6
legal tableau moves = 8
independent replay = verified
```

Exact Deal-2 row:

```text
Ks As 6h 7s Ad Ad Ah 10d Qh Jd
```

`DEAL NOW` costs one. Its post-deal facts include stock 30, face-down 36,
mobility 4, stable joins 5, same-suit mass 7, longest run 5, mixed boundaries
17, rehandling-debt proxy 17, and campaign MUST burden 33.

The bounded alternatives were:

| Preparation | Cost | Matched follow-on: now | Matched follow-on: prepared | Net after preparation |
|---|---:|---:|---:|---:|
| `move 6 8 1` | 1 | 1 | 1 | -1 |
| `move 7 1 2` | 1 | 1 | 1 | -1 |
| `move 9 7 1` | 1 | 1 | 1 | -1 |
| `move 6 8 1`; `move 1 6 1` | 2 | 1 | 1 | -2 |

Frozen decision: **`DEAL_NOW_PREFERRED`**. Eight legal tableau moves remain,
but none of the comparable preparation arms lowers total bounded expenditure.
The successful cost-23 route’s seven pre-Deal-2 tableau actions are therefore
not treated as proof that delaying Deal 2 was optimal.

Deal 2 makes `move-c8-c10-k1` newly actionable and blocks three earlier direct
projects. This transition is recorded rather than folded into a magic score.

## Checkpoint C — first foundation, before Deal 3

Exact reconstruction:

```text
corrected cost = 23
actions = 23
deals consumed = 2
stock = 30
first foundation = Spades
face-down = 32
empty columns = 0
fully open non-empty columns = columns 6 and 7
legal tableau moves = 6
independent replay = verified
```

Exact Deal-3 row:

```text
2c 10s Qd Kh 8h 9c 3s 5s 5d 4h
```

`DEAL NOW` costs one. The post-Deal-3 clone has stock 20, one foundation,
face-down 32, mobility 7, stable joins 3, same-suit mass 6, mixed boundaries
20, debt proxy 20, and campaign MUST burden 33.

Three generic permanent-join preparations survived deduplication:

| Preparation | Paid cost | Post-deal stable joins | Same-suit mass | Mixed boundaries | Bounded net |
|---|---:|---:|---:|---:|---:|
| `move 2 10 1` | 1 | 4 | 7 | 18 | inconclusive |
| `move 9 4 1` | 1 | 4 | 8 | 19 | inconclusive |
| both joins | 2 | 5 | 9 | 17 | inconclusive |

The stable work clearly improves post-deal structure, but the matched probe
found no common bounded objective with a measurable paid-cost saving. Frozen
Deal-3 recommendation: **`COMPARISON_INCONCLUSIVE`**. The implementation does
not manufacture a saving or convert prettier structure into a timing decision.

Deal 3 immediately blocks both current Tier-1 joins and creates no newly
depth-one-actionable high-value project in this bounded measurement. This is
important evidence for a future controller, but not enough by itself to prove
that the one- or two-move preparation is lifecycle-cheaper.

## Opposite-behaviour validation

A full 104-card synthetic legal fixture proves that the planner can delay a
legal deal when exact bounded preparation pays.

- Deal now: the exact three-card Spade band costs 3 downstream moves.
- Preparation: `move 2 1 1` places 6s on 7s for the known incoming 5s.
- Preparation cost: 1.
- Prepared post-deal downstream cost: 0.
- Bounded net gain: `3 - 0 - 1 = +2`.

Decision: **`PREPARATION_PREFERRED`**. The result comes from exact receiver
geometry and matched objective cost, not from a generic high-rank or same-suit
bias.

## Research and production budgets

With replay-verified incumbent 172, DEAL-NOW clones report:

| Checkpoint | g | h_deals | h_reveal_paid | h_admissible | Hard minimum | Headroom | Proof-prunable |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 7 | 4 | 0 | 4 | 11 | 160 | No |
| B | 12 | 3 | 3 | 6 | 18 | 153 | No |
| C | 24 | 2 | 6 | 8 | 32 | 139 | No |

With `incumbent=None`, the timing decision uses the same incoming-row and
marginal-comparison semantics. There is no target, headroom, or incumbent
proof pruning. Installing a later replay-verified incumbent changes only the
existing budget object.

Economic timing, structural outcomes, rehandling debt, actionability changes,
and the external 119 context never enter `proof_prunable`.

## Canonical comparison after freeze

Only after Checkpoints A, B, and C, the control, and the PASS verdict were
frozen did the diagnostic open the canonical route. It replays solved at
corrected cost 172. Its tableau-action counts before the five deals are:

```text
51, 37, 11, 17, 31
```

This is descriptive context only. It changed no candidate, downstream target,
or timing decision.

## Progressive economic credit — controller design only

A later anytime controller should retain DEAL at every legal pass:

1. dominant/permanent/actionable work plus DEAL timing;
2. positive investments and bounded rework plus DEAL;
3. speculative/deferrable work plus DEAL;
4. unexplained escape work plus DEAL; and
5. broad legal fallback plus DEAL.

The controller must never require tableau exhaustion before presenting DEAL.
This sprint does not implement those global passes.

## Hard-gate verdict

**PASS**, not STRONG PASS.

Confirmed:

- the active Unrestricted Deal rule is exact and enforced;
- empty and fully open non-empty columns are distinct;
- DEAL is a first-class H0 option;
- exact rows drive per-column impact analysis;
- all deal/preparation arms clone and independently replay;
- preparation cost is included in total marginal expenditure;
- a natural state deals with legal tableau moves remaining;
- a legal synthetic state delays for a bounded +2 gain;
- Checkpoint B produces a clear natural comparison;
- Checkpoint C has a frozen prospective result;
- production mode has no hidden incumbent dependency; and
- timing economics remain outside proof pruning.

STRONG PASS is withheld because Checkpoint C’s matched downstream evidence is
too flat to distinguish immediate Deal 3 from the visibly stronger permanent-
join preparation states.

## Limitations

- The H1/H2 sample is intentionally small and does not prove optimal deal
  timing.
- Actionability transitions use hard/direct depth-one tests; deeper bounded
  actionability remains a separate tactical question.
- The generic downstream selector can fail to find a common objective even
  when structural improvement is real, as at Checkpoint C.
- Mixed-boundary debt remains an ordering proxy, not measured eventual
  complete-solution cost.
- Exact incoming impacts identify per-card facts but do not yet solve joint
  multi-card walk-off scheduling.
- One benchmark and one synthetic control are not sufficient for weight
  calibration; no weights were tuned here.

## Recommended next task

Proceed to **Anytime Whole-Game Controller v0.1**, with strategic deal timing
as a mandatory decision service. DEAL must remain available beside every
economic tier, actionability must stay separate from value, and only the
existing admissible incumbent budget may proof-prune.
