# Spider Solver v0.53 — SD5 Resource-Runway Replan

## 1. Verdict

`JUST_IN_TIME_PREP_INSUFFICIENT` — depth<=4 / MW<=4 prep does not create a self-propelling post-Deal runway

depth<=4 / MW<=4 prep does not create a self-propelling post-Deal runway. sources=720 prep=103513 post=103513 deal_now_best=5 prep_best=5 improvements=0 F2=0. Just-in-time depth<=4 / MW<=4 preparation does not create a self-propelling foundation runway. Useful SD5 receiving structure must be built earlier than this window.

- Branch: `agent/sd5-resource-runway-replan-v0-53`
- Base SHA: `b1c93bd193221c5246e58d20f45244c89493c532`
- Elapsed: 589.3819258000003s

## 2. Reconstruction

- Pre-SD5 sources: **720** / expected 720 (replay_ok=True)
- Prep candidates: **103513** / expected 103513 (matches=True)
- Prep timing: `{'DEAL_NOW': 720, 'PREP_THEN_DEAL': 102793}` depth `{0: 720, 1: 3275, 2: 10342, 3: 26850, 4: 62326}`
- Post-SD5 exact: **103513** symmetry `103513` reduction `1.0`
- Post-SD5 timing: `{'DEAL_NOW': 720, 'PREP_THEN_DEAL': 102793}`
- SD5 row: `['3H', '10H', '2D', '3C', '9H', '7C', '7H', 'AS', '3C', '5D']` match=True

## 3. DEAL_NOW runway

```json
{
  "n": 720,
  "f2": 0,
  "runway_ge_6": 0,
  "runway_ge_5": 24,
  "runway_ge_4": 40,
  "runway_ge_3": 72,
  "next_ready": 0,
  "next_one_move": 16,
  "next_shallow": 672,
  "next_medium": 8,
  "next_deep": 24,
  "next_face_down": 0,
  "empty_in_one": 0,
  "fd_reveal_in_one": 0,
  "improved_support": 24,
  "best_direct": 5,
  "best_support": 5,
  "access": {
    "NEXT_SHALLOW": 672,
    "NEXT_DEEP": 24,
    "NEXT_ONE_MOVE": 16,
    "NEXT_MEDIUM": 8
  },
  "best_suit_counts": {
    "s": 0,
    "h": 0,
    "d": 72,
    "c": 648
  },
  "suit_next_ready": {
    "s": 0,
    "h": 0,
    "d": 0,
    "c": 0
  },
  "direct_by_suit": {
    "s": 3,
    "h": 1,
    "d": 5,
    "c": 2
  }
}
```

## 4. PREP_THEN_DEAL runway

```json
{
  "n": 102793,
  "f2": 0,
  "runway_ge_6": 0,
  "runway_ge_5": 2268,
  "runway_ge_4": 5348,
  "runway_ge_3": 13618,
  "next_ready": 0,
  "next_one_move": 3842,
  "next_shallow": 91607,
  "next_medium": 4802,
  "next_deep": 2542,
  "next_face_down": 0,
  "empty_in_one": 352,
  "fd_reveal_in_one": 0,
  "improved_support": 825,
  "best_direct": 5,
  "best_support": 5,
  "access": {
    "NEXT_SHALLOW": 91607,
    "NEXT_ONE_MOVE": 3842,
    "NEXT_DEEP": 2542,
    "NEXT_MEDIUM": 4802
  },
  "best_suit_counts": {
    "s": 336,
    "h": 0,
    "d": 14806,
    "c": 87651
  },
  "suit_next_ready": {
    "s": 0,
    "h": 0,
    "d": 0,
    "c": 0
  },
  "direct_by_suit": {
    "s": 3,
    "h": 1,
    "d": 5,
    "c": 2
  },
  "by_depth": {
    "1": {
      "n": 3275,
      "best_direct": 5,
      "next_ready": 0,
      "next_one_move": 98
    },
    "2": {
      "n": 10342,
      "best_direct": 5,
      "next_ready": 0,
      "next_one_move": 360
    },
    "3": {
      "n": 26850,
      "best_direct": 5,
      "next_ready": 0,
      "next_one_move": 1032
    },
    "4": {
      "n": 62326,
      "best_direct": 5,
      "next_ready": 0,
      "next_one_move": 2352
    }
  }
}
```

