# Proof-first admission v0.131

Schema `spider-proof-first-admission-0.131`. Deal `4925153`. Branch `local/proof-first-admission-v0-131`, started from v0.130 `4382d9f792a20ea818dc9bf1e812df602bbd6500`.

One change: an admissible `g + h` rejection happens before a new state takes a unique slot. Lane order, the bound, the symmetry quotient, and the post-SD5 caps are the ones used in v0.130.

## Result

Inconclusive. The matched ceiling-171 search stopped on the 90 second limit. It retained 29,154 proof-eligible identities and expanded 2,744 states. No complete suffix was found. `min f` stayed 168, the same value as the opening `150 + 18`. The fixed post-SD5 checkpoint is unresolved, not proved minimal. This run does not prove anything about the rest of the deal.

The 80,000 retained-state cap did not bind. In v0.130 Gate C that cap bound first, after 52.089 seconds, because 56,394 of the 80,000 counted identities had already failed `g + h <= 171` and were never expanded. Those states no longer take a slot. The search therefore spent the same 90 seconds expanding states that can still meet the ceiling, and the clock ran out with 50,846 retained slots unused.

The v0.130 ceiling-172 control had zero admissible prunes inside its 80,000 counted identities. This admission change does not free slots on that control, and the control was not rerun. It is not evidence that the positive control now finds the known suffix.

Pre-SD5 preparation was not started.

| Run | Ceiling | Stop | Solved | Expanded | Retained unique | Proof events | Elapsed |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| v0.130 Gate C | 171 | unique limit | no | 1,766 | 80,000, including dead states | 56,394 | 52.089 s |
| v0.131 Gate C | 171 | time limit | no | 2,744 | 29,154, all proof-eligible | 163,831 | 90.033 s |

## 1. Admission order

The previous child path generated a legal successor, applied the corrected step cost, rejected `child_g > ceiling` before the move was applied, then applied best-g dominance. A new identity was counted, stored in `best_g`, and appended as a node before `proof_dead` ran. A state with `g + h` above the ceiling had already consumed one of the finite unique slots.

The path is now:

1. Generate the child and charge its corrected step cost. `child_g > ceiling` is still rejected before the action is applied. Those skips stay in `ceiling_prunes` and are not generated states.
2. A generated child is counted in `generated` before dominance and before the proof test. A proof-dead child remains visible in that counter.
3. An equal or worse `g` for an identity already in `best_g` is a duplicate skip. Dominance still applies only to a state that was admitted.
4. When a ceiling and a lower bound are both present, evaluate the bound. `g + h > ceiling` records a proof event and does not take a unique slot, a `best_g` entry, a node, an observer call, or a heap entry. `g + h == ceiling` stays eligible. The comparison is strict.
5. A new identity is admitted while `unique` is below the cap. The identity that brings `unique` up to the cap is stored and terminal-checked, then the search stops. A further new identity is not stored. This is the v0.129 cap-boundary rule.
6. A rejected identity is remembered only for telemetry. A later arrival with a smaller `g` is checked again and can be stored. There is no proof-dead cache keyed by state alone.

`lower_bound_prunes` counts every rejected arrival, including a repeat of an identity that was never retained. `proof_prune_identities` counts each such identity once, even if a cheaper arrival is stored later. `proof_prune_unretained` is the subset that is absent from `best_g` when the search stops.

A run with no lower bound, or with no ceiling, does not call the bound and does not proof-prune. Root insertion is unchanged: the root is always retained, and a proof-dead root is not pushed.

## 2. Safety

`admissible_remaining` is a lower bound on the corrected cost still required. Any completion through that child costs at least `child_g + h`. If that sum is above the ceiling, refusing to retain the child cannot delete a solution that meets the ceiling. A later path into the same identity can arrive with a smaller `g`. That arrival has to be tested on its own numbers, because the earlier rejection depended on the higher `g`. Writing the failed `g` into `best_g` would also be wrong: the cheaper arrival would then look like a dominated repeat, or the dead arrival would already have spent the unique slot. The failed arrival is not stored.

