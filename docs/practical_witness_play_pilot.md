# Deal 4925153 practical witness-play trial

## Question

Does choosing a replay-verified short plan as provisional guidance produce more actual game progress than the unchanged PR3 selector on deal 4925153 and its verified early positions, under matched limits?

The answer from this one run is no. All four nonduplicate roots tie. The verdict is **NO_CLEAR_BENEFIT**.

## What was frozen

Parent of the freeze commit: `ac5c0ac3215715ce41649e13dd3a5e2ce2972a24`.

Freeze commit, recorded before either arm: `69cf172f0221be01fcf97f36bf8018191eb7163e`.

Implementation commit, recorded before the official episodes: `f2356985dfc39e697f09c7b6d244f95e04ec0ed9`.

| File | SHA-256 |
| --- | --- |
| `deals/4925153.txt` | `C0B70979B3E6B90E266691DF956026629C890F49C12ED519801D6779434734DF` |
| `solutions/4925153_canonical.moves` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` |

The canonical file matches the repository's established hash. Independent full-game verification reports 172 corrected MobilityWare moves, 8 foundations, empty stock, and an empty tableau. The autonomous 185-move file was not used. The reference suffix after the third stock deal was discarded. Preparation on the official run took 0.420 seconds, inside the 30-second cap.

The four roots come from that replay. Prefix cost is the corrected sum, which is one below the command count on the warm roots because the shared prefix contains one zero-cost transfer.

| Root | Commands | Corrected cost | Stock | Hidden | Foundations | Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| opening | 0 | 0 | 50 | 44 | 0 | counts |
| after-deal-1 | 52 | 51 | 40 | 12 | 0 | counts; imported prefix |
| after-deal-2 | 90 | 89 | 30 | 8 | 0 | counts; imported prefix |
| after-deal-3 | 102 | 101 | 20 | 7 | 1 | counts; imported prefix |

The four packs differ, so none is a duplicate. The results remain correlated within one deal. Warm roots are imported verified prefixes, not cold solves.

## Policy that was fixed before the run

Both modes use the same rules, `all_legal_actions` (Deal included), PR3 order, eight probe slots, and the same episode allowance. Deal takes the eighth probe slot only when it is legal and outside the first eight. That is allocation, not a proof that an omitted move is impossible.

The short goal is two additional face-down reveals anywhere, or the last remaining face-down card. `reveal_phase_complete` is not a solved game. Each probe keeps the PR4 caps: 20 identities, 2 seconds, 512 MB, 4 corrected moves from the decision state, no depth cap, no harvest, no full-game lower bound, ordered `pack_state`, `stop_on_first_terminal=False`. An unfinished witness may be executed. It is a legal plan and its realised cost, not a minimum and not an admissible bound. UNKNOWN moves stay legal.

Episode allowance, from the authenticated root and not including the imported prefix: 60 seconds, 12 additional corrected moves, 64 primitive actions, 8 decisions, 1,280 probe identities, 512 MB, one worker. Roots run in manifest order. Even indexes run baseline then witness. Odd indexes run witness then baseline. One run each.

## Invocation

Working directory: the repository root. Interpreter: `py -3`. Tree clean at `f2356985dfc39e697f09c7b6d244f95e04ec0ed9`. One worker. No second launch.

```python
from spider.practical_witness_manifest import prepare_manifest
from spider.practical_witness_play import run_paired_trial

