# State-first completion v0.126

Deal `4925153`. Corrected MobilityWare costs. One worker. Memory cap 3,072 MB. The exploratory continuation used hard corrected-cost cap 300 and did not impose the MW 172 ceiling. This release does not commit, push, merge, or open a pull request.

v0.125 reached a replay-valid four-foundation position at corrected cost 139. v0.126 continued that exact position with the existing state-first kernel. The continuation did not finish the game. An independent enumeration of the same legal component found 41,472 states, maximum corrected cost 153, eight face-down cards in every state, no empty column, and no fifth foundation. The component is closed. Ordering is not the reason the trajectory stops.

## 1. Branch and baseline commit

Branch `local/state-first-completion-v0-126`, created from a clean tree.

HEAD `49595bc5415d96f3a949b66b29059a0ad81eef03` (`49595bc Add state-first suit-completion ordering v0.125`).

`engine.py` and `rules.py` are unchanged. The seven original lane tuples are unchanged. `suit_lane_keys` is unchanged and remains the experimental default. The Human Strategy Controller, the anchored optimiser, the incumbent registry, and the verified solution files are unchanged. Historical reports and artifact directories were left in place.

## 2. Files changed

- `src/spider/global_search_experiment.py` — a saved prefix can resume `search_suit_ordered`. Corrected `g` stays absolute. Provenance is `checkpoint_continuation` or, if a full game replays, `checkpoint_assisted_complete`. Cold searches still emit `spider-global-search-0.125`.
- `tools/global_search_experiment.py` — `--prefix-artifact` loads that prefix for a cold suit search. The default variant remains `suit`.
- `tests/fixtures/g139_v0125_partial.json` — the 139 exported actions and the source hash.
- `tests/test_global_search_v0_126.py` — replay, continuation accounting, and incumbent checks.
- `docs/state_first_completion_v0_126.md` — this report.

Experimental outputs under `artifacts/global_search/v0_126/` are gitignored, as the existing `artifacts/` rule requires. They were not copied into `solutions/`.

## 3. g139 checkpoint provenance

Source artifact: `artifacts/global_search/v0_125/suit_80000.json`.

SHA-256: `bc0954851d2e8b37bfcdf3e10918b09a163b52898f2c8dc807663c1629ae1a36`.

Schema `spider-global-search-0.125`. Variant `suit`. Mode `cold`. Provenance `partial_legal_search`. `known_prefix` is false. `solved` is false. The actions are `result.best_partial.actions` (139 formatted moves). The search that produced them did not load the MW 172 or MW 185 routes.

Independent replay from `deals/4925153.txt`:

| Check | Result |
|---|---|
| Illegal action | none |
| Corrected cost | 139 |
| Foundations removed | 4 |
| Removal order | Spades, Clubs, Diamonds, Hearts |
| Removal costs | 76, 84, 87, 133 |
| Face-down after each removal | 13, 13, 12, 9 |
| Face-down at the end | 8 |
| Stock | empty |
| Solved | no |

The search's first visit to one foundation was a different branch at corrected cost 65. The exported trajectory itself removes Spades at 76. Clubs, Diamonds, and Hearts on that trajectory match the first-visit costs 84, 87, and 133.

Checkpoint id, the ordered `pack_state` hex of the replayed position:

`53504b310104000004033a2c36083504130104151918171600033d3c3b030231122d1a0700050d0c0b0a090003393837000b2b2a29282726252423222100031d1c1b00043433321100060605140302010d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201`

Stored with the physical analysis in `artifacts/global_search/v0_126/g139_checkpoint.json`. Later search from this id is checkpoint continuation, not a fresh cold solve.

## 4. Physical state

Stock is empty. No column is empty. Eight cards are face-down. The remaining 52 cards are one copy of every suit and rank. Face-down is deepest first. Face-up is bottom to top, so the last face-up card is the exposed top.

| Column | Face-down | Face-up |
|---|---|---|
| 1 | 10c, Qd, 6c, 8s | 5c, 4s, 3h |
| 2 | 5h | 9h, 8h, 7h, 6h |
| 3 | | Kc, Qc, Jc |
| 4 | Ac, 2h, Kd | 10h, 7s |
| 5 | | Ks, Qs, Js, 10s, 9s |
| 6 | | 9c, 8c, 7c |
| 7 | | Jd, 10d, 9d, 8d, 7d, 6d, 5d, 4d, 3d, 2d, Ad |
| 8 | | Kh, Qh, Jh |
| 9 | | 4c, 3c, 2c, Ah |
| 10 | | 6s, 5s, 4h, 3s, 2s, As |

