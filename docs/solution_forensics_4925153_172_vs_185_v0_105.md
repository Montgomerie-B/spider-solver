# Solution forensics: human-172 vs machine-185

Schema `spider-solution-forensics-0.105`. Route A is the reference (`human-172`). Route B is the machine (`machine-185`). Corrected MobilityWare cost is the engine total. This report compares structural condition at stock boundaries. It does not align move text and it does not treat either route as optimal.

## 1. Executive summary

machine-185 finishes at corrected MW 185. human-172 finishes at 172. The gap (B minus A) is 13. Segment accounting matches that gap (accounted 13).

Before SD1, B is cheaper by 18 MW (32 versus 50). The finished gap is 13. The continuation is mixed: later segments include both savings and extra cost. During opening tableau, before SD1, B spends 32 and A spends 50 (B minus A -18). At pre-SD1, B is ahead by 18 (g 32 versus 50). Bonds are 16 versus 22. Experimental debt sums are 75 versus 71. During tableau between SD2 and SD3, B spends 8 and A spends 11 (B minus A -3). At pre-SD3, B is ahead by 27 (g 73 versus 100). During tableau between SD3 and SD4, B spends 48 and A spends 17 (B minus A +31). At pre-SD4, B is behind by 4 (g 122 versus 118). Bonds are 39 versus 42. Experimental debt sums are 153 versus 102. During tableau between SD4 and SD5, B spends 10 and A spends 30 (B minus A -20). At pre-SD5, B is ahead by 16 (g 133 versus 149). At post-SD5, B is ahead by 16 (g 134 versus 150). Bonds are 30 versus 54. Experimental debt sums are 277 versus 132. During stock-empty endgame, B spends 51 and A spends 22 (B minus A +29). At solved, B is behind by 13 (g 185 versus 172). At pre-SD1, B still has 18 face-down cards and 16 same-suit bonds; A has 12 face-down cards and 22 bonds. Part of the opening save is doing less excavation. The cheaper-opening half is a corrected-MW fact, at confidence HIGH for the cost itself. The worse-continuation half is not uniform. This comparison does not show that the opening caused the later extra cost. Confidence for that causal reading is MEDIUM at most, and the reading is not established.

The finished gap is 13 MW. Signed non-zero segment differences (B minus A): opening tableau, before SD1 -18, tableau between SD1 and SD2 -6, tableau between SD2 and SD3 -3, tableau between SD3 and SD4 +31, tableau between SD4 and SD5 -20, stock-empty endgame +29. Those differences sum to the finished gap. A positive segment can be larger than the finished gap because other segments are negative. That is offsetting accounting. Do not convert one segment into a share of the finished gap. Positive-cost rehandle card-events differ by 13 (B minus A). Segment costs partition the gap. Rehandles, parks, and column debt overlap with it and are not a second partition.

The first 1 action(s) match. The next actions differ (`move 3 2 1` versus `move 6 8 2`). After that split the routes share no exact tableau until the solved terminal. The solved empty board is the same for every complete solution of this deal and is not a strategic reconvergence. This is different early ancestry after a short shared prefix, not one line continued at two costs.

What each route makes expensive later is in sections 11 and 12. Those statements carry confidence grades. A grade is not a count of caused moves.

## 2. Validation

| route | file | moves sha256 | actions | solved | foundations | stock | corrected MW | legacy MW | deals | tableau moves |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| human-172 | solutions\4925153_canonical.moves | 18338a08576ad24e9af1f4ba2e7db3e28768788dd511e823193b1937f3feef33 | 174 | True | 8 | 0 | 172 | 163 | 5 | 169 |
| machine-185 | solutions\4925153_autonomous_185.moves | b19c56e957ac2666298a80118d54ff7fca6c8114ed7d27590e2e98a017d4fb73 | 189 | True | 8 | 0 | 185 | 177 | 5 | 184 |

Deal file `deals\4925153.txt` sha256 `c0b70979b3e6b90e266691df956026629c890f49c12ed519801d6779434734df`.
Both totals were produced by `replay_actions_detailed` under `MW_RULES` from the untouched deal.

## 3. Opening comparison

| measure | human-172 | machine-185 |
| --- | --- | --- |
| corrected MW at pre-SD1 | 50 | 32 |
| action index at pre-SD1 | 51 | 35 |
| positive-cost moves | 50 | 32 |
| zero-cost whole-column moves | 1 | 3 |
| cards revealed | 32 | 26 |
| face-down remaining | 12 | 18 |
| same-suit bonds | 22 | 16 |
| run compression | 22 | 16 |
| empty columns | 0 | 0 |
| experimental debt sum | 71 | 75 |
| positive-cost rehandle card-events | 62 | 25 |
| foundations | 0 | 0 |

B's opening is cheaper on corrected MW. Zero-cost whole-column moves on B before SD1: action 30 `move 8 3 1` relocates 2H#A, source becomes empty, revealed 0, bonds +0, face-down +0; action 31 `move 9 8 4` relocates 7H#A 6H#A 5H#B 4H#A, source becomes empty, revealed 0, bonds +0, face-down +0; action 32 `move 6 9 6` relocates 7S#A 6S#B 5S#A 4S#B 3S#A 2S#B, source becomes empty, revealed 0, bonds +0, face-down +0. These transfers reveal nothing. They rearrange already-built runs and manage an empty column before the deal.

## 4. Stock-boundary comparison

