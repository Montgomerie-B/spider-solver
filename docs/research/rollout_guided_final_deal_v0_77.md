# rollout_guided_final_deal_v0_77

Verdict: `ROLLOUT_GUIDED_REACHES_DEEP_ENDGAME`

Integrated whole-game search from the untouched opening reached **F3 at g=169**
from a rollout descendant. v0.75 stopped at F2. No replay-valid terminal below
187. Best complete remains the autonomous incumbent **187**.

Canonical 172 was not used for prefiltering, candidates, ranking, portfolio, or
main search. After freeze, a 10-second Stage-A-like canonical rollout still
dominates the machine keys (F3 at g=158 / f=170 in 6.2 s).

## Integrated architecture

Whole-game `search_rollout_guided` = v0.75 continuation table + v0.73
maturity-aware tactical cash-out at rows=1 + **staged final-Deal rollout**.

1. Epochs rows=5..2 unchanged (COST / REVEAL / CONSTRUCTION / READINESS /
   HORIZON / ECONOMY). No rollout before the final Deal.
2. Rows=1: ordinary strategic search, state-derived tactical maturity,
   incumbent/control slot, rank-1 cash-out, ordinary harvest, exact Deal
   preview. Rank-2/3 readiness lanes stay off.
3. After harvest: diversity prefilter of at most **8** Deal-legal rows=1 roots.
4. Exact Deal. Frozen v0.76 rollout policy. No continuation suffixes, no
   tactical cash-out, no Deal, ceiling 186, absolute g retained.
5. Stage A: 10 s × 8. Stage B: +10 s on the top 4 by the frozen rollout key.
   Reservation ≤120 s from the 900 s envelope (scheduler: `min(120, remain-60)`
   at rows=1 allocation, then `min(120, remain_wall)` at the transition).
6. Descendants kept with packed state, absolute g, parent root, full action
   path from the opening. SPS1 identity for search dedup; ordered ancestry for
   replay.
7. Rows=0 portfolio: target 32, hard max 64. Majority rollout descendants plus
   a few original post-Deal controls. Remaining wall-clock time, no HORIZON,
   proof prune `g+h > 186`.

`search_integrated_tactical` is unchanged and does not call the guided
transition (v0.76 source firewall).

## Whole-game envelope

| | |
| --- | ---: |
| wall | 900.3 s |
| unique cap | 800,000 |
| unique used | 128,444 |
| expanded | 30,026 |
| generated | 267,004 |
| states/s | 33.4 |
| ceiling | 186 |
| RSS abort | 2560 MiB |
| stop | time limit |
| max F | 3 |
| solution_g | none |
| peak RSS | not retained in slim telemetry; no RSS abort |

Rollout unique is counted from **separate** TT instances (Stage A/B) and added
into the global counter, so A/B/main may overlap. Report both:

| bucket | unique | expanded |
| --- | ---: | ---: |
| Stage A sum (8 independent searches) | 7,436 | 1,019 |
| Stage B sum (4 independent searches) | 3,978 | 345 |
| rows=0 main | 9,657 | 580 |
| cumulative whole-game | 128,444 | 30,026 |

## Wall-time split

| phase | elapsed s | expanded | unique | max F | roots |
| --- | ---: | ---: | ---: | ---: | ---: |
| rows=5 | 112.5 | 7,026 | 22,764 | 0 | 1 |
| rows=4 | 112.5 | 2,391 | 23,195 | 0 | 149 |
| rows=3 | 192.8 | 9,203 | 27,350 | 1 | 154 |
| rows=2 | 160.6 | 7,566 | 22,532 | 1 | 249 |
| rows=1 strategic | 96.3 | 1,064 | 7,756 | 1 | 256 |
| rows=1 tactical | 16.2 | — | — | found 1 | 7 probes, control slot used |
| candidate prep + Deal | ~2.8 of rollout | — | — | — | 8 |
| Stage A | 80.0 | 1,019 | 7,436 | 2 | 8 |
| Stage B | 38.6 | 345 | 3,978 | 2 | 4 |
| rollout total | 121.4 | — | — | — | budget 120 |
| rows=0 main | 85.1 | 580 | 9,657 | 3 | 33 |
| canonical eval | 10 s after freeze | — | — | 3 | 1 |

