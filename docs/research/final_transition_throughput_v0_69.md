# final_transition_throughput_v0_69

Verdict: `TRANSITION_THROUGHPUT_RECOVERED_NO_F2`

Rows=1 expansions rose from **86 to 1600** (18.6×) in the same ~128 s, without changing strategy. No pre-SD5 F2 appeared. No terminal below 192.

## Measured bottleneck

v0.68 `TransitionTracker` called full `pareto_preview(pool)` on **every** rows=1 visit, then re-inserted up to 40 members into `post_deal_pareto`.

8 s microbench on the 192 rows=1 **epoch-entry** checkpoint (g=123, fd=2, F=1 — not the internal g=130 F2):

| | old (v0.68) | new (v0.69) |
| --- | ---: | ---: |
| expansions | 44 | 65 |
| exp/s | 5.38 | 7.96 |
| Pareto calls | 104 | 236 adds |
| Pareto seconds | **1.91** | **0.05** |
| category insert s | 0.001 | 0.003 |
| preview s | 0.57 | 1.21 |

Pareto rebuild was a real cost (24% of that 8 s). Incremental maintenance removes it. Remaining rows=1 time is kernel + exact Deal preview (now visible because search actually runs).

## Incremental Pareto

Separate fronts for operationally-defined vs plain records. Same dominance vector as v0.66. Each new record is compared only to its front; dominated members are dropped; the record is added if nondominated.

`post_deal_pareto` is materialised **once** per epoch via `finalize_track` (scheduler hook, default `None`).

v0.68 truncated the seen pool at 240 (keep 120). v0.69 keeps the **exact** nondominated set of all previewed records. Tests: incremental ident set = full `pareto_preview(all)` on 80 random corpora plus edge cases. Mobility/consolidation/operational/reception selected identities match the legacy tracker on a fixed 80-record corpus.

## Whole-game envelope

Untouched opening, ceiling 191, width 256, 900.3 s, unique 115,057, expanded 26,247. Policy frozen vs v0.68 except harvest bookkeeping.

## Rows=1 vs v0.68

| | v0.68 | v0.69 |
| --- | ---: | ---: |
| seconds | 128.9 | 128.3 |
| expanded | 86 | **1600** |
| generated | 762 | 15395 |
| unique | 875 | 9062 |
| exp/s | 0.67 | **12.5** |
| max F | 1 | 1 |
| min fd | 2 | 2 |
| preview s | 3.14 | 42.2 (more calls) |
| Pareto s | (dominant, unmeasured) | 10.9 |
| bookkeeping cat+finalize | — | 0.12 |

Throughput recovered. Preview is now the largest accounted rows=1 slice (~42 s / 9514 exact Deal clones).

## Checkpoint lineage

192 rows=1 epoch-entry: g=123, fd=2, F=1. Injected/survived as before.

Rows=1 previewed 9509 states; **5392** were checkpoint descendants. **Zero** of them, and zero of any origin, reached F=2 before SD5.

## Best pre-SD5 F2

None. Cheapest F2 is still **g=135 / fd=2 / rows=0 / h=39 / f=174**, same class as v0.68.

## F1–F8

| | v0.68 | v0.69 | v0.67 focused |
| --- | --- | --- | --- |
| F1 | 71 / fd10 / rows3 Spades | 71 / fd10 / rows3 Spades (ckpt lineage) | — |
| F2 | 135 / fd2 / rows0 | 135 / fd2 / rows0 | 130 / fd2 / **rows1** |
| F3+ | none | none | 173…192 |

Proof-prunes: 3873 (F1 3581, F2 292). Telemetry reconciles.

**Best complete g:** none. No v0.69 solution file.

## Interpretation

Bookkeeping, not Deal-preview cloning, was starving rows=1. Fixing it restores coverage. Coverage is still not finding a g=130-class F2 before the last Deal, so the next lever is **rows=1 transition ordering / lineage quality**, not more performance work and not a new endgame heuristic.

## Next recommendation

Next experiment should target rows=1 transition ordering/lineage quality, not more bookkeeping. Do not widen runtime. Do not copy the canonical route.