| horizon | g A | g B | found A | found B | fd A | fd B | empty A | empty B | bonds A | bonds B | reveal cols A | reveal cols B | cards 2+ A | cards 2+ B | debt sum A | debt sum B |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| opening | 0 | 0 | 0 | 0 | 44 | 44 | 0 | 0 | 0 | 0 | 6 | 6 | 0 | 0 | 4 | 4 |
| pre-SD1 | 50 | 32 | 0 | 0 | 12 | 18 | 0 | 0 | 22 | 16 | 1 | 0 | 24 | 17 | 71 | 75 |
| post-SD1 | 51 | 33 | 0 | 0 | 12 | 18 | 0 | 0 | 23 | 19 | 0 | 1 | 24 | 17 | 154 | 121 |
| pre-SD2 | 88 | 64 | 0 | 0 | 8 | 10 | 0 | 0 | 38 | 33 | 0 | 0 | 39 | 36 | 71 | 86 |
| post-SD2 | 89 | 65 | 0 | 0 | 8 | 10 | 0 | 0 | 40 | 34 | 0 | 0 | 39 | 36 | 134 | 167 |
| pre-SD3 | 100 | 73 | 1 | 1 | 7 | 9 | 0 | 0 | 35 | 26 | 0 | 0 | 43 | 39 | 74 | 126 |
| post-SD3 | 101 | 74 | 1 | 1 | 7 | 9 | 0 | 0 | 35 | 27 | 0 | 0 | 43 | 39 | 175 | 192 |
| pre-SD4 | 118 | 122 | 1 | 1 | 7 | 2 | 0 | 1 | 42 | 39 | 0 | 0 | 48 | 55 | 102 | 153 |
| post-SD4 | 119 | 123 | 1 | 1 | 7 | 2 | 0 | 0 | 43 | 39 | 0 | 0 | 48 | 55 | 193 | 236 |
| pre-SD5 | 149 | 133 | 2 | 2 | 1 | 2 | 0 | 1 | 50 | 30 | 0 | 0 | 64 | 58 | 72 | 197 |
| post-SD5 | 150 | 134 | 2 | 2 | 1 | 2 | 0 | 0 | 54 | 30 | 0 | 0 | 64 | 58 | 132 | 277 |
| stock-empty-endgame | 150 | 134 | 2 | 2 | 1 | 2 | 0 | 0 | 54 | 30 | 0 | 0 | 64 | 58 | 132 | 277 |
| solved | 172 | 185 | 8 | 8 | 0 | 0 | 10 | 10 | 0 | 0 | 0 | 0 | 83 | 89 | 0 | 0 |

Gap contribution is extra corrected MW spent by B in that segment. Deal segments contain only the deal action, so they are 0 when both routes pay 1.

| segment | A spent | B spent | B minus A | debt sum A | debt sum B | face-down A | face-down B | bonds A | bonds B | rehandles A | rehandles B |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| opening -> pre-SD1 | 50 | 32 | -18 | 71 | 75 | 12 | 18 | 22 | 16 | 62 | 25 |
| pre-SD1 -> post-SD1 | 1 | 1 | 0 | 154 | 121 | 12 | 18 | 23 | 19 | 62 | 25 |
| post-SD1 -> pre-SD2 | 37 | 31 | -6 | 71 | 86 | 8 | 10 | 38 | 33 | 137 | 106 |
| pre-SD2 -> post-SD2 | 1 | 1 | 0 | 134 | 167 | 8 | 10 | 40 | 34 | 137 | 106 |
| post-SD2 -> pre-SD3 | 11 | 8 | -3 | 74 | 126 | 7 | 9 | 35 | 26 | 170 | 121 |
| pre-SD3 -> post-SD3 | 1 | 1 | 0 | 175 | 192 | 7 | 9 | 35 | 27 | 170 | 121 |
| post-SD3 -> pre-SD4 | 17 | 48 | 31 | 102 | 153 | 7 | 2 | 42 | 39 | 185 | 171 |
| pre-SD4 -> post-SD4 | 1 | 1 | 0 | 193 | 236 | 7 | 2 | 43 | 39 | 185 | 171 |
| post-SD4 -> pre-SD5 | 30 | 10 | -20 | 72 | 197 | 1 | 2 | 50 | 30 | 235 | 178 |
| pre-SD5 -> post-SD5 | 1 | 1 | 0 | 132 | 277 | 1 | 2 | 54 | 30 | 235 | 178 |
| post-SD5 -> solved | 22 | 51 | 29 | 0 | 0 | 0 | 0 | 0 | 0 | 313 | 326 |

## 5. Strong machine behaviours

### MACHINE BEHAVIOUR TO PRESERVE

- **cheaper pre-SD1 line** (HIGH). Corrected MW at pre-SD1 is 32 for machine-185 and 50 for human-172.
- **more zero-cost whole-column transfers before SD1** (HIGH). machine-185 plays 3 zero-cost whole-column moves before SD1; human-172 plays 1. action 30 `move 8 3 1` relocates 2H#A and leaves the source empty; action 31 `move 9 8 4` relocates 7H#A 6H#A 5H#B 4H#A and leaves the source empty; action 32 `move 6 9 6` relocates 7S#A 6S#B 5S#A 4S#B 3S#A 2S#B and leaves the source empty. Together they reveal nothing and add no same-suit bonds. They are free rearrangement of already-built runs and empty-column choreography before the deal. Each such move costs 0 only because it relocates an entire column onto an empty column.
- **fewer positive-cost tableau moves before SD1** (HIGH). 32 positive-cost moves on machine-185 versus 50 on human-172.

### MACHINE BEHAVIOUR TO SUPPRESS / IMPROVE

- **higher exclusive-class spend in MIXED_SUIT_PLACEMENT** (MEDIUM). machine-185 spends 43 MW in MIXED_SUIT_PLACEMENT; human-172 spends 29. This is an accounting bucket. Moves in the bucket can also reveal or build.
- **more positive-cost rehandling of physical cards** (MEDIUM). machine-185 records 326 positive-cost rehandle card-events; human-172 records 313. A card-event is not a move, and the difference is not a count of wasted moves.
- **column 4 accumulates more face-up disorder than the reference at one or more stock horizons** (MEDIUM). Horizons where B's focus column has higher disorder: pre-SD1, post-SD1, pre-SD2, post-SD2, pre-SD3, post-SD3, pre-SD4, post-SD4, pre-SD5, post-SD5, stock-empty-endgame. At the compared horizons the focus column is more disordered on B, and B's experimental debt sum is also higher on at least one of those horizons. That is consistent with B carrying the liability rather than only moving it, but other columns can still hold different costs.
- **extra MW in tableau between SD3 and SD4** (HIGH). machine-185 spends 48 and human-172 spends 17 in post-SD3 -> pre-SD4 (difference 31). This locates the cost. It does not by itself name the card that caused it.
- **extra MW in stock-empty endgame** (HIGH). machine-185 spends 51 and human-172 spends 22 in post-SD5 -> solved (difference 29). This locates the cost. It does not by itself name the card that caused it.

## 6. Major structural liabilities

