# Common Priority Schema A/B v0.1

Base: `9e3240cdd30fbfdc8bf9f3cbc324caad2c91085b`

Deal: `4925153`

Seed: `0`

Arms: `CONTROL` and `COMMON_STAGE0`

## 1. Verdict

`REPRESENTATION_STARVATION_CONFIRMED`

Using one existing Stage-0 queue representation caused the controller to expand
397 broader-credit nodes and retain 1,806 broader-credit successors whose exact
states were absent from every CLEAN-generated successor in the treatment run.
Control expanded 400 CLEAN nodes and no broader-credit node. The intervention
therefore changed actual widening service and coverage, not just displayed rank.

This is not a recommendation to promote `COMMON_STAGE0`: it over-corrected toward
the broadest credit (389 of 400 expansions were credit 4), took 66% longer, and
still reached neither an actual empty column nor a foundation.

## 2. Exact code change

The bounded switch is `AnytimeControllerConfig.frontier_priority_schema`, whose
default is `LEGACY`. The chosen value is copied to the root and every ordinary
child as `StrategicSearchNode.frontier_priority_schema`; `dataclasses.replace`
therefore preserves it on analysed nodes and widening requeues.

`COMMON_STAGE0` changes queue ordering only:

* `strategic_progress_order_key()` uses the node's attached `stage0.ordering_key()`
  even when full analysis is attached.
* `_node_priority()` uses the existing lazy/Stage-0 positional offsets
  (`representative_index=1`, `continuity_index=4`) for those nodes.
* The node retains its real full analysis for expansion and successor generation.

Because all heap paths call `_node_priority()` or compare stored keys built by it,
the switch covers root/ordinary push, widening push, completion-reservation rekey,
epoch-transition rekey, and the stored priorities used by frontier sorting and
trimming. The special ordinary-order comparisons inside trimming also call the
same adapter. No tuple element is patched in isolation.

No successor family, scheduler lane order, resource planner, TT rule, frontier
width, credit limit, successor portfolio, tactical allocation, proof pruning, or
move-cost rule was changed. The production default remains byte-for-byte legacy
in behavior at the switch boundary.

## 3. A/B table

| Metric | CONTROL | COMMON_STAGE0 |
|---|---:|---:|
| Stop reason | strategic expansion limit | strategic expansion limit |
| Strategic expansions | 400 | 400 |
| Elapsed seconds | 523.406 | 870.791 |
| Tactical nodes | 1,049 | 34,423 |
| Successors generated | 1,105 | 2,549 |
| Successors retained | 914 | 1,815 |
| TT new / improved / suppressed | 915 / 0 / 191 | 1,740 / 76 / 734 |
| Final frontier entries | 256 | 256 |
| Distinct final node IDs | 256 | 256 |
| Duplicate final entries | 0 | 0 |
| Minimum face-down | 37 | 35 |
| Maximum foundations | 0 | 0 |
| Actual empty generated / retained / expanded | 0 / 0 / 0 | 0 / 0 / 0 |
| Proof prunes | 0 | 0 |
| Replay failures | 0 | 0 |
| Corrected-cost inconsistencies | 0 | 0 |

The treatment was 347.385 seconds (66.4%) slower at the common 400-expansion
prefix. Both arms nevertheless reached the requested expansion limit inside the
900-second allowance, so no elapsed-time truncation comparison was required.

## 4. Credit outcome

| Credit | CONTROL pushes | pops | expansions | trims | retained children | COMMON pushes | pops | expansions | trims | retained children |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 915 | 401 | 400 | 262 | 914 | 10 | 3 | 3 | 7 | 9 |
| 1 | 400 | 0 | 0 | 399 | 0 | 21 | 6 | 6 | 13 | 18 |
| 2 | 0 | 0 | 0 | 0 | 0 | 8 | 1 | 1 | 7 | 2 |
| 3 | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 1 | 2 | 2 |
| 4 | 0 | 0 | 0 | 0 | 0 | 1,785 | 417 | 389 | 1,115 | 1,784 |

Pushes include the root and ordinary retained children; pops can exceed expansions
when an already-expanded `(state, credit)` entry is popped and skipped. Trims count
removed frontier occurrences.

The first causally useful wider service was expansion 4. State
`7e14b4818ef7dfd8` had already expanded CLEAN at g=2, then its credit-1 widening
node (node 12) was expanded. Credit 1 exposed an `ECONOMIC_PROJECT /
workspace_excavation` successor with actions `(5,7,1) (5,2,1) (5,2,1) (5,3,1)`,
cost 4, corrected child g=6, and digest `e4a0de3a02754ba5`. It was independently
replay-valid, retained as node 13, created a fully revealed column, and was absent
from all CLEAN-generated coverage in this treatment. Node 13 was then expanded at
credit 1 on expansion 5.

Across the full treatment, 1,806 retained broader-credit successor states were
absent from all CLEAN-generated states in that arm. The exact rows, including
families, actions, costs, parent credit, child digest and geometry, are in the JSON
artefact. This definition is intentionally operational: it establishes additional
coverage in this run, not global mathematical unreachability by CLEAN search.

## 5. R2/R3 outcome

Control reproduced the expected four natural R2 states, none popped or expanded:

