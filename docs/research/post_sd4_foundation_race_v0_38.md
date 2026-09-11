# Spider Solver v0.38 — Post-SD4 Foundation Race: Heart 1 vs Diamond 1

## 1. Verdict

`NO_SECOND_FOUNDATION_IN_ENVELOPE` — neither Heart 1 nor Diamond 1 reached before SD5

neither Heart 1 nor Diamond 1 reached before SD5. post-SD4 helper leak confirmed=True. Current material: Heart1=True Diamond1=True Spade2=False Club1=False. SD4 2D current_count=1 (unique pre-SD5=True); 5D current_count=1. Search H BOUNDED_MISS / Search D BOUNDED_MISS (MW<=100 tableau component exhausted, no foundation). Equal 450s/500k envelopes. SD5 never expanded. Sunk-cost Heart history was not used as a prior.

- Branch: `agent/post-sd4-foundation-race-v0-38`
- Base SHA: `45080bfa768298def726fe473ea5bc12e0963bd8`

## 2. Horizon audit

{
  "pre_sd4_hearts_leak": {
    "confirmed": true,
    "stock_rows": 1,
    "legacy_count": 2,
    "legacy_zones": [
      "up",
      "sd3"
    ],
    "current_tableau_count": 1,
    "future_stock_count": 1,
    "reason": "After SD4, stock_deal_rows(state.stock)[0] is SD5. pre_sd4_hearts() still appends that row as zone='sd3', so post-SD4 occurrence telemetry includes cards that are not yet materially available."
  },
  "material": {
    "stock_rows": 1,
    "next_row": [
      "3H",
      "10H",
      "2D",
      "3C",
      "9H",
      "7C",
      "7H",
      "AS",
      "3C",
      "5D"
    ],
    "suits": {
      "s": {
        "name": "Spades",
        "complete_sets_now": 1,
        "complete_sets_after_sd5": 2,
        "first_available_now": true,
        "second_available_now": false,
        "missing_for_first_now": [],
        "missing_for_second_now": [
          "A"
        ],
        "missing_for_first_after_sd5": [],
        "sd5_supplies": [
          "AS"
        ]
      },
      "h": {
        "name": "Hearts",
        "complete_sets_now": 1,
        "complete_sets_after_sd5": 2,
        "first_available_now": true,
        "second_available_now": false,
        "missing_for_first_now": [],
        "missing_for_second_now": [
          "3",
          "7",
          "9",
          "10"
        ],
        "missing_for_first_after_sd5": [],
        "sd5_supplies": [
          "3H",
          "10H",
          "9H",
          "7H"
        ]
      },
      "d": {
        "name": "Diamonds",
        "complete_sets_now": 1,
        "complete_sets_after_sd5": 2,
        "first_available_now": true,
        "second_available_now": false,
        "missing_for_first_now": [],
        "missing_for_second_now": [
          "2",
          "5"
        ],
        "missing_for_first_after_sd5": [],
        "sd5_supplies": [
          "2D",
          "5D"
        ]
      },
      "c": {
        "name": "Clubs",
        "complete_sets_now": 0,
        "complete_sets_after_sd5": 2,
        "first_available_now": false,
        "second_available_now": false,
        "missing_for_first_now": [
          "3"
        ],
        "missing_for_second_now": [
          "3",
          "7"
        ],
        "missing_for_first_after_sd5": [],
        "sd5_supplies": [
          "3C",
          "7C",
          "3C"
        ]
      }
    },
    "candidate_first_foundations_now": [
      "Hearts",
      "Diamonds"
    ],
    "heart_1_now": true,
    "diamond_1_now": true,
    "spade_2_now": false,
    "club_1_now": false
  },
  "horizon_ok": true
}

## 3. Heart backward map

