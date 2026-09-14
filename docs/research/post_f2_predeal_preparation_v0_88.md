# post_f2_predeal_preparation_v0_88

Verdict: `POST_F2_PREP_SEARCH_LIMITED`

promising prepared lineage remains resource-limited

Tableau-only preparation after F2, then exact SD5. Canonical 172 was not a search input.

## Roots

{'can_deal': True, 'empty_n': 1, 'face_down': 2, 'foundations': 2, 'g': 128, 'ident': '53504b310102000a00020d29000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a3918000226340006363504213c0b000b3d3c3b3a3938373635343d000928270605242332313800000009080716151413121109131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal_tableau': 15, 'mixed_suit_boundaries': 27, 'n_deal': 4, 'n_ready': 1, 'name': 'NEW_G128_F2', 'ok': True, 'ordered_digest': '53504b310102000a00020d29000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a3918000226340006363504213c0b000b3d3c3b3a3938373635343d000928270605242332313800000009080716151413121109131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'stock_rows': 1, 'visible_runs': 36}
{'can_deal': True, 'empty_n': 1, 'face_down': 2, 'foundations': 2, 'g': 129, 'ident': '53504b310102000a00020d29000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a391800022634000436350421000d3d3c3b3a3938373635343d3c0b000928270605242332313800000009080716151413121109131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal_tableau': 15, 'mixed_suit_boundaries': 26, 'n_deal': 4, 'n_ready': 1, 'name': 'INCUMBENT_G129_F2', 'ok': True, 'ordered_digest': '53504b310102000a00020d29000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a391800022634000436350421000d3d3c3b3a3938373635343d3c0b000928270605242332313800000009080716151413121109131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'stock_rows': 1, 'visible_runs': 35}

## Immediate-Deal controls

{'assembly_f': 171, 'assembly_h': 42, 'empty_n': 0, 'foundations': 2, 'ident': '53505331010200000001330002321a00030d291300032634190007363504213c0b37000a08071615141312110925000a28270605242332313801000c3d3c3b3a3938373635343d17000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a3918330d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal': 5, 'mixed_suit_boundaries': 36, 'post_class': 'PROOF_VIABLE_POST_DEAL', 'post_delta_f': None, 'post_delta_h': None, 'post_digest': '53504b310102000000030d29130002321a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a39183300032634190007363504213c0b37000c3d3c3b3a3938373635343d17000a28270605242332313801000133000a080716151413121109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 129, 'pre_g': 128, 'prep_band': '0', 'prep_delta_g': 0, 'prep_payback': None, 'selection_role': 'immediate_deal', 'slack': 15, 'source': 'NEW_G128_F2', 'viable': True, 'visible_runs': 46}
{'assembly_f': 171, 'assembly_h': 41, 'empty_n': 0, 'foundations': 2, 'ident': '53505331010200000001330002321a00030d2913000326341900053635042137000a08071615141312110925000a28270605242332313801000d0a1918171615140302111c1b22000e3d3c3b3a3938373635343d3c0b17020f31122d0c3b1a1d1c2b2a1d2c1b3a3918330d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'legal': 5, 'mixed_suit_boundaries': 35, 'post_class': 'PROOF_VIABLE_POST_DEAL', 'post_delta_f': None, 'post_delta_h': None, 'post_digest': '53504b310102000000030d29130002321a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a391833000326341900053635042137000e3d3c3b3a3938373635343d3c0b17000a28270605242332313801000133000a080716151413121109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 130, 'pre_g': 129, 'prep_band': '0', 'prep_delta_g': 0, 'prep_payback': None, 'selection_role': 'immediate_deal', 'slack': 15, 'source': 'INCUMBENT_G129_F2', 'viable': True, 'visible_runs': 45}

prep unique A/B=50119/37408 predeal_f3=0 eval=80 viable_post=80 dead=0

## Selected rollout

| src | prep Δg | post g | h | f | slack | maxF | best f |
| --- | ------: | -----: | -: | -: | ----: | ---: | -----: |
| NEW_G128_F2 | 0 | 129 | 42 | 171 | 15 | 4 | 187 |
| INCUMBENT_G129_F2 | 0 | 130 | 41 | 171 | 15 | 2 | 171 |
| NEW_G128_F2 | 0 | 129 | 42 | 171 | 15 | 3 | 177 |
| NEW_G128_F2 | 12 | 141 | 38 | 179 | 7 | 2 | 179 |
| NEW_G128_F2 | 1 | 130 | 41 | 171 | 15 | 2 | 171 |
| NEW_G128_F2 | 3 | 132 | 42 | 174 | 12 | 2 | 174 |
| NEW_G128_F2 | 6 | 135 | 41 | 176 | 10 | 2 | 176 |
| INCUMBENT_G129_F2 | 0 | 130 | 41 | 171 | 15 | 2 | 171 |
| NEW_G128_F2 | 1 | 130 | 41 | 171 | 15 | 2 | 171 |
| NEW_G128_F2 | 1 | 130 | 42 | 172 | 14 | 2 | 172 |
| NEW_G128_F2 | 1 | 130 | 42 | 172 | 14 | 3 | 178 |
| NEW_G128_F2 | 1 | 130 | 42 | 172 | 14 | 2 | 172 |

continuation n=24 stop=`time limit` unique=49035 exp=3626 maxF=4 exhausted=False wall=900.3

## Interpretation

Bounded Δg<=15 tableau prep never produced post-Deal f<171. Spending more before SD5 typically raised f (e.g. Δg=12 → post 141/h38/f179). Δg=1 often traded +1g for -1h at the same f=171 without beating Root A immediate Deal in rollout. No pre-Deal F3. Immediate-Deal Root A remained the strongest 10–20s root (F3/F4). Continuation of the mixed 24-root portfolio was time-limited at maxF=4.

## Next recommendation

Immediate Deal remains locally preferable in the Δg<=15 window. Do not resume closed v0.87 F5s. Improve the rows=1 F2-producing trajectory.

