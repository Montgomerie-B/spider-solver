# Counterfactual continuations v0.106

Deal 4925153. The autonomous 185 is the baseline. The human 172 is examined after ranking and is not used to choose candidates.

Sections 7 through 17 govern this run. Policies at one root share a state, a ceiling, and a stage budget. A lower experimental debt score is not a cheaper solution. TIME_LIMIT is not EXHAUSTED. The 172 route does not choose candidates. The deep profile runs only when it is requested by name.

Branch `local/counterfactual-continuations-v0-106`. HEAD `84b8d39dab0731e32938f590036cbd658e0d6c84`.

## Baseline validation

| Route | Corrected MW | Explicit actions | SHA-256 |
|---|---:|---:|---|
| Human canonical 172 | 172 | 174 | `18338a08576ad24e9af1f4ba2e7db3e28768788dd511e823193b1937f3feef33` |
| Autonomous 185 | 185 | 189 | `b19c56e957ac2666298a80118d54ff7fca6c8114ed7d27590e2e98a017d4fb73` |

Local ceiling: 184. Search prunes any child with corrected MW above 184. The verified baseline is 185. The ceiling is a local experimental bound, not the production ceiling. The original 185 suffix is retained and is not returned as a search result unless an exact later state is reached at a strictly lower g and the spliced suffix replays.

## Resources

Profile `pilot`. Workers requested 1, workers used 1. Search width used 1. Total seconds recorded 1680.185. Peak RSS MB 176.98.

One search runs at a time, so the RSS abort applies to a single frontier. A parallel worker pool is not started.

One best-g lane is used so every policy expands in the same cost order. candidate_width caps how many first moves are screened.

| Limit | Value |
|---|---:|
| total_time_s per root | 840.0 |
| root_time_s | 45.0 |
| root_unique | 80000 |
| screen_time_s | 12.0 |
| screen_unique | 20000 |
| candidate_width | 12 |
| deep_survivors per policy | 2 |
| deep_time_s | 150.0 |
| deep_unique | 200000 |
| max_depth | 64 |
| rss_abort_mb | 3072.0 |

## Policies

- **C0** (control). Unmodified legal actions, including Deal. Best-g search. No column restriction.
- **C1** (hard). Until the next stock deal, tableau moves that increase the focus column's exposed suit boundaries are hidden from search. They stay legal in the engine. Deal is allowed. The restriction lifts at the next deal.
- **C2** (soft). Every legal move remains available. At equal corrected MW cost, search expands a lower focus-column suit-boundary count, then fewer rank discontinuities, then more same-suit bonds. Corrected MW stays the primary key.
- **A-suppress** (suppress_one). At the experiment root only, hide the original first action. Later placements onto the focus column stay available.

Outcome: **Inconclusive**.

## Experiment A — before action 25

Root `pre-action-25`. Phase pre-SD1. Action index 25. Cumulative corrected MW 24. State `3611b6f9212aced9b157fef97089060032f9b36f5918a6484c7760a1d083649b`. Column 4 disorder 0. Elapsed 840.0 s of a 840.0 s budget.

### Policy comparison at this root

| Policy | Stage | Status | Stop | Expanded | Unique | Seconds | Terminal g | Foundations seen | Immediate deal |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| REFERENCE_SUFFIX | known-line | REFERENCE_SUFFIX |  |  |  |  |  |  | False |
| C0 | root | NODE_LIMIT | unique limit | 14182 | 80000 | 28.59 |  | 0 | False |
| C1 | root | NODE_LIMIT | unique limit | 16168 | 80000 | 24.179 |  | 0 | False |
| C2 | root | NODE_LIMIT | unique limit | 14109 | 80000 | 28.135 |  | 0 | False |
| A-suppress | root | NODE_LIMIT | unique limit | 14699 | 80000 | 29.381 |  | 0 | False |
| C0 | deep | TIME_LIMIT | time limit | 35549 | 189328 | 64.855 |  | 0 | False |
| C0 | deep | TIME_LIMIT | time limit | 34747 | 189089 | 64.854 |  | 0 | False |
| C1 | deep | NODE_LIMIT | unique limit | 40939 | 200000 | 60.612 |  | 0 | False |
| C1 | deep | NODE_LIMIT | unique limit | 40069 | 200000 | 60.92 |  | 0 | False |
| C2 | deep | TIME_LIMIT | time limit | 32812 | 178453 | 64.855 |  | 0 | False |
| C2 | deep | TIME_LIMIT | time limit | 30912 | 182079 | 64.855 |  | 0 | False |
| A-suppress | deep | TIME_LIMIT | time limit | 36693 | 195114 | 64.854 |  | 0 | False |
| A-suppress | deep | TIME_LIMIT | time limit | 35493 | 193069 | 64.855 |  | 0 | False |

