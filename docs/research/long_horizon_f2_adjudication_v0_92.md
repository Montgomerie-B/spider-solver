# long_horizon_f2_adjudication_v0_92

Verdict: `LONG_HORIZON_F2_CALIBRATION_INSUFFICIENT`

CONTROL_187 did not reach F4; horizon cannot distinguish the known-good F2

Branch: `agent/long-horizon-f2-adjudication-v0-92`  Base: `dbf02ff7da00aca9cc0174cf27cbe8c12a65c60d`

Long-horizon adjudication of the existing v0.84 F2 population. CONTROL_187 is calibration only. The 187 suffix was not used. Canonical 172 was not a search input.

## Population

n_f2=279 n_unique_pre=279 n_viable_post=279 persisted_post=17 pareto=10 eligible=8

## Selection freeze (before old rollout labels)

{'NOVEL_A': {'assembly_f': 174, 'assembly_h': 40, 'control_tag': None, 'empty_n': 0, 'face_down': 2, 'foundations': 2, 'g': None, 'ident': '53505331010200000001330002321a00030d29130003263419000536350421370009282706052423323101000b0807161514131211091825000d0a1918171615140302111c1b22000e3d3c3b3a3938373635343d3c0b17020f31122d0c3b1a1d1c2b2a1d2c1b3a3938330d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal': 5, 'n_deal': None, 'name': 'NOVEL_A', 'post_digest': '53504b310102000000030d29130002321a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a393833000326341900053635042137000e3d3c3b3a3938373635343d3c0b170009282706052423323101000133000b08071615141312110918250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 134, 'pre_digest': '53504b310102000a00020d29000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a393800022634000436350421000d3d3c3b3a3938373635343d3c0b000828270605242332310000000a08071615141312110918131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'pre_g': 133, 'selection_reason': 'lowest_h_then_f_then_g', 'slack': 12, 'tactical_target': 'd', 'v084_selected': None, 'v084_selection_role': None, 'v084_short_liked': None, 'verify_ok': None}, 'NOVEL_B': {'assembly_f': 174, 'assembly_h': 40, 'control_tag': None, 'empty_n': 0, 'face_down': 2, 'foundations': 2, 'g': None, 'ident': '535053310102000000013300030d29130003263419000332211a0004363504370009282706052423323101000b0807161514131211091825000d0a1918171615140302111c1b22000e3d3c3b3a3938373635343d3c0b17020f31122d0c3b1a1d1c2b2a1d2c1b3a3938330d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal': 5, 'n_deal': None, 'name': 'NOVEL_B', 'post_digest': '53504b310102000000030d2913000332211a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a3938330003263419000436350437000e3d3c3b3a3938373635343d3c0b170009282706052423323101000133000b08071615141312110918250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 134, 'pre_digest': '53504b310102000a00020d2900023221000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a3938000226340003363504000d3d3c3b3a3938373635343d3c0b000828270605242332310000000a08071615141312110918131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'pre_g': 133, 'selection_reason': 'cheapest_distinct_g_f', 'slack': 12, 'tactical_target': 'd', 'v084_selected': None, 'v084_selection_role': None, 'v084_short_liked': None, 'verify_ok': None}, 'NOVEL_C': {'assembly_f': 180, 'assembly_h': 41, 'control_tag': None, 'empty_n': 0, 'face_down': 2, 'foundations': 2, 'g': None, 'ident': '535053310102000000013300030d29130003263419000332111a00040a1918220007363504213c0b37000a0807161514131211092500102827060524233231381716151403020100113d3c3b3a3938373635343d1c1b3a391817020c31122d0c3b1a1d1c2b2a1d2c1b330d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal': 9, 'n_deal': None, 'name': 'NOVEL_C', 'post_digest': '53504b310102000000030d2913000332111a00040a191822020c31122d0c3b1a1d1c2b2a1d2c1b3300032634190007363504213c0b3700113d3c3b3a3938373635343d1c1b3a391817001028270605242332313817161514030201000133000a080716151413121109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 139, 'pre_digest': '53504b310102000a00020d290002321100030a1918020b31122d0c3b1a1d1c2b2a1d2c1b000226340006363504213c0b00103d3c3b3a3938373635343d1c1b3a3918000f28270605242332313817161514030200000009080716151413121109131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'pre_g': 138, 'selection_reason': 'greatest_legal_then_fewer_mixed_runs', 'slack': 6, 'tactical_target': 'd', 'v084_selected': None, 'v084_selection_role': None, 'v084_short_liked': None, 'verify_ok': None}}

