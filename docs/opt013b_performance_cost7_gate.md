# Opt013B — Performance and cost-7 launch-readiness gate

## Status

**A. COST-7 LAUNCH READY** (gates measured; cost 7 **not** launched).

Base: Opt013A `660bffd` algebraic expander (exact vs free-closure oracle through ceiling 6).

## Profile (pre-optimisation algebraic ceiling 6)

| Observation | Value |
|-------------|------:|
| Elapsed | ~559 s |
| Quotient nodes | 121 |
| Peak RSS | ~68 MiB |
| Unique paid transitions | 2238 |

### Dominant bottlenecks (cProfile)

1. **`SpiderState.clone` via `copy.deepcopy`** — ~462 s / 145k clones (**dominant**)
2. **`expand_component_algebraic` / paid successor materialisation** — rides on clone
3. **`rss_bytes` PowerShell fallback** — ~42 s / 123 samples
4. **Start `free_closure` + `all_free_moves_reversible`** — ~45–75 s (algebraic path does not need full orbit)

## Optimisations (exact, no reachable-set change)

| Change | Rationale |
|--------|-----------|
| Structural `SpiderState.clone` (list copy of frozen `Card`s) | Removes deepcopy tax |
| Fast Windows RSS via typed `GetProcessMemoryInfo` | Avoids PowerShell per sample |
| Algebraic start: combinatorial free-orbit size; skip full free_closure | Empty-buffer free moves are structurally reversible |
| Arrangement signature dedupe in algebraic expand | Skip identical free witnesses |
| Cached `FreeEntity.packed` / card objects | Exact immutable caches |
| Free-slot-only rewrite in `build_state_from_arrangement` | Fixed columns already correct on free-orbit members |
| Quotient checkpoint schema with `backend_id` | Atomic write; refuse cross-backend resume |

`expand_component_bruteforce` remains the free-closure **correctness oracle** (unchanged semantics).

## Correctness re-proof

| Check | Result |
|-------|--------|
| Algebraic successor set ≡ brute, every component through ceiling 6 | **121/121 match** |
| Complete ceiling-6 quotient node sets algebraic ≡ brute | **equal** |
| `n_empty == 0` ⇒ free orbit singleton | **preserved** |
| Full `pytest` | see commit notes |

## Benchmark (complete ceiling 6)

| Metric | Brute-force | Algebraic (Opt013B) |
| -------------------- | ----------: | --------: |
| total quotient nodes | 121 | 121 |
| nodes by cost layer | same search | `{0:1, 1:40, 2:30, 3:40, 4:8, 5:2}` (cost≤5; c6 exhausts at 121) |
| elapsed time | ~69 s (post structural clone) / ~857 s Opt012 historical | **~8.1 s** |
| peak RSS | ~44 MiB | **~26–36 MiB** |
| paid transitions/sec | ~32 /s (2238 / 69s) | **~276 /s** (2238 / 8.1s) |
| target found | no | no |
| exhausted | yes | yes |

Performance target `algebraic ceiling-6 ≤ 120 s`: **PASS** (~8 s).

Opt012 historical reference (pre structural clone): 121 nodes, ~857 s, ~111 MiB, no target.

## Checkpoint audit (algebraic, ceiling 6)

| Item | Value |
|------|------:|
| schema | `opt013_quotient_ckpt_v1` |
| backend_id | `opt013_algebraic_v1` |
| checkpoint size | ~117 KiB (121 nodes) |
| write time | ~6 ms |
| restore time | ~10 ms |
| checksum time | ~1 ms |
| RSS before/after write | ~25.7 → ~25.8 MiB |
| temp disk residue | none (atomic replace) |
| second complete in-memory graph | **no** (arena only) |
| Opt012 brute resume as algebraic | **refused** |

## Cost-7 projection (not launched)

From measured c5 (5 nodes, ~0.5 s, ~24 MiB) and c6 (121 nodes, ~8 s, ~26 MiB):

| Estimate | Range |
|----------|------:|
| Likely quotient nodes at cost ≤ 7 | **500 – 5 000** (growth was 5→121 at last layer; next layer uncertain) |
| Likely runtime (algebraic) | **30 s – 10 min** (linear-ish in expands; 8 s × 4–40) |
| Likely peak RSS | **50 MiB – 1 GiB** (≪ 6 GiB gate) |
| Likely checkpoint size | **0.5 – 5 MiB** |

### Launch-ready gates

| Gate | Status |
|------|--------|
| Exact equivalence | PASS |
| All tests | PASS (see suite) |
| Clean reproduction | PASS |
| Checkpoint safe | PASS |
| Projected RSS < 6 GiB | PASS |
| 8 GiB process ceiling leaves ~2 GiB headroom | PASS |
| No other search worker active | operator check at launch |

### Recommended cost-7 production command (**DO NOT RUN in this phase**)

```text
python -m spider.planner.diagnostics.opt012_compact_search --ceiling 7 --max-rss-gib 8
```

(or project wrapper with `expand_mode=algebraic`, checkpoint dir under `artifacts/opt013/`, wall-clock and lock as used for Opt011).

## Explicit non-goals

- Cost 7 **not** launched here.
- No solver improvement claim (incumbent remains 172 / `77d169da2538ba8c`).
- Do not merge PR stack.
