# State-Local Strategic Credit Experiment v0.1

Base: `20383df3567cef7823c463c35fb8c773ff285f0b`

Deal: `4925153`

Seed: `0`

Arms: `LEGACY`, `COMMON_STAGE0_INHERITED`, and
`COMMON_STAGE0_STATE_LOCAL`

## 1. Verdict

`STATE_LOCAL_CREDIT_CONFIRMED`

State-local credit produced a functioning iterative-widening regime. Arm C
expanded broader-credit states, retained 255 operationally novel broader-credit
successors (253 unique digests), reset every ordinary child of a broader parent to
CLEAN, and subsequently expanded 50 of those novel digests at CLEAN. Expansion
service was distributed `[90, 81, 77, 76, 76]` over credits 0–4 instead of Arm B's
`[3, 6, 1, 1, 389]` avalanche.

This verdict is about credit semantics, not overall solving quality. Arm C used
more tactical nodes than Arm B, regressed minimum face-down from 35 to 36, and
still expanded no R3 state, created no actual empty, and reached no foundation.

## 2. Exact semantic change

The guarded switch is
`AnytimeControllerConfig.strategic_credit_propagation` with values `INHERITED`
and `STATE_LOCAL`. Its production default is `INHERITED`.

Immediately after the existing ordinary `StrategicSearchNode` child is built, the
small adapter `_apply_ordinary_child_credit_semantics()` applies one rule:

* `INHERITED`: the ordinary child keeps the parent's `StrategicCreditLevel`;
* `STATE_LOCAL`: the ordinary child starts at `StrategicCreditLevel.CLEAN`.

The adapter uses `dataclasses.replace` only when the credit must change. Analysis,
Stage-0 facts, actions, corrected g, incoming edge, continuation evidence,
milestones, obligations, target lineage, completion context, scheduler state, and
all other node metadata are preserved.

The original same-state widening statement remains inline and unchanged:

`widened = replace(node, node_id=uid, credit_level=next_credit)`

Thus an exact state still earns credit N+1 after its N expansion. Only an ordinary
new successor's initial strategic credit differs. `FrontierPrioritySchema` remains
an independent research switch and defaults to `LEGACY`.

## 3. Three-arm comparison

| Metric | A: LEGACY | B: COMMON + inherited | C: COMMON + state-local |
|---|---:|---:|---:|
| Stop reason | expansion limit | expansion limit | expansion limit |
| Expansions | 400 | 400 | 400 |
| Credit 0 expansions | 400 (100%) | 3 (0.75%) | 90 (22.5%) |
| Credit 1 expansions | 0 | 6 | 81 |
| Credit 2 expansions | 0 | 1 | 77 |
| Credit 3 expansions | 0 | 1 | 76 |
| Credit 4 expansions | 0 | 389 (97.25%) | 76 (19.0%) |
| Wider-credit expansions | 0 | 397 | 310 |
| Elapsed seconds | 526.949 | 869.981 | 565.529 |
| Tactical nodes | 1,043 | 33,379 | 52,516 |
| Generated successors | 1,105 | 2,549 | 1,909 |
| Retained successors | 914 | 1,815 | 507 |
| TT new / improved / suppressed | 915 / 0 / 191 | 1,740 / 76 / 734 | 504 / 4 / 1,402 |
| Novel wider retained | 0 | 1,806 | 255 |
| Novel wider then CLEAN-expanded | 0 | 0 | 50 |
| Minimum face-down | 37 | 35 | 36 |
| Maximum foundations | 0 | 0 | 0 |
| Actual empty generated / retained / popped / expanded | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| R2 unique retained / expanded | 4 / 0 | 1,730 / 393 | 494 / 87 |
| R3 unique retained / expanded | 1 / 0 | 6 / 0 | 10 / 0 |
| Final frontier size / distinct IDs / duplicates | 256 / 256 / 0 | 256 / 256 / 0 | 255 / 255 / 0 |
| Replay failures / cost inconsistencies / proof prunes | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

A versus B reproduces the previous comparator result: legacy priority completely
starved widening, while common representation exposed it and reproduced exactly
the prior `[3, 6, 1, 1, 389]` expansion distribution and 1,806 novel broader
successors. Tactical nodes differed slightly from the prior timing-sensitive
34,423 count; the structural result did not.

B versus C is decisive. CLEAN share rose by 21.75 percentage points and credit-4
share fell by 78.25 points. C did not collapse to CLEAN and did not maintain a
credit-4 ecosystem: every credit received 76–90 expansions.

## 4. Credit-flow analysis

### Credit lifecycle

