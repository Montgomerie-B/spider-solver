# solution_strategy_forensics_v0_61

Verdict: `FORENSICS_IDENTIFIES_GENERALISABLE_GAP`

Comparative strategy forensics of two independently replayed solutions of
deal 4925153:

| route | file | corrected MW |
|---|---|---|
| autonomous machine | `solutions/4925153_autonomous_v0_59.moves` | **198** |
| canonical expert | `solutions/4925153_canonical.moves` | **172** |

Gap: **26 corrected MW**.

This is analysis only. Search policy is unchanged. No hybrid route, no new
solution file, no 900 s optimisation run. The 172 trace is inspected as a
known cheaper route, not copied into the solver.

Base: `db18b944f9f612c2ab19ec54fde9f15a46b00218`
Branch: `agent/solution-strategy-forensics-v0-61`

---

## 1. Replay contract

Both files independently replayed from untouched deal 4925153.

| check | autonomous | canonical |
|---|---|---|
| every action legal | yes | yes |
| Deals | 5 | 5 |
| corrected MW | **198** | **172** |
| foundations | 8 | 8 |
| stock empty | yes | yes |
| tableau empty | yes | yes |
| `state.is_solved()` | yes | yes |
| physical cards tracked | 104 | 104 |

Contract green. Comparison is valid.

Explicit commands ≠ MW. Autonomous: 208 explicit (203 tableau + 5 Deals),
10 zero-cost tableau. Canonical: 174 explicit (169 tableau + 5 Deals),
2 zero-cost tableau. All economics use corrected g.

---

## 2. Exact epoch cost table

Replay-derived. Deal rows cost 1 each and cancel.

| epoch | 198 Δg | 172 Δg | delta (198−172) | cumulative gap |
|---|---|---|---|---|
| pre-SD1 | 32 | 50 | **−18** | −18 |
| SD1 | 1 | 1 | 0 | −18 |
| SD1–SD2 | 25 | 37 | **−12** | −30 |
| SD2 | 1 | 1 | 0 | −30 |
| SD2–SD3 | 14 | 11 | +3 | −27 |
| SD3 | 1 | 1 | 0 | −27 |
| SD3–SD4 | 10 | 17 | **−7** | **−34** |
| SD4 | 1 | 1 | 0 | −34 |
| SD4–SD5 | 45 | 30 | +15 | −19 |
| SD5 | 1 | 1 | 0 | −19 |
| post-SD5 | 67 | 22 | **+45** | **+26** |
| **total** | **198** | **172** | **26** | **26** |

This table is an exact additive explanation of the 26-MW gap.

The 172 route **spends more** in the opening, SD1–SD2, and SD3–SD4. The
machine’s largest prefix lead is 34 MW entering SD4. The entire net 26 is
realised in SD4–SD5 (+15) and post-SD5 (+45).

Zero-cost commands by epoch: autonomous 3 / 5 / 1 / 0 / 1 / 0; canonical
1 / 0 / 0 / 0 / 1 / 0. Extra free relocations do not explain the cheaper
route.

---

## 3. Observed route remaining cost

`observed_remaining_cost = final_solution_g − current_prefix_g`.

This is **not** an optimal cost-to-go. It is the remaining cost of that
known route.

| boundary | auto g | canon g | auto remaining | canon remaining | remaining gap |
|---|---|---|---|---|---|
| opening | 0 | 0 | 198 | 172 | 26 |
| after pre-SD1 | 32 | 50 | 166 | 122 | 44 |
| after SD1 | 33 | 51 | 165 | 121 | 44 |
| after SD1–SD2 | 58 | 88 | 140 | 84 | 56 |
| after SD2 | 59 | 89 | 139 | 83 | 56 |
| after SD2–SD3 | 73 | 100 | 125 | 72 | 53 |
| after SD3 | 74 | 101 | 124 | 71 | 53 |
| after SD3–SD4 | 84 | 118 | 114 | 54 | **60** |
| after SD4 | 85 | 119 | 113 | 53 | **60** |
| after SD4–SD5 | 130 | 149 | 68 | 23 | 45 |
| after SD5 | 131 | 150 | **67** | **22** | 45 |
| solved | 198 | 172 | 0 | 0 | 0 |

