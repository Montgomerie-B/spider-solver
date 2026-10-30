# Planning-architecture review following v0.139

**Status:** independent source-and-report review, no solver code changes, no new search runs.  
**Repository:** `Montgomerie-B/spider-solver`  
**Reviewed ref:** v0.139, `ef96d8e49450157c8c38ae2f41dc3f0f2202f3b5`  
**Review branch:** `review/planning-architecture-post-v0-139`  
**Decision:** **Do not implement v0.140 as another suit/length/milestone variant.** Specify the long-horizon planning contract and its falsifiable benchmarks before writing a replacement controller.

## Executive assessment

The research stack is meaningfully more reliable and targeted than it was at v0.127. The legal game engine and corrected MobilityWare scoring are retained; exact transposition handling, post-stock symmetry, proof-first admission, fair multi-root scheduling, a purposeful pre-deal macro generator, tactical milestone discovery and complete terminal replay are implemented and tested.

Yet the best verified complete game on deal 4925153 remains **172 corrected MW moves**, the imported canonical incumbent. No v0.128–v0.139 experiment has yielded a replay-verified 171-or-better complete game. The 185-move file remains a verified historical complete route, *not* proof of independent cold discovery.

The principal bottleneck is now the **missing contract between short tactical success and economical completion**. A foundation, reveal or seven-card top run is an observable property. It is not a guarantee that the tableau preserves the workspace, exposed receivers and other suit structures needed by subsequent operations. Our recent searches stop at such properties, then ask primitive-move search to repair any damage within a strict residual cost budget.

This is a planning-architecture diagnosis, not a proof that the existing bounded search could never succeed with different priorities.

## 1. Evidence ledger: what has and has not been established

