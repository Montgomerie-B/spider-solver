# Whole-deal backward/forward structural scheduler v0.2

## Scope and verified verdict

Scheduler v0.2 corrects the v0.1 Deal-starvation failure without adding search
resource. It introduces exact, one-step Deal counterfactuals; typed marginal
pre-Deal economics; explicit epoch saturation; and one post-transposition-table
epoch-transition representative. The representative is search coverage, not a
Deal score or proof preference.

The verified verdict is **PARTIAL**, architectural class **D — multi-epoch
economics failure**. Natural untouched play now advances through four
scheduler-justified Deals (epochs 0 through 4) under the unchanged Gate W
envelope. The remaining failure is no longer transition selection. Instead,
new bridge and high-leverage arrivals are observed after each Deal but are not
converted into preparation and foundation progress on the same continuous
branch. Gate W remains F0, and Gate V remains F1 rather than reaching F2.

No v0.3 or controller v0.16 work is included here.

## Exact v0.1 Deal-starvation diagnosis

The v0.1 schedule's `deal_now_preferred` value was diagnostic evidence, not a
coverage mechanism. With the existing four-objective limit, suit-diverse
selection filled the portfolio with local fragment objectives. Consequently,
`PREPARE_EPOCH_TRANSITION` did not annotate the legal Deal successor.

The Deal itself was still generated and could pass exact TT admission. The
failure occurred after that point: ordinary global priority repeatedly chose
locally attractive fragment states, and there was no post-TT lane reserving
one justified epoch transition. Thus the blocker was objective admission plus
global frontier coverage, not legality, replay, TT identity, tactical budget,
or an insufficient numerical Deal bonus.

The v0.2 flow is:

`fresh schedule -> exact saturation -> legal/replayed successor -> exact TT ->
typed epoch-transition opportunity -> at most one live representative -> one
ordinary expansion -> fresh post-Deal schedule`

## Counterfactual and marginal-economics API

`preview_deal_now` clones the exact state, invokes the active engine Deal using
`MW_RULES`, and builds exactly one fresh post-Deal schedule. It does not recurse,
enter the strategic TT, consume a tactical node, count as a strategic expansion,
or become an explored route.

`compare_prepare_then_deal` is narrower. It is called only for a replay-valid
successor that the controller already generated. It applies the candidate move,
uses the real engine Deal, and compares the resulting exact structure with the
existing Deal-Now preview. It neither invents a preparation route nor searches
for one.

`PreDealOpportunity` records:

- the scheduled objective and deadline distance;
- actionability and blocker work before and after Deal;
- survival or automatic supply after Deal;
- bounded estimated benefit and preparation cost;
- a typed classification and inspectable rationale.

The classifications are:

- `MUST_PRE_DEAL`: the exact next Deal materially loses or worsens important,
  deadline-relevant work. This blocks a scheduler Deal transition.
- `ADVANTAGE_PRE_DEAL`: bounded preparation may be superior, but the controller
  must find an already-generated realiser that demonstrates the advantage.
- `DEFERRABLE`: useful ordinary work whose marginal value before the next Deal
  is not superior to doing it later.
- `FUTURE_SUPPLIED`: the exact incoming row provides or preserves the relevant
  structure more cheaply.
- `NON_ECONOMIC`: the proposed preparation costs more rehandling or stable
  structure than its expected benefit.
- `INVALID`: stale, invalidated, or no longer meaningful work.

A useful move is therefore not automatically urgent. Stock coverage is not an
urgency signal on its own, and a late epoch-5 fragment remains visible without
becoming `MUST_PRE_DEAL` at epoch 0.

## Saturation and no-Deal-rush semantics

`assess_epoch_saturation` returns one of four exact-state statuses:

- `PREPARATION_REQUIRED` when at least one `MUST_PRE_DEAL` objective remains;
- `PREPARATION_ADVANTAGE` when no MUST remains but a bounded advantage is worth
  testing;
- `DEAL_READY` when no marginally superior pre-Deal preparation remains;
- `STOCK_EMPTY` when there is no next Deal.

MUST work continues to expose only existing legal preparations. Immediate Deal
does not qualify as an epoch transition while such work remains. For ADVANTAGE,
the controller compares only generated candidates. If none demonstrates a
better prepare-then-Deal result, Deal readiness is effective for that successor
only; the stored schedule remains an inspectable `PREPARATION_ADVANTAGE`
assessment. This prevents both invented preparations and permanent advantage
starvation.