Pre-final epochs 5–2: **578.4 s**. Rollout 121.4 s is 13.5% of 900 s (under the
28% overhead-failure threshold). Rows=0 received all remaining wall time.

## Prefilter and eight Stage A roots

Harvest rows=1 pool: **264**. Selected **8**. Exact-identity dedup. Not the
eight cheapest g.

| role | pre g | post g | F | fd | legal | h | f | tactical | ckpt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| tactical_cashout | 130 | 131 | 2 | 2 | 5 | 41 | 172 | d | yes |
| incumbent | 75 | 76 | 1 | 9 | 5 | 57 | 133 | — | yes |
| post_deal_operational | 132 | 133 | 1 | 2 | 5 | 42 | 175 | — | yes |
| post_deal_consolidation | 116 | 117 | 0 | 7 | 10 | 38 | 155 | — | no |
| post_deal_mobility | 105 | 106 | 0 | 7 | 12 | 44 | 150 | — | no |
| post_deal_reception | 112 | 113 | 0 | 7 | 12 | 40 | 153 | — | no |
| post_deal_pareto | 6 | 7 | 0 | 43 | 5 | 96 | 103 | — | no |
| cheap | 5 | 6 | 0 | 43 | 5 | 96 | 102 | — | no |

The incumbent **slot** is an early checkpoint Deal (pre g=75 F1), not the
actual 187 pre-SD5 g=129 F2. The 187-class F2 arrived as `tactical_cashout`
(pre 130 / post 131 / h=41 / f=172 / legal=5 / fd=2). That is the same static
class as the 187 control (post 130 / h=41 / f=171), **not** the historical
v0.71 g128 board (post 129 / h=43 / f=172).

## Stage A (10 s / root, equal budget)

Ranking by frozen v0.76 key:

1. tactical_cashout
2. post_deal_operational
3. incumbent
4. post_deal_consolidation
5. post_deal_reception
6. cheap
7. post_deal_pareto
8. post_deal_mobility

| rank | role | max F | g/f at max F | first ΔF | min h | mobility | descendants | unique |
| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | tactical_cashout | 2 | 131 / 172 | none | 23 | 79 | 65 | 1,050 |
| 2 | post_deal_operational | 2 | 139 / 177 | 5.3 s / +6 | 27 | 91 | 66 | 960 |
| 3 | incumbent | 1 | 76 / 133 | none | 45 | 15 | 65 | 927 |
| 4 | post_deal_consolidation | 1 | 121 / 156 | 0.8 s / +4 | 29 | 30 | 66 | 968 |
| 5 | post_deal_reception | 1 | 121 / 157 | 6.6 s / +8 | 34 | 59 | 6 | 903 |
| 6 | cheap | 0 | 6 / 102 | none | 80 | 13 | 1 | 872 |
| 7 | post_deal_pareto | 0 | 7 / 103 | none | 85 | 13 | 1 | 857 |
| 8 | post_deal_mobility | 0 | 106 / 150 | none | 39 | 37 | 1 | 899 |

Tactical F2 did **not** reach F3 in 10 s (v0.76 g128 did, at ~10 s; v0.76 187
needed ~22.5 s). Operational converted F1→F2 at g=139. Cheap/pareto/mobility
never founded. Static cheap-f fillers remain a poor predictor.

## Stage B (top 4, +10 s, extra_roots = Stage A descendants)

1. tactical_cashout
2. post_deal_operational
3. incumbent
4. post_deal_consolidation

| rank | role | max F | g/f at max F | first ΔF | min h | mobility | descendants | unique |
| ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | tactical_cashout | 2 | 131 / 172 | none | **18** | **118** | 65 | 1,040 |
| 2 | post_deal_operational | 2 | 139 / 177 | **0.06 s** / +6 | 23 | 100 | 66 | 1,141 |
| 3 | incumbent | 1 | 76 / 133 | none | 45 | 15 | 65 | 888 |
| 4 | post_deal_consolidation | 1 | 121 / 156 | 0.02 s / +4 | 30 | 28 | 66 | 909 |

