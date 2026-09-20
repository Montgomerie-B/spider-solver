# Spider Play Lab v0.103

A separate Tkinter/ttk and Canvas application for manual Spider play, canonical
solution replay, and durable human branches. The existing engine and rules are
unchanged. No campaign/search workers, incumbent promotion, or ceiling updates
are called by Play Lab.

## Launch

From this checkout:

```powershell
python tools/play_lab.py
# Or double-click run_play_lab.bat.
python tools/play_lab.py --deal deals/4925153.txt
python tools/play_lab.py --solution solutions/4925153_canonical.moves
python tools/play_lab.py --session "C:\path\to\session.json"
```

The source application needs Python with Tkinter; it has no third-party runtime
dependencies. The tested environment is Windows 11, Python 3.14.5, Tk 8.6.

## Play, replay, and branch

- Select an exposed card and click its destination, or drag it. An anchor selects
  the entire same-suit descending tail beneath it. The engine decides legality.
- Click **Deal stock** to deal, including when columns are empty (MW_RULES).
- **Load solution** accepts canonical `.moves` and `.moves.txt`, including partial
  routes and external human/autonomous routes. The entire route is checked before
  it is added; invalid imports leave the previous session intact.
- **First / Previous / Next / Last** navigate a loaded route. Left/Right step;
  Ctrl+Z/Ctrl+Y undo/redo. Next follows the loaded route while on that route;
  Redo follows the most recently selected child. After diverging, Next and Last
  follow the selected branch. Choose First to return to the parent route.
- Make any different legal action at a replay position to branch automatically.
  The panel shows the parent route, divergence ordinal, and parent g.
- The flat history index exposes every node without hundreds of levels of visual
  indentation. Fork children have a marker and short ID. Select any row to revisit
  it; the saved data remains a full tree. The route selector retains all imports.
- Analysis View reveals hidden card identities with muted faces and a `×` lock
  marker. They remain unselectable. Future stock rows SD1–SD5 follow the existing
  `stock_deal_rounds()` order; dealt rounds disappear. Normal View hides identities.
- Long columns scroll. For widely separated source/destination positions, select
  the source, scroll, and click the destination. Escape clears a selection.

## Durability and architecture

`spider.play_session.PlaySession` owns immutable history records, cached cloned
states, child links, redo preferences, imported routes, and a current-node pointer.
Every edge is one canonical game action. Undo is navigation, never an action.
Export walks only root → current, so abandoned actions do not enter a solution.

The session JSON embeds the validated original 104-card deal plus stable node IDs,
parents, canonical actions, incremental/cumulative engine costs, path ordinals,
stock/foundation/hidden/empty counts, flip/removal counts, timestamps, and a SHA-256
digest of the repository's structural state identity. Column order is preserved.
Canonical actions retain source, destination and k in the existing 1-based format.

Loading reconstructs **every branch**, in parent order, from fresh engine states;
stored counters and state hashes must match. Cached states are never trusted from
disk and callers receive clones. Imported routes and redo edges are also checked.

Default storage:

```text
%LOCALAPPDATA%\SpiderSolver\PlayLab\Sessions
%LOCALAPPDATA%\SpiderSolver\PlayLab\Exports
```

Each accepted action and history navigation saves synchronously using a temporary
file, flush/fsync, and atomic replace. The prior valid file is retained as
`.json.bak`. A short OS file lock serializes the compare-and-replace operation;
an outdated second window cannot overwrite newer work. Locks release on process
exit, including a crash. Small `.lock` files may remain and are harmless.

On a storage error the accepted action stays in memory, a visible error replaces
the autosaved indicator, and further actions/navigation are blocked. **Save Session**
can write a recovery copy. The app refuses normal close until the session is saved.
Startup lists recent sessions; Open session also accepts backups. Backups restore
to a separate recovery file. No application can guarantee recovery from physical
disk failure; copy valuable session files to independent storage as appropriate.

`spider.play_render` provides pure presentation/anchor helpers and a Canvas board;
`tools/play_lab.py` supplies dialogs, controls, and the history navigator. Neither
implements Spider legality, flipping, removal, or move scoring.

## Export and verification

**Export Current Line** creates a canonical `.moves` (or `.moves.txt`) file and a
JSON sidecar containing the full session and verification report. That sidecar
can also be reopened as a session. Each export uses the existing
`replay_actions_detailed()` on a new `SpiderState` built from the original cards,
and compares the resulting state, g, and solved status against the selected node.
The UI distinguishes VERIFIED SOLUTION from VERIFIED PARTIAL LINE.