### Next stock boundary

Deal-now is a legal boundary and is not a prepared tableau. A lower g on an immediate deal is the cost of dealing, not a better solution.

| Policy | Stage | Kind | g | g since root | Face-down | Foundations | Bonds | Empty | Disorder | Rehandles | Deal legal | Debt moved to 7 or 8 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| REFERENCE_SUFFIX | known-line | original_suffix_next_stock_boundary | 33 | 9 | 18 | 0 | 19 | 0 | 4 | 1 | True | False |
| C0 | root | best_scored_stock_boundary | 29 | 5 | 20 | 0 | 15 | 0 | 2 | 0 | True | False |
| C1 | root | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 15 | 0 | 2 | 0 | True | False |
| C2 | root | best_scored_stock_boundary | 29 | 5 | 20 | 0 | 15 | 0 | 2 | 0 | True | False |
| A-suppress | root | best_scored_stock_boundary | 30 | 6 | 20 | 0 | 16 | 0 | 2 | 0 | True | False |
| C0 | deep | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 15 | 0 | 3 | 1 | True | False |
| C0 | deep | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 15 | 0 | 3 | 0 | True | False |
| C1 | deep | best_scored_stock_boundary | 33 | 9 | 19 | 0 | 15 | 0 | 2 | 1 | True | False |
| C1 | deep | best_scored_stock_boundary | 32 | 8 | 19 | 0 | 15 | 0 | 2 | 0 | True | False |
| C2 | deep | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 16 | 0 | 3 | 0 | True | False |
| C2 | deep | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 15 | 0 | 3 | 0 | True | False |
| A-suppress | deep | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 15 | 0 | 3 | 1 | True | False |
| A-suppress | deep | best_scored_stock_boundary | 31 | 7 | 19 | 0 | 15 | 0 | 3 | 0 | True | False |

### Screen and deep effort

