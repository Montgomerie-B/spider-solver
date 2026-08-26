# Economic project realization calibration

## Status

Verdict: **PASS**.

The experiment confirms that the two immediately actionable Tier-1 permanent
joins produce materially better one-paid-move structural outcomes than an
equally immediate Tier-4 mixed park. The benchmark sample is smaller than the
target because every positive-investment excavation is behind the same
tableau-only reachability plateau at the legal cost-23 checkpoint. No Tier-2
project can make even one target reveal inside the matched no-deal bound.

This is calibration data, not fitted training data. No economic weight,
frontier threshold, reveal classification, lifecycle value, campaign ranking,
or predicted project order was changed after seeing realization results.

## Experimental protocol

The experiment follows two strictly ordered phases.

### Phase A — frozen prediction

The legal cost-23 state is independently reconstructed from the true deal
through the preferred permanent-join opening, generic Deal-1 realizer, and
corrected Deal-2 S#1 removal realizer. The reconstruction requires:

| Fact | Required and observed |
|---|---:|
| Corrected cost | 23 |
| Explicit actions | 23 |
| Stock deals | 2 |
| Stock remaining | 30 |
| Foundations | 1 Spade |
| Face-down cards | 32 |
| Deal 3 | Not taken |
| Independent replay | Verified |
| Stored/replayed state | Structurally equal |

The existing `analyze_economic_projects` result is then deep-frozen into
immutable primitive records containing:

- all 18 projects in exact frontier order;
- project kinds and tiers;
- every labelled cost and benefit component;
- debt, exit route, and bounded-exit flag;
- reveal classifications and zero information gain;
- rework investment fields;
- dominance relations;
- estimated remaining work; and
- research-incumbent and production-no-incumbent budgets.

A SHA-256 fingerprint covers the complete prediction payload. Every
realization result carries that fingerprint, and the experiment verifies it
again after all tactical work.

### Phase B — actionability and realization

Only after prediction freeze does the generic actionability pass ask whether a
project can make structural progress through tableau moves without dealing.
Every project begins from an independent clone of the same cost-23 state.

The actionability screen uses the same highest cost ceiling and tactical
limits as the realization experiment. For excavation projects it asks for at
least one real reduction in the target column's face-down prefix. A bounded
miss affects only current experimental eligibility; it is not a global proof
that the project will never be useful.

No canonical moves are opened during prediction, screening, realization,
measurement, downstream probing, or prediction-versus-actual classification.

## Generic realization API

`src/spider/planner/economic_project_realizer.py` provides:

- `freeze_economic_predictions` and `verify_prediction_freeze`;
- `project_predicate`;
- `probe_project_actionability` and `probe_frontier_actionability`;
- `select_representative_projects`;
- `realize_economic_project`;
- `realize_economic_project_bounds`;
- `measure_structural_state` and `structural_outcome_vector`;
- `run_downstream_probe`;
- `validate_rework_outcome`; and
- `assess_prediction`.

Statuses are:

- `PROJECT_REALIZED`;
- `PROJECT_ADVANCED`;
- `NOT_FOUND_WITHIN_BOUND`;
- `RESOURCE_LIMIT`;
- `INVALID_PROJECT`; and
- `NOT_ACTIONABLE_CURRENT_EPOCH`.

The module is an adapter over existing tactical primitives, particularly the
exact bounded objective realizer. It is not another whole-game search engine
and is not connected to `plan_search`.

## Structural predicates

Predicates are facts rather than score targets:

- a column face-down count reaches the frozen prefix target;
- a specified same-suit high/low adjacency exists;
- empty-column count increases;
- a stock-receiver top geometry exists; or
- a frozen lifecycle control effect is replayed.

The economic excavation project aggregates the complete known hidden prefix,
so `PROJECT_REALIZED` requires all face-down cards in that target column to be
exposed. A fallback one-reveal predicate may report `PROJECT_ADVANCED`, never
`PROJECT_REALIZED`.

