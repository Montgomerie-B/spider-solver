# Spider Solver v0.55 — Whole-Suit Component Assembly Audit

## 1. Verdict

`PREP_CREATES_SUPERIOR_COMPONENT_TOPOLOGY` — PREP creates a whole-suit assembly class absent from DEAL_NOW

PREP creates a whole-suit assembly class absent from DEAL_NOW. n=103513 deal_cover=4 prep_cover=4 pareto=20375 F2=0. v0.53 missed a meet-in-the-middle preparation advantage. PREP builds better whole-suit components.

- Branch: `agent/sd5-whole-suit-component-audit-v0-55`
- Base SHA: `0b01ef8819eea13bea34d65bdeba584a12a41ab1`
- Elapsed: 684.0967248000088s

## 2. Universe

- Post-SD5: **103513** / expected 103513 (match=True)
- DEAL_NOW / PREP: **720** / **102793**
- Replay: True

## 3. DEAL_NOW component topology

```json
{
  "n": 720,
  "min_cover": {
    "6": 680,
    "5": 28,
    "4": 12
  },
  "min_visible_cover": {
    "6": 688,
    "5": 20,
    "4": 12
  },
  "min_fd_cards": {
    "0": 712,
    "1": 8
  },
  "join_lb": {
    "5": 680,
    "4": 28,
    "3": 12
  },
  "longest": {
    "7": 680,
    "4": 12,
    "5": 24,
    "3": 4
  },
  "start_edges": {
    "0": 720
  },
  "cond_longest": {
    "7": 680,
    "4": 12,
    "5": 24,
    "3": 4
  },
  "k_len": {
    "7": 680,
    "3": 28,
    "2": 12
  },
  "a_len": {
    "2": 680,
    "4": 8,
    "5": 24,
    "1": 4,
    "3": 4
  },
  "gap": {
    "4": 680,
    "6": 12,
    "5": 16,
    "7": 8,
    "9": 4
  },
  "f2": 0,
  "best_cover": 4,
  "best_fd": 0,
  "best_cond_len": 7,
  "best_edges": 0,
  "best_gap": 4,
  "max_k": 7,
  "max_a": 5,
  "by_suit": {
    "s": {
      "n": 720,
      "min_cover": {
        "13": 560,
        "11": 56,
        "10": 72,
        "9": 32
      },
      "min_visible_cover": {
        "13": 560,
        "11": 56,
        "10": 72,
        "9": 32
      },
      "min_fd_cards": {
        "0": 720
      },
      "join_lb": {
        "12": 560,
        "10": 56,
        "9": 72,
        "8": 32
      },
      "longest": {
        "1": 560,
        "2": 56,
        "3": 104
      },
      "start_edges": {
        "0": 720
      },
      "cond_longest": {
        "1": 560,
        "2": 56,
        "3": 104
      },
      "k_len": {
        "1": 640,
        "2": 80
      },
      "a_len": {
        "1": 656,
        "3": 64
      },
      "gap": {
        "11": 576,
        "10": 80,
        "9": 64
      },
      "f2": 0,
      "best_cover": 9,
      "best_fd": 0,
      "best_cond_len": 3,
      "best_edges": 0,
      "best_gap": 9,
      "max_k": 2,
      "max_a": 3
    },
    "h": {
      "n": 720,
      "min_cover": {
        "10": 328,
        "9": 360,
        "8": 32
      },
      "min_visible_cover": {
        "10": 328,
        "9": 360,
        "8": 32
      },
      "min_fd_cards": {
        "0": 720
      },
      "join_lb": {
        "9": 328,
        "8": 360,
        "7": 32
      },
      "longest": {
        "3": 720
      },
      "start_edges": {
        "1": 720
      },
      "cond_longest": {
        "3": 720
      },
      "k_len": {
        "1": 720
      },
      "a_len": {
        "1": 720
      },
      "gap": {
        "11": 720
      },
      "f2": 0,
      "best_cover": 8,
      "best_fd": 0,
      "best_cond_len": 3,
      "best_edges": 1,
      "best_gap": 11,
      "max_k": 1,
      "max_a": 1
    },
    "d": {
      "n": 720,
      "min_cover": {
        "8": 536,
        "9": 8,
        "7": 108,
        "6": 28,
        "5": 28,
        "4": 12
      },
      "min_visible_cover": {
        "10": 252,
        "8": 292,
        "9": 40,
        "7": 80,
        "5": 20,
        "6": 24,
        "4": 12
      },
      "min_fd_cards": {
        "1": 312,
        "0": 408
      },
      "join_lb": {
        "7": 536,
        "8": 8,
        "6": 108,
        "5": 28,
        "4": 28,
        "3": 12
      },
      "longest": {
        "4": 364,
        "3": 332,
        "5": 24
      },
      "start_edges": {
        "0": 720
      },
      "cond_longest": {
        "4": 364,
        "3": 332,
        "5": 24
      },
      "k_len": {
        "1": 640,
        "3": 56,
        "2": 24
      },
      "a_len": {
        "1": 520,
        "2": 128,
        "4": 16,
        "5": 24,
        "3": 32
      },
      "gap": {
        "11": 512,
        "10": 128,
        "6": 16,
        "5": 16,
        "7": 32,
        "9": 8,
        "8": 8
      },
      "f2": 0,
      "best_cover": 4,
      "best_fd": 0,
      "best_cond_len": 5,
      "best_edges": 0,
      "best_gap": 5,
      "max_k": 3,
      "max_a": 5
    },
    "c": {
      "n": 720,
      "min_cover": {
        "6": 712,
        "7": 8
      },
      "min_visible_cover": {
        "6": 712,
        "7": 8
      },
      "min_fd_cards": {
        "0": 720
      },
      "join_lb": {
        "5": 712,
        "6": 8
      },
      "longest": {
        "7": 720
      },
      "start_edges": {
        "0": 720
      },
      "cond_longest": {
        "7": 720
      },
      "k_len": {
        "7": 720
      },
      "a_len": {
        "2": 712,
        "1": 8
      },
      "gap": {
        "4": 712,
        "5": 8
      },
      "f2": 0,
      "best_cover": 6,
      "best_fd": 0,
      "best_cond_len": 7,
      "best_edges": 0,
      "best_gap": 4,
      "max_k": 7,
      "max_a": 2
    }
  }
}
```