| Policy | Stage | First action | Status | Stop | Expanded | Unique | Seconds | Planned unique |
|---|---|---|---|---|---:|---:|---:|---:|
| C0 | screen | `move 3 5 1` | TIME_LIMIT | time limit | 2455 | 14472 | 5.684 | 20000 |
| C0 | screen | `move 6 4 1` | TIME_LIMIT | time limit | 2194 | 13341 | 5.677 | 20000 |
| C0 | screen | `move 7 3 4` | TIME_LIMIT | time limit | 2504 | 15196 | 5.677 | 20000 |
| C0 | screen | `move 7 5 5` | TIME_LIMIT | time limit | 2865 | 16143 | 5.676 | 20000 |
| C0 | screen | `move 7 9 2` | TIME_LIMIT | time limit | 2951 | 16196 | 5.677 | 20000 |
| C0 | screen | `move 9 3 2` | TIME_LIMIT | time limit | 2745 | 15948 | 5.677 | 20000 |
| C0 | screen | `move 9 5 3` | TIME_LIMIT | time limit | 3110 | 17263 | 5.677 | 20000 |
| C0 | screen | `move 5 2 3` | TIME_LIMIT | time limit | 2434 | 14774 | 5.676 | 20000 |
| C0 | screen | `move 5 4 6` | TIME_LIMIT | time limit | 2581 | 15584 | 5.677 | 20000 |
| C0 | screen | `move 5 6 5` | TIME_LIMIT | time limit | 2968 | 16667 | 5.677 | 20000 |
| C1 | screen | `move 3 5 1` | TIME_LIMIT | time limit | 3628 | 18024 | 5.676 | 20000 |
| C1 | screen | `move 7 3 4` | TIME_LIMIT | time limit | 3850 | 19631 | 5.676 | 20000 |
| C1 | screen | `move 7 5 5` | TIME_LIMIT | time limit | 3933 | 19577 | 5.678 | 20000 |
| C1 | screen | `move 7 9 2` | TIME_LIMIT | time limit | 3704 | 18289 | 5.677 | 20000 |
| C1 | screen | `move 9 3 2` | TIME_LIMIT | time limit | 3638 | 18070 | 5.676 | 20000 |
| C1 | screen | `move 9 5 3` | TIME_LIMIT | time limit | 3768 | 18291 | 5.676 | 20000 |
| C1 | screen | `move 5 2 3` | TIME_LIMIT | time limit | 3696 | 18728 | 5.679 | 20000 |
| C1 | screen | `move 5 6 5` | TIME_LIMIT | time limit | 3898 | 19191 | 5.676 | 20000 |
| C2 | screen | `move 3 5 1` | TIME_LIMIT | time limit | 2619 | 17253 | 5.678 | 20000 |
| C2 | screen | `move 7 3 4` | TIME_LIMIT | time limit | 2568 | 15607 | 5.68 | 20000 |
| C2 | screen | `move 5 2 3` | TIME_LIMIT | time limit | 2566 | 15717 | 5.677 | 20000 |
| C2 | screen | `move 5 6 5` | TIME_LIMIT | time limit | 2731 | 15753 | 5.676 | 20000 |
| C2 | screen | `move 7 5 5` | TIME_LIMIT | time limit | 2637 | 17326 | 5.676 | 20000 |
| C2 | screen | `move 7 9 2` | TIME_LIMIT | time limit | 2658 | 15877 | 5.677 | 20000 |
| C2 | screen | `move 9 3 2` | TIME_LIMIT | time limit | 2651 | 16423 | 5.677 | 20000 |
| C2 | screen | `move 9 5 3` | TIME_LIMIT | time limit | 2584 | 17809 | 5.676 | 20000 |
| C2 | screen | `move 6 4 1` | TIME_LIMIT | time limit | 2144 | 14217 | 5.676 | 20000 |
| C2 | screen | `move 5 4 6` | TIME_LIMIT | time limit | 2324 | 14158 | 5.677 | 20000 |
| A-suppress | screen | `move 3 5 1` | TIME_LIMIT | time limit | 1467 | 9108 | 5.678 | 20000 |
| A-suppress | screen | `move 7 3 4` | TIME_LIMIT | time limit | 1441 | 8987 | 5.676 | 20000 |
| A-suppress | screen | `move 7 5 5` | TIME_LIMIT | time limit | 1960 | 11312 | 5.677 | 20000 |
| A-suppress | screen | `move 7 9 2` | TIME_LIMIT | time limit | 2711 | 14952 | 5.676 | 20000 |
| A-suppress | screen | `move 9 3 2` | TIME_LIMIT | time limit | 2441 | 14303 | 5.677 | 20000 |
| A-suppress | screen | `move 9 5 3` | TIME_LIMIT | time limit | 2945 | 16309 | 5.677 | 20000 |
| A-suppress | screen | `move 5 2 3` | TIME_LIMIT | time limit | 2272 | 13890 | 5.676 | 20000 |
| A-suppress | screen | `move 5 4 6` | TIME_LIMIT | time limit | 2589 | 15572 | 5.676 | 20000 |
| A-suppress | screen | `move 5 6 5` | TIME_LIMIT | time limit | 2619 | 15198 | 5.677 | 20000 |
| C0 | deep | `move 3 5 1` | TIME_LIMIT | time limit | 35549 | 189328 | 64.855 | 200000 |
| C0 | deep | `move 7 3 4` | TIME_LIMIT | time limit | 34747 | 189089 | 64.854 | 200000 |
| C1 | deep | `move 3 5 1` | NODE_LIMIT | unique limit | 40939 | 200000 | 60.612 | 200000 |
| C1 | deep | `move 7 3 4` | NODE_LIMIT | unique limit | 40069 | 200000 | 60.92 | 200000 |
| C2 | deep | `move 3 5 1` | TIME_LIMIT | time limit | 32812 | 178453 | 64.855 | 200000 |
| C2 | deep | `move 7 3 4` | TIME_LIMIT | time limit | 30912 | 182079 | 64.855 | 200000 |
| A-suppress | deep | `move 3 5 1` | TIME_LIMIT | time limit | 36693 | 195114 | 64.854 | 200000 |
| A-suppress | deep | `move 7 3 4` | TIME_LIMIT | time limit | 35493 | 193069 | 64.855 | 200000 |

