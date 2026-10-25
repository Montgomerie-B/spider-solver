# Incumbent-anchored optimisation v0.118

Schema `spider-human-strategy-0.118`. Branch `local/incumbent-anchored-v0-118`. HEAD `65e7ab2b3588ddb69704136c91f6fc354e22e274` (`Add verified solve and optimise pipeline v0.117`). The v0.118 edits are uncommitted.

The v0.117 pipeline still verifies a complete route, keeps it as the incumbent, and prunes only when `g + admissible_remaining >= ceiling`. This release adds a second optimisation approach: replay that route into exact checkpoints, and search for a strictly cheaper corrected-MobilityWare path between two of them. On an exact column-ordered rejoin the original suffix stays. The full game is replayed before the experimental incumbent moves. Cold mode and solve mode do not load the route.

Deal 4925153 still has best verified complete cost **185** from the imported autonomous file, and **172** when that human file is supplied on its own. Neither anchored pilot found a cheaper rejoin. A constructed board did: a verified cost-3 route was replaced by a replayed cost-1 route.

## Files

Tracked edits, 211 insertions and 27 deletions:

- `src/spider/human_strategy/__init__.py` — schema `spider-human-strategy-0.118`
- `src/spider/human_strategy/controller.py` — component timers, incumbent-prune and resource-limit records, provenance
- `src/spider/human_strategy/strategic_frontier.py` — per-exclusion log
- `tools/human_strategy_solver.py` — `--mode anchored`
- `tests/test_human_strategy_v0_117.py` — expected schema string updated to 0.118

New files:

- `src/spider/human_strategy/anchored.py`
- `tests/test_human_strategy_v0_118.py`
- this note

`engine.py`, `rules.py`, corrected scoring, `solutions/`, `registry.py`, and Play Lab were not modified. No commit, push, merge, or pull request was made.

Existing modes remain: `cold`, `solve`, `optimise`, `solve-optimise`, `diagnose`. `anchored` is additive. `cold` and `solve` still reject an incumbent file. `optimise_anchored(..., mode="cold")` raises `AnchoredRefused`.

## Search throughput

A 40-second global optimise of deal 4925153 under the verified 185 ceiling, pilot frontier 8, one worker, goal `foundations` target 8. Measured in `artifacts/human_strategy/v0_118/experiment_a_global.json`.

| Bucket | Seconds |
| --- | --- |
| Foundation proposals, including excavation | 37.044 |
| Candidate generation | 0.485 |
| Deal-versus-prepare comparison | 0.187 |
| Tactical objective realisation | 0.142 |
| Admissible bound evaluation | 0.005 |
| Solve elapsed | 40.195 |

Foundation proposals are the run. The other named buckets together are under one second. About 2.3 seconds are loop overhead, cloning, and the final replay check.

| Counter | Value |
| --- | --- |
| Strategic states evaluated | 85 |
| Unique strategic states | 68 |
| Bounds evaluated | 108 |
| Safe incumbent prunes | 0 |
| Heuristic frontier exclusions | 10 |
| Candidate-cache hits / misses | 7 / 61 |
| Excavation hits / misses | 2 / 34 |
| Excavation nodes | 2859 |
| Excavation inconclusive probes | 20 |
| Played actions / corrected g | 53 / 53 |
| Foundations on that partial | 1 |
| `SEARCH_STATUS` | `TIME_LIMIT` |
| `resource_stops` | 1 |
| `BEST_VERIFIED` | 185 |
| `IMPROVED` | false |
| Peak RSS | 62.59 MB |

`unique_states` is the strategic canonical-key table. It does not count the 2859 excavation nodes. Those live inside foundation proposals.

The excavation cache recorded 2 hits and 34 misses, with 0 revisits. The probes are mostly different keys, so the time is many distinct buried-card searches, and the cache is already avoiding the identical ones it can see. This release leaves that probe behaviour in place.

### Why a full budget can say `PLANNING_STALL`

`TIME_LIMIT` is written when the controller loop header, or the play-goal kernel, observes the deadline. This 40-second run did that. Stop text: `time budget ended before a solved terminal`. `deadline_elapsed` is true.