- machine-185 spends 31 more MW than the reference during tableau between SD3 and SD4. Confidence HIGH.
- machine-185 spends 29 more MW than the reference during stock-empty endgame. Confidence HIGH.
- Repair R33 costs 4 MW on columns [3] and is tied, at HIGH confidence, to move 10 3 1 (mixed_suit). Confidence HIGH.
- Repair R55 costs 4 MW on columns [4] and is tied, at HIGH confidence, to move 1 4 1 (mixed_suit). Confidence HIGH.
- Repair R41 costs 3 MW on columns [10] and is tied, at HIGH confidence, to move 7 10 1 (mixed_suit). Confidence HIGH.
- Repair R54 costs 3 MW on columns [9] and is tied, at HIGH confidence, to move 1 9 1 (mixed_suit). Confidence HIGH.
- Repair R62 costs 3 MW on columns [8] and is tied, at HIGH confidence, to move 3 8 2 (mixed_suit). Confidence HIGH.
- Repair R8 costs 2 MW on columns [1] and is tied, at HIGH confidence, to move 9 1 1 (mixed_suit). Confidence HIGH.
- Column 4 is first materially more disordered than the reference at pre-SD1 (disorder 3 versus 0). Confidence MEDIUM.

Exclusive cost-class accounting partitions the MW totals. It is not a causal partition. A reveal that also parks is counted as REVEAL because reveal has priority.

| class | A | B | B minus A |
| --- | --- | --- | --- |
| EMPTY_PLACEMENT | 29 | 20 | -9 |
| FOUNDATION_TRIGGER | 8 | 8 | 0 |
| MIXED_SUIT_PLACEMENT | 29 | 43 | 14 |
| REVEAL | 44 | 43 | -1 |
| SAME_SUIT_MERGE | 57 | 66 | 9 |
| STOCK_DEAL | 5 | 5 | 0 |
| ZERO_COST_WHOLE_COLUMN | 0 | 0 | 0 |

## 7. Column focus forensic timeline

Focus column is 4 (MobilityWare column number, 1-based).

At the compared horizons the focus column is more disordered on B, and B's experimental debt sum is also higher on at least one of those horizons. That is consistent with B carrying the liability rather than only moving it, but other columns can still hold different costs.

Horizons where B is more disordered: pre-SD1, post-SD1, pre-SD2, post-SD2, pre-SD3, post-SD3, pre-SD4, post-SD4, pre-SD5, post-SD5, stock-empty-endgame.
Horizons where A is more disordered: none.

| horizon | disorder A | disorder B | debt A | debt B | suit br A | suit br B | rank br A | rank br B | buried up A | buried up B | argmax A | argmax B |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| opening | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| pre-SD1 | 0 | 3 | 1 | 19 | 0 | 3 | 0 | 0 | 0 | 3 | 3 | 1 |
| post-SD1 | 1 | 4 | 6 | 24 | 0 | 3 | 1 | 1 | 1 | 4 | 3 | 1 |
| pre-SD2 | 2 | 5 | 12 | 30 | 1 | 4 | 1 | 1 | 2 | 5 | 9 | 4 |
| post-SD2 | 4 | 5 | 26 | 29 | 2 | 4 | 2 | 1 | 9 | 5 | 4 | 5 |
| pre-SD3 | 1 | 5 | 6 | 31 | 0 | 4 | 1 | 1 | 1 | 6 | 8 | 5 |
| post-SD3 | 2 | 7 | 12 | 40 | 0 | 5 | 2 | 2 | 3 | 8 | 8 | 5 |
| pre-SD4 | 2 | 11 | 12 | 64 | 0 | 9 | 2 | 2 | 3 | 13 | 6 | 4 |
| post-SD4 | 4 | 13 | 20 | 73 | 1 | 10 | 3 | 3 | 4 | 14 | 6 | 4 |
| pre-SD5 | 0 | 9 | 1 | 51 | 0 | 7 | 0 | 2 | 0 | 10 | 6 | 4 |
| post-SD5 | 2 | 11 | 10 | 60 | 1 | 8 | 1 | 3 | 2 | 11 | 7 | 4 |
| stock-empty-endgame | 2 | 11 | 10 | 60 | 1 | 8 | 1 | 3 | 2 | 11 | 7 | 4 |
| solved | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |

First B action that raises column 4 disorder, or raises its experimental score by 2 or more: action 25 `move 6 4 1` at g=25 (pre-SD1, class MIXED_SUIT_PLACEMENT). Disorder 0 -> 1, experimental score 1 -> 6. Bonds delta +0, face-down delta +0, revealed nothing.

B actions that increase this column's disorder or experimental score by 2 or more: 17.

| action | g | canonical | class | disorder | score | revealed | bonds | face-down |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | 25 | `move 6 4 1` | MIXED_SUIT_PLACEMENT | 0->1 | 1->6 |  | +0 | +0 |
| 29 | 29 | `move 3 4 1` | MIXED_SUIT_PLACEMENT | 1->2 | 7->12 |  | +0 | +0 |
| 33 | 30 | `move 2 4 1` | MIXED_SUIT_PLACEMENT | 2->3 | 12->18 |  | +0 | +0 |
| 36 | 33 | `deal` | STOCK_DEAL | 3->4 | 19->24 |  | +3 | +0 |
| 55 | 52 | `move 1 4 1` | REVEAL | 4->5 | 24->30 | 10C#A | +0 | -1 |
| 61 | 58 | `move 9 4 11` | MIXED_SUIT_PLACEMENT | 4->5 | 24->29 |  | +0 | +0 |
| 72 | 69 | `move 10 4 2` | MIXED_SUIT_PLACEMENT | 4->5 | 24->31 |  | +0 | +0 |
| 78 | 74 | `deal` | STOCK_DEAL | 5->7 | 31->40 |  | +1 | +0 |
| 88 | 84 | `move 3 4 1` | MIXED_SUIT_PLACEMENT | 7->8 | 40->46 |  | +0 | +0 |
| 98 | 94 | `move 2 4 1` | REVEAL | 8->9 | 46->52 | 9H#A | +0 | -1 |
| 113 | 109 | `move 7 4 1` | MIXED_SUIT_PLACEMENT | 7->8 | 40->45 |  | +0 | +0 |
| 117 | 113 | `move 2 4 1` | MIXED_SUIT_PLACEMENT | 8->9 | 45->51 |  | +0 | +0 |
| 121 | 117 | `move 1 4 1` | MIXED_SUIT_PLACEMENT | 9->10 | 52->57 |  | +0 | +0 |
| 124 | 120 | `move 1 4 1` | MIXED_SUIT_PLACEMENT | 10->11 | 58->64 |  | +0 | +0 |
| 127 | 123 | `deal` | STOCK_DEAL | 11->13 | 64->73 |  | +0 | +0 |
| 138 | 134 | `deal` | STOCK_DEAL | 9->11 | 51->60 |  | +0 | +0 |
| 146 | 142 | `move 8 4 2` | MIXED_SUIT_PLACEMENT | 9->10 | 52->60 |  | +0 | +0 |

