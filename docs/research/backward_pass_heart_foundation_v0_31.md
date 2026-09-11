# Spider Solver v0.31 — Backward-Pass Heart-1 Foundation Planner

## 1. Verdict

`HEART_TARGET_SEARCH_STATE_EXPLOSION` — limits bound (time limit) before Heart 1

The v0.30 horizon and four Spade-1 sources reconstructed. Heart 1 is the only extra foundation materially available before SD4. The backward map finds six unique-copy access obligations (Q,J,10,9,7,3) and seven duplicate-rank alternatives; SD3 currently covers exposed 6H and AH if dealt immediately. Admissible MW lower bound is 0. Cost-aware search reached widening levels 0-3 (2.27M unique, max depth 18, 1.4 GiB) without a Heart foundation. Frontiers were not exhausted, so this is a bounded non-result, not a proof Heart 1 is unreachable before SD4. SD4 was never expanded.

- Branch: `agent/backward-pass-heart-foundation-v0-31`
- Base SHA: `dc3a44f4974acd25b9dd539864d13e5bf4fe28ac`
- Target: first Heart foundation. SD4 never expanded.

## 2. Horizon / target

- Remaining rows: SD3=['2C', '10S', 'QD', 'KH', '8H', '9C', '3S', '5S', '5D', '4H'] SD4=['9D', 'JS', 'QH', '2D', '4C', 'QC', 'KC', '8C', 'JH', '9S'] SD5=['3H', '10H', '2D', '3C', '9H', '7C', '7H', 'AS', '3C', '5D']
- Unlocks: {'SD3': [], 'SD4': ['first Diamonds'], 'SD5': ['second Spades', 'second Hearts', 'second Diamonds', 'first Clubs', 'second Clubs']}
- Target: first Hearts — After Spade 1, Heart 1 is the only additional foundation materially available before SD4. Diamond 1 unlocks at SD4; Clubs and all second foundations unlock at SD5.
- Opening horizon ok: True SD5=['3H', '10H', '2D', '3C', '9H', '7C', '7H', 'AS', '3C', '5D']

## 3. Backward pass