Same-suit runs that matter:

- Diamonds, column 7: Jd down to Ad, length 11, exposed. Qd and Kd are absent from the run.
- Spades, column 5: Ks down to 9s, length 5, exposed.
- Hearts, column 2: 9h down to 6h, length 4, exposed, with 5h directly face-down beneath.
- Hearts, column 8: Kh, Qh, Jh.
- Clubs, column 3: Kc, Qc, Jc.
- Clubs, column 6: 9c, 8c, 7c.
- Clubs, column 9: 4c, 3c, 2c, buried under Ah.
- Spades, column 10: 3s, 2s, As exposed; 6s, 5s buried under 4h.

Suit-completion proximity is 2,772. Diamonds contribute 1,140, Spades 698, Hearts 482, Clubs 452. The diamond run is `near_blocked`: length 11, and both missing cards are face-down. `near_accessible` is 0.

Accessible kings are the exposed heads Kc, Ks, and Kh. Kd is the next face-down card of column 4. Accessible aces are the exposed tops Ad, Ah, and As. Ac is the deepest face-down card of column 4.

The eight face-down cards and what would have to move before each can flip:

| Card | Column | Cards above it |
|---|---|---|
| 8s, then 6c, Qd, 10c | 1 | 5c, 4s, 3h, then the face-down cards above |
| 5h | 2 | 9h, 8h, 7h, 6h |
| Kd, then 2h, Ac | 4 | 10h, 7s, then the face-down cards above |

No legal sequence flips any of them. The enumeration in section 7 visited every reachable state and the face-down count stayed 8.

## 5. Legal moves and blockers

There are 14 legal tableau moves. Every one costs 1. None is a deal, none costs 0, none flips a card, and none empties a column.

| Move | What it does |
|---|---|
| `move 2 4 1` | 6h onto 7s |
| `move 2 6 1` | 6h onto 7c |
| `move 2 5 3` | 8h–6h onto 9s, leaving 9h |
| `move 5 3 2` | 10s–9s onto Jc |
| `move 5 8 2` | 10s–9s onto Jh |
| `move 6 5 2` | 8c–7c onto 9s, leaving 9c |
| `move 7 1 2` | 2d–Ad onto 3h, leaving 3d |
| `move 7 2 5` | 5d–Ad onto 6h, leaving 6d |
| `move 7 4 6` | 6d–Ad onto 7s, leaving 7d |
| `move 7 6 6` | 6d–Ad onto 7c, leaving 7d |
| `move 7 5 8` | 8d–Ad onto 9s, leaving 9d |
| `move 7 3 10` | 10d–Ad onto Jc, leaving Jd |
| `move 7 8 10` | 10d–Ad onto Jh, leaving Jd |
| `move 10 1 2` | 2s–As onto 3h, leaving 3s |

Columns 1, 3, 4, 8, and 9 have no legal move off them. Their tops need a 4, a queen, an 8, a queen, and a 2. Those receivers are not exposed, and the cards that could become those receivers are under the same tops or under another blocked top.

The joins still required for a fifth foundation are the gaps in the one remaining copy of each suit. The assembly units are:

| Suit | Lower bound | Units (low, high) |
|---|---:|---|
| Spades | 5 | 8; 4; 7; 9–13; 5–6; 1–3 |
| Hearts | 7 | 3; 5; 6–9; 2; 10; 11–13; 1; 4 |
| Diamonds | 2 | 12; 13; 1–11 |
| Clubs | 6 | 10; 6; 5; 11–13; 1; 7–9; 2–4 |

Diamonds are the closest suit, and both missing cards are inside the frozen face-down set: Qd is the third buried card of column 1, and Kd is the next flip of column 4. Building that foundation requires flips the position cannot make. The king runs on columns 3, 5, and 8 can move only onto an empty column, and no reachable state creates one.

Classification: the position has legal moves, and it is structurally closed. It is not a terminal position with an empty move list. It is not an ordering stall. A bounded failure is not required to reach that conclusion. The whole legal component was enumerated.

## 6. Admissible completion lower bound

`admissible_remaining` at g139 is 20. The reveal bound is 4 (`ceil(8 / 2)` with no stock deals left). The stock-empty assembly bound is 20 and dominates: 5 + 7 + 2 + 6. `g + h` is 159.

`proof_prune(139, 20, 172)` is false. `proof_prune(139, 20, 185)` is false. `proof_prune(139, 20, 159)` is true. The admissible bound does not rule out a route from this checkpoint cheaper than 172 or 185. Beating 172 would need a suffix of at most 32. Beating 185 would need a suffix of at most 45. Both are larger than 20.

