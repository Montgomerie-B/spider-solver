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

- Research baseline: v0.137 phase-aware milestones, `docs/phase_aware_milestone_v0_137.md`, on `local/phase-aware-milestone-v0-137`. Gate A replayed both tableaux from checkpoint 152. The five-move shortcut costs 155 and the canonical window costs 158. Both have admissible `f = 169` (`h` 14 and 11). Packs differ. `move 3 5 3` in the canonical suffix is illegal on the shortcut because column 5 holds the 3 of clubs rather than the 7 of hearts. Gate B passed: the opt-in ordering replayed that same five-move pack with no reference actions. Gate C, on the paired eight early roots, kept one milestone, root 0 at `g = 154`, `h = 17`, `f = 171`, the same pack v0.136 already exhausted. The `f <= 170` screen rejected it. Gate D did not run. The release stopped at Gate C. Caps were not raised, the canonical post-SD5 search was not repeated, the exhausted v0.136 endpoint was not rerun, and v0.138 was not started. The 172 and 185 solution files are unchanged. The 171 objective is not established.
- Next recommendation, not started: search these same roots for a different post-deal state whose admissible `f` is at most 170. Do not resume the `g = 154` identity, and do not treat a shorter club-and-reveal sequence as a gain when recomputed `f` stays 169.
- Do not merge `local/phase-aware-milestone-v0-137` into `main` without approval.
- The coding agent should deliver a pushed branch and verified commit, not a list of PowerShell commands for the owner.
