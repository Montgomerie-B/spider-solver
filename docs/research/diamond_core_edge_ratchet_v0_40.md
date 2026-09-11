# Spider Solver v0.40 — Diamond Unique-Core Edge Ratchet

## 1. Verdict

`DIAMOND_CORE_PARTIAL_TRACTABLE` — edges reached: ['A', 'B', 'D']

edges reached: ['A', 'B', 'D']. Unique current 2D=1 5D=1. Source-edge satisfaction A/B/C/D={'A': 0, 'B': 0, 'C': 0, 'D': 0}. Reached ['A', 'B', 'D']. Entry=A. Heart H9 cut was +4/77; Diamond-ready was +2/75. SD5 never expanded.

- Branch: `agent/diamond-core-edge-ratchet-v0-40`
- Base SHA: `8cbae9664c436f007164bf072a8fe0874b43e732`

## 2. Sources / current components

{
  "sources": {
    "n": 256,
    "cost_counts": {
      "75": 16,
      "76": 128,
      "77": 112
    },
    "all_replay_ok": true
  },
  "components": {
    "length_hist": {
      "4": 132,
      "5": 116,
      "3": 8
    },
    "sample": [
      {
        "column_1": 3,
        "ranks": [
          "4D",
          "3D"
        ],
        "length": 2,
        "exposed": false,
        "movable": false
      },
      {
        "column_1": 3,
        "ranks": [
          "QD",
          "JD"
        ],
        "length": 2,
        "exposed": false,
        "movable": false
      },
      {
        "column_1": 8,
        "ranks": [
          "7D",
          "6D"
        ],
        "length": 2,
        "exposed": false,
        "movable": false
      },
      {
        "column_1": 9,
        "ranks": [
          "JD",
          "10D",
          "9D",
          "8D"
        ],
        "length": 4,
        "exposed": false,
        "movable": false
      }
    ],
    "source_edge_satisfaction": {
      "A": 0,
      "B": 0,
      "C": 0,
      "D": 0
    },
    "audits": {
      "A": {
        "satisfied": 0,
        "legal_join_now": 0
      },
      "B": {
        "satisfied": 0,
        "legal_join_now": 0
      },
      "C": {
        "satisfied": 0,
        "legal_join_now": 0
      },
      "D": {
        "satisfied": 0,
        "legal_join_now": 0
      }
    },
    "d2": {
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
          "face_up_above": [],
          "cards_above": 0,
          "top": true
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
    "d5": {
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
 

## 3. Edges

{
  "A": {
    "reached": true,
    "first_s": 6.544212800014066,
    "first_unique": 7823,
    "best_full_mw": 84,
    "unique": 94323,
    "expanded": 88194,
    "generated": 562799,
    "duplicate_skips": 467732,
    "levels": [
      0,
      1,
      2,
      3
    ],
    "elapsed_s": 119.9430083000043,
    "peak_rss_mb": 85.640625,
    "stop_reason": "time limit",
    "sd5_expanded": false,
    "already_at_source": 0,
    "n": 104,
    "bands": {
      "84": 8,
      "85": 32,
      "86": 64
    },
    "preview": {
      "SECOND_EDGE_WITHIN_4": 26,
      "LIVE_BEYOND_4": 6
    },
    "second_edge_pct": 81.2,
    "portfolio": "docs/research/diamond_core_edge_A_v0_40.json",
    "foundation_surprise": false,
    "d2_preserved": 0.3076923076923077,
    "d5_preserved": 0.5384615384615384
  },
  "B": {
    "reached": true,
    "first_s": 0.4736597999872174,
    "first_unique": 1327,
    "best_full_mw": 78,
    "unique": 32379,
    "expanded": 91495,
    "generated": 224626,
    "duplicate_skips": 192297,
    "levels": [
      0,
      1,
      2,
      3
    ],
    "elapsed_s": 83.74462680000579,
    "peak_rss_mb": 85.640625,
    "stop_reason": "complete",
    "sd5_expanded": false,
    "already_at_source": 0,
    "n": 128,
    "bands": {
      "78": 40,
      "79": 88
    },
    "preview": {
      "LIVE_BEYOND_4": 32
    },
    "second_edge_pct": 0.0,
    "portfolio": "docs/research/diamond_core_edge_B_v0_40.json",
    "foundation_surprise": false,
    "d2_preserved": 0.0,
    "d5_preserved": 0.1640625
  },
  "C": {
    "reached": false,
    "first_s": null,
    "first_unique": null,
    "best_full_mw": null,
    "unique": 106603,
    "expanded": 100285,
    "generated": 582277,
    "duplicate_skips": 474856,
    "levels": [
      0,
      1,
      2,
      3
    ],
    "elapsed_s": 129.25165049999487,
    "peak_rss_mb": 92.1484375,
    "stop_reason": "time limit",
    "sd5_expanded": false,
    "already_at_source": 0,
    "n": 0,
    "bands": {},
    "preview": {},
    "second_edge_pct": null,
    "portfolio": "docs/research/diamond_core_edge_C_v0_40.json",
    "foundation_surprise": false,
    "d2_preserved": null,
    "d5_preserved": null
  },
  "D": {
    "reached": true,
    "first_s": 9.410666700016009,
    "first_unique": 14858,
    "best_full_mw": 82,
    "unique": 98529,
    "expanded": 100787,
    "generated": 576089,
    "duplicate_skips": 476616,
    "levels": [
      0,
      1,
      2,
      3
    ],
    "elapsed_s": 129.2374831000052,
    "peak_rss_mb": 92.23828125,
    "stop_reason": "time limit",
    "sd5_expanded": false,
    "already_at_source": 0,
    "n": 128,
    "bands": {
      "82": 96,
      "83": 32
    },
    "preview": {
      "LIVE_BEYOND_4": 32
    },
    "second_edge_pct": 0.0,
    "portfolio": "docs/research/diamond_core_edge_D_v0_40.json",
    "foundation_surprise": false,
    "d2_preserved": 0.0,
    "d5_preserved": 0.0
  }
}

## 4. Two-edge / ratchet

{
  "two_edge": {
    "n": 208,
    "pairs": {
      "A+B": 32,
      "MULTI:A+B+D": 40,
      "A+D": 8,
      "B+D": 128
    },
    "best": {
      "A+B": 84,
      "MULTI:A+B+D": 85,
      "A+D": 86,
      "B+D": 82
    },
    "path": "docs/research/diamond_core_two_edge_v0_40.json"
  },
  "ratchet": {
    "entry_edge": "A",
    "evidence": {
      "best_full_mw": 84,
      "second_edge_pct": 81.2,
      "preview": {
        "SECOND_EDGE_WITHIN_4": 26,
        "LIVE_BEYOND_4": 6
      },
      "not_merely_cheapest": true
    }
  }
}

## 5. Cross-target / foundation

{
  "cross_target": {
    "A": {
      "ah_top_c2": false,
      "ah_in_c2": true,
      "h9_up": false,
      "jh_still_down": true,
      "qh_jh": false,
      "heart_release_plausible": true
    },
    "B": {
      "ah_top_c2": false,
      "ah_in_c2": true,
      "h9_up": false,
      "jh_still_down": true,
      "qh_jh": false,
      "heart_release_plausible": true
    },
    "D": {
      "ah_top_c2": false,
      "ah_in_c2": true,
      "h9_up": false,
      "jh_still_down": true,
      "qh_jh": true,
      "heart_release_plausible": true
    }
  },
  "foundation": {
    "reached": false,
    "fixture": null
  }
}

## 6. Exactly one next recommendation

Continue the Diamond ratchet from entry edge A. Carry the two-edge portfolio and prefer boundaries with SECOND_EDGE_WITHIN_4. Do not take SD5. Do not search Hearts.

## Integrity

SD5 never expanded. Edge history not in canonical identity. Production unchanged.

