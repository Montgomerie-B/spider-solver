# Global search architecture v0.124

Deal `4925153`. Corrected MobilityWare costs. One worker. This release does not commit, push, merge, or open a pull request.

## 1. Starting commit and branch

Branch `local/global-search-review-v0-124`.

HEAD `82201eceb78fd581fe1856c930958a1cf11dae6f` (`82201ec Improve strategic objective identity and continuity v0.123`).

The working tree was clean at that commit before this review. `engine.py`, `rules.py`, the Human Strategy Controller, the incumbent registry, and the verified solution files are unchanged.

## 2. Original solver

The reusable global search is `search_whole_game` in `src/spider/whole_game_anytime.py`. It calls `run_search` in `src/spider/search_kernel.py`.

Successor generation uses `all_legal_actions`, which is `SpiderState.enumerate_legal_actions`. That list is every legal tableau transfer plus a stock deal when `can_deal` is true. The engine comment forbids tableau heuristics in that enumeration. Deal stays legal while tableau moves remain, including when a column is empty, under the default unrestricted rule.

`run_search` applies every action returned by `actions_fn`. Its default, if a caller omits `actions_fn`, is tableau-only. The whole-game adapter does not use that default. It passes the full legal list. Nothing in that path drops a move because a strategic objective failed to name it.

Ordering is seven lanes: cost, foundation, reveal, workspace, construction, prep, and epoch. `lane_keys` builds a tuple per lane. Lower tuples are popped first. Round-robin gives each lane a turn. The foundation lane key is `(-foundations, face_down, stock_rows, g)`. With zero foundations that key prefers fewer face-down cards, then fewer stock rows, then lower cost. It does not score how close one suit is to a removable king-to-ace sequence.

The algorithm is exact best-g search with several ordering heaps. Identity is `pack_whole_game_identity`: ordered `pack_state` (SPK1) while any stock remains, and the column-permutation quotient (SPS1) only after the stock is empty. A new path to the same identity is kept when its corrected cost is strictly lower. `child_g >= prev` is a duplicate skip, so a zero-cost return to a seen state does not loop. There is no beam truncation inside the kernel.

The adapter passes `cost_ceiling=300`. That skips a child whose corrected cost is already above 300. It is a hard path cap. The adapter does not pass `lower_bound_fn`, so this cap is not `g + h`. Optional proof pruning exists in the kernel and runs only when both a ceiling and a lower-bound function are supplied (`g + h > ceiling`).

Stock deals are ordinary children. Empty columns are ordinary destinations. A whole face-up column moved onto an empty column costs 0 when the source has no face-down cards, and costs 1 otherwise (`rules.mw_move_cost`). Face-down reveals and same-suit bonds affect lane order through `current_tableau_summary`. They do not delete successors. A completed same-suit sequence leaves the tableau when the engine's `check_seq` removes it. The terminal test is `state.is_solved()`: eight foundations, empty stock, and empty columns. A solved path is replayed and accepted only when the replay cost matches, all eight foundations are present, the stock is empty, and every column is empty.

Memory and time controls are `SearchLimits`: `max_unique`, `time_limit_s`, and `rss_abort_mb`. The historical defaults on the adapter are 800,000 unique states, 900 seconds, and 2.5 GiB, with the hard cost cap of 300. This review used 80,000 unique states, 3,072 MB, and the same cap of 300.

The adapter has no incumbent ceiling. An incumbent has to be supplied by another caller through `cost_ceiling` and, for an admissible prune, `lower_bound_fn`.

Older code in `src/spider/search.py` (`bounded_ucs`, `bounded_finisher`, `ida_star`) and `whole_game_epoch_scheduler.py` is not the producer of the packaged 185-move file. The epoch scheduler searches tableau moves inside a stock epoch and treats a deal as an epoch transition. That is heuristic frontier management. The whole-game adapter is the one that expands deals as normal legal children.