That bound is not a proof that a route exists. The exhaustive component is the stronger fact, and it applies only to this checkpoint: no completion exists at any corrected cost. The opening deal remains solvable by other lines. The verified MW 172 and MW 185 routes are such lines. They were not loaded into the search.

The exploratory continuation passed `lower_bound_fn=None`. Lower-bound prunes were 0. Proximity was not passed to `proof_prune`.

## 7. Stock-empty continuation

Command shape: existing `search_suit_ordered`, which calls `run_search` with `all_legal_actions`, the seven lanes, and `suit_lane_keys`. The root `g` was 139, so the cap of 300 is a full-game corrected cost. One worker. Unique cap 80,000. Time cap 150 seconds. RSS cap 3,072 MB. No incumbent. No 172 or 185 actions.

Result file: `artifacts/global_search/v0_126/continuation_suit_80000.json`.

| Measure | Value |
|---|---|
| Stop | `complete` |
| Solved | false |
| Provenance | `checkpoint_continuation` |
| Unique identities | 41,472 |
| Expanded records | 41,511 |
| Generated successors | 353,721 |
| Safe transposition skips | 311,122 |
| Stale lane pops | 256,689 |
| Lower-bound prunes | 0 |
| Heuristic exclusions | 0 |
| Stock deals | 0 |
| Elapsed | 128.958 s |
| CPU | 128.078 s |
| Peak RSS | 76.22 MB |
| Lane pops | 42,600 on each of the seven lanes |

The unique cap and the time cap did not bind. The frontier emptied. An independent breadth-first enumeration, using the same legal generator and the same `pack_whole_game_identity` dominance, exhausted a component of the same 41,472 identities in 76.375 seconds. Its edge count was 353,376. The kernel's generated count is higher because a cheaper path can expand an identity again. Both traversals agree on the state set.

That enumeration's maximum corrected cost is 153. Its minimum is 139. No state costs more than 300, so the hard cap removed nothing. Recorded in `artifacts/global_search/v0_126/g139_component.json`.

## 8. Foundations and cumulative costs

From the checkpoint, the continuation's maximum foundation count stayed 4. The report leader, the proximity leader, the face-down leader, the longest-run leader, and the exposed-run leader are all the checkpoint itself: cost 139, 8 face-down, proximity 2,772, run length 11, 14 legal moves. Replay of the stored actions from the opening returns cost 139.

No fifth, sixth, seventh, or eighth foundation was reached. No state in the component has fewer than 8 face-down cards or an empty column. The longest run never exceeded 11. States with a run of length at least 8: 2,860. Length at least 10: 474. Length 12 or 13: 0. `near_accessible_states` is 0. `near_blocked_states` is 131, all still on the blocked diamond shape. `states_below_root_face_down` is 0.

`SOLVED_VALID` does not apply. Eight foundations were not removed.

## 9. Why the trajectory does not finish

The position admits 14 legal moves, and every descendant of those moves stays inside a cage of 41,472 states. Across that cage:

- Face-down cards stay at 8, so Qd, Kd, 5h, and the other five buried cards never become available.
- Empty columns stay at 0, so the three exposed king runs cannot move as wholes.
- Foundation count stays at 4.
- The deepest state is only 14 corrected points beyond 139.

The measured ordering concern was that `(-foundations, -proximity, face_down, stock_rows, g)` might prefer the length-11 diamond run over a flip. Inside this component there is no flip to prefer. The maximum proximity in the component is the checkpoint's own 2,772, at 8 face-down and 14 legal moves. High proximity here coincides with the blocked diamond run. It does not hide a better state: the face-down leader and the mobility of every visited state were recorded, and none of them exposes a card or opens a column.

A transposition did not delete a useful route. The identity after an empty stock is column permutation. A flip changes a column's cards, so a revealing state cannot share an identity with a buried one. Dominance only drops an equal-or-worse cost to the same identity. The second enumerator, which keeps a cheaper cost and still expands it, found the same set and the same face-down count.

The failure is the selected state. It is a closed partial. The opening is a different question. The cold search that produced this prefix also visited states with 7 face-down cards, at three foundations rather than four. Those states are outside this component.

## 10. Endgame-ordering correction

No ordering correction was added. Gates B and C did not show an ordering deficiency. They showed a closed legal component. A different sort key would generate the same successors and the same 41,472 states. `suit_lane_keys` remains the v0.125 control and the experimental CLI default.

## 11. Matched ordering comparison

