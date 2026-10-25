# Foundation-critical excavation and probe recovery v0.116

v0.115 removed two foundations from deal 4925153 and then stopped. Spades left at corrected g=19. Clubs left at corrected g=83. Eight further legal moves reached g=91 with 21 face-down cards, and the search reported `PLANNING_STALL` after about 24.9 seconds of a 150-second budget. The hearts campaign could name a buried 8H and a buried 4H. The tactical realiser answered with `PROBE_LIMIT` and did not uncover either card.

v0.116 stays inside that controller. A buried foundation card is now an excavation objective. The existing cost-aware search builds a legal sequence, the Spider engine plays every action, and a miss inside a small budget can be tried again under a larger budget or a changed board. The frontier width stays 8.

The live continuation from the replayed g=83 board does new work. It refuses to park `3s` on the only empty column merely to uncover `Ah`. It moves the diamond run `Qd`–`8d` onto that column, which uncovers `Kh`, and the hearts run `Qh`–`6h` then lands on that king. The same-suit build is `Kh`–`6h`, eight cards. Corrected g is 91. Foundations are still spades then clubs. `solved` is false. A third foundation was not removed.

`engine.py`, `rules.py`, corrected MobilityWare scoring, the 172 and 185 solution files, the incumbent registry, historical campaigns, and Play Lab were not modified. Nothing in this release was committed.

## 1. Baseline

Schema is `spider-human-strategy-0.116`. The default artifact directory is `artifacts/human_strategy/v0_116/`.

Branch `local/foundation-excavation-v0-116`. HEAD `7acca97462467b1cd49022ea0239f160c1d185ea` (`Add third-foundation progression and viability analysis v0.115`). The v0.116 edits are uncommitted.

Pilot limits used below: one worker, frontier 8, 3 proposals, slice 24, per-line attempt cap 48, RSS abort 3072 MB, portfolio off. The g=83 and cold pilots use 150 seconds and 220 steps. Seed 111 uses 60 seconds, 80 steps, slice 8, and a per-line cap of 24. Smoke still has frontier 1. Extended was not launched. Cold mode still rejects an incumbent prefix. `prefix_injected` is false on every run below.

`FOUNDATION_TARGET_REACHED` still counts foundations gained during the call. From g=83, target 1 asks for one more removal. `SOLVED_VALID` still requires `is_solved()`, which is eight foundations, an empty stock, and an empty tableau.

## 2. Why the v0.115 probes stalled

The g=83 fixture is `tests/fixtures/g83_4925153_actions.json`. Replay spends corrected g=83, removes spades then clubs, leaves stock empty, leaves column 1 empty, and leaves 23 face-down cards. `solved` is false. g plus the admissible remainder is 136.

Two physical copies matter, and they are not interchangeable.

| Card | At g=83 | What the old realiser did |
| --- | --- | --- |
| 8H | Column 7, the only face-down card, under `6c Ah 3s`. Cover 3 | Returned `move 7 1 1`. That parks `3s` on the empty column and lowers cover from 3 to 2. `Ah` is then on top and has no tableau destination. The empty column is gone |
| 8H | Column 2, inside `10h`–`6h`, already a legal moving head | No excavation. The card can already move |
| 4H | Column 8, face-down, cover 5, under `4s 7d 5s As` | A short peel onto the empty column, which is the same column the 8H peel wants |
| 4H | Column 9, face-up, cover 5 | A different physical card |

`move 7 1 1` is legal. It is also a dead end for the card underneath. After that single move, a tableau search through corrected cost 10 exhausts and the buried 8H stays at cover 2. The old caller logged every empty result as `PROBE_LIMIT`, including searches that had exhausted their graph. The cache then treated that token as a reason not to look again. Extra clock time repeated the same miss.

The v0.115 suffix from g=83 is `move 2 5 5`, `move 7 1 1`, `move 4 2 3`, `move 9 1 2`, `move 6 3 3`, `move 3 4 4`, `move 3 2 1`, `move 4 3 4`. Replay ends at g=91, two foundations, 21 face-down, no empty column, admissible remainder 50, g plus the bound 141.