Terminal acceptance is unchanged. A solved state is stored only after it passes the same proof test. An admissible bound on a solved state is 0, so a solved state with `g <= ceiling` passes. Partial foundations and a heuristic score are not acceptance. Replay from the opening through `verify_complete_solution`, with eight foundations and the claimed cost, is the only acceptance gate.

Zero-cost whole-column transfers, unrestricted deal, ordered physical replay, and the stock-bearing identity split were not rewritten. Stock-bearing columns still use exact `pack_state` bytes. Empty-stock symmetry is still only a quotient of column order, and path reconstruction still replays the stored physical column order.

## 3. Tests

Focused kernel and endgame fixtures:

```text
$env:PYTHONPATH = "src"
py -3 -m pytest tests/test_proof_first_admission_v0_131.py tests/test_post_sd5_completion_v0_130.py tests/test_goal_directed_anchored_v0_129.py tests/test_search_kernel_consolidation_v0_57.py tests/test_human_strategy_v0_118.py -q --tb=line
```

56 passed in 3.43 s. The new file checks that a proof-dead child leaves the unique slot for a later candidate, that a rejected higher `g` does not block a cheaper arrival to the same identity, that equality with the ceiling is kept, that repeated dead arrivals count once per identity, that a terminal on the last retained slot is stored and replayable, that ordered and post-stock symmetry paths replay on the stored physical state, that stock-bearing columns stay distinct, that a missing bound and a zero bound search the same graph, and that a unique-cap stop is not a completed frontier. A seven-foundation position is not a solution. The v0.129 cap-boundary test and the v0.130 ceiling-equality test stayed green.

## 4. The matched search

One worker. Ceiling 171. Completion order `(g + h, h, -foundations, g)`, with `h = admissible_remaining`. Identity `pack_whole_game_identity`. Stored path `pack_state`. Caps: 80,000 retained identities, 90 seconds, 512 MB. The known 22-move suffix was replayed as an oracle and was not inserted into the frontier. Gate B and Gate D were not run.

Checkpoint 152 is the state after canonical action 151, the fifth deal. Recomputed: `g = 150`, stock 0, foundations 2, face-down 1, bonds 54, empty columns 0, 16 legal actions, no zero-cost action at the root, deal illegal. `admissible_remaining` and `stock_empty_assembly_h` are both 18. Slack to 171 is 3. The known suffix costs 22 and solves. Its slack against 172 reaches 0 during the suffix, which is why that suffix itself is not a ceiling-171 solution. `admissible_remaining` on the checkpoint took 0.187 ms. The full `completion_key` took 7.876 ms and was not used as the lane key.

| Fact | v0.130 Gate C | v0.131 Gate C |
| --- | ---: | ---: |
| Stop | unique limit | time limit |
| Solved | no | no |
| Negative proof | no | no |
| Expanded | 1,766 | 2,744 |
| Retained unique | 80,000 | 29,154 |
| Generated | 171,669 | 252,287 |
| Duplicate skips | 88,971 | 57,861 |
| Symmetry collapses | 82,177 | 115,412 |
| Stale pops | 20 | 33 |
| Ceiling prunes | 0 | 0 |
| Proof events | 56,394 | 163,831 |
| Proof identities | not recorded | 95,429 |
| Proof identities never retained | not recorded | 91,715 |
| Zero-cost actions | 13,577 | 19,722 |
| `g` expanded | 150–167 | 150–167 |
| `h` | 3–19 | 3–19 |
| `min f` | 168 | 168 |
| Foundations expanded | 2–5 | 2–5 |
| Elapsed | 52.089 s | 90.033 s |
| Peak RSS | 108.18 MB, inherited | 97.93 MB, this process |

Expansions match v0.130 through `g = 157` (298 states). From `g = 158` the retained frontier is larger, because states with `g + h > 171` are no longer sitting in the unique counter. v0.131 expansions by `g` are 1, 7, 17, 42, 55, 60, 60, 56, 132, 448, 596, 569, 392, 198, 75, 27, 8, 1 from 150 through 167. Generated children reach `g = 168` (184 children at that layer). Foundations expanded at 2, 3, 4, and 5 (1,099, 1,275, 348, and 22). Proof events sit at foundation counts 2, 3, 4, and 5 (45,540, 86,582, 29,414, and 2,295) and at `g` 159–168.