The remaining-cost advantage of the 172 route is already 44 MW after the
opening investment, 56 MW after SD2, and **60 MW** entering the last
stock row — while the machine still has the cheaper prefix g.

---

## 4. Foundation timing

| n | autonomous g / rows / fd / suit | canonical g / rows / fd / suit | observed remaining |
|---|---|---|---|
| 1 | 189 / 0 / 1 / d | **90 / 3 / 8 / s** | auto 9, canon 82 |
| 2 | 190 / 0 / 1 / c | **139 / 1 / 3 / d** | auto 8, canon 33 |
| 3 | 192 / 0 / 0 / s | 158 / 0 / 0 / c | auto 6, canon 14 |
| 4 | 193 / 0 / 0 / h | 168 / 0 / 0 / d | auto 5, canon 4 |
| 5 | 194 / 0 / 0 / h | 169 / 0 / 0 / s | auto 4, canon 3 |
| 6 | 195 / 0 / 0 / c | 170 / 0 / 0 / c | auto 3, canon 2 |
| 7 | 197 / 0 / 0 / d | 171 / 0 / 0 / h | auto 1, canon 1 |
| 8 | 198 / 0 / 0 / s | 172 / 0 / 0 / h | 0, 0 |

Canonical starts removing foundations in the midgame (F1 at stock rows=3,
fd=8; F2 at rows=1, fd=3) and then finishes six foundations in **14 MW**
after SD5 (g 158→172). Autonomous completes **all eight** after SD5,
starting only at g=189, 9 MW from the end.

Earlier foundation is not automatically better. v0.60 already found a
cheaper search F1 at g=41 that did not yield a cheaper whole game. The
distinguisher here is not “F1 happened” but **F1 on an excavated board**
(fd=8, remaining-cost 82) versus a late cascade on a still-tangled board.

---

## 5. Final-Deal comparison (priority)

States immediately after SD5. Remaining MW is calculated, not inferred
from command count.

| | autonomous 198 | canonical 172 |
|---|---|---|
| prefix g | 131 | 150 |
| observed remaining | **67** | **22** |
| post-SD5 tableau commands | 67 | 22 |
| post-SD5 zero-cost | 0 | 0 |
| paid remaining MW | **67** | **22** |
| foundations already removed | 0 | **2** (s, d) |
| face-down | 3 | 1 |
| empty columns | 0 | 0 |
| same-suit bonds | 65 | 54 |
| legal tableau | 12 | 16 |
| n_ready | 4 | 4 |
| longest run | 12 | 11 |
| merge edges | 1 | 1 |

Canonical’s 22 post-SD5 commands happen to equal 22 MW because none are
zero-cost. That equality was measured, not assumed.

Per-suit topology after SD5:

| suit | auto cover / k / a / gap / longest / bonds | canon cover / k / a / gap / longest / bonds |
|---|---|---|
| clubs | 2 / 11 / 2 / 0 / 11 / 16 | 2 / 11 / 2 / 0 / 11 / 17 |
| diamonds | 2 / 7 / 12 / −6 / 12 / 18 | 4 / 9 / 1 / 3 / 9 / 9 (1 already founded) |
| hearts | **7 / 3 / 1 / 9 / 5 / 11** | **3 / 6 / 8 / −1 / 8 / 18** |
| spades | 2 / 1 / 12 / 0 / 12 / 20 | 3 / 2 / 1 / 10 / 10 / 10 (1 already founded) |

Clubs look similar. Hearts do not: the cheaper route has lower cover, a
near-closed K/A gap, and a long A-side. The machine has **more** total
bonds and a 12-long diamond/spade run, and still needs 67 MW. Bond count
and longest run are not the post-stock cost driver.

Empty columns are 0 on both routes at every Deal boundary. Durable
empties do **not** distinguish these two solutions.

---

## 6. Deal reception

Observed landings, plus `heuristics.reception_fitness` as a comparison
number only. Fitness is not treated as ground truth.

