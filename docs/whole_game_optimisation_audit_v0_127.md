# Whole-game optimisation audit v0.127

Deal `4925153`. Corrected MobilityWare cost. Research only. No solver behaviour was changed. No commit, merge, or push of this audit.

Labels used below:

- **Verified.** Replayed on `SpiderState` under `MW_RULES`, or read from the cited source.
- **Hypothesis.** Consistent with the verified facts, and not itself a proof.
- **Recommendation.** Not implemented in this assignment.

The 172 route is `solutions/4925153_canonical.moves`. The 185 route is `solutions/4925153_autonomous_185.moves`. The 185 file is a replay-valid complete solution. Its independent cold-discovery provenance is not established. A valid replay is not a discovery.

## Executive summary

The whole-game kernel still walks a huge opening because the runs that have been used as the live search are cold runs. Cold mode refuses the 172 incumbent. The suit and original-kernel paths then apply a hard corrected-cost cap of 300 and pass no admissible remainder. A state is discarded for cost only when its own `g` exceeds 300. Both complete routes finish well below that cap, so the cap removes nothing on the routes we already know.

The admissible remainder that does exist is too small to police the opening even if the 172 ceiling were switched on. While stock remains, `admissible_remaining` is the number of remaining deals plus a residual-reveal term. On both routes that value stays in the range 1 to 5 until the stock is empty. `g + h >= 172` therefore starts to bind only when `g` is already near 167. The search can spend its unique-state budget on unproductive construction and still be inside the proof.

The bound becomes informative when the stock is empty. At the 172 route's position immediately after the fifth stock deal, `g = 150` and the stock-empty assembly bound is 18, so `g + h = 168`. That does not prove the position can beat 172, and it does not prune it. At the 185 route's matching position, `g = 134` and the assembly bound is 42, so `g + h = 176`. That state cannot beat a verified 172 incumbent. The machinery to say so is already in `proof_prune` and `stock_empty_assembly_h`. The cold whole-game path does not call it.

The 13-move gap is also already visible on the boards, without a new heuristic. Before the fifth deal the 172 route has spent 149 and the 185 route has spent 133. After that deal the 172 route has 54 same-suit bonds and four same-suit landings. The 185 route has 30 bonds and no same-suit landing. The fifth deal consumes 185's only empty column. The 172 route then finishes in 22 moves. The 185 route finishes in 51. The earlier analysis is reproduced: the more expensive preparation is the cheaper game.

Neither route contains an exact-state cycle. There is no demonstrated block of moves that returns to the same position at a higher corrected cost and can simply be deleted. The concrete opportunities inside 172 are six short reversal spans that the existing anchored optimiser already selected and, in v0.118, did not finish at 2,500 states. Raising that existing cap, then accepting a result only when the spliced game replays below 172, is the smallest experiment that can produce a verified improvement.

The thirty human principles in `src/spider/human_strategy/registry.py` are implemented in the Human Strategy Controller and covered by tests in `tests/test_human_strategy_v0_107.py`. The live whole-game kernel (`search_suit_ordered`, `search_whole_game`, `search_strategy_guided`) does not call that controller. `tools/global_search_experiment.py` states that it does not call the production controller. Backward stock wishes, width, and dormant objectives therefore do not influence the search that recent whole-game runs actually executed.

## 1. Repository baseline and actual code status

**Verified.** Branch `local/search-optimisation-audit-v0-127` was created from commit `1a6a8fc59b964725ced4b8c678a0b117b7641202` (`1a6a8fc Document closed four-foundation endgame v0.126`). Parent is `49595bc5415d96f3a949b66b29059a0ad81eef03` (v0.125). The working tree was clean at the branch point.

The v0.126 commit contains:

- `docs/state_first_completion_v0_126.md`, including the 41,472-state closed component at the g139 checkpoint, maximum corrected cost 153, face-down count frozen at 8, no empty column, and no fifth foundation.
- `tests/fixtures/g139_v0125_partial.json`.
- `tests/test_global_search_v0_126.py`.
- The checkpoint-continuation changes in `src/spider/global_search_experiment.py` and `tools/global_search_experiment.py`.

`git diff 49595bc HEAD` at that commit does not touch `solutions/4925153_canonical.moves`, `solutions/4925153_autonomous_185.moves`, `src/spider/engine.py`, `src/spider/rules.py`, `src/spider/human_strategy/controller.py`, or `tests/test_human_strategy_v0_120.py`.

File hashes at the audit, SHA-256:

| File | Hash |
|---|---|
| `solutions/4925153_canonical.moves` | `18338a08576ad24e9af1f4ba2e7db3e28768788dd511e823193b1937f3feef33` |
| `solutions/4925153_autonomous_185.moves` | `b19c56e957ac2666298a80118d54ff7fca6c8114ed7d27590e2e98a017d4fb73` |

Independent replay through `replay_actions_detailed` under `MW_RULES`:

| Route | Explicit actions | Tableau moves | Deals | Foundations | Corrected MW | Legacy MW | Solved |
|---|---:|---:|---:|---:|---:|---:|---|
| 172 | 174 | 169 | 5 | 8 | 172 | 163 | yes |
| 185 | 189 | 184 | 5 | 8 | 185 | 177 | yes |

**Outstanding regression, not resolved and not rerun.** The v0.126 report records two full-suite executions: 551 collected, 550 passed, 1 failed, in 221.00 s and 212.73 s. The failure is `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`. It expected `TIME_LIMIT`. The full-process solve returned `PLANNING_STALL` before the six-second deadline. Isolated runs pass. v0.126 did not edit that test or the Human Strategy Controller. This audit did not edit them either, and it did not rerun the suite. The failure remains a separate investigation before any future solver change is accepted.

The committed v0.126 document's section 22 still describes the pre-commit dirty tree and names HEAD `49595bc`. The commit itself is the checkpoint above. This audit does not rewrite that historical section.

`engine.py` and `rules.py` are unchanged by this assignment. Production solver behaviour is unchanged.

## 2. Forward analysis of both complete solutions

Action numbers below are 1-based positions in the moves files. `g` is corrected MobilityWare cost after the action. Face-down counts and bonds are the engine state at the named horizon. Bonds count adjacent face-up cards that are the same suit and one rank apart.

**Verified segment partition.** Deal actions cost 1 on both routes, so they contribute 0 to the gap.

| Segment | 172 actions | 172 cost | 185 actions | 185 cost | 185 minus 172 |
|---|---|---:|---|---:|---:|
| Opening, before SD1 | 1–51 | 50 | 1–35 | 32 | −18 |
| After SD1, before SD2 | 53–89 | 37 | 37–67 | 31 | −6 |
| After SD2, before SD3 | 91–101 | 11 | 69–77 | 8 | −3 |
| After SD3, before SD4 | 103–119 | 17 | 79–126 | 48 | +31 |
| After SD4, before SD5 | 121–151 | 30 | 128–137 | 10 | −20 |
| After SD5, to solved | 153–174 | 22 | 139–189 | 51 | +29 |

The signed differences sum to +13. That is the finished gap. A segment difference is a location of cost. It is not, by itself, a cause.

**Verified stock horizons.**

| Horizon | g 172 | g 185 | fd 172 | fd 185 | empty 172 | empty 185 | bonds 172 | bonds 185 | foundations |
|---|---:|---:|---:|---:|---|---|---:|---:|---|
| Opening | 0 | 0 | 44 | 44 | none | none | 0 | 0 | 0 |
| Pre-SD1 | 50 | 32 | 12 | 18 | none | none | 22 | 16 | 0 |
| Pre-SD2 | 88 | 64 | 8 | 10 | none | none | 38 | 33 | 0 |
| Pre-SD3 | 100 | 73 | 7 | 9 | none | none | 35 | 26 | spades |
| Pre-SD4 | 118 | 122 | 7 | 2 | none | column 2 | 42 | 39 | spades |
| Pre-SD5 | 149 | 133 | 1 | 2 | none | column 9 | 50 | 30 | spades, diamonds |
| Post-SD5 | 150 | 134 | 1 | 2 | none | none | 54 | 30 | spades, diamonds |
| Solved | 172 | 185 | 0 | 0 | all | all | 0 | 0 | 8 |