MEDIUM or HIGH backward attributions that repair column 4: R55 (HIGH, cost 4), R39 (HIGH, cost 2), R74 (HIGH, cost 2), R80 (HIGH, cost 2), R82 (HIGH, cost 2), R14 (HIGH, cost 1), R20 (HIGH, cost 1), R67 (HIGH, cost 1), R77 (HIGH, cost 1), R19 (MEDIUM, cost 1), R58 (MEDIUM, cost 1).

Column 4 is first materially worse than the reference at pre-SD1: disorder 3 versus 0, experimental debt 19 versus 1.

At pre-SD1, column 4 holds experimental debt 19 of the tableau sum 75 (share of the experimental score 0.253). Argmax column is 1. Vector: [19, 13, 1, 19, 12, 1, 1, 1, 1, 7]. That share is not a share of the finished MW gap.

At pre-SD4, column 4 holds experimental debt 64 of the tableau sum 153 (share of the experimental score 0.418). Argmax column is 4. Vector: [0, 0, 24, 64, 0, 15, 0, 21, 22, 7]. That share is not a share of the finished MW gap.

At post-SD5, column 4 holds experimental debt 60 of the tableau sum 277 (share of the experimental score 0.217). Argmax column is 4. Vector: [17, 9, 43, 60, 16, 24, 37, 35, 1, 35]. That share is not a share of the finished MW gap.

A focus column can be the worst column without holding most of the experimental debt, and a share of that score is not a share of the finished MW gap.

## 8. Card-rehandling comparison

| route | label | handling events | unique cards | moved 2+ | moved 3+ | moved 4+ | positive rehandles | zero-cost card moves | max handles |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | human-172 | 414 | 99 | 83 | 60 | 48 | 313 | 2 | 13 |
| B | machine-185 | 443 | 99 | 89 | 72 | 66 | 326 | 19 | 12 |

Most-handled cards, by deal-order identity:

| route | card | handles | positive rehandles |
| --- | --- | --- | --- |
| human-172 | AC#B | 13 | 12 |
| human-172 | 4S#B | 13 | 12 |
| human-172 | 2S#A | 12 | 11 |
| human-172 | 2C#A | 12 | 11 |
| human-172 | 3S#A | 12 | 11 |
| machine-185 | 4S#B | 12 | 10 |
| machine-185 | 3S#A | 11 | 9 |
| machine-185 | 5S#A | 11 | 9 |
| machine-185 | 2S#B | 11 | 9 |
| machine-185 | 7S#A | 10 | 8 |

These counts do not by themselves say which handling was necessary.

## 9. Park lifecycle comparison

**human-172.** candidates 169, removed non-same-suit 80, HIGH 56, MEDIUM 10, LOW non-same-suit 14, zero-cost whole-column relocations recorded 2.

| id | confidence | contact | cards | from | park | created | removed | life | deals | create cost | remove cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P8 | HIGH | mixed_suit | 7S#A 6S#B 5S#A 4S#B | 3 | 7 | 8 | 26 | 18 | 0 | 1 | 1 |
| P14 | HIGH | mixed_suit | JD#A | 9 | 2 | 14 | 67 | 53 | 1 | 1 | 1 |
| P15 | HIGH | mixed_suit | 6S#A | 9 | 4 | 15 | 35 | 20 | 0 | 1 | 1 |
| P16 | HIGH | mixed_suit | 5H#B | 10 | 4 | 16 | 34 | 18 | 0 | 1 | 1 |
| P17 | HIGH | mixed_suit | 4S#A | 8 | 4 | 17 | 22 | 5 | 0 | 1 | 1 |
| P18 | MEDIUM | mixed_suit | 3D#B | 10 | 4 | 18 | 21 | 3 | 0 | 1 | 1 |
| P20 | HIGH | mixed_suit | 2C#A AC#B | 8 | 9 | 20 | 37 | 17 | 0 | 1 | 1 |
| P21 | MEDIUM | mixed_suit | 3D#B | 4 | 8 | 21 | 23 | 2 | 0 | 1 | 1 |
| P22 | HIGH | empty | 4S#A | 4 | 10 | 22 | 105 | 83 | 3 | 1 | 1 |
| P23 | HIGH | mixed_suit | 3D#B | 8 | 10 | 23 | 85 | 62 | 1 | 1 | 1 |
| P25 | HIGH | mixed_suit | 2H#A | 8 | 10 | 25 | 49 | 24 | 0 | 1 | 1 |
| P26 | HIGH | empty | 7S#A 6S#B 5S#A 4S#B | 7 | 8 | 26 | 33 | 7 | 0 | 1 | 1 |

**machine-185.** candidates 184, removed non-same-suit 89, HIGH 71, MEDIUM 6, LOW non-same-suit 12, zero-cost whole-column relocations recorded 4.

| id | confidence | contact | cards | from | park | created | removed | life | deals | create cost | remove cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P5 | HIGH | mixed_suit | QS#B | 3 | 2 | 5 | 58 | 53 | 1 | 1 | 1 |
| P7 | HIGH | mixed_suit | 7S#A 6S#B 5S#A 4S#B | 3 | 7 | 7 | 27 | 20 | 0 | 1 | 1 |
| P8 | HIGH | mixed_suit | 4S#A | 8 | 1 | 8 | 49 | 41 | 1 | 1 | 1 |
| P13 | HIGH | mixed_suit | JD#A | 9 | 2 | 13 | 40 | 27 | 1 | 1 | 1 |
| P14 | HIGH | mixed_suit | 6S#A | 9 | 3 | 14 | 26 | 12 | 0 | 1 | 1 |
| P15 | HIGH | mixed_suit | 3D#A | 9 | 1 | 15 | 46 | 31 | 1 | 1 | 1 |
| P16 | HIGH | mixed_suit | 2S#A | 6 | 1 | 16 | 45 | 29 | 1 | 1 | 1 |
| P19 | HIGH | empty | 7H#A | 4 | 9 | 19 | 31 | 12 | 0 | 1 | 0 |
| P22 | HIGH | mixed_suit | 10H#A | 4 | 2 | 22 | 33 | 11 | 0 | 1 | 1 |
| P23 | HIGH | mixed_suit | 2C#A | 8 | 10 | 23 | 47 | 24 | 1 | 1 | 1 |
| P25 | HIGH | mixed_suit | QS#A | 6 | 4 | 25 | 176 | 151 | 5 | 1 | 1 |
| P26 | HIGH | mixed_suit | 6S#A | 3 | 5 | 26 | 87 | 61 | 3 | 1 | 1 |