At that g=91 board the new realiser exhausts the tableau graph and returns no actions. Raising the node cap from 2000 to 4500 does not grow the graph. Stock is empty, so a deal-allowed search has nothing to deal. A cost ceiling above 8 was not run.

| Card at g=91 | Place | Cover | Movable suffixes | Cost 6 / 2000 and cost 8 / 4500 |
| --- | --- | --- | --- | --- |
| 8H face-down | Column 7, down index 0 | 2. Above it, top first: `Ah`, `6c` | `Ah` only, and `Ah` has no destination | `GRAPH_EXHAUSTED_WITHIN_BOUND`, 216 nodes, cover stays 2. About 0.27 s |
| 8H face-up | Column 5, inside the hearts run, up index 5 | 2. Above it: `6h`, `7h` | `6h` can move. The 8H is not the head | Exhausted, 234 nodes, strategy `receiver-then-peel+unrestricted`, cover stays 2 |
| 4H face-down | Column 8, down index 1 | 5. Above it, top first: `As 5s 7d 4s 2c` | `As` only, no destination | Exhausted, 216 nodes, cover stays 5 |
| 4H face-up | Column 9, up index 2 | 3. Above it: `3c 2d 3d` | `3c` only, no destination | Exhausted, 216 nodes, cover stays 3 |
| 5H face-down | Column 2 | 15 | The column is deep | Exhausted, 270 nodes, unrestricted fallback, cover stays 15 |
| 5H face-up | Column 9 | 4 | Under `4h 3d 2d 3c` | Exhausted, 216 nodes, cover stays 4 |

The g=91 board has no legal partial excavation inside corrected cost 8. The empty column was spent by `move 7 1 1` before a longer plan could use it. The hearts card that would extend `10h`–`6h` is 5H, and neither copy moves inside this bound.

Before that trap, the buried 8H on column 7 does have a legal reveal. From raw g=83, `plan_obstructed_access` at cost 8 and 4500 nodes returns status `exposed`, cover 3 to 0, corrected cost 7, 2999 nodes. The card flips face-up and is not a legal moving head. The same call after only `move 2 5 5` still finds an expose, cost 7, 3111 nodes, 6.63 seconds. Those moves put `5s` onto the hearts run. The live controller does not play them. Section 8 records what it plays instead, and why that is the stronger hearts build.

An unguarded live continuation, measured before the receiver check in section 6, still opened with `move 2 5 5` and `move 7 1 1`. It then diverged from the eight v0.115 moves, reached g=92, and still had two foundations, 21 face-down cards, and g plus the admissible bound equal to 141. That run is the reason the empty-column check exists. It is not the result in section 8.

## 3. Excavation objective

`plan_obstructed_access` is the same realiser the foundation campaign already called. It now takes one physical card, or a rank chosen from the campaign's source list when several copies exist. Identity is object identity. Two cards that compare equal and sit in different places get different source keys.

Three results stay distinct:

| Status | Meaning |
| --- | --- |
| `progress` | The target's cover falls. The card stays face-down, or it stays covered. An intermediate move may raise cover |
| `exposed` | The target is face-up. It may still be unable to move |
| `unlocked` | The target is the head of a legal move |

A plan counts as executable only when `progress` finishes with a strictly smaller cover, or when `exposed` / `unlocked` finishes at cover 0. A sequence whose net cover does not fall is discarded even if every step was legal. Face-up does not mean mobile. Mobile does not mean the card completes a suit.

The engine's `apply_action` generates the cost and the next state. Knowing a face-down card's suit and rank can choose the target. It cannot move that card until the cards above it have moved legally.

Blockers are the physical cards above the target, top first. Movable groups are the legal suffixes of the face-up pile, not one card at a time. Receivers are columns the suffix can move to, including an empty column. Setup may build a receiver on another column before any card leaves the target column. A whole-column move onto an empty column still costs 0 and is expanded before a cost-1 edge. A peel that fills the last empty column and leaves the next card with no move and no empty column is not taken. A peel that uncovers the target is kept even when the uncovered card cannot yet move.

