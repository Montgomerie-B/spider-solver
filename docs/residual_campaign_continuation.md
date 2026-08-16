# Residual campaign continuation to actual removal

## Scope and hard result

This diagnostic asks one narrow question: can the campaign advanced by the
verified cost-47 residual transition be resumed and actually removed before
Deal 3? It reuses `realize_residual_campaign_transition` directly; no second
tactical engine, strategic layer, scoring change, readiness threshold,
`plan_search` change, or whole-game search was added.

The hard-gate result is **FAIL**. The tested continuation did not remove a
second foundation. It made one legal paid move, but foundation count remained
one at every bound. Campaign advancement is intentionally not treated as a
pass.

## Public-API reconstruction

The diagnostic loads the true deal and constructs the existing six-move
fixture. It then calls `realize_campaign_to_next_epoch` for Deal 1,
`realize_campaign_to_removal_epoch` for S#1 at Deal 2, and
`realize_residual_campaign_transition` with the previously verified bound-24
configuration. Independent replay from the opening establishes:

- corrected cost 47 and 47 actions;
- exactly two stock deals, current epoch 2, and 30 stock cards;
- one completed foundation, Spades only;
- 21 face-down cards and no empty columns; and
- stored and replayed states are structurally equal.

Failure of any reconstruction invariant stops the diagnostic before the new
continuation is attempted. The full historical route is confined to benchmark
diagnostic data; generic production logic contains no recorded route, suit,
column, or move constants.

## Reanalysed portfolio

The portfolio is recomputed from the cost-47 state before any canonical data
is read:

| Role | Campaign | Target | Risk-adjusted objective | Score | Remaining cost | Readiness | MUST | Stock |
|---|---|---:|---:|---:|---:|---|---:|---:|
| Primary | H#1 | Deal 2 | 17.0 | 107.0 | 15.0 | excavation-led / medium | 3 | 0 |
| Runner-up | D#1 | Deal 4 | 32.0 | 78.4 | 14.0 | excavation-led / low | 8 | 3 |
| Deferred | C#1 | Deal 5 | 45.0 | 57.6 | 21.0 | excavation-led / low | 6 | 6 |
| Deferred | S#2 | Deal 5 | 52.0 | 32.6 | 28.0 | deferred / low | 6 | 6 |

H#1 is the same outstanding suit, copy index, and target epoch advanced by the
previous transition, so the continuation gate opens. The identity is frozen
while interchangeable physical sources remain eligible after reanalysis.

## Structural campaign state

The generic band locator rediscovers these intact, movable Heart bands:

- 8H-4H in column 2;
- KH-QH in column 7;
- 2H-AH in column 8;
- 10H in column 4; and
- 6H in column 3.

None is covered, but no pair can join directly. The three remaining MUST
sources are JH and 9H in column 2 and 3H in column 5. They form two independent
source projects. Both projects share the same helper prerequisite, column 10
at reveal depth one, so that preparation is max-unioned rather than charged
twice. The workspace policy is `CREATE_THEN_SPEND`, with one workspace unit
estimated to cost one move.

Fresh obligations are derived from the changed tableau:

1. expose interchangeable JH, 9H, and 3H sources;
2. preserve or join the existing 8H-4H, KH-QH, and 2H-AH bands;
3. optionally create one workspace unit;
4. connect QH through AH;
5. assemble and trigger one Hearts foundation removal; and
6. verify exactly that removal.

Each contiguous band contributes one preservation obligation. Its individual
ranks are not duplicated as separate obligations.

## Iterative bounded continuation

All runs begin at the independently verified cost-47 state, remain
tableau-only, and prohibit Deal 3.

| Added-cost bound | Status | Added | Total | Nodes | Runtime | MUST | Obligations | Foundations |
|---:|---|---:|---:|---:|---:|---|---|---|
| 6 | PARTIAL | 1 | 48 | 6,657 | 26.862 s | 3 to 3 | 4/10 | 1 to 1 |
| 10 | PARTIAL | 1 | 48 | 10,914 | 41.627 s | 3 to 3 | 4/10 | 1 to 1 |
| 15 | PARTIAL | 1 | 48 | 17,507 | 62.173 s | 3 to 3 | 4/10 | 1 to 1 |
| 20 | RESOURCE_LIMIT | 1 | 48 | 16,893 | 69.527 s | 3 to 3 | 4/10 | 1 to 1 |
| 28 | RESOURCE_LIMIT | 1 | 48 | 17,096 | 69.610 s | 3 to 3 | 4/10 | 1 to 1 |

The three smaller beams were exhausted or truncated. The two larger runs hit
their wall-clock cap. These are resource-relative misses, not impossibility
proofs.

Every run chose the same auxiliary move:

```text
move 3 1 2
```

It exposes one face-down card and relocates the 6H band, but it does not expose
JH, 9H, or 3H and does not produce a direct band join. The best complete replay
therefore has 48 actions and corrected cost 48: the verified 47-action route
in `residual_campaign_transition.md`, followed by this one move. Because no
removal succeeded, there is no successful complete removal route to record.

## Foundation verification and final audit

Independent replay verifies the 48-action stored state exactly. It has:

- foundation count 1 to 1, with no newly added suit;
- no continuation deal, current epoch 2, and stock size 30;
- 20 face-down cards and no empty columns;
- 11 legal tableau moves and four fully open columns;
- workspace creation estimate one;
- longest visible same-suit run five and run mass 41; and
- unchanged three-source MUST burden.

Automatic K-to-A removal was never triggered. Consequently there is no
triggering move or corrected-cost removal event to validate.

## Exact blockers

The remaining structural blockers are precise:

- JH and 9H remain buried in the first source project;
- 3H remains buried in a second source project;
- both projects depend on the same one-reveal column-10 helper;
- none of the five current Heart bands can join directly; and
- the bounded beam did not expose any of the three blockers.

Only after all five prospective runs were frozen did the diagnostic parse the
canonical trace. Canonical removes foundations in the order S, D, C, D, S, C,
H, H. Its comparable first-foundation state is at corrected cost 90 with eight
face-down cards, epoch 2, stock 30, and run mass 53. Its second foundation is
Diamonds at corrected cost 139 after Deal 4. This is validation context only;
canonical agreement and a complete-solution improvement are not claimed.

The inexpensive failure-only counterfactual reports D#1 from the original
cost-23 residual state as `ADVANCE_ONE_EPOCH`, target Deal 4, seven MUST
sources, and three stock-supplied sources. Deal 3 would supply QD and 5D. No D
search is run.

## Tests, limitations, and next action

Focused tests cover public reconstruction, deterministic reanalysis, primary
identity gating, band rediscovery, band-obligation deduplication,
interchangeable sources, no-deal enforcement, automatic foundation detection,
foundation suit/count checks, independent replay and accounting, bounded
failure semantics, and absence of benchmark constants from production code.
The campaign transition/removal/realizer/campaign and directly reused
rules/metrics/workspace/state-identity regressions are also run.
The combined focused regression invocation passes 120 tests, including all 13
new continuation tests.

The tactical beam remains heuristic. Its resource-limited result establishes
only that no removal was found under these bounds and caps. Reported runtimes
are environment-dependent.

The recommended next action is a separate, narrow investigation of source
project and shared-helper guidance in the existing tableau beam, starting from
this exact replayable residual state. It should preserve the frozen campaign
identity and no-Deal-3 constraint, measure whether JH/9H and 3H exposure is
actually improved, and avoid changes to scores or readiness policy.

Run the diagnostic with:

```text
python -m spider.planner.diagnostics.residual_campaign_continuation_report
```