For an unexplained temporary park, replaying the predicted mixed boundary is
only `PROJECT_ADVANCED`. It cannot become realized merely because the park
move executed. Rework validation separately requires the promised structural
return.

## Matched resource limits

Every sampled project receives the identical configuration:

| Resource | Value |
|---|---:|
| Added-cost bounds | 4, 8, 12 |
| Nodes per bound | 50,000 |
| Seconds per bound | 18 |
| Stock deals allowed | No |
| Foundation increase allowed | No |
| Downstream cost ceiling | 8 |
| Downstream nodes | 20,000 |
| Downstream seconds | 8 |

The series stops after `PROJECT_REALIZED`. A Tier-4 control stops after its
frozen lifecycle effect is `PROJECT_ADVANCED` because it has no positive
return predicate to pursue.

## Frozen frontier and actionability

The frontier remains exactly:

- 2 `STRUCTURALLY_DOMINANT`;
- 13 `POSITIVE_INVESTMENT`;
- 1 `SPECULATIVE_DEFERRABLE`; and
- 2 `ECONOMICALLY_UNEXPLAINED`.

The deterministic actionability pass found:

- both Tier-1 permanent joins immediately actionable;
- all eight excavation projects unable to make even one target reveal in the
  112-state, cost-12 no-deal bounded closure;
- future-deal campaign projects ineligible;
- the current-epoch H campaign without a narrow structural predicate;
- the receiver project lacking frozen structural target coordinates;
- all three lifecycle park actions immediately actionable.

Consequently, the honest benchmark sample contains three projects rather than
inventing approximately six:

1. first frontier-ordered Tier-1 permanent join;
2. second frontier-ordered Tier-1 permanent join; and
3. first frontier-ordered actionable Tier-4 control.

Selection uses tiers, actionability, overlap keys, and quotas. It contains no
benchmark project ID, column, suit, rank, or move constant.

## Actual results

### Structural baseline

| Component | Cost-23 state |
|---|---:|
| Face-down | 32 |
| Foundations | 1 |
| Stock | 30 |
| Empty columns | 0 |
| Fully open non-empty columns | 2 |
| Legal tableau moves | 6 |
| Stable same-suit joins | 3 |
| Same-suit run mass | 6 |
| Longest same-suit run | 2 |
| Mixed boundaries | 12 |
| Rehandling-debt proxy | 12 |
| Current critical dependencies | 10 |
| Total campaign MUST burden | 26 |

### Prediction versus actual

| Project class | Predicted tier | Predicted lifecycle cost | Actual status/cost | Stable joins | Same-suit mass | Mixed boundaries | Mobility | MUST burden | Debt | Assessment |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| Permanent join A | 1 | 1 | Realized / 1 | +1 | +1 | -1 | +1 | -1 | -1 | Confirmed |
| Permanent join B | 1 | 1 | Realized / 1 | +1 | +2 | -1 | -1 | -1 | -1 | Confirmed |
| Mixed-park control | 4 | 3 projected lifecycle / 1 immediate | Advanced / 1 | 0 | 0 | +1 | -3 | +1 | +1 | Confirmed |

All three action sequences contain one legal single-card tableau move. Each
independently replays at corrected cost 1, retains stock 30 and one foundation,
and satisfies its frozen local predicate. No result receives credit for an
unobserved consequence.

The comparison is especially clean because immediate paid cost is equal. The
Tier-1 moves create permanent structure and remove a mixed liability. The
Tier-4 control creates liability, worsens campaign burden, and sharply reduces
current legal mobility.

## Downstream bounded probes

After each project, the economic portfolio is regenerated and its nearest
machine-testable follow-on is probed from both the original and post-project
states under identical cost-8/node/time limits.

For this sample the nearest follow-on is the other permanent join. It costs 1
from both states, so every bounded downstream delta is zero. This is honest
inconclusive evidence rather than an invented saving. The permanent value is
already directly present in the structural vectors.

## Rework “pot of gold” result

