# proof_aware_tactical_bridge_v0_80

Verdict: `PROOF_AWARE_BRIDGE_FINDS_VIABLE_F4`

Proof-aware hearts cash-out from g141 finds **two F4 states with f=186**
(slack 0): g=161 / h=25 and g=162 / h=24. Frozen continuation from those
roots expands 12 nodes and proof-prunes 181; no F5 and no route below 187.

v0.79's hearts F4 at g=163 / h=29 / f=192 is proof-dead and was not admitted.
Diamonds no longer produce a (dead) F4/F5 once `g+h>186` is enforced.

Canonical 172 was not a search input. Incumbent remains 187.

## g141 verification

Loaded from the v0.78 artefact (not a policy constant).

| fact | value |
| --- | ---: |
| g / F / fd / empty / legal | 141 / 3 / 2 / 2 / 41 |
| h / f / slack | 33 / 174 / **+12** |
| stock / Deal | empty / cannot Deal |
| digest | matches v0.78/v0.79 |

`slack = ceiling - f`. F2 186−172 = **+14** (v0.78 sign bug fixed in v0.79).

## Generic target ranking at g=141

Same `rank_ready_suits` as v0.79. No suit literals in policy.

| rank | suit | already F |
| ---: | --- | ---: |
| 1 | h | 0 |
| 2 | c | 1 |
| 3 | d | 1 |
| 4 | s | 1 |

## Tactical-planner proof hook

`search_foundation_cashout` now accepts optional:

* `lower_bound_fn` → existing `run_search` proof prune `g+h>ceiling`
* `future_cost_key_fn` → extra `target_future` lane `(g+h, h, cover, joins, K, A, gap, −merges, g)`
* `terminal_viability_fn` → production portfolio is VIABLE only

Defaults `None`: v0.71 pre-stock behaviour unchanged. Kernel still records
raw terminals before prune; v0.80 recomputes `h` and refuses `g+h>186`.

## h-cache

Exact cache keyed by `pack_whole_game_identity`. Not part of TT.

| | calls | hits | misses | seconds |
| --- | ---: | ---: | ---: | ---: |
| total | 212,627 | 84,968 | ~128k | ~21 s |

## Stage A (120 s, 200k unique, ceiling 186)

| rank | suit | raw F4 | viable F4 | cheap raw g/f | viable g/f | first viable s | prunes | unique |
| ---: | --- | ---: | ---: | --- | --- | ---: | ---: | ---: |
| 1 | **h** | 8 | **2** | **161 / 186** | **161 / 186** | **48.8** | 11,631 | 27,601 |
| 2 | c | 0 | 0 | — | — | — | 7,365 | 25,743 |
| 3 | d | 0 | 0 | — | — | — | 15,248 | 30,090 |
| 4 | s | 0 | 0 | — | — | — | 16,990 | 30,916 |

Hearts first **viable** F4 at 48.8 s (v0.79 first **raw** F4 was 10.8 s at
g=163 / f=192). TARGET_FUTURE participated (hearts 484 expansions).

Clubs/spades/diamonds: no target foundation. Cover still dropped (c:4, d:3,
s:5) on proof-viable states, but they did not cash out.

v0.79 diamond raw F4/F5 (~g174 / f194) did **not** recur as a live terminal
under the bound — those paths are pruned.

## Stage B

Only hearts had viable F4, so only hearts was promoted (+60 s).

| suit | raw | viable | cheap viable | f | prunes |
| --- | ---: | ---: | ---: | ---: | ---: |
| h | 5 | 1 | 162 | 186 | 4,899 |

Tactical wall 540.5 s ≤ 600. Stage A 480.4, Stage B 60.1.

## Raw vs viable F4/F5

| class | g | h | f | slack | target | time |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| fastest/cheapest **viable** F4 | **161** | 25 | **186** | 0 | h rank 1 | 48.8 s |
| lowest-h viable F4 | 162 | **24** | 186 | 0 | h | Stage B |
| v0.79 raw hearts F4 (dead) | 163 | 29 | 192 | −6 | h | 10.8 s v0.79 |
| v0.79 raw diamond F5 (dead) | 174 | ~21 | ~195 | −9 | d | ~10 s v0.79 |
| viable F5 | none | | | | | |

163+29=192 is classified **RAW / proof-dead** and is not a production root.

## Economics (from g141 h=33 f=174)

Viable F4 g=161 h=25:

* Δg = +20, Δh = −8, Δf = +12
* remaining slack = 0
* ASSEMBLY_PAYBACK = 0.40 (−Δh/Δg)

Viable F4 g=162 h=24: Δg=+21, Δh=−9, payback 0.43.

The original +12 slack is entirely consumed. Any later paid move without a
further h drop is proof-dead.

## Viable production portfolio (2 ≤ 16)

Both `f=186`. No proof-dead roots. Diversity: cheapest g and lowest h, same
target (only viable family).

## Global continuation

359 s requested. 0.81 s used. unique=190, expanded=12, proof-prunes=181,
max F=4, HORIZON 0, no terminal. Slack-0 F4s have almost no legal children
under `g+h>186`.

## Frontiers

**Viable:** F3 g141/h33/f174 slack+12; F4 g161/h25/f186 slack 0; F4 g162/h24/f186 slack 0.

**Raw:** same viable F4s in this run (dead 163/192 class not produced as a
kept terminal once the bound is on).

Best complete g: **187**. No replay. Incumbent/ceiling unchanged.

## v0.79 vs v0.80

| metric | v0.79 | v0.80 |
| --- | ---: | ---: |
| tactical lower-bound pruning | no | **yes** |
| future-cost lane | no | **yes** |
| raw F4 | yes (163/192) | yes (161/186, viable) |
| viable F4 | no | **yes, f=186** |
| raw F5 | yes | no |
| viable F5 | no | no |
| tactical unique | ~75k | ~128k |
| tactical proof prunes | 0 | **56,133** |
| global continuation roots | 16 dead | **2 viable** |
| continuation expansions | 0 | 12 |
| complete | none | none |

## Target-choice interpretation (frozen after the run)

Rank-1 hearts **remains** the only suit that produces a next foundation once
future cost is enforced. Clubs/spades did not become F4 winners despite
better v0.79 cover/h progress. Second-diamond's v0.79 cascade was
proof-dead and disappeared. Next-foundation choice still matters, but
**viability**, not speed, is the filter.

## 187 route (after freeze, evaluation only)

F3 g=175 / h=11 / f=186; next F4 diamonds rank 1, g=179 / h=8 / f=187, Δg=4.
That F4 is itself outside ceiling 186, as expected for a 187 finish. Not used
in v0.80 search.

## Tests

Default cash-out unchanged; v0.71 synthetic fixture; optional lower-bound
passthrough; 163+29 dead; viable f≤186 portfolio; equal Stage A; Stage B max
two; slack convention; canonical firewall; 187 replay. Plus v0.71/v0.79
regressions.

## Interpretation

Proof-aware targeting converts the v0.79 “fast dead F4” into a **slack-0
viable F4** (g=161, h=25). Hierarchical cash-out still works, and the
assembly bound now participates. Because slack is exhausted at F4, global
search cannot step to F5 without an h drop that this continuation did not
find. The g141 line is no longer an F3 stall; it is an **F4 slack-0 ridge**.

## Next recommendation

Repeat hierarchical decomposition from these **viable** F4 states (g=161/162,
f=186), searching for an F5 that reduces h. Do not resume proof-dead 163/192
roots, do not add wall time, and do not copy canonical 172.
