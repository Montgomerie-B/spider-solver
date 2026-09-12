# Spider Solver v0.52 — Diamond 6D Access Cut

## 1. Verdict

`DIAMOND_6D_ACCESS_NOT_FOUND` — no D6_EXPOSED inside the dedicated envelope

no D6_EXPOSED inside the dedicated envelope. T5 unique=199 D6 cheap=None T6 ready=0 persist=0 F2=0. Diamond 6D access failed inside a dedicated envelope — same warning as Spade LAND5 / Club 5C. Stop Diamond excavation.

- Branch: `agent/diamond-6d-access-cut-v0-52`
- Base SHA: `b34b6edfc7e2e322f56a8b0a90bb33d54895afa9`
- Elapsed: 272.0176795999869s

## 2. Sources

- Raw v0.51 TAIL5_PERSISTS: **199**
- Replay: **199** (ok=True)
- Symmetry-unique: **199**
- MW distribution: `{'90': 18, '91': 92, '92': 64, '93': 25}`
- Categories: `{'D6_MULTI_MOVE_ACCESS': 199}`

TAIL5 packet audit (after v0.51 join, expected exposed and movable):

- exposed sources: 199
- movable sources: 199

## 3. 6D audit

- Physical copies counted: 398 (expect 2 per source)
- Sources with an exposed 6D: 0
- One-move-exposable sources: 0
- Both face-down sources: 0
- Blocker-depth distribution: `{'5': 9, '6': 13, '7': 12, '8': 99, '9': 33, '10': 102, '11': 42, '12': 45, '13': 13, '14': 30}`
- Upper-run classes: `{}`
- K_THROUGH_6: 0
- Principal blocker signatures: `{"(True, 8, ('5C', '4S', '10D'))": 87, "(True, 10, ('5C', '4S', '10D'))": 74, "(True, 12, ('8S', '7H', '6H'))": 45, "(True, 11, ('8S', '7H', '6H'))": 42, "(True, 14, ('8S', '7H', '6H'))": 30, "(True, 9, ('8S', '7H', '6H'))": 29, "(True, 10, ('8S', '7H', '6H'))": 28, "(True, 13, ('8S', '7H', '6H'))": 13, "(True, 6, ('5C', '4S', '10D'))": 13, "(True, 7, ('5C', '4S', '10D'))": 12, "(True, 8, ('8S', '7H', '6H'))": 12, "(True, 5, ('5C', '4S', '10D'))": 9}`

## 4. One-move scan

- Legal actions scanned: **2698**
- D6_EXPOSED children: **0** (cheapest None)
- Foundation-2 surprises: **0**

## 5. D6_EXPOSED search

- Reached: **False**
- Attempted: True
- First hit: none
- Cheapest g: **None**
- Unique / expanded / generated / dups: 66208 / 24598 / 229679 / 158882
- Runtime / RSS: 267.32050849997904s / 78.31640625 MB
- Stop: time limit
- Boundary n / bands: 0 / `{}`

## 6. TAIL6

- READY counts: `{}`
- Ready n: 0
- Transitions: join=0 persist=0 auto-remove=0 contract=0
- Visible TAIL6 cheapest: None

## 7. TAIL7 preview

- Counts: `{}`
- Optional join classes: `{}`

## 8. Foundation 2

- Reached: **False**
- n / cheapest: 0 / None
- Fixture: None

## 9. Strategic interpretation

Diamond 6D access failed inside a dedicated envelope — same warning as Spade LAND5 / Club 5C. Stop Diamond excavation.

- Diamond still operational leader: **False**

No TAIL6 search until 6D exposed. No Spade/Club/Heart/F3/rank-8. Production unchanged.

## 10. Files

```json
{
  "report": "docs/research/diamond_6d_access_cut_v0_52.md",
  "result": "docs/research/diamond_6d_access_cut_v0_52.json",
  "sources": "docs/research/diamond_tail5_sources_v0_52.json",
  "exposed": null,
  "tail6_ready": null,
  "tail6": null,
  "foundation2": null,
  "fixture": null
}
```

## 11. Exactly one next recommendation

Diamond 6D access failed inside a dedicated envelope — same warning signature as Spade LAND5 / Club 5C. Stop Diamond excavation. Do not start another 6D blocker ratchet.