## Experiment B — immediately after SD3

Root `post-sd3`. Phase post-SD3. Action index 78. Cumulative corrected MW 74. State `1afac24bf8c16067d1c86e1e3de3adc92e1085f77cf51121cfc124e41f0610b4`. Column 4 disorder 7. Elapsed 840.0 s of a 840.0 s budget.

After this route's own third deal the corrected MW is 74 (before the deal 73). The reference route at its own third deal is 101 (before the deal 100). The machine is ahead by 27. Same stock horizon: immediately after each route's own third deal. The reference route is not an ancestor of this state and was not used to rank candidates.

### Policy comparison at this root

| Policy | Stage | Status | Stop | Expanded | Unique | Seconds | Terminal g | Foundations seen | Immediate deal |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| REFERENCE_SUFFIX | known-line | REFERENCE_SUFFIX |  |  |  |  |  |  | False |
| C0 | root | NODE_LIMIT | unique limit | 15019 | 80000 | 32.7 |  | 1 | False |
| C1 | root | NODE_LIMIT | unique limit | 15715 | 80000 | 41.0 |  | 1 | False |
| C2 | root | NODE_LIMIT | unique limit | 14362 | 80000 | 33.51 |  | 1 | False |
| C0 | deep | TIME_LIMIT | time limit | 38862 | 194506 | 87.014 |  | 1 | False |
| C0 | deep | TIME_LIMIT | time limit | 38092 | 185233 | 87.013 |  | 1 | False |
| C1 | deep | TIME_LIMIT | time limit | 28769 | 135123 | 87.013 |  | 1 | False |
| C1 | deep | TIME_LIMIT | time limit | 37790 | 183919 | 87.013 |  | 1 | False |
| C2 | deep | TIME_LIMIT | time limit | 38113 | 199058 | 87.013 |  | 1 | False |
| C2 | deep | TIME_LIMIT | time limit | 37363 | 198132 | 86.656 |  | 1 | False |

### Next stock boundary

Deal-now is a legal boundary and is not a prepared tableau. A lower g on an immediate deal is the cost of dealing, not a better solution.

| Policy | Stage | Kind | g | g since root | Face-down | Foundations | Bonds | Empty | Disorder | Rehandles | Deal legal | Debt moved to 7 or 8 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| REFERENCE_SUFFIX | known-line | original_suffix_next_stock_boundary | 123 | 49 | 2 | 1 | 39 | 0 | 13 | 31 | True | False |
| C0 | root | best_scored_stock_boundary | 79 | 5 | 7 | 1 | 29 | 0 | 10 | 0 | True | False |
| C1 | root | best_scored_stock_boundary | 80 | 6 | 6 | 1 | 29 | 0 | 10 | 0 | True | False |
| C2 | root | best_scored_stock_boundary | 80 | 6 | 7 | 1 | 29 | 0 | 9 | 0 | True | False |
| C0 | deep | best_scored_stock_boundary | 81 | 7 | 6 | 1 | 29 | 0 | 10 | 0 | True | False |
| C0 | deep | best_scored_stock_boundary | 81 | 7 | 6 | 1 | 29 | 0 | 10 | 0 | True | False |
| C1 | deep | best_scored_stock_boundary | 82 | 8 | 6 | 1 | 30 | 0 | 10 | 0 | True | False |
| C1 | deep | best_scored_stock_boundary | 81 | 7 | 6 | 1 | 29 | 0 | 10 | 0 | True | False |
| C2 | deep | best_scored_stock_boundary | 81 | 7 | 6 | 1 | 29 | 0 | 10 | 0 | True | False |
| C2 | deep | best_scored_stock_boundary | 81 | 7 | 6 | 1 | 29 | 0 | 10 | 0 | True | False |

### Screen and deep effort

