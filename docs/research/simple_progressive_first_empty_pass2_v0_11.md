# Simple Progressive Search v0.11: First-Empty Pass-2 Workspace

## 1. Verdict

`PASS2_ONLY_IMPROVES_SOFT_STRUCTURE` — Pass 2 used the first empty column heavily via Tier C and improved run/adjacency/block structure, but it never beat the seed on hard progress.

Pass 1 from this exact fd-13 / empty-1 state is locally exhausted. Enabling C lets the solver *use* the workspace; that use builds run 9 by consuming the empty and does not uncover another face-down card, create a second empty, or assemble a foundation.

FIRST_VISIT_EXACT remains research-only and has no proof authority.
Production default remains DEPTH_AWARE_COVERAGE, `start_pass=0`. Pass 2 is not integrated.

## 2. Hard-progress seed

Reproduced from `deals/4925153.txt` by replaying the 43-command fd-14 / stock-0 prefix, root action `(2,8,1)`, and the v0.10 B_2_8_1 continuation to its FIRST EMPTY event.

| Field | Value |
| --- | --- |
| ok | true |
| digest | `53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a29000000121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201` |
| path length | 102 primitives |
| corrected MW cost | 102 |
| fd | 13 |
| stock rows | 0 |
| foundations | 0 |
| empties | 1 |
| longest run | 6 |
| adjacencies | 37 |
| movable blocks | 3 |
| harvest expansion | 50066 |
| harvest depth | 58 |
| fixture | `solutions/4925153_simple_fd13_empty1_seed.moves.txt` |

Harvest matched the v0.10 B_2_8_1 first-empty witness (local expansion 50066, local depth 58, combined path 102). Independent replay from the original deal is legal under `MW_RULES`.

## 3. Root-action census at fd13/empty1

Engine-legal actions, classified by the existing `classify_tier`. Classifications were not altered.

| | A | B | C | D | total |
| --- | ---: | ---: | ---: | ---: | ---: |
| legal actions | 1 | 3 | 18 | 0 | 22 |
| canonical children | 1 | 3 | 18 | 0 | 22 |

- Tier-C actions that use the empty column: **17 / 18**
- Tier-C actions that break a same-suit join: **10 / 18** (9 of those also fill the empty)
- A/B actions that use the empty: **1**, the King-run `(4,2,2)` Tier B
- The only Pass-1-legal empty use is that King case. Ordinary non-King movement into the empty remains Tier C.

A/B root actions: `(8,6,6)` A; `(0,4,1)` B; `(4,2,2)` B into empty; `(5,6,1)` B.

## 4. Pass-1 vs Pass-2

Both arms: `tt_mode=first_visit`, one depth band 2000, no saturation, fresh TT, max 250,000 unique expansions, 600 s, RSS abort 10 GiB. Pass 2 started at Pass 2, so C was available from expansion 1. No D.

| Metric | Pass 1 A+B | Pass 2 A+B+C |
| --- | ---: | ---: |
| Expanded | 144 | 233865 |
| Unique | 144 | 233865 |
| Unique/exp | 1.000 | 1.000 |
| States/sec | 320.8 | 389.8 |
| Min FD | 13 | 13 |
| Max empties | 1 | 1 |
| Longest run | 7 | 9 |
| Max adjacencies | 38 | 40 |
| Max movable blocks | 5 | 8 |
| Max foundations | 0 | 0 |
| Max depth | 38 | 2000 |
| RSS (MiB) | 24.5 | 1169.9 |
| Stop | band envelope | time limit |

Pass 1 exhausted the A+B first-visit graph in 144 unique states and 0.45 s. That is the local plateau: A+B cannot leave this seed except by the King-to-empty B move, which is not enough to uncover fd or create a second empty.

Pass 2 explored three orders of magnitude more unique states and hit the 2000 depth guard. It never reduced fd below 13, never created a second empty, and never reached a foundation.