## 4. PREP component topology

```json
{
  "n": 102793,
  "min_cover": {
    "5": 24752,
    "6": 75866,
    "4": 1134,
    "7": 1041
  },
  "min_visible_cover": {
    "5": 24387,
    "6": 75791,
    "4": 1134,
    "7": 1481
  },
  "min_fd_cards": {
    "0": 101988,
    "1": 805
  },
  "join_lb": {
    "4": 24752,
    "5": 75866,
    "3": 1134,
    "6": 1041
  },
  "longest": {
    "7": 95291,
    "4": 3992,
    "5": 2268,
    "3": 1242
  },
  "start_edges": {
    "0": 102793
  },
  "cond_longest": {
    "7": 95291,
    "4": 3992,
    "5": 2268,
    "3": 1242
  },
  "k_len": {
    "7": 95291,
    "3": 3026,
    "2": 4476
  },
  "a_len": {
    "2": 94250,
    "4": 1105,
    "5": 2268,
    "1": 3299,
    "3": 1871
  },
  "gap": {
    "4": 94250,
    "6": 1908,
    "7": 1579,
    "5": 1771,
    "9": 1082,
    "10": 1176,
    "8": 1027
  },
  "f2": 0,
  "best_cover": 4,
  "best_fd": 0,
  "best_cond_len": 7,
  "best_edges": 0,
  "best_gap": 4,
  "max_k": 7,
  "max_a": 5,
  "by_suit": {
    "s": {
      "n": 102793,
      "min_cover": {
        "13": 48375,
        "12": 11922,
        "11": 20204,
        "10": 18964,
        "9": 3096,
        "8": 232
      },
      "min_visible_cover": {
        "13": 48375,
        "12": 11922,
        "11": 20204,
        "10": 18964,
        "9": 3096,
        "8": 232
      },
      "min_fd_cards": {
        "0": 102793
      },
      "join_lb": {
        "12": 48375,
        "11": 11922,
        "10": 20204,
        "9": 18964,
        "8": 3096,
        "7": 232
      },
      "longest": {
        "1": 48375,
        "2": 32562,
        "3": 19930,
        "4": 1926
      },
      "start_edges": {
        "0": 102793
      },
      "cond_longest": {
        "1": 48375,
        "2": 32562,
        "3": 19930,
        "4": 1926
      },
      "k_len": {
        "1": 82849,
        "2": 19944
      },
      "a_len": {
        "1": 99337,
        "3": 3456
      },
      "gap": {
        "11": 79393,
        "10": 19944,
        "9": 3456
      },
      "f2": 0,
      "best_cover": 8,
      "best_fd": 0,
      "best_cond_len": 4,
      "best_edges": 0,
      "best_gap": 9,
      "max_k": 2,
      "max_a": 3
    },
    "h": {
      "n": 102793,
      "min_cover": {
        "10": 39671,
        "9": 56258,
        "8": 6400,
        "7": 464
      },
      "min_visible_cover": {
        "10": 39671,
        "9": 56258,
        "8": 6400,
        "7": 464
      },
      "min_fd_cards": {
        "0": 102793
      },
      "join_lb": {
        "9": 39671,
        "8": 56258,
        "7": 6400,
        "6": 464
      },
      "longest": {
        "3": 102329,
        "4": 464
      },
      "start_edges": {
        "1": 101355,
        "2": 574,
        "0": 864
      },
      "cond_longest": {
        "4": 14853,
        "3": 82048,
        "6": 3746,
        "5": 2146
      },
      "k_len": {
        "1": 102181,
        "2": 312,
        "3": 284,
        "4": 16
      },
      "a_len": {
        "1": 102793
      },
      "gap": {
        "11": 102181,
        "10": 312,
        "9": 284,
        "8": 16
      },
      "f2": 0,
      "best_cover": 7,
      "best_fd": 0,
      "best_cond_len": 6,
      "best_edges": 2,
      "best_gap": 8,
      "max_k": 4,
      "max_a": 1
    },
    "d": {
      "n": 102793,
      "min_cover": {
        "8": 60158,
        "9": 9303,
        "7": 18529,
        "6": 8849,
        "5": 4820,
        "4": 1134
      },
      "min_visible_cover": {
        "10": 22911,
        "8": 38111,
        "9": 15903,
        "7": 12476,
        "6": 7803,
        "5": 4455,
        "4": 1134
      },
      "min_fd_cards": {
        "1": 33999,
        "0": 68794
      },
      "join_lb": {
        "7": 60158,
        "8": 9303,
        "6": 18529,
        "5": 8849,
        "4": 4820,
        "3": 1134
      },
      "longest": {
        "4": 53075,
        "3": 47426,
        "2": 24,
        "5": 2268
      },
      "start_edges": {
        "0": 102793
      },
      "cond_longest": {
        "4": 53075,
        "3": 47426,
        "2": 24,
        "5": 2268
      },
      "k_len": {
        "1": 80811,
        "3": 9098,
        "2": 12884
      },
      "a_len": {
        "1": 74881,
        "2": 14568,
        "4": 3080,
        "5": 2268,
        "3": 7996
      },
      "gap": {
        "11": 66619,
        "10": 18382,
        "9": 4424,
        "8": 4784,
        "6": 2574,
        "7": 5280,
        "5": 730
      },
      "f2": 0,
      "best_cover": 4,
      "best_fd": 0,
      "best_cond_len": 5,
      "best_edges": 0,
      "best_gap": 5,
      "max_k": 3,
      "max_a": 5
    },
    "c": {
      "n": 102793,
      "min_cover": {
        "5": 20375,
        "6": 77512,
        "7": 4906
      },
      "min_visible_cover": {
        "5": 20375,
        "6": 77512,
        "7": 4906
      },
      "min_fd_cards": {
        "0": 102793
      },
      "join_lb": {
        "4": 20375,
        "5": 77512,
        "6": 4906
      },
      "longest": {
        "7": 102793
      },
  
```

