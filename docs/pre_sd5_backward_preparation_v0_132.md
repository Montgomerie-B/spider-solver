# Pre-SD5 backward preparation v0.132

Schema `spider-pre-sd5-backward-preparation-0.132`. Deal `4925153`. Branch `local/pre-sd5-backward-preparation-v0-132`, started from v0.131 `8cc1e59c9674806ce880127db1c51a3d1bd0507c`.

Two changes only. `locate_all_cards` now gives each future stock card the column `SpiderState.deal` will use. A bounded tableau search then asks whether a different pre-SD5 shape, scored by dealing the known next row, improves the verified post-deal remainder. This is not a new whole-game solver. The post-SD5 search budgets from v0.130 and v0.131 were not increased, and no suffix repair or complete continuation was started.

## Result

The reversed stock-column mapping was real, and the locator now matches the engine on every full chunk of 50, 40, 30, 20, and 10 cards. The three-move neighborhood of the canonical pre-deal tableau was exhausted. Its best immediate-deal bound stayed 168, the same `150 + 18` already known after SD5. One move inside that neighborhood creates a fifth same-suit landing, at corrected cost 150 rather than 149, and the post-deal remainder stays 18.

The search from the checkpoint after the first diamond foundation filled 20,000 identities without reconstructing the canonical pre-deal tableau. That probe is inconclusive. Samples that deal earlier show a post-deal total of 166 only because they have spent less; their remainder is 24, not 18. No solved route was produced. The 172 and 185 solution files are unchanged.

## 1. Stock-column mapping

`SpiderState.deal` takes `stock[-10:]` and writes it left to right onto columns 0 through 9. `next_stock_row` already used that order. `locate_all_cards` did not. It set the column to `from_top % 10`, with `from_top = n - 1 - i`. On a 50-card stock that places `stock[0]`, the bottom card and the first card of the last deal, on column 9. The engine places it on column 0. Every card in a full ten-card chunk was mirrored.

The depth and the stock epoch were already right: `deal_offset = from_top // 10`, and `stock_epoch = current_stock_epoch(state, 5) + 1 + deal_offset`. Only the column changed. For a stock whose length is a multiple of 10, the corrected column is `i % 10`. The implementation uses the chunk offset `i - (n - 10 * (deal_offset + 1))` when that chunk is complete, and leaves a partial leftover on the old formula. Legal deals and the stocks in these tests are multiples of 10. This is not an engine dealing bug, and reception scoring was not rewritten.

Checked against `SpiderState.deal` for stock lengths 50, 40, 30, 20, and 10. Locator columns, deal offsets, and epochs agreed with the engine on every card. The old formula disagreed on `stock[0]` of the 50-card pile. At the canonical pre-SD5 state, the locator, `next_stock_row`, and `analyze_stock_reception` all name the same ten cards on the same columns. `analyze_stock_backward` builds its wishes from those reception columns.

## 2. The two reference positions

Both published routes were replayed before the probes. Canonical SHA-256 `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33`: 174 actions, corrected MobilityWare 172, 8 foundations. Autonomous SHA-256 `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73`: 189 actions, corrected MobilityWare 185, 8 foundations. The same hashes were checked after the probes. `independent_cold_complete` stays false. The 185 route's cold provenance is not established by this run.

The fifth deal is canonical action 151, in zero-based order. Checkpoint 151 is the state before that deal.

| | Canonical pre-SD5 | Immediately after the deal | 185 pre-SD5, then dealt |
| --- | ---: | ---: | ---: |
| Checkpoint | 151 | 152 | 137, then 138 |
| Corrected `g` | 149 | 150 | 133, then 134 |
| Stock cards | 10 | 0 | 10, then 0 |
| Empty columns | 0 | 0 | 1 (column 9) |
| Face-down | 1 | 1 | 2 |
| Foundations | 2 | 2 | 2 |
| Same-suit bonds | 50 | 54 | 30 |
| Same-suit landings | 4 | — | 0 |
| Admissible `h` | — | 18 | 42 |
| `g + h` if dealt now | — | 168 | 176 |

