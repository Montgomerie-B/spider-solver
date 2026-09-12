# Spider Solver v0.54 — Resource-Aware Foundation-2 Search

## 1. Verdict

`RESOURCE_AWARE_SEARCH_STATE_EXPLOSION` — Foundation 2 not found before unique/RSS limit

Foundation 2 not found before unique/RSS limit. roots=964 unique=600000 F2=None suit=None timing=None live=83. Even with ~1k resource-aware roots instead of 103k, Foundation 2 was not reached. Retreating to pre-SD4 receiving structure is now the justified next horizon, not another post-SD5 suit excavation.

- Branch: `agent/resource-aware-foundation2-search-v0-54`
- Base SHA: `4e48a9ed30a47ea77dadbde432da4eeff7f3179e`
- Elapsed: 298.7441793999751s

## 2. Roots

- DEAL_NOW raw: **720** (expected 720)
- PREP raw: **244**
- Combined raw: **964**
- Exact unique: **964**
- Convergences: 0
- MW: `{'76': 16, '77': 144, '78': 144, '79': 224, '80': 16, '81': 8, '83': 96, '84': 32, '85': 8, '86': 78, '87': 190, '89': 8}`
- Timing: `{'DEAL_NOW': 720, 'PREP_THEN_DEAL': 244}`
- PREP categories: `{'J_FILL': 164, 'F_EMPTY': 24, 'E_SHALLOW': 8, 'H_CHEAP_SUIT': 16, 'D_ONE_MOVE': 16, 'B_LONGEST': 16}`

## 3. Search

```json
{
  "attempted": true,
  "reached": false,
  "unique": 600000,
  "expanded": 218898,
  "generated": 1425275,
  "duplicate_skips": 826239,
  "elapsed_s": 297.4098490999895,
  "peak_rss_mb": 406.98828125,
  "stop_reason": "unique limit",
  "first_s": null,
  "first_unique": null,
  "first_g": null,
  "first_suit": null,
  "first_timing": null,
  "first_root_g": null,
  "continuation_mw": null,
  "min_live_g": 83,
  "closed_g": 82,
  "incumbent": null,
  "sd5_expanded": false,
  "accounting_fail": false,
  "final_action": null
}
```

## 4. Foundation portfolio

```json
{
  "n": 0,
  "bands": {},
  "suits": {},
  "timing": {},
  "fd": {},
  "empty_n": {}
}
```

## 5. Replay

```json
{}
```

## 6. Comparison to v0.43

```json
{
  "v043_roots": 103513,
  "v054_roots": 964,
  "root_reduction": 107.4,
  "v043_unique_budget": 600000,
  "v054_unique": 600000,
  "v043_min_live_g": 81,
  "v054_min_live_g": 83,
  "v054_closed_g": 82,
  "v054_first_g": null,
  "seeds_as_pct_of_unique": 0.16
}
```

## 7. Strategic interpretation

Even with ~1k resource-aware roots instead of 103k, Foundation 2 was not reached. Retreating to pre-SD4 receiving structure is now the justified next horizon, not another post-SD5 suit excavation.

No suit target. No low-tail constraint. No Deal. No Foundation 3. Production unchanged.

## 8. Files

```json
{
  "report": "docs/research/resource_aware_foundation2_search_v0_54.md",
  "result": "docs/research/resource_aware_foundation2_search_v0_54.json",
  "roots": "docs/research/resource_aware_foundation2_roots_v0_54.json",
  "portfolio": null,
  "fixture": null
}
```

## 9. Exactly one next recommendation

Condensed-root UCS still exploded before Foundation 2. Retreat to pre-SD4 receiving structure rather than widening MW or reseeding the 103k.