## 5. Direct condensation

```json
{
  "deal_now_best_len": 7,
  "prep_best_len": 7,
  "deal_now_f2": 0,
  "prep_f2": 0
}
```

## 6. PREP vs DEAL_NOW

- New classes: `['c:lower_min_component_cover', 'h:longer_direct_condensation', 'h:lower_min_component_cover', 'h:more_direct_merge_edges', 'h:smaller_ka_gap', 's:longer_direct_condensation', 's:lower_min_component_cover']`
- Pareto-nondominated PREP: **20375**
- Cheapest Pareto g: 77
- Suits: `{'c': 20375}`

```json
[
  {
    "g": 77,
    "timing": "PREP_THEN_DEAL",
    "prep_depth": 1,
    "prep_cost": 1,
    "lineages": [
      "diamond_ready"
    ],
    "origin": 0,
    "ordered_digest": "53504b310101000002063a2c360d32112913030315191b110b1a01103b27061534233231242302212c2b0a1c22000a1413121d07161d0c223300052d2421181900061a39283c1b3701041836033d17000b1231272635042a0514380100143d3c3b3a39383726081716351c2b2a292825343300032d09250d0d0c0b0a090807060504030201",
    "symmetry_digest": "535053310101000000032d092500052d2421181900061a39283c1b37000a1413121d07161d0c2233000b1231272635042a0514380100143d3c3b3a39383726081716351c2b2a292825343301041836033d1701103b27061534233231242302212c2b0a1c2202063a2c360d32112913030315191b110b1a0d0d0c0b0a090807060504030201",
    "best_suit": "c",
    "min_cover": 5,
    "min_visible_cover": 5,
    "min_fd_cards": 0,
    "join_lb": 4,
    "visible_n": 16,
    "start_edges": 0,
    "cond_longest": 7,
    "cond_min_n": 16,
    "longest": 7,
    "k_len": 7,
    "a_len": 2,
    "gap": 4,
    "joinable": false,
    "f2": false,
    "f2_suit": null,
    "full_actions": [
      [
        2,
        5,
        1
      ],
      [
        5,
        7,
        2
      ],
      [
        0,
        5,
        1
      ],
      [
        5,
        7,
        2
      ],
      [
        7,
        3,
        5
      ],
      [
        2,
        1,
        1
      ],
      [
        2,
        6,
        1
      ],
      [
        8,
        2,
        1
      ],
      [
        8,
        2,
        1
      ],
      [
        9,
        2,
        1
      ],
      [
        2,
        9,
        4
      ],
      [
        7,
        0,
        1
      ],
      [
        8,
        1,
        1
      ],
      [
        8,
        2,
        1
      ],
      [
        8,
        0,
        1
      ],
      [
        5,
        0,
        1
      ],
      [
        9,
        5,
        5
      ],
      [
        5,
        4,
        6
      ],
      [
        9,
        2,
        1
      ],
      [
        4,
        8,
        7
      ],
      [
        4,
        2,
        1
      ],
      [
        4,
        2,
        1
      ],
      [
        5,
        4,
        1
      ],
      [
        4,
        5,
        2
      ],
      [
        4,
        8,
        1
      ],
      [
        7,
        4,
        1
      ],
      [
        3,
        6,
        5
      ],
      [
        2,
        7,
        1
      ],
      [
        9,
        2,
        1
      ],
      [
        9,
        4,
        1
      ],
      [
        3,
        9,
        1
      ],
      [
        3,
        9,
        1
      ],
      [
        3,
        1,
        1
      ],
      [
        4,
        2,
        2
      ],
      [
        3,
        4,
        1
      ],
      [
        3,
        7,
        1
      ],
      [
        3,
        0,
        1
      ],
      [
        7,
        3,
        3
      ],
      [
        0,
        7,
        1
      ],
  
```

## 7. Foundation 2

- Local F2: **False** n=0 cheapest=None suit=None
- Fixture: None

## 8. Strategic interpretation

v0.53 missed a meet-in-the-middle preparation advantage. PREP builds better whole-suit components.

No UCS. No descendant search. No pre-SD4. No weighted score. Production unchanged.

## 9. Files

```json
{
  "report": "docs/research/sd5_whole_suit_component_audit_v0_55.md",
  "result": "docs/research/sd5_whole_suit_component_audit_v0_55.json",
  "atlas": "docs/research/sd5_component_topology_atlas_v0_55.json",
  "portfolio": "docs/research/sd5_component_aware_portfolio_v0_55.json",
  "foundation2": null,
  "fixture": null
}
```

## 10. Exactly one next recommendation

Run one compact component-aware Foundation-2 search from the new portfolio. Do not resume Ace-tail excavation or the 103k UCS.

