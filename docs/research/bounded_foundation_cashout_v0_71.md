# bounded_foundation_cashout_v0_71

Verdict: `TACTICAL_CASHOUT_FINDS_CHEAPER_F2`

g=128 < incumbent 130

## Why this differs from READINESS

READINESS answers: which currently-ready suit looks best in this state?
TACTICAL CASH-OUT answers: given that suit as a fixed short-term objective, which sequence of legal actions reaches its foundation?
Intermediate operational keys may worsen. Monotonic improvement is not required.

## Search firewall

Search used only the autonomous 192 prefix up to the rows=1 epoch-entry, that exact state, its prefix g, and generic operational analysis of that state. The 192 suffix, the known F2 digest, and canonical 172 were not available during search.

## Exact tactical root

- absolute g = 123
- F = 1
- fd = 2
- stock rows = 1
- deals in prefix = 4
- legal mobility = 8
- ordered digest = `53504b310101000a00020d2900010b000b0a1918171615140302111c020f31122d0c3b1a1d1c2b2a1d2c1b3a391822000226340005363504213c000b3d3c3b3a3938373635343d0009282706052423323138000e2d2c2b2a2928272625242332211b0009080716151413121109131a22331937170133250d0d0c0b0a090807060504030201`
- identity is ordered pre-stock = True

## Generic target selection

- rule = `rank_ready_suits(state)['best']['suit']`
- target suit = `d` (telemetry only; not a policy literal)
- n_ready = 2
- ready suits = ['h', 'd']
- cover = 3
- blockers = 42
- K/A access = 3 / 1
- gap = 1
- merge edges = 0
- operational key = [2, 3, 42, 14, 0, 3, 1, -11, -1, 0, 0, -2, 123]

## Tactical lanes

- COST: absolute g
- TARGET_ASSEMBLY: cover, inaccessible joins, K/A access, gap, merge edges, blockers, g
- TARGET_ACCESS: K/A blocker burden, buried/exposed components, workspace, g

## Focused envelope

- time = 300.0 s
- unique cap = 400000
- RSS abort = 2560.0 MiB
- cost ceiling = 191
- Deal = forbidden
- harvest_slack = None (continue after first terminal)

## Search totals

- unique = 41576
- expanded = 13156
- generated = 119766
- duplicate skips = 57209
- stale skips = 2292
- expansions/sec = 43.852
- elapsed = 300.00956779997796 s
- stop = time limit
- lane expansions = {'cost': 4788, 'target_access': 4260, 'target_assembly': 4108}
- first target foundation g = 129 at t=0.4032570999697782 s
- cheapest target foundation g = 128
- delta_g = 5
- distinct terminals = 349
- portfolio size = 64
- cheapest action count = 5

## Cheapest path target-metric evolution

- g=124 mw=1 fd=2 empty=1 legal=14 cover=3 blockers=42 K=3 A=1 gap=1 merge=0 worsened=[]
- g=125 mw=1 fd=2 empty=1 legal=12 cover=3 blockers=41 K=2 A=0 gap=1 merge=1 worsened=[]
- g=126 mw=1 fd=2 empty=1 legal=13 cover=2 blockers=43 K=1 A=0 gap=0 merge=0 worsened=['blockers', 'merge_edges', 'exposed_components']
- g=127 mw=1 fd=2 empty=0 legal=12 cover=2 blockers=42 K=0 A=0 gap=0 merge=1 worsened=[]
- g=128 mw=1 fd=2 empty=1 legal=13 cover=None blockers=36 K=13 A=2 gap=11 merge=0 worsened=[]

## Non-monotonic steps

n = 1
- i=2 g=126 action=[8, 3, 1] worsened=['blockers', 'merge_edges', 'exposed_components']

## After-run incumbent comparison

- planner target = `d`
- incumbent cashed = `d` at g=130
- planner cheapest g = 128
- incumbent action count = 7
- planner action count = 5
- terminal same state = False
- classification = cheaper_different

## Deal-preview comparison

- planner preview = {'auto_foundations': 0, 'best_suit': 'c', 'boundaries': 37, 'component_layers': 37, 'deal_cost': 1, 'empty_land': 1, 'empty_n': 0, 'face_down': 2, 'foundations': 2, 'legal_tableau': 5, 'mixed': 9, 'mixed_supports': 9, 'n_ready': 4, 'ok': True, 'op_defined': True, 'post_digest': '53504b310102000000030d29130002321a000d0a1918171615140302111c0b22020f31122d0c3b1a1d1c2b2a1d2c1b3a39183300032634190007363504213c1b37000c3d3c3b3a3938373635343d17000a28270605242332313801000133000a080716151413121109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 129, 'pre_g': 128, 'pre_legal': 13, 'rank_ok': 0, 'same_suit': 0, 'stock_rows': 0, 'visible_components': 47}
- incumbent preview = {'auto_foundations': 0, 'best_suit': 'c', 'boundaries': 35, 'component_layers': 35, 'deal_cost': 1, 'empty_land': 1, 'empty_n': 0, 'face_down': 2, 'foundations': 2, 'legal_tableau': 5, 'mixed': 9, 'mixed_supports': 9, 'n_ready': 4, 'ok': True, 'op_defined': True, 'post_digest': '53504b310102000000030d29130002321a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a391833000326341900053635042137000e3d3c3b3a3938373635343d3c0b17000a28270605242332313801000133000a080716151413121109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201', 'post_g': 131, 'pre_g': 130, 'pre_legal': 15, 'rank_ok': 0, 'same_suit': 0, 'stock_rows': 0, 'visible_components': 45}

## Interpretation

A generic bounded cash-out probe independently completed the rank-1 ready suit cheaper than the autonomous 192 suffix.

## Next recommendation

v0.72 should integrate bounded tactical cash-out probes into the rows=1 whole-game scheduler, using selected ready-state roots.

