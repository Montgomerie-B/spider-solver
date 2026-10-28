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

- Research baseline: v0.134 purposeful macro portfolio, `docs/purposeful_macro_portfolio_v0_134.md`, on `local/purposeful-macro-portfolio-v0-134`. From checkpoint 140 the macro search, which was not given the named moves, produced replayed fifth-deal plans at `g=142` with four same-suit landings, including plans at `h=24`, `f=166`. One kept plan contains `move 2 5 1`, `move 3 1 2`, and `move 9 2 1` among extra zero-cost transfers. Empty-column count was not the objective. One eight-root continuation used the unchanged v0.133 lanes, strict `g+h>171` pruning, and the 20,000-state / 45-second / 512 MB cap. It stopped at 45 seconds with 3,182 retained identities, 2,192 expansions, and no reference match. Origin 7 took 2,190 of those expansions. Minimum `f` stayed 166. No complete game at 171 or fewer was verified. The result is inconclusive. The canonical post-SD5 search was not repeated, its budgets were not increased, the continuation cap was not raised, and v0.135 was not started. The 172 and 185 solution files are unchanged.
- Next recommendation, not started: share that same 20,000-state and 45-second budget across the admitted roots. The goal lane starved the `f=166` preparation. Do not raise the cap, do not repeat the canonical post-SD5 search, and do not add another heuristic family from this result.
- Do not merge `local/purposeful-macro-portfolio-v0-134` into `main` without approval.
- The coding agent should deliver a pushed branch and verified commit, not a list of PowerShell commands for the owner.