## Historical short-rollout labels (after freeze)

{'control_187': {'role': 'fill', 'selected': True, 'stage_a_maxF': [2], 'stage_a_roles': ['fill']}, 'novel_a': {'role': 'lowest_h', 'selected': True, 'stage_a_maxF': [2], 'stage_a_roles': ['lowest_h']}, 'novel_b': {'role': 'pareto_balanced', 'selected': True, 'stage_a_maxF': [2], 'stage_a_roles': ['pareto_balanced']}, 'novel_c': {'role': 'highest_mobility', 'selected': True, 'stage_a_maxF': [2], 'stage_a_roles': ['highest_mobility']}}

## Stage A 150s scorecard

| root | start g/h/f | 150s maxF | deepest g/h/f | slack | stop | unique | expanded |
| ---- | ----------- | --------: | ------------- | ----: | ---- | -----: | -------: |
| CONTROL_187 | 130/41/171 | 3 | 156/27/183 | 3 | time limit | 18878 | 1250 |
| NOVEL_A | 134/40/174 | 4 | 172/14/186 | 0 | time limit | 18316 | 1280 |
| NOVEL_B | 134/40/174 | 3 | 157/29/186 | 0 | time limit | 19053 | 1133 |
| NOVEL_C | 139/41/180 | 2 | 139/41/180 | 6 | time limit | 19760 | 1744 |

calibration_insufficient=True extension=150.0

## Stage B

{'calibration': False, 'deepest_f': 186, 'deepest_g': 172, 'deepest_h': 14, 'deepest_slack': 0, 'elapsed_s': 149.09669989999384, 'expanded': 1319, 'max_F': 4, 'name': 'NOVEL_A', 'solved': False, 'start_f': 174, 'start_g': 134, 'start_h': 40, 'status': 'LONG_HORIZON_LIVE', 'stop': 'time limit', 'time_first_increase': 59.991407299996354, 'unique': 19151}

## Old short vs new deep

[{'extended_maxF': None, 'old_liked': False, 'old_short_maxF': [2], 'old_short_role': 'fill', 'root': 'CONTROL_187', 'stage_a_maxF': 3, 'status': 'LONG_HORIZON_LIVE'}, {'extended_maxF': 4, 'old_liked': True, 'old_short_maxF': [2], 'old_short_role': 'lowest_h', 'root': 'NOVEL_A', 'stage_a_maxF': 4, 'status': 'LONG_HORIZON_LIVE'}, {'extended_maxF': None, 'old_liked': True, 'old_short_maxF': [2], 'old_short_role': 'pareto_balanced', 'root': 'NOVEL_B', 'stage_a_maxF': 3, 'status': 'LONG_HORIZON_LIVE'}, {'extended_maxF': None, 'old_liked': True, 'old_short_maxF': [2], 'old_short_role': 'highest_mobility', 'root': 'NOVEL_C', 'stage_a_maxF': 2, 'status': 'LONG_HORIZON_LIVE'}]

wall=900.1 maxF=4

## Interpretation

CONTROL_187 reached its known F3 (g156/h27/f183 slack+3) in 150s and again after a fresh 150s extension, but never F4. That is the historical 187-class F3, not yet the F4-F8 conversion. NOVEL_A, which short rollout liked as lowest_h, reached F4 g172/h14/f186 slack 0 (v0.91-class dead gateway) and Stage B confirmed the same F4. NOVEL_B F3 f=186 slack 0. NOVEL_C stayed F2. Ranking by 150s maxF would prefer the slack-0 F4 over the known-good F2. The horizon is therefore too short to recognise a choice we already know was good.

## Next recommendation

Do not generate more upstream candidates yet. Improve consequence-evaluator depth/efficiency first.