| Policy | Stage | First action | Status | Stop | Expanded | Unique | Seconds | Planned unique |
|---|---|---|---|---|---:|---:|---:|---:|
| C0 | screen | `move 1 7 1` | TIME_LIMIT | time limit | 2874 | 15534 | 6.178 | 20000 |
| C0 | screen | `move 10 8 1` | TIME_LIMIT | time limit | 2840 | 15730 | 6.177 | 20000 |
| C0 | screen | `move 10 9 1` | TIME_LIMIT | time limit | 2634 | 13695 | 6.177 | 20000 |
| C0 | screen | `move 3 4 1` | TIME_LIMIT | time limit | 2582 | 14963 | 6.178 | 20000 |
| C0 | screen | `move 5 6 1` | TIME_LIMIT | time limit | 2865 | 15389 | 6.178 | 20000 |
| C0 | screen | `move 6 2 1` | TIME_LIMIT | time limit | 2710 | 14508 | 6.178 | 20000 |
| C0 | screen | `move 7 10 1` | TIME_LIMIT | time limit | 2666 | 15769 | 6.178 | 20000 |
| C0 | screen | `move 9 3 7` | TIME_LIMIT | time limit | 2938 | 16027 | 6.178 | 20000 |
| C0 | screen | `move 9 4 8` | TIME_LIMIT | time limit | 2985 | 15831 | 6.178 | 20000 |
| C0 | screen | `move 9 2 5` | TIME_LIMIT | time limit | 2976 | 16230 | 6.177 | 20000 |
| C0 | screen | `move 9 5 3` | TIME_LIMIT | time limit | 2894 | 15654 | 6.178 | 20000 |
| C0 | screen | `move 9 6 4` | TIME_LIMIT | time limit | 2950 | 15859 | 6.18 | 20000 |
| C1 | screen | `move 1 7 1` | TIME_LIMIT | time limit | 2860 | 15265 | 6.178 | 20000 |
| C1 | screen | `move 10 8 1` | TIME_LIMIT | time limit | 2879 | 15793 | 6.177 | 20000 |
| C1 | screen | `move 10 9 1` | TIME_LIMIT | time limit | 3024 | 14959 | 6.177 | 20000 |
| C1 | screen | `move 5 6 1` | TIME_LIMIT | time limit | 2761 | 14669 | 6.177 | 20000 |
| C1 | screen | `move 6 2 1` | TIME_LIMIT | time limit | 2943 | 15404 | 6.177 | 20000 |
| C1 | screen | `move 7 10 1` | TIME_LIMIT | time limit | 2778 | 15914 | 6.178 | 20000 |
| C1 | screen | `move 9 3 7` | TIME_LIMIT | time limit | 2968 | 15822 | 6.177 | 20000 |
| C1 | screen | `move 9 2 5` | TIME_LIMIT | time limit | 3002 | 15869 | 6.177 | 20000 |
| C1 | screen | `move 9 5 3` | TIME_LIMIT | time limit | 2940 | 15732 | 6.178 | 20000 |
| C1 | screen | `move 9 6 4` | TIME_LIMIT | time limit | 2961 | 15732 | 6.177 | 20000 |
| C2 | screen | `move 1 7 1` | TIME_LIMIT | time limit | 2766 | 15455 | 6.177 | 20000 |
| C2 | screen | `move 10 8 1` | TIME_LIMIT | time limit | 2766 | 15655 | 6.178 | 20000 |
| C2 | screen | `move 10 9 1` | TIME_LIMIT | time limit | 2884 | 15697 | 6.178 | 20000 |
| C2 | screen | `move 5 6 1` | TIME_LIMIT | time limit | 2766 | 14740 | 6.178 | 20000 |
| C2 | screen | `move 6 2 1` | TIME_LIMIT | time limit | 2789 | 15426 | 6.179 | 20000 |
| C2 | screen | `move 7 10 1` | TIME_LIMIT | time limit | 2518 | 15637 | 6.178 | 20000 |
| C2 | screen | `move 9 3 7` | TIME_LIMIT | time limit | 2762 | 15560 | 6.177 | 20000 |
| C2 | screen | `move 9 2 5` | TIME_LIMIT | time limit | 2789 | 15825 | 6.179 | 20000 |
| C2 | screen | `move 9 5 3` | TIME_LIMIT | time limit | 2378 | 13594 | 6.177 | 20000 |
| C2 | screen | `move 9 6 4` | TIME_LIMIT | time limit | 2342 | 13243 | 6.177 | 20000 |
| C2 | screen | `move 3 4 1` | TIME_LIMIT | time limit | 2213 | 13147 | 6.177 | 20000 |
| C2 | screen | `move 9 4 8` | TIME_LIMIT | time limit | 2712 | 14985 | 6.178 | 20000 |
| C0 | deep | `move 1 7 1` | TIME_LIMIT | time limit | 38862 | 194506 | 87.014 | 200000 |
| C0 | deep | `move 10 9 1` | TIME_LIMIT | time limit | 38092 | 185233 | 87.013 | 200000 |
| C1 | deep | `move 1 7 1` | TIME_LIMIT | time limit | 28769 | 135123 | 87.013 | 200000 |
| C1 | deep | `move 10 8 1` | TIME_LIMIT | time limit | 37790 | 183919 | 87.013 | 200000 |
| C2 | deep | `move 10 9 1` | TIME_LIMIT | time limit | 38113 | 199058 | 87.013 | 200000 |
| C2 | deep | `move 1 7 1` | TIME_LIMIT | time limit | 37363 | 198132 | 86.656 | 200000 |

