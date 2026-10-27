# Post-SD5 completion v0.130

Schema `spider-post-sd5-completion-0.130`. Deal `4925153`. Branch `local/post-sd5-completion-v0-130`, started from v0.129 `bfc08b0b642260dcf428e633f88a04ee1bb4632a`.

This is an incumbent-guided suffix search from the exact tableau after stock deal 5. It is not an exact-state checkpoint rejoin, not a general suffix repair, and not an `independent_cold_complete` solve. The production incumbent was not overwritten.

## Result

No complete game cheaper than 172 was found. The positive control also failed to rediscover any complete suffix inside the budget. Every search stopped on the unique-state cap. The fixed post-SD5 checkpoint is unresolved, not proved minimal.

| Gate | Ceiling | Ordering | Stop | Solved | Expanded | Unique | Foundations expanded |
| --- | ---: | --- | --- | --- | ---: | ---: | --- |
| B, positive control | 172 | completion prefix | unique limit | no | 1,766 | 80,000 | 2–5 |
| C, strict improvement | 171 | completion prefix | unique limit | no | 1,766 | 80,000 | 2–5 |
| D, ordering comparison | 171 | cost `(g,)` | unique limit | no | 5,373 | 80,000 | 2–3 |

The known 22-move suffix remains a replayed solution of this position. Its existence is why a capped miss is inconclusive. The search did not preload that suffix.

The next hypothesis is a different tableau before SD5, with backward planning from the final row and a looser rejoin or a full endgame continuation. That search was not started.

## 1. Baseline

Repository `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`. Remote `origin` is `https://github.com/Montgomerie-B/spider-solver.git`. One worker. Corrected MobilityWare scoring, including zero-cost whole-column transfers onto an empty column. `MW_RULES` still allows a deal onto an empty column. This position has an empty stock, so a deal is not legal.

Both historical solution files were replayed from `deals/4925153.txt` before the searches and hashed again afterwards.

| Route | SHA-256 | Explicit | Tableau | Deals | Foundations | Corrected MW | Legacy MW | Solved |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | 174 | 169 | 5 | 8 | 172 | 163 | yes |
| `solutions/4925153_autonomous_185.moves` | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` | 189 | 184 | 5 | 8 | 185 | 177 | yes |

The hashes were unchanged. `solutions/` was not written. The incumbent registry was not written. The 185 route was replayed and left unused.

The v0.126 full-suite failure is unchanged and was not rerun. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` where the assertion expects `TIME_LIMIT` when the whole suite runs.

## 2. The checkpoint

The fifth `deal` is canonical action index 151. Checkpoint 152 is the state after that action. The values below were recomputed from the replay.

| Fact | Value |
| --- | ---: |
| Actions already applied | 152 |
| Absolute corrected cost `g` | 150 |
| Stock cards | 0 |
| Foundations | 2 |
| Face-down cards | 1 |
| Same-suit bonds | 54 |
| Empty columns | 0 |
| Legal actions | 16 |
| Zero-cost actions at the root | 0 |
| Deal legal | no |
| Stock-empty assembly `h` | 18 |
| `admissible_remaining` | 18 |
| `g + h` | 168 |
| Known suffix | 22 actions, corrected cost 22 |
| Slack to 172 | 4 |
| Slack to 171 | 3 |

Gate A replayed the known suffix from this checkpoint. At every continuation state, both `stock_empty_assembly_h` and `admissible_remaining` were at most the corrected cost still left in that suffix. The slack falls to 0 at suffix step 17 (`g=167`, `h=5`, three foundations) and stays tight through the last move. The replay finishes at corrected cost 172 with eight foundations and an empty stock. This is a sanity check on the known path, not a general admissibility proof.

`admissible_remaining` at this position equals the assembly bound. One call took 0.191 ms. The full existing `completion_key`, which also counts blockers, boundaries, and legal moves, took 3.081 ms. Eighty thousand of those key calls would spend about four minutes before any other search work. The runs below therefore use the cheap prefix of that key, `(g + h, h, -foundations, g)`, with `h = admissible_remaining`. The proof test is unchanged: a state is discarded when `g + h` is strictly greater than the absolute ceiling. Equality is kept, because a state can still finish exactly at the ceiling.

