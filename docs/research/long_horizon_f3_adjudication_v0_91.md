# long_horizon_f3_adjudication_v0_91

Verdict: `LONG_HORIZON_F3_EXHAUSTED`

generated F4/F5 candidates exhausted without a solution

Branch: `agent/long-horizon-f3-adjudication-v0-91`  Base: `b121f99d0777ab173f6bf6dc6c5117ff29af11f4`

Tactical F3→F4 probes are candidate generators. Stage C frozen continuation is the adjudicator.
Canonical 172 was not a search input.

## v0.90 reporting fix

{'cheap_F3': {'elapsed_s': 9.939541600004304, 'f': 174, 'g': 134, 'h': 40}, 'cross_wired': False, 'first_F3': {'elapsed_s': 1.1730631000245921, 'f': 173, 'g': 138, 'h': 35}, 'fix': 'V090_F3_SUMMARY_FORMATTING_FIX'}

`V090_F3_SUMMARY_FORMATTING_FIX`: first F3 economics stay with ~1.17 s; cheapest-g F3 stays with ~9.94 s.

## F3 roots

[{'calibration_name': 'FIRST_LOWEST_F_F3', 'g': 138, 'foundations': 3, 'assembly_h': 35, 'assembly_f': 173, 'slack': 13, 'face_down': 2, 'empty_n': 1, 'legal_tableau': 20, 'visible_runs': 38, 'visible_components': 38, 'mixed_suit_boundaries': 29, 'ready_suits': ['s', 'h', 'd', 'c'], 'n_ready': 4, 'ordered_digest': '53504b310103000000030d29130005321a191817000e0a1918171615140302111c1b2201020e31122d0c3b1a1d1c2b2a1d2c1b3a393800032634330007363504213c0b3700013d00062827060524230000000a080716151413121109250d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'ident': '5350533101030000000000013d00030d291300032634330005321a19181700062827060524230007363504213c0b37000a08071615141312110925000e0a1918171615140302111c1b2201020e31122d0c3b1a1d1c2b2a1d2c1b3a39380d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'ok': True, 'reason': None, 'vs_g141_ident': True, 'vs_g148_ident': True, 'known_closed': False, 'elapsed_s': 1.1730631000245921, 'foundation_suits': ['c', 'd', 's']}, {'calibration_name': 'CHEAPEST_G_F3', 'g': 134, 'foundations': 3, 'assembly_h': 40, 'assembly_f': 174, 'slack': 12, 'face_down': 2, 'empty_n': 1, 'legal_tableau': 13, 'visible_runs': 43, 'visible_components': 43, 'mixed_suit_boundaries': 34, 'ready_suits': ['s', 'h', 'd', 'c'], 'n_ready': 4, 'ordered_digest': '53504b310103000000030d29130002321a000e0a1918171615140302111c1b2201020f31122d0c3b1a1d1c2b2a1d2c1b3a3918330004263419380007363504213c0b3700023d1700062827060524230000000a080716151413121109250d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'ident': '535053310103000000000002321a00023d1700030d291300042634193800062827060524230007363504213c0b37000a08071615141312110925000e0a1918171615140302111c1b2201020f31122d0c3b1a1d1c2b2a1d2c1b3a3918330d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'ok': True, 'reason': None, 'vs_g141_ident': True, 'vs_g148_ident': True, 'known_closed': False, 'elapsed_s': 9.939541600004304, 'foundation_suits': ['c', 'd', 's']}]

fresh targets: {'CHEAPEST_G_F3': ['h', 'd', 's', 'c'], 'FIRST_LOWEST_F_F3': ['h', 'c', 'd', 's']}

## Stage A / B

