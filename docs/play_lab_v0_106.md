# Spider Play Lab v0.106 — controller corrections

v0.106 keeps the v0.105 Optimise tab and corrects how a restarted campaign, an exhaustion record, and a time budget are stored. The seed route is still `docs/research/pre120_optimisation/4925153_assisted_140.moves`, action hash `34a94de8e6edfa4b`. The incumbent starts at 140 and the ceiling at 139. Historical 164, 162, 160, 158 and the pinned 157 game remain suffix sources.

`dist\v0.104`, `dist\v0.105`, and `dist\SpiderPlayLab` were left in place. This package is a separate folder.

## Launch on the ThinkCentre

Copy the whole `SpiderPlayLab` folder. The executable needs the `_internal` directory beside it. Python and Git are not required.

```
dist\v0.106\SpiderPlayLab\SpiderPlayLab.exe
```

On this machine the built executable is:

```
C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103\dist\v0.106\SpiderPlayLab\SpiderPlayLab.exe
```

Open the Optimise tab. Unlimited widening is on. Start keeps searching prefixes of the verified best route, under that route's cost, with no campaign clock and no per-attempt time limit. Actions 100 and 90 are first. Later prefixes widen from the tightest admissible score downward. A finished frontier is not searched again at that ceiling. A memory stop is not exhaustion: the next prefix starts. One worker. The RSS spinbox is the safety cap. It is still clamped to the request, 8 GiB, and 40 percent of available RAM. The state count for one prefix is however many 1,300-byte states fit in that RSS. When a caller omits the identity count outside this mode, the library budget remains 2,000,000.

Turn Unlimited off for a bounded run. Those spinboxes still open at 360 minutes, 7,200 seconds, and 6,607,641 identities. `SPIDER_PLAY_LAB_UNLIMITED=0` selects that bounded launch. The other overrides are `SPIDER_PLAY_LAB_DURATION_MIN`, `SPIDER_PLAY_LAB_ATTEMPT_S`, `SPIDER_PLAY_LAB_MAX_UNIQUE`, and `SPIDER_PLAY_LAB_RSS_MB`.

Campaign files stay in `%LOCALAPPDATA%\SpiderSolver\PlayLab\Optimiser\4925153` unless `SPIDER_PLAY_LAB_OPTIMISER_DIR` is set. A long run previously died while the window was reading `state.json`: Windows returned access denied on the snapshot replace, and that error was recorded as a failed job and then as a failed supervisor. The replace is retried, readers share the file for delete, and a snapshot that still cannot be written does not stop the search. The same six test modules passed 140 tests after this change. The known baseline failures were not re-run.

## What changed in the controller