| Topic | Evidence | Interpretation |
| --- | --- | --- |
| Valid incumbent | `solutions/4925153_canonical.moves`; 174 explicit actions, corrected cost 172, eight foundations; SHA-256 `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | Valid complete-game target, not proved optimal |
| Independent completion | v0.124 audit documents cold whole-game/controller searches unable to finish within those budgets; provenance of historical 185 is not established as independent cold | Keep cold and incumbent-guided metrics separate |
| Search-order efficiency | v0.129 reached paid layers stalled under v0.128 uniform cost; v0.131 moved proof checks before retained-state admission | Real kernel improvement; no solution improvement |
| Stock correctness | v0.132 fixed mirrored future-stock column labels in `backward_strategy.locate_all_cards`, checked five row lengths against the engine | Backward diagnostics now use correct physical column mapping |
| Tactical preparation | v0.134 discovered a known useful four-landing pre-SD5 preparation without seeding the moves | Tactical plan generation is feasible |
| Multi-root allocation | v0.135 distributed 3,318 expansions across eight viable origins (407–450 each), compared with v0.134's 2,190/2,192 from one origin | Fairness fix measured; no completed-route improvement |
| Short vs useful milestone | v0.136 five-move club/reveal result ended at g155,h14,f169 versus reference at g158,h11,f169; reference suffix illegal on shortcut | Three moves saved locally did **not** demonstrate lower full-game cost |
| Heart assembly | v0.138 seven-heart top-run endpoints; six selected f<=170 continuations exhausted under ceiling 171 | Negative only for six *specific selected starting states* |
| Compound tactical outcome | v0.139 seven top hearts + genuine reveal: one early root-0 terminal at g154,h17,f171; seven roots had no recorded terminal in the time cap | Composite criterion is feasible; portfolio has not produced usable continuation candidates |
| Terminal selection | v0.139 `lower_f` now independently verifies every *recorded* terminal before f ranking | Fixes prior 128-terminal truncation; does not recover v0.138's unpersisted 33+180 candidates |
| Regression health | v0.139 maintained suite 663 passed, 0 failed in its reported run | Previously reproduced v0.120 `PLANNING_STALL` versus `TIME_LIMIT` remains issue #6; eight separately uncollected research modules remain |

**Evidence limits:** Numbers and replay/test outcomes above come from committed reports and code, not new test execution by this review. Frontier exhaustion with a sound admissible bound proves absence of a <=171 continuation only from the *searched exact state/identity* with all applicable successors represented. A resource-limited stop or a heuristic `f<=170` screen is **not** proof of global impossibility.

## 2. Root cause 1: an excessively narrow ancestor and homogeneous portfolio

The v0.134–v0.139 eight-root research portfolio is reconstructed after **canonical checkpoint 140 at corrected g139**, shortly before the fifth stock deal. All candidates inherit the preceding 140 canonical actions. The small fixed search budget and `purposeful_macro.select_portfolio` favour cheap SD5 receiving arrangements; `GATE_B_LANDINGS=4`, `GATE_B_G_POST=142`, and selection by `-hits`, `g_post`, `h_post`, and receiving mask are especially close to the known positive control.

The eight roots are distinct legal physical states, but **all** in the v0.139 report:
- start post-SD5 with exactly three face-down cards;
- hold two foundations;
- have the same highest top-heart suffix, `5H 4H 3H`;
- share the same long canonical ancestry and a single macro-generation horizon.

This is **not broad strategic diversity**. It compares local seating variations within one already chosen long-term plan. None can recover a different SD3/SD4 excavation decision. The eight-root scheduler fairly shares effort, but it cannot compensate for a homogeneous, strategically disadvantaged input portfolio.

**Action:** evaluate diversity over *different stock-boundary ancestors and consequences* (face-down depth/distribution, suit-component access, productive space, already prepared foundations, future-deal landing geometry, and required setup cost), not simply physical pack, receipt mask or low g. Avoid learning a policy only from this deal's four-landing witness.

## 3. Root cause 2: no contract for downstream obligations

The tactical milestone predicates in `post_deal_milestone.py`, `heart_run_followthrough.py` and `reveal_aware_heart.py` correctly recognise observable **terminal properties**. But a path can satisfy a property while consuming an essential receiver, splitting a transferable run, trapping a suit behind another stack or losing the only recoverable workspace.

Specific cases:
- v0.136/137 club+reveal control: three fewer moves than the canonical reference milestone, but +3 in the admissible residual, fewer bonds, less workspace, less mobility and an illegal inherited canonical suffix.
- v0.138 heart-run control: king-high run is reached one move earlier than the canonical ace-low run; same f, different suit geometry.
- v0.138 early root-0 heart state at g147,h22,f169 has three face-down cards, no free columns and nine legal tableau moves despite having met the target.
- v0.139 early root-0 combined milestone at g154,h17,f171 also has **zero** empty columns, two foundations and three original hidden cards reduced to two; it met the objective but did not satisfy the f<=170 experimental screening rule.

**Action:** specify a tactical **option** or macro as a verified primitive path with (a) prerequisites, (b) achieved effect, (c) preserved future receivers, (d) damaged/deferred dependencies, (e) temporary workspace usage and recovery, (f) exact corrected cost, and (g) exact final physical tableau. A milestone's postcondition must be evaluated alongside the *next required operations*, not in isolation. Suggestions may reorder the legal primitive search; they must not silently delete legal moves or become unproved proof bounds.

Use a state-dependent, re-evaluated **AND/OR dependency graph**, not a fixed linear list: revealing a buried card may require clearing a run, which may require a receiving column and a temporary park; another suit may be assembled first to release that workspace. Changes in card exposure or stock epoch invalidate and regenerate the dependency plan.

## 4. Root cause 3: the admissible bound is a proof filter, not a strategic forecast

`admissible_remaining` combines `compute_solution_lower_bound` with the stock-empty `assembly_lb` by **max**. The assembly bound uses physical same-suit intervals and the minimum interval multicover per suit; it captures unavoidable suit assembly, not the full cost of freeing those intervals and recovering contested workspace.

The bound becomes effective close to the canonical endgame, but does not distinguish the *true* full-game cost of competing intermediate positions. Examples:
- canonical post-SD5: g150,h18,f168, known remaining cost 22 (four above h);
- early alternative post-SD5: g142,h24,f166, but no full continuation is known;
- root-0 compound milestone: g154,h17,f171, on the exact proof boundary; the test's *screen* rejected it without proving its continuation impossible;
- reference vs five-move club/reveal shortcut: f169 for both, but different mobility and endgame prerequisites.

A lower f is only a mathematically smaller *optimistic* total, not a prediction of the best route. The experimental **f<=170** preference is a useful allocation policy but **must never be interpreted as a sound rejection of all f171 candidates**.

**Action:** evaluate bound *informativeness* at numerous canonical/historical checkpoints: known remaining moves minus h, actual admissible-prune yields, depth of buried-card dependencies, and queue time spent in states with f near 171. Separate admissible proof from ranking signals. Consider an additional safe bound only after deriving and fixture-verifying a formal argument; do not turn interference scores, mobility or desired receiver count into proof pruning.

## 5. Root cause 4: two solvers, research modules and search have not converged

The v0.124 architecture audit showed two distinct failure modes:
- `whole_game_anytime.search_whole_game` legally expands all successors but, in the measured cold 80k-state run, never completed a foundation. Its historical hard ceiling 300 lacked the `admissible_remaining` prune that incumbent-guided searches now use.
- The Human Strategy Controller can generate and score legal actions but can suppress them via strategic width, objective/campaign gates and a stall with still-legal actions. It is not complete, and the intermittent TIME_LIMIT versus PLANNING_STALL regression is unresolved.

The v0.128–v0.139 research modules added correct and useful components, but compose them as **serial one-off gates**, often rediscovering the same eight roots and discarding frontiers at time limits. The controller's strategy knowledge and the kernel's completeness-oriented legal graph remain largely separate.

**Action:** retain one authoritative rules engine, one shared primitive search kernel, one proof/best-g identity discipline, and one replay validator. Implement strategy as *proposals of costed options and priority*, with legal primitive fallback. Preserve search work and candidate provenance across progressive widening rather than repeatedly restarting a small fixed frontier. Do not reimplement Spider legality or a second transposition table inside a new strategic controller.

## 6. Proposed architecture (design only)

```text
Known deal + verified full-route incumbent
   |
   v