Temporary parking is allowed. The park fixture moves `5s` onto `6s`, which raises the buried card's cover from 1 to 2, then moves `6s`–`5s` onto `7d` and flips the target. Cover goes 1, then 2, then 0. That plan is `exposed`, cost 2, and the card is not movable.

Clubs are the non-hearts fixture. A face-down 8C under `6c` and `3s` has receivers `4d` and `7d`. Cost 1 returns `progress`, cover 2 to 1, and the 8C stays face-down. Cost 4 returns `exposed`, actions `move 1 2 1` then `move 1 3 1`, cost 2, cover 0, and the 8C is not a legal head. A second, already movable 8C is left alone.

## 4. Search and cost

The search is Dijkstra on corrected MobilityWare cost. The secondary key is how many blockers still lack a home. That number orders the heap. It does not prune. Zero-cost edges come out before cost-1 edges. Speculative campaign costs are not used as bounds.

The strategy name `receiver-then-peel` freezes the target column during setup. If that restricted graph exhausts, the target column has a legal move, nodes remain, and no executable plan was found, one unrestricted pass may use the leftover node budget. The strategy string becomes `receiver-then-peel+unrestricted` and is part of the cache key. On the g=91 buried 8H the target column cannot move, so the fallback does not run.

A full reveal that fits in the cost ceiling stops the search. A peel that only makes `progress` is remembered and the search continues, so a later reveal can replace it. The g=83 face-up 5H shows why the search must be allowed to finish its budget: the best plan inside cost 8 is `move 9 7 2` then `move 9 1 1`, cover 6 to 3, cost 2, and the search still runs to the node cap because a reveal was not found. `NODE_LIMIT` with that partial plan is a real reduction. It is not a proof that cover 0 is impossible at a higher ceiling.

Live budgets, and when they grow:

| Caller | First probe | Expansion |
| --- | --- | --- |
| Opening access, while a prerequisite is still shallow | Cost 4, 800 nodes, about 2 seconds | None |
| Elapsed access, after the campaign's stock epoch has passed | Cost 6, 2000 nodes, 3 seconds | Cost 8, 4500 nodes, 12 seconds, and only when the target is a connector or a chosen source, the first plan is not executable, the miss is allowed to grow, and more than a second remains |
| Recovery | Cost 4, 600 nodes | None. One recovery per canonical state |

Expansion is refused when the probe already returned `exposed` or `unlocked`, when the category is `SUCCESS`, or when an exhaustive miss was already run at cost 8 or more. `NODE_LIMIT`, `TIME_LIMIT`, `PROBE_LIMIT`, and a partial result may grow once. An exhaustive miss at cost 8 does not grow again on the same strategy and the same deal policy.

The elapsed caller looks at two targets. Connectors of an exposed same-suit run come first, then chosen obstructed copies, then at most two other buried cards of the suit. It stops early when it has an `exposed` or `unlocked` plan that does not shorten a same-suit run of length at least 5. A mere `progress` result does not suppress the second target. Among the plans it keeps, a shortening plan ranks behind one that leaves the long run intact. Outcome order is then unlocked, exposed, progress, then smaller remaining cover, then smaller corrected cost.

## 5. Probe cache

The cache key is the state fingerprint, the physical source key, whether deals are allowed, the cost ceiling, the node ceiling, and the strategy name. An exact key is never searched twice, including an inconclusive result.

| Stored result | What a later call may do |
| --- | --- |
| `SUCCESS` (`exposed` or `unlocked`) | Reuse it when its corrected cost fits the new ceiling and the stored ceiling is no higher than the request |
| `GRAPH_EXHAUSTED_WITHIN_BOUND` or `PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS`, with no actions | Suppress the same strategy and the same deal policy up to the cost that was actually exhausted. A higher ceiling, `allow_deals=True`, or a different strategy runs |
| `PARTIAL_PROGRESS`, `NODE_LIMIT`, `TIME_LIMIT`, `PROBE_LIMIT` | Answer only the exact key. A larger node cap or a larger cost ceiling is a new probe |

