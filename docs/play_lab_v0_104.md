# Spider Play Lab v0.104 — human research workflow

Implemented in `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`.
This is a focused extension of v0.103's persistent action tree and Tk desktop UI.
No rules, scoring, search heuristics, campaign integration, registry, or ceiling
logic changed. No new third-party dependencies were added.

## Using the release

Run `dist/v0.104/SpiderPlayLab/SpiderPlayLab.exe`. Keep its entire folder together.
The existing `dist/SpiderPlayLab` v0.103 package, including the user-added autonomous
185 solution, is preserved. The new package bundles the same default deal and
canonical solution as before; other solutions can be opened with Load solution.

Load a solution, navigate to a position, and press **Start Branch Campaign**.
Accept the generated name or enter a name. The sidebar shows the parent solution,
origin action, origin MW g, and current g. This naming operation adds no game move.
Starting another campaign creates a child with its own origin and saved position.
The campaign selector returns to each campaign's latest saved position. The parent
replay selector returns to the original route's opening, preserving campaigns.

The **Clean move record** shows exactly the root-to-current action lineage,
including pre-campaign ancestry. Undo removes rows; redo restores them. Playing a
different move after undo selects a new history branch. **All history** retains
abandoned alternatives and the original replay. Scores come from existing history
nodes. Stock-deal rows and campaign origins are marked, and the current action is
highlighted. Export still derives from the model's lineage, never from display text.

## Persistence and compatibility

Session format 2 adds campaign name, origin node/action/g, parent route and source
path, optional parent campaign, creation time, current node, and active campaign.
Recovery reconstructs every node through existing engine replay and checks origin
metadata against that history. Campaigns are local Play Lab research metadata;
they do not create autonomous search campaigns.

v0.103 format-1 sessions load without changing their history. Saving them in v0.104
writes format 2, retaining the existing backup mechanism. v0.103 cannot read format
2. Validation used a new test session, leaving earlier user sessions alone.
Animation speed, analysis visibility, window size, and scroll position are per-window
preferences; they reset on launch. Active campaign and clean lineage persist.

## Movement and stock presentation

`PlayController` applies and autosaves the complete authoritative operation first.
The board then animates cloned snapshots and presentation sprites. Conflicting
actions are ignored while busy rather than queued with stale coordinates. The clean
recorder updates immediately. The renderer never applies Spider moves or scores.

Movement durations: Instant 0 ms, Fast 160 ms, Normal 320 ms, Slow 650 ms.
Animated moves include a 45 ms arrival hold and 140 ms effects interval, so the
Normal input gate lasts approximately 505 ms plus processing time. A gold outline
distinguishes the moving run, which follows an eased path. Stock cards cascade to
columns 1–10 within the same movement interval. Flipped cards get a brief highlight;
completed sequences receive a short completion notice after arrival. Instant skips
all transition/effect delays. First, Last, backward navigation, and history jumps
redraw immediately. Resize or a view/speed change safely finishes the visual
transition at the already-saved state.

Analysis View renders future SD1–SD5 as subdued miniature cards aligned under the
ten columns, with red/dark suits and a small unavailable mark. Stock ordering comes
directly from `stock_deal_rounds`; dealt rounds disappear. Miniatures have no playable
anchor or hitbox, and cannot be destinations. Normal View conceals the future panel
entirely, as v0.103 did. Long columns and stock rows use the board's scrollbar.

## Automated validation

Full Play Lab and relevant frozen-engine regression command:

```powershell
python -m pytest -q tests/test_play_lab_v0_104.py tests/test_play_session.py tests/test_rules.py tests/test_deal.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_same_suit_block_legality.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_parse.py tests/test_solution_archive.py tests/test_4925153_move_accounting_audit.py
```

Result: **176 passed in 122.15s** — all 152 baseline cases plus 24 new cases.
Coverage includes origins at opening/mid-replay/stock/end states, child campaigns,
recovery, metadata checks, format-1 migration, lineage/undo/alternate/redo/export,
all speeds, rapid-input gating, saved state before animation, invalid-input recovery,
instant Last, real Canvas sprites/resize, stock ordering/locking/concealment,
live recorder widgets, and a completed named branch independently verified at g=172.

After the final layout adjustments:

```powershell
python -m pytest -q tests/test_play_lab_v0_104.py -k 'canvas or live_recorder'
# 3 passed, 21 deselected in 2.83s
python -m pytest -q tests/test_play_lab_v0_104.py -k live_recorder
# 1 passed, 23 deselected in 2.07s
git diff --check
# passed; no whitespace errors
```

Earlier diagnostic runs: the first 51-case run had 50 passes and one Tk interpreter
startup error; a later three-case run had two passes and a similar startup failure.
The installed Tcl files existed, and isolated runs passed. The GUI fixtures now share
one Tk interpreter per test process, matching the real application, instead of
repeatedly destroying and constructing Tk roots. The subsequent full run above
passed. An earlier complete run also passed 176 cases in 117.70s. No tests were skipped
or weakened, and no expensive search campaign was run.