The incoming row, in column order, is `3H, 10H, 2D, 3C, 9H, 7C, 7H, AS, 3C, 5D`. Copy labels in deal-file order are `3H#B, 10H#B, 2D#A, 3C#A, 9H#B, 7C#B, 7H#B, AS#A, 3C#B, 5D#A`. Both club threes are in that row, and no club foundation exists yet. A club foundation cannot be finished before this deal.

The first diamond foundation is canonical action 139. Checkpoint 140, the state after that action, has `g=139`, 10 stock cards, 2 empty columns, 2 foundations, 3 face-down cards, and 44 bonds. The canonical route then plays 11 tableau actions, of which 10 have a corrected cost of 1. The free action in that window is `move 2 5 1`. Replaying those 11 actions returns the checkpoint-151 state.

Dealing the 185 pre-SD5 position immediately cannot beat 172 on the admissible bound: `134 + 42 = 176`. Its empty column is column 9, so `3C#B` lands on an empty column instead of on a 4C.

## 3. Receivers that are already productive

Columns are physical. The stock-bearing identity used by both probes is ordered `pack_state`. Swapping two columns is a different state while stock remains.

At checkpoint 151 the exposed tops are:

| Column | Top | Face-up | Face-down | Incoming | Landing |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | 8H | 6 | 0 | 3H#B | non-connecting, buries KH–8H |
| 2 | JH | 3 | 0 | 10H#B | same-suit |
| 3 | 4H | 7 | 0 | 2D#A | non-connecting; a 3D would connect |
| 4 | AH | 2 | 1 | 3C#A | non-connecting; a 4C would connect |
| 5 | 2C | 1 | 0 | 9H#B | non-connecting; a 10H would connect |
| 6 | 8C | 7 | 0 | 7C#B | same-suit |
| 7 | 2S | 20 | 0 | 7H#B | non-connecting, buries JS–2S |
| 8 | 4C | 3 | 0 | AS#A | non-connecting; a 2S would connect |
| 9 | 4C | 10 | 0 | 3C#B | same-suit |
| 10 | 6D | 8 | 0 | 5D#A | same-suit |

Column 1's face-up cards are exactly `KH QH JH 10H 9H 8H`. Column 7's exposed same-suit tail is `JS 10S 9S 8S 7S 6S 5S 4S 3S 2S`. A non-connecting landing on an exposed same-suit run of length at least 6 is counted as a buried long run. Both of those landings qualify, so the canonical deal buries two long runs. That threshold is a recorded feature, not a prune.

The four same-suit landings are the productive arrangement already on the board: JH under 10H, 8C under 7C, 4C on column 9 under 3C#B, and 6D under 5D. Column 8 also shows a 4C, but the other club three is the card that lands on column 4, whose top is AH. Moving column 8's 4C is a different choice from keeping column 9's receiver.

The backward pass asks for a 4H on column 1, a 3D on column 3, a 4C on column 4, a 10H on column 5, an 8H on column 7, and a 2S on column 8. Those are preferences. Putting 4H on column 1 would catch 3H and would also give up the exposed KH–8H run that the 172 route keeps. Putting 8H on column 7 would catch 7H and would break that same heart run. The 185 route's empty column 9 misses 3C#B entirely.

At checkpoint 140 the two empty columns are 1 and 5. The cards that would land on them are 3H and 9H. Neither is a king, so carrying both spaces into the deal gives those spaces to the stock. A one-move use does exist: `move 3 1 1` seats the exposed 4H on column 1, and 3H would then connect. `move 3 1 2` leaves that same 4H exposed. Free whole-column transfers onto those spaces also exist, including `move 2 1 1` and `move 2 5 1`. A free transfer onto one empty leaves the other empty. That is two-space leverage. It is recorded on the paths that use it. An empty column is not itself a score.

