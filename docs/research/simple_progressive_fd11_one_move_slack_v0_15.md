# Simple Progressive Search v0.15: One-Move-Slack FD11 Checkpoints

## 1. Verdict

`DEPTH10_FD11_ENUMERATION_INCOMPLETE` — the 1800 s cap stopped expansion after **640,378 / 759,780** depth-9 states (84.3%). This is a partial census, not a silent sample. Phase 2 was not run.

Streaming worked: v0.14's 1,144,490 depth-≤9 keys were retained exactly; 6,170,637 depth-10 successors were generated; 4,330,558 fd>11 children were discarded; only **6** extra keys were kept (the new fd11 candidates). RSS 569 MiB.

The six first-seen-at-depth-10 fd11 states found so far are all **empty-less**, with no immediate uncover or foundation move. That is observational and not exhaustive.

One extra primitive before fd11 is the only slack tested. Production `solve_progressive` is unchanged. Depth 11 was not searched.

## 2. Depth-9 regression

- first_depth fd11=9
- keys before stream=1144490 (v0.14 unique through depth 9=1144490)
- depth-9 expanded complete=False frac=640378/759780 (84.3%)

## 3. Depth-10 harvest

- successors generated=6170637 duplicates=1840073 discarded=4330558
- unique retained=1144496 elapsed=1800.354898000005 rss=568.7890625 stop=time limit
- new depth-10 fd11 candidates=6 (dead depth-9 re-hits excluded)
- empty0/1/ge2={'empty_0': 6, 'empty_1': 0, 'empty_ge2': 0}
- empty identities={'()': 6}
- run distribution={'6': 4, '5': 1, '7': 1}
- legal range=[4, 8] adj range=[38, 40] blocks range=[4, 5]
- direct fd10=False direct foundation=False

## 4. Phase 2 continuation

- not run.

## 5. Winner

- none.

## 6. Depth-9 dead vs depth-10 viable

| Metric | Depth-9 dead | Depth-10 viable |
| --- | ---: | ---: |
| FD | 11 | None |
| Depth from fd13 | 9 | None |
| Local MW cost | 9 | None |
| Empties | 0 | None |
| Run | 6 | None |
| Adjacencies | 39 | None |
| Movable blocks | 4 | None |
| Legal actions | 5 | None |
| Reaches fd10 | no | False |
| Continuation depth to fd10 | — | None |

## 7. Exactly one next recommendation

Do not raise limits here. Report the partial harvest and stop.

## Integrity

Verdict DEPTH10_FD11_ENUMERATION_INCOMPLETE. new_d10_fd11=6 complete=False fd10=no foundation=no.

Base SHA `2141aaf3b134459634ac42e025d52fe9697f4e52`. Deal `deals/4925153.txt`.
Production solve_progressive is unchanged. Depth 11+ fd11 states were not searched.

