# Resource excavation later-phase shadow v0.1

**Status:** complete. No controller integration, no operator changes, no v0.9.

**Start SHA:** `93a2cf9606cc3cfafa4186b92da3907c6237d0e4`

**Branch:** `agent/resource-excavation-later-phase-shadow-v0-1`

**Decision: D. PRODUCTION DOES NOT REACH RESOURCE GEOMETRY IN THE BOUNDED CONTINUATION FOREST**

State-only restart is faithful. A width-4 × six-generation production-only
continuation forest deals the entire stock and never produces an empty
column, a fully revealed column, an empty-creatable column, a foundation,
or min face-down ≤ 1.

The unchanged resource planner was therefore not given later-phase geometry
to exploit. That is an upstream production result, not a planner failure.

Recommended next step (not taken here):

> Diagnose the production first-empty / full-reveal bottleneck directly,
> upstream of the resource planner.

## Restart fidelity

The reproducible 25-expansion opening run was recaptured. Eight expanded
parents were selected by canonical digest order only.

Each was restarted as a fresh v0.8 search from the cloned `SpiderState`
(`expansions=1`) with the original 104-card deal.

| digest | original g | generated set | retained set | class |
| --- | --- | --- | --- | --- |
| `021a7380370396fe` | 10 | equal | TT-divergent | `STATE_ONLY_RESTART_EQUIVALENT` |
| `30b1cd213a2956ed` | 7 | equal | equal | `STATE_ONLY_RESTART_EQUIVALENT` |
| `38ca4cbe24e07b09` | 8 | equal | equal | `STATE_ONLY_RESTART_EQUIVALENT` |
| `3943a81991e43d75` | 4 | equal | TT-divergent | `STATE_ONLY_RESTART_EQUIVALENT` |
| `5591fe7440637e26` | 6 | equal | TT-divergent | `STATE_ONLY_RESTART_EQUIVALENT` |
| `55a4e5534aa202dc` | 7 | equal | equal | `STATE_ONLY_RESTART_EQUIVALENT` |
| `564b6aa649b89649` | 9 | equal | TT-divergent | `STATE_ONLY_RESTART_EQUIVALENT` |
| `565d1de7d0f17f9e` | 10 | equal | equal | `STATE_ONLY_RESTART_EQUIVALENT` |

Generated successor kinds, action sequences, child canonical identities and
corrected costs match in all 8 cases, including scheduler-ranked edges.
Credit level was CLEAN (0) on every fixture.

Retained-set mismatches are original-run TT occupancy: an isolated restart
admits children the in-run TT already held. That is search-context, not
tableau-state divergence. Gate 2 was not required.

Continuation identity is the canonical state digest. Continuation context
is the `SpiderState` only.

## Continuation forest

Each production run used the existing envelope: 25 expansions, 300k tactical
nodes, 180s wall-clock, scheduler on, allocation on, seed 0. The expansion
cap bound every run.

Root selection: 4 highest-priority unexpanded retained frontier nodes using
production `_node_priority` with `node_id` stripped; canonical digest
tie-break. Not geometry, not resource outcome, not the 172-move route.

| gen | roots | retained states | frontier | fd min/med | G1 | G2 | G3 | G4 | G5 | stock rows | empties | foundations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | 58 | 33 | 43 / 43 | 0 | 0 | 0 | 0 | 0 | 2–5 | 0 | 0 |
| 1 | 4 | 312 | 212 | 44 / 44 | 0 | 0 | 0 | 0 | 0 | 0–4 | 0 | 0 |
| 2 | 4 | 142 | 67 | 44 / 44 | 0 | 0 | 0 | 0 | 0 | 0–1 | 0 | 0 |
| 3 | 4 | 133 | 60 | 44 / 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 4 | 4 | 56 | 8 | 44 / 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 | 4 | 95 | 26 | 44 / 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 6 | 4 | 83 | 20 | 44 / 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Generations executed: 7 (opening + 6 continuations). Roots executed: 1 + 24 = 25
bounded production runs. This is a research corpus, not one ordinary v0.8 search.

By generation 3 the stock is exhausted. Face-down remains 44. Production is
dealing through the deck without uncovering buried cards or creating space.

## Trigger corpus

| trigger | unique states | earliest generation |
| --- | ---: | ---: |
| G1 idle empty | 0 | never |
| G2 fully revealed | 0 | never |
| G3 empty-creatable | 0 | never |
| G4 foundation | 0 | never |
| G5 low buried depth | 0 | never |

No G1/G2/G3 state appeared. The forest was not widened.

## Resource audit

Zero harvested states, so P and S target counts are 0. The resource planner
was not asked to explain a later-phase sample that does not exist.

`NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR` under P: **0**  
under S: **0**

Architectural reading:

`production must first create/reveal workspace geometry → resource planner can then exploit it`

This experiment confirms the dependency. In this bounded production-only
forest, v0.8 never creates that geometry. The resource planner is therefore
not the mechanism that solves first-empty / early excavation; it is also
not testable as a later-phase accelerator until production actually reaches
later-phase states.

## Pytest

Complete suite after this diagnostic:

`1844 passed, 37 xfailed in 1240.94s`

0 unexpected failures. The node-78 test was not modified.

## Production non-changes

`anytime_controller.py` and `resource_excavation_planner.py` unchanged.
No 172-move route, no node 78, no v0.9.
