# StateServiceRegistry v0.1

## 1. Verdict

`STATE_SERVICE_REGISTRY_READY`

The controller can now distinguish exact-state knowledge from execution of a
particular bounded service request.  All focused lifecycle contracts pass, the
registry ran in all three frozen treatment arms, replay and corrected-cost
integrity passed, exact state identity and proof pruning were not changed, and
the production defaults remain `LEGACY + INHERITED` with the registry disabled.

## 2. Exact registry contract

`StateServiceRegistry` is an explicitly bounded migration layer with separate
arrival and service records.  It is configured with maximum state and request
counts and raises a capacity error instead of silently dropping authoritative
lifecycle state.

The arrival key is the existing canonical Spider state key, unchanged.  The
v0.1 service key is:

`(canonical state, strategic credit, CURRENT_STRATEGIC_SUCCESSORS, BEST_ARRIVAL_STRATEGIC_NODE_V0_1)`

The final component is an explicit adapter contract rather than canonical game
identity.  It says that the registry retains the controller's selected best
`StrategicNode` witness and presents that witness to the existing successor
generator.  Decorative history on an equal or worse arrival neither replaces
the best witness nor creates a new request.

The registry stores one best arrival record, request references, and one
opaque witness reference per exact state.  It does not copy a full node into
each service request.  `CURRENT_STRATEGIC_SUCCESSORS` is the only v0.1 coverage
mode; arbitrary future project or policy work is deliberately out of scope.

## 3. State-arrival lifecycle

A new exact state installs corrected cost, replayable best-node witness, and
arrival version 1.  An equal or higher corrected-cost arrival is suppressed and
cannot overwrite either the cost or witness.  A cheaper legal arrival replaces
the cost and witness, increments the version monotonically, and reopens every
existing current-generator credit request for that state.

That reopening rule is intentionally minimal: current whole-generator work is
arrival-sensitive because it consumes the selected node context, so each
already known credit request receives one opportunity to run from the new best
arrival version.  It does not claim that arbitrary policy contexts are
equivalent or require replay.

The focused tests establish one best-cost record per exact state, non-increasing
best cost, witness replacement only on improvement, and version advancement
only on improvement.  The existing canonical state key implementation remains
the sole authority for structural equivalence.

## 4. Service-request lifecycle

The implemented statuses are `PENDING`, `LIVE`, `RUNNING`, `ATTEMPTED`,
`DEFERRED`, plus the explicit terminal diagnostic status `PROOF_PRUNED`.

- `PENDING`: valid requested coverage has no controller handle yet.
- `LIVE`: exactly one registered frontier handle represents the request.
- `RUNNING`: the handle passed version and ownership checks before analysis.
- `ATTEMPTED`: the bounded successor-generator call actually completed; its
  serviced arrival version, execution count, and outcome are retained.
- `DEFERRED`: a valid unexecuted request lost representation and retains access
  to the state's best witness for later activation.
- `PROOF_PRUNED`: the existing admissible proof path pruned a running request;
  it is not falsely counted as an attempted generator execution.

Repeated submissions coalesce into one request record.  Activation enforces at
most one live handle.  Frontier trimming routes a removed live handle to
`DEFERRED`; TT-suppressed rediscovery can reactivate pending/deferred coverage
from the retained best witness.  A successful pop transitions through
`RUNNING`, and only actual completion can mark `ATTEMPTED`.

## 5. D1–D4 defect results

| Defect | Result | Evidence |
|---|---|---|
| D1 — cheaper arrival reopening | Pass | The deterministic test first demonstrates that legacy `(state, credit)` membership remains suppressive after TT improvement.  Registry mode replaces the witness, advances the arrival version, reopens the old request, and executes it once at the lower cost.  Frozen P2 also produced 12 cheaper arrivals and 16 reopenings. |
| D2 — evicted unserved work | Pass | A live handle is evicted to `DEFERRED` without becoming `ATTEMPTED`; the best witness survives, reactivation succeeds, and the request executes exactly once.  The frozen frontier did not reach its 256-entry cap, so the natural frozen count is zero and the deterministic regression is the acceptance evidence. |
| D3 — duplicate sharing | Pass | Duplicate submissions share one request record and one live handle; a second activation is rejected and only one execution is recorded.  The frozen arms coalesced 740 duplicate submissions in total. |
| D4 — state-local widening | Pass | CLEAN and every wider credit are distinct request keys, each applicable request executes once per arrival version, and ordinary children of a broad expansion continue to start CLEAN.  No inherited-credit propagation was introduced. |

All ten listed registry invariants, best-witness suppression/replacement, status
transitions, and default-mode constraints are covered by 13 focused tests.

## 6. Stale-handle behaviour

Every registry-backed frontier pop calls `begin(handle_id)` before the existing
expensive controller analysis.  The call verifies handle ownership, request
status, live-handle identity, and arrival version.  Unknown, superseded, or
otherwise obsolete handles return no witness and cannot enter successor
generation.

The deterministic test uses a newer arrival to invalidate a queued old-version
handle and proves that the supplied analysis counter remains zero.  In the
frozen P2 run, three such old-version handles were rejected before analysis.
P0 and P7 rejected none.  Total frozen stale rejections were 3 and live-handle
invariant violations were 0.

## 7. Existing-controller integration

The registry wraps the existing admission, request, frontier representation,
pop validation, completion, widening, proof-prune, trim/defer, and rediscovery
points.  The whole strategic successor generator, scheduler, tactical
allocation, corrected MobilityWare cost, canonical identity, and ordinary
state-local child-credit helper remain intact.

