# g128_focused_endgame_v0_78

Verdict: `G128_FOCUSED_SEARCH_LIMITED`

F3+ frontier still live at 900 s; terminal unresolved.

Rollout assessment: `LONG_SEARCH_STILL_INCONCLUSIVE`

No complete route. The 30-second F3 signal reproduced exactly, and a cheaper
F3 (g=141) appeared by 90 s, but F4+ never arrived.

This is a focused stock-empty search from the autonomous v0.71 g128 tactical
F2. No whole-game campaign. Canonical 172 was not a search input.

## Autonomy

1. opening → g123 is the replay-valid 187 incumbent rows=1 checkpoint
   (`n_prefix=127`, digest equals the v0.71 tactical root).
2. g123 → g128 is the stored generic v0.71 tactical planner continuation:
   five tableau actions, rank-1 target `d`, no Deal, Δg=5.
3. SD5 is one real engine Deal (cost 1). v0.78 only evaluates that future.

No human moves. No canonical suffix.

## g123 / g128 / post-SD5

| | g | F | fd | rows | digest |
| --- | ---: | ---: | ---: | ---: | --- |
| 187 rows=1 checkpoint | 123 | 1 | 2 | 1 | equals v0.71 `tactical_root` |
| v0.71 tactical F2 | 128 | 2 | 2 | 1 | equals stored continuation; ≠ 187 F2 |
| post-SD5 root | 129 | 2 | 2 | 0 | equals v0.76 `tactical_f2_g128` |

Post-SD5 facts (authoritative now, matches v0.76):

* Deal legal, cost 1, absolute g=129
* legal = 5, empty = 0, visible components / boundaries = 47
* assembly h = 43, f = 172
* SPS1 identity recorded separately from ordered pack_state

## Envelope

* 900.3 s / unique 105,020 / expanded 9,762 / generated 253,066
* 10.8 states/s / peak RSS 137 MiB / abort 2560 MiB
* ceiling 186 / unique cap 800,000
* stop `time limit` / max F=3 / solution_g none
* no Deal, no tactical cash-out, no continuation table, no 187/192 suffix
* HORIZON expansions = 0
* incumbent unchanged at 187

## Snapshots

Mid-run unique/expanded/prunes are 0: `abort_when` sees the epoch object
before those counters are published. Frontier times are from harvest and
are reliable. End-of-run counters are complete.

| t | max F | cheapest F3 g/f | first ΔF | min h | min f | mobility | bounds |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 10 s | 2 | — | — | 23 | 172 | 68 | 18 |
| 30 s | 3 | **158 / 180** | 10.9 s / g=158 | 16 | 172 | 153 | 11 |
| 60 s | 3 | 158 / 180 | same | 16 | 172 | 153 | 11 |
| 120 s | 3 | **141 / 174** (at 90.1 s) | same | 16 | 172 | 153 | 11 |
| 300 s | 3 | 141 / 174 | same | 16 | 172 | 153 | 11 |
| 900 s | 3 | 141 / 174 | same | 16 | 172 | 153 | 11 |

v0.76 30 s reference: F3 ≈ g158 / f180 at ~10 s. **Reproduced** (10.9 s, g=158, f=180).

## F2–F8 cheapest frontier

| F | g | h | f | slack | fd | empty | legal | bounds | t s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 129 | 43 | 172 | **+14** | 2 | 0 | 5 | 47 | 0.0 |
| 3 | **141** | 33 | 174 | 12 | 2 | 2 | 41 | 28 | 90.1 |
| 4–8 | — | — | — | — | — | — | — | — | — |

Cheapest F3 (g=141) and first F3 (g=158 at 10.9 s) are different states.
The first-F3 node matches the v0.76 short rollout. The later cheaper F3 is
a different branch.

No complete terminal. No terminal lineage.

## Lanes / assembly

| lane | expansions |
| --- | ---: |
| reveal | 2,009 |
| readiness | 1,986 |
| construction | 1,955 |
| completion | 1,686 |
| economy | 1,392 |
| cost | 734 |
| horizon | **0** |

Proof-prunes **59,640** (F2: 56,228; F3: 3,412) / calls 115,086 / 23.4 s.
min h=16, min f=172, max h=44. Reconcile ok.

## Comparison with v0.74 focused 187-root

| | v0.74 from post g=130 h=41 f=171 | v0.78 from post g=129 h=43 f=172 |
| --- | --- | --- |
| time to first F3 | 368 s (cheapest F3=156) | **10.9 s** (g=158 / f=180) |
| cheapest F3 | 156 / h27 / f183 | **141 / h33 / f174** |
| F4 | 175 | none |
| F5–F7 | 180, 183, 186 | none |
| F8 / terminal | 187 | none |
| proof-prunes | 65,969 | 59,640 |
| unique / exp | (focused 900 s, solved) | 105,020 / 9,762 |

g128 is a **better F3 factory** than the 187 root and a **worse F4+ converter**
in this 900 s window.

## Short-rollout predictiveness

The v0.76 30 s ranking was not a false alarm: the same F3 (g=158 / f=180)
appears at the same time under concentrated search. Continuing the search
then found an even cheaper F3 (g=141), beating v0.74's F3=156.

It did **not** predict a complete route below 187, nor F4+. Short rollout
is a valid selector for early conversion. It is not yet a proven proxy for
terminal cost.

## Incumbent / continuation table

Incumbent remains **187**. Ceiling remains **186**.
`RECORD_MW=119`, `CANONICAL_MW=172` unchanged.
No v0.78 solution file. Continuation table not used during search and not
updated.

## Interpretation

The g128 tactical F2 is a real, reconstructable autonomous state whose
short-horizon conversion is exactly as the v0.76 pilot claimed. Nine hundred
seconds of the same policy that solved 187 from the sibling F2 root reached
a cheaper F3 and then stalled. The missing piece is F3→F4 conversion on
this board, not another pre-Deal heuristic and not another whole-game
900 s campaign.

## Next recommendation

Improve stock-empty conversion efficiency on this g128-derived F3
continuation (assembly / concentration), not total wall time and not
canonical 172.
