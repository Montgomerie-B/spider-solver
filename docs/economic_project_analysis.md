# Economic project analysis

## Status and scope

This layer adds whole-tableau economic analysis between strategic facts and a
future anytime controller. It is diagnostic and ordering-only. It does not
continue the legal cost-23 checkpoint, deal the third stock row, remove a
second foundation, search for a complete solution, modify `plan_search`, or
write a solution archive.

The generic implementation is split between:

- `src/spider/planner/economic_projects.py` — reveal consequences, project
  cost/benefit/debt, rework investment, frontier tiers, and conservative
  dominance metadata;
- `src/spider/planner/incumbent_budget.py` — incumbent-independent proof budget
  semantics and a strictly separate heuristic economic budget;
- `src/spider/planner/diagnostics/economic_project_analysis_report.py` — legal
  benchmark reconstruction, frozen prospective analysis, and only then
  canonical validation.

No benchmark deal number, move, column, incumbent, or external score is a
constant in either generic module.

## Perfect-information reveal principle

Spider is a perfect-information planning problem in this project. Every
face-down card is already known from the loaded deal. Therefore:

```text
information_gain = 0
```

for every reveal. Face-down reduction has no intrinsic reward.

A reveal receives structural value only when known consequences justify it,
including:

- satisfying a current or next-deal campaign dependency;
- enabling a same-suit receiver or permanent band;
- preparing an exact known stock receiver;
- advancing a column toward reusable workspace;
- removing or avoiding a mixed-suit liability;
- exposing a downstream dependency chain;
- making another physical copy unnecessary; or
- plausibly avoiding later paid work.

The classifications `CRITICAL_NOW`, `REQUIRED_BEFORE_NEXT_DEAL`,
`HIGH_VALUE_CURRENT_EPOCH`, `USEFUL_BUT_DEFERRABLE`,
`REPLACEABLE_BY_DUPLICATE`, `REPLACEABLE_BY_STOCK`, `LATER_EPOCH`, and
`LOW_CURRENT_VALUE` communicate timing and substitutability. They are
heuristic labels, not proof predicates.

The cost-23 checkpoint supplies a useful natural contrast. A depth-one 2c has
zero structural value in the current analysis because a known stock copy is
available, while deeper selected campaign sources have materially greater
consequence-only value. The ordering is driven by dependencies and structural
outcomes, not by novelty or raw reveal count.

## Economic project abstraction

An `EconomicProject` is a strategic unit of work rather than necessarily one
move. Generic kinds cover card or column excavation, workspace creation and
recovery, permanent joins, band assembly, mixed-boundary removal, exact-stock
receiver preparation, campaign steps, temporary rework, and deferred work.

Each project retains a component breakdown:

### Cost

- immediate corrected paid cost;
- independently bounded tactical cost, when one exists;
- necessarily consumed stock deals;
- current observed rehandling obligations;
- estimated additional paid actions;
- mixed-suit park and stable-join-break debt;
- workspace creation/recovery;
- receiver preparation;
- future rehandling; and
- timing delay.

Every component is labelled `HARD_FACT`, `BOUNDED_FACT`, or
`HEURISTIC_ESTIMATE`. An absent bounded route is represented as absent rather
than silently replaced by a heuristic.

### Benefit

- stable same-suit joins and run mass;
- mandatory campaign dependencies advanced;
- redundant source alternatives retired;
- exact-stock receivers prepared;
- mixed boundaries removed;
- workspace created or made more recoverable;
- critical reveal chains advanced;
- foundation readiness; and
- plausible future paid actions avoided.

### Debt

Project lifecycle records temporary actions, mixed boundaries created, stable
joins broken, provisional joins, workspace consumed, an explicit future exit
route, whether that route is bounded, and projected rehandling cost. Debt is
always ordering-only. It is represented in the labelled cost breakdown and is
not subtracted twice by the assessment.

## Rework as investment

Rework is neither prohibited nor rewarded by default. `ReworkInvestment`
records:

- investment cost;
- expected structural return;
- expected paid-action saving;
- concrete evidence;
- net economic value;
- confidence; and
- whether the exit route is bounded.

A temporary project becomes a positive investment only when it has an
identified return and, for the stronger judgement, a bounded exit whose return
exceeds its debt. A synthetic legal-scale fixture demonstrates that a bounded
four-action park/exit route can outrank clean but low-return local work when it
clears a mandatory chain, creates workspace, and avoids later separation. An
unexplained park remains low-ranked. This demonstrates the intended “pot of
gold” rule without encoding a benchmark conclusion.

## Economic frontier

The frontier retains every project and orders it into four tiers:

1. `STRUCTURALLY_DOMINANT` — permanent structure or critical current work with
   no material identified downside;
2. `POSITIVE_INVESTMENT` — cost or temporary work with a larger identified
   structural return;
3. `SPECULATIVE_DEFERRABLE` — plausible but weakly timed, substitutable, or
   insufficiently bounded value;
4. `ECONOMICALLY_UNEXPLAINED` — legal work with no identified current return.

Tier 4 is retained. The frontier cannot delete a state or prove that a branch
is impossible.

## Conservative dominance