`campaign_expand.expand_opening` calls the epoch portfolio search. `verify_g123_root` reconstructs a known g123 prefix and checks the digest. The hierarchical campaign record `HIERARCHICAL_CAMPAIGN_186_VERIFIED` (`docs/research/hierarchical_deep_campaign_v0_100.md`) reports a verified replay of cost 186 after that checkpoint. `solutions/4925153_autonomous_v0_100.json` records `canonical_used: false`, incumbent 187 before and 186 after, and `production_ceiling_after: 185`. The production registry `solutions/4925153_incumbent.json` still points at that v0.100 line, with incumbent cost 186 and production ceiling 185. This review did not edit it and did not rerun the campaign.

## 3. Current Human Strategy Controller

The production controller is `solve` in `src/spider/human_strategy/controller.py`, schema `spider-human-strategy-0.123`.

`build_candidates` (`portfolio.py`) scores every action from `all_legal_actions`, then may append portfolio objectives. `_defer_unhelpful_shuffles` reorders. It does not drop a scored move. `_dedupe` sorts by `rank_key` (projected cost, then a solved flag, then attractiveness). Projected cost is an estimate.

The controller then keeps `ranked[:strategic_width]`. The pilot width is 3. `select_candidate` chooses one objective. Sibling ids go onto a dormant list capped at 16. They are backtrack options, not an expansion of every legal child.

A foundation campaign can replace that choice. When the campaign has no executable step, `goal == "foundations"`, and `yield_to_alternative` is set, the controller tries an alternate campaign and then `_recovery_candidate`. If both fail, and legal tableau moves remain, it stops with `no campaign offered an executable step` (`controller.py`, the yield branch). The already scored choice is not applied on that path.

`_seed_divergences` queues unplayed legal tableau moves only when the frontier queue is empty. It skips deals, skips moves that `covers_productive_run` judges to be covers of a long same-suit run, skips the immediate inverse of the last move, and stops after `frontier.proposals` seeds (3 on the pilot profile).

Exact-state dominance keeps the cheaper ancestry of one physical state. `proof_prune` is `g + admissible_remaining >= incumbent` and is idle in cold mode because the incumbent is absent. Safe prunes on the v0.123 cold run were 0.

The committed v0.123 cold run on this deal (`artifacts/human_strategy/v0_123/experiment_c_policy.json`) stopped `PLANNING_STALL` at 94.381 seconds with one foundation, corrected cost 47, 24 face-down cards, and 20 stock cards. Five legal tableau moves remained. About 56 seconds and 627 strategic commits remained. The 8H excavation probe still exposes the buried heart at the documented ladder step of 4,500 nodes. That probe is not the obstruction.

## 4. Successor generation, side by side

| Question | Whole-game kernel | Human Strategy Controller |
| --- | --- | --- |
| Who creates children? | `all_legal_actions` | One selected objective, plus a few dormant or seeded siblings |
| Are all legal moves generated? | Yes | They are scored. Most are not expanded |
| What deletes a move? | Exact-state dominance, the hard cost cap, the unique/time/RSS limits | Strategic width, campaign yield, productive-run filter, proposal cap, frontier cap, dormant cap |
| Deal | Ordinary legal child | Often outside the width, or deferred by a campaign |
| Search order | Seven heuristic lanes, round-robin | Objective rank, then campaign lock |
| Proof prune | Only with a lower bound and a ceiling. Cold whole-game search passes neither | Cold `proof_prune` is off. Heuristic drops are labelled and are not proofs |
| Completion | Replay of eight foundations | The same replay rule, through the incumbent helpers |

The kernel is a state-space search guided by lane order. The controller is a strategy-objective search that sometimes expands the legal graph.

**A legal move can be excluded because no currently selected strategic objective proposes it.**

The measured states below show the generator scoring every legal action and the width then keeping three. The stall state shows a further gate: the selected legal move was still not played. Neither exclusion is safe dominance, and neither is an admissible incumbent prune. Both are intentional heuristic restrictions. They are also large. At the opening, 5 of 8 legal successors sit outside the width. Immediately before the historical action-18 deal, 13 of 16 do, and the deal is one of them.

## 5. Measured legal-action coverage