| Deal | auto rank_ok / ss / mixed / fit / legal / F / fd | canon rank_ok / ss / mixed / fit / legal / F / fd |
|---|---|---|
| SD1 | **3 / 3 / 7 / 4 / 12 / 0 / 18** | 1 / 1 / 9 / 2 / 8 / 0 / 12 |
| SD2 | 1 / 0 / 9 / 4 / **4** / 0 / 10 | **2 / 2 / 8 / 6 / 12 / 0 / 8** |
| SD3 | 1 / 1 / 9 / 4 / 9 / 0 / 10 | 0 / 0 / 10 / 2 / 7 / **1** / 7 |
| SD4 | **2 / 2 / 8 / 8 / 15 / 0 / 9** | 1 / 1 / 9 / 4 / 10 / 1 / 7 |
| SD5 | 3 / 3 / 7 / 10 / 12 / 0 / 3 | **4 / 4 / 6 / 22 / 16 / 2 / 1** |

Reception is mixed. The machine actually lands SD1 and SD4 better. The
canonical advantage is concentrated at **SD2** (legal 12 vs 4 after Deal)
and **SD5** (fitness 22 vs 10, four same-suit landings, two foundations
already off the board). Receiver-shaping before every Deal is not a
uniform fact of the 172 route.

---

## 7. Rehandling

Conservative definition: a tableau action is tagged `REHANDLE` if any
physical card in the moved run already participated in a prior **paid**
action. Exclusive buckets are mutually exclusive; multi-tags remain on
the action for structural analysis.

| | autonomous | canonical | delta |
|---|---|---|---|
| exclusive REHANDLE MW | 126 | 102 | **+24** |
| tagged rehandle actions (paid) | 133 | 109 | +24 |
| cards paid after first same-suit attach | 85 | 76 | +9 |
| repeat paid movers (≥2) | 93 | 83 | +10 |
| mean paid actions / card | 6.56 | 3.96 | +2.60 |
| mean paid after attach / card | 4.60 | 2.30 | +2.30 |
| cards that ever mixed-park | 79 | 34 | +45 |
| mixed-park exclusive MW | 10 | 7 | +3 |
| exclusive REVEAL MW | 32 | 28 | +4 |

Card-touch counts are diagnostic. They are not MW. One paid action may
move many cards.

Hottest autonomous rehandled identities: `4S#A` (17 paid actions),
`2S#A` (16), `2C#B` (15). Canonical maxima are 13 (`4S#B`, `AC#B`).
Duplicate-rank labels are distinct: `5S#A` and `5S#B` never collapse.

Ambiguous exclusive `OTHER_PAID` is 2 vs 5 MW. Causality that cannot be
tagged is left there rather than forced into rehandle.

---

## 8. Exclusive-bucket waterfall (also exact)

Mutually exclusive paid-MW buckets sum to each route’s g, so their
differences sum to 26.

| bucket | 198 | 172 | delta |
|---|---|---|---|
| DEAL | 5 | 5 | 0 |
| FOUNDATION_TRIGGER | 8 | 8 | 0 |
| REHANDLE | 126 | 102 | **+24** |
| REVEAL | 32 | 28 | +4 |
| MIXED_SUIT_PARK | 10 | 7 | +3 |
| PRIMARY_PROGRESS | 15 | 17 | −2 |
| OTHER_PAID | 2 | 5 | −3 |
| ZERO_COST_RELOCATION | 0 | 0 | 0 |
| **total** | **198** | **172** | **26** |

Fact: the exclusive REHANDLE bucket accounts for 24 of the 26. Caveat:
the tag is conservative-high (any previously paid card in the run). It is
an accounting partition, not a proof that 24 MW of the gap is wasted
motion in the causal sense.

---

## 9. Interpretive breakdown (not forced to 26)

Inference, not an additive identity.

* **Early structural investment.** Canonical spends 18+12+7 = 37 extra MW
  before SD4 (net 34 after the +3 SD2–SD3 recovery) and exits those
  epochs with lower face-down (12 vs 18 pre-SD1; 8 vs 10 at SD2; 7 vs 9
  at SD4) and a remaining-cost lead of 60 MW. That is the “pay now”
  half.
* **Late conversion.** Post-SD5 costs 67 vs 22. Combined with SD4–SD5
  (+15), this is the “cash out” half. Most of the *realised* g overtake
  is post-SD5; most of the *prepaid* remaining-cost lead is already
  present by SD2–SD4.
* **Rehandling.** Exclusive +24 MW is the largest bucket-level signal.
  Mean paid-after-attach is double (4.60 vs 2.30). Mixed-park identities
  79 vs 34. Consistent with “park and rebuild” versus “place once”.