## 5. Empty-column usage

| | Pass 1 | Pass 2 |
| --- | ---: | ---: |
| Moves into an empty | 76 | 74196 |
| of which Tier B | 76 | 3661 |
| of which Tier C | 0 | 70535 |
| first empty-use expansion | 2 | 2 |
| first empty-use tier | B `(8,2,7)` | B `(8,2,7)` |

Pass 2 considered C 260724 times and expanded 156608 C children. D remained 0.

The first replay-valid run-8 / run-9 event in Pass 2 occurred at local expansion 854, depth 853. The last move of that witness used the empty column as Tier C and left **zero** empties: the workspace was consumed to assemble run 9. Combined replay of that witness is legal. That relationship is recorded on the path; it is not a general causal claim about every C fill.

No empty-use on any arm directly preceded fd reduction, a second empty, run >= 10, or a foundation, because those events never occurred.

## 6. Hard-progress events

Seed-inherited events (`fd_below_14`, `first_empty`) fire at expansion 1 / depth 0 because the search root already has fd 13 and one empty. They are not new progress.

New events:

- Pass 1: none beyond seed; longest run 7 is below the run-8 recorder.
- Pass 2: `run_ge_8` and `run_ge_9` at expansion 854, depth 853, fd 13, empty 0, foundations 0, combined replay ok.
- Every C-root sweep: same pattern, run 9, fd 13, empty 1 as a max, foundations 0. Several run-9 witnesses also consume the empty via a final Tier-C fill.

No arm recorded `fd_le_12`, `fd_le_11`, `second_empty`, `run_ge_10`, `complete_ka_run`, or `first_foundation`.

## 7. Root Tier-C coverage

Pass-2 DFS expanded **0 / 18** distinct Tier-C root children. It dived into the first root child, A `(8,6,6)`, and never returned before the time limit.

Forced research-only C-root sweep therefore ran for all 18 canonically distinct unvisited C children: 50,000 unique expansions, 180 s, depth 2000, fresh TT, A+B+C thereafter.

| Sweep | Unique | Min FD | Max empty | Run | Fnd | C into empty | Depth | Stop |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| all 18 CROOT_* | 50000 | 13 | 1 | 9 | 0 | 12878–16320 | 2000 | node limit |

No sweep arm beat Pass 2 on hard progress. Clean-process RSS stayed ~273–293 MiB per sweep arm.

## 8. Optional extension

Not triggered. The 250k Pass-2 treatment did not achieve fd <= 12, empties >= 2, run >= 10, or a first foundation.

## 9. First foundation

No. `first_foundation_node` is null on every arm. No foundation route was saved.

## 10. What this answers

The central question was whether Pass 1 has been plateauing because the tier policy forbids using the empty it just created.

- **Permission:** yes. Pass 1 is exhausted here. Ordinary empty fills and join-breaks are Tier C, so A+B cannot use the workspace except for the King case.
- **Conversion:** no. Once C is enabled, the solver *does* use the empty (70,535 C fills in Pass 2) and that use can build run 9, but the empty is consumed and fd stays 13. Workspace permission is not the remaining bottleneck for a reveal or a foundation.

Do not treat the run-9 empty-fill as a reason to add Pass 3. Pass 3 would add D, which this census shows does not even exist at the seed.

## 11. Exactly one next recommendation

Do not integrate Pass 2 and do not add Pass 3. Inspect the replay-valid run-9 empty-consuming witness and the binding depth-2000 ceiling: the remaining bottleneck is converting the first empty into a face-down uncover or a second empty, not granting permission to occupy the empty.

## Integrity

Base SHA `e3dc45f2432a206cd309f2d55d196ad8afcd8cb3`. Deal `deals/4925153.txt`.
Default TT remains depth-aware. `first_visit` is research-only and not proof-safe.
`stop_on_first_empty` is harvest-only and default OFF.
Production `solve_progressive` defaults are unchanged.