Same-suit attaches are stored as LOW disassembly evidence and excluded from these counts.

HIGH parks are common on both routes (A 56, B 71). A single HIGH park is a graded temporary placement, not a rare proof of a mistake.

## 10. Workspace lifecycle comparison

Components are listed separately. There is no workspace efficiency scalar.

**human-172.** episodes 50, acquired by play 50, sum of recorded acquisition costs 48 (a shared action that empties two columns is counted on each episode), consumed 40, consumed by a stock deal 0, consumed with a reveal 9, consumed with immediate benefit 11, recovered 40, held until end 10, positive immediate unwind 32.

| id | column | created | acq cost | held | consumed by | stock deal | reveals | benefit | unwind | recovered | until recovery |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W1 | 10 | 19 | 1 | 3 | move 4 10 1 | False | 0 | False | 1 | True | 83 |
| W2 | 8 | 25 | 1 | 1 | move 7 8 6 | False | 0 | False | 1 | True | 7 |
| W3 | 3 | 28 | 1 | 1 | move 7 3 2 | False | 1 | True | 1 | True | 35 |
| W4 | 8 | 33 | 1 | 1 | move 4 8 2 | False | 0 | False | 1 | True | 2 |
| W5 | 8 | 36 | 1 | 1 | move 9 8 2 | False | 0 | False | 1 | True | 2 |
| W6 | 9 | 38 | 1 | 5 | move 1 9 1 | False | 1 | True | 0 | True | 3 |
| W7 | 8 | 39 | 1 | 1 | move 7 8 6 | False | 0 | False | 1 | True | 5 |
| W8 | 8 | 45 | 1 | 1 | move 9 8 1 | False | 0 | True | 1 | True | 4 |

**machine-185.** episodes 44, acquired by play 44, sum of recorded acquisition costs 40 (a shared action that empties two columns is counted on each episode), consumed 34, consumed by a stock deal 2, consumed with a reveal 8, consumed with immediate benefit 12, recovered 34, held until end 10, positive immediate unwind 27.

| id | column | created | acq cost | held | consumed by | stock deal | reveals | benefit | unwind | recovered | until recovery |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W1 | 9 | 15 | 1 | 4 | move 4 9 1 | False | 1 | True | 0 | True | 12 |
| W2 | 6 | 25 | 1 | 2 | move 7 6 6 | False | 0 | False | 0 | True | 5 |
| W3 | 3 | 29 | 1 | 1 | move 8 3 1 | False | 0 | True | 1 | True | 65 |
| W4 | 8 | 30 | 0 | 1 | move 9 8 4 | False | 0 | True | 1 | True | 33 |
| W5 | 9 | 31 | 0 | 1 | move 6 9 6 | False | 0 | True | 1 | True | 7 |
| W6 | 6 | 32 | 0 | 2 | move 7 6 2 | False | 1 | True | 1 | True | 9 |
| W7 | 9 | 39 | 1 | 1 | move 2 9 3 | False | 0 | False | 1 | True | 17 |
| W8 | 6 | 43 | 1 | 2 | move 1 6 1 | False | 0 | False | 1 | True | 8 |

No single workspace-efficiency scalar is computed. Under unrestricted deal an empty column cannot survive a stock deal, so stock_deals_crossed_while_empty is expected to stay 0 and consumed_by_stock_deal records empties the deal itself spent.

## 11. Forward attribution findings

Forward question: at what point does one trajectory begin accumulating extra later cost? The evidence available from two finished routes is the segment in which B's MW spend pulls ahead, together with the structural measures at that boundary. That is a location, not a proof of avoidability.

- Before SD1 the gap (B minus A) is -18 MW. B is ahead on cost at that boundary.
- During opening tableau, before SD1, B spends 18 MW fewer than A. At the end of the segment, experimental debt sums are 75 (B) and 71 (A); positive-cost rehandle card-events to date are 25 and 62.
- During tableau between SD1 and SD2, B spends 6 MW fewer than A. At the end of the segment, experimental debt sums are 86 (B) and 71 (A); positive-cost rehandle card-events to date are 106 and 137.
- During tableau between SD2 and SD3, B spends 3 MW fewer than A. At the end of the segment, experimental debt sums are 126 (B) and 74 (A); positive-cost rehandle card-events to date are 121 and 170.
- During tableau between SD3 and SD4, B spends 31 MW more than A. At the end of the segment, experimental debt sums are 153 (B) and 102 (A); positive-cost rehandle card-events to date are 171 and 185.
- During tableau between SD4 and SD5, B spends 20 MW fewer than A. At the end of the segment, experimental debt sums are 197 (B) and 72 (A); positive-cost rehandle card-events to date are 178 and 235.
- During stock-empty endgame, B spends 29 MW more than A. At the end of the segment, experimental debt sums are 0 (B) and 0 (A); positive-cost rehandle card-events to date are 326 and 313.
- The finished gap is 13 MW. Signed non-zero segment differences (B minus A): opening tableau, before SD1 -18, tableau between SD1 and SD2 -6, tableau between SD2 and SD3 -3, tableau between SD3 and SD4 +31, tableau between SD4 and SD5 -20, stock-empty endgame +29. Those differences sum to the finished gap. A positive segment can be larger than the finished gap because other segments are negative. That is offsetting accounting. Do not convert one segment into a share of the finished gap. Positive-cost rehandle card-events differ by 13 (B minus A). Segment costs partition the gap. Rehandles, parks, and column debt overlap with it and are not a second partition.

