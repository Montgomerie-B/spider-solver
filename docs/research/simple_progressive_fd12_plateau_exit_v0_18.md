# Simple Progressive Search v0.18: FD12 Plateau Exit Audit

## 1. Verdict

`FD12_PLATEAU_HAS_NEW_FD11_EXITS_BUT_THEY_STALL` — new fd11 exit classes exist but their reachable region has no fd10/foundation.

The minimum-depth fd12 plateau **exhausts** at 20,736 symmetry classes and **never creates an empty**.
It has 8,640 fd11 exits: 720 land in the original 1,728-state dead region; **7,920 are new**.
Those new exits' complete shared graph also **exhausts** (19,008 classes, still fd 11, still no empty,
still no foundation). They are experimentally dead. This fd12 checkpoint cannot reach fd10 by any
legal post-stock continuation.

Production `pack_state` / `solve_progressive` are unchanged. Post-stock column symmetry is
research-only. Dead-region pruning is measurement-only and is not integrated.

## 2. FD12 root

- replay_ok=True path=110 cost=110 fd=12 stock=0 fnd=0 empties=[] run=6
- ordered digest: `53504b3101000000040b3a2c360835042302310b0d1c3b1a29040115191b112800032d2c2b00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- symmetry digest: `535053310100000000022d0c00032d2c2b00080d0c262139383706000812272a0524133201000b1716352b14092534332201000d3d3c3b3a39383726252423222100121413121d071d1c1b1a191817161534333231040115191b1128040b3a2c360835042302310b0d1c3b1a29041118360a2a280706050403020911033d3c0b0a290827`

## 3. Dead fd11 region

- unique=1728 expected=1728 exhausted=True min_fd=11 empty=0 fnd=0 surprises=0 elapsed=3.3207515999965835

Why this set may be pruned: fd cannot increase; stock is empty and cannot return;
the region is completely exhausted over all legal tableau play; it contains no fd10 and
no foundation. Entering it proves this continuation cannot make further hard progress.
This pruning is exact for this bounded graph only.

- stock0 A+B+C complete on fd12: True
- stock0 A+B+C complete on dead fd11: True

## 4. Phase 1 — fd12 plateau

- exhausted=True stop=frontier empty unique=20736 generated=145584 dups=116209 max_depth=18 elapsed=38.96551529999124 rss=59.60546875
- empty0=20736 empty1=0 empty_ge2=0 max_empties=0 max_run=9 max_adj=41 max_blocks=8
- classifier_surprises=0
- the plateau never creates, consumes, transfers or recreates an empty

- fd11 exit edges=8640 distinct classes=8640 known_dead=720 new=7920 earliest_new_depth=3
- new-exit classes are reported as experimentally dead after Phase 2 exhaustion; that fact is not fed back into Phase 1 and is not integrated

## 5. Direct dead exit vs first new exit

| Metric | Direct dead exit | New exit |
|---|---:|---:|
| Start fd | 12 | 12 |
| Plateau setup moves | 0 | 2 |
| FD after reveal | 11 | 11 |
| Empties before reveal | [] | [] |
| Empties after reveal | [] | [] |
| Run | 6 | 6 |
| Legal actions | 5 | 5 |
| In known dead region | True | False |
| Reaches fd10 | False | False |

## 6. Phase 2 — new fd11 continuation

- sources=7920 unique=19008 stop=frontier empty min_fd=11 fnd=0 empty=0 elapsed=32.39939059999597 rss=122.8359375
- fd10=False foundation=False
- the shared new-exit graph is a closed dead component (measurement only; not a production learner)

## 7. Exactly one next recommendation

This minimum-depth fd12 cannot reach fd10: its plateau exhausts, and every fd11 exit — including those outside the original 1,728-state dead region — exhausts without fd10 or a foundation. Next: backtrack one hard-progress level and look for a different fd12 checkpoint; do not add primitive slack around this same fd12 state.

## Integrity

Verdict FD12_PLATEAU_HAS_NEW_FD11_EXITS_BUT_THEY_STALL. plateau unique=20736 exhausted=True exit_classes=8640 known_dead=720 new=7920 fd10=False foundation=False.

Base SHA `3392f920d3d0bcffecb20c8c5dbd7182f83afd4e`. Deal `deals/4925153.txt`.
Production pack_state and solve_progressive are unchanged.
Two-move slack was not searched. The quotient and dead-set pruning are not integrated.