`PLANNING_STALL` is a different exit, already used by the v0.117 150-second pilot. The strategic policy calls `strategic_stop_status` while legal tableau moves remain. `_continue_from_frontier` then refuses another line once fewer than 0.05 seconds remain, and the status stays `PLANNING_STALL`. The header never gets another iteration in which to record `TIME_LIMIT`. That sequence is the existing stop rule. `resource_stops` stays 0 for `PLANNING_STALL` because that token is not a budget status. A partial line produced by either stop is still a partial line. The verified 185 stays the best complete route.

## Checkpoints

`build_checkpoints` replays the verified actions on a clone. Index 0 is the opening. Index `k` is the position after `k` actions. Each checkpoint stores:

| Field | Meaning |
| --- | --- |
| `index` | Actions already applied |
| `g` | Exact corrected MobilityWare total |
| `stock_cards`, `stock_rows` | Stock still held |
| `foundations` | Completed foundations |
| `face_down` | Tableau face-down count |
| `empty_columns` | Empty columns |
| `bonds` | Same-suit bonds |
| `admissible_remaining` | Whole-game proof bound at that position. Ordering and diagnostics. The segment search uses its own bound |
| `state_id` | First 16 hex digits of ordered `pack_state` |
| `state`, `key` | Private clone and `canonical_state_key`. Omitted from the public JSON |

The 185 file produces 190 checkpoints, final `g=185`, 8 foundations, empty stock. The 172 file produces 175 checkpoints, final `g=172`. Every checkpoint `g` on the 185 replay matches a fresh `apply_action` total. Neither solution file was rewritten.

## Rejoining

A suffix may be kept only when the replacement ends on the same physical state as the incumbent checkpoint.

`states_rejoin` is `canonical_state_key` equality:

- Tableau columns stay in physical order 0..9. Face-down order and face-up order are part of the column.
- Stock order is the deal order.
- Foundations are a multiset of sequences. Completion order is not distinguished.
- Two cards of the same suit and rank are not separate objects in this key.

`pack_state` is the search identity. It is the same column order. `pack_post_stock_symmetry_state` sorts columns and is not used. On the micro board, moving the lone king onto an empty column and swapping that column with another empty column leaves the symmetry pack unchanged and changes both `pack_state` and `states_rejoin`. An unchanged suffix is refused there, because the suffix names physical columns.

Stock that cannot be turned into the target stock by dealing whole rows from the end is unreachable (`segment_lower_bound` is `None`). A foundation multiset that is not a subset of the target is unreachable. A deal count, when the stock prefix matches, is an admissible extra cost. Face-down reveals and future foundation removals are not added: one action can reveal more than one card and finish a suit, and a whole-column transfer onto an empty column can cost 0. Summing those obligations would be inadmissible.

The whole-game bound is unchanged. `admissible_remaining` is still remaining deals plus `ceil(residual face-down / 2)` after crediting up to 10 reveals per deal, and `stock_empty_assembly_h` only when the stock is empty. At the positions this global policy reaches, that total sits far under 172 and 185, which is why the global gate records 0 prunes. No stronger whole-game proof bound is added in this release.

## Windows and the segment search

`select_windows` builds an ordered list, capped at 16 by default:

1. Exact returns to an earlier checkpoint, shortest positive-cost cycle first. The replacement is the empty path. The 185 and 172 replays have none (190 and 175 distinct keys).
2. Up to 6 non-overlapping reversal windows. A reversal is a segment that contains a move and its inverse column transfer.
3. Up to 3 between-foundation windows of span 4..10, shortest first.
4. Remaining slots: non-overlapping low-change or paid-run windows, shorter spans first.

Skipped windows are a screen. A skipped window is not proved optimal.

For a segment of incumbent cost `C`, the search accepts only a path with corrected cost `< C`. The existing kernel runs with `cost_ceiling = C - 1`, identity `pack_state`, actions from `enumerate_legal_actions` (deals included), and uniform-cost order so a zero-cost whole-column transfer is expanded before a cost-1 edge of equal ancestry. `g + segment_lower_bound > C - 1` prunes. A finished graph with no hit is `EXHAUSTED` and is a negative result only inside that ceiling. `time limit`, `unique limit`, and `rss abort` are `INCONCLUSIVE` and are not proofs. Default caps are 4 seconds (10 seconds when `C >= 4` or the window sits between foundations), 2500 unique states, and 3072 MB.