## 3. Search

`run_search` has one root: the packed physical checkpoint, `g=150`. Successors are `all_legal_actions`. Step costs are corrected MobilityWare costs. The terminal test is `state.is_solved()`. The first solved state stops the run. That cost would be a verified cost of one legal suffix, not a claim that no cheaper suffix exists.

Search identity is `pack_whole_game_identity`. The stored node remains `pack_state`, so a reconstructed path uses the original column indices. With the stock empty, the identity is the existing whole-column permutation quotient. A stock-bearing state keeps ordered `pack_state`. No new quotient was added. The known suffix was not inserted into the frontier.

Caps for every gate: 80,000 unique identities, 90 seconds, 512 MB, one worker. The time cap and the memory cap did not bind. The process working set peaked at 108.2 MB during the first search. Each run stopped because the unique counter reached 80,000.

The kernel admits an identity before the proof test. A state with `g + h` above the ceiling still consumes a unique slot, and then it is not queued. Under ceiling 171 that admission rule filled most of the budget with states the bound had already retired.

## 4. Gate B, ceiling 172

Inconclusive. Stop `unique limit` after 61.091 s. No terminal. Expanded 1,766, unique 80,000, generated 171,669, transposition or symmetry skips 88,971, stale pops 20, ceiling prunes 0, lower-bound prunes 0, zero-cost actions 13,577, symmetry collapses 82,177. `g` spanned 150–168. `h` spanned 3–19. The best scored `g + h` was 168, the same value as the opening. Foundations were expanded at counts 2, 3, 4, and 5 (692, 780, 272, and 22 expansions). No state reached eight foundations.

Expansions by absolute `g`: 150: 1, 151: 7, 152: 17, 153: 42, 154: 55, 155: 60, 156: 60, 157: 56, 158: 52, 159: 61, 160: 340, 161: 394, 162: 326, 163: 184, 164: 75, 165: 27, 166: 8, 167: 1. Generated children reached `g=168` (184 of them) and those nodes were not expanded. Every scored state satisfied `g + h <= 172`, which is why the bound pruned nothing. The cap arrived while the `f=168` layer was still open.

This does not show that a 22-move suffix is absent. The replayed canonical suffix is one.

## 5. Gate C, ceiling 171

Inconclusive. The completion order expanded the same 1,766 nodes and generated the same 171,669 children as Gate B. Elapsed 52.089 s. The difference is the proof test: 56,394 admitted states had `g + h > 171` and were not queued. Those prunes sit at `g` 160–168 and at foundation counts 2, 3, 4, and 5 (17,992, 29,086, 8,770, and 546). Ceiling prunes stayed 0, because no generated child had corrected cost above 171; the bound, not the raw cost, retired them.

The same nodes were expanded because the completion order had not yet popped a state with `g + h > 171` when the unique counter filled. Queueing those states in Gate B did not change the expansions. Refusing them in Gate C did not free the unique slots, because the counter increments before the proof test.

No solved state was stored. `negative_proof` is false. A finished frontier would have been the strongest negative result available for this fixed checkpoint. This run is not that result, and it says nothing about a different tableau before the fifth deal.

## 6. Gate D, cost order, ceiling 171

Inconclusive. Same identity, bound, and caps. The lane key was `(g,)`. Stop `unique limit` after 50.244 s. Expanded 5,373, unique 80,000, generated 150,630, skips 70,631, stale 0, ceiling prunes 0, lower-bound prunes 69,088, zero-cost actions 5,194, symmetry collapses 14,135. Expanded `g` reached 156 (1, 16, 104, 435, 1,418, 2,917, 482). Generated children reached `g=157`. Foundations expanded only at 2 and 3 (4,799 and 574). Bound prunes were 61,481 at two foundations and 7,607 at three. `h` spanned 12–20. The best scored `g + h` was again 168.