Integration is behind `enable_state_service_registry=False`.  Enabling v0.1 is
accepted only for `COMMON_STAGE0 + STATE_LOCAL`; unsupported legacy-mode mixes
fail explicitly.  With the switch off, the prior `expansion_credits` path is
still used.  Global defaults remain `LEGACY` priority and `INHERITED` credit
propagation.

Telemetry exposes registry state/request counts, all lifecycle status counts,
cheaper arrivals, reopenings, eviction/defer events, reactivations, duplicate
coalesces, pre-analysis stale rejections, invariant violations, service
executions, and a deterministic shallow memory estimate.

The focused registry tests passed (`13 passed`).  The relevant controller,
state-identity, collision, common-priority, state-local, and v0.2 regression
selection passed on the final tree (`118 passed in 78.21s`).  Because the
integration crosses the production controller loop, the full suite was also
run: it completed with an empty failure cache across 2,042 collected test
nodes.

## 8. Frozen behavioural comparison

The committed configuration used P0/4925153, P2, and P7; 80 strategic
expansions; 120,000 tactical-node and 240-second ceilings; frontier 256;
successor cap 10; credit 0–4; seed 0; scheduler and tactical allocation enabled;
`COMMON_STAGE0 + STATE_LOCAL`; and no workspace service, grace/stock guard, or
resource planner.  Run order was counterbalanced on P2.

| Deal | Arm | Strategic | Tactical | Elapsed (s) | TT new/improved/suppressed | Min face-down | Stock rows | Foundations | Best progress |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 | Legacy | 80 | 20,126 | 170.487 | 142/0/234 | 38 | 3 | 0 | `57e776f099a0b7c6` |
| P0 | Registry | 80 | 20,637 | 170.394 | 142/0/234 | 38 | 3 | 0 | `57e776f099a0b7c6` |
| P2 | Legacy | 80 | 25,542 | 115.553 | 127/5/278 | 41 | 4 | 0 | `4d67539f2e5b6949` |
| P2 | Registry | 80 | 25,706 | 119.096 | 120/12/279 | 41 | 4 | 0 | `4d67539f2e5b6949` |
| P7 | Legacy | 80 | 3,895 | 99.954 | 151/0/211 | 38 | 1 | 0 | `4dcad73819bb4098` |
| P7 | Registry | 80 | 3,918 | 99.935 | 151/0/211 | 38 | 1 | 0 | `4dcad73819bb4098` |

All six runs completed at the strategic limit and all best-progress replay and
cost checks passed.  Strategic-expansion, face-down, stock, foundation, credit
distribution, and best-progress deltas were zero on every pair.

P7's trajectory was identical.  P2's changed trajectory is causally associated
with the intended D1 correction: 12 TT improvements caused 16 request reopenings
and three stale-handle rejections, changing exact TT composition while retaining
the same endpoint.  P0's trajectory digest changed even though state/TT counts,
generated and retained successors, credits, and endpoint were identical, and no
arrival-lifecycle event occurred.  Its additional 511 tactical visits are
consistent with timing/resource-bound tactical realizer jitter after registry
bookkeeping; this is an inference, not evidence of a lifecycle correction.

## 9. Runtime/memory overhead

Treatment/control elapsed ratios were P0 `0.99946`, P2 `1.03066`, and P7
`0.99981`; median `0.99981`, range `0.99946–1.03066`.  The largest observed
runtime increase was 3.07% on P2, the only frozen deal exercising cheaper
arrival reopening.  Tactical-node deltas were +511, +164, and +23 respectively.

The three treatment runs retained 413 registry states and 613 service requests:
P0 142/209, P2 120/183, and P7 151/221.  Their combined deterministic shallow
footprint was 305,728 bytes (105,308; 90,168; 110,252), averaging 101,909 bytes
per run, approximately 499 bytes per request or 740 bytes per state.  This
estimate includes Python containers and record objects but excludes shared
witness object graphs; witnesses are referenced rather than duplicated.

Across treatment runs there were 240 actual service executions, 12 cheaper
arrival updates, 16 reopenings, 740 duplicate coalesces, three stale rejections,
zero live-handle violations, and zero natural frontier deferrals/reactivations.

## 10. Remaining context-model limitations

The temporary adapter preserves the selected best `StrategicNode`, including
the extensive context already consumed by the current generator, but v0.1 does
not prove arbitrary scheduler, campaign, continuation, provenance, or future
project contexts equivalent.  Only current state-local whole-generator coverage
at an explicit credit level is modeled.  Submission counts are diagnostic, not
a persistent general subscriber model.

Deferred work is reactively restored when relevant suppressed rediscovery is
observed; v0.1 does not add a policy for proactively scheduling every deferred
request.  The frozen envelope did not naturally trim the frontier, so D2 rests
on deterministic integration-level evidence rather than a panel event.

The architecture review's separate foundation finding remains: the current-
epoch foundation realizer can require explicit campaign demand that normal
demand derivation may not create.  This migration neither repairs nor changes
foundation demand/ownership semantics.  It also does not introduce portfolios,
budgets, rotation, workspace/N8/cap-2/stock-lag policy, or the resource planner.

## 11. One next bounded migration task

Migrate the existing completion-cash-out and epoch-transition frontier
reservations into registry subscribers of the same state/credit service request,
while preserving their present priorities and quotas.  The bounded experiment
should measure duplicate representations and prove one shared live/execution
handle; it must not add strategic portfolio policy.