## 4. How the two probes were limited

Both probes play `tableau_actions` only. The real deal is applied to a clone after each retained state and is not a search move. Identity is ordered `pack_state`. One worker. Caps: 20,000 retained identities, 30 seconds, 512 MB. No reference actions were loaded into the frontier. `is_terminal` is always false, so a foundation removal does not stop the search.

The near-deal probe starts at checkpoint 151, `g=149`. It allows three tableau actions. A zero-cost whole-column transfer counts as one of the three. The kernel ceiling is the proof ceiling 171, and the bound passed in is the raw admissible remainder. A cost-only ceiling of 152 was not run: once a space exists, an unbounded run of free transfers can fill the unique cap without paying. In this neighborhood the root has no empty column, and no expanded state offered a zero-cost action.

The last-preparation probe starts at checkpoint 140, `g=139`, and refuses any child with corrected `g` above 149. That is the number of paid moves the verified route spent, not a proof that the game is over. The kernel has one ceiling, so the height given to it is `max(0, admissible - 22)`. For every `g <= 149`, `g + shifted height > 149` is exactly `g + admissible > 171`. Equality stays eligible. A deal-now total of 172 or more marks that immediate deal as unable to beat 172. It does not delete the pre-deal state, because another tableau move can change the landing.

While stock remains, the admissible remainder at these positions is about 1. The 22-point shift therefore stays 0, and the proof test does not fire. The zeros in `lower_bound_prunes` are not evidence about the preparation budget. `ceiling_prunes` is also 0 on the second probe because the search never generated a state at `g=150`.

The portfolio keeps at most eight deal-legal assessments. The axes are lower `g`, lower post-deal `h`, more same-suit landings, and more legal tableau moves after the deal. Empty columns are not an axis. A smaller `g + h` is not a claim that the game can be finished at that cost.

## 5. Near-deal neighborhood

Stop: depth limit, after 2.395 seconds. The frontier drained, and 1,142 states were stored at depth 3 and not expanded. This is the whole three-move neighborhood, not a timeout.

| | |
| --- | ---: |
| Expanded | 200 |
| Retained | 1,342 |
| Generated | 3,299 |
| Duplicate skips | 1,958 |
| Depth skips | 1,142 |
| Proof prunes | 0 |
| Ceiling prunes | 0 |
| Zero-cost actions considered | 0 |
| Deal evaluation | 1.592 s |
| Peak RSS | 34.4 MB |
| Distinct post-deal states | 1,342 |
| Deal-now `f >= 172` | 1,323 |
| Minimum `h` after the deal | 18 |
| Minimum `f` after the deal | 168 |
| Maximum same-suit landings | 5 |
| Pareto front | 4, not truncated |

The canonical state is the root, at `g=149`. Nineteen states, including that root, still have an immediate-deal bound below 172. None has a post-deal remainder below 18, and none has a total below 168.

The only new landing inside three moves is `move 7 8 2`. It moves `3S 2S` from the spade tail onto column 8's `4C`. Column 8's new top is 2S, so AS connects. The pre-deal cost becomes 150, the post-deal cost is 151, `h` stays 18, and `f` is 169. Mobility rises from 16 to 19. JS–4S remains a buried long run, and KH–8H is still buried by 3H. The extra landing does not tighten the bound. The same move followed by two further moves reaches five landings at `g=152` with `h` of 19 or 20, so those deals cannot beat 172 even as a lower bound. No shortlisted state in this neighborhood has an empty column. There is no two-space opportunity within the three moves.

## 6. Last-preparation search

Stop: unique limit, after 25.540 seconds. The canonical checkpoint-151 state was not reached. The known 11-action continuation shows that the state is reachable. This cap does not prove it unreachable.