Terminal/foundation-critical play retains precedence. Completion cash-out and
epoch-transition coverage remain independent typed mechanisms inside the same
frontier capacity; a completion representative wins a direct priority conflict.

## One-shot epoch-transition representative

A Deal successor qualifies only after:

1. the source schedule is freshly `DEAL_READY` (including a bounded effective
   readiness decision after failed ADVANTAGE comparison);
2. the Deal is legal and independently replayed;
3. the exact child state passes normal TT admission; and
4. the successor is a direct one-action Deal.

`EpochTransitionOpportunity` is identified by the exact canonical source state,
source epoch, exact incoming row, and a deterministic fingerprint. Its ordering
uses corrected `g`, remaining urgent work, rehandling debt, stable structure,
and next-epoch opportunity count. At most one live representative is reserved.
Once popped it is marked spent and cannot reserve again for the same exact
transition.

The representative receives one ordinary strategic expansion. It does not
enlarge the frontier, add tactical nodes, extend persistence, change allocator
tiers, or attach an arbitrary scalar bonus. Completion/foundation precedence,
exact duplicate suppression, and ordinary alternatives all remain intact.

## Post-Deal replanning and harvest

Every genuinely admitted Deal child receives a new schedule derived from its
exact post-Deal state. The prior readiness decision is not carried across the
epoch. The replan recomputes lane assignments, adjacency state, receptions,
bridge cards, foundation floors, deadlines, classifications, saturation, and
the bounded objective portfolio.

`EpochTransitionTrace` records the source fingerprint, corrected cost and epoch
before/after, all pre-Deal classification IDs, selected preparation, exact row,
admission/reservation/expansion status, typed realized harvests, and fresh next
objective IDs. Harvest kinds distinguish free joins, foundation triggers,
bridge arrivals, new high-leverage sources, useful isolation, workspace,
fragments, neutral transitions, and harmful receptions. Deal itself is never
counted as a harvest.

## Proof and resource safety

The exact TT remains `canonical structural Spider state -> lowest corrected g`.
Saturation, counterfactuals, scheduler deadlines, transition opportunities,
and spent status are absent from canonical identity. Lower-g exact dominance
and the existing admissible bound are unchanged. Scheduler proof-prunes remain
zero.

All acceptance gates retain their inherited limits. The scheduler still uses a
four-objective portfolio. Frontier width, closure beam, persistence, tactical
node budgets, allocator settings, and wall-clock ceilings were not increased.
Preview count and time, prepare-then-Deal comparison count and time, saturation
time, and representative-selection time are separately measured.

The focused v0.2/v0.1/v0.15 matrix passes **224 tests**. The complete repository
suite passes **1,540 tests**, preserves **37 expected xfails**, and emits the one
inherited `PytestReturnNotNoneWarning` in 1,220.19 seconds (20:20). No xfail was
weakened.

## Regression anchors

- Canonical solution: corrected 172, path `77d169da2538ba8c`, endpoint
  `4e9861540eac570cb`.
- Machine F1 anchor: corrected `g=21`, Spades foundation, stock 30, FD 33,
  path `924bfd20deac96af`, endpoint `fbea39bb5e2a3a47`, structural hash
  `b7522950ea41ad9a`.
- Independent F1 anchor: corrected `g=23`, independently replayed.
- Active profile: MobilityWare four-suit with unrestricted Deal into empty
  columns; every Deal costs one corrected move.

The v0.1 blueprint is preserved. The exact future rows remain:

| Epoch | Incoming row, columns 1–10 |
|---:|---|
| 1 | Js 9d 4d Kh 4d 6d 9s 7d 8s 5c |
| 2 | Ks As 6h 7s Ad Ad Ah 10d Qh Jd |
| 3 | 2c 10s Qd Kh 8h 9c 3s 5s 5d 4h |
| 4 | 9d Js Qh 2d 4c Qc Kc 8c Jh 9s |
| 5 | 3h 10h 2d 3c 9h 7c 7h As 3c 5d |

Both Club 3s remain in the final row. Generic temporal floors remain Clubs
5/5, Diamonds 4/5, Hearts 2/5, and Spades 2/5 for their two remaining lanes.

## Natural benchmark gates