* **Foundation timing.** Midgame F1/F2 on an excavated board, then a
  14-MW six-foundation finish. Not cheap-F1-at-any-cost.
* **Deal reception.** Helpful at SD2 and SD5; not a uniform policy of
  the 172 route (machine is better at SD1 and SD4).
* **Workspace empties.** Not a distinguisher (0 vs 0 at every Deal).
* **Component condensation.** Post-SD5 heart cover/gap is the clearest
  suit-level contrast. Bond count favours the *more expensive* route.

These categories overlap. They are not a second 26-MW identity.

---

## 10. Crossover points

1. **Prefix g.** The machine is cheaper from the opening through SD5
   (lead peaks at 34 MW after SD3–SD4). The only epoch in which
   cumulative g is overtaken is **post-SD5**.
2. **Epoch delta sign.** Canonical first spends *less* in SD2–SD3 (+3 to
   the gap). The large recoveries are SD4–SD5 (+15) and post-SD5 (+45).
3. **Remaining-cost.** Canonical is cheaper from move 0. The remaining
   gap grows to 44 after the opening investment, 56 after SD2, and peaks
   at **60 MW after SD4** — before the g overtake.
4. **Where the 26 is created vs realised.** Created as remaining-cost
   before SD5 (peak 60). Realised as prefix-g overtake after SD5 (45 of
   the epoch delta; 15 already spent in SD4–SD5 reducing the 34-MW lead
   to 19, then 45 more to finish at +26).
5. **Step-change Deal.** SD5 is the conversion cliff (remaining 67 vs
   22). SD2 is the earliest structural cliff (legal 4 vs 12, remaining
   139 vs 83, for only 30 extra MW spent).

---

## 11. Structural signatures before the g advantage is realised

Measured while the machine still has cheaper prefix g.

| signature | support | counterexample | genericity |
|---|---|---|---|
| Lower face-down | pre-SD1 12 vs 18; SD2 8 vs 10; SD4 7 vs 9; SD5 1 vs 3 | none in this pair | PLAUSIBLY_GENERAL |
| Remaining-cost lead after extra early spend | 83 vs 139 after SD2 for +30 MW invested | — | PLAUSIBLY_GENERAL |
| Higher post-Deal mobility at SD2 | legal 12 vs 4 | SD1 legal 8 vs 12 (machine better) | PLAUSIBLY_GENERAL |
| Midgame F on excavated board | F1 g=90 fd=8 remaining 82 | v0.60 F1 g=41 fd=17 did not convert | PLAUSIBLY_GENERAL |
| Lower mixed-park / rehandle | 34 vs 79 mixed-park cards; exclusive rehandle −24 | tag is conservative | GENERAL |
| Heart K/A topology | SD2 a_len 8 vs 1, cover 6 vs 10; SD5 cover 3 vs 7, gap −1 vs 9 | suit-specific | BENCHMARK_SPECIFIC details |
| More same-suit bonds | pre-SD1 22 vs 16; SD2 40 vs 31 | **SD5 54 vs 65 — cheaper route has fewer bonds** | anti-signature post-stock |
| Durable empty columns | — | 0 vs 0 at every Deal | not a distinguisher |
| Cheapest-g F1 | — | v0.60 g=41 failed; this 198 route F1 is g=189 | anti-lesson |

Overfit risk is high for “copy F1 at g=90 on spades with rows=3”. It is
low for “do not starve excavation” and “penalise re-moving attached
cards”.

---

## 12. Card-lifecycle highlights

104 physical identities from initial deal order. Duplicates are
`5S#A` / `5S#B` (and the same scheme for every other pair). Identities
are research telemetry; engine `Card` semantics are unchanged. All 104
are located through tableau movement, Deal, exposure, and foundation
removal on both routes.

| | autonomous | canonical |
|---|---|---|
| mean paid actions / card | 6.56 | 3.96 |
| mean move actions / card | 6.81 | 3.98 |
| never moved (destination-only) | 2 | 5 |
| first same-suit attach recorded | 95 | 93 |
| mixed-park ever | 79 | 34 |
| max paid actions on one card | 17 (`4S#A`) | 13 (`4S#B`, `AC#B`) |
| init face-down first-exposure mean g | 43.3 (43 of 44) | 45.8 (44 of 44) |

