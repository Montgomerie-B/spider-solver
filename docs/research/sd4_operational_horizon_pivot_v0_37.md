# Spider Solver v0.37 — SD4 Operational-Horizon Pivot

## 1. Verdict

`SD4_UNLOCKS_H9_MULTIPLE_ROUTES` — macros A (324/324) and B (324/324) both expose 9H

macros A (324/324) and B (324/324) both expose 9H. SD4 row ['9D', 'JS', 'QH', '2D', '4C', 'QC', 'KC', '8C', 'JH', '9S']. Macro A unlocked 324/324; macro B unlocked 324/324. Continuation LB 4 valid=True. Independent depth-6 search incumbent=77 first_t=3.5063504000136163 (first hit at 3971 unique / depth 4). The later unique-limit at 250k is post-SD4 branching of the full depth-6 envelope, not a miss of the four-action unlock. SD5 never expanded. 9H is terminal. Diamond/2D is telemetry only. This is an operational-horizon statement for the explored Gate-2 lineage, not a proof that no pre-SD4 Heart route exists.

- Branch: `agent/sd4-operational-horizon-pivot-v0-37`
- Base SHA: `b30850880e1cc76789478e3824ff827269533a71`

## 2. Sources

{
  "n": 324,
  "cost_counts": {
    "73": 16,
    "74": 48,
    "75": 80,
    "76": 64,
    "77": 43,
    "78": 33,
    "79": 25,
    "80": 6,
    "81": 6,
    "82": 3
  },
  "cost_min": 73,
  "cost_max": 82,
  "all_replay_ok": true,
  "failures": 0
}

## 3. SD4 and macros

{
  "sd4": {
    "valid": true,
    "row": [
      "9D",
      "JS",
      "QH",
      "2D",
      "4C",
      "QC",
      "KC",
      "8C",
      "JH",
      "9S"
    ],
    "expected": [
      "9D",
      "JS",
      "QH",
      "2D",
      "4C",
      "QC",
      "KC",
      "8C",
      "JH",
      "9S"
    ],
    "c2": "JS",
    "c3": "QH",
    "c4": "2D",
    "c6": "QC",
    "c2_is_js": true,
    "c3_is_qh": true,
    "c4_is_2d": true,
    "c6_is_qc": true,
    "stock_rows": 2,
    "mismatch": null
  },
  "macros": {
    "A": {
      "hits": 324,
      "n": 324,
      "pct": 100.0,
      "first_failure": null
    },
    "B": {
      "hits": 324,
      "n": 324,
      "pct": 100.0,
      "first_failure": null
    },
    "labels": [
      "STOCK_MEDIATED_RELEASE",
      "STOCK_MEDIATED_SAME_SUIT_BUILD"
    ]
  }
}

## 4. Search

{
  "unique": 250000,
  "expanded": 73905,
  "generated": 632108,
  "duplicate_skips": 382424,
  "first_s": 3.5063504000136163,
  "first_unique": 3971,
  "first_g": 77,
  "incumbent": 77,
  "max_depth": 6,
  "complete_depth": false,
  "elapsed_s": 237.73626309999963,
  "peak_rss_mb": 150.49609375,
  "stop_reason": "unique limit",
  "sd5_expanded": false,
  "witnesses": 256
}

## 5. Proof / lower bound

{
  "continuation_lb": {
    "valid": true,
    "lb": 4,
    "deal_cost": 1,
    "js_costs": [
      1,
      1
    ],
    "ah_costs": [
      1
    ],
    "reasons": [],
    "rationale": "SD4 always costs 1. It places JS on AH in the still-buried 9H column. JS+AH is not a movable run, so JS must leave in its own action (cost >= 1). AH must then leave to flip original JH (cost >= 1; column still has face-down). JH must then leave to flip unique 9H (cost >= 1). One action flips at most one face-down card. Therefore continuation to H9 from this exact Gate-2 state is >= 4."
  },
  "local_plus4_optimal": true,
  "global_claim": false
}

## 6. H9 boundary

{
  "full_cost": 77,
  "full_path_length": 77,
  "continuation": 4,
  "source_g": 73,
  "stock_rows": 1,
  "fd": 5,
  "foundations": 1,
  "empties": [],
  "face_up_col": [
    "9H"
  ],
  "face_down_col": [
    "5H"
  ],
  "mandatory_ranks": {
    "Q": {
      "status": "face_up_buried",
      "count": 2,
      "column_1": 3,
      "zone": "up"
    },
    "J": {
      "status": "exposed_top",
      "count": 2,
      "column_1": 6,
      "zone": "up"
    },
    "10": {
      "status": "face_up_buried",
      "count": 2,
      "column_1": 6,
      "zone": "up"
    },
    "9": {
      "status": "exposed_top",
      "count": 2,
      "column_1": 2,
      "zone": "up"
    },
    "7": {
      "status": "face_up_buried",
      "count": 2,
      "column_1": 9,
      "zone": "up"
    },
    "3": {
      "status": "face_up_buried",
      "count": 2,
      "column_1": 4,
      "zone": "up"
    }
  },
  "qh_jh_same_suit": false,
  "c3_top": "JS",
  "c4_top": "AH",
  "c6_top": "JH",
  "full_replay_ok": true,
  "fixture": "solutions/4925153_v0_37_h9_best.moves.txt",
  "via": [
    "B"
  ]
}

## 7. Diamond interaction

{
  "gate2_2d": {
    "tableau": 0,
    "stock": 2,
    "sd4": 1,
    "sd5": 1,
    "sd4_has_2d": true,
    "sd5_has_2d": true
  },
  "sd4_2d_unique_pre_sd5": false,
  "ah_temporarily_on_2d": true,
  "ah_release_from_2d": {
    "legal_ah_dests": [],
    "can_release_now": false
  },
  "note": "Telemetry only. Diamond foundation is not searched."
}

## 8. Operational horizon

`HEART_OPERATIONAL_UNLOCK_AT_SD4`

## 9. Portfolio

{
  "n": 256,
  "bands": {
    "77": 32,
    "78": 224
  },
  "path": "docs/research/sd4_operational_horizon_pivot_v0_37_h9_portfolio.json"
}

## 10. Exactly one next recommendation

Heart operational unlock is at SD4 for this lineage. Next: choose the post-9H target — continue the Heart foundation, or reassess Diamonds now that 2D is the AH parking spot. Do not take SD5 yet. Do not inspect the human route.

## Integrity

Verdict SD4_UNLOCKS_H9_MULTIPLE_ROUTES. SD5 expanded=False.
Gate 4 terminal. No Heart foundation search. No Diamond search. No production change.

