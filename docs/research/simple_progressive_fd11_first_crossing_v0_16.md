# Simple Progressive Search v0.16: True One-Move-Slack FD11 First-Crossing

## 1. Verdict

`TRUE_ONE_MOVE_SLACK_CANDIDATES_EXIST_BUT_STALL` — delaying the fd11 reveal by exactly one primitive does produce a canonical state outside the known dead bubble, but that state still cannot reach fd10.

The complete depth-9 frontier has **759,780** states, of which only **6** have fd=12 (plus 1 fd=11, 759,773 fd=13). Expanding those 6 parents yields **6** true first-crossing depth-10 fd11 children: 5 re-enter the dead bubble; **1** is new. Its A+B+C graph is also 1,728 unique states through local depth 13, still fd 11, still no empty, still no foundation.

Post-reveal rearrangements of the known dead fd11 are not slack. Production `solve_progressive` is unchanged.

## 2. Phase 0 — dead fd11 bubble

- unique=1728 expected=1728 exhausted=True fd10=False empty=False fnd=False elapsed=2.5201007000141544 rss=22.703125

## 3. Phase 1 — classify the six v0.15 candidates

| # | class | first_fd11_depth | parent_fd | bubble | empties | run | legal |
| ---: | --- | ---: | ---: | --- | --- | ---: | ---: |
| 1 | TRUE_FIRST_CROSSING_DEPTH10 | 10 | 12 | True | [] | 6 | 5 |
| 2 | POST_REVEAL_DEPTH10 | 9 | 11 | True | [] | 6 | 5 |
| 3 | POST_REVEAL_DEPTH10 | 9 | 11 | True | [] | 6 | 5 |
| 4 | POST_REVEAL_DEPTH10 | 9 | 11 | True | [] | 5 | 4 |
| 5 | POST_REVEAL_DEPTH10 | 9 | 11 | True | [] | 7 | 8 |
| 6 | TRUE_FIRST_CROSSING_DEPTH10 | 10 | 12 | False | [] | 6 | 5 |

- POST_REVEAL=4 TRUE_FIRST_CROSSING=2 outside_bubble=1

## 4. Early continuation

- genuine 0: stop=max depth unique=1728 min_fd=11 fnd=0 elapsed=2.5

## 5. Phase 2 — complete fd12-parent harvest

- complete=True unique=1144496 keys_before_stream=1144490 parent_fd_counts={'13': 759773, '12': 6, '11': 1} skipped_non_fd12=759774 true_candidates=6 outside_bubble=1 elapsed=668.1065295000008 rss=569.921875

## 6. Phase 3 — continuation

- sources=1 unique=1728 stop=max depth min_fd=11 fnd=0 elapsed=2.506921500011231

## 7. Comparison table

| Candidate class | Count | In dead bubble | Outside bubble | Reaches fd10 |
| --- | ---: | ---: | ---: | ---: |
| v0.15 POST_REVEAL | 4 | 4 | 0 | False |
| v0.15 TRUE_FIRST_CROSSING | 2 | 1 | 1 | False |
| complete TRUE_FIRST_CROSSING | 6 | 5 | 1 | False |

## 8. Exactly one next recommendation

One-move slack produces one outside-bubble fd11, and it still stalls. Next: do not add a heuristic and do not search two-move slack in this line until that question is tasked separately.

## Integrity

Verdict TRUE_ONE_MOVE_SLACK_CANDIDATES_EXIST_BUT_STALL. v15 true=2 post=4 outside=1 fd10=no.

Base SHA `062f7b4ff034fec1aaee3d4afaca1c5b9bce87f8`. Deal `deals/4925153.txt`.
Production solve_progressive is unchanged. Depth-11 slack was not searched.

