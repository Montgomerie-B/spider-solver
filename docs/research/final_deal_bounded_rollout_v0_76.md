# final_deal_bounded_rollout_v0_76

Verdict: `ROLLOUT_SIGNAL_STRONGLY_DISCRIMINATES`

Bounded 30-second stock-empty rollouts separate final-Deal board quality.
The ranking disagrees with one-step preview, agrees with known 187/192 vs 198
downstream remaining cost, and canonical calibration converts faster still.

## Machine-only corpus

Continuation-table rows=1 states plus actual 187/192/198 pre-SD5 roots and the
v0.71/v0.75 tactical F2 (g=128, different digest). Canonical 172 was not used
for corpus, selection, search, or ranking.

## Selected eight roots (static preview)

| role | pre g | post g | F | fd | legal | h | f | bounds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ctrl_187 | 129 | 130 | 2 | 2 | 5 | 41 | 171 | 35 |
| ctrl_192 | 134 | 135 | 2 | 2 | 6 | 39 | 174 | 33 |
| ctrl_198 | 130 | 131 | 0 | 3 | 12 | 31 | 162 | 26 |
| tactical_f2_g128 | 128 | 129 | 2 | 2 | 5 | 43 | 172 | 37 |
| fill_low_f | 90 | 91 | 0 | 9 | 10 | 47 | 138 | 36 |
| fill_mobility | 124 | 125 | 0 | 3 | 20 | 33 | 158 | 28 |
| fill_consolidation | 125 | 126 | 0 | 3 | 20 | 32 | 158 | 27 |
| fill_operational | 128 | 129 | 1 | 2 | 5 | 42 | 171 | 37 |

Not eight cheapest-g states. Absolute g preserved. Real engine Deal.

## Envelope

30 s / 50k unique / 2.5 GiB / ceiling 186 / no Deal / no tactical / no
continuation-table suffixes / COMPLETION lanes + assembly bound.

## Per-root search (30 s)

| role | unique | exp | prunes | max F | F3 g / f | min h | min f | first ΔF |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| ctrl_187 | 3503 | 256 | 1204 | 3 | 172 / 186 | 14 | 171 | 22.5 s / +42 |
| ctrl_192 | 3422 | 210 | 869 | 3 | 172 / 187 | 15 | 174 | 28.3 s / +37 |
| ctrl_198 | 2820 | 192 | 0 | 1 | — | 19 | 162 | 8.3 s / +10 |
| tactical_f2_g128 | 3678 | 265 | 1414 | 3 | **158 / 180** | 16 | 172 | **10.0 s / +29** |
| fill_low_f | 2430 | 378 | 0 | 0 | — | 32 | 138 | none |
| fill_mobility | 2486 | 166 | 0 | 0 | — | 29 | 158 | none |
| fill_consolidation | 2478 | 171 | 0 | 0 | — | 28 | 158 | none |
| fill_operational | 2938 | 193 | 345 | 2 | — | 19 | 171 | 4.5 s / +7 |

No root solved. No complete candidate below 187.

## Rollout-key ranking (experimental, not admissible)

1. tactical_f2_g128
2. ctrl_187
3. ctrl_192
4. fill_operational
5. ctrl_198
6. fill_low_f
7. fill_mobility
8. fill_consolidation

## Control comparison (eval labels after freeze)

Known remaining: 187=57, 192=57, 198=67.

Rollout order among controls: **187, 192, 198**. Agrees with known downstream quality.
187 reached F3 with better f than 192 (186 vs 187). 198 only reached F1.

## g128 tactical F2 vs g129/187 F2

Rollout **prefers g128**. Both start F=2, legal=5. g128 has slightly worse static h
(43 vs 41) but converts to F3 cheaper and earlier (g=158 f=180 at 10 s vs g=172
f=186 at 22 s). Cheap entry with a more fragmented board still converted faster
in this 30-second window. Completeness of that future is unknown.

## One-step vs rollout

Static order (lowest f, then mobility): fill_low_f, fill_consolidation,
fill_mobility, ctrl_198, ctrl_187, fill_operational, tactical_f2_g128, ctrl_192.

Rollout order is almost the reverse of cheap-f preference. Cheap post-Deal g
**negatively** correlated with short-horizon conversion: the three cheapest-f
F=0 fillers never founded.

Most informative rollout metrics: max F, f and g at that F, time/cost to first
foundation increase. Static h and post-g alone are misleading.

## 187 short vs long historical (eval)

v0.74 focused search from this same post-Deal root found F3 at g=156 (368 s)
and solved at 187 (246 s). The 30 s pilot reached F3 at g=172. Same direction,
shallower cheapest-g. Useful as a quality signal, not a substitute for a full
endgame solve.

## Canonical calibration (after freeze)

pre g=149, post g=150, F=2, fd=1, legal=16, h=18, f=168.

30 s: max F=**5** (g=167, f=171), min h=3, first ΔF at 6.2 s / +8, mobility 227.

Would rank **1st** among the eight machine roots. Consistent: the later, richer
post-SD5 board converts far faster. Not used to change ranking or policy.

## Performance

setup 0.78 s; aggregate rollout 241.4 s; peak RSS ~41 MiB; ~6–13 exp/s per root.

## Next recommendation

v0.77 should integrate bounded post-Deal rollout into final-Deal root selection
inside the existing whole-game time envelope.