Profile `pilot`, strategic width 3. `artifacts/global_search/v0_124/coverage.json`. Distinct successors were counted by applying each authoritative legal action. On these six states every legal action produced a distinct child, and `build_candidates` scored every legal action. `not_scored` is 0. Safe dominance and admissible pruning are empty in this pass because the frontier was not run. The class `heuristic_rank_cutoff` is the width.

| State | g | Foundations | Face-down | Stock cards | Legal | Inside width | Outside width | Selected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Opening | 0 | 0 | 44 | 50 | 8 | 3 | 5 | `move 3 6 1` |
| Before historical action 18 | 17 | 0 | 33 | 40 | 16 | 3 | 13 | `move 1 7 1` |
| Historical 25-action state | 25 | 1 | 32 | 30 | 3 | 2 | 1 | none (top objective has no action) |
| Cheaper ancestry of that state | 23 | 1 | 32 | 30 | 3 | 2 | 1 | none |
| First foundation on the g83 line | 19 | 1 | 33 | 30 | 6 | 3 | 3 | `move 8 10 1` |
| After the historical deal | 18 | 0 | 33 | 30 | 11 | 3 | 8 | `move 8 10 1` |
| v0.123 planning stall | 47 | 1 | 24 | 20 | 6 | 3 | 3 | `move 2 3 3` |

The kernel would generate every row's legal count. The controller's committed step is one objective.

At the stall, the three moves outside the width are `move 3 4 3`, `move 5 8 1`, and `move 7 8 1`. The saved stop text also names `move 2 8 1` and `move 2 3 3`, which are inside the width. The campaign gate left all five tableau moves unplayed. State id `eebf1cac949b3fc7af9e71c357b8735a3ff2927aea44b8cbe5b298bbd457aa02` matches the v0.123 record. Replay cost is 47.

## 6. Role of strategic objective gating

Objective generation is a ranker. Objective selection is a gate.

1. `build_candidates` scores the legal list.
2. `considered = ranked[:strategic_width]` keeps three candidates on the pilot profile.
3. One candidate is executed, unless a campaign replaces it or the yield branch returns first.
4. Other legal moves are expanded later only if they fit a dormant slot, a deal-time sibling retain, or the empty-queue seeder, and only up to the proposal cap.

That is why repeated tactical improvements stay inside one foundation. The search never has the other legal children on the frontier at the moment they are legal. Moves that temporarily split a suit, occupy an empty column, or deal an awkward row are absent unless the current objective names them.

`_seed_divergences` is the closest approach to broad coverage, and it runs only after the queue is empty. It is still a capped heuristic filter.

## 7. Action 18 and the 25-action state

The g83 fixture's 18th action is `deal`. Both `deal` and the alternate reveal are legal. At the state after 17 fixture actions the portfolio selects `move 1 7 1`. The width also holds `move 7 9 1` and `move 7 8 1`. The deal is in the outside-width list, together with 12 other legal moves. The v0.123 reported line did deal on its own later path. At this historical state the deal is still a rank cutoff, not a generated successor of the committed objective.

The fixture's first 25 actions reach one physical state at corrected cost 25, one foundation, and 32 face-down cards. Twenty-two stored branches in `experiment_c_policy.json` reach that same `canonical_state_key`. The cheapest do so in 23 actions at cost 23. One of those branches is labelled `C#1` and is still open at branch cost 24. Dominance of the cost-23 ancestry is the correct exact-state rule. The legal futures match. This review does not weaken that rule to preserve the cost-25 spelling.

At that shared state the legal moves are `deal`, `move 10 4 2`, and `move 4 2 1`. The width holds the first two. `move 4 2 1` is the outside move. The top-ranked objective has no engine action, so `selected` is empty. The same classification appears at cost 23, because the physical state is the same. Cumulative cost changes the path and does not change the legal set.

## 8. Why a complete game was found earlier

Two different claims have to stay separate.

The whole-game kernel can represent every legal continuation, including awkward ones, for as long as the unique, time, and memory budgets allow. Zero-cost transfers stay in the graph until they repeat an identity at an equal or worse cost. Foundation removal is an ordinary engine effect, not a special objective. That architecture can, in principle, finish a game.