On `FOUND`, the splice is `prefix + replacement + incumbent suffix`. It is kept only when:

1. The replacement replays from the source checkpoint onto the target checkpoint at the searched cost.
2. `verify_complete_solution` replays the whole splice from the opening to eight foundations, empty stock, and a solved board.
3. The corrected total is strictly less than the current verified cost.

Anything else leaves the previous route in place. The production registry is not written. After a kept improvement the checkpoints are rebuilt and another round may run, up to six improvements. Provenance `approach` is `anchored`. `global_search` is false. `cold_injection` is false. `incumbent_source` stays `imported` until a cheaper full replay exists, and then becomes `discovered`.

Global `optimise` is unchanged: it starts at move 0, does not inject the incumbent actions, and still uses `admissible_remaining` against the numeric ceiling. Its provenance `approach` is `global` and `anchored_used` is false.

## Frontier exclusions

Each global refusal is logged with the objective, parent-state id, corrected `g`, strategic priority, and whether an equivalent physical state is already queued or expanded. The successor state is absent, because the objective has not been played.

On the 40-second run, 10 records, all `heuristic_admission`, all `proof: false`. Seven already had the same physical state retained under another line. That is capacity, not a proof that the omitted objective cannot beat 185. The frontier width stays 8. Transposition dominance, when it happens, is logged separately with `proof: true` because the cheaper ancestry of that same state is the one kept. Incumbent prunes and a deadline with queued lines still unstarted are logged as `incumbent_prune` and `resource_limitation`. This run had neither of those two kinds; the clock was recorded as `TIME_LIMIT` at the header, with `resource_stops` 1.

## Experiment E — constructed improvement

Board: column 0 holds Qh–Ah, column 1 holds Kh, seven foundations already out, stock empty. The imported route is the four-action detour of corrected cost 3. It does not repeat a checkpoint. Anchored search replaced actions 0..3, segment cost 2, with the zero-cost king transfer `(1, 2, 1)`. The incumbent suffix `(0, 2, 12)` was kept. Independent replay cost is 1, eight foundations, solved.

| Field | Value |
| --- | --- |
| Before | 3, imported |
| After | 1, discovered |
| `IMPROVED` | true |
| `SEARCH_STATUS` | `IMPROVED` |
| Window | reversal, indices 0–3, ceiling 2, replacement cost 0 |
| Expansions | 1 |
| Elapsed | 0.021 s |
| Peak RSS | 27.25 MB |

The unit suite also cuts a different waste route from 5 to 3 and then from 3 to 1 by deleting two exact cycles, one per round. Equal cost and a more expensive splice do not replace the route. A zero-time call keeps the previous verified cost and reports `TIME_LIMIT`.

## Experiment B — anchored MW 185

`solutions/4925153_autonomous_185.moves`, verified at cost 185, then 16 windows inside a 150-second allowance. The windows finished in 6.780 s. Peak RSS 33.25 MB. Source id is that 185 file. The 172 file was not an input.

`BEST_VERIFIED=185`. `IMPROVED=false`. `SEARCH_STATUS=NO_IMPROVEMENT`. `INCUMBENT_SOURCE=imported`. Rejoins 0. Expansions 2346. Segment-bound prunes 523. Checkpoints 190.

| Window | Cost | Status | Expanded | Unique | Bound prunes | Proof inside the ceiling |
| --- | --- | --- | --- | --- | --- | --- |
| reversal 130–134 | 4 | `EXHAUSTED` | 180 | 245 | 65 | yes |
| reversal 138–142 | 4 | `EXHAUSTED` | 97 | 97 | 0 | yes |
| reversal 3–8 | 5 | `EXHAUSTED` | 640 | 850 | 210 | yes |
| reversal 97–102 | 5 | `EXHAUSTED` | 993 | 1220 | 227 | yes |
| reversal 65–73 | 8 | `INCONCLUSIVE` | 164 | 2500 | 13 | no, unique cap |
| between foundations 183–187 | 4 | `INCONCLUSIVE` | 36 | 2500 | 0 | no, unique cap |
| between foundations 177–182 | 5 | `INCONCLUSIVE` | 83 | 2500 | 0 | no, unique cap |
| between foundations 168–177 | 9 | `INCONCLUSIVE` | 80 | 2500 | 0 | no, unique cap |
| paid runs 0–2 through 12–14 | 2 | `EXHAUSTED` | 6–11 each | 7–12 | 1 each | yes |
| low-change 14–16 | 2 | `EXHAUSTED` | 12 | 13 | 1 | yes |