{
  "aggregate": {
    "n": 256,
    "hard_on_all": [
      "10",
      "3",
      "7",
      "9"
    ],
    "hard_on_some": {
      "3": 256,
      "7": 256,
      "9": 256,
      "10": 256
    },
    "alternative_on_all": [
      "2",
      "4",
      "5",
      "6",
      "8",
      "A",
      "J",
      "K",
      "Q"
    ],
    "gate_status": {
      "3H:face_up_buried": 256,
      "7H:face_up_buried": 256,
      "9H:exposed_blocked": 224,
      "10H:face_up_buried": 256,
      "9H:exposed_movable": 32
    }
  },
  "detail_source0": {
    "hard_ranks": [
      "3",
      "7",
      "9",
      "10"
    ],
    "alternative_ranks": [
      "A",
      "2",
      "4",
      "5",
      "6",
      "8",
      "J",
      "Q",
      "K"
    ],
    "components": [],
    "nearest_gates": [
      {
        "card": "3H",
        "status": "face_up_buried",
        "column_1": 4,
        "cards_above": 8,
        "face_up_above": [
          "2H",
          "KH",
          "7S",
          "6H",
          "KH",
          "QS",
          "2D",
          "AH"
        ],
        "movable": false,
        "requires_reveal": false,
        "requires_landing": false
      },
      {
        "card": "7H",
        "status": "face_up_buried",
        "column_1": 9,
        "cards_above": 10,
        "face_up_above": [
          "6H",
          "5C",
          "QH",
          "JD",
          "10D",
          "9D",
          "8D",
          "5D",
          "4H",
          "JH"
        ],
        "movable": false,
        "requires_reveal": false,
        "requires_landing": false
      },
      {
        "card": "9H",
        "status": "exposed_blocked",
        "column_1": 2,
        "cards_above": 0,
        "face_up_above": [],
        "movable": false,
        "requires_reveal": false,
        "requires_landing": true
      },
      {
        "card": "10H",
        "status": "face_up_buried",
        "column_1": 6,
        "cards_above": 4,
        "face_up_above": [
          "9C",
          "8D",
          "QC",
          "JH"
        ],
        "movable": false,
        "requires_reveal": false,
        "requires_landing": false
      }
    ]
  },
  "macro_a_77_components": [
    {
      "column_0": 2,
      "column_1": 3,
      "cards": [
        "QH",
        "JH"
      ],
      "length": 2,
      "head": "QH",
      "tail": "JH"
    }
  ],
  "macro_b_77_components": []
}

## 4. Diamond backward map

{
  "aggregate": {
    "n": 256,
    "hard_on_all": [
      "2",
      "5"
    ],
    "hard_on_some": {
      "2": 256,
      "5": 256
    },
    "alternative_on_all": [
      "10",
      "3",
      "4",
      "6",
      "7",
      "8",
      "9",
      "A",
      "J",
      "K",
      "Q"
    ],
    "gate_status": {
      "2D:face_up_buried": 256,
      "5D:face_up_buried": 256
    }
  },
  "detail_source0": {
    "hard_ranks": [
      "2",
      "5"
    ],
    "alternative_ranks": [
      "A",
      "3",
      "4",
      "6",
      "7",
      "8",
      "9",
      "10",
      "J",
      "Q",
      "K"
    ],
    "components": [],
    "nearest_gates": [
      {
        "card": "2D",
        "status": "face_up_buried",
        "column_1": 4,
        "cards_above": 1,
        "face_up_above": [
          "AH"
        ],
        "movable": false,
        "requires_reveal": false,
        "requires_landing": false
      },
      {
        "card": "5D",
        "status": "face_up_buried",
        "column_1": 9,
        "cards_above": 2,
        "face_up_above": [
          "4H",
          "JH"
        ],
        "movable": false,
        "requires_reveal": false,
        "requires_landing": false
      }
    ]
  },
  "sd4_2d": {
    "suit": "d",
    "rank": 2,
    "rank_str": "2",
    "current_count": 1,
    "tableau_count": 1,
    "foundation_count": 0,
    "future_stock_count": 1,
    "future_after_SD5_count": 2,
    "hard": true,
    "alternative": false,
    "absent_now": false,
    "tableau": [
      {
        "zone": "CURRENT_TABLEAU",
        "face_up": true,
        "column_0": 3,
        "column_1": 4,
        "up_index": 8,
        "face_up_above": [
          "AH"
        ],
        "cards_above": 1,
        "top": false
      }
    ],
    "foundations": [],
    "next_stock": [
      {
        "zone": "NEXT_STOCK_ROW",
        "column_0": 2,
        "column_1": 3,
        "card": "2D",
        "available_now": false
      }
    ]
  },
  "unique_5d": {
    "suit": "d",
    "rank": 5,
    "rank_str": "5",
    "current_count": 1,
    "tableau_count": 1,
    "foundation_count": 0,
    "future_stock_count": 1,
    "future_after_SD5_count": 2,
    "hard": true,
    "alternative": false,
    "absent_now": false,
    "tableau": [
      {
        "zone": "CURRENT_TABLEAU",
        "face_up": true,
        "column_0": 8,
        "column_1": 9,
        "up_index": 17,
        "face_up_above": [
          "4H",
          "JH"
        ],
        "cards_above": 2,
        "top": false
      }
    ],
    "foundations": [],
    "next_stock": [
      {
        "zone": "NEXT_STOCK_ROW",
        "column_0": 9,
        "column_1": 10,
        "card": "5D",
        "available_now": false
      }
    ]
  }
}

