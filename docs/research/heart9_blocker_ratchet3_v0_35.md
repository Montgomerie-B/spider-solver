# Spider Solver v0.35 — Gate 3 Ratchet: First JH Blocker Flip

## 1. Verdict

`GATE3_JH_NOT_FOUND_IN_ENVELOPE` — no Gate-3 witness in the bounded search

no Gate-3 witness in the bounded search. Gate 3 is the 1->0 face-down-blocker transition exposing JH while 9H stays down. GLOBAL_LB_GATE3=72 is valid (Gate 1 >= 70 plus two non-zero uncovers) and is not tightened with the unproved Gate-2 best-known 73. v0.34 JSON persisted 16 of 144 harvested Gate-2 states; v0.35 reconstructed 144 exact sources {"73": 16, "74": 48, "75": 80}. Fast path hits: 0/0/0. Directed waves A/B/C emptied at 184/368/440 unique with 0 JH flips. Source lock: all 144 states have stock_rows=2, no empties, immovable AH packet, SD3 consumed, SD4 withheld. This is not a global proof that Gate 3 is unreachable from the original Spade sources — only that the retained 144-state Gate-2 sample cannot cross it without SD4. SD4 never expanded. 9H was not searched.

- Branch: `agent/heart9-blocker-ratchet3-v0-35`
- Base SHA: `4344734d3ab817010e55b8bbf9761c8ae1daa42f`

## 2. Source reconstruction

- v0.34 persistence gap confirmed: `True`
- v0.34 JSON persisted 16 states; directed harvest reported 144 witnesses.
- Recovered Gate-2 states: **144** after exact-state dedup (**144**).
- Counts by full MW: `{"73": 16, "74": 48, "75": 80}`
- Expected: `{"73": 16, "74": 48, "75": 80}`
- Discrepancy: none
- All sources replay: `True`
- Snapshot: `docs/research/heart9_blocker_ratchet3_v0_35_gate2_sources.json`

- Source lock: stock_rows `{"2": 144}`; empties `{"0": 144}`; packet movable `{"False": 144}`; SD3 still available `0`.

## 3. Proof

- Gate-3 chain valid: `True`
- GLOBAL_LB_GATE3: **72** valid=`True`
- Per-source bound: Gate 3 >= g+1. Example 73 -> 74.
- B3 equals global LB: `False`

Any pre-SD4 Heart-1 route needs the unique 9H. Exposing that 9H requires exposing JH last. Gate 1 is proved at full MW 70. Each subsequent uncover of the still-buried 9H column costs at least 1 corrected MW, so AH then JH compose to GLOBAL_LB_GATE3 = 72. Gate 2 at 73 is best-known, not a proved minimum, and is not substituted into this bound.

## 4. Fast path

- Hits from 73 sources: **0**
- Hits from 74 sources: **0**
- Hits from 75 sources: **0**
- Cheapest one-move Gate 3: **None**

## 5. Search

- Waves used: `['A', 'B', 'C']`
- Levels: `[0, 1, 2, 3]`
- First hit: Nones / unique None at g=None
- Unique / expanded / generated / duplicates: 992 / 2704 / 4924 / 4076
- Runtime / RSS: 7.149339099967619s / 54.71875 MiB
- Stop: frontier empty
- SD4 expanded: `False`

## 6. Result

- B3 best-known: **None**
- Globally proved: `None` (None)
- Source Gate-2 band that produced B3: **None**
- Full path / MW: None / None
- Continuation from Gate 2: None
- Stock / fd / foundations: None / None / None
- Target face-up: `None`
- Target remaining face-down: `None`
- Replay: `None`

## 7. Boundary portfolio

- B3 / B3+1 / B3+2: `{}`
- SD3 status: `{"sd3_available": 0, "sd3_done": 0}`
- Persisted: `docs/research/heart9_blocker_ratchet3_v0_35_gate3_portfolio.json` (0 states)
- Every retained state has full path / MW / digest / origin / SD3 / continuation.

## 8. Condensation

{
  "v32_h9": false,
  "v32_s": 900,
  "v32_unique": 198303,
  "v33_first_s": 0.17,
  "v33_first_unique": 72,
  "v33_gate1_proved": true,
  "v34_b": 73,
  "v34_first_s": 0.04,
  "v34_first_unique": 41,
  "v34_proved": false,
  "v35_b3": null,
  "v35_first_s": null,
  "v35_first_unique": null,
  "v35_gate3": false,
  "v35_proved": false
}

## 9. Strategic learning

The Gate-2 C/C+1/C+2 sample is operationally uniform: SD3 consumed, zero empties, AH covering JH and not legally movable. Cost slack did not buy landing-structure diversity. Not turned into a heuristic.

## 10. Exactly one next recommendation

The retained Gate-2 C/C+1/C+2 sample is tableau-locked after SD3 (AH covers JH, no empties, packet immovable, SD4 withheld). Next: widen Gate-2 slack or build a cost-complete Gate-2 frontier that still has an empty or a 2H landing, then retry Gate 3. Do not expose 9H, do not search Heart 1, and do not take SD4.

## Integrity

Verdict GATE3_JH_NOT_FOUND_IN_ENVELOPE. SD4 expanded=False.
Gate 3 terminal. 9H not exposed. Full MW preserved. No production change. No large UCS.