| Arm / credit | Pushes | Pops | Expansions | Trims | Retained children produced | Unique retained child digests | Tactical nodes attributable |
|---|---:|---:|---:|---:|---:|---:|---:|
| A / 0 | 915 | 401 | 400 | 262 | 914 | 914 | 1,043 |
| A / 1 | 400 | 0 | 0 | 399 | 0 | 0 | 0 |
| A / 2–4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| B / 0 | 10 | 3 | 3 | 7 | 9 | 9 | 19 |
| B / 1 | 21 | 6 | 6 | 13 | 18 | 18 | 170 |
| B / 2 | 8 | 1 | 1 | 7 | 2 | 2 | 741 |
| B / 3 | 3 | 1 | 1 | 2 | 2 | 2 | 597 |
| B / 4 | 1,785 | 417 | 389 | 1,115 | 1,784 | 1,708 | 31,852 |
| C / 0 | 508 | 94 | 90 | 173 | 238 | 238 | 295 |
| C / 1 | 90 | 81 | 81 | 0 | 23 | 23 | 5,714 |
| C / 2 | 81 | 77 | 77 | 0 | 129 | 129 | 15,967 |
| C / 3 | 77 | 76 | 76 | 0 | 42 | 42 | 13,427 |
| C / 4 | 76 | 76 | 76 | 0 | 75 | 75 | 17,113 |

Retained-child columns are attributed to the expanding parent's credit. Tactical
attribution covers work observed inside successor generation and sums to each
arm's total tactical-node count.

Same-state widening pushes in C were 90 into credit 1, 81 into credit 2, 77 into
credit 3, and 76 into credit 4. Ordinary pushes all landed at credit 0: 507 CLEAN
children plus the CLEAN root account for the 508 credit-0 pushes. Parent→child
retained transitions were:

| Parent credit | Child credit | Count |
|---:|---:|---:|
| 0 | 0 | 238 |
| 1 | 0 | 23 |
| 2 | 0 | 129 |
| 3 | 0 | 42 |
| 4 | 0 | 75 |

Arm B instead retained `0→0: 9`, `1→1: 18`, `2→2: 2`, `3→3: 2`, and
`4→4: 1,784`. That directly confirms inherited branch-wide freedom as the
mechanism behind the credit avalanche.

Final frontier credit distributions were:

* A: `[255, 1, 0, 0, 0]`;
* B: `[0, 2, 0, 0, 254]`;
* C: `[241, 9, 4, 1, 0]`.

C therefore ended with new states waiting primarily for CLEAN service, while
same-state higher-credit requeues were being consumed rather than accumulating.

### First useful wider-credit flow

All common-schema arms first serviced broader credit at expansion 4. State
`7e14b4818ef7dfd8`, g=2, expanded at credit 1 and produced the replay-valid
`ECONOMIC_PROJECT / workspace_excavation` sequence
`(5,7,1) (5,2,1) (5,2,1) (5,3,1)`, cost 4, child g=6, digest
`e4a0de3a02754ba5`. That child was absent from CLEAN-generated successor coverage.

The naturally serviced two-generation trace exposes the semantic difference:

* B: credit-1 parent → `e4a0...` credit 1 → `5556...` credit 1 →
  `947a...` credit 1; all three descendants expanded at credit 1.
* C: credit-1 parent → `e4a0...` CLEAN → `5556...` CLEAN →
  `947a...` CLEAN; all three descendants expanded at CLEAN.

No service was forced to obtain this trace.

## 5. Novel-coverage analysis

Arm B retained 1,806 novel broader-credit successors (1,730 unique), almost all
from its inherited credit-4 ecosystem. None subsequently received a CLEAN
expansion.

Arm C retained 255 novel broader-credit successors (253 unique):

| Parent credit | Novel retained |
|---:|---:|
| 1 | 21 |
| 2 | 127 |
| 3 | 38 |
| 4 | 69 |

By successor family, Arm C produced 153 `ECONOMIC_PROJECT`, 33
`PREPARE_THEN_DEAL`, and 69 `RAW_TABLEAU_MOVE` novel retained successors. Fifty
unique novel digests later received a CLEAN expansion. This is direct evidence of
the intended cycle: broader coverage discovers a new state; that state starts and
is serviced at CLEAN; it may later earn its own widening.

C retained less broad coverage than B, partly because resetting exact child states
to CLEAN exposes them to the unchanged exact TT. The 1,402 suppressions and the
known trimmed-state/reopen defects remain confounders. Still, 255 discoveries and
50 CLEAN continuations are materially useful coverage, so the experiment does not
support `STATE_LOCAL_CREDIT_LOSES_USEFUL_COVERAGE`.

## 6. Search-progress analysis

| Structural metric | A | B | C |
|---|---:|---:|---:|
| R2 generated events / unique digests | 4 / 4 | 2,537 / 1,730 | 1,897 / 494 |
| R2 retained events / unique digests | 4 / 4 | 1,806 / 1,730 | 498 / 494 |
| R2 popped / expanded events | 0 / 0 | 421 / 393 | 91 / 87 |
| R3 generated events / unique digests | 1 / 1 | 8 / 6 | 22 / 10 |
| R3 retained / live / popped / expanded / trimmed | 1 / 0 / 0 / 0 / 1 | 6 / 1 / 0 / 0 / 5 | 10 / 8 / 0 / 0 / 2 |