## 12. Backward attribution findings

Backward question: which earlier decision made a later repair necessary? HIGH requires the repaired physical card to be the anchor of a HIGH-confidence park on the repaired column. MEDIUM is an overlapping placement or a stock landing whose column was arranged earlier. LOW is column correlation without that card link. None of these grades assign an exact future-move total.

HIGH sample (12 shown):

- **R33** columns [3] cards QD#B 6H#B 2C#A AC#B 4D#A 3D#A repair cost 4 at actions [88, 89, 90, 91]. Candidate cause: `move 10 3 1` (mixed_suit) at action 47. 2C#A was placed by move 10 3 1 at action 47 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R55** columns [4] cards AD#A 2D#B 8H#B 10C#A 9C#B repair cost 4 at actions [133, 134, 135, 136]. Candidate cause: `move 1 4 1` (mixed_suit) at action 121. 10C#A was placed by move 1 4 1 at action 121 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R41** columns [10] cards AH#A 3S#B 2S#A 4H#B repair cost 3 at actions [105, 106, 107]. Candidate cause: `move 7 10 1` (mixed_suit) at action 81. 3S#B was placed by move 7 10 1 at action 81 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R54** columns [9] cards JH#B AD#A 2C#B repair cost 3 at actions [130, 131, 132]. Candidate cause: `move 1 9 1` (mixed_suit) at action 120. 2C#B was placed by move 1 9 1 at action 120 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R62** columns [8] cards 8C#B 7C#B 2C#A AC#B 4D#A 3D#A repair cost 3 at actions [146, 147, 148]. Candidate cause: `move 3 8 2` (mixed_suit) at action 91. 4D#A was placed by move 3 8 2 at action 91 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R8** columns [1] cards 2S#A 3D#A repair cost 2 at actions [45, 46]. Candidate cause: `move 9 1 1` (mixed_suit) at action 15. 3D#A was placed by move 9 1 1 at action 15 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R17** columns [8] cards 6C#A 5C#B 7D#B repair cost 2 at actions [62, 63]. Candidate cause: `move 7 8 1` (mixed_suit) at action 42. 6C#A was placed by move 7 8 1 at action 42 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R28** columns [5] cards 2S#A 4D#B 3D#B repair cost 2 at actions [82, 83]. Candidate cause: `move 6 5 1` (mixed_suit) at action 53. 2S#A was placed by move 6 5 1 at action 53 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R39** columns [4] cards JH#A QD#B repair cost 2 at actions [102, 103]. Candidate cause: `move 3 4 1` (mixed_suit) at action 88. QD#B was placed by move 3 4 1 at action 88 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R46** columns [7] cards JH#A QD#B repair cost 2 at actions [112, 113]. Candidate cause: `move 4 7 1` (empty) at action 103. QD#B was placed by move 4 7 1 at action 103 (empty) and is in this repair. Park confidence was HIGH because: non-king material occupied an empty column and was later removed after a stock deal, a delay, or added obstruction
- **R49** columns [1] cards AD#A 2C#B repair cost 2 at actions [119, 120]. Candidate cause: `move 5 1 1` (mixed_suit) at action 80. AD#A was placed by move 5 1 1 at action 80 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R50** columns [6] cards 8H#B 9C#B repair cost 2 at actions [122, 123]. Candidate cause: `move 5 6 1` (mixed_suit) at action 79. 8H#B was placed by move 5 6 1 at action 79 (mixed_suit) and is in this repair. Park confidence was HIGH because: mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose

MEDIUM sample (12 shown):

- **R26** columns [5] cards 8H#B AD#A repair cost 2 at actions [79, 80]. Candidate cause: `deal` (stock_landing) at action 68. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 6 5 1.
- **R61** columns [6] cards 7C#B AD#B repair cost 2 at actions [144, 145]. Candidate cause: `deal` (stock_landing) at action 68. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 8 6 1.
- **R4** columns [9] cards 8S#B repair cost 1 at actions [38]. Candidate cause: `deal` (stock_landing) at action 36. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 6 9 6.
- **R6** columns [1] cards JS#B 10S#A 9S#B 8S#B 7S#A 6S#B repair cost 1 at actions [41]. Candidate cause: `deal` (stock_landing) at action 36. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 6 1 1.
- **R7** columns [10] cards 5C#B repair cost 1 at actions [44]. Candidate cause: `deal` (stock_landing) at action 36. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 8 10 1.
- **R18** columns [10] cards 7D#B repair cost 1 at actions [66]. Candidate cause: `move 8 10 1` (mixed_suit) at action 63. The repaired cards overlap an earlier non-building placement, but the link is not a single HIGH-confidence anchor removal. temporary non-building placement was later moved; more than one Spider objective is consistent with it
- **R19** columns [4] cards 7S#A 6S#B 5S#A 4S#B 3S#A 2S#B repair cost 1 at actions [67]. Candidate cause: `move 9 4 11` (mixed_suit) at action 61. The repaired cards overlap an earlier non-building placement, but the link is not a single HIGH-confidence anchor removal. mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose
- **R21** columns [8] cards 10D#B repair cost 1 at actions [70]. Candidate cause: `deal` (stock_landing) at action 68. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 2 8 8.
- **R22** columns [9] cards QH#B repair cost 1 at actions [71]. Candidate cause: `deal` (stock_landing) at action 68. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 8 9 2.
- **R23** columns [10] cards JD#B 10D#B repair cost 1 at actions [72]. Candidate cause: `deal` (stock_landing) at action 68. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 4 10 6.
- **R24** columns [2] cards AS#B repair cost 1 at actions [73]. Candidate cause: `deal` (stock_landing) at action 68. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 10 2 1.
- **R27** columns [7] cards 3S#B repair cost 1 at actions [81]. Candidate cause: `deal` (stock_landing) at action 78. A repaired card was dealt onto this column. The deal is mandatory; the choice is the tableau left for it to land on. Last tableau touch before that deal: move 8 7 4.

Counterfactual seeds recorded: 8. They are one ply of immediate metrics.

