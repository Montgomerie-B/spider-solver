# Spider Solitaire Solver — Agent-managed Git workflow

This file defines the **default development handoff** for the repository. Read it at the start of every Grok Build / coding-agent assignment. The project owner should not need to open PowerShell to stage files, commit releases, create branches or push work.

## Ownership and intent

- **Coding agent (Grok Build or other agent with the working checkout):** owns local branch synchronisation, selective staging, commits, pushes, and factual reporting.
- **ChatGPT with the connected GitHub account:** can verify remote commits, create branches, inspect diffs, review, create issues and coordinate pull requests.
- **Project owner:** supplies requirements and approves changes when needed; does not act as a routine Git operator.
- A previous release prompt's boilerplate such as "Do not commit or push" is superseded by this workflow **when the project owner instructs the agent to use this new default**. Explicit later instructions from the owner take precedence. Never merge into `main` without separate owner approval.

## Before editing

1. Inspect `git status --short --untracked-files=all`, `git branch --show-current`, `git rev-parse HEAD`, and `git remote -v`. Confirm `origin` is `https://github.com/Montgomerie-B/spider-solver.git`.
2. Fetch remote refs. Use the explicitly designated release branch, creating it only if it does not already exist. If the branch exists remotely, check it out / track it and synchronise with a **fast-forward only** pull. Never silently reset, stash or discard unexpected local work.
3. Verify the actual baseline commit and record known unresolved regressions before making changes. Never assume GitHub `main` matches the active development branch.

## After completing work

1. Run the relevant tests and independent replay checks. Distinguish newly introduced regressions from documented baseline failures. Do not alter rules, tests or verified solutions merely to make a run green.
2. Stage **only intended paths**, explicitly including new modules, fixtures, documentation and tests. Review `git status --short --untracked-files=all`, `git diff --cached --check`, `git diff --cached --name-status`, and `git diff --cached --stat`. Do not stage secrets, private credentials, large temporary products or unrelated generated files.
3. Create a descriptive commit on the assigned feature branch. Push it to `origin` and verify the remote branch SHA matches the new local HEAD. A known pre-existing failure may be documented in a research checkpoint; do not claim the suite passed. If new work is incomplete, mark the commit and report as **WIP** rather than claiming a finished release.
4. Report the branch, full commit SHA, GitHub link, files changed, test outcomes, remaining blockers and clean/dirty working-tree state. The owner must **not** be given routine staging, commit or push commands.

## Safety boundaries

- **No direct pushes to `main`**, auto-merge, force push, history rewrite of published commits, deletion of branches, or changes to the verified 172/185 solution files without explicit approval.
- Never bypass repository security policies or authentication. If credentials/permissions block a push, explain the exact one-time connection problem instead of suggesting routine PowerShell as the normal workflow.
- Preserve independent cold-search provenance, exact engine legality, corrected MobilityWare move accounting (including zero-cost whole-column transfers), and full eight-foundation replay validation for any claimed solution.
- Known baseline issue at v0.126/v0.127: `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` can return `PLANNING_STALL` instead of `TIME_LIMIT` in full-suite runs. Report this openly; do not silently weaken the test.
- A branch push is not a production deployment or a merge. ChatGPT can review the remote code and prepare a pull request when appropriate.

## Current release handoff

- Research baseline: v0.138 heart-run follow-through, `docs/heart_run_followthrough_v0_138.md`, on `local/heart-run-followthrough-v0-138`. Checkpoint 160 already contains a buried seven-heart run, so the obligation is a seven-card heart run on a column top. Gate A passed without reference actions: `Kh` through `7h` at `g = 160`, `h = 10`, `f = 170`. The canonical `7h` through `Ah` oracle is `g = 161`, `h = 9`, `f = 170`. Gate B rebuilt that king-high run from the five-move shortcut at `g = 157`, `h = 13`, `f = 170`, behind checkpoint 163 on the residual. Gate C, on the paired eight roots, opened six heart endpoints with `f <= 170`. The cheapest is root 0 at `g = 147`, `h = 22`, `f = 169`, still with three face-down cards and two foundations. Gate D exhausted those six prefixes under `g + h > 171` and accepted no game. The release stopped at Gate D. Caps were not raised, the canonical post-SD5 search was not repeated, the exhausted v0.136 endpoint was not rerun, and v0.139 was not started. The 172 and 185 solution files are unchanged. The 171 objective is not established.
- Next recommendation, not started: accept a top heart run on these same roots only when the face-down count has also fallen. Keep the same caps. Leave the `g = 154` pack out.
- Do not merge `local/heart-run-followthrough-v0-138` into `main` without approval.
- The coding agent should deliver a pushed branch and verified commit, not a list of PowerShell commands for the owner.
