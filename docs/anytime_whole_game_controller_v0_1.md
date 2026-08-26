# Anytime Whole-Game Controller v0.1

**Branch base:** `agent/strategic-deal-timing` at `6bea3776e5fd05007c46e5e6c509f67842732905`

**Prospective verdict:** **FAIL**

**Scope:** first generic, bounded strategic controller; not a completed whole-game solver

## Active rule profile

The controller freezes the active MobilityWare 4-suit profile before analysis or search. The benchmark uses **Unrestricted Deal ON** and the preflight requires `MW_RULES.can_deal_into_empty is True`. A genuine empty column therefore does not suppress a legal stock deal.

The frozen profile also asserts:

- four suits, 104 cards, ten tableau columns and five ten-card stock rows;
- single cards may move onto any suit at exactly one rank lower;
- multi-card blocks must be descending and same-suit;
- moves to an empty column are legal;
- the next row is `state.stock[-10:]`, dealt left-to-right;
- only an exact same-suit K-A sequence is removed automatically;
- an ordinary tableau move costs one, a whole open column moved to empty costs zero, a deal costs one and automatic removal costs zero; and
- solved means empty stock and tableau with exactly eight foundations.

No additional rules inconsistency was found.

## Rule-surprise preflight

Both mandated anchors were independently reconstructed before the prospective benchmark:

- Canonical route: solved at corrected cost 172; 174 explicit commands, 169 tableau commands, five deals and eight foundations; path hash `77d169da2538ba8c`; final-state hash `4e9861540eac570cb`.
- Legal machine first-foundation route: corrected cost 23; 23 explicit actions, two deals, first Spade foundation, stock 30 and 32 face-down cards.

The diagnostic performs these regressions in isolated subprocesses and retains only primitive summaries. The prospective controller receives no action from either route. Canonical future actions are opened only after every prospective result is frozen.

## Controller architecture

`solve_anytime(initial_state, cards, incumbent=None, config=...)` accepts an arbitrary legal state and full deal. It builds a priority frontier of `StrategicSearchNode` values. Each `StrategicSuccessor` may carry multiple explicit actions and must independently replay from its parent before admission. The full resulting state is then reanalysed.

The public model includes:

- `AnytimeControllerConfig` and `AnytimeControllerStatus`;
- `StrategicSearchNode`, `StrategicSuccessor` and `StrategicActionKind`;
- five `StrategicCreditLevel` values;
- `StrategicAnalysisSnapshot`;
- `IncumbentRecord` and `AnytimeSearchResult`; and
- bounded `ControllerTelemetry` and `DecisionTraceEntry` records.

The module contains no benchmark deal, route, column, suit-order, 172 or 119 constants.

## Strategic states and edges

Each analysis snapshot recomputes:

- the economic project frontier;
- campaign portfolio;
- structural measurement;
- current actionability and blocked high-value projects;
- exact next-row deal timing where legal; and
- incumbent budget with the proved lower bound.

Successors can be direct or bounded economic projects, foundation campaign/removal macros, Deal Now, preparation then Deal, or credit-4 raw legal fallback moves. Exact resulting states are deduplicated. The retained set is filled across deal timing, permanent structure, campaigns, workspace/excavation, rework and raw fallback categories before a category can monopolise the small branch budget.

Every edge is replayed independently. Every retained child is fully reanalysed. Foundation removals and stock deals have explicit reanalysis counters and timeline events; stale campaign assumptions are not carried forward.

## Value and actionability

Economic value is not treated as proof of immediate executability. Direct legal projects enter immediately. Other projects must first pass a bounded actionability probe and then a bounded realiser. A miss is local to the exact state, credit and resource envelope and never becomes a global impossibility proof.

The v0.1 run exposed an important resource-control defect: `max_bounded_projects_per_expansion` bounded successful realisations, but did not also bound unsuccessful actionability probes. Across the five-minute production-like attempt, 616 bounded-inaccessible results consumed the entire 80,000-node tactical allowance. This is the principal observed stall.

## Deal timing

Deal is generated whenever the engine says it is legal, even while tableau moves remain and even with empty columns under the active profile. The timing service ranks and orders its portfolio; it has no proof-pruning authority.

- `DEAL_NOW_PREFERRED` and `DEAL_REQUIRED_FOR_ACTIONABILITY` put Deal first and retain credible preparation arms.
- `PREPARATION_PREFERRED` puts preparation first and retains Deal.
- `COMPARISON_INCONCLUSIVE` retains both.

The benchmark run retained five Deal Now and five preparation-then-Deal states. This demonstrates first-class deal coverage, but the priority discipline then moved too readily through stock epochs without achieving foundation progress. That is an ordering failure, not evidence that early dealing is globally correct.

## Permanent-move dominance and rework lifecycle

Raw moves use the established lifecycle classifier and record placement class, future exit route and estimated rehandling cost. Stable same-suit joins are ordered ahead of equally credible mixed parks. Mixed-suit debt and campaign economics remain heuristic and cannot proof-prune.

Telemetry records stable-join, mixed-boundary and rehandling-debt changes after each retained edge. The run created debt at deals and selected several stable same-suit joins that removed individual mixed boundaries. It found no foundation route, so it supplied no evidence that total projected debt was ultimately repaid. No permanent join was deliberately overridden on a verified solution path because no complete path existed.

## Progressive credit

Coverage widens monotonically:

1. Clean: structurally dominant/currently actionable work, stable structure and strategic deal alternatives.
2. Positive investment: Tier-2 work, bounded excavation/workspace and campaign edges.
3. Speculative: Tier-3 and broader campaign/rehandling work.
4. Escape: Tier-4 and weakly explained bounded work.
5. Raw legal fallback: corrected `enumerate_moves()` plus Deal.

The production run expanded credits `{0: 11, 1: 6, 2: 9, 3: 9, 4: 20}`. Credit controls search order and coverage only.

## Transposition and proof semantics

The strategic transposition table keys the exact tableau face-down/up structure, stock and foundations. It admits a state only when its corrected paid cost `g` is lower than the stored value. Heuristic economics and lifecycle scores are deliberately ignored. Predecessor action paths remain on admitted nodes.

Production TT totals were 72 new exact states, no lower-cost replacements and 61 higher/equal-cost suppressions. No heuristic state-dominance claim was made.

Proof pruning uses only:

`remaining_deals + ceil(max(0, face_down - 10 * remaining_deals) / 2)`

The production-like run had no incumbent and therefore no proof pruning. Research mode supplied only the verified score 172 and made zero proof-bound prunes in the explored corridor. Economic work, deal timing, campaign cost and rehandling debt did not enter the admissible bound. Bounded frontier trimming is separately labelled heuristic; none occurred in these runs.

## Incumbent lifecycle and solution acceptance

Production mode starts with no cap. A solved search endpoint must replay independently from the original state, end with empty stock/tableau and eight foundations, match the endpoint structurally and reproduce its corrected cost before it can become the first incumbent. Search then continues for a strict improvement while resources remain.

Research mode uses the same implementation with the scalar incumbent 172, targeting at most 171. The stored 172 actions are not supplied. The external 119 result has no role in the controller, bound or incumbent.

No complete candidate was found, so no incumbent was installed and the external archive was not written.

## Prospective benchmark runs

The diagnostic used at most four strategic successors per expansion, frontier 500, credits 0–4 and a deterministic four-combination source beam for ordering. Existing callers remain exhaustive by default, and the source beam has no proof authority.

| Mode | Requested bound | Actual result |
|---|---:|---|
| Production smoke | 60 s, 40 expansions, 20,000 tactical nodes | 57.71 s; 19 expansions; 20,008 tactical nodes |
| Production-like | 300 s, 160 expansions, 80,000 tactical nodes | 138.05 s; 55 expansions; 80,000 tactical nodes |
| Research, incumbent 172 | 300 s, 160 expansions, 80,000 tactical nodes | 139.36 s; 56 expansions; 80,009 tactical nodes |

Both main runs stopped on the tactical-node limit rather than wall time. Production generated 132 strategic successors and retained 71: five Deal Now, five preparation-then-Deal, 31 economic-project and 30 raw-tableau successors. It performed 72 full analyses.

The best recorded production state had `g=6`, state hash `f21d27e6ebd84f63`, stock empty, zero foundations and 43 face-down cards. The controller reached all five stock epochs but did not materially exceed the legal cost-23 checkpoint, which already has one foundation and only 32 face-down cards. No first machine solution or <=171 candidate was found.

## Unseen-deal smoke tests

Two deterministic valid shuffled four-suit deals were run with `incumbent=None` and ten-second requested limits:

- seed 104729: 11.88 s, two expansions, legal progression, unrestricted profile confirmed;
- seed 130363: 13.13 s, two expansions, legal progression through stock epoch 1, unrestricted profile confirmed.

Both ended by the wall-clock bound. Neither was required to solve. They confirm the entry point and rule preflight are generic, but their very low expansion throughput reinforces the analysis-cost limitation.

## Telemetry findings and limitations

- The bounded trace, deal/foundation/rework timelines and aggregate counters stayed within configured limits.
- Deal timing was first-class rather than a no-move fallback.
- Full credit widening and raw legal fallback were reached.
- Exact TT suppression worked and did not incorporate heuristic scores.
- The production and research searches were almost identical because the proved lower bound was far below 172 in every explored state.
- No foundation timeline event was recorded.
- Reanalysis and tactical actionability probing are too expensive for whole-game breadth in v0.1.
- Stock-epoch progress currently receives too much priority relative to actionable structural progress; the controller can consume stock without building a removal path.
- Actionability caching is correct for an exact state/project/credit/resource key, but exact-state expansion happens once and changing remaining resource envelopes meant this run had 616 misses and no hits.
- The bounded physical-source beam improves analysis latency but can reduce heuristic portfolio coverage. It remains unsuitable for proof elimination.

## Hard-gate verdict

**FAIL.**

The implementation satisfies rule fidelity, strategic Deal coverage, replayed edges, genericity, progressive widening, exact TT and proof separation. The prospective controller did not solve, did not remove a foundation, and did not materially advance beyond the legal cost-23 checkpoint. Per the sprint gate, no automatic economic retuning or longer search was started.

## Precise next task

Build v0.2 around measured successor-throughput and actionability control, without changing economic weights for this deal:

1. add an explicit per-expansion actionability-probe allowance, separate from the successful-realisation allowance, so inaccessible candidates cannot consume the global tactical budget;
2. normalise/cache bounded actionability results by deliberate resource tiers and report unique project probes versus retries;
3. revise transparent frontier ordering so stock consumption alone cannot outrank credible foundation/reveal progress;
4. reuse already-computed post-deal economic facts when constructing the fully reanalysed child, avoiding duplicate work without weakening the reanalysis invariant; and
5. rerun short generic and benchmark smokes before authorising another five-minute attempt.

This is a controller-resource and priority sprint, not benchmark-specific economic tuning.
