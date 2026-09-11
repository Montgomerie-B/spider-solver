# Spider Solver v0.39 — Unbiased SD4 Diamond Operational Cut

## 1. Verdict

`DIAMOND_READY_VIA_DIFFERENT_ROUTE` — SD4+single JH move unlocked 74/324; 4H not required

SD4+single JH move unlocked 74/324; 4H not required. Unique Diamond current ranks after SD4=['2', '5'] (before SD4=['5', '9']). After SD4, 2D is top on 324/324; AH-on-2D count=0 (Heart macro was not applied). 5D cover classes after SD4: {'4H|JH': 40, 'JH': 74, '4H|3S|JH': 89, 'KC': 118, '4H|3S|2C|AH|JH': 3}. Enumerated +1-tableau after SD4: 74; +2-tableau: 0. Search incumbent=75 first_t=0.16618830000516027 continuation_best=2. Heart H9 cut was +4 to full 77. SD5 never expanded.

- Branch: `agent/sd4-diamond-operational-cut-v0-39`
- Base SHA: `e7f5021ac1f7bc7b190bbedf174a443afbab6c3a`

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
  "all_replay_ok": true
}

## 3. Diamond material / SD4 structure

{
  "material": {
    "unique_before_sd4": [
      "5",
      "9"
    ],
    "unique_after_sd4": [
      "2",
      "5"
    ],
    "unique_ok": true,
    "sd5_excluded": true
  },
  "sd4_structure": {
    "d2_top_after_sd4": 324,
    "ah_on_2d_after_sd4_only": 0,
    "c9_top_after_sd4": {
      "JH": 324
    },
    "d5_cover_after_sd4": {
      "4H|JH": 40,
      "JH": 74,
      "4H|3S|JH": 89,
      "KC": 118,
      "4H|3S|2C|AH|JH": 3
    },
    "jh_c9_dests": {
      "QH": 324,
      "QC": 324
    },
    "note": "Engine c9 is not uniformly JH/4H/5D. 5D may already be top of c9 or sit under KC at c7."
  }
}

## 4. Macro audit

{
  "one_after_sd4": 74,
  "two_after_sd4": 0,
  "n": 324,
  "one_kinds": {
    "JH->QH": 74,
    "JH->QC": 74
  },
  "two_kinds": {},
  "no_ah_to_2d": true
}

## 5. Exact cut search

{
  "unique": 18154,
  "expanded": 15922,
  "generated": 33796,
  "duplicate_skips": 15958,
  "first_s": 0.16618830000516027,
  "first_unique": 403,
  "first_g": 75,
  "incumbent": 75,
  "max_depth": 6,
  "elapsed_s": 13.083252700016601,
  "peak_rss_mb": 43.6640625,
  "stop_reason": "frontier empty",
  "sd5_expanded": false,
  "ah_on_2d_generated": 3288,
  "witnesses": 256
}

## 6. Ready portfolio

{
  "n": 256,
  "bands": {
    "75": 16,
    "76": 128,
    "77": 112
  },
  "categories": {
    "cont2|qh_jh=True|ah=JS|h9=False": 64,
    "cont2|qh_jh=False|ah=JS|h9=False": 64,
    "cont3|qh_jh=False|ah=AH|h9=False": 13,
    "cont3|qh_jh=True|ah=AH|h9=False": 13,
    "cont3|qh_jh=False|ah=JS|h9=False": 64,
    "cont3|qh_jh=True|ah=JS|h9=False": 38
  },
  "path": "docs/research/sd4_diamond_operational_cut_v0_39_portfolio.json",
  "best": {
    "full_cost": 75,
    "continuation": 2,
    "source_g": 73,
    "ah_c2": "JS",
    "h9_up": false,
    "jh_still_down": true,
    "qh_jh": true,
    "stock_rows": 1,
    "fd": 7,
    "fixture": "solutions/4925153_v0_39_diamond_ready_best.moves.txt",
    "full_replay_ok": true
  }
}

## 7. Continuation probe

{
  "LIVE_BEYOND_8": 32
}

## 8. Cross-target / comparison

{
  "cross_target": {
    "ah_still_c2": false,
    "h9_still_down": true,
    "original_jh_still_down": true,
    "qh_jh_incidental": true,
    "heart_sd4_release_still_possible": false
  },
  "comparison": {
    "heart_h9_cut_continuation": 4,
    "heart_h9_best_full_mw": 77,
    "diamond_ready_continuation": 2,
    "diamond_ready_best_full_mw": 75,
    "diamond_cheaper_operational_cut": true
  }
}

## 9. Exactly one next recommendation

Diamond operational access is available from the unbiased pre-SD4 frontier without parking AH on 2D. Next: compare this Diamond-ready portfolio against the v0.37 Heart H9 cut for a fair post-SD4 foundation-order decision. Do not take SD5 yet. Do not inspect the human route.

## Integrity

No Heart AH->2D prescription. SD5 never expanded. Production unchanged.