| | |
| --- | ---: |
| Expanded | 1,609 |
| Retained | 20,000 |
| Generated | 37,208 |
| Duplicate skips | 17,209 |
| Zero-cost actions considered | 6,722 |
| Proof prunes | 0 |
| Ceiling prunes | 0 |
| Deal evaluation | 19.116 s |
| Peak RSS | 64.2 MB |
| Distinct post-deal states | 20,000 |
| Deal-now `f >= 172` | 888 |
| Minimum `h` after the deal | 24 |
| Minimum `f` after the deal | 166 |
| Maximum same-suit landings | 4 |
| Pareto front | 138, not truncated |

The root itself, dealt immediately, has `g_post=140`, one same-suit landing (7C on 8C), two empty landings (3H and 9H), `h=27`, and `f=167`. Three face-down cards remain. The numeric total is below 168 because ten paid preparation moves have not been spent. The remainder is worse than 18.

The retained paths that reach four same-suit landings do it in two paid moves plus free transfers. One such path is `move 2 5 1`, `move 3 1 2`, `move 9 2 1`. The free move parks 2C on the empty column 5 and leaves column 1 empty. The next move seats a heart build on column 1 so that 3H connects. The last move takes the JH from column 9 onto column 2, so 10H connects, and uncovers the 4C that catches 3C#B. Column 6 already caught 7C. That is four landings at `g_pre=141`, `g_post=142`, `h=24`, `f=166`, with 3 face-down cards and 48 bonds. Several other shortlist paths are the same landing pattern reached by a different free transfer between the two spaces (`move 8 5 3`, `move 10 5 2`, and the transfers that put those columns back). They use one to three zero-cost whole-column moves on the actual path. They do not reduce `h` below 24.

Catching 3H here is the opposite of the canonical choice. The 172 route leaves 3H on KH–8H and spends the remaining moves reducing the assembly bound from the mid-20s to 18. A bound of 166 does not say this early deal finishes in 166 moves. No continuation was searched, and none is claimed.

The two spaces at `g=139` are why the unique cap filled before `g=149`. Free transfers to new physical arrangements consume retained identities without raising `g`. The search considered 6,722 of them. Best-first order therefore stayed in the `g=139` to `g=141` band.

## 7. What was preserved

Corrected MobilityWare scoring is unchanged, including a zero-cost move of a whole face-up column onto an empty column when the source has no face-down cards. Unrestricted dealing into an empty column is unchanged. The kernel admission order from v0.131 is unchanged. The Human Strategy Controller, `engine.py`, and `rules.py` were not edited. The v0.120 timing test was not weakened. No incumbent or solution file was written.

## 8. Tests

`tests/test_pre_sd5_backward_preparation_v0_132.py` and `tests/test_backward_strategy.py`: 19 passed. The new file locks the engine mapping and epochs for all five full stock lengths, the disagreement of `from_top % 10`, the SD5 row and both reference deals, unrestricted dealing onto an empty column, zero-cost depth accounting, ordered identity while stock remains, the deal-now flag that does not delete the pre-deal state, proof rejection before a unique slot, and the shifted-bound identity for `g` from 130 through 149 and admissible heights from 0 through 49.

The maintained regression list from `docs/global_search_architecture_v0_124.md`, plus the v0.125, v0.126, v0.129, v0.130, v0.131, and v0.132 files: 586 passed in 210.99 seconds. The v0.120 live-solve test returned `TIME_LIMIT` in this run. It can still return `PLANNING_STALL` in another full-suite run, and that sensitivity is not retired. Bare `pytest tests` still fails collection on the eight research modules that import missing `*_v0_1` services. Those modules were not edited.

## 9. Next experiment

Do not start a complete continuation from an early-deal state whose remainder is 24. The three-move neighborhood of the real pre-SD5 tableau was exhausted, and 168 remained its best immediate-deal bound. The next complete-route experiment, only if it is authorised on its own, should return to the verified post-SD5 checkpoint at `g=150`, `h=18`. It needs its own budget. This release did not run it, and it did not raise the old 80,000-state or 90-second cap.
