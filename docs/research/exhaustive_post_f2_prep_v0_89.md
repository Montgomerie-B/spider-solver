# exhaustive_post_f2_prep_v0_89

Verdict: `EXHAUSTIVE_PREP_FINDS_SUPERIOR_ROOT`

A Δg=2 / f=172 high-mobility prepared post-SD5 state ranked above Root A immediate Deal on the frozen v0.76 rollout key (both reached F3; the prepared root converted at lower f). No post-Deal state in the complete archive has f<171. Incumbent 187 is unchanged.

Branch: `agent/exhaustive-post-f2-prep-v0-89`  
Base: `03c472fb74b92dc44c714ca2866d37fc2118cfd2`  
Archive mode: `ARCHIVE_REGENERATED`. `ARCHIVE_EVAL=ALL`.

## Archive

v0.88 JSON stored counts and an 80-eval *sample*, not 87,527 digests, so the preparation searches were regenerated with frozen v0.88 semantics (150 s × 2, Δg≤15, tableau only, `pack_state` identity).

| | this run | v0.88 |
|---|---:|---:|
| Root A | 51,512 | 50,119 |
| Root B | 37,715 | 37,408 |
| total | 89,227 | 87,527 |

Difference +1,700 (+1.94%). Both harvests stopped on `time limit`. A prior crash-run of the same contract produced 88,030. The population is the same time-bounded search, not a retuned one. `archive_totals_ok=True`.

- pre-Deal F3+: **0**
- Deal-legal evaluations: **89,227** (illegal=0)
- unique post identities: **86,416**
- convergence max=2, mean=1.03
- proof-viable=85,460 / proof-dead=956
- eval/s=430.6; Deal=23.6 s; h=26.6 s; dedup=0.3 s
- h-cache: calls=86,418 hits=2 misses=86,416 seconds=20.85
- peak RSS=1,484 MB

## Any f<171?

**No.** Exhaustive min_f=171. The v0.88 sampled claim is now confirmed on the full generated archive.

## f distribution (unique post identities)

| bucket | n |
|---|---:|
| ≤169 | 0 |
| 170 | 0 |
| 171 | 8 |
| 172 | 105 |
| 173 | 513 |
| 174 | 1,272 |
| 175–176 | 5,757 |
| 177–180 | 26,715 |
| 181–186 | 51,090 |
| >186 | 956 |

Root A holds 4 of the 8 f=171 states; Root B holds 4. All f=171 states have prep band `0` or `1-2`. Expensive prep (band 10–15) occupies almost all of f=181–186 and all 956 proof-dead states.

## f=171 analysis (all 8 unique post identities)

- sources: NEW_G128_F2=4, INCUMBENT_G129_F2=4
- bands: 0=4, 1–2=4
- (g,h): (129,42), (130,41), (131,40)
- legal 5–6; empties 0; visible_runs 44–46; mixed-suit boundaries 34–36

Same-f171 topologies exist (legal=6 vs control legal=5; h=40 vs 42) but did not beat Root A immediate Deal in Stage A (they stayed at maxF=2).

## Absolute best unique post states

- lowest f / lowest g / greatest slack / greatest F / most empties: Root A family, post g=129 / h=42 / f=171, legal=5, empties=0
- lowest h / lowest mixed / lowest visible_runs: Δg=15 Root A prep, post g=144 / h=36 / f=180, legal=9, mixed=30, runs=40
- greatest mobility: Δg=12 Root B prep, post g=142 / h=39 / f=181, legal=13

Static best f is still immediate-Deal class. Topology extrema sit at much worse f.

## Pareto vs v0.88 sample

Exhaustive proof-viable Pareto size=**38**.

v0.88 did not persist the 80 evaluated post-digests. Comparison uses the 12 unique post_digests that *were* persisted (`selected` + `pareto` + controls).

- captured by persisted sample: 3
- missed: 35
- globally best f sampled: **yes**
- highest-mobility f=171 sampled: **yes**
- materially promising f=172 mobility root: **not** in the persisted 12

The 80-state selection method kept the static f=171 controls and missed most of the exhaustive Pareto, including the f=172 mobility state that later ranked first on rollout.

## Rollout

16 live unique roots; known-closed hits=0; lower-g reopenings=0.

Stage A (10 s each):

| role | source | Δg | post g/h/f | legal | maxF | min_f |
|---|---|---:|---|---:|---:|---:|
| immediate_deal | Root A | 0 | 129/42/171 | 5 | **3** | 171 |
| immediate_deal | Root B | 0 | 130/41/171 | 5 | 2 | 171 |
| lowest_f | Root A | 0 | 129/42/171 | 5 | 3 | 171 |
| f171_mobility | Root A | 1 | 130/41/171 | 6 | 2 | 171 |
| f171_topology | Root B | 1 | 131/40/171 | 6 | 2 | 171 |
| **f172_mobility** | Root A | 2 | 131/41/172 | 10 | **3** | 172 |
| f172_topology | Root A | 4 | 133/39/172 | 7 | 2 | 172 |
| highest_mobility | Root B | 12 | 142/39/181 | 13 | 2 | 181 |
| lowest_mixed | Root A | 15 | 144/36/180 | 9 | 3 | 180 |
| pareto_balanced | Root A | 13 | 142/37/179 | 9 | 2 | 179 |

Stage B (4 × 20 s): all four promoted roots remained maxF=3. Continuation of 24 descendants, 144.8 s, stop=`time limit`, unique=19,404, maxF=4. Not solved.

Root A immediate Deal still reaches F3 in 10 s. The Δg=2 f=172 legal=10 state also reaches F3 and ranks strictly better on the frozen key (F3 at lower f / better mobility, not cheaper starting g). That is a same-or-worse static f with stronger short-horizon conversion — the case Part 13/14 asked to keep.

## Closed / continuation / incumbent

- known-closed hits: 0
- lower-g reopenings: 0
- retained continuation roots: 24
- F2–F8 frontier: maxF=4 (no F5–F8)
- best complete g: none (unsolved)
- incumbent 187 / ceiling 186 unchanged
- RECORD_MW=119, CANONICAL_MW=172 unchanged
- canonical 172 was not a search input

## Interpretation

Within the entire generated Δg≤15 post-F2 preparation population, **no state produces post-Deal f<171**. Immediate Deal remains the static f minimum. Same-f171 alternatives did not beat Root A on short rollout.

However a nearby f=172 high-mobility preparation *did* outrank Root A immediate Deal on the frozen rollout key and is therefore a live focused endgame control. This is not `SEARCH_LIMITED` merely because harvest was time-capped; the generated archive was evaluated exhaustively. Continuation of the winner remains time-limited at F4.

## Next recommendation

Make the prepared post-SD5 f=172 mobility state the next focused endgame control. Do not move upstream yet.
