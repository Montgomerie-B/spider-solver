# f3_tactical_bridge_v0_79

Verdict: `F3_TACTICAL_BRIDGE_DEEP_ENDGAME`

Hearts and second-diamond target probes from the exact v0.78 g141 F3 reach
F4 (g=163) and F5 (g=174). Concentrated continuation then proof-prunes every
admitted root: all have `g+h ≥ 192 > 186`. No complete route below 187.

Not a whole-game opening campaign. Canonical 172 was not a search input.
Incumbent remains 187.

## Slack convention

`slack = ceiling - f` (not `f - ceiling`).

| state | g | h | f | ceiling | slack |
| --- | ---: | ---: | ---: | ---: | ---: |
| F2 post-SD5 | 129 | 43 | 172 | 186 | **+14** |
| F3 g141 | 141 | 33 | 174 | 186 | **+12** |
| cheapest F4 | 163 | 29 | 192 | 186 | −6 |

The v0.78 report printed F2 slack as −14; that was telemetry sign, not a
bound-semantics defect. Assembly prune remains `g+h > 186`.

## g141 root verification

Loaded from `docs/research/g128_focused_endgame_v0_78.json` (not a policy
constant). Unpacked and recomputed:

| fact | v0.78 record | recompute |
| --- | ---: | ---: |
| g | 141 | 141 |
| F | 3 | 3 |
| h / f | 33 / 174 | 33 / 174 |
| fd / empty | 2 / 2 | 2 / 2 |
| legal | 41 | 41 |
| boundaries | 28 (harvest `boundaries_total`) | **36** (`visible_runs`) |

Core identity matches. Boundary disagreement is two metrics on the same
digest, not a wrong state. Stock empty, cannot Deal. Founded: c, d, s.

Search used this packed state at absolute g=141. Opening→F3 ancestry was
**not** reconstructed before search (Part 19).

## Materially-ready ranking at g=141

`rank_ready_suits(state, g=141)` — no suit literals in policy.

| rank | suit | already F | cover | blockers | K | A | gap | merges | buried | exposed |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | h | 0 | 3 | 61 | 6 | 2 | 5 | 0 | 8 | 2 |
| 2 | c | 1 | 7 | 40 | 0 | 16 | — | 0 | 3 | 3 |
| 3 | d | 1 | 10 | 41 | 14 | 6 | 11 | 1 | 8 | 2 |
| 4 | s | 1 | 10 | 53 | 2 | 0 | 11 | 0 | 9 | 1 |

## Stage A (60 s, 100k unique, ceiling 186, equal)

| rank | suit | F4 | cheapest g | first s | terminals | unique | exp | min h | min f |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | **h** | **yes** | **163** | **10.8** | 768 | 12,912 | 2,048 | 27 | 174 |
| 2 | c | no | — | — | 0 | 15,907 | 3,014 | 17 | 174 |
| 3 | **d** | **yes** | **174** | **10.5** | 361 | 16,998 | 2,045 | 16 | 174 |
| 4 | s | no | — | — | 0 | 15,598 | 1,724 | 22 | 174 |

First F4: hearts, g=163, 10.8 s. No Deal in any tactical path.

Clubs/spades made structural progress (min cover 2 / 5) but no target
foundation. Other-suit completions do not count as that target's terminal.

## Stage B (top 2 families +60 s)

Promoted generically: **h, d** (the two F4 families).

| suit | F4 | cheapest g | first s (this run) | terminals | unique |
| --- | --- | ---: | ---: | ---: | ---: |
| h | yes | 163 | 10.4 | 777 | 13,023 |
| d | yes | 174 | 10.5 | 348 | 16,708 |

Stage B did not improve cheapest g or h versus Stage A. Kernel resume of
Stage A frontiers is not exposed; probes restarted from g141.

Tactical wall 362.9 s (A 242.9 + B 119.9) vs 360 s nominal; each probe's
`time_limit_s` was 60 s, extra is setup overhead.

## F4/F5 portfolio (16 unique)

Cheapest hearts F4: g=163, h=29, f=192, slack −6, fd=2, legal=11.

Cheapest diamond cascade F5: g=174, h=20–21, f=194, slack −8, fd=1.

Diversity: both successful targets, cheapest g, lowest h, highest mobility.
No F3 fillers. Cap 16.

## Remaining-time continuation

537 s requested. Actual 0.06 s. unique=16, expanded=0, proof-prunes=16
(F4: 8, F5: 8). HORIZON 0. Every root fails `g+h > 186`.

## F3–F8 frontier

| F | g | h | f | slack | fd | empty | legal | provenance | t |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 3 | 141 | 33 | 174 | +12 | 2 | 2 | 41 | v0.78 cheapest F3 | 0 |
| 4 | 163 | 29 | 192 | −6 | 2 | 0 | 11 | tactical hearts | 10.8 s Stage A |
| 5 | 174 | 21 | 195 | −9 | 1 | 0 | 7 | tactical 2nd diamonds | 10.5 s Stage A |
| 6–8 | — | — | — | — | — | — | — | pruned | — |

No complete terminal. No terminal lineage. Best complete g = **187**.

## v0.78 vs v0.79

| | v0.78 | v0.79 |
| --- | --- | --- |
| root | F2 g129 | F3 g141 |
| allocation | 900 s global | ≤360 s target cash-out + rest continuation |
| unique / exp | 105,020 / 9,762 | tactical ~75k unique; continuation 16 / 0 |
| F3 | 141 | given |
| first F4 | none | **hearts g=163 in 10.8 s** |
| F5 | none | **g=174** (diamond cascade) |
| terminal | none | none |

Hierarchical decomposition **finds** the missing F4. It does not produce a
186-viable F4 (h=29 vs the 187-route F4 h=8).

## 187-route F3→F4 (after freeze, evaluation only)

| | 187 route |
| --- | --- |
| F3 | g=175, h=11, f=186, fd=2, suits d+h+s |
| n_ready | 4 (s, h, d, c) |
| next founded | **diamonds**, operational **rank 1** at that F3 |
| F4 | g=179, h=8, f=187 |
| F3→F4 Δg | **4** |

The incumbent F3 is already highly assembled (h=11). g141 is a cheaper but
much less assembled F3 (h=33). Hearts is unfounded on g141 and is rank 1;
on the 187 F3 hearts is already down. Do not retune v0.79 from this.

## Tests

Slack +14/+12, g141 artefact load, generic ready-target ranking, suit-specific
goal, no Deal, ceiling 186, Stage A/B caps, portfolio ≤16, canonical firewall,
187 incumbent replay. Plus v0.71/v0.78 regressions.

## Interpretation

Stock-empty endgame **does** benefit from the same hierarchical move that
worked before SD5: fix a foundation objective, cash it, reassess. Two of
four ready suits produce F4/F5 in ~10 s; two do not — next-foundation choice
matters. The resulting boards are assembly-dead at 186, so the next
abstraction is **F4 quality (h)**, not another pre-Deal heuristic.

## Next recommendation

Repeat tactical next-foundation decomposition at these F4/F5 states, but
select/retain only descendants that reduce assembly h. Do not add wall time
and do not copy canonical 172.
