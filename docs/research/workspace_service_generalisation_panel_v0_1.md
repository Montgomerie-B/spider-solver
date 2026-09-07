# Workspace-Service Generalisation Panel v0.1

## 1. Verdict

`WORKSPACE_SERVICE_NOISY_OR_MIXED`

Bounded workspace service is not specific to deal 4925153: treatment materially changed workspace circulation on three non-calibration deals, and productive descendants re-entered ordinary search on P2, P4, and P7. P2 and P7 also improved minimum face-down by 13 and 2 cards respectively.

It did not generalise to a clear majority. Combined `EMPTY_CREATABLE` plus `ACTUAL_EMPTY` expansion increased on only 4/10 deals (P0, P2, P4, P7); six deals had no workspace service at all. Ordinary-serviced productive descendants improved over control on only P2 and P7. The panel therefore contains real positive cases, clean null cases, and significant cost/stock-progression tradeoffs rather than one coherent cross-deal effect.

## 2. Panel construction and frozen seeds

No canonical arbitrary-deal generator with a documented stable shuffle contract existed in the repository, so a research-only generator was frozen in commit `863ff6e` before any panel search.

The generator constructs two explicit 52-card decks in copy, suit `shdc`, ascending-rank order. It uses descending Fisher–Yates. Each bounded draw comes from the first eight bytes of `SHA-256(domain || seed_u64_be || counter_u64_be)`, with rejection sampling before modulo reduction. This avoids dependence on Python's random implementation. Seeds are the first eight SHA-256 bytes of `workspace-service-panel-v0-1:Pn`, interpreted as unsigned big-endian integers.

| Entry | Seed | Opening digest | Frozen run order |
| --- | ---: | --- | --- |
| P0 | calibration fixture | `c06565c127ccbc7a` | TREATMENT, CONTROL |
| P1 | 12858661474814657433 | `4985999558684dba` | CONTROL, TREATMENT |
| P2 | 17037747615682187675 | `4d67539f2e5b6949` | TREATMENT, CONTROL |
| P3 | 3511299091343336564 | `116e16a36fb97d8d` | CONTROL, TREATMENT |
| P4 | 6782576163807013305 | `d8ce5c96ef47d786` | TREATMENT, CONTROL |
| P5 | 5347712971617699974 | `2a38b6842db9491d` | CONTROL, TREATMENT |
| P6 | 323099503300668895 | `a76f1d0eaa918477` | TREATMENT, CONTROL |
| P7 | 1454277106742966837 | `3e1bac697f14bb19` | CONTROL, TREATMENT |
| P8 | 719590085337095586 | `c30d6533e8e80ff6` | TREATMENT, CONTROL |
| P9 | 11599763336346334964 | `b280e024873cb6de` | CONTROL, TREATMENT |

Each P1–P9 fixture contains exactly two copies of every suit/rank card, 54 opening tableau cards in standard `6/6/6/6/5/5/5/5/5/5` geometry, one face-up card per column, and 50 stock cards. P0 uses `deals/4925153.txt`. All openings use `MW_RULES`, including unrestricted dealing and corrected whole-column-to-empty cost.

The immutable panel definition, fixture hashes, generator contract, seeds, digests, and order are in `docs/research/workspace_service_generalisation_panel_v0_1_panel.json`.

## 3. Validation and calibration

Both arms used `COMMON_STAGE0 + STATE_LOCAL`, controller seed 0, 400 strategic expansions, 300,000 tactical nodes, 900 seconds, frontier cap 256, successor portfolio 10, maximum credit 4, scheduler and tactical allocation enabled, no incumbent, and the standard two-foundation diagnostic stop. Treatment used the unchanged one-representative workspace lane at fixed `N = 8`.

P0 broadly reproduced calibration. Control expanded zero workspace states and reached minimum face-down 36. Treatment expanded 13 `EMPTY_CREATABLE` and 1 `ACTUAL_EMPTY` state, reached minimum face-down 37, and retained 57 productive workspace descendants. Both arms preserved credit balance and integrity.

The panel endpoint applies the specified productive filter before counting downstream service. Under that stricter definition P0 had zero ordinary-serviced productive descendants. The earlier single-deal report's count of two included retained, ordinary-expanded descendants whose recorded structural-effect vector was empty; the present panel does not count them as productive.

All 20 arms completed at 400 expansions. There were no replay failures, corrected-cost inconsistencies, proof prunes, false independent-replay flags, final duplicate IDs, lane-introduced duplicates, resource-planner calls, or credit-balance flags. P6 recorded nine observations of the held-constant pre-existing overlapping-protection duplication behavior in each arm, but both final frontiers contained 256 distinct node IDs and no duplicates.

## 4. Ten-deal paired table

`Ord` is retained productive workspace descendants later expanded by the ordinary queue. Face-down delta is treatment minus control; negative is better.