State & stock-epoch facts  [ordered columns until stock exhausted]
   |
   v
Backward AND/OR dependency analysis
  card exposures / suit assembly / useful receivers / workspace
   |
   v
Bounded legal option generator
  replayable primitive actions + exact g + pre/post conditions
   |
   v
Dependency-aware portfolio (diverse ancestors and alternative plans)
   |
   v
Persistent incumbent-guided search
  one best-g transposition table, proof-first admissible pruning,
  progressive widening, fair option allocation, primitive fallback
   |
   v
Complete 8-foundation game -> independent full replay -> improved incumbent
```

**Separation of concerns**:
- **Safety and proofs:** `engine.py`, `rules.py`, `step_cost`, `pack_state`/`pack_whole_game_identity`, `admissible_remaining`, `run_search`, `verify_complete_solution`.
- **Strategic decisions:** objective/dependency options, macro endpoint usefulness, portfolio diversity, node/option scheduling and non-admissible estimates.
- **Empirical evaluation:** source/target provenance, retained vs generated, bound gaps, stalled vs exhausted, root/option contributions, verified completed routes, and runtime. An imported-prefix route is never independent cold discovery.

A high-level option is **not** a new game move: its cost and final state are replay-derived from legal primitive actions, and action sequences can always be expanded and verified. Exact physical column identity must remain during stock epochs. After stock exhaustion only proven whole-column symmetry may be used, with physical action remapping on reference-rejoin paths.

## 7. Recommended non-coding next stage — falsifiable architecture design

**Do not commission a new algorithm or v0.140 implementation yet.** First design an Option/Dependency/Portfolio interface and evaluate it *offline* against saved evidence and engine-replayed states:

1. **Build an outcome/dependency ledger** for the canonical 172 line, historical 185, canonical checkpoints 140/151/152/158/160/163, the five-move club/reveal shortcut, the v0.139 root portfolio and the already exhausted root-0/six heart endpoints. Record source g, exact action path, reached effects, still-buried cards, essential receiver/space requirements, lower-bound gap and known next legal actions. Do not invent full-game costs for incomplete states.
2. **Specify a neutral option contract**: named objective, prerequisites, supported alternatives, exact primitive action list, cost, state identity, effects, consumed/recovered workspace, outstanding/conflicting dependencies and proof provenance. Show how three example options compose and how a locally cheaper option can be rejected by a *measured dependency cost* without pretending that cost is admissible.
3. **Specify portfolio diversity and selection** using mutually different postconditions or earlier stock-boundary ancestors, not just landing count and g. Include at least one candidate with meaningful reveal progress and one with productive workspace; document why the current eight-root set fails that test. Diversity constraints must be *budgeted search preferences*, not completeness claims.
4. **Assess bound information** over matched route checkpoints and synthetic correctness fixtures. Distinguish safe prune from predictive priority. Recommend one specific candidate for a future **formal admissibility proof** only if supported; otherwise retain the current bound.
5. **Define a single objective pilot** only after the design review: evidence that a verified useful option can enable a *second* productive option without losing the first one's required outcome. This should be tested on at least one **held-out** board/deal or a deliberately constructed fixture, not tuned exclusively against the two supplied routes. Keep an explicit negative control for a shortcut that saves g but destroys a needed receiver.
6. **State an implementation go/no-go gate**: the pilot must yield replay-verified two-stage progress with exact prefix costs, preserve all legal primitives, report structural trade-offs, avoid false optimality claims and demonstrate broader meaningful outcomes than the current eight roots. Only then consider coding an anytime persistent option-guided search.

**Explicitly deferred:** more suit-length milestones, another goal lane, cap escalation, unproved lower-bound penalties, retraining scoring weights on the same routes, full Human Strategy Controller rewrite and merging research branches into main.

## 8. Outstanding maintenance

- Issue #6: reproduce and resolve the live-solve status contract deterministically (`PLANNING_STALL` vs `TIME_LIMIT`) rather than weakening the test.
- Eight historical research modules fail bare `pytest tests` collection due to missing `*_v0_1` imports; identify whether they are maintained dependencies, obsolete tests or require a separate optional test marker. Do not conceal by silently skipping them.
- Distinguish **source commit tests reported by Grok** from independent execution. Review did not execute repository tests or local Windows artifacts.
- Keep `main` and existing verified solution hashes untouched pending an explicit integration decision.

## Recommendation

**Approve the architecture specification and evidence-led pilot design, not another automatic v0.140 coding experiment.** The near-term objective is to make the solver choose a short sequence *because it demonstrably enables the next useful sequence*, while retaining the exact-search and full-game replay guarantees that have already been earned.