`PROBE_LIMIT` means the search stopped on its budget. It does not prove the card is unreachable. A tableau-only exhaustion does not answer a search that is allowed to deal. A pre-search time guard (`time_left` under 0.05 seconds) returns `TIME_LIMIT` and is not stored. A search that itself hits the deadline is stored under its exact key.

`close_foundation_campaign` drops `excavation_cache`, `access_cache`, `buried_tried`, and the bottleneck cache together with the old epoch state. The next suit does not inherit the previous suit's misses.

The bottleneck probe keeps its own key: fingerprint, deals off, cost 8, 2500 nodes, strategy `tableau-completion`. A resource limit on that probe is not stored. This release does not turn a bottleneck cache hit into a replayed plan.

## 6. Live integration

`propose_foundation_step` still tries a same-suit join before excavation. On g=83 that join is `move 2 5 5`, which extends `10h`–`6h` onto `Jh`. Excavation runs after that join when no further join is waiting.

Opening access used to accept the shallowest chosen card. After the join that card is `Ah` on column 7, cover 1, and the plan is `move 7 1 1`. `Ah` becomes face-up and nothing in hearts can land on it, the buried 8H stays in the column, and the only empty column is gone. `_empty_spent_without_receiver` rejects that plan. A plan that spends the last empty column is kept when the uncovered card is a legal head, or when a same-suit run can legally land on it.

The next shallow target is `Kh` on column 4, cover 5, under `Qd Jd 10d 9d 8d`. One move, `move 4 1 5`, puts that diamond run on the empty column and leaves `Kh` on top. The hearts run can then land on it. The log line is `tableau:6:up:1 spends the only empty column and Ah is not a receiver for its suit; not played`, followed by the king expose.

A held multi-action plan appends `foundation: continue {label}` as each step is played, so a campaign that stays inside one plan is still reported as continuing. An `ACCESS` plan is not dropped for an abandonment reason. Legality is checked when the step is played. The run guard still redirects a first action that would cover a same-suit run of length at least 7, including an `ACCESS` plan. A note that says the park is recoverable is left alone.

When the elapsed probe misses, the campaign yields. The yield names the real category (`GRAPH_EXHAUSTED_WITHIN_BOUND`, `NODE_LIMIT`, `PARTIAL_PROGRESS`, `PROBE_LIMIT`, or `TIME_LIMIT`) and says the miss leaves the suit eligible. Hearts is not forced. Diamonds, the second clubs, and the second spades stay in the portfolio. The frontier limit is still 8. A full frontier records `dropped_full` and the event says the rejection is not exhaustion. An attained excavation state uses the normal `consider` path.

Excavation is requested for a foundation dependency. It is not used to chase face-down count by itself.

## 7. Experiment A — the g=91 board

The v0.115 suffix was replayed from the g=83 fixture. The resulting board matches section 2: g=91, foundations spades then clubs, 21 face-down, stock 0, no empty column, 22 same-suit bonds, 46 once the removed suits are counted, admissible remainder 50, g plus the bound 141, `solved` false.

No buried or immovable hearts copy in that table produced a legal action inside cost 8. There is no partial excavation to execute on this board. The failure is the graph, inside this cost and this deal policy. It is not an open node cap.

## 8. Experiment B — continuation from g=83

Diagnose mode, opening g=83, goal `foundations`, target one additional foundation, the pilot limits in section 1, 150 seconds. The 83 actions were replayed to build the board. They were not passed in as incumbent moves. `prefix_injected` is false.

The selected suffix, each step cost 1:

| Move | g after | Hearts run |
| --- | --- | --- |
| `move 2 5 5` | 84 | `Qh Jh 10h 9h 8h 7h 6h` (7) |
| `move 4 1 5` | 85 | unchanged. `Kh` on column 4 is uncovered. Cover of that king goes from 5 to 0 |
| `move 5 4 7` | 86 | `Kh Qh Jh 10h 9h 8h 7h 6h` (8) |
| `move 1 5 5` | 87 | unchanged. The diamond run leaves column 1 |
| `move 7 1 1` | 88 | unchanged |
| `move 3 2 1` | 89 | unchanged. 22 face-down |
| `move 3 5 1` | 90 | unchanged. 21 face-down |
| `move 2 3 1` | 91 | unchanged |