Observed focus-debt drop with a rise in column 7 or 8:

- C0-screen-move 6 2 1. This is a vector change, not a terminal-cost result.
- C2-screen-move 6 2 1. This is a vector change, not a terminal-cost result.

## Answers

### 1. Could the column-4 intervention at action 25 preserve the economical opening?

The recorded action `move 6 4 1` costs 1 and changes column-4 suit boundaries from 0 to 1. On the verified 185 the next stock boundary after this root is at corrected MW 33 (9 since the root, 12 actions). C1 hid 2 actions and left 9 legal actions; A-suppress hid 1 action and left 10 legal actions. No verified continuation showed those three zero-cost moves surviving an intervention. The restrictions left other legal moves in place, so they did not by themselves discard the opening. Preservation is unresolved.

### 2. Did the intervention avoid debt or merely move it?

Observed: focus debt fell while column 7 or 8 rose on B C0-screen-move 6 2 1, B C2-screen-move 6 2 1. That is a transfer of the diagnostic vector. It is not a terminal-cost result.

### 3. Did the restriction sacrifice valuable reveals, compression, or workspace?

Experiment A: C0 allowed 11 and C1 allowed 9 of 11 engine-legal actions. Hidden: move 5 4 6, move 6 4 1. Experiment B: C0 allowed 13 and C1 allowed 11 of 13 engine-legal actions. Hidden: move 3 4 1, move 9 4 8. The hidden actions stay legal in the engine. Deal stays available. No pair of finished solutions separates a sacrificed reveal from an unused one. A terminal sacrifice is unresolved.

### 4. How did hard restriction compare with soft preference?

Experiment A root workers, same planned stage budget. C0: NODE_LIMIT in 28.59 s, expanded 14182, unique 80000, foundations seen 0, minimum focus boundaries seen 0; C1: NODE_LIMIT in 24.179 s, expanded 16168, unique 80000, foundations seen 0, minimum focus boundaries seen 0; C2: NODE_LIMIT in 28.135 s, expanded 14109, unique 80000, foundations seen 0, minimum focus boundaries seen 0. Experiment B root workers, same planned stage budget. C0: NODE_LIMIT in 32.7 s, expanded 15019, unique 80000, foundations seen 1, minimum focus boundaries seen 3; C1: NODE_LIMIT in 41.0 s, expanded 15715, unique 80000, foundations seen 1, minimum focus boundaries seen 3; C2: NODE_LIMIT in 33.51 s, expanded 14362, unique 80000, foundations seen 1, minimum focus boundaries seen 3. Equal corrected MW remains the primary key. The soft key does not remove moves.

### 5. Could the post-SD3 state produce a cheaper continuation?

No replay-verified continuation below 185 was produced from the post-SD3 state. The searches that stopped on a budget remain unresolved rather than disproven.

### 6. Did the original 27-move lead contain recoverable value?

At this stock horizon the machine's corrected MW is 74 and the reference is 101, a lead of 27. The lead is a measurement on the verified routes. This run did not convert it into a finished total below 185. Whether it is recoverable remains unresolved.

### 7. Which intermediate structural measurements predicted eventual success or failure?

No verified solution below 185 was available to test a predictor. Column-4 disorder, same-suit bonds, face-down count, and the diagnostic debt vector were recorded. None is confirmed here as an early-warning signal of eventual cost. A lower focus-boundary count inside a budget is a search observation, not a prediction. Experiment A: 49 retained boundaries had column-4 disorder 2–3 against the 185 suffix boundary's 4, but same-suit bonds were 13–16 against 19 and face-down cards were 19–20 against 18. Those searches spent 4–9 corrected MW to the deal; the 185 suffix spends 9. Lower disorder here is not structural readiness.

