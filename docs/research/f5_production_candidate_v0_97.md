# f5_production_candidate_v0_97

Verdict: `F5_PRODUCTION_F5_STALL`

reproduced F5 but no deeper meaningful consequence

Branch: `agent/f5-production-candidate-v0-97`  Base: `b8384fdd35cf283030acb958dedcf39283a989f8`

One ORIGINAL_G123 F2, ceiling 186, lean evaluator, 240 s max. Canonical 172 absent.

## Candidate

{'g': 130, 'h': 42, 'f': 172, 'legal': 5, 'face_down': 2, 'visible_runs': 46, 'mixed_suit_boundaries': 36, 'ident': '53505331010200000001330002321a00030d2913000326341900053635042137000a08071615141312110925000a28270605242332313801000d0a1918171615140302111c0b22000e3d3c3b3a3938373635343d3c1b17020f31122d0c3b1a1d1c2b2a1d2c1b3a3918330d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'ordered_digest': '53504b310102000000030d29130002321a000d0a1918171615140302111c0b22020f31122d0c3b1a1d1c2b2a1d2c1b3a391833000326341900053635042137000e3d3c3b3a3938373635343d3c1b17000a28270605242332313801000133000a080716151413121109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'source_f1': 'ORIGINAL_G123', 'v096_signal': {'max_F': 5, 'first_deep_g': 174, 'first_deep_f': 186, 'unique': 7160, 'elapsed_s': 25.135374699999375}}

distinct_from_CONTROL_187=True n_deal=5

## Envelope

ceiling=186 t=240.0s unique=800000 stop_on_terminal=True

## Milestones

| F | first t | first g/h/f | cheapest g | lowest f |
| -: | ------: | ----------- | ---------: | -------: |
| 2 | 0.0 | 130/42/172 | 130 | 172 |
| 3 | 6.1 | 155/22/177 | 155 | 177 |
| 4 | 12.2 | 172/14/186 | 171 | 185 |
| 5 | 14.7 | 174/12/186 | 174 | 186 |

F5 reproduced=True stop=`time limit` unique=67453 maxF=5 wall=252.5

## Known-closed audit

{'n_hits': 2, 'n_reopen': 0, 'hits': [{'ident': '535053310105000000000000000000010100010b00011d00020d0c00041d1c1b1a000908071615141312110900150a1918171615140302111c1b1a19181706050413120d3d3c3b3a3938373635343332310d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'arrival_g': 174, 'closed_g': 173, 'closed_source': 'v081', 'F': 5, 'reopened': False}, {'ident': '5350533101040000000000010100011d00020d0c00033d3c3b00041d1c1b1a0009080716151413121109000a0b3a393837363534333200140a1918171615140302111c1b1a19181706050413010131120d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'arrival_g': 171, 'closed_g': 170, 'closed_source': 'v081', 'F': 4, 'reopened': False}]}

## Interpretation

reproduced F5 but no deeper meaningful consequence

## Next recommendation

The 25-second F5 signal did not mature. Pause and consolidate.

