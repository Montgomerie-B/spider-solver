# state_convergence_endgame_v0_74

Verdict: `STATE_CONVERGENCE_ENDGAME_COST_IMPROVED`

Exact autonomous state-convergence spliced at 191, then a focused stock-empty
search from F2+Deal independently completed at **g = 187**.

## Why this remains autonomous

The two 191-splice portions were independently solver-generated.

- Prefix (v0.73): whole-game strategic search, machine-incumbent checkpoint,
  generic maturity-aware root selection, generic rank-1 tactical target,
  bounded tactical planner. No canonical input.
- Suffix (v0.67): autonomous stock-empty solver. No canonical route.

They were spliced only because the complete F2 states are byte-identical.
No human or canonical move was inserted. That is ordinary exact-state
transposition: a cheaper path to an existing node inherits any legal suffix.

The 187 continuation is a second autonomous step. After promoting the 191
splice, search started from the exact post-SD5 game state. The old suffix was
not a search target, move-ordering hint, or forced continuation.

## 192 verification

- ok, g=192, five Deals, solved, stock empty, tableau empty

## Exact old F2 splice point

- unique match (n_hits=1)
- action_index=133, n_prefix=134, n_suffix=63
- g=130, rows=1, fd=2, F=2, suits=Spades+Diamonds
- digest equals the v0.73 F2 digest

## g129 prefix reconstruction

- reconstructed from stored v0.73 ancestry: 192 rows=1 checkpoint (g=123)
  plus deterministic tactical cash-out (target=d, 6 tableau actions)
- replay g=129, rows=1, fd=2, F=2, digest match

## 191 splice replay

- legal, five Deals, g=191, eight foundations, stock empty, tableau empty, solved
- splice digest match at g=129
- suffix state sequence matches the 192 suffix with absolute g exactly one lower
- suffix cost=62; expected 129+62=191; n_prefix=133, n_suffix=63, n_spliced=196
- preserved as `solutions/4925153_autonomous_v0_74_splice191.moves`

## Focused root (F2 + real engine Deal)

- pre-SD5 g=129, rows=1
- post-SD5 g=130, rows=0, F=2, fd=2, legal=5, boundaries/components=45, h=41, f=171, slack_190=19
- immediate-Deal digest equals old F2+Deal (old absolute g=131)
- the 192 route does **not** Deal immediately: five tableau moves, then Deal at suffix index 5, old g=135
- that later post-SD5 board is different; it was not the search root
- old suffix unavailable to search (`incumbent_by_rows={}`, `epoch_augment_fn=None`)

## Focused envelope

- 900 s / 800k unique / 2.5 GiB / no Deal / absolute ceiling 190
- root g not reset (absolute g=130)
- lanes: COST, REVEAL, CONSTRUCTION, READINESS, ECONOMY, COMPLETION
- HORIZON inactive (0 expansions)
- exact cheapest-g TT, SPS1/post-stock identity, v0.67 assembly bound, proof prune g+h>190

## Search totals

- unique=110583 expanded=9421 generated=274649
- elapsed=900.1 s stop=solved maxF=8 states/s=10.47
- solved g=187 replay_ok=true replay_g=187 five Deals
- terminal found at t≈246 s; search continued after solve and did not beat 187

## Lane expansions

| lane | expansions |
| --- | ---: |
| cost | 813 |
| reveal | 1985 |
| construction | 1920 |
| readiness | 1581 |
| horizon | 0 |
| economy | 1308 |
| completion | 1814 |

## Assembly proof-prunes

- calls=123222 seconds=22.84 prunes=65969
- prunes_by_F: F2=57561 F3=5749 F4=1945 F5=482 F6=190 F7=42
- min_h=1 max_h=42 min_f=171 slack at root=19
- telemetry reconciles

## F2–F8 cheapest-g frontier (absolute g, assembly h, f, slack under 190)

