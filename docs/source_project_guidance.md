# Shared-helper source-project guidance

## Scope and gate

This experiment tests one narrow hypothesis: a residual foundation campaign may
stall because the tableau beam does not remain committed to its source-exposure
projects and their shared prerequisites. It does not change campaign scores,
campaign ranking, readiness, rules, corrected MobilityWare accounting, or the
solution archive. It neither deals the third stock row nor runs a whole-game
search.

Only an independently replayed second foundation removal passes the gate.
Source exposure or useful tableau progress without that removal is diagnostic
evidence, but the verdict remains `FAIL`.

## Generic model

`campaign_source_projects.py` converts every remaining MUST tableau source for
one fixed campaign identity into a `CampaignSourceProject`. A project records:

- all usable interchangeable physical sources for each rank;
- the selected source column and target-relative reveal prefix;
- destination ranks, helper dependencies, and temporary-space need;
- current rank satisfaction, nearby campaign bands, and join distance.

`CampaignHelperTask` represents a structural prefix reduction on another
column. Tasks are max-unioned by column: if two projects need depths one and
two, both depend on the single depth-two task, and the helper is searched and
charged once. Priority is causal: helpers with the most dependants and the
nearest join come first, followed by the selected source prefix. Workspace is
handled inside the committed excavation primitive; direct band joining is
left to the existing transition/removal search.

The bounded realizer keeps a helper or source target committed until its
predicate succeeds, the bounded search ends, resources expire, or fixed-
identity reanalysis invalidates it. It reuses target-relative closure,
committed excavation, engine legality, corrected structural identity, and the
existing campaign transition/removal beam. It is orchestration, not a second
broad tableau search engine.

## Verified starting state

The diagnostic reconstructs the benchmark entirely through public APIs:

1. the supplied six-move fixture;
2. the Deal-1 campaign realizer;
3. the S#1 Deal-2 removal realizer;
4. the verified 24-cost residual transition.

The resulting state independently replays at corrected cost 47 with 47
actions, exactly two deals, 30 stock cards, one Spade foundation, 21 face-down
cards, and structural equality to the stored state. Reanalysis preserves the
previously advanced primary exactly: `H#1@D2`.

Its remaining MUST sources are `Jh`, `9h`, and `3h`. The generic model derives:

- source column 2 (one-based), ranks J and 9, four required reveals;
- source column 5, rank 3, two required reveals;
- one shared helper on column 10, requiring one card of prefix reduction;
- protected structural bands K-Q, 8-4, and 2-A of Hearts.

The helper has two dependency edges, one to each source project, and appears
once in the priority order.

## Frozen prospective A/B result

Both arms start from the same cost-47 state and fixed campaign identity. At
added-cost bounds 6, 10, 15, 20, and 28, each arm is configured with 50,000
nodes and a 12-second time limit. The existing transition search checks its
time limit between expansion batches, so its observed wall time can exceed the
configured value; the table reports the actual measurements from the frozen
run.

| Bound | Existing transition | Guided source projects |
|---:|---|---|
| 6 | `PARTIAL`, +1, MUST 3→3, 3,208 nodes, 17.596s | `PROJECT_ADVANCED`, +2, helper 0→1, one reveal, 6,122 nodes, 12.672s |
| 10 | `RESOURCE_LIMIT`, +1, MUST 3→3, 3,703 nodes, 20.955s | `PROJECT_ADVANCED`, +2, helper 0→1, one reveal, 6,209 nodes, 12.598s |
| 15 | `RESOURCE_LIMIT`, +1, MUST 3→3, 3,672 nodes, 21.285s | `PROJECT_ADVANCED`, +2, helper 0→1, one reveal, 6,124 nodes, 12.600s |
| 20 | `RESOURCE_LIMIT`, +1, MUST 3→3, 3,678 nodes, 20.952s | `PROJECT_ADVANCED`, +2, helper 0→1, one reveal, 5,975 nodes, 12.592s |
| 28 | `RESOURCE_LIMIT`, +1, MUST 3→3, 3,649 nodes, 20.890s | `PROJECT_ADVANCED`, +2, helper 0→1, one reveal, 6,102 nodes, 12.734s |

No arm exposes a campaign source rank or removes a foundation. Reanalysis of
the best partial guided state reports six current MUST source keys because the
K-Q band is temporarily covered; this is state-relative source selection, not
a change to campaign scoring.

## Best guided progression

The best bounded prefix is the same at every tested bound:

1. move the entire column-10 helper run to column 7 (`move 10 7 11`), cost 1;
2. move the ten-card 8-4 Heart band and its cover from column 2 to the now-free
   column 10 (`move 2 10 10`), cost 1.

The first action satisfies the one shared helper for both projects. The second
keeps commitment to the first source project and reduces its face-down count
from five to four. The K-Q, 8-4, and 2-A structural bands remain intact; K-Q is
covered rather than split. The resulting prefix independently replays from the
true opening at corrected cost 49, still with exactly two deals and 30 stock
cards.

Stage A then ends at a resource limit with no required Heart rank usable. Stage
B is therefore not entered: handing the state to removal search before source
predicates are satisfied would defeat the two-stage experiment.

## Foundation gate and blocker

The final prospective facts are:

- foundations: 1→1;
- added foundation suits: none;
- stock epoch: 2;
- face-down cards: 21→20;
- longest same-suit run: 5→5;
- same-suit run mass: 40→41;
- independent best-prefix replay: true;
- complete route to a second removal: none.

The verdict is **FAIL**. The exact blocker class is **source exposure**. The
shared helper is not the remaining blocker: it is completed once and unlocks
both project dependencies. The first committed source prefix advances one
reveal, but J, 9, and 3 of Hearts remain unavailable at every tested bound.
This is a bounded, resource-limited miss, not an impossibility proof. Band
joining, workspace for the final join, and final placement are not reached.

## Canonical comparison after the freeze

Only after the prospective result was frozen did the diagnostic load the
canonical moves. The canonical foundation order is
`S, D, C, D, S, C, H, H`. Its two-foundation milestone is command 140 at
corrected cost 139, with order `S, D`, three face-down cards, ten stock cards,
and two empty columns. The prospective best partial state is cost 49 with one
foundation, 20 face-down cards, 30 stock cards, and no empty columns.

This comparison is descriptive only. It claims neither canonical agreement
nor a complete-solution improvement.

## Next experiment

Per the hard gate, no further Heart-specific adjustment is made here. The next
action is an equal-resource `H#1` versus `D#1` campaign comparison from the
verified cost-23 residual state.

Run the report with:

```powershell
$env:PYTHONPATH = 'src'
py -m spider.planner.diagnostics.source_project_guidance_report
```