manifest = prepare_manifest()
run_paired_trial(
    manifest,
    confirm_official=True,
    freeze_sha="69cf172f0221be01fcf97f36bf8018191eb7163e",
    implementation_sha="f2356985dfc39e697f09c7b6d244f95e04ec0ed9",
)
```

The call uses the default `EpisodeBudget`. Traces are `docs/practical_witness_play_pilot.json`. `tests/test_practical_witness_play_lock.py` replays every saved action from the opening and does not call the episode driver.

## Results

Checks passed. No illegal step, pack mismatch, or false certainty flag. `independent_cold_complete` is false on every episode. No episode solved. Windows `process_time` advances in 15.625 ms steps, so the CPU figures are coarse.

The executed action lists are identical across modes on every root. Witness mode never selected a different move from the baseline fallback or from the baseline candidate's own witness.

| Root | Stop | Paid | Primitives | Decisions | Probe ids | Foundations | Hidden | Stock | Goals | Baseline wall / CPU (s) | Witness wall / CPU (s) |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |
| opening | paid-moves | 12 | 12 | 7 | 815 | 0 → 0 | 44 → 33 | 50 | 5 | 1.29 / 1.25 | 1.348 / 1.203 |
| after-deal-1 | repeated-state | 3 | 3 | 4 | 640 | 0 → 0 | 12 → 12 | 40 | 0 | 0.719 / 0.719 | 0.888 / 0.875 |
| after-deal-2 | repeated-state | 2 | 3 | 4 | 640 | 0 → 1 | 8 → 8 | 30 | 0 | 1.333 / 1.297 | 1.297 / 1.281 |
| after-deal-3 | repeated-state | 3 | 3 | 4 | 640 | 1 → 1 | 7 → 7 | 20 | 0 | 0.709 / 0.719 | 0.763 / 0.766 |

Opening baseline seconds were 0.396 and 0.371, continuation 0.333 and 0.433, overhead 0.56 and 0.543. The warm roots spent roughly 0.15–0.69 s in portfolio construction, 0.15–0.23 s in continuation search, and the rest in overhead. The 60-second, 1,280-identity, and 512 MB caps did not bind. RSS at admission time was about 29 MB.

On the opening, both modes executed five upper-unfinished witnesses. In each of those decisions the cheapest verified plan was already the first PR3 candidate, so witness mode's preference and baseline mode's own-witness rule played the same plan. Two later decisions had no verified witness and both played that candidate's single action. Eleven reveals occurred by paid 11. The twelfth paid move revealed nothing. Hidden ended at 33. Stock stayed 50. Deal was legal and probed on all seven decisions, and was reserved into the eighth slot on two of them. Neither arm dealt.

On the three warm roots every probed candidate was `unknown`. Both modes played the same single-action fallback. Deal was legal, probed, and reserved when it sat outside the first eight. Neither arm dealt, and no face-down card was revealed. Each episode stopped when the next action would revisit an ordered state at an equal or higher episode cost. After the second deal, the shared line also completed one foundation (the opening move of that line moves 12 cards) and included one zero-cost transfer, which is why paid moves are 2 while primitive actions are 3. That foundation gain is shared, so it is not a win for either arm.

Progress comparison is foundations and hidden cards, with a solved game outranking an incomplete one. Stock alone is ignored. All four pairs are ties. Observed trajectory cost at every shared reveal count is equal as well: the opening matches at 0 through 11 reveals, and the warm roots share only the zero-reveal point. Those costs are observed, not optimal. Different endpoints would not have been a shorter solution; these endpoints are the same.

No candidate or selection is marked as a full-game optimum. Upper-unfinished choices keep `admissible_bound` false.

## Verdict

**NO_CLEAR_BENEFIT.** Witness mode has zero progress wins. Baseline dominates zero roots. The pattern is four ties caused by identical legal play, including capped probes and repeated-state stops. This is within-deal evidence only. It does not generalise, does not show that a divergent endpoint would remain finishable, and does not change the verified 172-move complete route.

Recommendation: leave the probe caps, budgets, and selector unchanged.

## Tests

Focused mechanism tests were committed in `f235698` before the episodes. They do not call `run_paired_trial`. The lock test replays the saved JSON.

Regression, run once after the episodes, from the repository root:

`py -3 -m pytest` with `-q --tb=line -p no:cacheprovider` on the 53-file parent selection plus the three new files (56 files).

Result of this run: **731 passed, 0 failed, 287.02 s**.

The 53-file list is the section-19 command in `docs/strategic_continuity_v0_123.md` (31 files through `tests/test_human_strategy_v0_123.py`) plus `tests/test_global_search_v0_124.py`, `tests/test_global_search_v0_125.py`, `tests/test_global_search_v0_126.py`, the v0.129–v0.139 files named in the maintained set, `tests/test_dependency_options_two_stage.py`, `tests/test_dependency_options_offline_audit_pr2.py`, `tests/test_dependency_contract_continuity_pr3.py`, `tests/test_dependency_objective_lookahead_pr4.py`, `tests/test_dependency_objective_panel_pr4.py`, `tests/test_dependency_objective_reserved_pr4.py`, `tests/test_dependency_objective_inventory.py`, and `tests/test_dependency_objective_inventory_lock.py`. The three added files are `tests/test_practical_witness_manifest.py`, `tests/test_practical_witness_play.py`, and `tests/test_practical_witness_play_lock.py`.

This is not the whole suite. Bare `pytest tests` was not run. The PR4 and inventory outcomes were not rerun to change their locks; those lock tests passed inside this selection.

Separate historical reports, not this run: at `1a56107` the 51-file selection was 703 passed / 0 failed / 281.24 s. At `ac5c0ac` the 53-file selection was 709 passed / 0 failed / 249.06 s.

Issue #6 remains disclosed. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` passed in this 56-file run. In heavier runs it can return `PLANNING_STALL` instead of `TIME_LIMIT`. The test was not weakened.

The eight historical collection modules still fail to import. With `PYTHONPATH=src` and `-p no:cacheprovider` they reported 8 errors in 5.15 s. They were not edited. The missing service modules named in the PR3 note remain absent.

## Files in this trial

- `src/spider/practical_witness_manifest.py`
- `tests/test_practical_witness_manifest.py`
- `src/spider/practical_witness_play.py`
- `tests/test_practical_witness_play.py`
- `docs/practical_witness_play_pilot.json`
- `docs/practical_witness_play_pilot.md`
- `tests/test_practical_witness_play_lock.py`

Engine, rules, costs, identity, the search kernel, production controllers, the PR3 selector, the PR4 evaluator and panel, the inventory validation, and the solution files are unchanged.

## Limitations

The four roots share one deal, and three start from an imported canonical prefix. A warm-root episode is not an independent cold solve. The 12-move allowance cannot finish the game from these positions. Identical play means this run did not separate the two selectors: where a witness existed, it belonged to the baseline's first candidate; elsewhere there was no verified witness to prefer. Unprobed and UNKNOWN moves were not treated as impossible. Nothing here authorises a higher probe cap, a retune, a learned model, or a follow-on experiment.