The natural frozen candidate is the highest Tier-2 project with non-zero
rework debt. Its frozen investment was:

- estimated investment 16;
- estimated structural return 83;
- expected saving 1;
- heuristic net 68;
- medium confidence;
- exit route explicitly unbounded; and
- `worthwhile=False` under the existing rework rule.

The no-deal actionability probe exhausts the matched 112-state cost-12 closure
without a single target reveal. Classification: `FAILED_TO_REALIZE`.

This does not disprove that the project becomes valuable after Deal 3. It does
show that the current portfolio's positive-investment tier is not itself an
actionability claim. The benchmark cannot validate a real current-epoch pot of
gold because no debt-bearing Tier-2 project is reachable under the task's
no-Deal-3 boundary.

No synthetic example is added to the benchmark sample. Existing synthetic
coverage continues to test the general rule that bounded return can exceed
rework debt.

## Tier-4 control

The control behaves exactly as the frozen economic explanation predicted:

- immediate cost 1;
- no stable join or run-mass gain;
- one new mixed boundary;
- one added debt unit;
- legal mobility 6 to 3;
- total MUST burden 26 to 27; and
- no downstream saving.

Its tier remains Tier 4 after observation. The result is `PROJECT_ADVANCED`,
not `PROJECT_REALIZED`, because executing an unexplained park is not a
structural return.

## Proof-safety boundary

At baseline:

```text
g = 23
h_admissible = 4
hard minimum = 27
incumbent = 172
improvement target = 171
proof_prunable = false
```

Each one-cost clone reports `g=24`, unchanged admissible `h=4`, and
`proof_prunable=false`.

Only the existing admissible lower bound affects proof pruning. Economic
scores, prediction tiers, actionability results, measured structural vectors,
rehandling debt, downstream probes, and the external 119 context never enter
the proof decision.

## Canonical post-freeze observation

Only after predictions, sample, actionability results, realization results,
structural vectors, prediction classifications, rework classification, and
the PASS verdict are frozen does the diagnostic open the canonical route.

It independently replays at corrected cost 172 and solves. Both selected
same-suit relationships occur in the later route. The route also contains many
stable joins as well as mixed and workspace parks, consistent with the model's
distinction between permanent work and rework. Canonical data changes no
earlier result.

## Hard-gate verdict

**PASS**, not STRONG PASS.

Confirmed:

- immutable prediction-before-realization discipline;
- exact cost-23 reconstruction;
- deterministic generic selection;
- legal replay-valid project realization;
- clear Tier-1 versus Tier-4 discrimination at matched paid cost;
- permanent structural gain from both high-tier projects;
- honest failure of the natural rework candidate to become actionable;
- proof/economic separation;
- no Deal 3 or second foundation; and
- canonical access only after the result freeze.

STRONG PASS is withheld because no Tier-2 project is actionable at this
checkpoint, the sample contains only three projects, and downstream probes do
not establish a cost saving.

## Limitations

- The economic frontier does not yet encode tactical actionability strongly
  enough; Tier 2 currently means attractive if reachable, not reachable now.
- Excavation closure's static `emptyable_this_epoch` assessment is more
  optimistic than the bounded exact no-deal reachability result here.
- The receiver project lacks explicit frozen target coordinates suitable for
  generic realization.
- Campaign projects need narrower current-epoch subpredicates.
- Rehandling debt is still an ordering proxy, not measured eventual solution
  cost.
- One checkpoint cannot calibrate global weights, and this task intentionally
  does not try.

## Recommended next task

Because the result passes and the architecture behaved correctly, the next
development task may be **Anytime Whole-Game Controller v0.1**. Its first
version should treat actionability as a separate gate from economic value,
retain portfolio diversity, use the existing no-incumbent/verified-incumbent
budget semantics, and continue to forbid heuristic proof pruning.

The controller task should not tune economic weights from this single sample.
It should collect comparable outcomes across multiple checkpoints and unseen
deals first.
