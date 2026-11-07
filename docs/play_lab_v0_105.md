# Spider Play Lab v0.105 — unattended optimiser

Play Lab keeps manual play, replay, and named branch campaigns. The new Optimise tab runs the compact suffix-assisted solver against deal 4925153, starting from the accepted 140-move game.

The seed route is `docs/research/pre120_optimisation/4925153_assisted_140.moves`, action hash `34a94de8e6edfa4b`. The incumbent starts at 140 and the ceiling at 139. Historical 164, 162, 160, 158 and the pinned 157 game remain suffix sources. They are not search roots.

## Launch on the ThinkCentre

Keep the whole folder together. Python and Git are not required.

```
dist\v0.105\SpiderPlayLab\SpiderPlayLab.exe
```

Open the Optimise tab. The release uses one worker. Set the campaign minutes, the per-attempt seconds, the identity cap, and the requested RSS. The tab shows the requested cap and the effective cap after the existing clamp: the request, 8 GiB, and 40 percent of available RAM. The identity cap is not raised above 2,000,000. Planning uses 1,300 bytes per retained state, from the measured compact-kernel peak of 2,341.6 MB at 2,000,000 identities.

Start begins a campaign. Pause lets the current attempt finish and then waits. Resume continues with the next distinct job. Stop ends the worker. An unfinished attempt is recorded as stopped or interrupted. It is not an exhaustion claim. A later attempt with that prefix starts again from the saved authenticated prefix, because the exact frontier is not retained.

Open verified best loads the current best through the existing replay session. Named branch campaigns and earlier history nodes stay in the session. This release optimises deal 4925153 only.

Campaign files, including the queue, attempt records, and any newly verified games, are stored in:

```
%LOCALAPPDATA%\SpiderSolver\PlayLab\Optimiser\4925153
```

The older `dist\SpiderPlayLab` and `dist\v0.104` folders are left in place.

## What the controller records

A job is identified by the physical pack, accumulated corrected cost, route and prefix hash, MobilityWare rules, absolute ceiling, and the compact configuration (time limit, effective RSS, identity cap, one worker, advice off). The first roots are action 100 and action 90 of the current best route when their admissible f is within the ceiling. Other pre-120 roots are added when they are still useful. Action 120 and later prefixes stay closed.

A stop reason of `complete` is an exhaustion claim for that exact prefix, pack, cost, rules, and ceiling, and for any tighter ceiling on the same state. Time, identity, and memory caps are not exhaustion. The same capped configuration is not queued again. A stopped or interrupted job is not queued again under the identical configuration. A different budget may try the same prefix, and the record says the new attempt restarts from the saved prefix.

A cheaper game is replayed from the original opening and written before the attempt ledger is closed. The campaign then lowers the incumbent and the ceiling and drops queued jobs so the next choice uses the new route. No cheaper game is required for the controller to be doing its job.

Manual named branch campaigns stay in the Play Lab session. They are not optimiser jobs.

## Packaged runtime

Source checkouts still authenticate the pinned 157 game and the 140 seed with Git blob ids, then replay them and check the action hashes. The frozen executable does not call Git. It checks `resources/play_lab_manifest.json` against the bundled deal and routes, then performs the same replay and hash validation. Solver source hashes in a package are taken from the bundled files.

PyInstaller 6 stores those files under `_internal`. Deal validation uses that bundle directory. A path built from `Path(__file__).parents[2]` points at the folder beside the executable, which does not contain the deal.

`SpiderPlayLab.exe --verify-packaged` replays the bundled 140 game and exits without opening the window. A windowed launch has no console, so a missing standard stream does not turn a successful replay into a crash.

## Validation

Scheduler, exhaustion, adoption, resource clamp, manifest replay, and session preservation:

```
python -m pytest -q tests/test_unattended_optimiser.py tests/test_incumbent_suffix.py tests/test_play_lab_v0_104.py tests/test_play_session.py tests/test_solution_archive.py tests/test_canonical_moves.py
```

Results from this workspace:

- `tests/test_unattended_optimiser.py`: 9 passed.
- `tests/test_incumbent_suffix.py`: 16 passed. The direct-terminal publish path did not change the existing ledger assertions.
- `tests/test_play_lab_v0_104.py`, `tests/test_play_session.py`, `tests/test_solution_archive.py`, and `tests/test_canonical_moves.py`: 103 passed, including the new Optimise responsiveness case.
- After the bundle-root fix, `tests/test_solution_archive.py`, `tests/test_canonical_moves.py`, `tests/test_unattended_optimiser.py`, and `tests/test_incumbent_suffix.py` passed together: 76 tests. The Optimise responsiveness test passed again on its own.
- The bounded campaign below selected action 100, paused, skipped that identical cap, started action 90 by itself, and was then stopped. Research `status.json` was unchanged.

A short acceptance campaign under `%LOCALAPPDATA%\SpiderSolver\PlayLab\Optimiser\4925153-acceptance` used a 40-identity cap and a 5-second attempt limit. It authenticated hash `34a94de8e6edfa4b`, queued actions 100 (f=132) and 90 (f=126), skipped action 119 because f=140 is above ceiling 139, paused after action 100 stopped on the identity cap, refused to repeat that cap, and started action 90. Stopping that job recorded: the exact frontier was not retained, a later attempt starts from the saved prefix, and the job is not exhausted. The best remained the seed 140 game. Requested RSS was 3,000 MB. On this host the effective cap was about 2,968 MB, with one worker.

Known baseline failures were not re-run and were not weakened:

- `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` instead of `TIME_LIMIT`.
- Eight historical collection failures remain in the exact-state and workspace-service v0.1 modules.

The first packaged `--verify-packaged` run, from a directory that is not a Git checkout, exited 1. Validation looked for `deals\4925153.txt` beside the executable. The rebuilt executable, started from `C:\Users\Codex\AppData\Local\Temp`, printed `PACKAGED_SEED_OK hash=34a94de8e6edfa4b g=140 routes=6 runtime=packaged` and exited 0.

The packaged window was started from that same directory. Its title was Spider Play Lab v0.105, the process was responding, and it was then closed. The Optimise buttons were exercised in the source GUI test. They were not clicked inside the frozen window.

A frozen supervisor started outside the checkout authenticated hash `34a94de8e6edfa4b` with `git_used` false. It queued actions 100 and 90, skipped action 119, and did not repeat an identical cap. With a 25-identity cap it ran the queued roots by itself. Action 116 finished with stop `complete` at 21 identities and recorded that exact prefix, pack, cost, rules, and ceiling. The other stops were identity caps, not exhaustion. A second frozen run requested 512 MB. The effective cap stayed 512 MB and the identity budget fell to 412,977 because of the 1,300-byte retained-state estimate. Pause waited until action 100 hit its time limit, skipped that same cap, and started action 90. Killing that process and opening the supervisor again recorded action 90 as interrupted, with the frontier text, and `exhausted` false. The best remained the seed 140 game. Research `status.json` was unchanged. `dist\v0.104` and `dist\SpiderPlayLab` were still present.