Frontier reuse is visible: operational F2 reappeared at 0.06 s because Stage B
started from Stage A descendants. Tactical still max F=2 but improved h
(23→18) and mobility (79→118). No Stage A/B terminal.

## Frontier reuse → rows=0 roots

Descendants retained (ancestry-verified): 65+66+65+66+6+1+1+1 ≈ 271 across
Stage A; Stage B kept the same compact sets on the four promoted roots.

Admitted to main search: **32** unique roots (scheduler `input_roots=33`).
Hard max 64. Root F distribution: **30 × F2, 2 × F1, 0 × F0**.

This is the opposite of v0.74/v0.75 dilution (264 stock-empty roots, max F2).
F0 cheap boards were not refilled to width 256.

F3 at g=169 carries `lineage=['rollout_descendant']` and appears at t=817 s,
i.e. at rows=0 start (~815 s). The main epoch therefore **began from** a
rollout descendant rather than rediscovering F3 from the raw post-Deal root.

## Tactical g128-class root

| | v0.71/v0.76 g128 | v0.77 autonomous tactical |
| --- | --- | --- |
| pre g | 128 | 130 |
| post g | 129 | 131 |
| F / fd / legal | 2 / 2 / 5 | 2 / 2 / 5 |
| h / f | 43 / 172 | 41 / 172 |
| target | d | d |
| same digest as v0.71 | — | **no** (187-class, `from_incumbent_ckpt`) |
| Stage A | F3 at 158 / f=180 in 10 s | F2, min h=23, no ΔF |
| Stage B | (pilot was 30 s flat) | F2, min h=18, mobility 118 |
| rollout rank | 1 of 8 (pilot) | **1 of 8** (integrated) |
| descendants admitted | n/a (pilot discarded) | yes; F3 g=169 in main |
| final conversion | unknown (pilot) | F3=169, no F4+ |

The g128-style cheaper F2 was **not** rediscovered. A 187-class F2 was, ranked
first, reused, and converted one foundation further than v0.75.

## 187 control

| | known 187 | v0.77 slot |
| --- | --- | --- |
| actual pre-SD5 | g=129 F=2 fd=2 | incumbent **slot** g=75 F=1 fd=9 |
| actual post-SD5 | g=130 h=41 f=171 legal=5 | tactical slot g=131 h=41 f=172 legal=5 |
| remaining after SD5 | 57 | unknown for this sibling |
| Stage A | F3 at 172 / 186 in 22.5 s (v0.76 30 s) | tactical: no F3 in 10 s |
| Stage B | — | tactical promoted, still F2 |
| portfolio | — | 187-class F2 descendants dominate F2 roots |
| main continuation | v0.74 focused: F8=187 | F3=169 in 85 s, no cheaper complete |

The current incumbent solution was not improved. The early-checkpoint
incumbent slot (g=75) did not convert; it was retained as a control F1 root.

## Rows=0 concentration vs v0.75 / v0.73

| | v0.75 whole-game | v0.77 |
| --- | --- | --- |
| stock-empty roots | 256-class mixture | **32 / 33** |
| rows=0 time | ~205 s diluted | **85.1 s** concentrated |
| rows=0 expanded | (diluted into F2) | 580 |
| rows=0 unique | — | 9,657 |
| max F | 2 | **3** |
| cheapest F2 | 128 rows=1 | 91 rows=0 fd=9 (different class) plus 187-class F2 |
| tactical-origin | F2 g=128 | F2 g=131 (187-class) |
| rollout-descendant roots | 0 | majority of 32 |
| incumbent-control roots | checkpoints | 2 F1 + tactical F2 |

Initial rows=0 f: F2 roots around f=172–177; F3 later f=186. Median F of roots
= 2.

## F1–F8 frontier