Foundation removal order, verified:

| 172 action | g | Suit | Face-down after | 185 action | g | Suit | Face-down after |
|---:|---:|---|---:|---:|---:|---|---:|
| 91 | 90 | spades | 8 | 74 | 71 | spades | 10 |
| 140 | 139 | diamonds | 3 | 137 | 133 | diamonds | 2 |
| 160 | 158 | clubs | 0 | 168 | 164 | hearts | 2 |
| 170 | 168 | diamonds | 0 | 177 | 173 | diamonds | 1 |
| 171 | 169 | spades | 0 | 182 | 178 | clubs | 0 |
| 172 | 170 | clubs | 0 | 183 | 179 | clubs | 0 |
| 173 | 171 | hearts | 0 | 187 | 183 | hearts | 0 |
| 174 | 172 | hearts | 0 | 189 | 185 | spades | 0 |

The routes share the first action, `move 3 6 1`. The second actions differ: 172 plays `move 3 2 1`, 185 plays `move 6 8 2`. They do not meet again on an exact tableau until the empty solved board, which every complete solution of this deal shares. This is two ancestries, not one line stored at two costs.

**Verified: no exact cycle on either route.** A full scan of column-ordered canonical keys, and a second scan of suit-rank column tuples plus stock and foundations, found no return to an earlier position at a higher `g`. `select_windows` therefore reports no `exact_cycle` window. There is no demonstrated deletion that preserves the rest of the route by identity.

Positive-cost rehandle leaders, by physical deal-order copy:

| 172 card | Positive handles | 185 card | Positive handles |
|---|---:|---|---:|
| 4S#B | 13 | 4S#B | 11 |
| AC#B | 13 | 5S#A | 10 |
| 6S#B, 5S#A, 3S#A, 2S#A | 12 | 3S#A, 2S#B | 10 |

Repeated handling is concentrated on the spade run that both routes rebuild. Repetition is not yet a proved saving, because the scans found no exact loop.

## 3. Backward analysis from the final stock deal

The fifth deal is fixed. Left to right it is:

`3H#B`, `10H#B`, `2D#A`, `3C#A`, `9H#B`, `7C#B`, `7H#B`, `AS#A`, `3C#B`, `5D#A`.

**Verified 172 position immediately before that deal.** One face-down card remains: `AC#A` under `2H#B AH#A` on column 4. No column is empty. Six columns are free-relocatable, meaning the whole face-up column can move onto an empty column at cost 0 once an empty column exists: columns 1, 2, 5, 8, 9, and 10.

| Column | Face-up, bottom to top | Exposed same-suit run | Suit breaks | Free |
|---:|---|---|---:|---|
| 1 | KH#A QH#A JH#A 10H#A 9H#A 8H#B | KH–8H, length 6 | 0 | yes |
| 2 | KH#B QH#B JH#B | KH–JH, length 3 | 0 | yes |
| 3 | 4D#B 3D#A 2C#A AC#B 6H#B 5H#A 4H#B | 6H–4H | 2 | no |
| 4 | 2H#B AH#A, over face-down AC#A | 2H–AH | 0 | no |
| 5 | 2C#B | singleton | 0 | yes |
| 6 | KS#A QS#A JC#A 10C#A AD#B 9C#B 8C#B | 9C–8C | 3 | no |
| 7 | hearts 8H–AH, then KC#B QC#B, then JS#A–2S#B | JS–2S, length 10 | 2 | no |
| 8 | 6C#B 5C#B 4C#B | 6C–4C | 0 | yes |
| 9 | KC#A–4C#A | length 10 | 0 | yes |
| 10 | KD#A QD#B JD#B 10D#B 9D#A 8D#A 7D#B 6D#A | KD–6D, length 8 | 0 | yes |

Landings of SD5 on that board:

| Column | Incoming | Top before the deal | Landing |
|---:|---|---|---|
| 1 | 3H#B | 8H#B | non-connecting, buries KH–8H |
| 2 | 10H#B | JH#B | same suit, extends KH–JH to KH–10H |
| 3 | 2D#A | 4H#B | non-connecting |
| 4 | 3C#A | AH#A | non-connecting |
| 5 | 9H#B | 2C#B | non-connecting |
| 6 | 7C#B | 8C#B | same suit, extends 9C–8C |
| 7 | 7H#B | 2S#B | non-connecting, buries JS–2S |
| 8 | AS#A | 4C#B | non-connecting |
| 9 | 3C#B | 4C#A | same suit, extends KC–4C to KC–3C |
| 10 | 5D#A | 6D#A | same suit, extends KD–6D to KD–5D |

Bonds move from 50 to 54. That is exactly the four same-suit landings.

**Verified 185 position immediately before the same deal.** Face-down cards: `AC#A` and `2H#B` on column 4. Column 9 is empty. No other column is free-relocatable. The longest clean exposed run is a singleton on most columns. Column 7 holds KC#A–4C#A, then five further cards, so the club run is buried. Column 4 has 11 face-up cards and 7 suit boundaries.

SD5 landings on that board: columns 1–8 and 10 are non-connecting. Column 9 is empty, and `3C#B` fills it. Same-suit landings: none. Bonds stay 30.

**Verified consequence.** From those two post-SD5 states the remaining corrected costs are 22 and 51. The stock-empty assembly bound is 18 on the 172 state and 42 on the 185 state. The 172 route's extra 16 moves before the deal buy a tableau whose proved remaining work is 24 moves lower on the assembly bound, and whose actual remaining work is 29 moves lower.

What the 172 route spent the after-SD4 segment on is visible in actions 121–151. It peels column 2, revealing `AH#A`, `JH#A`, `9H#A`, and `5H#A`. It assembles the two heart runs, the KD–6D run on column 10, and the club run already seated on column 9. Action 140 completes the first diamond foundation. Action 142 is the route's second zero-cost transfer (`2C#B` onto the empty column 5). Action 146 reveals `KD#A`. Action 150 reveals `2H#B` and leaves only `AC#A` down. The route then deals. It does not spend a move to expose `AC#A` first.

The 185 after-SD4 segment is actions 128–137, ten moves. It peels `JS#A` off the column SD4 had filled, scatters `AD#A` twice, lays `10C#A 9C#B` onto the club run, and at action 137 completes diamonds by `move 2 9 1`. That removal leaves column 9 empty. Action 138 deals into it. There is no receiver-building interval between the diamond removal and the deal.

**Hypothesis.** The 172 advantage at SD5 is a combination, and the measured parts have different weights.

- Receiving columns are the sharp difference: four same-suit landings against none, on the columns the fixed deal actually uses.
- Suit assembly is the same fact seen as run length: exposed KC–4C on column 9, KD–6D on column 10, KH–JH on column 2, plus a buried JS–2S.
- Exposure differs by one card. That does not explain a 29-move endgame gap.
- Workspace differs in kind. The 172 route reaches SD5 with zero empty columns and six pure free columns. The 185 route reaches SD5 with one empty column and no free column, then gives the empty column to `3C#B`.
- Whole-column transfers are more common on the 185 route and are not the source of its loss. See section 7.
- The costly reconstruction is the 185 endgame. From its own post-SD5 state, at least 42 of the 51 moves are required by the assembly bound. Changing those 51 without changing the tableau is capped by that bound.

**Hypothesis, not a saving.** Two 172 runs are in the wrong columns for this particular deal. `3H#B` lands on `8H#B` and buries KH–8H. `7H#B` lands on `2S#B` and buries JS–2S. A different column for either run would be a different route. The existing endgame still absorbs both burials inside 22 moves.

## 4. Stock-by-stock card dependency maps

Copies are deal-order labels. `#A` is the first copy in the deal file, `#B` the second. A copy on the opening tableau is available at round 0, including while it is face-down. A copy still in the stock is available only after its deal. Because a foundation needs one copy of every rank, the first foundation of a suit is impossible before the latest rank's earlier copy has been dealt. The second foundation waits on the later copy of its latest rank.

**Verified impossibility, from the deal alone.**