Project A may heuristically dominate project B only when it is no worse in
immediate paid cost, reveal/dependency value, workspace effect, and stock
receiver effect, and is strictly better in permanent structure, mixed debt,
rehandling, or critical advancement.

Dominance is suppression/ordering metadata only. `proof_pruning_allowed` is
false on projects, debt, rework investments, frontier tiers, and dominance
relations. A permanent same-suit join therefore outranks an otherwise
comparable unexplained mixed park, but the park remains available to exact
search.

## Incumbent budget

`IncumbentBudget` accepts an optional replay-verified incumbent.

With incumbent `U`:

```text
improvement_target = U - 1
hard_min_total = g + h_admissible
hard_headroom = improvement_target - hard_min_total
proof_prunable = (g + h_admissible >= U)
```

With no incumbent, the target and headroom are unbounded and incumbent proof
pruning is disabled. The same budget object can later install the first
replay-verified incumbent; its proof limit tightens immediately without
changing the state analysis.

The heuristic budget is separate:

```text
heuristic_economic_slack = improvement_target - g - estimated_remaining_work
```

Changing `estimated_remaining_work`, even to an arbitrarily large value,
cannot change `hard_min_total` or `proof_prunable`.

## Proven-safe remaining lower bound

The only full-solution lower bound used by this layer is the current proved
formula:

```text
h_deals = remaining_deals
h_reveal_paid = ceil(max(0, face_down - 10 * remaining_deals) / 2)
h_admissible = h_deals + h_reveal_paid
```

The division by two allows one paid tableau action to reveal at both its source
and, after foundation removal, its destination. The deal allowance permits up
to one such foundation-triggered flip in each of ten columns per deal.

The former `face_down + deals` quantity remains available in the lower-bound
diagnostic only under an explicitly non-admissible name. It is absent from the
proof total and cannot prune.

## Legal cost-23 diagnostic findings

The checkpoint is reconstructed from the true deal through the preferred
six-action permanent-join opening, the generic Deal-1 realizer, and the
corrected Deal-2 S#1 removal realizer. Independent replay and structural
identity require:

| Fact | Result |
|---|---:|
| Corrected cost | 23 |
| Explicit actions | 23 |
| Deals taken | 2 |
| Stock remaining | 30 |
| Foundations | 1 Spade foundation |
| Face-down cards | 32 |
| Deal 3 taken | No |

The exact next row is inspected but not applied. Current static structure has
no empty column, two fully open non-empty columns, three visible same-suit
joins, and twelve visible mixed-suit boundaries. The analysis emits a non-flat
portfolio spanning critical excavation, campaigns, permanent joins, receiver
preparation, speculative work, and retained unexplained parks. The existing
campaign primary is not forced to the top economic position.

For the replay-verified research incumbent 172:

| Budget quantity | Value |
|---|---:|
| `g` | 23 |
| `h_deals` | 3 |
| `h_reveal_paid` | 1 |
| `h_admissible` | 4 |
| Hard minimum total | 27 |
| Maximum improving total | 171 |
| Hard headroom | 144 |

The current heuristic remaining-work estimate is 38, giving heuristic economic
slack 110. Those two values are diagnostics only; the large hard headroom is
reported honestly rather than inflated by heuristic campaign estimates.

## Research and production modes

In research mode, 172 is authoritative because its complete route replays. The
external score 119 is context showing that a much more economical solution may
exist, but no project-held 119 route exists and it never enters an
authoritative budget or pruning expression.

In production mode before a first solution, `incumbent=None`: there is no
artificial cap and no incumbent proof pruning. Economic project analysis is
unchanged. Once a complete replay-verified solution is found, its score can be
installed into the same budget object.

## Canonical post-freeze observations

The prospective project order, reveal values, costs, and tiers are frozen
before the canonical move file is opened. Only then does the diagnostic replay
the complete 172 route and classify its local placements. This validates that
the lifecycle vocabulary recognises both permanent joins and temporary debt.
Canonical future actions never influence project construction or constants.

No improvement over 172 is claimed.

## Proof-safety boundary

Proof-safe:

- corrected engine legality and replay;
- exact state facts and known stock rows;
- the existing proved remaining-deal/reveal lower bound;
- `g + h >= incumbent` pruning for a replay-verified incumbent.

Ordering-only:

- reveal structural scores and classifications;
- economic costs not independently bounded;
- estimated remaining work and economic slack;
- lifecycle/rehandling debt;
- rework return;
- frontier tiers; and
- economic dominance.

The ordering layer cannot be promoted to admissible proof pruning without a
separate formal proof of the relevant component and non-overlap with existing
bounds.

## Limitations and recommended next task

Project scores are deliberately transparent but still coarse. Excavation
benefits can overlap across campaigns, later stock geometry is prospective,
and many exit routes remain unbounded until a tactical realizer supplies a
legal replay. The estimated remaining-work total is therefore not a predicted
solution cost.

The recommended next task is a bounded tactical validation sprint: realize a
small number of top frontier projects and Tier-4 controls from cloned states,
measure corrected cost and actual lifecycle changes, and use those outcomes to
calibrate generic project evidence. Controller integration and whole-game
search should remain a later, separately gated change.