| F | g | rows | fd | h/f | legal | provenance | t s |
| ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| 1 | 71 | 3 | 10 | 0/71 | 10 | incumbent checkpoint (same as v0.75) | 226.7 |
| 2 | 91 | 0 | 9 | 44/135 | 28 | `final_deal_rollout` (early-Deal F1 continuation) | 883.1 |
| 3 | 169 | 0 | 2 | 17/186 | 46 | `rollout_descendant` | 817.5 |
| 4–8 | — | — | — | — | — | not reached | — |

Cheapest complete terminal: **187 incumbent only**. No v0.77 solution file.

Do not conflate F2 g=91 (fd=9, early Deal) with the conversion-relevant F2
(fd=2, 187-class) that produced F3.

## Comparison baselines

| | F1 | F2 | F3 | F4+ | complete |
| --- | --- | --- | --- | --- | --- |
| v0.75 integrated | 71 | 128 rows=1 | none | none | 187 incumbent |
| v0.74 focused from g=130 | — | 130 post-SD5 | **156** | F8=187 | **187** |
| v0.76 g128 30 s | — | 129 | **158 / f=180** | none | none |
| v0.76 187 30 s | — | 130 | 172 / f=186 | none | none |
| **v0.77 integrated** | 71 | 91 (fd=9) / 131 class | **169 / f=186** | none | 187 incumbent |

F3 is materially beyond v0.75 and between the 30 s 187 pilot (172) and the
focused v0.74 (156). Not a g128 reproduction.

## Continuation table / assembly bound

* lookups 122,305 / hits 98 / cheaper-prefix **0** / splices **0**
* proof-prunes **7,065** (all at F2) / calls 119,099 / 2.12 s
* reconcile ok
* preview cache: 8,001 calls, hit rate 2.8%

Continuation table stayed active outside rollout. Rollout itself passed
`continuation_table=None`. No cheaper-prefix splice, matching v0.75.

Proof prune `g+h > 186` unchanged. Lanes in the full run still include HORIZON
in pre-final epochs (2,423 expansions); rows=0 uses COST/REVEAL/CONSTRUCTION/
READINESS/ECONOMY/COMPLETION only.

## After-run canonical calibration

Canonical pre-SD5 was **not** a search root. After freeze, 10 s Stage-A-like
from its real Deal:

* post g=150, F=2, fd=1, legal=16, h=18, f=168
* F3 at g=158 / h=12 / f=170 / legal=106 in **6.2 s**
* rollout key would rank **1st** vs every machine Stage A/B signature

Consistent with v0.76 (canonical F5 in 30 s). No policy change.

## Tests

Focused v0.77 tests cover: rows=1-only hook, machine-only selection, canonical
firewall, Stage A/B caps and budgets, frozen key, reservation ≤120 s,
ancestry/absolute g, no continuation suffix in rollout, static root retained
beside descendants, rows=0 ≤64, SPS1 vs replay ancestry, proof prune,
continuation table, 187 incumbent replay.

Regressions: v0.57–v0.76 contracts, rules/MW/metrics, identity, scheduler,
viability, Deal preview, tactical cash-out, continuation table, assembly
bound, canonical accounting.

## Interpretation

Bounded rollout **does** survive integration as a selection signal: the
187-class tactical F2 ranked first, its descendants were reused, and the
narrowed rows=0 phase reached F3 — the first time the 900 s whole-game
envelope has done so. Two gaps remain. First, candidate generation did not
autonomously rediscover the cheaper g128 F2 that converted in 10 s in the
pilot; the selected tactical board is a 187 sibling (post 131 vs 129). Second,
85 s of concentrated continuation from that F2 only reached F3=169, far short
of v0.74's focused F8=187. The bottleneck is now **post-rollout conversion
depth**, not pre-Deal heuristics or 256-wide dilution.

## Next recommendation

Focus next on the best rollout-derived root/continuation rather than adding
another pre-Deal heuristic. Increase search concentration and reuse efficiency
on the 187-class F2 descendants (and keep looking for a g128-class sibling),
not total wall time. Do not copy canonical 172.
