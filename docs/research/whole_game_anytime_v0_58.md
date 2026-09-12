# whole_game_anytime_v0_58

Verdict: `WHOLE_GAME_PROGRESS_NO_FOUNDATION`

A generic opening-to-solved multi-lane search ran for 900 seconds from the
untouched 4925153 deal. It exhausted every stock epoch, including empty
stock, and excavated face-down cards 44 → 13, but never completed a
foundation. No autonomous solution was produced.

This is a whole-game scheduler result, not a reason to reopen local F1
excavation or the post-SD5 F2 line.

---

## Envelope (one policy, one run)

- time: 900 s
- unique cap: 800,000
- RSS abort: 2560 MB
- corrected MW ceiling: 300
- no depth ceiling
- terminal: `state.is_solved()` only

Stopped on **time limit**. Unique 615,235 did not reach the 800k cap.
Peak RSS 1,060 MB, under the abort.

---

## Exact identity

- stock remaining: ordered `pack_state` (SPK1). Column permutation is not
  an identity because future Deal rows land on physical columns.
- stock empty: `pack_post_stock_symmetry_state` (SPS1).
- magics SPK1 / SPS1 cannot collide. Neither packing format was changed.

---

## Lanes (ordering only)

Shared cheapest-g TT. Round-robin. No suit-specific lanes.

| Lane | Key (lower better) |
|---|---|
| cost | `(g,)` |
| foundation | `(-foundations, face_down, stock_rows, g)` |
| reveal | `(face_down, -foundations, -empties, g)` |
| workspace | `(-empties, face_down, -run_compression, g)` |
| construction | `(-bonds, -longest_run, -merges, face_down, g)` |
| prep | `(-stock_rows, face_down, -bonds, -empties, g)` |
| epoch | `(stock_rows, -foundations, face_down, g)` |

PREP and EPOCH ADVANCE compete on Deal timing. Deal has no extra bonus
or penalty beyond engine cost 1.

Policy firewall: the adapter does not read `solutions/4925153_canonical.moves`,
the historical F1 path, F1/F2 suit identity, or known Deal timing.

---

## Main run totals

| metric | value |
|---|---|
| elapsed_s | 900.0 |
| peak_rss_mb | 1059.9 |
| unique | 615,235 |
| expanded | 101,659 |
| generated | 1,182,487 |
| duplicate_skips | 528,132 |
| stale_skips | 28,054 |
| expanded/s | 113.0 |
| min_g / max_g | 0 / 88 |
| min_live_g / closed_g | 6 / 5 |
| max_foundations | 0 |
| min_face_down | 13 (opening 44) |
| max_empty | 1 |
| solved | false |

### Per-lane

| lane | pops | expansions | stale |
|---|---|---|---|
| cost | 18,531 | 18,520 | 11 |
| foundation | 18,531 | 39 | 18,492 |
| reveal | 18,531 | 16,865 | 1,666 |
| workspace | 18,530 | 14,934 | 3,596 |
| construction | 18,530 | 14,754 | 3,776 |
| prep | 18,530 | 18,256 | 274 |
| epoch | 18,530 | 18,291 | 239 |

Foundation-lane expansions collapsed because foundation count never left 0,
so that heap was almost entirely stale copies of other lanes' work.

Structural scoring was cheap enough to expand ~113 nodes/s and generate
~1.3k children/s. Scoring was not the bottleneck; branching and duplicate
pressure were.

---

## Stock-epoch progression

Opening: 5 stock rows, 44 face-down, 0 foundations.

| rows | first g | first t | first unique | cheapest g | min fd | max f | best bonds |
|---|---|---|---|---|---|---|---|
| 5 | 0 | 0.02 s | 0 | 0 | 18 | 0 | 15 |
| 4 | 1 | 0.03 s | 9 | 1 | 16 | 0 | 17 |
| 3 | 7 | 0.06 s | 67 | 2 | 16 | 0 | 19 |
| 2 | 8 | 0.09 s | 115 | 3 | 13 | 0 | 20 |
| 1 | 9 | 0.13 s | 189 | 4 | 13 | 0 | 26 |
| 0 | 10 | 0.16 s | 237 | 5 | 13 | 0 | 34 |

EPOCH ADVANCE reached empty stock in a fraction of a second (cheapest
g=5 = five Deals). Closed g=5 means every ≤5-move path, including
Deal-only, was expanded. No foundation exists on those cheap Deal-only
paths.

---

## Foundation milestones

None. F1 was not reached. F2 was not reached.

---

## Best whole-game state reached

Preferred ranking: more foundations, then fewer face-down, then fewer
stock rows, then lower g.

- g=54, stock=0, foundations=0, face-down=13, empty=0
- same-suit bonds=19, longest visible run=7, merge edges=1
- t≈110 s, unique≈85,570

Strongest construction snapshot (not the same node): bonds=34, longest=8,
g=60, stock=0, face-down=26. Post-stock per-suit cover still 6–7; no
local F2.

---

## Autonomous solution

None. No `solutions/4925153_autonomous_v0_58.moves`.

Replay/accounting: no solution to replay. Engine Deal cost 1, capture/restore,
and canonical 172 replay tests remain green.

---

## After-the-run comparison (evaluation only)

- Historical machine F1 was g=21 with stock still remaining. This run
  never scored a foundation, including after reaching stock=0 at g=5.
- v0.56 failed to reach F2 from post-SD5/F1 despite better component
  topology. This run never entered that line.
- Canonical complete trace is 172 corrected MW. Not used for search.
- 119 is not the current target.

---

## Interpretation

The v0.57 kernel plus a Deal-inclusive whole-game identity can search
from the opening deal without experiment-chain imports. The seven-lane
scheduler is live and balanced on pops, but EPOCH ADVANCE burns stock
immediately and the foundation lane is inert until a foundation exists.
Post-stock excavation is real (fd 44→13, 8-card runs, cover 6–7) and
still does not complete a suit inside 900 s / 615k unique.

Do not respond by targeting the historical F1 path.

---

## Next recommendation

Stay on the whole-game path and address early scheduler diversity and
Deal-timing coordination so PREP/construction can mature before stock is
exhausted. Do not reopen local card/suit excavation.