Verification is read-only with respect to the autonomous registry. The existing
archive validator independently checks solved exports in the acceptance tests.
The canonical 4925153 route is 174 actions, 169 tableau moves, 5 deals, corrected
MW cost **172**, and 8 foundations. No claim is made to have found a new 166 route.

## Independent Windows package

```powershell
python -m pip install pyinstaller  # only if not already installed
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_play_lab.ps1
.\dist\SpiderPlayLab\SpiderPlayLab.exe
```

Keep the entire `dist/SpiderPlayLab` folder together. It bundles Tcl/Tk, the default
deal and canonical route. This is a separate build specification; the Campaign GUI
build is unchanged. Build/dist files are ignored by Git. The tested builder is
PyInstaller 6.22.3.

## Automated validation

```powershell
python -m pytest -q tests/test_play_session.py tests/test_rules.py tests/test_deal.py tests/test_metrics.py tests/test_canonical_moves.py tests/test_same_suit_block_legality.py tests/test_mobilityware_unrestricted_rules_contract.py tests/test_solution_parse.py tests/test_solution_archive.py tests/test_4925153_move_accounting_audit.py
```

Final result: **152 passed in 115.86s**, with no failures (27 new Play Lab cases,
125 existing regression cases). Tests cover all 17 non-visual requirements in the
brief, including a genuine reversible divergent branch completed to a solve and
independently validated by `solution_archive.validate_solution`. Additional tests
cover corrupt metadata, invalid/partial imports, disk failure, recovery, backups,
concurrent writers, snapshot isolation, and export/session filename safety.

An initial run exposed a `from_deal` argument-name conflict (fixed). A recovery test
was then corrected to avoid intentionally writing two independently loaded copies
to the same path, which correctly triggers the concurrent-writer protection.

## Desktop validation and limits

Windows desktop validation exercised deal 4925153, a legal drag (`move 3 6 1`),
click-selection of a two-card run (`move 6 8 2`), illegal king rejection without a
dialog, Ctrl+Z/Ctrl+Y, dealing, Analysis View, hidden-card rejection, SD1–SD5
identities, canonical import through the picker, Left/Right replay, automatic
branch provenance, verified branch export, and close/reopen via recent sessions.
The restored branch retained g=2, action count=2, and divergence after action 1.
First/Last displayed the canonical solved state at g=172 with all eight foundations.

The final packaged executable was launched and restored the same session. On
20 September the restored session also contained `4925153_autonomous_185.moves`.
The packaged app replayed that route through action 189 and exported it through
the file picker. The independent export result was VERIFIED SOLUTION: MW cost
185, 189 actions, 184 tableau moves, 5 deals, 8 foundations, solved=True.
The resulting `.moves` file was then separately passed to the existing
`solution_archive.validate_solution('4925153', export_path)`, which also returned
valid=True, solved=True, MW=185, actions=189, deals=5, foundations=8.

The UI deliberately has no solver advice or animations. It targets desktop sizes
of at least 1120×680; larger displays give more room for research. The history
navigator is a flat index of a persistent tree, not a graph editor. Analysis-view
preference is per window. Canonical and divergent completed-route tests, plus the
actual autonomous 185 packaged export, cover the intended replay/export workflow.

## Repository isolation

Original checkout: `C:\Users\Codex\Documents\Grok Build\spider-solver-intent-v01`
on `local/autopilot-persistence-v0-102a`. Preflight found no tracked changes and
existing untracked research result folders/watcher scripts; all were preserved.
Recent baseline commits were bb02e3a (campaign persistence/moving ceiling), aa916de
(operation persistence), and c46525f (autopilot identity/pause/failure contracts).

Play Lab checkout: `C:\Users\Codex\Documents\Grok Build\spider-play-lab-v0-103`
on `local/spider-play-lab-v0-103`, based on
`bb02e3a8e562d32c014839bbd73706a99dcd1413`. Files are left uncommitted for review.
No push, merge, PR, campaign operation, incumbent change, or production-ceiling
change was performed. Engine/rules and all other existing tracked files are unchanged.

Added files: `src/spider/play_session.py`, `src/spider/play_render.py`,
`tools/play_lab.py`, `tests/test_play_session.py`, `run_play_lab.bat`,
`spider_play_lab.spec`, `scripts/build_play_lab.ps1`, and this document.
