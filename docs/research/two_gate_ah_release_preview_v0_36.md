# Spider Solver v0.36 — Two-Gate AH-Release Preview

## 1. Verdict

`GATE3_JH_NOT_FOUND_UNDER_COST82` — no Gate-3 witness with full MW <= 82

no Gate-3 witness with full MW <= 82. Gate 2 is internal. Nested probes classify each new Gate-2 state as AH_RELEASE_NOW / SD3_AVAILABLE / POST_SD3 / EXACT_DEAD_KNOWN. v0.35 exact dead memo loaded 144 identities, reuse hits 7998. AH release is empty or any-suit rank 2. SD3 row ('2C', '10S', 'QD', 'KH', '8H', '9C', '3S', '5S', '5D', '4H') (2C on col1, 10S on col2). Cost ceiling 82. No incumbent+2 Gate-2 prune. No large UCS. SD4 never expanded. 9H not searched.

- Branch: `agent/two-gate-ah-release-preview-v0-36`
- Base SHA: `2412db2a101a56285268417e6993bc4ca4682080`

## 2. Gate-1 sources

- n=40 costs `{"70": 16, "71": 8, "72": 16}`
- SD3 available/used: 24 / 16
- empty counts: `{"0": 40}`
- exposed rank-2: 0 yes / 40 no
- all replay: `True`

## 3. v0.35 dead memo

- exact states loaded: 144
- exact reuse hits: 7998
- Reused only by ordered pack_state identity. No structural overgeneralisation.

## 4. Gate-2 encounters

{
  "ah_release_now": 0,
  "class_counts": {
    "EXACT_DEAD_KNOWN": 7998,
    "POST_SD3_RELEASE_NOT_IMMEDIATE": 3248
  },
  "cost_max": 82,
  "cost_min": 73,
  "encounters": 11246,
  "exact_dead": 3048,
  "exact_dead_known_skip": 7998,
  "live_beyond_probe": 200,
  "nested_probe_gate3": 0,
  "outside_old_737475": 180,
  "post_sd3": 11246,
  "pre_sd3": 0,
  "probe_counts": {
    "EXACT_DEAD": 3048,
    "LIVE_BEYOND_PROBE": 200,
    "SKIPPED_KNOWN_DEAD": 7998
  },
  "total_records_kept": 256
}

## 5. Gate 3

{}

## 6. Search

{
  "cost_ceiling": 82,
  "duplicate_skips": 409816,
  "elapsed_s": 750.0021258999768,
  "expanded": 154788,
  "generated": 768832,
  "incumbent": null,
  "max_g_seen": 83,
  "no_gate2_incumbent_plus_2": true,
  "peak_rss_mb": 191.6015625,
  "probes": 3248,
  "sd4_expanded": false,
  "stop_reason": "time limit",
  "unique": 288095,
  "used_heuristic_prune": false
}

## 7. Portfolios

{
  "gate1": "docs/research/two_gate_ah_release_preview_v0_36_gate1_sources.json",
  "gate2": "docs/research/two_gate_ah_release_preview_v0_36_gate2_portfolio.json",
  "gate3": "docs/research/two_gate_ah_release_preview_v0_36_gate3_portfolio.json",
  "gate3_bands": {},
  "gate3_n": 0
}

## 8. Learning

All 11246 Gate-2 encounters under MW 82 were post-SD3 (pre-SD3 count=0). Zero AH_RELEASE_NOW. 24/40 Gate-1 sources still had SD3, but no pre-SD3 AH-exposure appeared in the envelope. Preview did visit Gate-2 costs 73-82 (outside-old-band kept=180) yet they stayed operationally uniform: SD3 consumed, no empty, no exposed 2, AH immovable. 200 LIVE_BEYOND_PROBE components did not reach JH inside the wall-clock bound. Backward knowledge of JH did not unlock a viable AH-exposure timing before SD4 at MW<=82. Not turned into a heuristic.

## 9. Exactly one next recommendation

Gate 3 was not found at full MW <= 82 from the 40 Gate-1 states with SD4 withheld. Next: decide whether Heart-before-SD4 is still the right earliest extra foundation, or allow SD4 and reassess Heart versus newly available Diamonds. Do not raise the 82 envelope.

## Integrity

Verdict GATE3_JH_NOT_FOUND_UNDER_COST82. SD4 expanded=False.
Gate 2 internal. Gate 3 terminal. Cost ceiling 82. No large UCS. No production change.