Canonical exposes buried cards at a similar *time in g*, but then
touches them far fewer times. The cost is rehandling after exposure, not
late first-flip.

---

## 13. Optional v0.60 cheap-F1 appendix

Reconstructed from `docs/research/autonomous_cost_optimisation_v0_60.json`
(`foundations.cheap.1.ordered_digest`). Not a complete solution.

| | v0.60 cheap F1 | canonical F1 | autonomous 198 at rows=3 (after SD2) |
|---|---|---|---|
| g | **41** | 90 | 59 |
| F / suits | 1 / s | 1 / s | 0 |
| stock rows | 3 | 3 | 3 |
| face-down | **17** | **8** | 10 |
| empty | 0 | 0 | 0 |
| bonds | 14 | (canon F1 epoch fd=8) | 31 |
| legal | 7 | — | 4 |
| n_ready | 1 (hearts material) | — | 2 (s, h) |
| observed remaining of a known solve | unknown (no complete cheap-F1 route) | 82 | 139 |

Cheap F1 bought a foundation 49 MW earlier than the 172 route’s F1, but
left **17 face-down** and almost no workspace. Canonical waited until
fd=8. The 198 incumbent never cashes F1 until post-stock. This is
downstream evidence that “cheap F1” without excavation is a poor
whole-game lineage — the same failure v0.60 observed when F2 collapsed
to g=190.

---

## 14. Action taxonomy (definitions)

Multi-tags are allowed. Exclusive buckets are used only for MW totals.

* `REVEAL` — a face-down card is exposed.
* `EMPTY_CREATED` / `EMPTY_CONSUMED` — empty-column count rises / the
  destination was empty.
* `SAME_SUIT_BOND_GAIN` / `LOSS` — tableau same-suit bond count changes.
* `COMPONENT_MERGE` — moved run attaches same-suit onto dest top.
* `COMPONENT_BREAK` — a same-suit join at the source is split.
* `MIXED_SUIT_PARK` — dest top is opposite suit (legal rank).
* `PARK_RELEASE` — a previously mixed-parked identity is moved again.
* `REHANDLE` — any card in the run already had a paid action.
* `FOUNDATION_TRIGGER` — auto-foundation fired.
* `RECEIVER_CREATION` — a King is placed onto a newly consumed empty.
* `DEAL_PREPARATION` — empty consumed within three commands of a Deal.
* `ZERO_COST_RELOCATION` — full-column-to-empty, cost 0.
* `OTHER` — no other tag applied.
* Exclusive `PRIMARY_PROGRESS` — paid merge/bond-gain that is not
  rehandle, reveal, or foundation.
* Exclusive `OTHER_PAID` — paid, none of the above.

---

## 15. Policy firewall

No change to:

* `whole_game_epoch_scheduler.py` lane ordering or harvest categories
* `autonomous_cost.py`
* engine / MW accounting
* either solution file

Generic helper: `src/spider/solution_forensics.py`. It does not import
`simple_*` and is not called from the scheduler. Candidate heuristics
below are hypotheses, not code.

---

## 16. Generalisation screen

| lesson | class |
|---|---|
| Repeat paid movement of attached cards is expensive | **GENERAL** |
| Early excavation (lower fd) can be worth higher prefix g | **PLAUSIBLY_GENERAL** |
| Deal-landing quality at some boundaries predicts later remaining cost | **PLAUSIBLY_GENERAL** |
| Foundation cash-out should be gated on fd/mobility, not cheapest g | **PLAUSIBLY_GENERAL** |
| Post-stock, cover and K/A gap beat raw bond count | **PLAUSIBLY_GENERAL** |
| Empty-column count as the 172-vs-198 distinguisher | rejected on this pair |
| Copy F1 at g=90 on spades with rows=3 | **HUMAN_ROUTE_SPECIFIC** |
| Heart cover 3 / a_len 8 as a numeric target | **BENCHMARK_SPECIFIC** |

Only GENERAL and PLAUSIBLY_GENERAL items are candidates for solver work.

---

## 17. Ranked hypotheses (do not implement in v0.61)

### 1. `rehandling_aware_economy` — GENERAL