Independent replay spends 91 and matches `cumulative_g`. Foundations are still spades then clubs. Face-down 21. Stock 0. No empty column. Same-suit bonds 23, 47 with the two removed suits. Admissible remainder 49. g plus the bound is 140. `solved` is false. `result.solved` is false. Status `PLANNING_STALL`. Elapsed 143.224 seconds. Peak RSS 93.1 MB. Unique states 19. Objectives attempted 23. Backtracks 18. Cache hits 17, misses 24. Deals 0. Frontier generated 11, explored 11, `dropped_full` 0, same-move skips 2, unique histories 10, still queued 0. The suffix's first eight moves are not the v0.115 suffix.

The strategic gain is the hearts build. At g=83 the longest hearts run on column 2 is `10h`–`6h`. After the join it is `Qh`–`6h` on column 5. `move 4 1 5` does not lengthen it. It makes `Kh` a legal home for that run. `move 5 4 7` is the same-suit join onto that king. The king is not itself a moving head. The run moves onto the king. Eight hearts in order is the opportunity this excavation creates. It does not remove the hearts foundation. Ranks 5 through ace are still required. The immediate connector is 5H.

At the end of this line the 5H copies are unchanged in the way that matters: column 9 face-up at cover 6, and column 2 face-down at cover 11. The elapsed probe on the face-up 5H returned `GRAPH_EXHAUSTED_WITHIN_BOUND` at cost 6 (2000 nodes) and again at cost 8 (4500 nodes), with no actions. The face-down 5H returned `PARTIAL_PROGRESS` at both ceilings and the executable check did not play it, so its net cover did not fall. Both misses left hearts eligible. The buried 8H on column 7 is at cover 2. The other 8H sits inside `Kh`–`6h`. Uncovering the duplicate does not extend the run.

A retained branch reaches g=93 with the same two foundations and 21 face-down cards. The extra cost does not remove a third suit. The selected line is the g=91 line. Campaigns entered were `H#1`, `D#1`, and `S#2`. `C#2` was retained from g=88 and later produced an expose of a jack of clubs (cover 5 to 0, two legal moves) on that branch. The selected line does not depend on that expose.

Compared with the v0.115 g=91 board, this line has the same corrected g, one fewer point of admissible remainder, one more same-suit bond, and a hearts run that includes its king. Six foundations remain. 91 plus 49 is 140, which is still under 172 and under 185. The bound does not say those reference totals are out of reach, and this trajectory is not a solution.

## 9. Experiment C — cold target of three

Cold, from move 0, target 3, the same 150-second pilot, no g=19, g=83, or g=91 prefix.

Status `PLANNING_STALL`. The selected trajectory has 47 actions, corrected g=47, one foundation (spades), 24 face-down, stock 20, three deals, no empty column, 11 same-suit bonds, 23 with the removed suit, admissible remainder 4, g plus the bound 51. Replay matches. `solved` is false. Elapsed 150.021 seconds. Peak RSS 61.1 MB. Unique states 84. Attempted 140. Backtracks 1575. Cache hits 1559, misses 77. Frontier generated 22, explored 7, `dropped_full` 10, same-move skips 1512, unique histories 8, still queued 5, replaced 0. `prefix_injected` is false.

The admissible remainder of 4 is the computed lower bound on remaining corrected cost. Seven foundations are still on the table, 24 cards are face-down, and 20 cards are in the stock. The position is not a near-solution.

The first 22 actions are the first 22 actions of the g=83 fixture, including `move 2 1 12` at action 19, which removes spades. Action 23 is `move 8 10 1`. The fixture's action 23 is `move 4 2 1`. The cold search does not return to the clubs removal inside 150 seconds. Every retained branch has one foundation. The deepest retained corrected costs are g=55 (still open, 28 face-down) and g=54. None of them is a second foundation.