Cost order spends the unique budget on the shallow layers. Completion order spends it further along `g` and reaches five foundations. Neither order produced a solved tableau. Symmetry collapses were larger on the completion run (82,177 against 14,135) because that run met more empty-column permutations after foundations were removed. Those permutations were not deleted from the move generator. They lost the identity test and did not become extra unique states.

## 7. Acceptance

No gate produced a replayed suffix. `verify_complete_solution` was not given a candidate. A solved suffix would have been concatenated with the unchanged 152-action prefix and accepted only when the full game replayed at the claimed cost with eight foundations. Provenance would have been a reused canonical prefix, an independently discovered suffix, and an incumbent-guided route. `independent_cold_complete` would have stayed false. A cost of 172 would have validated the control and would not have replaced the incumbent. A cost of 171 or less would have been reported as an experimental route and would not have been written over `solutions/`.

## 8. What the budget shows

The opening has no empty column, so the root itself has no zero-cost move. Symmetry starts to matter after a foundation removal creates an empty column. On the completion runs, 82,177 generated states were a second physical column order of an identity already seen. That is the quotient doing the job it was built for. The remaining distinct classes still reached 80,000 before a solved state appeared.

The admissible frontier did not improve on `g + h = 168` inside the admitted set. Low `h` values in the completion run belong to states whose `g` had already risen. `h=3` is still an `f` of at least 168. Foundation count did move: the completion order expanded 22 states with five foundations. That is search progress. It is not a complete game.

The unique cap counts proof-dead states. Under ceiling 171, 56,394 of the 80,000 completion-order identities were retired by `admissible_remaining` only after they had taken a slot. Raising the same cap, or swapping the lane key again, would keep searching this one tableau. The issue's stopping rule applies: the checkpoint is unresolved, and v0.130 does not add suffix repair or another controller.

## 9. Tests

Focused fixtures cover the stock-bearing identity split, the empty-stock permutation, both lane keys, retention of the zero-cost transfer, absence of a deal, replay of the reconstructed suffix on the original columns, the two-state cap contrast against ordered identity, the ceiling equality rule, and the recomputed canonical checkpoint.

```text
$env:PYTHONPATH = "src"
py -3 -m pytest tests/test_post_sd5_completion_v0_130.py -q --tb=line
```

9 passed in 0.42 s. The full regression was not run. The documented v0.126 timing-sensitive failure is separate from this run. No new regression was observed in the focused tests.

## 10. Reproduction

From the repository root. The driver inserts `src` on its own path. It writes `artifacts/post_sd5_v0_130/results.json` and does not write `solutions/`. `artifacts/` is gitignored.

```text
py -3 tools/post_sd5_completion_v0_130.py
```

The run that produced this report ended:

```text
GATE A index=152 g=150 h=18 fd=1 bonds=54 legal=16 key_s=0.003081
DONE B stop=unique limit solved=False g=None expanded=1766 unique=80000 generated=171669 dup=88971 symmetry=82177 ceiling_prunes=0 lb_prunes=0 zero=13577 max_f=5 elapsed=61.091 peak=108.17578125 proof=False
DONE C stop=unique limit solved=False g=None expanded=1766 unique=80000 generated=171669 dup=88971 symmetry=82177 ceiling_prunes=0 lb_prunes=56394 zero=13577 max_f=5 elapsed=52.089 peak=108.17578125 proof=False
DONE D stop=unique limit solved=False g=None expanded=5373 unique=80000 generated=150630 dup=70631 symmetry=14135 ceiling_prunes=0 lb_prunes=69088 zero=5194 max_f=3 elapsed=50.244 peak=108.17578125 proof=False
ACCEPTED 0 HASHES_OK True NEGATIVE_C False
```

## 11. Scope left unchanged

`engine.py`, `rules.py`, the search kernel's admission rule, the Human Strategy Controller, and the v0.120 timing test were not edited. The five v0.128 exact-rejoin windows were not searched again. Cold whole-game search was not run. General suffix repair was not implemented.