* Mechanism: add a cheap rehandle-debt signal to ECONOMY / harvest
  (repeat paid participation of already-attached cards; bond-break after
  gain). Prefer durable placements over parking.
* Evidence: exclusive REHANDLE +24 of 26 MW; mean paid/card 6.56 vs
  3.96; mixed-park identities 79 vs 34.
* Likely MW: a material slice of the 24-MW exclusive gap if the tag is
  not too conservative.
* Complexity: medium. Telemetry exists; search needs a packed-state
  proxy, not per-card history, or a bounded ancestor statistic.
* Overfit: low if the signal is generic (paid-after-attach / bond churn)
  and not a 4925153 card list.
* Experiment: optional harvest/ECONOMY feature on the frozen v0.59
  architecture; one 900 s run, ceiling 197, no canonical seeding.

### 2. `deal_reception_shaping` — PLAUSIBLY_GENERAL

* Mechanism: score DEAL_NOW roots by observed landings (rank_ok,
  same-suit, mixed_block, legal_after), not `reception_fitness` as
  oracle and not cheapest g alone.
* Evidence: SD5 fitness 22 vs 10 and four same-suit landings; SD2 legal
  12 vs 4. Counterexample: machine SD1/SD4 landings are better.
* Likely MW: part of the 45-MW post-SD5 gap, not all of it.
* Complexity: low–medium (boundary scoring).
* Overfit: medium if tuned only to SD5 of this deal.
* Experiment: A/B harvest of DEAL_NOW using observed landing counts.

### 3. `excavation_gated_foundation_cashout` — PLAUSIBLY_GENERAL

* Mechanism: allow midgame F harvest only when fd and mobility pass a
  gate; do not protect cheapest-g F1.
* Evidence: canonical F1 g=90 fd=8 remaining 82 vs v0.60 F1 g=41 fd=17
  and this incumbent’s F1 g=189.
* Likely MW: lineage survival, not a direct 26-MW subtract.
* Complexity: medium (gate + harvest).
* Overfit: medium if the numeric fd gate is fit to 8.
* Experiment: drop cheap-F1 checkpoints that fail an fd/mobility gate;
  compare F2/F8 under ceiling 197.

### 4. `early_excavation_vs_cheapest_g` — PLAUSIBLY_GENERAL

* Mechanism: keep a high-excavation / low-fd cohort next to cheapest-g
  so the scheduler does not starve the +18/+12 opening investment that
  bought remaining-cost 44 then 56.
* Evidence: machine leads g by 34 at SD4 and then pays 60 extra.
* Likely MW: enables hypotheses 1–3 rather than subtracting 26 itself.
* Complexity: medium (portfolio split already exists; needs an
  excavation extreme that is not dominated by g).
* Overfit: low if fd is the feature.
* Experiment: harvest min-fd and min-rehandle alongside min-g in every
  epoch, including rows=5.

### 5. `low_cover_ka_topology` — PLAUSIBLY_GENERAL

* Mechanism: after stock, rank remaining suits by cover and K/A gap,
  not longest run or bond total.
* Evidence: post-SD5 hearts cover 7 vs 3, gap 9 vs −1; machine bonds 65
  vs 54 and still costs 67.
* Likely MW: part of the 45-MW post-SD5 conversion.
* Complexity: low (readiness already exposes cover/gap).
* Overfit: high if hearts-on-4925153 numbers become targets;
  PLAUSIBLY_GENERAL as a ranking key.
* Experiment: post-stock harvest by min max-cover and min |gap| among
  unfounded suits.

---

## 18. Recommended next experiment

**Hypothesis 1: rehandling-aware ECONOMY / portfolio on the frozen
v0.59 architecture.**

Do not copy the 172 route. Do not seed canonical states. Do not widen
the 900 s envelope. Measure whether a generic anti-rehandle signal can
beat autonomous 198 from the same incumbent-aware setup as v0.60.

---

## Files

* `src/spider/solution_forensics.py` — generic replay telemetry
* `research/solution_strategy_forensics_v0_61.py`
* `tests/test_solution_strategy_forensics_v0_61.py`
* `docs/research/solution_strategy_forensics_v0_61.json`
* `docs/research/solution_strategy_epoch_comparison_v0_61.json`
* `docs/research/solution_strategy_card_lifecycle_v0_61.json`

Solution files are unmodified. No new `.moves` file.