| Suit | First foundation cannot be removed before | Because the earlier copy of this rank arrives then | Second foundation cannot be removed before |
|---|---|---|---|
| Spades | SD2 | AS#B on SD2 column 2 | SD5 (AS#A) |
| Hearts | SD2 | QH#B on SD2 column 9 | SD5 (3H#B, 7H#B, 9H#B, 10H#B) |
| Diamonds | SD4 | 2D#B on SD4 column 4 | SD5 (2D#A, 5D#A) |
| Clubs | SD5 | both 3C copies are on SD5 | SD5 (3C#A, 3C#B, and 7C#B) |

Both club foundations are impossible before SD5. A club campaign that tries to remove a club foundation earlier cannot succeed on this deal. Building KC–4C before SD5 is still legal and, on the 172 route, useful, because `3C#B` arrives on column 9. Completing the suit early is the impossible part. The partial run is a preference, and it is a preference about a specific column.

The five deals, column 1 through column 10:

| Deal | Cards |
|---|---|
| SD1 | JS#B, 9D#B, 4D#A, KH#B, 4D#B, 6D#B, 9S#B, 7D#B, 8S#B, 5C#B |
| SD2 | KS#B, AS#B, 6H#B, 7S#B, AD#A, AD#B, AH#B, 10D#B, QH#B, JD#B |
| SD3 | 2C#B, 10S#B, QD#B, KH#A, 8H#B, 9C#B, 3S#B, 5S#B, 5D#B, 4H#B |
| SD4 | 9D#A, JS#A, QH#A, 2D#B, 4C#B, QC#B, KC#B, 8C#B, JH#B, 9S#A |
| SD5 | 3H#B, 10H#B, 2D#A, 3C#A, 9H#B, 7C#B, 7H#B, AS#A, 3C#B, 5D#A |

**Mathematical constraints.**

- Five deals must still be played from the opening. Each costs 1.
- No club foundation exists in any legal state that still has both threes of clubs in the stock.
- The first diamond foundation cannot exist before SD4, because both twos of diamonds are still in the stock until then. The 172 route removes diamonds at action 140, after SD4. The 185 route removes diamonds at action 137, also after SD4.
- The first spade foundation cannot exist before SD2. Both routes remove spades after SD2 (172 at action 91, 185 at action 74).

**Preferences, not constraints.** These are desirable when they are cheap, and harmful when they are pursued instead of a receiver the next deal can use.

- Before SD5, a same-suit top on columns 2, 6, 9, and 10 matches `10H#B`, `7C#B`, `3C#B`, and `5D#A`. The 172 route has all four. The 185 route has none.
- Seating KC–4C on column 9 is the specific preparation that catches `3C#B`. The same run on column 7, which is where the 185 route leaves it, does not catch that card. Column identity is part of the preference.
- An empty column carried into SD5 is filled by `3C#B` unless something else occupies column 9 first. `3C#B` is not a king. The empty column is a poor receiver for it.
- Exposing `AC#A` before SD5 is unnecessary on the verified 172 route. The route deals with that card still down and still finishes in 22 more moves.
- Chasing a club removal before SD5 cannot succeed. Spending a long excavation only to complete clubs early is the harmful version of an otherwise useful club run.

`analyze_stock_backward` in `src/spider/planner/backward_strategy.py` can describe the next row's wishes. It is not called by the whole-game kernel. Section 9 records that split. The map above is an offline reading of the deal and of the two replays. It was not fed back into a search.

## 5. Principal strategic differences between 172 and 185

**Verified.** The routes diverge at action 2 and stay apart. The cost lead changes hands twice in a way that matters.

- Through SD3 the 185 route is cheaper: pre-SD3 is 73 against 100. It has also turned fewer cards (9 face-down remaining against 7) and built fewer bonds (26 against 35).
- Between SD3 and SD4 the 185 route spends 48 against the 172 route's 17. By pre-SD4 it is behind on `g` (122 against 118) and column 4 is the disordered column: at post-SD5 it still holds `AC#A` and `2H#B` down, with 11 face-up cards and 8 suit boundaries. The 172 column 4 at the same moment is `2H#B AH#A` over `AC#A`, plus the newly dealt `3C#A`.
- Between SD4 and SD5 the 172 route spends 30 and the 185 route spends 10. Bonds move 43 to 50 on the 172 route and 39 to 30 on the 185 route. The cheaper segment is the one that disassembles.
- After SD5 the assembly bounds are 18 and 42. The played remainders are 22 and 51.

**Hypothesis.** The 185 route's early saving is less excavation, which the pre-SD1 face-down counts support (18 against 12) and which the v0.105 forensic report also measured. This audit does not treat that opening as the cause of the endgame. The causal claim would need a hybrid route that keeps the cheap opening and still reaches a post-SD5 tableau with a small assembly bound. No such hybrid was constructed here.

**Verified and easy to misuse.** At post-SD5 a policy that ranks by `g` alone prefers 134 over 150. The assembly bound reverses that preference: 176 against 168, and 176 cannot beat 172. A foundation-count policy sees a tie at two foundations. A bond policy and an assembly policy both prefer the 172 state. An empty-column policy prefers the 185 state before the deal (one empty column against zero) and is indifferent after the deal.

The largest located extra costs on the 185 route are the +31 between SD3 and SD4 and the +29 after SD5. The second of those is partly forced: at least 42 moves remain at the moment the segment starts, so the position, not merely the later play, is already expensive. The +31 is the construction of that position. It is a place to look. It is not a list of 31 deletable moves.

Apparent inefficiencies on the 172 route are in section 8. They do not make 172 optimal. They are the places a cheaper complete route would have to differ.

## 6. Empty-column use

**Verified counts.** The 172 route has 32 intervals in which at least one column is empty, and 5 intervals in which two or more are empty at once. Four of those five last two actions: 39–40, 66–67, 72–73, and 140–141. The fifth is actions 160–174, `g` 158 through 172, which is the foundation liquidation. The maximum simultaneous empty count during that liquidation reaches the solved board.

The 185 route has 28 empty intervals and 4 two-empty intervals. Three are two actions long (101–102, 161–162, 163–164). The fourth is actions 181–189, again the liquidation.

**Verified deal behaviour.** Every 172 pre-deal horizon has zero empty columns. The route creates spaces between deals and refills them before the next deal. The 185 route deals twice into an empty column: SD4 fills column 2 with `JS#A`, and SD5 fills column 9 with `3C#B`. Unrestricted MobilityWare rules allow both deals. The empty column is legal. It is also the landing square.

The 185 empty column at pre-SD5 is the residue of action 137, `move 2 9 1`, which removes the diamond foundation on column 9. The space exists for one state. The next action deals. It is not used to expose a card, untangle a mixed column, or consolidate a run.

**Verified latent workspace on the 172 route.** At pre-SD5 the route has no empty column and six free-relocatable pure columns. Those columns are a space that has not been spent. Creating one empty column from them costs 0 once any one of them is moved onto an empty column, but creating the first empty column still needs a king-headed run or a foundation removal, because a non-king block cannot move onto an occupied column and there is no empty column yet. The free columns become zero-cost mobility after the first space appears. In the endgame, after action 160 has produced spaces, the route has 9 to 20 zero-cost legal moves available at the sampled positions (actions 161, 166, 169, and 171). The played moves at 166 and 169 still cost 1, because they move a proper suffix of a longer column rather than a whole free column.

**What two spaces do here.** Outside the final liquidation, two spaces are held for a single intervening move and then collapsed. That is compatible with a short tactical park. It is not a sustained two-space rearrangement strategy, and it is not how the 172 route buys the SD5 tableau. Rewarding the empty-column count would score the 185 pre-SD5 position above the 172 pre-SD5 position. The endgame costs say the opposite.

**Recommendation: workspace utility.** Classify a newly empty column by a bounded legal lookahead, using the existing segment search rather than a new planner.

- Unproductive: the lookahead finds no reveal, no same-suit join that was illegal without the space, no zero-cost relocation onto a column whose next stock card continues the run, and no reduction in the stock-empty assembly bound.
- Productive: one of those consequences is reached inside a short cost cap, and the empty column is allowed to be refilled before the next deal.
- Two-space leverage: the same consequence is illegal, or costs more, when the lookahead is forbidden from using a second empty column.

The score is the consequence. The empty-column count is only the precondition. Stock-deal legality stays with `can_deal`. Carrying an empty column into a deal is legal under `MW_RULES` and, on this deal's fifth row, gives the empty column to a non-king.

## 7. Zero-cost whole-column transfers

A corrected-cost zero move is a transfer of an entire face-up column onto an empty column when the source has no face-down cards. `mw_move_cost` returns 0 for that case and 1 when the source still has a face-down card. Both replays use that rule.

**Verified 172 transfers, two in the whole game.**

| Action | g after | Move | Cards | What it does |
|---:|---:|---|---|---|
| 46 | 45 | `move 9 8 1` | 2S#B | Slides a one-card column from column 9 onto empty column 8. Reveals nothing. Column 9 becomes empty and is refilled before SD1. |
| 142 | 140 | `move 2 5 1` | 2C#B | After the first diamond removal. Slides `2C#B` onto empty column 5. Reveals nothing. Frees column 2, which the later heart assembly uses. |

**Verified 185 transfers, four in the whole game.**

| Action | g after | Move | Cards | What it does |
|---:|---:|---|---|---|
| 30 | 29 | `move 8 3 1` | 2H#A | Rotates the empty column from 3 to 8. |
| 31 | 29 | `move 9 8 4` | 7H#A 6H#A 5H#B 4H#A | Parks a heart run on the new empty column. |
| 32 | 29 | `move 6 9 6` | 7S#A 6S#B 5S#A 4S#B 3S#A 2S#B | Parks a spade run and leaves column 6 empty. |
| 76 | 72 | `move 8 9 8` | KD#B through 6D#B | After the first spade foundation. Relocates an eight-card diamond run onto empty column 9. |

Actions 30–32 are one manoeuvre: three free transfers, no reveal, no new bond, and an empty column that is filled again before SD1. They reorder runs that were already built. The 185 route is 18 moves cheaper than the 172 route at pre-SD1, and three of its opening actions are these free transfers. The free transfers are part of a cheaper opening. They do not prevent the expensive endgame.

**Search treatment, verified from the kernel.** `step_cost` is the corrected cost. A zero-cost child has `child_g == g`. The duplicate rule skips a child when `child_g >= prev` for the same identity, so a second arrival at the same position by a free move is discarded. A free move to a new identity is kept and does not raise `g`. The cost lane, whose key is `(g,)`, therefore treats it as no worse than doing nothing. The unique-state counter still increments. A cloud of reversible free rearrangements can fill `max_unique` without improving the tableau. SPS1, `pack_whole_game_identity` after the stock is empty, collapses column permutations of an exact column encoding. It does not collapse two states that merely look alike. While stock remains, identity is ordered `pack_state`, because the next deal lands on physical columns. That split is the correct one for this deal: the 172 club run is valuable on column 9 and not on column 7.

`strategic_action_order`, used by the strategy variant and not by the default suit search, ranks a same-suit join and a reveal ahead of a move onto an empty column. A free park that is not itself a same-suit join waits behind those. The suit kernel passes `action_order=None` unless an advice function is supplied. Primary suit runs do not reorder actions at all. Lanes reorder states.

No positive-cost move on the 172 route was shown to be replaceable by a free transfer. The park-and-return spans in section 8 move a suffix, not a whole free column, so the zero-cost rule does not apply to them as played.

## 8. Candidate savings in the 172 route

**Demonstrated redundant operations: none.** Both cycle scans are empty. Deleting a contiguous span of the 172 file does not leave a legal cheaper solution by exact identity. The v0.118 anchored run on this same file returned `IMPROVED=false` and rejoins 0, which agrees with the empty cycle list.

**Speculative, and already isolated by the existing anchored screen.** `select_windows` on the current 172 file, with span limit 12, returns six reversal windows. A reversal window contains a move and a later inverse column transfer. The state at the end is not the state at the start, so the inverse pair is repeated handling around some other move, not a proved loop. The v0.118 anchored run on this file exhausted 11 windows with no cheaper rejoin and left five windows inconclusive at 2,500 unique states: reversal spans 20–24, 76–80, 146–149, and 165–168, plus the between-foundation span 160–170 at cost 10. The current screen also contains the opening reversal at actions 1–5 and the span at actions 115–117. v0.118 did not list those two spans among the inconclusive windows.

| Checkpoint span | 1-based actions | Cost | Played moves | Physical cards in the out-and-back | Status |
|---|---|---:|---|---|---|
| 20–24 | 21–24 | 4 | `move 4 8 1`, `move 4 10 1`, `move 8 10 1`, `move 8 4 1` | a card from column 4 travels via column 8 and returns | inconclusive in v0.118 |
| 76–80 | 77–80 | 4 | `move 6 1 2`, `move 6 5 1`, `move 5 6 2`, `move 1 6 2` | a two-card block leaves column 6 and returns | inconclusive in v0.118 |
| 114–117 | 115–117 | 3 | `move 1 10 1`, `move 9 1 3`, `move 10 1 1` | one card leaves column 1 for column 10 and returns | on the current screen; v0.118 did not list it as inconclusive |
| 146–149 | 147–149 | 3 | `move 3 10 2`, `move 3 4 7`, `move 10 3 2` | `5H#A 4H#B` park on column 10 while `QD#B`–`10D#B` and the cards under them move from column 3 to column 4 | inconclusive in v0.118 |
| 165–168 | 166–168 | 3 | `move 6 8 9`, `move 6 3 1`, `move 8 6 9` | a 9-card suffix of column 6 parks on empty column 8 and returns, around `move 6 3 1` | inconclusive in v0.118 |
| 160–170 | 161–170 | 10 | endgame, from the club removal toward the second diamond removal | several runs, including the moves above | inconclusive in v0.118 |

At action 147 the route has an empty column 10, five zero-cost legal moves, and 38 legal actions. The played move ranks 20th under `strategic_action_order`. At action 166 there are three empty columns and 15 zero-cost moves. The played `move 6 8 9` ranks 11th of 165. Those ranks are a mismatch with a myopic same-suit-first order. They are not evidence that the human action is waste.

**Speculative endgame slack.** At post-SD5 on the 172 route the assembly bound is 18 and the played remainder is 22. Any cheaper completion of that exact tableau saves at most 4. During the final foundation streak the assembly bound sits within 0 or 1 of the true remainder, so the last few foundation triggers are already tight. A saving, if one exists, is in the geometry before that streak, which is what spans 160–170 and 165–168 cover.

**Speculative column placement, not a local window.** Avoiding the SD5 burial of KH–8H by `3H#B`, and of JS–2S by `7H#B`, would require those runs to sit on different columns before action 152. That is a different ancestor, not a deletion. The heavy spade handles (`4S#B` thirteen times, and the neighbouring spade copies twelve times) live in that rebuilt run. They are a place a non-exact repair might look. They are not a demonstrated redundancy.

**Not a candidate.** Replacing the 172 opening with the 185 opening saves 18 on that prefix and does not preserve the 172 suffix. Replacing the 172 after-SD4 segment with the 185 segment saves 20 on that segment and produces the post-SD5 state whose assembly bound is 42. Those are verified cost differences. They are not improvements.

## 9. Backward-planning code and live integration

**Verified locations.**

| Piece | Location | What it computes |
|---|---|---|
| Next row | `planner/stock_reception.py`, `next_stock_row` | The exact ten cards about to be dealt, in column order |
| Stock wishes | `planner/backward_strategy.py`, `analyze_stock_backward` | Landing class, desired top, fill-then-deal versus carry-empty |
| Buried prerequisites | `analyze_buried_cards`, `analyze_backward` | Face-down cards and the rank that would free them |
| Campaign use | `planner/foundation_campaign.py` around the `analyze_stock_backward` call | Stock wishes inside a foundation campaign |
| Controller context | `human_strategy/context.py`, `evaluation.py` | Records the next row, bury risk, and `admissible_remaining` |
| Controller catalogue | `human_strategy/registry.py` | Thirty principles, each with a named test |

`analyze_backward` is reached from campaign and diagnostic code. The Human Strategy Controller's foundation-direction loader imports the workspace-probe context from `backward_strategy.py`. The default whole-game kernel does not import `backward_strategy`, `next_stock_row`, or the controller.

`search_suit_ordered` builds legal actions with `all_legal_actions`, orders states with `suit_lane_keys`, and prunes only when optimise mode supplies `admissible_remaining`. Cold mode, which is the variant used for the published 40-second, 80,000-state, seed-126, and g139 runs, sets the lower-bound function to `None`.

**Verified consequence.** Backward planning can describe a position. On the path that recent whole-game experiments execute, it does not change which child is generated, which child is pruned, or which child is popped first. A wish such as "put a 4C on column 9 before SD5" is absent from `lane_keys` and from `suit_lane_keys`.

The controller path is a different program. Its tests show individual principles changing a fixture decision. Those tests are not the whole-game kernel. Section 21 records each principle.

## 10. Audit of pruning and progressive-search mechanisms

The live whole-game path in this audit is `run_search` as called from `search_suit_ordered`, `search_whole_game` / `search_original_kernel`, and `search_strategy_guided`. The Human Strategy Controller is recorded where it owns a mechanism the kernel does not use.

| Mechanism | Exists | Active on the live kernel path | Safe | Eliminates | Defers | Cost | Evidence |
|---|---|---|---|---|---|---|---|
| Incumbent branch-and-bound | `human_strategy/incumbent.py` `proof_prune`; kernel `proof_dead` when `lower_bound_fn` and `ceiling` are set | Optimise mode only. Cold mode refuses `incumbent_cost` | Yes, when `h` is admissible and the ceiling is `incumbent - 1`. Kernel uses `g + h > ceiling` | States that cannot beat the verified complete cost | Nothing. The prune is permanent | One bound evaluation per generated child that survives the hard cap | Unit tests in `test_human_strategy_v0_107.py` and `test_global_search_v0_126.py`. Not engaged by the cold 80,000-state runs |
| Admissible remainder | `evaluation.py` `admissible_remaining`; `planner/lower_bounds.py`; `assembly_lower_bound.py` | Same switch as the incumbent prune. Cold passes `None` | The deal-and-reveal bound is argued in the lower-bounds module. Assembly is argued only for an empty stock. This audit checked both complete routes: neither bound exceeded the true remainder at any prefix | Little, until `g` is high or the stock is empty. See section 11 | Nothing | Cheap arithmetic | Route check in this audit. g139 check already in the v0.126 report: `h = 20`, `139 + 20 = 159`, which does not prune against 172 |
| Exact-state transposition | `search_kernel.py`: skip when `child_g >= prev` for `pack_whole_game_identity` | Yes | Yes for exact identity. A worse or equal `g` is dominated | Duplicate arrivals | A strictly cheaper arrival replaces the stored `g` | Hash map | Kernel counters `duplicate_skips`. g139 continuation recorded 311,122 duplicate skips |
| Symmetry | `packed_state.py` `pack_whole_game_identity` | Yes. Ordered identity while stock remains. SPS1 column permutation only after the stock is empty | Yes. The function refuses SPS1 while stock remains | Column permutations of an otherwise identical stock-empty state | Nothing | Sort of ten column blobs | v0.126 tests keep the seven lanes and the identity split. Anchored rejoin deliberately does not use SPS1, because a suffix names columns |
| Proven move dominance | No general move-dominance proof beyond the identity rule | No | — | — | — | — | Not found as a separate live pass |
| Progressive tactical budgets | `human_strategy/search_budget.py` ladder 160 / 800 / 4,500 nodes | Controller only | The ladder is a resource limit, not a proof | Stops a probe | The next rung can retry | Wall clock and node caps | v0.120 tests. The unresolved `PLANNING_STALL` / `TIME_LIMIT` failure is in this family of live solves |
| Deferred alternatives | Controller dormant objectives | Controller only. The kernel keeps every non-dominated child on the lane heaps | Dormant ids are heuristic memory | A failed objective is skipped on that exact state | The rest of the heap remains | Small | `test_failed_objective_backtracks_then_widens` |
| Beam width | `macro.py` beam settings | Not on the v0.124–v0.126 kernel path | Historical | Would drop unselected states | Depends on the old macro | — | Not the live path |
| Frontier scheduling | Kernel round-robin over the seven lane heaps | Yes | Ordering is not a proof. A state stays until it is popped or a cap hits | Nothing by rank | All lanes share the frontier. There is no later widen step | One pop per turn | `search_kernel.py` lane cycle. v0.126 g139 continuation popped each of the seven lanes 42,600 times |
| Whole-game lanes | `whole_game_anytime.py` `lane_keys` | Yes | Order only | Nothing | The other six lanes | Negligible | Keys quoted in section 14 |
| Backward planning | Section 9 | No on this path | Wishes are not admissible | Nothing in the kernel | Nothing in the kernel | The campaign probe can be expensive when the controller runs it | No call from `global_search_experiment.py` |
| Suit-completion order | `suit_lane_keys` replaces the foundation key's second component with proximity | Yes, as the experimental default | Order only. Source comments and tests forbid passing the score to `lower_bound_fn` | Nothing | Other lanes still run | One tableau scan per popped state | v0.125 and v0.126 tests. On seed 126 it lengthened runs and removed no foundation |
| Stock-deal legality | `engine.py` `can_deal` | Yes, inside `enumerate_legal_actions` | Yes. It implements the chosen rules | Illegal deals | Legal deals stay, including deals into empty columns under `MW_RULES` | Trivial | Both solutions replay, including 185's deals into empty columns |
| Anchored optimisation | `human_strategy/anchored.py` | Only when a caller passes a verified route. Cold search raises `AnchoredRefused` if asked | Exact column-ordered rejoin, then a full-game replay before any route is accepted | Segment searches whose lower bound already meets the segment cost | Inconclusive windows stay inconclusive | Default 2,500 states and a few seconds per window | v0.118: 172 file, no improvement, five windows inconclusive. v0.126 short run still returns 172 |
| Continuation / suffix repair | `search_suit_ordered(..., prefix_actions=...)` | Yes, as an explicit prefix | The prefix is replayed. Provenance is `checkpoint_continuation` or `checkpoint_assisted_complete` | Does not repair an arbitrary suffix | The suffix search is a fresh kernel from that state | The g139 component exhausted at 41,472 states | v0.126. The g139 prefix is a closed partial. `verify_complete_solution` rejects it |

**Why the published whole-game runs used ceiling 300.** `HARD_COST_CEILING = 300` in `global_search_experiment.py`. `search_original_kernel` documents it as a hard path cap. `search_suit_ordered` in cold mode stores that integer and passes it to `run_search` with `lower_bound_fn=None`. Children with `g > 300` are skipped. `proof_dead` returns false immediately because the bound function is missing. The 172 incumbent is refused in cold mode so that a cold result cannot be confused with an imported solution.

`search_strategy_guided` records the same 300 on the result object in cold mode, then assigns `ceiling = None` when `incumbent_cost` is `None` immediately before `run_search`. The kernel on that cold strategy path therefore has no cost ceiling at all. The recorded 300 is not the ceiling the kernel enforced. This audit does not change that function.

Optimise mode on both suit and strategy paths sets the kernel ceiling to `incumbent - 1` and supplies `admissible_remaining`. That path was not the path used for the cold 80,000-state experiments. A short anchored optimisation of the 172 file still reports 172.

## 11. Assessment of the current admissible lower bound

`admissible_remaining` is `compute_solution_lower_bound.h_admissible`, and, when no stock row remains, the maximum of that value and `stock_empty_assembly_h`.

The deal-and-reveal term is:

```text
h = remaining_deals + ceil(max(0, face_down - 10 * remaining_deals) / 2)
```

The proof notes in `planner/lower_bounds.py` are the right shape. A free move cannot reveal. One paid tableau move can flip at most two cards, on two different columns. One deal can flip at most one card on each of ten columns. Summing face-down count and deals would double-count and is correctly marked inadmissible.

**Verified against both solutions.** At every prefix, this deal-and-reveal `h` was less than or equal to the true remaining corrected cost. Its slack falls to 1 only on the final action, where the term is 0 and one paid foundation move remains. The assembly term at those same final positions equals the true remainder, so the combined slack is 0 there. Through every stock horizon the slack stays large. Examples from the 172 route:

| Horizon | g | True remainder | Base h | Assembly h | g + combined h | Prune against 172 |
|---|---:|---:|---:|---:|---:|---|
| Opening | 0 | 172 | 5 | 0 | 5 | no |
| Pre-SD1 | 50 | 122 | 5 | 0 | 55 | no |
| Pre-SD5 | 149 | 23 | 1 | 0 | 150 | no |
| Post-SD5 | 150 | 22 | 1 | 18 | 168 | no |
| g139 closed partial | 139 | no solution in that component | 4 | 20 | 159 | no |

The 185 post-SD5 line is the informative one: `g = 134`, assembly `h = 42`, `g + h = 176`. `proof_prune(134, 42, 172)` is true. The current bound can reject that verified-expensive tableau. It cannot reject the opening, and it cannot reject the 172 post-SD5 tableau.

The bound is admissible on the evidence of these two suffixes. It is too weak to remove the unproductive opening. That weakness is structural: five deals and fifty possible deal-triggered flips cover the opening's 44 face-down cards, so the reveal term is zero and `h` stays at 5 until deals have been spent and a deep column remains.

## 12. Opportunities for stronger safe pruning

**Checked, and not a sum.** A column with `d` face-down cards needs `d` separate flips. One action flips a given column at most once. Each remaining deal can account for at most one of those flips. So a second admissible figure is `remaining_deals + max(0, deepest_column_face_down - remaining_deals)`. It overlaps the existing reveal term. The safe combination is the maximum, not the sum.

On every prefix of both routes, that maximum, also taking the stock-empty assembly bound when the stock is empty, stayed at or below the true remainder. On these routes it only lifts the stock-phase bound by about one move (post-SD1 on the 172 route: base 4, column figure 5). It does not move the opening prune threshold in a way that would shrink the search against a 172 ceiling. It is a safe tightening for positions that bury one deep column while the other columns are already open. It is a poor bet as the next experiment on this deal.

**Do not add, without a disjointness proof.**

- A join per broken suit, on top of the reveal term. The same paid move can reveal and join.
- One move per remaining foundation, on top of the assembly bound. The assembly proof already uses `max(m, u - m)` so that the completing join is not counted twice, and it is valid when the stock is empty because a deal is no longer able to attach ten cards at once.
- The assembly bound while stock remains. One deal can create up to ten joins. The stock-empty proof does not survive that action.
- Face-down count, empty-column count, bond deficit, or suit proximity. All of those can overestimate.

**Safe constraints that are not extra cost.** Section 4's suit gates can order objectives. They add no integer to `h`, because the necessary deals are already counted. Using them as a permanent cost penalty would be inadmissible.

Any stronger numeric bound still needs the check this audit ran for the column figure: every prefix of both complete routes, plus a small exhaustive fixture, before it is allowed to prune.

## 13. Proposed whole-game progressive widening

**Recommendation.** The kernel already generates every legal child, already drops exact dominated identities, and already keeps the survivors on heaps. What it does not have is a widening schedule. Round-robin explores all seven obsessions at once until `max_unique` or the clock stops. A stopped run discards the unpopped heap. The next run starts over, unless a caller passes one prefix, as v0.126 did for a single checkpoint.

A modest schedule on top of the same kernel, for incumbent-guided search only:

1. Generate the legal children. Do not drop any before the proof checks.
2. Apply the hard ceiling `incumbent - 1` and `proof_dead` with `admissible_remaining`.
3. Apply exact-identity dominance, including SPS1 only when the stock is empty.
4. Rank the survivors with the balanced key in section 14. Pop a small primary quota from that ranking.
5. Leave the other survivors on the existing heaps. Do not delete them because their rank is poor.
6. When the primary quota produces no complete route, increase the quota and continue popping the same heaps.
7. Keep `best_g`, the node table, and the heaps across quota increases. A wider pass is the same search.
8. Stop when a complete replay beats 172, or when the unique-state and time budgets are spent. A budget stop is inconclusive.

Cold search should keep refusing an imported action sequence. If a cold run is given the numeric ceiling 171, the report must label the run incumbent-guided. The v0.126 provenance labels already exist for that distinction.

The g139 component is the example of work that should be abandoned for a proved reason: the component is closed, face-down count cannot fall, and no empty column can be created. That is a property of the component, not a reason to add another ordering key. The report key `_better_partial` still prefers more foundations, so it exported that closed line even though the same cold run had seen a three-foundation state with fewer face-down cards. A widening schedule does not fix a report key that selects a closed component as the continuation seed.

## 14. Proposed balanced strategic evaluation

**Verified imbalance in the current keys.** Lower tuples are popped first.

| Lane | Key | What it chases |
|---|---|---|
| cost | `(g,)` | Lowest corrected cost, including free moves |
| foundation | `(-foundations, face_down, stock_rows, g)` plus proximity on the suit path | More foundations, then the proximity score |
| reveal | `(face_down, -foundations, -empty, g)` | Fewer face-down cards, then more empty columns |
| workspace | `(-empty, face_down, -compression, g)` | More empty columns first |
| construction | `(-bonds, -longest, -merges, face_down, g)` | More bonds and longer runs |
| prep | `(-stock_rows, face_down, -bonds, -empty, g)` | Keeping stock undealt |
| epoch | `(stock_rows, -foundations, face_down, g)` | Dealing the stock sooner |

`strategy_features` adds `face_down - 20 * foundations`, then minus bonds, minus longest run, minus empty columns, plus stock rows. The coefficient 20 lets one foundation outrank twenty face-down cards. The workspace lane lets one empty column outrank any bond difference. Prep and epoch pull the stock in opposite directions and each gets one pop in seven.

The known solutions are counterexamples to each single chase.

- More empty columns: 185 pre-SD5 has one, 172 has zero, and 172 is the cheaper finish.
- More foundations earlier: both routes hold one foundation for a long time. The g139 partial has four and cannot reach a fifth.
- Longer runs: seed 126's suit order built a run of length 10 and removed no foundation.
- Lower `g`: 185 is ahead at post-SD5 and behind at the end.
- Dealing immediately: the 172 route spends 30 moves after SD4 before it is willing to deal, and that delay is the cheap finish.

**Recommendation.** Rank a state by a small vector of incomparable evidence, and break ties by rotating which component is primary, instead of scaling one component by a constant. The components that the two solutions actually separate are:

- corrected `g`;
- `admissible_remaining`, as a display of proved work, not as a second copy of something already in the prune;
- stock-empty assembly bound once the stock is empty, which separates 18 from 42 at the fifth deal;
- number of same-suit landings the next fixed stock row would make;
- whether a one-ply or two-ply lookahead from a new empty column reveals a card or reduces that assembly bound.

A plan that uses two spaces to expose a card and to seat KC–4C on column 9 before SD5 outranks a plan that only lengthens a run on column 7. The landing count is the evidence. It is an ordering feature. It becomes a prune only where section 4 gives an impossibility, and even then the prune is "this foundation cannot exist yet", not a fake extra move cost.

Do not fit the weights on these two routes and then quote the same routes as confirmation. The routes are the calibration set. A later check belongs on another seed, or on a held-out window of this deal that was not used to choose the key.

## 15. How the incumbent should guide optimisation

The 172 route is a verified ceiling and a source of checkpoints. It is not a script the search must replay.

**Already implemented, and the right first tool.** `optimise_anchored` replays the route, builds column-ordered checkpoints, and searches a segment only for a path that returns to a later checkpoint at a strictly lower corrected cost. A splice is kept only when the whole game replays. Cold mode cannot call it. SPS1 is not used, so a suffix that names column 9 is not attached to a state where that run sits on column 7. v0.118 and the short v0.126 check both left the file at 172. The unfinished windows are section 8.

Exact rejoin cannot represent the improvement this audit thinks is most plausible: a different seating of the same runs before SD5, followed by a different endgame that is still cheap. The post-SD5 states of the two routes are not the same state. A search that demands the 172 post-SD5 tableau can save at most the 4 moves of assembly slack. A search that demands an earlier checkpoint can save only a local detour.

**Recommendation, without building it here.** Keep the anchored contract and widen the target, not the heuristic.

- Local simplification and redundant-handling removal are the reversal windows. Exact rejoin is enough.
- Commutation of independent moves is the same mechanism when the transposed span returns to the same checkpoint.
- A bounded deviation may leave the intermediate tableaux and must hit a later checkpoint whose suffix is then replayed, not assumed. The natural targets are the pre-SD5 checkpoint and the post-SD5 checkpoint of the 172 route. If the search arrives at a different post-SD5 state, the stored suffix is discarded and the segment has to finish the game itself, under ceiling 171.
- Re-optimisation between stock boundaries is that same idea with the five deal horizons as the checkpoint set.
- Repair of a known suffix after an altered prefix is legal only when `states_rejoin` says the prefix ended on the suffix's required state.

Provenance stays split. An incumbent-guided splice that replays at 171 is an improved imported solution. It is not an independent cold complete. A cold run that is handed the 172 action list, or a prefix taken from it, gets the checkpoint-assisted label the v0.126 code already uses.

## 16. Components that can be reused unchanged

- `engine.py`, `rules.py`, and `MW_RULES`, including deal-into-empty legality and corrected zero-cost transfers.
- `replay_actions_detailed` and `verify_complete_solution`.
- `admissible_remaining`, `compute_solution_lower_bound`, and `stock_empty_assembly_h`, as a maximum, with assembly applied only on an empty stock.
- `proof_prune` and the kernel's `proof_dead` inequality.
- `pack_state`, `pack_whole_game_identity`, and the refusal of column symmetry while stock remains.
- `run_search`, the seven `lane_keys`, and `suit_lane_keys` as order-only signals.
- `optimise_anchored`, `select_windows`, `search_segment`, and the full-game replay gate.
- The provenance labels from v0.125 and v0.126.
- The two solution files, as immutable inputs.
- The Human Strategy Controller's tests and principle catalogue, as a specification of intended behaviour. Reuse does not mean calling the controller from the kernel in the next patch.

## 17. Components that appear redundant or counterproductive

- The workspace lane's primary key, `-empty`, and the `-empty_count` term in `strategy_features`. On this deal they prefer the tableau that deals a space away and then spends 51 moves.
- The foundation-first report key `_better_partial`. It selected the closed g139 line as the continuation seed while a three-foundation state in the same run had fewer face-down cards.
- Cold `search_strategy_guided` recording ceiling 300 and then passing `None` into `run_search`. Operators cannot see the ceiling the kernel used.
- Running the published whole-game searches at ceiling 300 in cold mode when the question is whether a complete route can beat 172. The cap does not encode the question. The runs remain valid as cold partials.
- A second copy of backward planning inside a new subsystem. `analyze_stock_backward` already exists and is unwired. Wiring a wish in as a prune would be the harmful move.
- Treating the 185 file as evidence that the autonomous solver discovered a cold optimum. The file is a verified replay. The discovery claim is not established.
- Adding another suit-ordering key to open the g139 component. v0.126 showed the component is closed under the rules.

The seven lanes should not be deleted as part of the next experiment. They are order-only and tested. The empty-column primary key should stop being the workspace objective when a balanced key is introduced. That is a later change, not this audit.

## 18. Ranked recommendations

| Rank | Change | Expected benefit | Complexity | Risk |
|---|---|---|---|---|
| 1 | Re-search the inconclusive 172 anchored windows at a higher unique cap. Section 19. | Direct. A hit splices into a replayable game under 172. A miss retires those windows. | One existing call, larger caps | Low. The accept gate is already a full replay |
| 2 | Point the same segment search at the 172 pre-SD5 and post-SD5 checkpoints, and require the search to finish the game if it misses the exact tableau | Can see a different SD5 seating, which is where the 13-move gap lives | Small extension of target selection inside `anchored.py` | Medium. A missed rejoin must not keep the old suffix |
| 3 | Use optimise mode, ceiling `171`, and `admissible_remaining` for any whole-game run whose question is "beat 172" | Cuts states with `g + h >= 172`. Immediately rejects tableaux like the 185 post-SD5 state | Configuration of the existing mode | Low for correctness. Small early-search reduction, because `h` stays near 5 |
| 4 | Add the deepest-column reveal figure as `max`, not a sum, after it passes the same suffix check on a fixture | Slightly stronger on deep single columns | A few lines in the lower-bound function | Low if the max rule is kept. High if someone sums it |
| 5 | Order the foundation lane by suits that are still possible before the next deal, using section 4 | Stops a club-completion chase before SD5 from outranking a spade or heart line | Small ordering change | Medium if it is mistaken for a cost prune |
| 6 | Replace `-empty` with the lookahead utility in section 6 | Stops the search from hoarding spaces the next deal will fill | Needs a bounded probe | Medium. Easy to over-reward spaces again |
| 7 | Progressive quotas on the existing heaps, section 13 | Stops each widen from discarding finished transposition work | Scheduling change in the kernel loop | Medium. Easy to restart by accident |
| 8 | Another global heuristic, an eighth lane, or a new backward planner | Unlikely, until 1–3 have been measured | High | High. Repeats the pattern this reset is trying to leave |

## 19. One minimal next implementation experiment

**Do not implement it in v0.127.**

Use `search_segment` on the verified 172 route. Do not write a new searcher. Targets, in order:

1. Checkpoint span 165–168, played cost 3. Actions 166–168. The 9-card park onto column 8 and its return.
2. Checkpoint span 146–149, played cost 3. Actions 147–149. The `5H#A 4H#B` park around the diamond-run transfer.
3. Checkpoint spans 20–24 and 76–80, played cost 4.
4. Checkpoint span 160–170, played cost 10, only if the shorter spans produce no splice.

Caps, fixed in advance: one worker, 20,000 unique states, 30 seconds, 3,072 MB, segment ceiling equal to the played segment cost minus one. Zero-cost transfers stay legal because `search_segment` already sorts by `step_cost`. Identity stays `pack_state` plus `canonical_state_key`, which is what the anchored search already uses.

Acceptance: `states_rejoin` at the segment's end checkpoint, then `verify_complete_solution` on the spliced full action list, corrected cost less than or equal to 171, eight foundations. Anything short of that, including a cheaper segment that fails the full replay, is not an improvement. An exhausted segment is a negative result inside that ceiling. A unique-state or time stop is inconclusive.

Record the run as incumbent-guided. Do not label it `independent_cold_complete`.

This experiment is aimed at a verified complete game. The v0.118 pilots already showed that several neighbouring windows have no cheaper exact rejoin. These five are the ones that stopped at 2,500 states while containing the only repeated card motions the cycle scan could not dismiss. If they also exhaust, the honest next step is recommendation 2, a stock-boundary target, and not another ordering feature.

## 20. Reproduction commands and final Git status

Headline totals, from the repository root. The command is one PowerShell here-string so the quotes survive:

```text
@'
import sys
from pathlib import Path
sys.path.insert(0, "src")
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions_detailed
cards = load_deal(Path("deals/4925153.txt"))
pairs = [
    ("172", "solutions/4925153_canonical.moves"),
    ("185", "solutions/4925153_autonomous_185.moves"),
]
for label, path in pairs:
    state = SpiderState.from_cards(list(cards))
    print(label, replay_actions_detailed(state, parse_moves_file(Path(path))))
'@ | Set-Content -Encoding utf8 $env:TEMP\v0127_totals.py
py -3 $env:TEMP\v0127_totals.py
```

The stock horizons, assembly figures, cycle scan, and reversal windows in this report were measured by a temporary replay script that called `replay_actions_detailed`, `step_cost`, `stock_empty_assembly_h`, `compute_solution_lower_bound`, `build_checkpoints`, and `select_windows`. The script was deleted after the numbers were written down. The existing structural comparison remains available:

```text
py -3 tools/solution_forensics.py --deal deals/4925153.txt --a solutions/4925153_canonical.moves --b solutions/4925153_autonomous_185.moves --label-a human-172 --label-b machine-185 --expect-a 172 --expect-b 185 --out artifacts/forensics/v0127_check.json
```

`artifacts/` is gitignored. That command was not required for the numbers above. The v0.105 report at `docs/solution_forensics_4925153_172_vs_185_v0_105.md` is the earlier structural comparison. This audit recomputed the segment costs and the pre-SD5 gap rather than copying that report's tables.

v0.126 reproduction, not rerun here, remains the continuation command in `docs/state_first_completion_v0_126.md`. The full regression was not rerun. Its recorded result is 550 passed and 1 failed.

Final Git status after this report was written:

```text
## local/search-optimisation-audit-v0-127
?? docs/whole_game_optimisation_audit_v0_127.md
```

HEAD is `1a6a8fc59b964725ced4b8c678a0b117b7641202`. `git diff --stat` is empty. No commit, merge, or push was made.

## 21. Original strategy traceability

The catalogue is `PRINCIPLES` in `src/spider/human_strategy/registry.py`. This audit did not invent further principles. Each named test below is present in `tests/test_human_strategy_v0_107.py`. Those tests drive the Human Strategy Controller on fixtures. They were among the passing tests of the v0.126 suite. They were not rerun here.

The status column is about the live whole-game kernel, not about the existence of the controller. "Disconnected" means the controller implements the principle and the kernel path in section 10 does not execute that code.

| ID | Principle | Kernel status | Where the behaviour actually is |
|---|---|---|---|
| 1 | Optimise final completion cost rather than immediate attractiveness | Disconnected | Controller rank key. Test `test_completion_cost_beats_a_free_relocate`. The kernel cost lane ranks `g` only |
| 2 | Analyse the full known deal, including hidden cards and future stock | Disconnected | `StrategicContext` and `next_stock_row`. Test `test_known_hidden_card_is_not_accessible`. The kernel sees the cards because they are in the state. It does not score the next row |
| 3 | Work backwards from future completion requirements | Disconnected | Controller prerequisite note. Test `test_backward_prerequisite_is_exposed_first`. `analyze_backward` is on the campaign path, not the kernel |
| 4 | Reason using strategic objectives rather than isolated moves | Disconnected | Controller objective ids. Test `test_legal_move_that_misses_its_purpose_is_not_success` |
| 5 | Restrict serious consideration to a small number of promising avenues | Disconnected | Controller `strategic_width`. Test `test_width_limits_the_considered_set`. The kernel generates every legal action |
| 6 | Pursue a principal line before progressively widening | Disconnected | Controller dormant stack. Test `test_failed_objective_backtracks_then_widens`. The kernel round-robin has no widen step |
| 7 | Explore unconventional moves deliberately when justified | Disconnected | Controller prefers a revealing mixed peel. Test `test_revealing_mixed_move_beats_a_cosmetic_join`. `strategic_action_order` ranks same-suit ahead of reveal, and the suit kernel does not use that order unless advice is supplied |
| 8 | Reassess strategy after major structural changes | Partially implemented | The kernel scores each child from the child state. The controller's replan event is a separate mechanism. Test `test_foundation_removal_replans` |
| 9 | Prefer productive same-suit construction | Partially implemented | Construction lane ranks bonds. Same-suit action preference exists only in `strategic_action_order`. Test `test_same_suit_join_beats_a_dead_park` |
| 10 | Preserve valuable existing runs | Disconnected | Controller split penalty. Test `test_controller_does_not_split_a_built_run`. Bond totals react after a split. They do not forbid it |
| 11 | Identify realistically removable suits | Partially implemented | Suit proximity orders the foundation lane and ignores the section 4 gates. The controller marks this principle conditional: the default goal does not call `rank_ready_suits`. Test `test_longer_run_is_extended_first` |
| 12 | Pursue economical early foundations | Partially implemented | Foundation lane and `_better_partial` prefer more foundations. That preference exported the closed g139 line. Test `test_completion_cost_beats_a_free_relocate` |
| 13 | Distinguish theoretical availability from practical accessibility | Partially implemented | The engine only moves a legal same-suit suffix. CardFact accessibility is controller-side. Test `test_duplicate_physical_cards_stay_distinct` |
| 14 | Preserve useful incomplete suit structures | Disconnected | Same controller penalty as principle 10. Test `test_controller_does_not_split_a_built_run` |
| 15 | Replan after each foundation removal | Partially implemented | Same state-based rescoring as principle 8. Test `test_foundation_removal_replans` |
| 16 | Treat kings as contextual logistical problems | Disconnected | Controller king penalty. Test `test_king_move_depends_on_what_it_frees` |
| 17 | Treat empty columns as tools, not trophies | Partially implemented | The controller test `test_empty_column_is_spent_to_reveal` spends a space to reveal. The live workspace lane ranks `-empty` first, which is the trophy signal |
| 18 | Spend workspace when recoverability justifies it | Disconnected | Controller `exit_route_bounded`. Test `test_same_suit_join_beats_a_dead_park` |
| 19 | Evaluate workspace acquisition efficiency | Disconnected | Controller one-ply reveal preference. Test `test_empty_column_is_spent_to_reveal` |
| 20 | Account for deferred parking and rehandling without calling it admissible | Partially implemented | `admissible_remaining` ignores rehandling in both programs. Cold kernel search does not consult it. Test `test_rehandling_does_not_become_an_admissible_bound` |
| 21 | Prefer recoverable or self-liquidating parks | Disconnected | Controller park class. Test `test_same_suit_join_beats_a_dead_park` |
| 22 | Exploit strategically useful zero-cost whole-column transfers | Partially implemented | Corrected cost 0 is active in the engine and the kernel. The suit kernel does not select them on purpose. Anchored segment search tries cost 0 first. Test `test_zero_cost_transfer_is_taken_when_it_improves_the_landing` |
| 23 | Distinguish productive temporary disorder from harmful structural debt | Disconnected | Controller reveal-versus-dead-park split. Test `test_revealing_mixed_move_beats_a_cosmetic_join` |
| 24 | Choose stock-deal timing strategically | Partially implemented | Prep and epoch lanes pull in opposite directions and do not look at the incoming row. Controller test `test_costly_preparation_beats_immediate_deal` |
| 25 | Prepare for exact incoming stock cards | Disconnected | `next_stock_row` in the controller. Test `test_costly_preparation_beats_immediate_deal`. No kernel call |
| 26 | Execute preparatory actions at their economically appropriate moment | Disconnected | Controller bundles a bury-saving move with the following deal. Test `test_costly_preparation_beats_immediate_deal` |
| 27 | Exploit future stock arrivals to release temporary structures | Disconnected | Controller deal preference when a landing already matches. Test `test_immediate_deal_beats_wasteful_preparation` |
| 28 | Search alternative early strategic ancestries | Partially implemented | Kernel transposition keeps the cheaper `g`. It does not undo a deal to try a saved preparation. Controller test `test_failed_objective_backtracks_then_widens` |
| 29 | Learn from completed routes, deviations, and backward attribution | Partially implemented | The registry text says completed-route forensics are not loaded into the controller. Anchored mode loads a route only when asked. Cold mode refuses it. Test `test_failed_objective_is_not_retried_on_the_same_state` |
| 30 | Use verified incumbents, admissible bounds, and selective widening | Partially implemented | Optimise mode prunes with `g + admissible_remaining`. Cold mode refuses the incumbent. Width growth is controller-only. Recent whole-game runs used cold ceiling 300. Test `test_warm_ceiling_prunes_and_cold_mode_refuses_injection` |

No principle in this table is both implemented and demonstrably active inside `search_suit_ordered` as that function is called on a cold whole-game run. The pieces that are partially active are cost, legality, transposition, foundation-count ordering, bond ordering, empty-column ordering, and suit proximity. Empty-column ordering is active in the direction the principle warns against.