The verified complete routes on this deal were not produced by a short cold call to that kernel.

- The 186 campaign reconstructed a known g123 prefix (`source="known_g123"`, 127 actions, digest checked) and then searched. `canonical_used` is false. The harvest record cites on the order of 10k to 32k unique states depending on the summary, and a full replay of cost 186 with eight foundations. This review did not rerun it.
- `solutions/4925153_autonomous_185.moves` replays at corrected cost 185, with 189 actions, five deals, and eight foundations. Git history of that file, newest first, is `84b8d39`, `0f4b55e`, `beafe2f`, `a1a935f`, and `dcde6bc`. No current Python module writes that filename. Cold discovery from the opening is not established. The file remains a valid imported complete incumbent.
- The human reference `solutions/4925153_canonical.moves` replays at 172. It is imported.

A fresh cold call to `search_whole_game`, 80,000 unique states, ceiling 300, finished with zero foundations (section 11). The historical success is the campaign stack plus stored complete routes. It is not evidence that the same kernel, cold, inside a 150-second budget, finishes this deal.

## 9. Experimental approach

Option A. The kernel is sound and reusable. Option B would have rebuilt the same driver.

Experiment C is `search_strategy_guided` in `src/spider/global_search_experiment.py`. It calls the same `run_search` with `actions_fn=all_legal_actions` and the same seven lanes, plus one strategy lane. `strategic_action_order` sorts every legal child and raises if a child is missing. Cold mode refuses an incumbent cost. It uses the original hard cap of 300 and does not pass a lower bound. Optimise mode, which this comparison did not run, sets the ceiling to `incumbent_cost - 1` and prunes with `admissible_remaining` only.

The strategy tuple is `(face_down - 20 * foundations, -bonds, -longest run, -empty columns, stock rows, g)`. It orders one lane. It is not an admissible bound and it is not a proof. The report key used to remember a partial prefers a solved state, then more foundations, then fewer face-down cards, then more bonds, then a longer run, then fewer stock rows, then lower g. Strata record the best face-down / bond / cost cell inside each foundation and stock-row pair so one report key is not the only view. More foundations are not treated as a proof that a trajectory is globally better. No partial replaces a complete incumbent.

Control B is `search_whole_game` unchanged, through `search_original_kernel`. The only primary difference from Experiment C is the extra lane and the child order. Width, time, RSS cap, hard cost cap, deal, and rules match. `stop_on_first_terminal` is set on the experiment and left at the adapter default on Control B. It did not matter: neither search solved.

A discarded draft that taught the production controller to play the next portfolio objective after a campaign yield is stashed on `local/strategic-continuity-v0-123` and is not this experiment. Its gitignored artifact, if still present under `artifacts/human_strategy/v0_124/`, is that draft. It is not Control A and not Experiment C.

## 10. Minimal implementation

New files, isolated from `controller.py`:

- `src/spider/global_search_experiment.py` — schema `spider-global-search-0.124`
- `tools/global_search_experiment.py` — cold kernel, cold strategy, and the coverage measurement
- `tests/test_global_search_v0_124.py`

The production schema stays `spider-human-strategy-0.123`. Cold search does not read the 185 file, the 172 file, the g83 fixture, or a research checkpoint. Those files are used by the unit tests and by the offline coverage script only.

## 11. Controlled comparison

Deal `deals/4925153.txt`. Rules and corrected costs unchanged. Seed 0 on the strategy search. The kernel and the controller have no random seed. Kernel runs use `max_unique=80000`, RSS cap 3072 MB, and hard ceiling 300. The controller runs use the committed v0.123 flags: pilot profile, `--no-portfolio`, frontier 8, proposals 3, slice 24, line attempts 48, `--max-steps 1000`, one worker. Controller "unique" counts strategic states. Kernel "unique" counts authoritative identities. Those counts are not the same unit.