There is no Experiment B. Control A is the v0.125 suit order, run from g139 under the budget in section 7. It reached four foundations, eight face-down cards, and a completed frontier. A second policy was not run, because it cannot enlarge this component.

## 12. Alternative four-foundation checkpoints

The v0.125 artifact stores one replayable four-foundation action path: the report leader at cost 139. Its `f4_stock0` stratum has the same cost and face-down count and does not store actions or a digest. The other leaders are not four-foundation states:

| Leader | Foundations | Cost | Face-down | Actions |
|---|---:|---:|---:|---:|
| report | 4 | 139 | 8 | 139 |
| proximity | 0 | 82 | 14 | 82 |
| face_down | 3 | 102 | 7 | 102 |
| longest_run | 3 | 133 | 9 | 133 |
| exposed_run | 3 | 132 | 10 | 132 |

No second four-foundation state was available to continue. The three-foundation face-down leader was not used as a hidden guide, and the MW 172 and MW 185 routes were not used either.

## 13. Independent cold search

The cold 80,000-state suit search is the existing v0.125 artifact above. This release did not change `suit_lane_keys`, `lane_keys`, or `all_legal_actions`. Cold `search_suit_ordered` still starts at `g = 0` with no prefix. That run was not executed a second time.

Cited cold result, `artifacts/global_search/v0_125/suit_80000.json`:

| Measure | Value |
|---|---|
| Provenance | `partial_legal_search` |
| Stop | unique limit |
| Foundations | 4 |
| First visits | f1 at 4.283 s, g 65, 13 face-down; f2 at 7.284 s, g 84; f3 at 7.417 s, g 87; f4 at 48.49 s, g 133 |
| Exported partial | g 139, 8 face-down, stock empty, replay 139 |
| Unique | 80,000 |
| Elapsed | 100.212 s |
| Peak RSS | 163.90 MB |
| Fifth foundation | no |
| Solved | no |
| Minimum face-down seen anywhere | 7 |

The same published comparison, at 80,000 states, remains:

| Ordering | Foundations |
|---|---:|
| Original seven lanes | 0 |
| Human strategy lane | 0 |
| Suit proximity | 4 |

Those two controls are `artifacts/global_search/v0_124/control_b_150.json` and `experiment_c_150.json`. Their lane weights, caps, and files were not changed. The cold result and the checkpoint continuation are separate. The continuation is not an independent cold discovery.

## 14. Second seeded deal

Seed 126, from `opening_from_seed`. Not deal 4925153. Both policies: one worker, 20,000 unique states, 60-second cap, hard cost cap 300, RSS cap 3,072 MB. Both hit the unique limit with zero foundations. Neither was tuned on 4925153.

| Policy | Foundations | Longest run seen | Best face-down | Best stock rows | Best cost | Unique | Time | RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original kernel | 0 | 5 | 25 | 0 | 44 | 20,000 | 40.565 s | 50.15 MB |
| Suit order | 0 | 10 | 16 | 1 | 60 | 20,000 | 24.845 s | 55.51 MB |

The suit search built longer runs and turned more cards on this deal. It did not remove a foundation. That is a structural difference at a matched cap, not evidence that the suit order finishes four-suit games in general. The v0.125 seed-125 smoke at 2,500 states is unchanged and is a smaller, separate check.

## 15. Verified complete solutions

No new complete route was found. The checkpoint continuation removed no further foundation. There is no prefix-plus-suffix game to validate, and nothing was written to `solutions/`.

## 16. Incumbent integrity

`solutions/4925153_autonomous_185.moves` still replays at corrected cost 185 with eight foundations. `solutions/4925153_canonical.moves` still replays at 172 with eight foundations. The g139 prefix is rejected by `verify_complete_solution`. A short anchored optimisation from the verified 172 route still reports cost 172 and no improvement. The continuation tests read those files and check that the bytes are unchanged. Neither file was overwritten. The production registry was not edited.

## 17. Test totals

`tests/test_global_search_v0_126.py`: 13 passed in 0.90 seconds.

The maintained regression is the v0.123 file list, plus `tests/test_global_search_v0_124.py`, `tests/test_global_search_v0_125.py`, and `tests/test_global_search_v0_126.py`. Two runs of that command collected 551 tests. Each run reported 550 passed and 1 failed, in 221.00 seconds and 212.73 seconds. The failure was `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle`. It expected `TIME_LIMIT` and the full-process solve returned `PLANNING_STALL` before the six-second deadline. The same test passed in 6.33 seconds by itself, the v0.120 file passed 21 tests in 6.61 seconds, and it passed again when run after the v0.125 and v0.126 tests. This release did not edit that test or the Human Strategy Controller.