## 5. Direct comparison

- Prep classes absent from DEAL_NOW: `[]`
- Pareto improvements: **0**
- Cheapest improvement g: None
- Improvement suit distribution: `{}`

```json
[]
```

## 6. One-support probe

```json
{
  "qualifying": 102569,
  "examined": 3892,
  "children": 23601,
  "cap": 250000,
  "complete": false,
  "improved": 849,
  "best_examples": [
    {
      "g": 85,
      "timing": "DEAL_NOW",
      "prep_depth": 0,
      "prep_cost": 0,
      "lineages": [
        "diamond_multi_edge"
      ],
      "origin": 640,
      "ordered_digest": "53504b310101000002073a2c360d3211293813030315191b110b1a010c3b27061534233231242322212200091413121d07161d0c3300062d242118341900051a39283c37010718363d1c1b0a0917000c1231272635042a051403020100133d3c3b3a39383726081716351c2b2a2928253300042d2c2b250d0d0c0b0a090807060504030201",
      "symmetry_digest": "535053310101000000042d2c2b2500051a39283c3700062d242118341900091413121d07161d0c33000c1231272635042a051403020100133d3c3b3a39383726081716351c2b2a29282533010718363d1c1b0a0917010c3b27061534233231242322212202073a2c360d3211293813030315191b110b1a0d0d0c0b0a090807060504030201",
      "best_suit": "d",
      "direct_len": 4,
      "support_len": 5,
      "joins": 0,
      "access": "NEXT_SHALLOW",
      "min_depth": 0,
      "f2": false,
      "f2_suit": null,
      "empty_now": false,
      "empty_in_one": false,
      "fd_reveal_in_one": false,
      "improved_support": true,
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
  
```

## 7. Foundation 2

- Local F2: **False** n=0 cheapest=None suit=None
- Fixture: None

## 8. Portfolio

```json
{
  "n": 512,
  "categories": {
    "B_LONGEST": 40,
    "D_ONE_MOVE": 32,
    "E_SHALLOW": 48,
    "F_EMPTY": 24,
    "H_CHEAP_SUIT": 24,
    "I_DEAL_NOW": 48,
    "J_FILL": 296
  },
  "suits": {
    "d": 268,
    "c": 236,
    "s": 8
  },
  "timing": {
    "DEAL_NOW": 268,
    "PREP_THEN_DEAL": 244
  },
  "mw_bands": {
    "86": 78,
    "87": 182,
    "76": 16,
    "77": 144,
    "85": 8,
    "80": 16,
    "81": 8,
    "89": 8,
    "78": 52
  }
}
```

## 9. Strategic interpretation

Just-in-time depth<=4 / MW<=4 preparation does not create a self-propelling foundation runway. Useful SD5 receiving structure must be built earlier than this window.

- Just-in-time prep helping: **False**

No UCS over 103k. No suit excavation. No Foundation 3. Production unchanged.

## 10. Files

```json
{
  "report": "docs/research/sd5_resource_runway_replan_v0_53.md",
  "result": "docs/research/sd5_resource_runway_replan_v0_53.json",
  "atlas": "docs/research/sd5_resource_runway_atlas_v0_53.json",
  "portfolio": "docs/research/sd5_resource_aware_portfolio_v0_53.json",
  "foundation2": null,
  "fixture": null
}
```

## 11. Exactly one next recommendation

Just-in-time depth<=4 / MW<=4 SD5 prep does not create a self-propelling runway. Useful receiving structure must be established earlier than this window. Do not widen prep depth in a follow-on of this experiment; do not resume suit excavation.