| Run | Wall s | CPU s | RSS MB | Stop | Foundations | Best snapshot |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| A cold, saved v0.123, 150 s budget | 94.381 | — | 139.22 | `PLANNING_STALL` | 1 | g 47, fd 24, stock 20, bonds 11, run 4 |
| A cold, this release, 40 s | 40.117 | — | 94.70 | `TIME_LIMIT` (secondary stall) | 1 | g 30, fd 28, stock 30, bonds 6, run 3 |
| B kernel, 40 s | 40.002 | 39.922 | 75.99 | time limit | 0 | g 55, fd 14, stock 0, bonds 19, run 7 |
| B kernel, 150 s budget | 102.863 | 102.578 | 154.69 | unique limit | 0 | same state as the 40 s snapshot, seen near 42 s |
| C strategy, 40 s | 40.000 | 39.938 | 121.71 | time limit | 0 | g 77, fd 16, stock 0, bonds 29, run 7, replay matches |
| C strategy, 150 s budget | 61.531 | 61.391 | 168.59 | unique limit | 0 | g 85, fd 16, stock 0, bonds 32, run 7, replay matches |

Coverage and quality, kernel family. `generated` is legal children applied, including ones later dominated. `duplicate_skips` is exact-state dominance. Heuristic exclusions are 0. Legal drops are 0.

| Run | Generated | Unique retained | Duplicate skips | Stock-deal nodes retained | Expanded |
| --- | ---: | ---: | ---: | ---: | ---: |
| B 40 s | 59,635 | 36,548 | 22,097 | not returned for an unsolved adapter path | 5,567 |
| B 150 s budget | 142,518 | 80,000 | 58,974 | same | 13,532 |
| C 40 s | 94,084 | 57,834 | 34,636 | 5,846 | 9,819 |
| C 150 s budget | 133,682 | 80,000 | 51,165 | 7,013 | 13,516 |

The retained-deal counts are nodes whose action is a deal. They are not the five deals on one path. Both best strategy paths end with an empty stock, so those paths dealt all five rows. Control B's best snapshot is also stock-empty. Control A's reported lines dealt twice in 40 seconds (30 cards left) and three times in the saved 150-second run (20 cards left).

Strata for Experiment C, best cell in each stock stage, all at zero foundations:

| Stock rows left | 40 s best | 150 s budget best |
| --- | --- | --- |
| 5 | fd 19, bonds 14, g 32, at 2.0 s | fd 19, bonds 14, g 32, at 2.1 s |
| 4 | fd 17, bonds 17, g 39 | fd 17, bonds 17, g 39 |
| 3 | fd 17, bonds 18, g 41 | fd 17, bonds 18, g 41 |
| 2 | fd 16, bonds 18, g 50 | fd 16, bonds 18, g 50 |
| 1 | fd 16, bonds 18, g 50 | fd 16, bonds 18, g 50 |
| 0 | fd 16, bonds 29, g 77, at 39.7 s | fd 16, bonds 32, g 85, at 46.2 s |

No foundation time exists for B or C. Control A had one foundation inside 40 seconds.

Control A's saved 150-second run evaluated 339 strategic states, made 373 commits, attempted 753 objectives, and recorded 21 dominance discards, 0 safe prunes, and 0 frontier transpositions. The 40-second rerun evaluated 216 strategic states, made 225 commits, attempted 513 objectives, and recorded 5 dominance discards, 20 heuristic exclusions, and 0 safe prunes. Both are cold: incumbent source none, best verified none.

Extending Control B from 36,548 to 80,000 identities did not change its best snapshot. The extra states were not a better partial under that report key. Experiment C explored faster and built more same-suit bonds (32 against 19) with two more face-down cards and a higher path cost. Under the report key, fewer face-down cards rank ahead of extra bonds, so Control B's snapshot remains the better partial of the two legal-state searches.

The useful coverage result is real. Both legal-state searches reach a stock-empty tableau with 14 or 16 face-down cards and a same-suit run of length 7. The controller's reported 40-second line still has 30 stock cards and 28 face-down cards, and its saved 150-second line still has 20 stock cards and 24 face-down cards. Its own stock-empty portfolio row in the v0.123 report had one foundation and 28 face-down cards. The kernel region is one the committed controller line does not report.

