# strong_surplus_f4_bridge_v0_87

Verdict: `STRONG_F4_ZERO_SLACK_F5`

best F5 f=186

Hierarchical F4→F5 proof-aware bridge from v0.86 strong-surplus F4s. Canonical 172 was not a search input. v0.86 F5 path was not seeded.

## Structural telemetry

{'g141_v085_recorded': 28, 'g141_visible_runs': 36, 'g148_v085_recorded': 24, 'g148_visible_runs': 32, 'same_label_must_not_mix': True, 'v085_boundaries_field': 'mixed_suit_boundaries (interference_debt.boundaries_total)', 'v086_boundaries_field': 'visible_runs (current_tableau_summary.visible_runs)'}

## Active F4 roots

| root | g | h | f | slack | fd | empties | legal | visible_runs | mixed_suit_boundaries |
| ---- | -: | -: | -: | ----: | -: | ------: | ----: | -----------: | --------------------: |
| lowest_f | 154 | 27 | 181 | 5 | 2 | 0 | 11 | 29 | 19 |
| lowest_h | 155 | 26 | 181 | 5 | 2 | 0 | 10 | 28 | 18 |
| highest_mobility | 155 | 26 | 181 | 5 | 2 | 1 | 26 | 28 | 19 |

## Stage A probes

| root g | f | rank | target | stop | unique | raw | viable | best g | h | f | slack |
| -----: | -: | ---: | ------ | ---- | -----: | --: | -----: | -----: | -: | -: | ----: |
| 154 | 181 | 1 | h | time limit | 9551 | 0 | 0 | None | None | None | None |
| 154 | 181 | 2 | d | time limit | 9323 | 0 | 0 | None | None | None | None |
| 154 | 181 | 3 | c | time limit | 9635 | 0 | 0 | None | None | None | None |
| 154 | 181 | 4 | s | time limit | 9821 | 0 | 0 | None | None | None | None |
| 155 | 181 | 1 | h | time limit | 10112 | 0 | 0 | None | None | None | None |
| 155 | 181 | 2 | d | time limit | 9777 | 0 | 0 | None | None | None | None |
| 155 | 181 | 3 | c | time limit | 9912 | 0 | 0 | None | None | None | None |
| 155 | 181 | 4 | s | time limit | 10225 | 0 | 0 | None | None | None | None |
| 155 | 181 | 1 | h | time limit | 9932 | 18 | 18 | 172 | 14 | 186 | 0 |
| 155 | 181 | 2 | d | time limit | 8956 | 0 | 0 | None | None | None | None |
| 155 | 181 | 3 | c | time limit | 9506 | 0 | 0 | None | None | None | None |
| 155 | 181 | 4 | s | time limit | 9650 | 0 | 0 | None | None | None | None |

Stage B pairs: [[155, 'h'], [155, 'd'], [154, 'h'], [154, 'd']]

raw=35 viable=35 surplus=0 strong=0 closed=0 reopen=0

## Slack trajectory

{'F3': {'f': 177, 'g': 148, 'slack': 9}, 'F4': {'f': 181, 'slack': 5}, 'F5': {'f': 186, 'slack': 0}}

## Continuation

portfolio n=8 stop=`complete` unique=1150 exp=40 maxF=5 exhausted=True

wall_s=485.7

## Interpretation

Only the high-mobility F4 (g155/h26/f181, legal=26) cashed F5, at g172/h14/f=186 (loss +5). Sibling F4s with legal 10–11 produced no F5 in 30+30s. Slack decayed 9→5→0. Continuation of 8 zero-slack F5s returned complete (unique=1150, exp=40, maxF=5, no solution): those exact roots are closed. Hierarchical decomposition was more conclusive than v0.86 mixed 14-root continuation (time-limited).

## Next recommendation

Those exact f=186 F5 roots are exhausted. Return to rows=1 and test pre-Deal preparation after F2 before SD5.