Of the 95,429 identities rejected at least once, 3,714 were stored later at a cheaper `g`. The telemetry set did not block that arrival. The other 91,715 were absent from `best_g` at the stop. The 163,831 proof events therefore include repeats.

`lower_bound_calls` was 194,427: the root plus every generated child that was not a duplicate of an admitted state. 163,831 of those child checks failed the ceiling. The rest were eligible and were subject to the unique cap and best-g rules.

The process working set peaked at 97.9296875 MB during this run. The v0.130 figure was the high-water of a process that had already run Gate B.

Both solution files were replayed before the search and hashed again afterwards.

| Route | SHA-256 | Explicit | Tableau | Deals | Foundations | Corrected MW | Legacy MW | Solved |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `solutions/4925153_canonical.moves` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | 174 | 169 | 5 | 8 | 172 | 163 | yes |
| `solutions/4925153_autonomous_185.moves` | `B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73` | 189 | 184 | 5 | 8 | 185 | 177 | yes |

The hashes were unchanged. `solutions/` was not written. The incumbent registry was not written. The 185 route was replayed and left unused. Its independent cold provenance is not established. No candidate reached eight foundations, so there is no experimental suffix to preserve.

## 5. Reproduction

From the repository root. The driver inserts `src` on its own path. It writes `artifacts/proof_first_v0_131/results.json` and does not write `solutions/`. `artifacts/` is gitignored.

```text
py -3 tools/proof_first_admission_v0_131.py
```

The run that produced this report ended:

```text
CHECKPOINT index=152 g=150 h=18 fd=1 legal=16 key_s=0.007876
DONE C stop=time limit solved=False g=None expanded=2744 unique=29154 generated=252287 dup=57861 symmetry=115412 ceiling_prunes=0 lb_prunes=163831 proof_ids=95429 proof_unretained=91715 zero=19722 max_f=5 elapsed=90.033 peak=97.9296875 proof=False outcome=inconclusive
OUTCOME inconclusive HASHES_OK True ACCEPTED False
```

## 6. Full suite

A bare `py -3 -m pytest tests` still stops during collection. Eight research modules import harnesses that are not on `PYTHONPATH`:

- `tests/test_exact_state_policy_context_equivalence_v0_1.py`
- `tests/test_one_shot_natural_empty_service_v0_1.py`
- `tests/test_one_shot_natural_r3_service_v0_1.py`
- `tests/test_workspace_opportunity_service_lane_v0_1.py`
- `tests/test_workspace_service_generalisation_panel_v0_1.py`
- `tests/test_workspace_service_lag1_grace_v0_1.py`
- `tests/test_workspace_service_stock_guard_v0_1.py`
- `tests/test_workspace_service_stock_synchronous_v0_1.py`

Those modules were not changed, and the import path was not patched.

The maintained regression is the file list in `docs/global_search_architecture_v0_124.md`, plus `tests/test_global_search_v0_125.py`, `tests/test_global_search_v0_126.py`, `tests/test_goal_directed_anchored_v0_129.py`, `tests/test_post_sd5_completion_v0_130.py`, and `tests/test_proof_first_admission_v0_131.py`. One run with `PYTHONPATH=src` collected 577 tests. All 577 passed in 239.80 seconds.

The historical full-suite failure was not reproduced in this run. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed inside the 577. v0.126 recorded that the same test can return `PLANNING_STALL` instead of `TIME_LIMIT` when the suite runs. That test and the Human Strategy Controller were not edited. This pass does not retire that timing sensitivity.

## 7. Scope left unchanged

`engine.py`, `rules.py`, the Human Strategy Controller, and the v0.120 timing test were not edited. The completion-order lane key was not replaced with the full `completion_key`. No second scheduler, no new heuristic, no longer exact-state window, and no suffix repair were added. The caps were not raised. Cold whole-game search was not run. Changing the tableau before SD5 was not started.