### 8. Did any intervention produce a valid solution below 185?

No intervention produced a replay-verified solution at corrected MW 184 or below.

### 9. Which candidates remain unresolved rather than disproven?

Unresolved budgets: MEMORY_LIMIT 0, NODE_LIMIT 9, TIME_LIMIT 83. EXHAUSTED 0. EXHAUSTED is disproven only inside the stated contract, and a C1 exhaustion does not show that a hidden move was required. TIME_LIMIT is not EXHAUSTED. A low heuristic rank is not a hopeless label.

### 10. What, specifically, should the next solver learn from the evidence?

Best-g search meets an immediate legal deal before it can imitate the 185's longer preparation for the next deal. A useful next test has to spend tableau moves before dealing, or it has to notice an exact later state of a verified route. Column-4 disorder was not shown to be an early-warning signal of terminal cost, and it was not shown to be irrelevant. Do not add a heuristic whose job is to keep every column tidy.

## Machine behaviour to preserve

- Corrected MobilityWare accounting, including a zero cost for relocating an entire column onto an empty column.
- Unrestricted Deal. Every policy in this experiment leaves Deal available, including when a column is empty.
- The verified 185's opening economy and its three zero-cost whole-column moves. This run did not produce a finished line that shows those moves are harmful.

## Machine behaviour to discourage

- None. The bounded searches did not show an expensive structural pattern that a verified alternative avoided.

## Still unknown

- Whether any complete continuation from these roots costs less than 185 corrected MW.
- Whether column-4 disorder is an early-warning signal of eventual cost or a correlate of other structure.
- Whether the action-25 placement avoids later cost, creates it, or only moves the diagnostic vector.
- Whether the post-SD3 lead of 27 corrected MW can be converted into a lower finished total.
- The terminal value of every candidate that stopped on time, nodes, or memory.

## Causal labels

### observed

- Experiment A: `move 6 4 1` changed column-4 suit boundaries from 0 to 1 at cost 1.

### controlled

- Experiment A compared policies from one packed state under one stage budget: C0 NODE_LIMIT unique 80000; C1 NODE_LIMIT unique 80000; C2 NODE_LIMIT unique 80000; A-suppress NODE_LIMIT unique 80000.
- Experiment B compared policies from one packed state under one stage budget: C0 NODE_LIMIT unique 80000; C1 NODE_LIMIT unique 80000; C2 NODE_LIMIT unique 80000.

### inferred

- No inferred causal claim about the 13-move gap is made from an unfinished branch.

### unresolved hypothesis

- A definite terminal-cost saving cannot be attributed to an intervention without a verified complete alternative.
- No such alternative was verified in this run.

## Where structural metrics misled

- Experiment A: 49 retained boundaries had column-4 disorder 2–3 against the 185 suffix boundary's 4, but same-suit bonds were 13–16 against 19 and face-down cards were 19–20 against 18. Those searches spent 4–9 corrected MW to the deal; the 185 suffix spends 9. Lower disorder here is not structural readiness.
- Experiment B: 43 retained boundaries had column-4 disorder 6–10 against the 185 suffix boundary's 13, but same-suit bonds were 27–30 against 39 and face-down cards were 6–9 against 2. Those searches spent 5–8 corrected MW to the deal; the 185 suffix spends 49. Lower disorder here is not structural readiness.

## Endgame

No fully solved alternative was generated.


## Interpretation

Recorded searches: 92. Status counts: 9 NODE_LIMIT, 83 TIME_LIMIT.

No policy produced a complete continuation whose independent replay is cheaper than 185.

An unresolved budget is not evidence that the original 185 decisions are optimal.

A cleaner column at an intermediate state is supporting evidence only. The claim of improvement requires the replayed solution.

## Limitations

- A structurally cleaner column is supporting evidence only.
- The first solved terminal under the ceiling is one verified line, not a proof of the minimum.
- An unresolved budget is not evidence that the 185 decisions are optimal.
- C1 exhaustion shows only that the restriction contained no cheaper solution.
- TIME_LIMIT is not EXHAUSTED.
- Deal-now is legal and is not a prepared tableau.
- The experimental debt score is recorded and is not an optimisation target.
- A 172 suffix match is examined after ranking and does not choose the candidate.