Twelve windows are negative results for a strict local improvement. Four are unfinished. The best verified complete solution after the run is still the imported 185.

## Experiment C — anchored MW 172

Separate process. `solutions/4925153_canonical.moves` only. Verified at 172. 175 checkpoints. 6.555 s of a 150-second allowance. Peak RSS 33.06 MB.

`BEST_VERIFIED=172`. `IMPROVED=false`. `SEARCH_STATUS=NO_IMPROVEMENT`. `INCUMBENT_SOURCE=imported`. Rejoins 0. Expansions 1809. Segment-bound prunes 704. Eleven windows `EXHAUSTED`, five `INCONCLUSIVE` at the 2500 unique cap (reversals at 146–149, 165–168, 20–24, and 76–80, and the between-foundation window 160–170 of cost 10). These figures are not mixed into the 185 run. The 172 route was not written over the 185 baseline.

## Global comparison

The 40-second global run and the anchored runs do not explore the same state space.

| | Global, 40 s, ceiling 185 | Anchored 185 |
| --- | --- | --- |
| Start | Opening, no action prefix | Checkpoints of the verified route |
| Best verified complete cost | 185 | 185 |
| Improved | false | false |
| Status | `TIME_LIMIT` | `NO_IMPROVEMENT` |
| Safe whole-game prunes | 0 | 0 (this mode uses the segment ceiling) |
| Segment-bound prunes | — | 523 |
| Heuristic exclusions | 10 | 0 (no strategic frontier) |
| States | 85 strategic evaluations, 68 unique keys, 2859 excavation nodes | 2346 segment expansions |
| Elapsed / RSS | 40.195 s / 62.59 MB | 6.780 s / 33.25 MB |
| Partial reported | 53 actions, g=53, 1 foundation | The retained complete 185. `solved` true because that route replays |

The global ceiling did not prune. The segment ceilings did: short paid pairs died in about ten expansions, and four longer reversals ran to completion under their own `C`. That is the search reduction this release can claim. It is a reduction inside chosen segments of one known solution. It is not a proof that 185 is optimal, and it is not the same tree as the multi-line controller.

## Tests, runtime, memory

`tests/test_human_strategy_v0_118.py` has 10 tests. They cover checkpoint costs on the 185 replay, source and target identity, column permutation versus the symmetry pack, stock and foundation refusal, the cost-3 to cost-1 rejoin, equal and worse rejection, zero-cost transfers, full-game verification, an invalid candidate leaving the route unchanged, two successive improvements, the segment ceiling, an inconclusive zero-time window, cold refusal, both provenance labels, segment transposition, frontier exclusion kinds, and a CLI timeout that prints `BEST_VERIFIED=185` / `IMPROVED=false` / `SEARCH_STATUS=TIME_LIMIT` without touching the registry or the 185 file.

The regression command below passed **410 tests in 290.24 s**, exit 0. That is the previous 400 plus these 10.

| Run | Elapsed | Peak RSS | Result |
| --- | --- | --- | --- |
| Global optimise | 40.195 s | 62.59 MB | 185 kept, partial g=53, `TIME_LIMIT` |
| Anchored 185 | 6.780 s | 33.25 MB | 185 kept, 12 segments exhausted, 4 inconclusive |
| Anchored 172 | 6.555 s | 33.06 MB | 172 kept, separate run |
| Micro rejoin | 0.021 s | 27.25 MB | 3 replaced by 1 |
| Regression | 290.24 s | not a search RSS | 410 passed |

One worker. No run approached 3072 MB. The anchored pilots returned before the 150-second allowance because the selected windows finished.

## Limitations

