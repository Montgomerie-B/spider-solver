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

- Research baseline: v0.130 post-SD5 completion, `docs/post_sd5_completion_v0_130.md`, on `local/post-sd5-completion-v0-130`. From the exact checkpoint after stock deal 5 (`g=150`, `h=18`), no complete suffix was found inside 80,000 symmetry classes at ceiling 172 or 171. The checkpoint is unresolved, not proved minimal.
- Next experiment, not started: change the tableau before SD5, using backward planning from the final row and a looser rejoin or a full endgame continuation. Do not treat that as general suffix repair unless the assignment says so.
- Preferred next working branch: create it when that experiment is assigned. Do not merge `local/post-sd5-completion-v0-130` into `main` without approval.
- The coding agent should deliver a pushed branch and verified commit, not a list of PowerShell commands for the owner.
