# final_deal_transition_v0_66

Verdict: `FINAL_DEAL_TRANSITION_IMPROVES_CONVERSION`

Diagnosis: `TRANSITION_IMPROVED_CONVERSION_NOT_ENOUGH`

One-step deterministic Deal-preview harvest at the final stock row produced cheaper F3–F7 conversion than v0.65 under the same F2 prefix, ceiling, lanes, and envelope. No complete solution below 198.

## F2 reconstruction

Exact v0.65 autonomous F2, loaded from stored prefix (not re-searched):

| fact | value |
| --- | ---: |
| g | 130 |
| stock rows | 1 |
| fd | 2 |
| F | 2 |
| suits | Spades + Diamonds |
| actions | 134 |
| deals | 4 |
| legal tableau | 15 |
| digest | `53504b310102000a00020d29…` |
| replay | valid |

Immediate DEAL control (unchanged vs v0.65):

| landing | count |
| --- | ---: |
| rank-compatible | 0 |
| same-suit | 0 |
| mixed | 9 |
| empty | 1 |
| legal 15 → 5 |  |
| post boundaries | 35 |
| post components | 45 |

## Deal-preview implementation

`preview_next_deal(state)` clones, records landings from `stock[-10:]` left-to-right, applies `SpiderState.deal(MW_RULES)`, and returns telemetry. The supplied state is never mutated. Post digest equals `pack_state(clone.deal())`. Deal cost is 1. MobilityWare Unrestricted Deal into an empty column remains legal. Automatic foundation removal during Deal is reported per landing.

Search does not read `4925153_canonical.moves`. Intra-epoch lanes remain v0.63 `COST / REVEAL / CONSTRUCTION / OPERATIONAL_READINESS / ECONOMY` (`HORIZON` inactive when a suit is ready). Post-stock policy is unchanged.

## Controlled envelope

| knob | v0.65 | v0.66 |
| --- | ---: | ---: |
| time | 900 s | 900.4 s |
| unique cap | 800,000 | 84,202 used |
| RSS abort | 2.5 GiB | not hit |
| ceiling | 197 | 197 |
| width | 256 | 256 |
| rows=1 alloc | ~360 s | 360.7 s |
| post-stock alloc | ~540 s | 539.1 s |
| expansions | 52,450 | 10,897 |
| exp/s | 58.3 | 12.1 |

Preview analysis at every rows=1 visit cut throughput. Rows=1 expanded only 663 states (2,408 unique). Post-stock still received ~240 roots and 10,234 expansions.

## Portfolio composition (rows=1 harvest)

DEAL_NOW retained (1 root, the F2 immediate Deal).

Transition cats: consolidation 28, mobility 7, operational 40, pareto 11, reception 36 → 122 / 256 = 47.7%.

Existing cats still occupied 134 / 256 (cheap, ECONOMY, construction, operational, workspace, Pareto, DEAL_NOW). The share exceeded the ¼–⅓ guideline because ordinary categories overlapped heavily, so round-robin kept filling unique transition states. The portfolio was not converted into “256 best preview states”. No retune after the run.

## Best transition-aware pre-SD5 states

Modest preparation bought small, consistent reception/mobility gains versus immediate DEAL:

| cat | prep Δg | post legal | legal gain | rank-ok | same-suit | mixed | post bounds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| post_deal_consolidation | 4 | 7 | +2 | 2 | 2 | 8 | 33 |
| post_deal_reception | 6 | 7 | +2 | 3 | 2 | 7 | 33 |
| post_deal_mobility | 1 | 6 | +1 | 1 | 1 | 9 | 34 |
| DEAL_NOW control | 0 | 5 | 0 | 0 | 0 | 9 | 35 |

No state with a large mobility jump (canonical post-Deal legal is only 7) appeared under this F2 topology at modest cost. The useful signal was cheaper conversion, not a dramatic pre-Deal tableau rewrite.

## Post-SD5 structural frontier

| F | v0.65 g | v0.66 g | Δ | fd | empty | bounds | legal | t (s) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 179 | **173** | −6 | 2 | 2 | 9 | 100 | 382 |
| 4 | 186 | **181** | −5 | 1 | 1 | 6 | 53 | 386 |
| 5 | 194 | **186** | −8 | 0 | 2 | 4 | 84 | 388 |
| 6 | 197 | **194** | −3 | 0 | 6 | 2 | 148 | 394 |
| 7 | none ≤197 | **196** | new | 0 | 6 | 0 | 81 | 498 |
| 8 | none ≤197 | none | — |  |  |  |  |  |

F3 fell materially below 179. F7 appeared inside the ceiling for the first time on this lineage. No F8 and no terminal.

Best complete g: none. Incumbent 198 holds.

## After-run canonical preview (evaluation only)

Canonical F2: g=139, fd=3, rows=1, legal 31, components 21, boundaries 13.

Canonical post-SD5 preview: rank-ok 1, same-suit 1, mixed 7, legal 7, boundaries 20, components 30.

Autonomous immediate post-SD5: rank-ok 0, same-suit 0, mixed 9, legal 5, boundaries 35, components 45.

The selected prepared autonomous roots closed a little of that gap (legal 7, mixed 7, bounds 33) at +4 to +6 MW, still far from the canonical F2’s pre-Deal organisation (legal 31 / bounds 13). Policy was not changed after this comparison.

## Generality

`USEFUL_ONCE_EXCAVATION_MATURE_FINAL_DEAL`

The preview is a generic one-step engine function, but this trial only harvested at rows=1 after a mature F2. It is not yet evidence for whole-game Deal timing. Reception/mobility gains were small; the conversion win may be “pick a slightly better stock-empty board and let frozen post-stock search work”.

## Strategic interpretation

Late-game organisation, not excavation, was the v0.65 deficiency. Knowing the exact post-SD5 tableau and preferring that topology in the final harvest lowered F3 by 6 MW and reached F7=196. Existing post-stock search still cannot finish the last suit under 198. The remaining bottleneck is stock-empty assembly / cost-to-go, not another rows=1 harvest tweak.

## Next recommendation

Keep the F2 prefix. Next experiment is stock-empty assembly / cost-to-go on the improved post-SD5 states. Do not widen runtime. Do not copy the canonical route.