- Action 25 `move 6 4 1` is immediate rank 9 of 11. Locally ordinary on the immediate sort: False. It bought class MIXED_SUIT_PLACEMENT, cost 1, reveals none, bonds +0, face-down +0. Why selected: focus-column disorder increased and nothing was revealed. Better immediate alternatives include `move 7 3 4` (rank 1, focus disorder 0, debt sum 62), `move 5 2 3` (rank 2, focus disorder 0, debt sum 67), `move 3 5 1` (rank 3, focus disorder 0, debt sum 68).
- Action 29 `move 3 4 1` is immediate rank 8 of 9. Locally ordinary on the immediate sort: False. It bought class MIXED_SUIT_PLACEMENT, cost 1, reveals none, bonds +0, face-down +0. Why selected: focus-column disorder increased and nothing was revealed. Better immediate alternatives include `move 5 7 1` (rank 1, focus disorder 1, debt sum 62), `move 2 3 1` (rank 2, focus disorder 1, debt sum 67), `move 6 5 4` (rank 3, focus disorder 1, debt sum 67).
- Action 33 `move 2 4 1` is immediate rank 25 of 26. Locally ordinary on the immediate sort: False. It bought class MIXED_SUIT_PLACEMENT, cost 1, reveals none, bonds +0, face-down +0. Why selected: focus-column disorder increased and nothing was revealed. Better immediate alternatives include `move 4 6 1` (rank 1, focus disorder 1, debt sum 67), `move 5 7 1` (rank 2, focus disorder 2, debt sum 61), `move 3 6 1` (rank 3, focus disorder 2, debt sum 66).
- Action 61 `move 9 4 11` is immediate rank 14 of 16. Locally ordinary on the immediate sort: False. It bought class MIXED_SUIT_PLACEMENT, cost 1, reveals none, bonds +0, face-down +0. Why selected: focus-column disorder increased and nothing was revealed. Better immediate alternatives include `move 6 8 1` (rank 1, focus disorder 4, debt sum 97), `move 9 10 6` (rank 2, focus disorder 4, debt sum 97), `move 9 6 2` (rank 3, focus disorder 4, debt sum 97).
- Action 72 `move 10 4 2` is immediate rank 11 of 11. Locally ordinary on the immediate sort: False. It bought class MIXED_SUIT_PLACEMENT, cost 1, reveals none, bonds +0, face-down +0. Why selected: focus-column disorder increased and nothing was revealed. Better immediate alternatives include `move 9 1 2` (rank 1, focus disorder 4, debt sum 147), `move 8 10 4` (rank 2, focus disorder 4, debt sum 142), `move 3 1 1` (rank 3, focus disorder 4, debt sum 147).
- Action 88 `move 3 4 1` is immediate rank 10 of 11. Locally ordinary on the immediate sort: False. It bought class MIXED_SUIT_PLACEMENT, cost 1, reveals none, bonds +0, face-down +0. Why selected: focus-column disorder increased and nothing was revealed. Better immediate alternatives include `move 7 6 4` (rank 1, focus disorder 7, debt sum 175), `move 10 7 1` (rank 2, focus disorder 7, debt sum 178), `move 8 5 2` (rank 3, focus disorder 7, debt sum 180).

immediate child only; not a solved continuation and not a claim that the alternative saves a stated number of moves
A poor immediate rank is not evidence that the played move was a mistake. The sort is one ply. A reveal can rank worse because the newly exposed card raises column disorder, while an alternative that reveals nothing keeps the old top.

## 13. Earliest important divergences

The first 1 action(s) match. The next actions differ (`move 3 2 1` versus `move 6 8 2`). After that split the routes share no exact tableau until the solved terminal. The solved empty board is the same for every complete solution of this deal and is not a strategic reconvergence. This is different early ancestry after a short shared prefix, not one line continued at two costs.

Common prefix actions: 1. First differing action on A: `move 3 2 1`. First differing action on B: `move 6 8 2`. Shared exact states: 3. Strategic reconvergences after the prefix, excluding any solved terminal: 0. Shared solved terminals: 1. Post-stock symmetry-only pairs: 0.

pack_post_stock_symmetry_state is reported only when both states have empty stock and their ordered hashes differ. It is not used while stock remains.

## 14. What B teaches that A does not

- **part of the opening save is less excavation** (HIGH). machine-185 reaches pre-SD1 at g 32 with 18 face-down cards, 16 same-suit bonds, and 25 positive-cost rehandle card-events. human-172 is at g 50 with 12 face-down cards, 22 bonds, and 62 rehandle card-events. The cheaper line has exposed fewer cards.
- **cheaper pre-SD1 line** (HIGH). Corrected MW at pre-SD1 is 32 for machine-185 and 50 for human-172.
- **more zero-cost whole-column transfers before SD1** (HIGH). machine-185 plays 3 zero-cost whole-column moves before SD1; human-172 plays 1. action 30 `move 8 3 1` relocates 2H#A and leaves the source empty; action 31 `move 9 8 4` relocates 7H#A 6H#A 5H#B 4H#A and leaves the source empty; action 32 `move 6 9 6` relocates 7S#A 6S#B 5S#A 4S#B 3S#A 2S#B and leaves the source empty. Together they reveal nothing and add no same-suit bonds. They are free rearrangement of already-built runs and empty-column choreography before the deal. Each such move costs 0 only because it relocates an entire column onto an empty column.
- **fewer positive-cost tableau moves before SD1** (HIGH). 32 positive-cost moves on machine-185 versus 50 on human-172.
- **being ahead on g at stock-empty can hide a worse tableau** (HIGH). At post-SD5, machine-185 is at g 134 and human-172 is at 150 (B minus A -16), with bonds 30 versus 54 and experimental debt sum 277 versus 132. A policy that watches only g still prefers machine-185 here. The stock-empty endgame is where that lead is spent.

## 15. What A does materially better

- human-172 spends more before SD1 (50 versus 32), so it is not the cheaper opening.
- human-172 spends 31 fewer MW during tableau between SD3 and SD4 (17 versus 48 for machine-185).
- human-172 spends 29 fewer MW during stock-empty endgame (22 versus 51 for machine-185).
- human-172 spends 14 fewer MW in the exclusive class MIXED_SUIT_PLACEMENT (29 versus 43). This is an accounting bucket.
- human-172 spends 9 fewer MW in the exclusive class SAME_SUIT_MERGE (57 versus 66). This is an accounting bucket.
- Costs human-172 pays that machine-185 does not match: opening tableau, before SD1 (50 versus 32); tableau between SD1 and SD2 (37 versus 31); tableau between SD2 and SD3 (11 versus 8); tableau between SD4 and SD5 (30 versus 10); EMPTY_PLACEMENT (29 versus 20).
- At post-SD5, human-172 holds 54 same-suit bonds against 30 for machine-185, with experimental debt sum 132 against 277.
- At pre-SD1, post-SD1, pre-SD2, post-SD2, pre-SD3, post-SD3, pre-SD4, post-SD4, pre-SD5, post-SD5, stock-empty-endgame, human-172 keeps column 4 less disordered than machine-185.