## 5. Heart search

{
  "classification": "BOUNDED_MISS",
  "reached": false,
  "first_s": null,
  "first_unique": null,
  "best_full_mw": null,
  "unique": 45520,
  "expanded": 128008,
  "generated": 611008,
  "duplicate_skips": 525800,
  "levels": [
    0,
    1,
    2,
    3
  ],
  "elapsed_s": 203.12958450001315,
  "peak_rss_mb": 69.3984375,
  "stop_reason": "frontier empty",
  "sd5_expanded": false,
  "portfolio_n": 0,
  "replay": null,
  "fixture": null,
  "fd": null,
  "empties": null,
  "foundations": null
}

## 6. Diamond search

{
  "classification": "BOUNDED_MISS",
  "reached": false,
  "first_s": null,
  "first_unique": null,
  "best_full_mw": null,
  "unique": 45520,
  "expanded": 113176,
  "generated": 542496,
  "duplicate_skips": 481352,
  "levels": [
    0,
    1,
    2,
    3
  ],
  "elapsed_s": 176.89602240000386,
  "peak_rss_mb": 69.3984375,
  "stop_reason": "frontier empty",
  "sd5_expanded": false,
  "portfolio_n": 0,
  "replay": null,
  "fixture": null,
  "fd": null,
  "empties": null,
  "foundations": null
}

## 7. Cross-target effects

{
  "heart_path_on_diamond": "CROSS_TARGET_NEUTRAL",
  "diamond_path_on_heart": "CROSS_TARGET_NEUTRAL",
  "heart_frees_2d": null,
  "diamond_moves_ah": null
}

## 8. Comparison

{
  "operational_leader": null,
  "cost_leader": null,
  "heart_class": "BOUNDED_MISS",
  "diamond_class": "BOUNDED_MISS",
  "heart_unique": 45520,
  "diamond_unique": 45520,
  "heart_time": 203.12958450001315,
  "diamond_time": 176.89602240000386,
  "equal_envelope": true
}

## 9. Exactly one next recommendation

Neither foundation was removed before SD5 in the equal envelope. Next: attack the nearest remaining mandatory gates (Diamond: AH-on-2D; Heart: remaining unique buried ranks) rather than raising budgets. Do not take SD5 yet.

## Integrity

Verdict NO_SECOND_FOUNDATION_IN_ENVELOPE. SD5 expanded H=False D=False.
Equal envelopes. Current-horizon excludes SD5. No production change.