The 13 new tests are among the 550 passes. The previous v0.125 total was 538. This suite is those 538 plus these 13.

A bare `pytest` still collects research modules outside this suite. Those modules were not changed and were not "fixed."

## 18. Runtime and peak RSS

| Run | What it is | Time | Peak RSS | Stop |
|---|---|---:|---:|---|
| Suit continuation from g139 | checkpoint, 80,000 cap | 128.958 s | 76.22 MB | frontier empty at 41,472 |
| Independent component enumeration | same position | 76.375 s | not recorded | 41,472 states, max g 153 |
| Seed 126 original kernel | cold, 20,000 | 40.565 s | 50.15 MB | unique limit |
| Seed 126 suit order | cold, 20,000 | 24.845 s | 55.51 MB | unique limit |
| v0.125 suit cold, cited | cold, 80,000 | 100.212 s | 163.90 MB | unique limit |

The continuation's peak RSS is the largest measurement taken in this session. The cited cold run is higher and was not repeated.

## 19. Remaining limitations

The closed-component result is for this checkpoint under the current rules and the stock-empty column-permutation identity. It does not say that every four-foundation state is closed, and it does not say the opening has no cheaper solution than 172.

The cold search's report key prefers more foundations, so it exported the closed g139 line even though the same run had seen a three-foundation state with 7 face-down cards. The kernel did explore other branches until the 80,000 cap. It does not yet notice that a component has become closed, so a future cold run can still spend states inside a cage like this one.

Suit proximity remains an ordering signal. On seed 126 it lengthened runs without removing a foundation. One deal and one extra seed do not establish a general finishing policy.

## 20. Recommended v0.127 development

Do not search g139 again for a fifth foundation, and do not start incumbent optimisation from it. There is no completion on this prefix at any cost.

The useful next step is inside the existing cold kernel. When a stock-empty state has no empty column, detect whether its legal component can still flip a card or create a column. If the component is closed, leave it and keep the unique-state budget for partials that still have an exposure route. The v0.125 face-down leader, three foundations at cost 102 with 7 face-down cards, is an example of a partial the report key currently ranks behind the closed four-foundation line.

Keep `suit_lane_keys` selectable. Do not replace it because this one prefix is closed. A closed component is a property of the state, and another ordering key does not open it.

After a cold search can finish a game, the existing anchored optimiser is the tool for driving the cost from that complete route toward 172. That stage still requires an independently replayed eight-foundation game. This release did not produce one.

## 21. Reproduction commands

From the repository root:

```
py -3 -c "import json,hashlib; from pathlib import Path; p=Path('artifacts/global_search/v0_125/suit_80000.json'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
```

Checkpoint replay and continuation:

```
py -3 tools/global_search_experiment.py --variant suit --mode cold --time-limit 150 --max-unique 80000 --memory-mb 3072 --cost-ceiling 300 --prefix-artifact artifacts/global_search/v0_126/g139_checkpoint.json --out artifacts/global_search/v0_126/continuation_suit_80000.json
```

Seed 126, matched cap:

```
py -3 tools/global_search_experiment.py --variant kernel --mode cold --deal-seed 126 --time-limit 60 --max-unique 20000 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_126/seed126_kernel_20000.json
py -3 tools/global_search_experiment.py --variant suit --mode cold --deal-seed 126 --time-limit 60 --max-unique 20000 --memory-mb 3072 --cost-ceiling 300 --out artifacts/global_search/v0_126/seed126_suit_20000.json
```

The cited cold 80,000-state suit run is the command already recorded in `docs/state_first_suit_proximity_v0_125.md`. Focused tests:

```
py -3 -m pytest tests/test_global_search_v0_126.py -q --tb=short
```

The full regression command is the one in `docs/global_search_architecture_v0_124.md` section 19, followed by `tests/test_global_search_v0_125.py` and `tests/test_global_search_v0_126.py`.

## 22. Final Git status

Branch `local/state-first-completion-v0-126`. HEAD `49595bc5415d96f3a949b66b29059a0ad81eef03`. Nothing was committed, pushed, merged, or opened as a pull request.

```
 M src/spider/global_search_experiment.py
 M tools/global_search_experiment.py
?? docs/state_first_completion_v0_126.md
?? tests/fixtures/g139_v0125_partial.json
?? tests/test_global_search_v0_126.py
```

`engine.py`, `rules.py`, `solutions/`, and the v0.125 artifact directory are unmodified. `artifacts/global_search/v0_126/` holds the checkpoint, the continuation, the component count, and the seed-126 pair. That directory is gitignored.
