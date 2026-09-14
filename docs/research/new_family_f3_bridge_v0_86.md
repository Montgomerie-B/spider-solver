# new_family_f3_bridge_v0_86

Verdict: `NEW_F3_BRIDGE_FINDS_STRONG_SURPLUS`

next-foundation f=181

Equal 90s proof-aware probes of the v0.85 new-family F3s. Old g141 is a frozen control, not a search root. Canonical 172 was not a search input.

## Roots

| name | g | h | f | slack | legal | boundaries | old digest? | ok |
| --- | -: | -: | -: | ----: | ----: | ---------: | --- | --- |
| NEW_CHEAP_F3 | 141 | 33 | 174 | 12 | 43 | 36 | differs=True | True |
| NEW_FIRST_F3 | 148 | 29 | 177 | 9 | 43 | 32 | differs=True | True |

## Root/target probes

| root g | h | f | rank | target | stop | unique | exp | raw | viable | best g | h | f | slack |
| -----: | -: | -: | ---: | ------ | ---- | -----: | --: | --: | -----: | -----: | -: | -: | ----: |
| 141 | 33 | 174 | 1 | h | time limit | 20260 | 1493 | 6 | 6 | 159 | 27 | 186 | 0 |
| 141 | 33 | 174 | 2 | c | time limit | 20515 | 1713 | 0 | 0 | None | None | None | None |
| 141 | 33 | 174 | 3 | d | time limit | 21711 | 1769 | 0 | 0 | None | None | None | None |
| 141 | 33 | 174 | 4 | s | time limit | 22626 | 1434 | 0 | 0 | None | None | None | None |
| 148 | 29 | 177 | 1 | h | time limit | 19938 | 1650 | 134 | 89 | 154 | 27 | 181 | 5 |
| 148 | 29 | 177 | 2 | d | time limit | 24649 | 1799 | 0 | 0 | None | None | None | None |
| 148 | 29 | 177 | 3 | c | time limit | 23572 | 1736 | 0 | 0 | None | None | None | None |
| 148 | 29 | 177 | 4 | s | time limit | 22770 | 1550 | 0 | 0 | None | None | None | None |

## Old g141 vs new g141

| metric | old g141 | new g141 |
| --- | ---: | ---: |
| g | 141 | 141 |
| h | 33 | 33 |
| f | 174 | 174 |
| slack | 12 | 12 |
| fd | 2 | 2 |
| empties | 2 | 2 |
| legal | 41 | 43 |
| boundaries | 36 | 36 |
| foundation suits | historical | ['c', 'd', 's'] |
| best next F | 4 | 4 |
| best next g | 161 | 159 |
| best next h | 25 | 22 |
| best next f | 186 | 186 |
| bridge loss | 12 | 12 |
| remaining slack | 0 | 0 |

## New g141 vs new g148

| metric | new g141 | new g148 |
| --- | ---: | ---: |
| root g | 141 | 148 |
| h | 33 | 29 |
| f | 174 | 177 |
| slack | 12 | 9 |
| boundaries | 36 | 32 |
| legal | 43 | 43 |
| best next f | 186 | 181 |
| bridge loss | 12 | 4 |
| terminal slack | 0 | 5 |
| time to first viable | 14.464644699997734 | 22.71315260004485 |

raw=140 viable=95 surplus1=5 strong=3 closed_hits=0 lower_g_reopen=0

## Continuation

portfolio n=14 stop=`time limit` unique=29915 exp=2026 maxF=5 exhausted=False

wall_s=900.1 reserve=180.0s no_stage_b=True

## Interpretation

At identical g/h/f, the new g141 still cash-outs Hearts to f=186 (loss +12), like old g141, though cheapest F4 g is 159 vs 161. The more-assembled new g148 (f=177, slack +9) reaches Hearts F4 at f=181 (slack +5, loss +4) with 89 viable terminals and continuation hit F5. Paying +7 MW before cash-out beat cheapest-F3 slack. Closed-state hits=0.

## Next recommendation

Make the strong-surplus next-foundation the next hierarchical root.