[{'best_viable_f': 186, 'cheapest_viable_g': 159, 'elapsed_s': 30.109695099992678, 'expanded': 600, 'first_viable_s': 10.635677000042051, 'min_h_viable': 25, 'operational_rank': 1, 'proof_prunes': 3401, 'raw_count': 8, 'root_name': 'FIRST_LOWEST_F_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 'h', 'surplus_count': 0, 'unique': 7185, 'viable_count': 8}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.020102100039367, 'expanded': 726, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 2, 'proof_prunes': 2510, 'raw_count': 0, 'root_name': 'FIRST_LOWEST_F_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 'c', 'surplus_count': 0, 'unique': 6735, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.00535430002492, 'expanded': 736, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 3, 'proof_prunes': 3673, 'raw_count': 0, 'root_name': 'FIRST_LOWEST_F_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 'd', 'surplus_count': 0, 'unique': 7579, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.010497099952772, 'expanded': 659, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 4, 'proof_prunes': 2098, 'raw_count': 0, 'root_name': 'FIRST_LOWEST_F_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 's', 'surplus_count': 0, 'unique': 6584, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.02417690004222, 'expanded': 856, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 1, 'proof_prunes': 3797, 'raw_count': 0, 'root_name': 'CHEAPEST_G_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 'h', 'surplus_count': 0, 'unique': 7334, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.007704000046942, 'expanded': 862, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 2, 'proof_prunes': 3814, 'raw_count': 0, 'root_name': 'CHEAPEST_G_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 'd', 'surplus_count': 0, 'unique': 7348, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.006621800013818, 'expanded': 785, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 3, 'proof_prunes': 2857, 'raw_count': 0, 'root_name': 'CHEAPEST_G_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 's', 'surplus_count': 0, 'unique': 6562, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.025306300027296, 'expanded': 809, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 4, 'proof_prunes': 3348, 'raw_count': 0, 'root_name': 'CHEAPEST_G_F3', 'stage': 'A', 'stop_reason': 'time limit', 'suit': 'c', 'surplus_count': 0, 'unique': 7247, 'viable_count': 0}]

[{'best_viable_f': 186, 'cheapest_viable_g': 159, 'elapsed_s': 30.215090200013947, 'expanded': 619, 'first_viable_s': 10.411943799990695, 'min_h_viable': 25, 'operational_rank': 1, 'proof_prunes': 3513, 'raw_count': 8, 'root_name': 'FIRST_LOWEST_F_F3', 'stage': 'B', 'stop_reason': 'time limit', 'suit': 'h', 'surplus_count': 0, 'unique': 7409, 'viable_count': 8}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.04217079997761, 'expanded': 872, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 1, 'proof_prunes': 3835, 'raw_count': 0, 'root_name': 'CHEAPEST_G_F3', 'stage': 'B', 'stop_reason': 'time limit', 'suit': 'h', 'surplus_count': 0, 'unique': 7454, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.116909599979408, 'expanded': 725, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 3, 'proof_prunes': 3623, 'raw_count': 0, 'root_name': 'FIRST_LOWEST_F_F3', 'stage': 'B', 'stop_reason': 'time limit', 'suit': 'd', 'surplus_count': 0, 'unique': 7492, 'viable_count': 0}, {'best_viable_f': None, 'cheapest_viable_g': None, 'elapsed_s': 30.02725519996602, 'expanded': 790, 'first_viable_s': None, 'min_h_viable': None, 'operational_rank': 4, 'proof_prunes': 3314, 'raw_count': 0, 'root_name': 'CHEAPEST_G_F3', 'stage': 'B', 'stop_reason': 'time limit', 'suit': 'c', 'surplus_count': 0, 'unique': 7136, 'viable_count': 0}]

raw=16 viable=8 surplus=0 strong_surplus=0

## F4 portfolio

[{'assembly_f': 186, 'assembly_h': 27, 'bridge_loss': None, 'class': 'VIABLE_TARGET_CASHOUT', 'closed': False, 'foundations': 4, 'g': 159, 'gateway': 'PROOF_VIABLE', 'ident': '5350533101040000000000010900011b0002080700023d2c00030d291300082827060534333201000a0a191817161514030211000f363504213c0b3a3938372625242322020831122d0c3b1a1d1c2b2a0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'legal_tableau': 24, 'ordered_digest': '53504b310104000000030d29130000000a0a191817161514030211020831122d0c3b1a1d1c2b2a000109000f363504213c0b3a393837262524232200023d2c0008282706053433320100011b000208070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'portfolio_role': 'best_FIRST_LOWEST_F_F3', 'quality': None, 'reopened': None, 'root_g': 138, 'root_name': 'FIRST_LOWEST_F_F3', 'slack': 0, 'tactical_target': 'h', 'viable': True}, {'assembly_f': 186, 'assembly_h': 25, 'bridge_loss': None, 'class': 'VIABLE_TARGET_CASHOUT', 'closed': False, 'foundations': 4, 'g': 161, 'gateway': 'PROOF_VIABLE', 'ident': '5350533101040000000000011b00012c00013d000309080700030d2913000728272625242322000a0a1918171615140302110010363504213c0b3a393837060534333201020831122d0c3b1a1d1c2b2a0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'legal_tableau': 27, 'ordered_digest': '53504b310104000000030d29130000000a0a191817161514030211020831122d0c3b1a1d1c2b2a00030908070010363504213c0b3a39383706053433320100013d00072827262524232200011b00012c0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'portfolio_role': 'lowest_h', 'quality': None, 'reopened': None, 'root_g': 138, 'root_name': 'FIRST_LOWEST_F_F3', 'slack': 0, 'tactical_target': 'h', 'viable': True}, {'assembly_f': 186, 'assembly_h': 25, 'bridge_loss': None, 'class': 'VIABLE_TARGET_CASHOUT', 'closed': False, 'foundations': 4, 'g': 161, 'gateway': 'PROOF_VIABLE', 'ident': '53505331010400000000000000011b00023d2c000309080700030d2913000728272625242322000a0a1918171615140302110010363504213c0b3a393837060534333201020831122d0c3b1a1d1c2b2a0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'legal_tableau': 42, 'ordered_digest': '53504b310104000000030d29130000000a0a191817161514030211020831122d0c3b1a1d1c2b2a00030908070010363504213c0b3a39383706053433320100023d2c00072827262524232200011b00000d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'portfolio_role': 'highest_mobility', 'quality': None, 'reopened': None, 'root_g': 138, 'root_name': 'FIRST_LOWEST_F_F3', 'slack': 0, 'tactical_target': 'h', 'viable': True}, {'assembly_f': 186, 'assembly_h': 27, 'bridge_loss': None, 'class': 'VIABLE_TARGET_CASHOUT', 'closed': False, 'foundations': 4, 'g': 159, 'gateway': 'PROOF_VIABLE', 'ident': '535053310104000000010900011b00012c00013d0002080700030d291300082827060534333201000a0a191817161514030211000f363504213c0b3a3938372625242322020831122d0c3b1a1d1c2b2a0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'legal_tableau': 10, 'ordered_digest': '53504b310104000000030d291300012c000a0a191817161514030211020831122d0c3b1a1d1c2b2a000109000f363504213c0b3a393837262524232200013d0008282706053433320100011b000208070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201', 'portfolio_role': 'fill', 'quality': None, 'reopened': None, 'root_g': 138, 'root_name': 'FIRST_LOWEST_F_F3', 'slack': 0, 'tactical_target': 'h', 'viable': True}]
closed_hits=0 reopen=0

## Stage C long-horizon scorecard

| source F3 | F4 g/h/f | F4 slack | 90s maxF | deepest g/h/f | deepest slack | stop | status |
| --------- | -------- | -------: | -------: | ------------- | ------------: | ---- | ------ |
| FIRST_LOWEST_F_F3 | 159/27/186 | 0 | 4 | 159/27/186 | 0 | complete | LONG_HORIZON_DEAD |
| FIRST_LOWEST_F_F3 | 159/27/186 | 0 | 4 | 159/27/186 | 0 | complete | LONG_HORIZON_DEAD |
| FIRST_LOWEST_F_F3 | 161/25/186 | 0 | 4 | 161/25/186 | 0 | complete | LONG_HORIZON_DEAD |
| FIRST_LOWEST_F_F3 | 161/25/186 | 0 | 4 | 161/25/186 | 0 | complete | LONG_HORIZON_DEAD |

## Stage D

[]

maxF=4 deepest_f=186 slack=0 live=0 dead=4 wall=362.4

## Root A vs Root B consequences

{'CHEAPEST_G_F3': {'best_f4_f': None, 'deepest_f': None, 'deepest_slack': None, 'max_F': 3, 'n': 0, 'statuses': []}, 'FIRST_LOWEST_F_F3': {'best_f4_f': 186, 'deepest_f': 186, 'deepest_slack': 0, 'max_F': 4, 'n': 4, 'statuses': ['LONG_HORIZON_DEAD', 'LONG_HORIZON_DEAD', 'LONG_HORIZON_DEAD', 'LONG_HORIZON_DEAD']}}

## Historical g148

g148: F3 f177 → F4 f181 → F5 f186 → closed. 187-class converts F4→F8 despite worse local f.

## Interpretation

Root A (g138/f173) generated zero-slack Hearts F4s at f=186 (g159/h27 and g161/h25). Stage C exhausted each proof-viable graph at F4 with stop=complete; no F5. Root B (g134/f174) produced no proof-viable F4. The extra +4 g in Root A bought only a dead F4 gateway, worse slack decay than historical g148 (F3 f177 -> F4 f181 -> F5 f186). Local F3 quality did not predict cheaper eventual continuation.

## Next recommendation

Stop mining this prepared-root family. Move upstream to strategic rows=1 F1 preparation → tactical F2 cash-out → SD5 → long-horizon evaluation.