## Actual Windows Computer Use validation

Performed through the Computer Use plugin on the source app and packaged executable:

1. Opened deal 4925153 and loaded the actual `4925153_autonomous_185.moves`.
2. Stepped the opening at Normal speed. A screenshot caught the highlighted 5–4
   spade run in transit from column 6 toward column 8. Switched to Instant and
   confirmed action 4 / g=4 without transition.
3. Used All history to navigate to action 37 / g=34, one move after SD1 at action 36.
   Started `v104 acceptance - after SD1`.
4. Manually played `move 9 1 1`, `move 10 7 1`, `move 3 7 1`. The clean recorder
   reached action 40 / g=37. Two Undo clicks removed the last two rows.
5. Played alternate `move 3 10 1`. The clean line became 39 actions / g=36.
   All history visibly retained the abandoned actions 39 and 40 plus the new sibling.
6. Inspected the long tableau, branch status, origin marker, selected-run outlines,
   dark/red suits, and all SD1–SD5 miniature rows. Clicked a future card without
   changing the state. Normal View concealed identities. Maximized the window from
   1422×932 to 1920×1032 and inspected alignment and readable controls.
7. Exported the partial branch through the picker. The app reported VERIFIED PARTIAL
   LINE, 39 actions, MW=36, one deal, zero foundations. The sidecar replay restored
   identical actions and metadata; separate assertions compared the file's parsed
   actions with the recovered lineage and checked that abandoned alternatives remained.
8. Closed the source app, launched v0.104's executable, and restored the test session
   through Recent sessions. Campaign name, origin action 37 / g=34, current action 39
    / g=36, and selected clean route were preserved.
9. Switched to the parent replay, used Last (immediate at Normal speed), and confirmed
   action 189, g=185, five deals, eight foundations, ten empty columns and empty stock.
   Went back one action, created `v104 acceptance - solved export`, selected the
   nine-card run and manually moved it from column 6 to column 1 to finish.
10. Exported the completed named branch through the picker. Independently called
    `solution_archive.validate_solution('4925153', exported_path)` outside the UI:
    valid=True, solved=True, MW=185, 189 actions, 184 tableau moves, five stock deals,
    eight removals/foundations, stock_remaining=0. Returned to the earlier campaign
    and confirmed its saved action 39 / g=36 position was still intact.

Artifacts under `%LOCALAPPDATA%/SpiderSolver/PlayLab`:

- Session: `Sessions/4925153_1b9aca091fae435faf972ebfa6646827.json`
- Partial: `Exports/4925153_g36_0cb2a1cc.moves` and `.json`
- Solved: `Exports/4925153_g185_8671cbec.moves` and `.json`

These are acceptance-test campaigns. No new improved solution was discovered or
claimed; the solved desktop check completed the known 185 route. Automated coverage
also preserves the original v0.103 divergent-branch completion tests. Sub-frame
repeated Next/conflicting input and resize during motion are covered deterministically
by the controller/Canvas tests; the desktop check additionally exercised actual resize.

## Build and scope

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_play_lab.ps1
```

PyInstaller 6.22.3 / Python 3.14.5 built the separate Windows folder successfully.
The executable was launched and used for recovery, miniature-card inspection,
campaign switching, manual completion, and verified export. The final package includes
the layout follow-ups found during this inspection. No installer is required.
The rebuilt final executable was launched again and restored the exploratory
campaign with the origin marker and highlighted action 39 fully visible immediately,
confirming the automatic-scroll correction.

Known limits: the history view remains a flat index into a persistent tree; this is
not a graph editor. Long columns/five stock rows require scrolling on smaller windows.
Inputs during transitions are intentionally ignored. Reverse/jump navigation is
instant. There is no autoplay, solver advice, search integration, or new best-score claim.

Changed files:

- `src/spider/play_session.py` — campaign persistence and clean-line accessor.
- `src/spider/play_controller.py` (new) — authoritative operation/input gate.
- `src/spider/play_render.py` — animation sprites/effects and stock miniatures.
- `tools/play_lab.py` — campaign controls, recorder, speed, layout and UI integration.
- `tests/test_play_lab_v0_104.py` (new) — 24 focused cases.
- `scripts/build_play_lab.ps1` — versioned output preserving v0.103.
- `docs/play_lab_v0_104.md` (new) — this implementation and validation report.

Preflight was clean on `local/spider-play-lab-v0-103`; HEAD was exactly the requested
baseline, and its ancestry was checked. Final HEAD remains
`636f54961abb0909c65722ce32df73e410680f36`. The four modified files and three new files
above remain uncommitted. `src/spider/engine.py` and `src/spider/rules.py` have no diff.
No commit, push, merge, PR, incumbent promotion, production ceiling update, or
autonomous campaign operation was performed.
