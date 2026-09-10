# Simple Progressive Search v0.20: Alternate Buried-Stack Targeting

## 1. Verdict

`ALTERNATE_TARGETS_NOT_REACHED` — the control succeeded, but neither alternative target could be revealed inside the bounded envelope.

All 18 v0.19 fd12 exits uncovered the same buried stack (original 1-based column 2,
signature `h5,h9,h11,h1,d8`). Target-directed search rediscovered that easy reveal
(1 known-dead fd12 exit at depth 9, unique 99,300 before first reveal). Instructed
to clear column 1 it reduced face-up 9→7 over 500,000 states with **zero** reveals.
Instructed to clear column 7 it reduced face-up 17→10 over 500,000 states with **zero**
reveals. No fd10, no foundation.

TARGET_FACE_UP_COUNT ordering is a research heuristic with no proof or pruning authority.
Failure of an arm does **not** prove that target unreachable. Production `pack_state` /
`solve_progressive` are unchanged.

## 2. Root buried targets

- 1-based col 1: fd=4 fu=9 run=1 key=`c10,d12,c6,s8`
- 1-based col 2: fd=5 fu=5 run=1 key=`h5,h9,h11,h1,d8`
- 1-based col 7: fd=4 fu=17 run=1 key=`h8,c6,s10,d10`

## 3. v0.19 exit audit

- exits=18 by_target={'h5,h9,h11,h1,d8': 18} earliest={'h5,h9,h11,h1,d8': 8} known/new={'h5,h9,h11,h1,d8:KNOWN_DEAD_FD12': 15, 'h5,h9,h11,h1,d8:NEW_FD12_EXIT': 3}

## 4. Target arms

| Reveal target | Root FU | Unique | FD12 exits | New | Reaches FD10 |
|---|---:|---:|---:|---:|---:|
| Known/easy col2 | 5 | 100000 | 1 | 0 | False |
| Alternate col1 | 9 | 500000 | 0 | 0 | False |
| Alternate col7 | 17 | 500000 | 0 | 0 | False |

- control: first reveal depth 9, unique-before=99300, min FU=1, 88.2 s, 87 MiB, stop=`unique limit`
- alt1: min FU 9→7, 406 s, stop=`unique limit`, no target reveal
- alt2: min FU 17→10, 387 s, stop=`unique limit`, no target reveal

## 5. Downstream

- skipped: no new alternate exits

## 6. Exactly one next recommendation

Cheap target-clearance cannot expose the harder stacks inside this envelope. Next: do not raise v0.19's breadth limit here; a later task may try a different treatment.

## Integrity

Verdict ALTERNATE_TARGETS_NOT_REACHED. control_exits=1 alt1_exits=0 alt2_exits=0 fd10=False foundation=False.

Base SHA `5af74c3f204f23e92ff8573e833ec66de20c24af`. Deal `deals/4925153.txt`.
No broad fd13 exhaustion, no fd14 backtrack, no extra heuristic.