| Gate | Fixed envelope | Result | Scheduler transition evidence |
|---|---|---|---|
| U, untouched | 90 s, 25 expansions, 300k tactical nodes, frontier 256 | 25 expansions, 34.718 s, 82 tactical nodes; F0, stock 50, FD 38, `g=8` | Opening `DEAL_READY`; one exact transition reserved, expanded and spent; fresh epoch 1 schedule |
| V, cost-21 F1 | 90 s, 25 expansions, 300k tactical nodes, frontier 256 | 25 expansions, 30.398 s, 101 tactical nodes; F1, stock 30, FD 32, total `g=26` | Five exact epoch-3-to-4 transitions reserved, expanded and spent; F2 not reached |
| W, untouched | 180 s, 50 expansions, 500k tactical nodes, frontier 256 | 50 expansions, 59.467 s, 181 tactical nodes; selected best F0, stock 50, FD 39, `g=6` | Continuous one-shot transitions 0→1→2→3→4; four reserved, expanded and spent; F1/F2 not reached |

Gate U's selected route is independently replay-valid with path
`475b12278d6b9f52`, endpoint `23413a4ad8d91f27`, and structural hash
`fc3a7380fd6146e`. Its transition funnel recorded one naturally Deal-ready
state, one legal/TT-admitted/qualified Deal, one reserved representative, one
expansion, and one fresh epoch-1 replan. Across 25 expansions the scheduler saw
68 `DEFERRABLE`, 29 `MUST_PRE_DEAL`, and 3 `ADVANTAGE_PRE_DEAL`
classifications. The principal opening transition used exact row E1 and
created a new fragment opportunity.

Gate V starts from the replayed cost-21 F1 state, not a route hint. The best
continuation is five actions and remains F1, with continuous total cost 26,
path `d5ad12fdb68dc3ea`, endpoint `30496cf7f013e61f`, and structural hash
`31659973bc6dba50`. It expands epochs 2, 3 and 4. Exact prepare-then-Deal
comparison rejects undemonstrated advantages on five legal generated lines,
allowing their one-shot epoch-4 transitions. The exact row is E4; realized
harvest includes bridge/high-leverage arrivals in columns 1, 6, 8 and 10 plus
new fragment opportunities. F2 is not reached.

Gate W is authorized by Gate U's natural epoch advance and Gate V's
scheduler-guided epoch advance. It records 200 generated/actionable objectives,
49 entering the portfolio, 21 admitted, 16 selected/satisfied, and five
downstream structural harvests. Saturation counts are 46
`PREPARATION_REQUIRED`, 2 `PREPARATION_ADVANTAGE`, and 2 statically
`DEAL_READY`; two further states become effectively Deal-ready after no
generated advantage realiser proves better. Classification totals are 70 MUST,
6 ADVANTAGE, and 124 DEFERRABLE; 12 selected pre-Deal objectives are MUST.

The continuous epoch chain is exact and replay-verified:

| Transition | Corrected g | Exact-row harvest |
|---|---:|---|
| 0→1 | 0→1 | new fragment opportunity |
| 1→2 | 1→2 | one bridge/high-leverage arrival; new fragment opportunity |
| 2→3 | 2→3 | five bridge/high-leverage arrivals; new fragment opportunity |
| 3→4 | 3→4 | three bridge/high-leverage arrivals; new fragment opportunity |

In total Gate W records nine realized bridge arrivals, nine high-leverage
source arrivals, four new-fragment opportunities, four exact TT-admitted
transition representatives, and zero scheduler or general proof prunes. It
performs 111 Deal-Now previews in 5.777 seconds, 45 prepare-then-Deal
comparisons in 0.037 seconds, and 6.532 seconds of saturation analysis. The
exact TT reports 106 new states, 6 improved states, and 66 suppressions.

Because Gate W does not reach F2, no deterministic repeat and no optional
240-second whole-game run are authorized. No solution archive is changed and
there is no new complete score below 172.

## Precise remaining blocker and next task

Transition selection now works. The next blocker is coordination after useful
stock arrives: consecutive Deal-ready replans recognize bridges and new
high-leverage sources, but the current marginal model does not form a durable
arrival-to-foundation conversion obligation or compare consuming that arrived
leverage against taking another Deal. The result is exact multi-epoch motion
without foundation conversion.

A separately authorized scheduler v0.3 should address only that demonstrated
blocker: typed arrival-consumption and foundation-conversion economics across
epochs, with explicit evidence for when a newly arrived bridge must be used
before the following Deal. It should retain all current resource, TT, proof,
frontier, objective-count, and persistence limits. Do not return to local
controller micro-sprints and do not begin v0.3 automatically.