The anchored pilots did not produce a complete route cheaper than 185, or cheaper than 172. Twelve 185 segments are locally settled under their ceilings. The four inconclusive windows, including the stock-empty endgame spans, stopped at 2500 unique states. A higher cap there might finish the proof or find a rejoin. It has not been run.

Many cheaper complete games, if they exist, never rejoin an incumbent checkpoint. Global search is still required for those. On this policy it spends almost all of its time in foundation excavation, and the whole-game bound does not yet reach the 185 ceiling, so the incumbent is carried and not used as a global prune.

`PLANNING_STALL` and a full frontier remain non-proofs. `EXHAUSTED` on a segment is a proof only below that segment's `C`.

No cold solution of deal 4925153 was produced. The stored 185 and 172 routes were imported and labelled imported. The 119-move benchmark was not attempted.

## What v0.119 should measure

Judge the next change by a verified complete cost, or by a segment that moves from `INCONCLUSIVE` to a finished proof.

The global lever is the foundation-proposal loop: 37 seconds of a 40-second run, 34 excavation misses, 20 of them inconclusive. A cheaper or more widely reusable probe would move the strategic search. Widening the frontier from 8 to 32 would change the 10 heuristic exclusions, seven of which already keep the same physical state, and would not be a proof.

The anchored lever is the stock-empty endgame windows on the 185 route (indices 168–177, 177–182, 183–187) and the cost-8 reversal at 65–73. They hit the unique cap while the short paid pairs did not. Raising that cap, still with the segment ceiling, is a bounded experiment. Cold mode should keep refusing both solution files.

## Reproduce

From `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`:

```text
py -3 -m pytest tests/test_human_strategy_v0_110.py tests/test_human_strategy_v0_109.py tests/test_human_strategy_v0_108.py tests/test_human_strategy_v0_107.py tests/test_counterfactual_continuations_v0_106.py tests/test_rules.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_4925153_move_accounting_audit.py tests/test_deal.py tests/test_same_suit_block_legality.py tests/test_state_identity.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_forensics_v0_105.py tests/test_search_kernel_consolidation_v0_57.py tests/test_play_session.py tests/test_play_lab_v0_104.py tests/test_human_strategy_v0_111.py tests/test_foundation_campaign_realizer.py tests/test_human_strategy_v0_112.py tests/test_human_strategy_v0_113.py tests/test_human_strategy_v0_114.py tests/test_human_strategy_v0_115.py tests/test_human_strategy_v0_116.py tests/test_human_strategy_v0_117.py tests/test_human_strategy_v0_118.py -q --tb=line
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot --goal foundations --target-foundations 8 --time-limit 40 --frontier 8 --proposals 3 --slice 24 --line-attempts 48 --workers 1 --no-portfolio --max-steps 220 --memory-mb 3072 --out artifacts/human_strategy/v0_118/experiment_a_global.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_autonomous_185.moves --profile pilot --time-limit 150 --workers 1 --memory-mb 3072 --out artifacts/human_strategy/v0_118/experiment_b_anchored_185.json
```

```text
py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode anchored --incumbent solutions/4925153_canonical.moves --profile pilot --time-limit 150 --workers 1 --memory-mb 3072 --out artifacts/human_strategy/v0_118/experiment_c_anchored_172.json
```

Experiment E is `optimise_anchored` on the constructed board in `tests/test_human_strategy_v0_118.py`. Measured JSON is `artifacts/human_strategy/v0_118/experiment_e_micro.json`. That directory is gitignored.

## Branch, HEAD, and status

Branch `local/incumbent-anchored-v0-118`. HEAD `65e7ab2b3588ddb69704136c91f6fc354e22e274`. The v0.118 edits are uncommitted.

```text
 M src/spider/human_strategy/__init__.py
 M src/spider/human_strategy/controller.py
 M src/spider/human_strategy/strategic_frontier.py
 M tests/test_human_strategy_v0_117.py
 M tools/human_strategy_solver.py
?? docs/incumbent_anchored_optimisation_v0_118.md
?? src/spider/human_strategy/anchored.py
?? tests/test_human_strategy_v0_118.py
```

`engine.py`, `rules.py`, `registry.py`, and the files under `solutions/` are absent from the status. No commit, push, merge, or pull request was made.
