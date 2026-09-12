# Spider Solver v0.56 — Component-Aware Foundation-2 Search

## 1. Verdict

`COMPONENT_AWARE_SEARCH_IMPROVES_TOPOLOGY_NO_F2` — no F2, but descendants beat v0.55 root component classes

no F2, but descendants beat v0.55 root component classes. unique=332438 F2=None suit=None timing=None. The authorised post-SD5 component search compressed structure further than the v0.55 roots but still did not remove a second foundation. The shallow line is exhausted.

- Branch: `agent/sd5-component-aware-f2-search-v0-56`
- Base SHA: `7385aeac594fdff7312aa8d0180763646ef82f70`
- Envelope: MW<=110, unique 600000, 420.0s, 2560.0 MB RSS

## 2. Roots

```json
{
  "deal_now_raw": 720,
  "portfolio_raw": 512,
  "portfolio_timing": {
    "DEAL_NOW": 72,
    "PREP_THEN_DEAL": 440
  },
  "portfolio_categories": {
    "A_COVER": 40,
    "B_CONDENSE": 64,
    "E_DEAL_NOW": 60,
    "F_SUIT": 16,
    "G_FILL": 332
  },
  "combined_raw": 1232,
  "symmetry_unique": 1160,
  "convergences": 0,
  "timing": {
    "DEAL_NOW": 720,
    "PREP_THEN_DEAL": 440
  },
  "deal_replay_ok": true,
  "port_replay_ok": true
}
```

## 3. Search

```json
{
  "attempted": true,
  "unique": 332438,
  "expanded": 76981,
  "generated": 722154,
  "duplicate_skips": 349031,
  "stale_skips": 1292,
  "elapsed_s": 420.0070132999681,
  "peak_rss_mb": 1096.41796875,
  "stop_reason": "time limit",
  "min_g": 76,
  "max_g": 110,
  "min_live_g": 80,
  "closed_g": 79,
  "incumbent": null,
  "first_s": null,
  "first_unique": null,
  "first_g": null,
  "first_suit": null,
  "first_timing": null,
  "first_category": null,
  "sd5_expanded": false,
  "accounting_fail": false
}
```

## 4. Per-lane coverage

```json
{
  "names": [
    "cost",
    "s",
    "h",
    "d",
    "c",
    "work"
  ],
  "pops": {
    "cost": 13046,
    "s": 13046,
    "h": 13046,
    "d": 13045,
    "c": 13045,
    "work": 13045
  },
  "expansions": {
    "cost": 13044,
    "s": 12396,
    "h": 13039,
    "d": 12747,
    "c": 12955,
    "work": 12800
  },
  "stale": {
    "cost": 2,
    "s": 650,
    "h": 7,
    "d": 298,
    "c": 90,
    "work": 245
  }
}
```

## 5. Component progress by suit

```json
{
  "roots": {
    "s": {
      "cover": 8,
      "visible": 8,
      "edges": 0,
      "cond_len": 4,
      "gap": 9,
      "fd": 0,
      "longest": 4,
      "k_len": 1,
      "a_len": 3,
      "g": 87
    },
    "h": {
      "cover": 8,
      "visible": 8,
      "edges": 1,
      "cond_len": 4,
      "gap": 11,
      "fd": 0,
      "longest": 3,
      "k_len": 1,
      "a_len": 1,
      "g": 83
    },
    "d": {
      "cover": 4,
      "visible": 4,
      "edges": 0,
      "cond_len": 5,
      "gap": 5,
      "fd": 0,
      "longest": 5,
      "k_len": 3,
      "a_len": 5,
      "g": 86
    },
    "c": {
      "cover": 5,
      "visible": 5,
      "edges": 0,
      "cond_len": 7,
      "gap": 4,
      "fd": 0,
      "longest": 7,
      "k_len": 7,
      "a_len": 2,
      "g": 77
    }
  },
  "descendants": {
    "s": {
      "cover": 8,
      "visible": 8,
      "edges": 0,
      "cond_len": 4,
      "gap": 9,
      "fd": 0,
      "longest": 4,
      "k_len": 1,
      "a_len": 3,
      "g": 87
    },
    "h": {
      "cover": 6,
      "visible": 6,
      "edges": 3,
      "cond_len": 6,
      "gap": 11,
      "fd": 0,
      "longest": 5,
      "k_len": 1,
      "a_len": 1,
      "g": 91
    },
    "d": {
      "cover": 4,
      "visible": 4,
      "edges": 2,
      "cond_len": 6,
      "gap": 5,
      "fd": 0,
      "longest": 5,
      "k_len": 3,
      "a_len": 5,
      "g": 92
    },
    "c": {
      "cover": 4,
      "visible": 4,
      "edges": 2,
      "cond_len": 8,
      "gap": 2,
      "fd": 0,
      "longest": 7,
      "k_len": 7,
      "a_len": 4,
      "g": 96
    }
  },
  "improved": {
    "improved": true,
    "reasons": [
      "h:cover 8->6",
      "h:edges 1->3",
      "h:cond 4->6",
      "d:edges 0->2",
      "d:cond 5->6",
      "c:cover 5->4",
      "c:edges 0->2",
      "c:cond 7->8",
      "c:gap 4->2"
    ]
  }
}
```

## 6. Foundation 2 / replay

```json
{
  "foundation2": {
    "reached": false,
    "n": 0,
    "first_g": null,
    "best_g": null,
    "suit": null,
    "timing": null,
    "category": null,
    "origin_timings": {}
  },
  "replay": {}
}
```

## 7. vs v0.54

```json
{
  "v054_unique": 600000,
  "v056_unique": 332438,
  "v054_min_live_g": 83,
  "v054_closed_g": 82,
  "v056_min_live_g": 80,
  "v056_closed_g": 79,
  "v054_f2": false,
  "v056_f2": false,
  "v056_time_s": 420.0070132999681,
  "v056_rss_mb": 1096.41796875
}
```

## 8. Strategic interpretation

The authorised post-SD5 component search compressed structure further than the v0.55 roots but still did not remove a second foundation. The shallow line is exhausted.

Time, not the 600k unique cap, stopped the run: six-lane scoring is slower than v0.54 UCS (~77k expansions vs 219k). `closed_g` here is the cheapest live heap key, not a UCS completeness proof — suit lanes expand higher-`g` states on purpose. Limits were not raised.

No pre-SD4. No Foundation 3. No Ace-tail/6D/4S excavation. Production unchanged.

## 9. Files

{
  "report": "docs/research/sd5_component_aware_f2_search_v0_56.md",
  "result": "docs/research/sd5_component_aware_f2_search_v0_56.json",
  "progress": "docs/research/sd5_component_aware_f2_progress_v0_56.json",
  "fixture": null
}

## 10. Exactly one next recommendation

The shallow post-SD5 preparation/component-search line has had its authorised final test. Consolidate the research search kernel before any further strategic experiment.