A restart replays every saved `4925153_assisted_*.moves` file under `verified\` and `jobs\*\search\`. Each file that replays is put back into the search and suffix sources, including the saved incumbent and a worse intermediate improvement. The persisted best is then reconciled with those files. A missing or rejected file cannot leave a verified-best claim whose hash was not replayed. When that reconciliation raises the incumbent, queued jobs are dropped.

An exhaustion record stores the launch ceiling and the final live ceiling from the completed attempt. Coverage uses the final live ceiling. A search launched at 139 that tightens to 138 does not count as exhaustion through 139. An older exhausted record with no stored live ceiling keeps its original scope text and its exhausted flag, and is marked so that it does not prove exhaustion at the launch ceiling.

Each new attempt receives the lesser of its planned limit and the campaign time still remaining. The job stores both numbers. A time limit that was shortened by the campaign deadline is `interrupted` with stop reason `deadline`. It is not exhaustion, and the same prefix can be tried again for the full planned limit. A clean `complete` inside a shortened window remains exhaustion at the final live ceiling. Resume on a fresh campaign starts the run clock when `run_started_at` is missing and keeps a clock that is already stored. Stop asks the worker to finish, pumps the Tk event loop while it waits, and only then terminates a worker that is still alive.

The resource manifest stores the raw, LF, and CRLF digests. A source checkout matches when the LF digest matches, or when the raw digest matches. Different content is rejected. Source mode still checks the pinned 157 and 140 git blobs. A frozen run does not call git.

The packaged source fingerprint includes `src/spider/unattended_optimiser.py`, `src/spider/packaged_runtime.py`, `src/spider/play_optimise_panel.py`, and `tools/play_lab.py`.

## Validation

```
py -3 -m pytest -q tests/test_unattended_optimiser.py tests/test_incumbent_suffix.py tests/test_play_lab_v0_104.py tests/test_play_session.py tests/test_solution_archive.py tests/test_canonical_moves.py
```

135 passed in 113.29 seconds. The new cases cover the 146/140 restart fixture, an unsupported persisted best, the 138 live ceiling, a deadline that is not exhaustion, LF and CRLF authentication, the controller files in the source identity, the RAM clamp for a request above 2,000,000, a fresh Resume clock, and a Stop wait that still dispatches a Tk callback.

The restart fixture loaded the real 146 and 142 games plus the 140 seed. After adopt, the selected search root was the 140 game, and 146 and 142 remained available. Removing the 140 and 142 files and claiming an unsupported best of 130 returned the incumbent to the replayed 146 game and dropped the queued job.

Known baseline failures were not re-run and were not weakened:

- `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` instead of `TIME_LIMIT`.
- Eight historical collection failures remain in the exact-state and workspace-service v0.1 modules.

No cheaper game was required, and none was found. The best stayed hash `34a94de8e6edfa4b`.

## Packaged checks

PyInstaller 6.22.3 on Python 3.14.5 built `dist\v0.106`. From `C:\Users\Codex\AppData\Local\Temp`, which is not the Git checkout:

```
SpiderPlayLab.exe --verify-packaged
```

exited 0 and printed `PACKAGED_SEED_OK hash=34a94de8e6edfa4b g=140 routes=6 runtime=packaged`.

The same executable was then started from that directory with a temporary session that already contained one history node and a named branch campaign, `Acceptance branch`. UI Automation reported the window title `Spider Play Lab · v0.106` and `Responding` true. A screen capture showed the Optimise tab and the preserved branch. UI Automation exposed only the top-level window. The child windows are `TkChild` handles with empty captions. `SetCursorPos` returned false and the cursor stayed at 557,483. `SendInput` reported three events and the cursor did not move. `SetForegroundWindow` returned false. An MSAA child walk crashed the probe with `0xC0000005`. Start, Pause, Resume, Stop, and Open verified best were therefore not clicked in the frozen window. The temporary session file was unchanged afterwards, and the twelve files already in `%LOCALAPPDATA%\SpiderSolver\PlayLab\Sessions` were unchanged. `docs/research/pre120_optimisation/status.json` stayed at SHA-256 `C8ACC007BF385CA7F35D659052F8D0BB3E3A669ACDD12865E7977F7330F1D032`.

The frozen supervisor was run from the same outside directory, with `git_used` false and no missing fingerprint files. The four controller sources above were present in the packaged fingerprint (`packaged:a1498f0a0b6b2705`).

A 50-second campaign requested 5,000,000 identities and 512 MB. The recorded clamp was 512 MB and 412,977 identities. The default in that record remained 2,000,000. It authenticated hash `34a94de8e6edfa4b`, started the campaign clock, skipped action 119 because f=140 is above ceiling 139, and queued actions 100, 90, 58, 80, 110, and 116. Action 100 ran with planned 6.00 seconds and applied 6.00 seconds, stopped on `time limit` at 1,533 identities, and was not exhausted. The supervisor then paused and logged that no new job had started. After resume it skipped the identical action-100 cap and started action 90, again at planned 6.00 seconds and applied 6.00 seconds. Killing that process and starting the supervisor once more, with stop already requested, recorded action 90 as `interrupted`, with the frontier text, `exhausted` false, and then exited without starting another job. The best remained the seed 140 game.

A second campaign used a 12-second budget and a planned attempt of 60 seconds, again at 512 MB and a 5,000,000 request. Action 100 was stored as planned 60 seconds and applied 11.58 seconds, `deadline_limited` true. The time limit was recorded as `interrupted` / `deadline`, not exhausted, and the campaign then stopped because the duration had elapsed. No second job started.

Opening a verified line through `open_verified_route` is covered by `test_open_verified_best_preserves_session_history`: the existing nodes and the named branch remain, and the route is appended. That test ran in the 135 above. The frozen Open verified best button was not clicked.

## Load dialog and control maxima

The Load dialog opens `solutions` under the source checkout, or `_internal\solutions` in the frozen folder. A campaign writes its games under `%LOCALAPPDATA%\SpiderSolver\PlayLab\Optimiser\4925153`. After a moves file replays, the campaign also copies that file into the Load dialog folder. An existing file with different bytes is left unchanged. A folder that cannot be written does not stop the campaign. The copy is not a search root.

The Play Lab campaign found `4925153_assisted_139.moves`, corrected cost 139, action hash `9f954355f8040751`. The campaign bytes are CRLF, raw SHA-256 `f53ca25fe4b3e255ccd29045e31da806fbe1533d158ad132281efadb0aa14b41`. The LF digest is `8ec28b738da5c29934a4d0aa9ff48b27cdcb2ddc09441ea8ced3ea0ca847c8e9`. That file is in the checkout `solutions` folder and in each packaged `solutions` folder. The header is `Corrected MW=139. Witness 157 at action 153.`

The same six test modules, with the new dialog, 139 replay, and maximum-control cases, passed 138 tests. The known baseline failures were not re-run.