v0.115's cold target-3 run, under the same 150-second pilot, reached the two-foundation line and the g=91 stall, with 14 proposals dropped for frontier capacity. This run drops 10 proposals for the same reason and leaves 5 lines queued. The frontier width was not increased.

Elapsed excavation on this run did fire. Examples: `Kh` and `6h` exhausted in 2 nodes at both ceilings; `Jh` returned `PARTIAL_PROGRESS` (271 nodes, then 1151); `7h` returned `PARTIAL_PROGRESS` and then `PROBE_LIMIT` at 347 nodes; one `2c` returned `PARTIAL_PROGRESS` and the other copy exhausted at 3111 nodes inside cost 8. The misses left the other suits eligible. They did not produce a second removal.

## 10. Experiment D — seed 111

`random.Random(111)` shuffles a copy of `deals/4925153.txt`. The layout is not deal 4925153. Cold, target one foundation, 60 seconds, 80 steps, slice 8, line cap 24, frontier 8, one worker. The v0.115 seed-111 note used 40 seconds and a 50-step cap, so the two runs are not the same budget.

Status `PLANNING_STALL`. Corrected g=23. Foundations 0. Face-down 30. Stock 40, so one deal. `solved` is false. Elapsed 60.199 seconds. Peak RSS 54.8 MB. Unique states 76. 23 actions. `dropped_full` 1. Still queued 5. `prefix_injected` is false. Campaigns entered: `C#1`, `S#1`, `D#1`. `H#1` was not entered. The elapsed-excavation event list is empty. The non-hearts excavation in section 3 is the clubs fixture, not this shuffle. This pilot shows that the controller runs on another four-suit layout and does not require the hearts geometry of deal 4925153.

## 11. Tests, runtime, and memory

The new file is `tests/test_human_strategy_v0_116.py`. The checks are properties of the realiser and the cache. The g=83 actions are a replay source for one buried card. They are not a script the live policy looks up.

| Test | What it holds |
| --- | --- |
| Buried clubs identity, cover, and blockers | One face-down 8C, cover 2, blockers `6c` then `3s` |
| Multi-move clubs reveal | Two legal receives, cost 2, cover 0, card not movable |
| Face-up and immovable | Uncovered 8C has no legal move |
| Two physical copies | The free 8C is not planned. The buried 8C is |
| Parking | Cover may rise from 1 to 2 and then fall to 0 |
| Zero-cost and the dead-end peel | A lone king onto empty costs 0. `Ah` onto the only empty is not success. The exhaustion does not suppress a higher ceiling, a deal, or another strategy |
| Probe categories | `PROBE_LIMIT` stays inconclusive. An exact repeat hits. A different node cap misses |
| Revisit | `NODE_LIMIT` at one node can be searched again at a larger cap. The identical cap hits |
| Time guard | A skip under 0.05 seconds is not cached |
| Live clubs campaign | The elapsed caller returns an `ACCESS` plan, replay cost 2, and the frontier accepts it. A ninth distinct signature on a full frontier of 8 is refused and `dropped_full` increases. Close drops the excavation cache |
| g=83 buried 8H | The direct realiser reveals it in more than one move, cost above 1, cover 3 to 0, and the card is not movable. The plan is not only `move 7 1 1` |
| Empty column and a receiver | Parking `3s` to uncover `Ah` is rejected. Uncovering `Kh` when a hearts run can land is kept |
| After the hearts join | Live access on the post-join g=83 board refuses the ace trap and leaves a hearts king that the run can join, width at least 7, and the column then contains king, queen, and six |
| g=19 and g=83 replay | Both trajectories still replay. Spades at g=19. Spades then clubs at g=83. `solved` is false |
| Eight foundations | Seven empty foundations are not solved. Eight are. The g=83 board is not solved |

`tests/test_human_strategy_v0_112.py` accepts `GRAPH_EXHAUSTED_WITHIN_BOUND`, `NODE_LIMIT`, and `TIME_LIMIT` as well as `PROBE_LIMIT`. Each of those still has to leave the text `not infeasibility`. The g=32 hearts probes are exhaustive inside the cap, and the campaign still yields, tries diamonds and clubs, and deals.