The stretch result was not met. Neither cold legal-state search removed a foundation, let alone two.

## 12. Foundations and complete solutions

| Solver | Foundations in this budget | Complete cold solution |
| --- | ---: | --- |
| Control A, 40 s and saved 150 s | 1 | none |
| Control B, 40 s and 80,000 states | 0 | none |
| Experiment C, 40 s and 80,000 states | 0 | none |
| Imported autonomous file | 8 on replay | cost 185, imported |
| Imported human file | 8 on replay | cost 172, imported |

No new complete solution was found. Nothing was written under `solutions/`.

## 13. Cold versus imported provenance

Cold runs in this release start from `opening_from_deal` and pass no action prefix. `search_strategy_guided` rejects `incumbent_cost` in cold mode. Its source does not name the 185 file, the 172 file, or the g83 fixture. Tests that replay those files are labelled imported or reference.

The 185 and 172 replays in the unit tests check integrity. They are not discoveries. The g83 fixture replays at cost 83 with foundations spades then clubs, and it is not solved. The coverage script reads that fixture and the v0.123 artifact as diagnostics.

Optimise mode on the experimental driver would mark `imported_incumbent`. The benchmark did not enter optimise mode. Anchored optimisation still refuses `mode="cold"`. The v0.123 anchored runs remain the record that anchored search operates and did not improve 185 or 172. This release did not add a rejoin method and did not repeat those anchored searches.

## 14. Tests

`tests/test_global_search_v0_124.py` contains the twenty focused checks: full legal order, labelled objective exclusions, safe versus heuristic pruning, stock deals, column order, duplicate cards, zero-cost transfers, zero-cost cycle cutoff, cheaper ancestry, admissible incumbent pruning, heuristic scores kept out of proofs, eight-foundation validation, cold refusal of a reference cost, a fixed seed, deadline and unique-limit stops, the g83 replay, the 4,500-node excavation ladder, the 185 and 172 replays, anchored cold refusal, and backend isolation.

Those twenty tests passed in 0.80 seconds. They do not run a 40-second or 150-second search.

The maintained regression list from v0.123, plus `tests/test_global_search_v0_124.py`, passed **514 tests in 240.48 seconds**. That is the previous 494 plus these 20. A bare `pytest` also collects research modules that fail to import. Those modules are outside this suite, and this release did not change them.

## 15. Runtime and memory

Kernel and strategy pilots were run one at a time. Peak RSS stayed between 76 MB and 169 MB, under the 3,072 MB cap. No run hit the RSS abort. CPU time for the four legal-state pilots is within a few tenths of a second of wall time, which is the expected shape of a one-worker search.

The controller 40-second rerun peaked at 94.7 MB. The saved controller 150-second run peaked at 139.22 MB. The controller spends most of its wall time in foundation analysis and excavation probes. The kernel spends it expanding legal children. Equal nominal time limits are not equal work.

## 16. Remaining weaknesses

The legal-state search reaches a deep stock-empty region and then stops without a foundation. The foundation lane does not distinguish a nearly finished suit from a low face-down count. Round-robin gives that lane the same number of pops as the cost lane. Extra unique states past the 42-second snapshot did not improve Control B.

The strategy lane increased bonds and did not reduce face-down below the original kernel. It is not yet a better whole-game ordering.

The controller still completes the first foundation sooner, and it still cannot develop that partial. At the measured stall it had already scored `move 2 3 3` and did not play it. Width and the campaign gate, not the node budget, closed the legal graph.

The hard cap of 300 did not bind. Observed partial costs were 30 to 85. No admissible lower bound was active in the cold pilots, so these stops are not proofs that a foundation is impossible.

`search_whole_game` does not return the action list of an unsolved best snapshot. Experiment C does, and its best partials replayed at the recorded cost. Control B's best snapshot is a metric record from the original adapter.

## 17. Recommended v0.125 architecture