| Deal | Workspace expanded C/T | EC expanded C/T | AE expanded C/T | Ord C/T (unique) | Min face-down C/T (delta) | Foundations C/T | Tactical ratio | Time ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 | 0 / 14 | 0 / 13 | 0 / 1 | 0 / 0 (0 / 0) | 36 / 37 (+1) | 0 / 0 | 1.065 | 1.080 |
| P1 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (0 / 0) | 40 / 40 (0) | 0 / 0 | 0.983 | 1.103 |
| P2 | 0 / 71 | 0 / 52 | 0 / 19 | 0 / 4 (0 / 4) | 39 / 26 (-13) | 0 / 0 | 2.230 | 2.501 |
| P3 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (0 / 0) | 41 / 41 (0) | 0 / 0 | 0.894 | 1.099 |
| P4 | 2 / 11 | 2 / 8 | 0 / 3 | 1 / 1 (1 / 1) | 36 / 36 (0) | 0 / 0 | 1.143 | 1.145 |
| P5 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (0 / 0) | 41 / 41 (0) | 0 / 0 | 0.969 | 1.118 |
| P6 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (0 / 0) | 36 / 36 (0) | 0 / 0 | 1.025 | 1.058 |
| P7 | 0 / 12 | 0 / 10 | 0 / 2 | 0 / 1 (0 / 1) | 34 / 32 (-2) | 0 / 0 | 7.373 | 0.980 |
| P8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (0 / 0) | 38 / 38 (0) | 0 / 0 | 1.003 | 1.074 |
| P9 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (0 / 0) | 43 / 40 (-3) | 0 / 0 | 0.856 | 1.034 |

## 5. Primary endpoint analysis

Treatment produced 6 ordinary-serviced productive descendant occurrences, all unique, across three non-calibration deals: P2 contributed 4, P4 contributed 1, and P7 contributed 1. Control produced 1 unique occurrence, on P4. The paired endpoint therefore improved on two deals, tied on eight, and never worsened. The required non-calibration treatment coverage count is 3/9.

Minimum face-down improved on 3 deals, tied on 6, and worsened on 1; median paired delta was 0. P2 supplied the strongest treatment-aligned improvement at -13, followed by P7 at -2. P0 worsened by +1. P9 improved by -3 despite treatment selecting no workspace representative, so that difference is timing-sensitive background divergence and is not evidence for the service mechanism.

The cross-panel primary evidence is thus mixed: useful ordinary reintegration appears beyond calibration, but only two improvements coincide with a paired increase in workspace service and downstream ordinary endpoints.

## 6. Workspace generalisation

Counts below are generated/retained/expanded. `Rep/F/N` is treatment representatives selected, forced services, and natural services. `Prod` is retained productive workspace descendants.

| Deal | EC C | EC T | AE C | AE T | Max empties C/T | Rep/F/N T | Prod C/T | Productive descendants later workspace-serviced T |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 | 22/10/0 | 136/45/13 | 0/0/0 | 49/12/1 | 0/1 | 53/42/10 | 0/57 | 8 |
| P1 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0 | 0/0/0 | 0/0 | 0 |
| P2 | 2/1/0 | 1076/348/52 | 0/0/0 | 415/115/19 | 0/2 | 285/12/272 | 0/522 | 70 |
| P3 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0 | 0/0/0 | 0/0 | 0 |
| P4 | 15/6/2 | 97/26/8 | 3/2/0 | 61/15/3 | 1/1 | 43/42/0 | 6/65 | 8 |
| P5 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0 | 0/0/0 | 0/0 | 0 |
| P6 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0 | 0/0/0 | 0/0 | 0 |
| P7 | 42/12/0 | 125/42/10 | 0/0/0 | 17/10/2 | 0/1 | 52/43/8 | 0/75 | 11 |
| P8 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0 | 0/0/0 | 0/0 | 0 |
| P9 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0 | 0/0/0 | 0/0 | 0 |

Treatment increased `EMPTY_CREATABLE` expansion on 4/10 deals, `ACTUAL_EMPTY` expansion on 4/10, retained productive descendants on 4/10, and ordinary-serviced productive descendants over control on 2/10. It selected 433 representatives: 139 were forced, 290 expanded naturally while reserved, and 4 survived to arm end. The concentration in four deals, rather than a clear majority, is the central reason for the mixed verdict.

## 7. Foundation and stock progression

No arm reached a foundation, so foundation outcome was treatment-only 0, control-only 0, both 0, neither 10. No complete solve existed to replay.

| Deal | Minimum stock rows in an expanded state C/T |
| --- | ---: |
| P0 | 3 / 3 |
| P1 | 1 / 1 |
| P2 | 0 / 4 |
| P3 | 1 / 1 |
| P4 | 1 / 1 |
| P5 | 0 / 0 |
| P6 | 3 / 3 |
| P7 | 1 / 5 |
| P8 | 3 / 3 |
| P9 | 1 / 1 |

P2 and P7 expose the main strategic tradeoff. Treatment reduced face-down substantially while remaining four and five stock rows earlier than control. Workspace service improved local uncovering but displaced deal progression within the 400-expansion envelope. P4 increased workspace circulation without changing face-down, foundations, stock depth, or the ordinary-descendant endpoint relative to control.