| F | g | h | f | slack | fd | empty | legal | bounds | t (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 130 | 41 | 171 | 19 | 2 | 0 | 5 | 35 | 0.01 |
| 3 | 156 | 27 | 183 | 7 | 2 | 1 | 30 | 21 | 368 |
| 4 | 175 | 13 | 188 | 2 | 2 | 3 | 109 | 8 | 308 |
| 5 | 180 | 9 | 189 | 1 | 1 | 2 | 45 | 3 | 26 |
| 6 | 183 | 4 | 187 | 3 | 0 | 5 | 84 | 1 | 245 |
| 7 | 186 | 1 | 187 | 3 | 0 | 8 | 105 | 0 | 246 |
| 8 | 187 | 0 | 187 | 3 | 0 | 10 | 0 | 0 | 246 |

## Inherited 191 suffix foundation progression (evaluation only, not seeded)

| F | g | h | f |
| --- | ---: | ---: | ---: |
| 2 | 129 | 0 (rows=1) | 129 |
| 3 | 184 | 7 | 191 |
| 4 | 186 | 5 | 191 |
| 5 | 188 | 3 | 191 |
| 6 | 189 | 2 | 191 |
| 7 | 190 | 1 | 191 |
| 8 | 191 | 0 | 191 |

The inherited suffix is tight: every post-stock foundation sits at f=191.
The focused search's cheapest F3 is g=156 versus inherited 184 (Δ28).

## Promoted incumbent

- best complete g=187
- files: `solutions/4925153_autonomous_v0_74.moves` and `..._v0_74_best.moves`
- AUTONOMOUS_INCUMBENT_MW=187, ceiling=186
- RECORD_MW=119 and CANONICAL_MW=172 unchanged
- no canonical input

## 187 checkpoints (replace 192 as current control; 192 artefacts kept)

| rows | g | F | fd |
| --- | ---: | ---: | ---: |
| 5 | 0 | 0 | 44 |
| 4 | 33 | 0 | 18 |
| 3 | 65 | 0 | 10 |
| 2 | 74 | 1 | 9 |
| 1 | 123 | 1 | 2 |
| 0 | 130 | 2 | 2 |

rows=0 is the focused F2+Deal root, not the 191 splice's later Deal at g=134.

## v0.73 integrated vs focused endgame

v0.73 rows=0 epoch (measured):

- input_roots=264
- alloc/elapsed≈205.5 s
- expanded=1351 generated=20488 unique=12627
- maxF=2 min_g=6 (cheap early-deal-to-empty-stock roots in the portfolio)
- stop=time limit
- tactical hook not used at rows=0

Focused rows=0:

- input_roots=1 (the exact cheaper post-SD5 state)
- 900 s, expanded=9421 unique=110583 generated=274649
- maxF=8 min_f=171 proof-prunes=65969
- solved at 187

Causes, from telemetry not speculation:

1. **256-root dilution** — 264 mixed post-Deal roots versus one exact F2+Deal root.
2. **Too little stock-empty time** — 206 s versus 900 s.
3. **Transition portfolio competition** — min_g=6 shows cheap whole-game Deal-now
   descendants consumed the rows=0 budget; the tactical F2 was not the sole root.
4. **Ceiling/ordering interaction** — v0.73 ceiling 191 with a diluted portfolio
   never left F2; the focused run's COMPLETION lane (1814 expansions) and proof
   pruning (65969) could operate on the actual endgame.

## Interpretation

Spider continuation is state-based. The cheaper autonomous path to the incumbent
F2 is a legal transposition. Immediate Deal from that F2, rather than the old
suffix's five preparatory tableau moves, is a different stock-empty node. From
that node the frozen endgame machinery found a complete continuation at 187,
four corrected MW inside the 191 splice and five inside the previous 192
incumbent. The saving appears as much earlier F3 conversion (156 vs 184), not
as a new heuristic.

## Next recommendation

187 is the autonomous incumbent. Return to whole-game optimisation with ceiling 186.
