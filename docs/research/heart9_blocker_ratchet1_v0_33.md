# Spider Solver v0.33 — Gate 1 Ratchet: First 8D Blocker Flip

## 1. Verdict

`GATE1_8D_REACHED_AND_COST_PROVED` — Gate 1 reached and Pass B proved cheapest cost

Gate 1 is a proof-safe cut: the unique 9H sits under JH, AH, then top face-down 8D. Directed search found the 3->2 flip (newly exposed 8D) in 0.17s / 72 unique states at local g=8 (full path/MW 70). Pass B UCS found no cheaper cut and exhausted the g<8 frontier, so C=8 is proved minimum from these four sources. Portfolio 40 states in bands 16/8/16 at C/C+1/C+2, both before-SD3 and prepared-SD3 timings. Versus v0.32 (198k unique / 900s / no H9), the next-gate decomposition condensed the problem by orders of magnitude. SD4 was never expanded. Heart 1 was not searched.

- Branch: `agent/heart9-blocker-ratchet1-v0-33`
- Base SHA: `42a832684b60a303e71fbaf6dc456a75c8fd5322`

## 2. Proof

{
  "chain": {
    "chain_bottom_to_top": [
      "JH",
      "AH",
      "8D"
    ],
    "column_0": 1,
    "column_1": 2,
    "flip_sequence": [
      "8D",
      "AH",
      "JH",
      "9H"
    ],
    "gate1_proof": "Every path that later exposes 9H must first flip the current top face-down card above it. That card is 8D, which is the 3->2 blockers_above transition.",
    "h9": {
      "column_0": 1,
      "column_1": 2,
      "down_index": 1,
      "face_down_above": [
        "JH",
        "AH",
        "8D"
      ],
      "face_down_blockers_above": 3,
      "face_down_len": 5,
      "face_up": false,
      "face_up_above": [
        "KD",
        "QS",
        "JD",
        "10H",
        "9D",
        "8D"
      ],
      "face_up_count": 6,
      "in_sd3": false,
      "zone": "down"
    },
    "top_face_down": "8D",
    "valid": true
  },
  "flip_cost": {
    "lb_to_gate1": 1,
    "lb_to_h9": 3,
    "rationale": "Corrected MW zero-cost relocate applies only when the source column becomes empty and has no remaining face-down cards. The 9H column still has face-down cards under every Gate-1 uncover, so that uncover costs >= 1. One action flips at most one face-down card.",
    "uncover_costs_from_target_column": [],
    "valid": true,
    "zero_cost_requires_empty_column": true
  }
}

## 3. Pass A

- levels=[0, 1, 2, 3] first_t=0.17414479999570176 first_unique=72 first_g=8 first_depth=8
- unique=146006 expanded=183345 generated=513334 dups=350471 reopens=16861
- bands={'10': 16, '8': 16, '9': 8} timings=['GATE1_AFTER_PREPARED_SD3', 'GATE1_BEFORE_SD3'] stop=time limit elapsed_s=600.000590599986 rss=110.6171875

## 4. Pass B

{
  "cheaper": false,
  "elapsed_s": 641.5155687000079,
  "expanded": 284574,
  "generated": 700690,
  "incumbent": 8,
  "peak_rss_mb": 162.4921875,
  "proved": true,
  "run": true,
  "sd4_expanded": false,
  "stop_reason": "frontier empty",
  "unique": 284574,
  "witnesses": 0
}

## 5. Boundary

{
  "actions": [
    [
      8,
      5,
      1
    ],
    [
      1,
      7,
      2
    ],
    [
      1,
      8,
      1
    ],
    [
      5,
      1,
      1
    ],
    [
      1,
      5,
      2
    ],
    [
      1,
      0,
      1
    ],
    [
      5,
      0,
      2
    ],
    [
      1,
      5,
      1
    ]
  ],
  "deals": 2,
  "depth": 8,
  "empties": [],
  "face_down_col": [
    "5H",
    "9H",
    "JH",
    "AH"
  ],
  "face_up_col": [
    "8D"
  ],
  "fd": 8,
  "fd_blockers": 2,
  "fixture": "solutions/4925153_v0_33_gate1_8d_best.moves.txt",
  "foundations": 1,
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
      3,
      1
    ],
    [
      "deal"
    ],
    [
      5,
      7,
      1
    ],
    [
      0,
      5,
      1
    ],
    [
      9,
      7,
      1
    ],
    [
      9,
      8,
      2
    ],
    [
      0,
      9,
      1
    ],
    [
      0,
      2,
      1
    ],
    [
      0,
      7,
      1
    ],
    [
      0,
      8,
      1
    ],
    [
      0,
      6,
      

## 6. Condensation vs v0.32

{
  "condensed": true,
  "v32_expanded": 228681,
  "v32_h9": false,
  "v32_seconds": 900,
  "v32_unique": 198303,
  "v33_expanded": 183345,
  "v33_first_s": 0.17414479999570176,
  "v33_first_unique": 72,
  "v33_gate1": true,
  "v33_unique": 146006
}

## 7. Exactly one next recommendation

Carry the Gate-1 portfolio (cost bands C/C+1/C+2) into Gate 2: first exposure of AH. Do not jump to 9H or Heart 1, and do not take SD4.

## Integrity

Verdict GATE1_8D_REACHED_AND_COST_PROVED. SD4 expanded=False.
Gate 1 terminal. No H9/Heart search. No production change.