The regression command in section 13 passed 377 tests in 282.41 seconds, exit 0. That is the previous 362 plus these 15. `registry.py` was not edited. Principle 11 stays CONDITIONAL.

Peak RSS on the three pilots: 93.1 MB from g=83, 61.1 MB cold, 54.8 MB on seed 111. All three used one worker. None approached the 3072 MB abort.

## 12. What remains, and what v0.117 should do

No third foundation came off deal 4925153. The best measured g=83 continuation is corrected g=91, two foundations, 21 face-down, hearts built through `Kh`–`6h`, admissible total 140, 143.224 seconds. The cold target of three removes only spades, at g=47, with five lines still queued and ten proposals never started because the frontier of 8 was full.

The highest-value unresolved card on the g=83 continuation is the 5H that would extend `Kh`–`6h`. The face-up copy is column 9 at cover 6. Inside corrected cost 8 the tableau graph is exhausted, at 2000 nodes and again at 4500, and no legal action is returned. The other copy is face-down on column 2 at cover 11. Its partial probe did not reduce net cover. The buried 8H on column 7, cover 2, is a second copy of a rank already inside the run. The direct realiser can expose it at cost 7 from the post-join board. Doing so lands cards on the hearts run and does not add a new hearts rank.

The g=91 exhaustion inside cost 8 should not be repeated unchanged. A higher cost ceiling on that board was not measured. Stock there is empty.

Widening the frontier above 8 is still a separate experiment. Cold target-3 dropped 10 proposals. Seed 111 dropped 1. This release kept the width at 8 so the excavation result would not be mixed with a larger frontier. v0.117 should not bundle a jump from 8 to 32 with another excavation change.

The cold search's departure at action 23 (`move 8 10 1` instead of `move 4 2 1`) is the reason it never reached the clubs removal in 150 seconds. Putting that line back by replaying the fixture would not be a new search. The useful next measurement is whether the post-spade choice can prefer a continuation that still has a clubs build, while the 5H excavation gets a budget that is allowed to differ from the exhausted cost-8 tableau probe. A 600-second run was not started.

Eight foundations remain the only finished game. `Kh`–`6h` plus two removed suits is a partial trajectory.

## 13. Reproduce

Branch `local/foundation-excavation-v0-116`. HEAD `7acca97462467b1cd49022ea0239f160c1d185ea`. The v0.116 edits are uncommitted. Do not commit them as part of reading this note.

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py -q --tb=line
```

Experiment A replays the g=83 fixture plus the eight v0.115 moves and calls `plan_obstructed_access` on each immovable hearts copy at cost 6 / 2000 nodes and cost 8 / 4500 nodes. Experiment B calls `solve` in diagnose mode on the replayed g=83 state with `opening_g=83`, `goal="foundations"`, `target_foundations=1`, and the pilot overrides in section 1. Experiment C calls `solve` in cold mode from the opening with `target_foundations=3` and the same pilot. Experiment D shuffles the deal with `random.Random(111)` and calls cold `solve` with `target_foundations=1`, 60 seconds, 80 steps, slice 8, and line cap 24. There is no CLI flag for the g=83 checkpoint. `--root post-sd3` remains the 185-prefix diagnose root and was not used.

Measured JSON from this run is under `artifacts/human_strategy/v0_116/` (`experiment_a_g91.json`, `experiment_b_g83.json`, `experiment_c_cold.json`, `experiment_d_seed111.json`). That directory is gitignored.

Files changed, against `7acca97`. Untracked files are the new test and this note.

```text
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/foundation_direction.py
 M tests/test_human_strategy_v0_112.py
 M tools/human_strategy_solver.py
?? docs/foundation_excavation_v0_116.md
?? tests/test_human_strategy_v0_116.py
```

`git diff --stat` reports 932 insertions and 153 deletions across the five tracked files. `engine.py` and `rules.py` are absent from the status. No commit, push, merge, or pull request was made.