## 8. Search-balance and cost

No deal triggered either balance threshold. No treatment credit level exceeded 60%, and no paired credit share shifted by more than 25 percentage points.

| Deal | Credit expansions C | Credit expansions T | Tactical nodes C/T | Elapsed seconds C/T |
| --- | --- | --- | ---: | ---: |
| P0 | 90/80/78/77/75 | 93/79/77/76/75 | 50,671 / 53,945 | 576.8 / 623.0 |
| P1 | 89/80/78/77/76 | 89/80/78/77/76 | 11,088 / 10,902 | 228.9 / 252.4 |
| P2 | 94/80/79/74/73 | 99/82/76/72/71 | 28,504 / 63,563 | 318.4 / 796.5 |
| P3 | 92/79/79/76/74 | 92/79/79/76/74 | 13,235 / 11,827 | 538.6 / 591.8 |
| P4 | 97/76/76/76/75 | 96/79/77/75/73 | 48,755 / 55,707 | 427.1 / 488.9 |
| P5 | 92/80/78/75/75 | 91/80/79/76/74 | 37,274 / 36,122 | 354.5 / 396.2 |
| P6 | 93/79/77/76/75 | 93/79/77/76/75 | 6,825 / 6,999 | 755.8 / 799.7 |
| P7 | 93/78/78/77/74 | 86/82/78/78/76 | 10,982 / 80,968 | 493.7 / 483.7 |
| P8 | 84/79/79/79/79 | 84/79/79/79/79 | 67,276 / 67,494 | 520.8 / 559.5 |
| P9 | 87/79/78/78/78 | 85/80/79/78/78 | 26,634 / 22,789 | 346.0 / 357.7 |

The median tactical-node ratio was 1.014 (range 0.856–7.373): treatment was cheaper on 4 deals and more expensive on 6. The median elapsed-time ratio was 1.089 (range 0.980–2.501): treatment was faster on 1 and slower on 9. Totals were 301,244 versus 410,316 tactical nodes and 4,560.7 versus 5,349.3 seconds.

Across all deals control generated/retained 18,280/4,873 successors and treatment 19,182/5,065. Aggregate TT new/improved/suppressed was 4,704/179/13,407 control versus 4,901/174/14,117 treatment. These activity increases are not themselves success evidence.

## 9. Outlier deals

P2 is the strongest positive case. Twelve forced services, plus 272 reservations consumed naturally, raised workspace expansion from 0 to 71, retained 522 productive descendants, delivered 4 unique productive endpoints back to ordinary search, and improved face-down by 13. It also more than doubled tactical work and elapsed time and left treatment four stock rows behind control's stock-empty expansion.

P7 is the second positive case and largest tactical outlier. Treatment added 12 workspace expansions, one ordinary-serviced productive endpoint, and a two-card face-down improvement, but tactical nodes rose 7.37× and treatment did not progress past the initial five stock rows while control reached one.

P0 is the direct negative face-down case: calibration circulation reproduced, but treatment was one face-down card worse and yielded no productive ordinary endpoint. P4 is circulation without downstream gain over control. P1, P3, P5, P6, and P8 are clean service-null cases.

P9 changed face-down and search coverage despite selecting no workspace representative. Both arms received identical states and seeded randomness, but tactical routines are time-bounded; the enabled qualification observer adds runtime overhead and can perturb timing-sensitive tactical outcomes. P9 is therefore panel noise, not a workspace-service success. Alternating order limits systematic direction but cannot make individual timed searches bit-identical.

## 10. What this proves

Bounded service describes a real but conditional Spider-search mechanism. It is not tied to the known calibration digest or path: on independently generated P2 and P7 it unlocked workspace states, productive continuation, ordinary-queue reintegration, and lower face-down. P4 independently reproduced broader workspace circulation.

The result does not establish a general solver improvement. Six deals produced no eligible serviced state, only two paired deals improved the ordinary productive endpoint, no foundation was reached, and the strongest cases delayed stock progression and carried high tactical cost. The generic lane answers a service-starvation problem when suitable opportunities already arise; it does not ensure that such opportunities arise across openings or that local workspace investment is globally well timed.

The causal claim is consequently bounded: occasional forced service can compound existing intelligence on some unrelated deals, but the current unconditional entitlement is neither broadly active nor consistently aligned with whole-deal progress.

## 11. One next bounded experiment

On the same frozen ten-deal panel and unchanged `N = 8` lane, add a single predeclared stock-stall guard that withholds forced workspace service when treatment is more than one undealt stock row behind the strongest live ordinary frontier state, and measure whether P2/P7 face-down gains survive without their stock-progression and cost penalties.

**Verification.** The ten new panel tests plus the prior 245-test relevant regression selection passed on the final tree: `255 passed in 140.07s`. All result gates in the machine artifact pass.

Machine-readable paired evidence is in `docs/research/workspace_service_generalisation_panel_v0_1.json`; resumable arm checkpoints are in `research/results/workspace_service_generalisation_panel_v0_1/`.