Arm C retained these ten natural R3 digests. None was popped or expanded:

| Digest | Node | g | Parent→child credit | Insert expansion / rank | Best / last rank | Outcome |
|---|---:|---:|---:|---:|---:|---|
| `5481589d5f04c257` | 17 | 7 | 0→0 | 5 / 3 | 3 / 204 | live |
| `bf5a42ecfefd5ff4` | 18 | 7 | 0→0 | 5 / 3 | 2 / 203 | live |
| `67257953c862ece2` | 22 | 8 | 0→0 | 6 / 1 | 1 / 200 | live |
| `4a9c3b4f295f77f2` | 23 | 8 | 0→0 | 6 / 1 | 1 / 199 | live |
| `afc6d9383d829dce` | 38 | 11 | 2→0 | 11 / 1 | 1 / 179 | live |
| `2fbec47f7ce43dca` | 51 | 12 | 2→0 | 16 / 4 | 4 / 181 | live |
| `c0a7b906a631ad61` | 291 | 22 | 2→0 | 119 / 9 | 4 / 12 | live |
| `c967b7bbd57c0e96` | 378 | 21 | 2→0 | 154 / 41 | 38 / 47 | live |
| `0f872730f95f1603` | 762 | 22 | 2→0 | 365 / 257 | 257 / 258 | trimmed at 365 |
| `b3ddf9584dace726` | 768 | 23 | 2→0 | 368 / 256 | 256 / 257 | trimmed at 368 |

The JSON records all 22 natural R3 generation events, including higher-credit
duplicate generations suppressed before frontier admission. Because no R3 node
expanded, there are no R3-parent production successors to report. Neither prior
observation digest `1c3d3ec77bf164ad` nor `edb1f739a3100867` occurred naturally
in B or C; A reproduced their prior lifecycle.

All arms generated and retained states with two stock rows remaining, but no arm
expanded such a state. Expanded stock distributions were A: 10/98/292 at 5/4/3
rows, and both B and C: 1/5/394 at 5/4/3 rows. All arms remained at zero actual
empty and zero foundation. C's minimum face-down 36 was between A's 37 and B's 35.

## 7. Performance

State-local reduced elapsed time from 869.981 to 565.529 seconds versus inherited
(35.0% lower) and reduced generated/retained successors from 2,549/1,815 to
1,909/507. It did not reduce tactical consumption: 52,516 tactical nodes was 57.3%
more than B and 50.4 times A.

The per-credit tactical distribution shows why cost alone is not a success metric:
C repeatedly earned and serviced genuine credit 2–4 expansions, spending 46,507
tactical nodes there, while returning their children to CLEAN. B concentrated
31,852 tactical nodes at inherited credit 4. State-local fixed the semantic
avalanche but did not optimize tactical expense.

## 8. Confounders

Held unchanged:

1. cheaper TT arrivals may fail to reopen already-expanded `(state, credit)`;
2. trimmed states remain TT-seen and suppress equal/higher-cost rediscovery;
3. overlapping frontier protections can duplicate node IDs.

C's 1,402 TT suppressions make the first two defects especially relevant to its
lower retention count. No final frontier contained duplicate node IDs, but the
protection logic was not repaired. There were zero replay failures, corrected-cost
inconsistencies, and proof prunes in every arm.

No R2/R3 reservation, R3 bonus, lane reorder, fairness mechanism, resource
planner, successor-family change, portfolio-width change, TT change, proof change,
cost change, or tactical-grant change was made.

## 9. What the experiment proves

The experiment causally supports state-local `StrategicCreditLevel` under this
commit, seed, deal, and fixed production-style envelope. Resetting only ordinary
children:

* preserved same-state widening through every credit;
* eliminated inherited near-total credit-4 dominance;
* produced balanced service across CLEAN and credits 1–4;
* retained genuinely additional broader coverage;
* allowed 50 broader discoveries to receive their own CLEAN expansion.

It does not prove that state-local credit is globally optimal, that C is cheaper,
that C preserves every useful state B found, or that credit semantics solve the
remaining strategic bottleneck. The persistent failure to pop any R3 state is
independent evidence that frontier service remains unresolved.

## 10. One next bounded experiment

Under `COMMON_STAGE0 + STATE_LOCAL`, A/B exactly one within-capacity reservation
for the strongest naturally generated R3 parent, defined only by structural facts,
to test whether existing production successors can create the first replay-valid
empty; do not add a priority bonus or invoke the resource planner.

## Tests run

* Focused state-local and prior comparator tests: 9 passed.
* Controller/credit/natural-resource regression selection: 143 passed.
* Additional controller-v0.2 and resource-planner integrity selection: 64 passed.

The final distinct passing selection contains 216 tests. An earlier regression
attempt produced 142 passes and one source-audit failure because widening had been
factored into a helper; the original inline widening statement was restored, the
focused marker test passed, and the complete 143-test selection then passed.

Machine-readable results:
`docs/research/state_local_credit_semantics_v0_1.json`.
