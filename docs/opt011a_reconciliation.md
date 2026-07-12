# Opt011A — repository reconciliation and exact-search hardening

## Active bounded scan (left running)

| Field | Value |
|-------|--------|
| Label | `bounded scan: corrected cost <= 7, explicit depth <= 24` |
| PIDs | 15612 (WindowsApps launcher) → **7932** (real worker) |
| Command | `python -m spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor --resume --max-expanded 5000000 --max-depth 24` |
| Completeness | **Not complete** for unrestricted cost ≤ 7 |
| Improvement | **None claimed** |

No second long search was launched. Checkpoints under the original worktree were not deleted.

## Git reconciliation

| Ref | Hash |
|-----|------|
| Original Opt011 commit | `60738df` |
| Safety branch | `safety/opt011-60738df` |
| `origin/main` base | `d602fe7` |
| Clean replacement branch | `opt011a/hardened` |

`60738df` was based on `4b1e0ac` (9 commits behind `origin/main`) and included ~140MB of mutable checkpoints/progress.

Critical: almost all of `src/spider/*` (engine, metrics, solution_archive, hybrid adapter, …) existed only as **local untracked** files — documented on `origin/main` but not present as code. The clean commit therefore ships the required implementation dependencies so a fresh clone can run Opt011.

## Algorithm audit (prior bounded implementation)

1. **Frontier:** binary heap (priority on target distance, then MW cost, depth).
2. **Algorithm class:** best-first / beam-ish search with optional frontier memory caps — **not** complete 0–1 BFS.
3. **Edge costs:** corrected MW ∈ {0,1}; hybrid ordered successors; later full legal set.
4. **Zero vs unit cost:** not specially ordered in a 0–1 deque (heap only).
5. **TT key:** Zobrist hash.
6. **Dominance:** keep lower corrected cost; equal cost keeps shallower depth.
7. **Depth:** hard `max_depth=24` bound → incompleteness for unrestricted cost ≤ 7.
8. **Path history:** legality is state-only; paths stored for reconstruction.
9. **Hybrid:** ordering only when full move set retained; filtering would break completeness.
10. **Resume:** frontier path replay + TT restore; prior schema incomplete.

**Conclusion:** The depth-24 production run is **not** complete for unrestricted corrected cost ≤ 7.

## Exact mode (hardened)

- Algorithm id: `opt011_exact_01bfs` v2
- 0–1 BFS, no explicit-depth cutoff
- Ceiling 7, no stock deals
- Target = Zobrist + structural equality
- Atomic checkpoints, single-writer lock, `--max-rss-gib`
- Bounded mode retained as diagnostic only (never reports unrestricted exhaustion)

## Long-run command (ready, not launched)

```bat
set PYTHONPATH=src
python -m spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor --mode exact --max-rss-gib 12
```