Use the whole-game kernel as the global explorer for stage 1. Keep every authoritative legal successor, subject to exact-state dominance, an explicit hard cap, and the time, memory, and unique limits.

Use human-strategy scores to order that graph. A campaign macro may be tried first. It must not remove the other legal children. The production controller remains the place for tactical realisation and for the existing stage-2 tools: admissible branch-and-bound, exact-state dominance, fixed and adaptive checkpoint optimisation, and complete-game replay. Do not add another anchored rejoin in v0.125. Do not edit the incumbent registry.

Do not make the v0.124 strategy lane the default. On this deal the original seven lanes produced the better partial under the report key (face-down 14, cost 55, against face-down 16, cost 85). Keep the lane available as an optional ordering experiment.

The next labelled experiment, at the same 80,000-state cap, should add one ordering feature for suit-completion proximity and leave legal generation unchanged. The current foundation lane collapses to face-down and stock while foundations are zero, which matches the measured result of a long run and no removal. Changing the unique cap in that same run would mix two questions. This release already showed that 80,000 states under the present lanes do not improve on the snapshot found near 42 seconds.

A 900-second, 800,000-state cold envelope is a later measurement. It is justified after a suit-completion ordering exists, because the missing behaviour in this budget was selection, not an empty legal list.

Stage 1 still means an independent complete game. Stage 2 still means a verified complete incumbent. The 185 and 172 files stay imported references. A partial trajectory still cannot replace either of them.

The target is a solver that explores the game broadly and uses strategic intelligence to search the most promising regions first. A solver that only searches moves it can explain strategically is the controller's current shape, and this deal shows where that shape stops.

## 18. Reproduction

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 tools/global_search_experiment.py --coverage --out artifacts/global_search/v0_124/coverage.json

py -3 tools/global_search_experiment.py --variant kernel --time-limit 40 --max-unique 80000 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_124/control_b_40.json

py -3 tools/global_search_experiment.py --variant strategy --mode cold --seed 0 --time-limit 40 --max-unique 80000 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_124/experiment_c_40.json

py -3 tools/global_search_experiment.py --variant kernel --time-limit 150 --max-unique 80000 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_124/control_b_150.json

py -3 tools/global_search_experiment.py --variant strategy --mode cold --seed 0 --time-limit 150 --max-unique 80000 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_124/experiment_c_150.json

py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 1000 --memory-mb 3072 --out artifacts/global_search/v0_124/control_a_40.json

py -3 -m pytest tests/test_global_search_v0_124.py -q --tb=short

py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py tests/test_human_strategy_v0_119.py tests/test_human_strategy_v0_120.py tests/test_human_strategy_v0_121.py tests/test_human_strategy_v0_122.py tests/test_human_strategy_v0_123.py tests/test_global_search_v0_124.py -q --tb=line
```

The regression command is the v0.123 file list plus `tests/test_global_search_v0_124.py`. A bare `pytest` also collects research modules that fail to import. Those modules are outside the maintained suite.

The saved Control A 150-second record is `artifacts/human_strategy/v0_123/experiment_c_policy.json`. It was not rerun. The historical 186 campaign was not rerun.

## 19. Changed files

- `src/spider/global_search_experiment.py` (new)
- `tools/global_search_experiment.py` (new)
- `tests/test_global_search_v0_124.py` (new)
- `docs/global_search_architecture_v0_124.md` (new)

Gitignored measurements under `artifacts/global_search/v0_124/`:

- `coverage.json`
- `control_a_40.json`
- `control_b_40.json`
- `control_b_150.json`
- `experiment_c_40.json`
- `experiment_c_150.json`

Unchanged: `src/spider/engine.py`, `src/spider/rules.py`, `src/spider/human_strategy/controller.py`, `solutions/4925153_incumbent.json`, `solutions/4925153_autonomous_185.moves`, `solutions/4925153_canonical.moves`, and the v0.123 report.

## 20. Git status

Branch `local/global-search-review-v0-124` at `82201ec`.

After these files were added, `git status --short` shows the four new paths above as untracked. No tracked file is modified. Nothing was committed, pushed, merged, or opened as a pull request.
