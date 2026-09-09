# Simple Progressive Search Baseline v0.1

## 1. Verdict

`SIMPLE_SOLVER_SEARCH_PROMISING` — E2 expanded 1000000 exact states at 866/s with joint fd=6; no foundation yet.

Competing solver, not a patch to the strategic controller.  Objective:
any replay-valid complete solution of deal 4925153.  Move count is not
optimised toward the 119-move external benchmark or the 172-move canonical line.

## 2. Solver architecture

One iterative DFS over ordinary legal Spider actions (tableau transfer and
stock Deal).  Working state is mutated in place with column/stock snapshots
for backtracking.  Children are ordered by a four-tier desirability band,
then a cheap local score.  Exact packed identity (`pack_state`, same fields
as `canonical_state_key`) plus the current relaxation pass is the
transposition key.  Inverse moves, ancestor recurrence, and equivalent
child states are suppressed locally.  Passes 0–3 widen permission from
Tier A through D; remaining node/time budget is split across remaining
passes so a huge A-graph cannot starve later tiers.  Deal is a planned
action scored from the known next stock row, with a 1-ply (optional 2-ply)
preparation lookahead.  No controller, scheduler, allocator, campaign,
registry, project, or reservation objects.

## 3. Move tiers/order

| Tier | Pass | Meaning |
| --- | ---: | --- |
| A | 0 | foundation, reveal, same-suit extend, create empty, strongly constructive Deal |
| B | 1 | mixed build, king-to-empty, moderate Deal, same-suit after a join-break |
| C | 2 | join-break rework, consume empty, mediocre Deal |
| D | 3 | remaining legal actions, including badly landing Deals |

Within a permitted tier: foundation > reveal > empty > same-suit length,
minus join-break / last-empty consumption.  An identified 1-ply Deal prep
is boosted ahead of Deal-now.

## 4. Exact-memory/backtracking model

TT stores the highest pass at which a packed exact state was started and
the highest pass at which it finished.  Skip if `seen` or `done` coverage
is at least the current pass.  Broader coverage subsumes narrower.
A pass-0 exhaustion does not mark pass 3.  Incomplete expansions (budget
abort) are not marked done.  Path keys prevent ancestor recurrence.

## 5. Perfect-information Deal planning

Next row is `state.stock[-10:]` landing on columns 1–10.  Signals: same-suit
parent, mixed rank adjacency, empty landings, buried tops, buried same-suit
runs of length ≥ 3.  1-ply lookahead applies up to 8 cheap A/B tableau
moves, scores the resulting Deal, and restores.  Prep is skipped on pass 0
so A-only search stays cheap; 2-ply is attempted only when that candidate
set is tiny.  Unrestricted Deal legality is obeyed (empties do not block
Deal under `MW_RULES`).

## 6. Throughput benchmark

| Envelope | Expanded | Unique | s | states/s | TT hit rate | Peak RSS MiB | Max depth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E1 | 100000 | 99478 | 119.2 | 838.9 | 0.652 | n/a* | 3321 |
| E2 | 1000000 | 999478 | 1155.1 | 865.7 | 0.677 | n/a* | 5000 |
| E3 | — | — | — | — | — | — | — |

\*E1/E2 ran before the Windows RSS HANDLE fix.  A later 20k-node calibration
sampled **28.3 MiB** peak (about 9 MiB above a 19 MiB interpreter), ≈0.45 KiB
extra per unique state, implying on the order of **0.5 GiB** at E2's 999k
unique keys.  Memory is not the limiter.

Strategic-controller historical rate (coalescing v0.1 P0, 400 expansions
in ~530s): **0.75 strategic expansions/s**.
These are not semantically equivalent to primitive exact-state expansions.

## 7. 4925153 search results

- E1: solved=False foundations=0 joint fd=17 stock_rows=5 cost=39 length=39 pass=3 nodes=100000 unique=99478 gen=403467 tt_hits=187309 dups=0 cycles=116162 inverses=69204 depth=3321 tiers considered=[180466, 331372, 605677, 74576] expanded=[37796, 51918, 10278, 4] deals considered/executed=75260/6 deal-now=6 prepared=6124 prep calls/nodes=50260/191283 stop=node limit replay=True replay_fd=17 replay_stock=5.
- E2: solved=False foundations=0 joint fd=6 stock_rows=4 cost=78 length=80 pass=3 nodes=1000000 unique=999478 gen=4113206 tt_hits=2099137 dups=0 cycles=1014072 inverses=643156 depth=5000 tiers considered=[1764884, 3171204, 7690190, 693531] expanded=[356584, 543553, 99856, 4] deals considered/executed=697597/244 deal-now=244 prepared=54254 prep calls/nodes=447597/1770418 stop=node limit replay=True replay_fd=6 replay_stock=4.
- E3: skipped (E3 estimate 11551s exceeds bounded run).

## 8. First-foundation result

No replay-valid foundation on 4925153 in the completed envelopes.

## 9. Complete-solution result

No complete solution in the completed envelopes.

## 10. Search-space anatomy

On E2, legal moves considered by tier A/B/C/D = [1764884, 3171204, 7690190, 693531].
Expanded by tier = [356584, 543553, 99856, 4].
Duplicate children removed = 0; path cycles = 1014072; inverses = 643156.
Deals considered 697597, executed 244; prep lookahead calls 447597 using 1770418 nodes.

Branching is dominated by ordinary tableau transfers (C is common among
*considered* moves, A/B among *expanded* moves).  Deal is sparse: 244
executed vs 4.1M generated children.  Exact TT and inverse/path-cycle cuts
are the main reducers (TT hit rate 0.677; 1.01M ancestor cycles; 0.64M
inverses).  Unique states ≈ expanded (999478 / 1000000), so the envelope
almost never exhausted a position — it walked new exact states down a deep
corridor.  E2 hit the implementation depth guard of **5000** (human line is
~174 commands).  The best joint replayable state is much shallower: 80
primitive moves, face-down 6 / stock 4.  That is uncovering progress, not a
foundation, and it shows DFS+constructive-first spending most nodes on
long A/B shuffles rather than on many distinct early Deal-preparation
positions.

## 11. Comparison with strategic-controller granularity

Simple solver primitive exact-state rate on E2: **865.7/s**.
Strategic controller recent 4-suit 400-expansion runs: about **0.75 strategic expansions/s** (~530s wall,
each expansion itself a tactical search of up to 300k nodes plus campaign
machinery).  Memory here is one packed exact key per visited state
(999478 unique; E2 RSS unsampled, 20k calibration extrapolates ~0.5 GiB).
Do not treat the two expansion types as equivalent.  The comparison is
granularity: this solver asks how far cheap ordered exact backtracking
gets when the unit of search is a legal Spider action.

Strategic controller first foundations on 4925153 in those runs: **0**.
This solver first foundations: **0**; complete solution: **False**.

## 12. One next bounded recommendation

Add iterative deepening on primitive depth (bands well above the 174-move human line, e.g. 80/160/320) so the same A–D exact-TT solver spends nodes on distinct early positions instead of 5000-move shuffles; do not add a controller.

## Integrity

Base SHA `a10578240dd10d2c3c8a4b385ed2534ec341967f`. Independent envelopes from `deals/4925153.txt`.
Human canonical line was not used to seed, train, or guide search.
Returned paths replay through `replay_actions`. Solver does not import
planner policy. Anytime controller is unchanged.

