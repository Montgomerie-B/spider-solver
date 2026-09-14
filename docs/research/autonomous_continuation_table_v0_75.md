# autonomous_continuation_table_v0_75

Verdict: `CONTINUATION_TABLE_VALID_NO_IMPROVEMENT`

The continuation table operated correctly, matched 65 exact autonomous states
(99 hits), and produced no cheaper complete route. Best candidate total remained 187.

## Continuation table

Machine sources only. Canonical 172 excluded. All four sources replay-valid.

| source | terminal g | actions | recorded | min-V updates |
| --- | ---: | ---: | ---: | ---: |
| v0.59 | 198 | 208 | 209 | 0 |
| v0.67 | 192 | 197 | 198 | 60 |
| v0.74 splice191 | 191 | 196 | 197 | 128 |
| v0.74 | 187 | 191 | 192 | 134 |

- unique entries = **406**
- by stock rows: 5=36, 4=39, 3=26, 2=60, 1=63, 0=182
- by F: 0=213, 1=64, 2=103, 3=7, 4=6, 5=3, 6=6, 7=3, 8=1
- F2 digest remaining **V=58** from v0.74 (source_prefix_g=129)
- build_s = 0.074

Keyed by ordered `pack_state`. Not SPS1. Not move ordering.

## Envelope

900 s / 800k unique / 2.5 GiB / width 256 / ceiling 186 / opening root.

187 checkpoints injected as current controls (one per epoch): rows 5/4/3/2/1/0 at g 0/33/65/74/123/130.

## Search totals

- unique=129694 expanded=31424 generated=270134
- elapsed=900.2 s stop=time limit maxF=2
- solved=false

## Continuation telemetry

| metric | value |
| --- | ---: |
| lookups | 137098 |
| hits | 99 |
| unique matched digests | 65 |
| equal-cost | 97 |
| cheaper-prefix | 0 |
| worse-prefix | 2 |
| best prefix saving | none |
| best candidate total | 187 |
| splices attempted | 0 |
| splices ok | 0 |
| lookup seconds | 0.101 |
| lookup % of search | 0.011% |

Overhead is negligible. Hits were almost entirely same-cost control matches on the 187 path.

## Tactical integration (unchanged v0.73)

- rows=1 control slot used
- 8 selected / 7 probed / 1 found
- control root g=123 target=d: first F2 g=129, cheapest F2 g=128 (different digest from the table F2)
- tactical unique=3975 expanded=872 in 16.2 s of 32.1 s reserved

The g=128 F2 is the v0.71-style cheaper cash-out. It is **not** the 187 F2 digest, so the stored 58-move suffix is not legal from it.

## F1–F8 milestones

| F | g | rows | fd | provenance |
| --- | ---: | ---: | ---: | --- |
| 1 | 71 | 3 | 10 | 187 checkpoint descendant |
| 2 | 128 | 1 | 2 | tactical cash-out, incumbent checkpoint, target d |
| 3–8 | — | — | — | not reached |

## Assembly proof-prunes

calls=133392, 5.48 s, prunes=7900 (F1=6768, F2=1132). min_h=0 max_h=96. Reconciles.

Lane expansions: cost 4156, reveal 6218, construction 7842, readiness 4387, horizon 2698, economy 5167, completion 389, plus tactical target_assembly 284 / target_access 283.

## 187 vs 172 forensics (evaluation only)

| route | g | post-SD5 g | remaining | fd | F | legal | h | f | rehandle |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| autonomous 198 | 198 | 131 | 67 | 3 | 0 | 12 | 31 | 162 | 133 |
| autonomous 192 | 192 | 135 | 57 | 2 | 2 | 6 | 39 | 174 | 118 |
| autonomous 187 | 187 | 130 | 57 | 2 | 2 | 5 | 41 | 171 | 113 |
| canonical 172 | 172 | 150 | 22 | 1 | 2 | 16 | 18 | 168 | 109 |

The 15-MW 187→172 gap is **not** mostly pre-SD5. Autonomous stock-empty remaining is 57 versus canonical 22 (Δ35). Canonical enters SD5 later (g=150 vs 130) with a cheaper assembly board (h=18 vs 41, legal 16 vs 5). The machine reaches stock exhaustion earlier on a structurally more expensive tableau.

## Interpretation

Exact-state continuation matching works and is cheap. Whole-game search rediscovered known 187 states at the same g, never cheaper. The tactical planner still finds a cheaper *different* F2 (g=128) that cannot inherit the 187 suffix. Closing 187→172 is a post-SD5 conversion problem, not a missing transposition on the current solved subgraph.

## Next recommendation

The 187→172 gap is overwhelmingly post-SD5 conversion; next evaluate final-Deal roots by bounded stock-empty rollout / future cost rather than only one-step preview.