- hard obligations: 6 alternative: 7
- duplicate ranks: 7
- hard: [
  {
    "column_1": 9,
    "kind": "expose_unique_copy",
    "occurrence": "T15",
    "rank": "Q",
    "text": "Heart Q unique tableau copy T15 must be exposed (zone=up, depth=2)"
  },
  {
    "column_1": 2,
    "kind": "expose_unique_copy",
    "occurrence": "T2",
    "rank": "J",
    "text": "Heart J unique tableau copy T2 must be exposed (zone=down, depth=8)"
  },
  {
    "column_1": 2,
    "kind": "expose_unique_copy",
    "occurrence": "T4",
    "rank": "10",
    "text": "Heart 10 unique tableau copy T4 must be exposed (zone=up, depth=2)"
  },
  {
    "column_1": 2,
    "kind": "expose_unique_copy",
    "occurrence": "T1",
    "rank": "9",
    "text": "Heart 9 unique tableau copy T1 must be exposed (zone=down, depth=9)"
  },
  {
    "column_1": 9,
    "kind": "expose_unique_copy",
    "occurrence": "T13",
    "rank": "7",
    "text": "Heart 7 unique tableau copy T13 must be exposed (zone=up, depth=5)"
  },
  {
    "column_1": 4,
    "kind": "expose_unique_copy",
    "occurrence": "T7",
    "rank": "3",
    "text": "Heart 3 unique tableau copy T7 must be exposed (zone=up, depth=5)"
  }
]
- alternative copies: [
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T9",
      "SD3C4"
    ],
    "rank": "K",
    "text": "Heart K can come from T9 or SD3C4"
  },
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T11",
      "SD3C5"
    ],
    "rank": "8",
    "text": "Heart 8 can come from T11 or SD3C5"
  },
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T10",
      "T14"
    ],
    "rank": "6",
    "text": "Heart 6 can come from T10 or T14"
  },
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T0",
      "T5"
    ],
    "rank": "5",
    "text": "Heart 5 can come from T0 or T5"
  },
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T6",
      "SD3C10"
    ],
    "rank": "4",
    "text": "Heart 4 can come from T6 or SD3C10"
  },
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T8",
      "T12"
    ],
    "rank": "2",
    "text": "Heart 2 can come from T8 or T12"
  },
  {
    "kind": "choose_copy",
    "occurrence_ids": [
      "T3",
      "T16"
    ],
    "rank": "A",
    "text": "Heart A can come from T3 or T16"
  }
]
- components: [
  {
    "cards_above": [
      "9D",
      "8D"
    ],
    "column_0": 1,
    "column_1": 2,
    "highest": 10,
    "highest_label": "10",
    "is_exposed_suffix": false,
    "length": 1,
    "lowest": 10,
    "lowest_label": "10",
    "movable_as_block": false,
    "naturally_joined_ranks": [
      "10"
    ]
  },
  {
    "cards_above": [
      "4C",
      "3D",
      "2C",
      "AC",
      "4D",
      "3D",
      "2S",
      "AD"
    ],
    "column_0": 2,
    "column_1": 3,
    "highest": 5,
    "highest_label": "5",
    "is_exposed_suffix": false,
    "length": 1,
    "lowest": 5,
    "lowest_label": "5",
    "movable_as_block": false,
    "naturally_joined_ranks": [
      "5"
    ]
  },
  {
    "cards_above": [
      "AC",
      "KH",
      "7S",
      "6H"
    ],
    "column_0": 3,
    "column_1": 4,
    "highest": 4,
    "highest_label": "4",
    "is_exposed_suffix": false,
    "length": 3,
    "lowest": 2,
    "lowest_label": "2",
    "movable_as_block": false,
    "naturally_joined_ranks": [
      "4",
      "3",
      "2"
    ]
  },
  {
    "cards_above": [
      "7S",
      "6H"
    ],
    "column_0": 3,
    "column_1": 4,
    "highest": 13,
    "highest_label": "K",
    "is_exposed_suffix": false,
    "length": 1,
    "lowest": 13,
    "lowest_label": "K",
    "movable_as_block": false,
    "naturally_joined_ranks": [
      "K"
    ]
  },
  {
    "cards_above": [],
    "column_0": 3,
    "column_1": 4,
    "highest": 6,
    "highest_label": "6",
    "is_exposed_suffix": true,
    "length": 1,
    "lowest": 6,
    "lowest_label": "6",
    "movable_as_block": true,
    "naturally_joined_ranks": [
      "6"
    ]
  },
  {
    "cards_above": [
      "7D",
      "6D",
      "5C",
      "4S",
      "10D"
    ],
    "column_0": 7,
    "column_1": 8,
    "highest": 2,
    "highest_label": "2",
    "is_exposed_suffix": false,
    "length": 1,
    "lowest": 2,
    "lowest_label": "2",
    "movable_as_block": false,
    "naturally_joined_ranks": [
      "2"
    ]
- SD3 reception: {
  "by_column": [
    {
      "buries_current_top": true,
      "buries_exposed_heart": false,
      "column_1": 1,
      "current_top": "KS",
      "heart_arrival": false,
      "incoming": "2C",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
      "buries_exposed_heart": false,
      "column_1": 2,
      "current_top": "8D",
      "heart_arrival": false,
      "incoming": "10S",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
      "buries_exposed_heart": false,
      "column_1": 3,
      "current_top": "AD",
      "heart_arrival": false,
      "incoming": "QD",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
      "buries_exposed_heart": true,
      "column_1": 4,
      "current_top": "6H",
      "heart_arrival": true,
      "incoming": "KH",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
      "buries_exposed_heart": false,
      "column_1": 5,
      "current_top": "AD",
      "heart_arrival": true,
      "incoming": "8H",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": false,
      "buries_exposed_heart": false,
      "column_1": 6,
      "current_top": null,
      "heart_arrival": false,
      "incoming": "9C",
      "join": "empty",
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
      "buries_exposed_heart": false,
      "column_1": 7,
      "current_top": "6C",
      "heart_arrival": false,
      "incoming": "3S",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
      "buries_exposed_heart": false,
      "column_1": 8,
      "current_top": "10D",
      "heart_arrival": false,
      "incoming": "5S",
      "join": null,
      "useful_heart_landing": false
    },
    {
      "buries_current_top": true,
  
- admissible MW lower bound: 0 Heart 1 is already materially present post-SD2.  Required access moves may be zero-cost whole-column relocates, so no positive MW bound is proved.

## 4. Search

- levels=[0, 1, 2, 3] unique=2271104 expanded=1829614 generated=11294894 dups=8620148 reopens=403646
- zero_cost=165616 max_depth=18 stop=time limit incumbent=None
- elapsed_s=1779.9875157999923 rss_mb=1405.3359375
- per_level=[{'cheaper_reopens': 1999, 'duplicate_skips': 1307064, 'expanded': 506550, 'generated': 2329208, 'heap_empty': False, 'incumbent': None, 'level': 0, 'unique_delta': 1020145, 'witnesses': 0}, {'cheaper_reopens': 313919, 'duplicate_skips': 1802759, 'expanded': 444189, 'generated': 2903045, 'heap_empty': False, 'incumbent': None, 'level': 1, 'unique_delta': 786367, 'witnesses': 0}, {'cheaper_reopens': 87098, 'duplicate_skips': 2472056, 'expanded': 442448, 'generated': 3013906, 'heap_empty': False, 'incumbent': None, 'level': 2, 'unique_delta': 454752, 'witnesses': 0}, {'cheaper_reopens': 630, 'duplicate_skips': 3038269, 'expanded': 436427, 'generated': 3048735, 'heap_empty': False, 'incumbent': None, 'level': 3, 'unique_delta': 9836, 'witnesses': 0}]
- control=None

## 5. Result

- heart=False timing=[] path=None MW=None before_sd3=None after_sd3=None
- stock=None fd=None foundations=None classes=0 replay=False fixture=None

## 6. Post-hoc parks

[]

## 7. Exactly one next recommendation

Keep the Heart-1 target and funnel; do not raise limits here and do not take SD4.

## Integrity

Verdict HEART_TARGET_SEARCH_STATE_EXPLOSION. SD4 expanded=False.
No production change. No human-route guidance.