| Digest | Node | g | FD | Credit | Insert expansion/rank | Best / last rank | Popped | Expanded | Trimmed |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `1c3d3ec77bf164ad` | 378 | 5 | 39 | 0 | 116 / 148 | 148 / 257 | no | no | yes, expansion 211 |
| `edb1f739a3100867` | 419 | 6 | 38 | 0 | 128 / 32 | 11 / 36 | no | no | no; live |
| `de13114dc57870d7` | 430 | 7 | 37 | 0 | 131 / 169 | 169 / 255 | no | no | no; live |
| `f729fad6e19cb5b5` | 441 | 8 | 37 | 0 | 134 / 172 | 172 / 254 | no | no | no; live |

`1c3d3ec77bf164ad` was the sole Control R3 state; it was retained naturally and
trimmed without being popped. `edb1f739a3100867` again reached best rank 11 but
was never serviced. This closely reproduces the audit's structural pattern.

Treatment followed a different natural path, so neither named digest was
generated. It retained/pushed 1,813 R2 node entries (1,730 unique digests), popped
424, expanded 396, trimmed 1,134, and left 255 live. Thus the strong R2 service
outcome passed. Six unique R3 states were retained, but none was popped or
expanded; five were trimmed and one remained live:

| R3 digest | Node | g / credit | Insert expansion/rank | Best / last rank | Outcome |
|---|---:|---:|---:|---:|---|
| `5481589d5f04c257` | 17 | 7 / 1 | 5 / 3 | 3 / 255 | trimmed at 134 |
| `bf5a42ecfefd5ff4` | 18 | 7 / 1 | 5 / 3 | 2 / 254 | live |
| `67257953c862ece2` | 22 | 8 / 1 | 6 / 1 | 1 / 256 | trimmed at 136 |
| `4a9c3b4f295f77f2` | 23 | 8 / 1 | 6 / 1 | 1 / 255 | trimmed at 136 |
| `afc6d9383d829dce` | 37 | 11 / 2 | 10 / 1 | 1 / 256 | trimmed at 167 |
| `2fbec47f7ce43dca` | 47 | 12 / 4 | 13 / 4 | 4 / 254 | trimmed at 157 |

The machine artefact contains the full retained structural-node lifecycle rather
than special-casing either observation digest.

## 6. Search-progress outcome

Neither arm generated an actual empty or foundation. Treatment did improve the
minimum face-down count from 37 to 35 and expanded many fully revealed-column
states, but it did not service an immediately empty-creating R3 parent.

Expanded-node stock rows were:

| Stock rows undealt | CONTROL expansions | COMMON_STAGE0 expansions |
|---:|---:|---:|
| 5 | 10 | 1 |
| 4 | 98 | 5 |
| 3 | 292 | 394 |
| 2 | 0 | 0 |

Generated/retained stock distributions are recorded in the JSON. The first novel
wider successor's corrected g was 2 + 4 = 6 and its complete path replayed to the
same exact state and cost. All retained successors in both arms passed that same
full-path replay and cost check.

## 7. Performance

COMMON_STAGE0 used 32.8 times as many tactical nodes (34,423 versus 1,049) and
took 66.4% longer. It also generated 2.31 times as many successors. This is real
additional work unlocked by wider credit, not a queue-comparison cost alone.

The harness captured total elapsed and tactical-node use. It did not add new
component timers, so no additional economic/scheduler timing attribution is made.

## 8. Confounders

The following known defects were deliberately unchanged:

1. cheaper TT arrivals may not reopen an already-expanded `(state, credit)`;
2. trimmed states remain TT-seen and can suppress equal/higher-cost rediscovery;
3. overlapping frontier protection can duplicate node IDs.

Treatment observed 76 TT improvements and 734 suppressions; these figures should
not be read as reopen counts. No duplicate node ID was present in either final
frontier, but duplicate-protection semantics were not repaired. Proof pruning was
unchanged and unused (zero in both arms).

## 9. Interpretation

The experiment proves that incompatible queue representations were operationally
suppressing strategic widening at this commit and configuration. A common existing
representation changed broader-credit service from 0 to 397 expansions and
produced large, independently replay-valid new retained coverage.

It does not prove that COMMON_STAGE0 is a good production comparator, that credit
4 should dominate, that the 1,806 states are unreachable by all possible CLEAN
runs, or that wider credit alone solves the workspace bottleneck. In fact, the
treatment still starved every retained R3 node and reached no actual empty or
foundation.

All required gates passed:

* comparator invariant: PASS;
* Control structural reproduction: PASS;
* replay/cost integrity and unchanged proof pruning: PASS;
* broader-credit expansion plus genuinely additional retained coverage: PASS;
* strong outcomes: R2 expansion PASS; R3 expansion, actual empty, foundation FAIL.

## 10. Recommendation

Run one bounded follow-up A/B that reserves exactly one naturally generated R3
parent (defined structurally, never by digest) for ordinary expansion within the
same width and resource limits, to test whether existing production successors can
create the first replay-valid empty; do not add the resource planner in that test.

## Tests run

* `tests/test_common_priority_schema_ab_v0_1.py`: 5 passed.
* Controller/credit/natural-resource regression selection: 143 passed.
* Additional controller-v0.2 and resource-planner integrity selection: 64 passed.

Total successful tests: 212. An initial focused invocation without the repository's
required `PYTHONPATH=src` failed at import collection only; the corrected focused
run and all subsequent runs passed.

Machine-readable results: `docs/research/common_priority_schema_ab_v0_1.json`.