## 16. Implications for future principal-line search

- The opening zero-cost whole-column transfers on B reveal nothing. Preserve them as free rearrangement of already-built runs onto empty columns. Do not preserve them as free reveals.
- Do not score a state by g alone once the stock is near empty. A route can be ahead on corrected MW while holding fewer same-suit bonds and a higher column-debt vector.
- Do not score a state by empty-column count or by the experimental debt sum alone. Both can disagree with the route that actually finishes cheaper.
- Add a column-disorder check before a stock deal: suit boundaries and rank discontinuities on the column that is about to receive a card, especially when the placement that raised them revealed nothing. The deal costs 1 either way; the top it lands on is the decision.
- Preserve physical-card identity inside diagnostics. Rank/suit notation collides on a two-deck deal and will mis-attribute rehandles.
- Backward repair links are evidence for which branch point to test. They are not yet a heuristic weight.
- Search changes wait on the bounded counterfactual in section 20. v0.105 does not change beam, DFS, UCS, A*, campaigns, or the principal-line policy.
- The routes share only a short prefix, then different early ancestry. A solver that imitates the reference from the first action would discard the machine opening rather than repair its continuation. A shared solved terminal means both routes finished the deal. It does not mean the lines reconverged strategically.

## 17. Metrics that proved useful

- **corrected MW by stock-boundary segment.** The segment differences sum to the finished gap, so they locate where moves are spent without aligning move text.
- **physical-card handle and rehandle counts.** Duplicate rank/suit cards make notation identity wrong. Deal-order ids show which card is actually shuttled.
- **column suit boundaries and rank discontinuities.** They describe mixed stacking and blockers directly. They move when a column is made harder to unwind.
- **per-column experimental debt vector.** The focus column's score can be the worst column and still be a minority of the tableau sum. The vector shows the other columns. A share of the score is not a share of the MW gap.

## 18. Metrics that were noisy or misleading

- **empty-column count.** B has more empty columns at the end of a segment where B also spent more MW: post-SD3 -> pre-SD4. More empties are not a quality signal on this pair.
- **HIGH park count.** Both routes record many HIGH parks (A 56, B 71). The grade marks a temporary placement that was later moved, with the recorded evidence. A single HIGH park is not a rare proof that the move created the finished gap.
- **one-ply immediate sort of legal alternatives.** The sort prefers lower focus disorder and lower face-down before it can represent what a reveal bought. A reveal can rank poorly because the exposed card raises disorder. That rank is not evidence the reveal was a mistake.

## 19. Explicit unknowns

- Two complete routes cannot show that a different move at a seed would finish cheaper. That requires a bounded replay of the alternative.
- Park confidence is a documented heuristic. A HIGH park can still have been the cheapest way to expose a card. When both routes have many HIGH parks, the count is a weak discriminator.
- Exclusive cost classes hide mixed motives. A REVEAL bucket move may also have been the move that disordered a column.
- Post-stock column symmetry is an exact automorphism only after the stock is empty. It does not identify similar openings.
- The experimental debt score has not been calibrated against remaining MW. Agreement on this pair would still be one observation.
- Column 4 was the requested focus. Verdict: reference_avoids_this_columns_disorder. A hotter argmax column at a horizon is a competing hypothesis, not a refutation, until a counterfactual separates them.
- The better-opening / worse-continuation hypothesis is only partly supported. The opening cost is lower. The continuation contains both savings and extra cost. Two routes cannot show that the opening caused the later extra cost.

## 20. Recommended next development step

From the machine state immediately before action 25 (`move 6 4 1`), the first recorded increase in focus-column 4 disorder (0 to 1, class MIXED_SUIT_PLACEMENT, revealed nothing). Run a bounded continuation that is forbidden from increasing that column's suit boundaries until the next stock boundary. Separately, start from the post-SD3 state: column 4 disorder is 7 on B versus 2 on A, cumulative g is 74 versus 101, and experimental debt on the column is 40 versus 12. Apply the same suit-boundary constraint until the next stock boundary. Compare corrected MW, same-suit bonds, and the debt vector at the next stock boundary with the original continuation. Do not launch a campaign or a whole-game search. Do not imitate the reference from the first action. The one-ply seeds are screens. A poor immediate rank on a reveal is not evidence that the reveal was a mistake, because the sort can punish the disorder of the card that was just exposed.

## Definitions

- **counterfactual_seed.** One legal ply of immediate metrics. Not a search and not a solved branch. A poor immediate rank on a reveal is not a verdict.
- **exclusive_cost_class.** Priority partition of each action's corrected MW cost so class costs sum to the route total. Tags are multi-label and are not a partition.
- **experimental_debt_score.** 3*suit_boundaries + 2*rank_discontinuities + buried_face_up + 2*component_layers + immobile_exposed. Face-down is in the indicator vector and is excluded from the score. Not a remaining-cost estimate.
- **park_confidence.** HIGH, MEDIUM, or LOW. LOW is retained as ambiguous evidence.
- **physical_card.** Index into the original deal file order, plus a label such as 7S#A. The suffix distinguishes duplicate rank/suit cards. Stock-deal placement is recorded and is not counted as a handle.
- **post_stock_symmetry_hash.** sha256 of pack_post_stock_symmetry_state when stock is empty, else null. Research identity only. Never applied while stock remains.
- **segment_gap.** Signed corrected-MW differences by stock-boundary segment sum to the finished gap. When some segments are negative, a larger positive segment is an offset. It is not a percentage of the gap.
- **solved_terminal.** A shared exact state that is solved is recorded separately from strategic reconvergence. It is the empty completed tableau.
- **state_hash.** sha256 of spider.packed_state.pack_state. Ordered columns. Not Zobrist.
- **undo.** Canonical analysis does not read Play Lab sessions and does not call undo.
- **version.** spider-solution-forensics-0.105
