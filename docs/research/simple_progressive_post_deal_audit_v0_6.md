# Simple Progressive Search v0.6: Post-Deal Continuation Audit

## 1. Verdict

`TT_OR_SATURATION_BLOCKS_POST_DEAL_CONTINUATION` — hypothesis `SATURATION_SCHEDULE_SKIPS_WIDER_CONTINUATION`.

Instrumentation only. Best-reveal Deal probe, A–D classification, scores,
preparation, depth bands, saturation, exact TT, and node budgets are unchanged.

## 2. Strong coupled lineage

- Lineage ID: `L_COUPLED_FD14_DEALS5_DEPTH43`.
- Source: deals_completed=5 fd=14 stock_rows=0 foundations=0 depth=43 cost=43 path_length=43.
- Replay-valid: True.
- Deals on this path: 5.
- Terminal key: `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`.

This is one replay-valid path — the strongest `best_fd_by_stock_dealt`
witness that completed the most stock rows. Separate per-depth minima
are not spliced together.

## 3. Per-Deal continuation anatomy

### Deal 1

**Pre-Deal**

- digest `53504b310100003204053a2c36083504230231050415191b11282d0c2b1a01073b27061534233231000314131200012d00020d0c040718360a2a2807060504030200011200083d3c3b3a3938372600021716131a2233193717013325290b1c22343c3d381b09320a2c1d1839030525140d0116072121112a1c2b0b29241d242609270835`
- primitive depth 38; pass first-seen 0
- fd=14 foundations=0 stock_rows=5 empties=0
- legal=10 tableau A/B/C/D=0/3/6/0
- Deal ordinary tier=3 legal=True

**Deal**

- child digest `53504b310100002804063a2c360835042302310b050515191b11282d0c2b1a2901083b270615342332312400041413121d00022d2400030d0c26040818360a2a28070605040302090002122700093d3c3b3a39383726080003171635131a2233193717013325290b1c22343c3d381b09320a2c1d1839030525140d0116072121112a1c2b`
- post fd=14 foundations=0 stock_rows=4
- matched checkpoint child=True pop=children_exhausted

**Continuation**

- post tableau A/B/C/D=2/5/0/0
- expanded at current pass (direct)=3
- descendants before next Deal=2
- descendants until backtrack=21
- best descendant fd=14 foundations=0
- next Deal reached=True
- post-state suppression: slice saturated/skipped (pass=1 skipped at bands>=320 bands=[320, 640])

### Deal 2

**Pre-Deal**

- digest `53504b310100002804063a2c360835042302310b050515191b11282d0c2b1a2901083b270615342332312400041413121d00022d2400030d0c26040818360a2a28070605040302090002122700093d3c3b3a39383726080003171635131a2233193717013325290b1c22343c3d381b09320a2c1d1839030525140d0116072121112a1c2b`
- primitive depth 39; pass first-seen 0
- fd=14 foundations=0 stock_rows=4 empties=0
- legal=8 tableau A/B/C/D=2/5/0/0
- Deal ordinary tier=3 legal=True

**Deal**

- child digest `53504b310100001e04073a2c360835042302310b0d050615191b11282d0c2b1a290101093b27061534233231241600051413121d0700032d242100040d0c2621040918360a2a280706050403020911000312272a000a3d3c3b3a39383726081c00041716352b131a2233193717013325290b1c22343c3d381b09320a2c1d183903052514`
- post fd=14 foundations=0 stock_rows=3
- matched checkpoint child=True pop=children_exhausted

**Continuation**

- post tableau A/B/C/D=1/3/0/0
- expanded at current pass (direct)=2
- descendants before next Deal=2
- descendants until backtrack=14
- best descendant fd=14 foundations=0
- next Deal reached=True
- post-state suppression: slice saturated/skipped (pass=1 skipped at bands>=320 bands=[320, 640])

### Deal 3

**Pre-Deal**

- digest `53504b310100001e04073a2c360835042302310b0d050615191b11282d0c2b1a290101093b27061534233231241600051413121d0700032d242100040d0c2621040918360a2a280706050403020911000312272a000a3d3c3b3a39383726081c00041716352b131a2233193717013325290b1c22343c3d381b09320a2c1d183903052514`
- primitive depth 40; pass first-seen 0
- fd=14 foundations=0 stock_rows=3 empties=0
- legal=5 tableau A/B/C/D=1/3/0/0
- Deal ordinary tier=3 legal=True

**Deal**

- child digest `53504b310100001404083a2c360835042302310b0d32050715191b11282d0c2b1a29010a010a3b2706153423323124162c00061413121d071d00042d24211800050d0c262139040a18360a2a28070605040302091103000412272a05000b3d3c3b3a39383726081c2500051716352b14131a2233193717013325290b1c22343c3d381b09`
- post fd=14 foundations=0 stock_rows=2
- matched checkpoint child=True pop=children_exhausted

**Continuation**

- post tableau A/B/C/D=0/7/0/0
- expanded at current pass (direct)=1
- descendants before next Deal=2
- descendants until backtrack=12
- best descendant fd=14 foundations=0
- next Deal reached=True
- post-state suppression: slice saturated/skipped (pass=1 skipped at bands>=320 bands=[320, 640])

### Deal 4

**Pre-Deal**

- digest `53504b310100001404083a2c360835042302310b0d32050715191b11282d0c2b1a29010a010a3b2706153423323124162c00061413121d071d00042d24211800050d0c262139040a18360a2a28070605040302091103000412272a05000b3d3c3b3a39383726081c2500051716352b14131a2233193717013325290b1c22343c3d381b09`
- primitive depth 41; pass first-seen 0
- fd=14 foundations=0 stock_rows=2 empties=0
- legal=8 tableau A/B/C/D=0/7/0/0
- Deal ordinary tier=3 legal=True

**Deal**

- child digest `53504b310100000a04093a2c360835042302310b0d3229050815191b11282d0c2b1a29010a0b010b3b2706153423323124162c1c00071413121d071d2200052d2421183400060d0c2621393c040b18360a2a280706050403020911033d000512272a0538000c3d3c3b3a39383726081c251b00061716352b1409131a2233193717013325`
- post fd=14 foundations=0 stock_rows=1
- matched checkpoint child=True pop=children_exhausted

**Continuation**

- post tableau A/B/C/D=2/6/0/0
- expanded at current pass (direct)=3
- descendants before next Deal=2
- descendants until backtrack=11
- best descendant fd=14 foundations=0
- next Deal reached=True
- post-state suppression: slice saturated/skipped (pass=1 skipped at bands>=320 bands=[320, 640])

### Deal 5

**Pre-Deal**

- digest `53504b310100000a04093a2c360835042302310b0d3229050815191b11282d0c2b1a29010a0b010b3b2706153423323124162c1c00071413121d071d2200052d2421183400060d0c2621393c040b18360a2a280706050403020911033d000512272a0538000c3d3c3b3a39383726081c251b00061716352b1409131a2233193717013325`
- primitive depth 42; pass first-seen 0
- fd=14 foundations=0 stock_rows=1 empties=0
- legal=9 tableau A/B/C/D=2/6/0/0
- Deal ordinary tier=3 legal=True

**Deal**

- child digest `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`
- post fd=14 foundations=0 stock_rows=0
- matched checkpoint child=True pop=children_exhausted

**Continuation**

- post tableau A/B/C/D=1/4/0/0
- expanded at current pass (direct)=1
- descendants before next Deal=5
- descendants until backtrack=5
- best descendant fd=14 foundations=0
- next Deal reached=False
- post-state suppression: slice saturated/skipped (pass=1 skipped at bands>=320 bands=[320, 640])

## 4. Legal actions by tier

| Stock remaining | FD | Pass | A legal | B legal | C legal | D legal | Deal tier | Descendants before next boundary |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 14 | 0 | 2 | 5 | 0 | 0 | 3 | 2 |
| 3 | 14 | 0 | 1 | 3 | 0 | 0 | 3 | 2 |
| 2 | 14 | 0 | 0 | 7 | 0 | 0 | 3 | 2 |
| 1 | 14 | 0 | 2 | 6 | 0 | 0 | 3 | 2 |
| 0 | 14 | 0 | 1 | 4 | 0 | 0 | — | 5 |
| 0 | 14 | 0 | 1 | 4 | 0 | 0 | — | terminal |

## 5. Wider-pass lifecycle

| State | Pass 0 | Pass 1 | Pass 2 | Pass 3 | Suppression |
| --- | --- | --- | --- | --- | --- |
| post-Deal 1 fd=14 stock=4 | expanded@452784 rem=281 tt=novel | unseen | unseen | unseen | slice saturated/skipped |
| post-Deal 2 fd=14 stock=3 | expanded@452785 rem=280 tt=novel | unseen | unseen | unseen | slice saturated/skipped |
| post-Deal 3 fd=14 stock=2 | expanded@452786 rem=279 tt=novel | unseen | unseen | unseen | slice saturated/skipped |
| post-Deal 4 fd=14 stock=1 | expanded@452787 rem=278 tt=novel | unseen | unseen | unseen | slice saturated/skipped |
| post-Deal 5 fd=14 stock=0 | expanded@452788 rem=277 tt=novel | unseen | unseen | unseen | slice saturated/skipped |
| terminal fd=14 stock=0 | expanded@452788 rem=277 tt=novel | unseen | unseen | unseen | slice saturated/skipped |
| stock-empty best fd=14 | expanded@452788 rem=277 tt=novel | unseen | unseen | unseen | slice saturated/skipped |

Checkpoint children later reopened at Pass 1/2/3: **0**.
Checkpoint children never widened: **140**.

## 6. Saturation/TT effects

- Search stop reason: `node limit`.
- Saturated passes: [1, 2, 3].
- Slices skipped: 4.
- TT hits=1819094 prunes=1819094 reopens=712625.
- Non-widen reasons across checkpoint Deal children: `{'node budget ended': 130, 'slice saturated/skipped': 10}`.

Slice schedule (expanded / unique_new / skipped):

- band 80 pass 0: expanded=50000 unique_new=47541 skipped=False sat_trig=False stop=budget.
- band 80 pass 1: expanded=50000 unique_new=7441 skipped=False sat_trig=False stop=budget.
- band 80 pass 2: expanded=50000 unique_new=3000 skipped=False sat_trig=False stop=budget.
- band 80 pass 3: expanded=50000 unique_new=44354 skipped=False sat_trig=False stop=budget.
- band 160 pass 0: expanded=50000 unique_new=590 skipped=False sat_trig=False stop=budget.
- band 160 pass 1: expanded=50000 unique_new=0 skipped=False sat_trig=True stop=budget.
- band 160 pass 2: expanded=50000 unique_new=0 skipped=False sat_trig=True stop=budget.
- band 160 pass 3: expanded=50000 unique_new=42701 skipped=False sat_trig=False stop=budget.
- band 320 pass 0: expanded=100000 unique_new=42916 skipped=False sat_trig=False stop=budget.
- band 320 pass 1: expanded=0 unique_new=0 skipped=True sat_trig=False stop=saturated.
- band 320 pass 2: expanded=0 unique_new=0 skipped=True sat_trig=False stop=saturated.
- band 320 pass 3: expanded=100000 unique_new=4591 skipped=False sat_trig=False stop=budget.
- band 640 pass 0: expanded=100000 unique_new=42 skipped=False sat_trig=False stop=budget.
- band 640 pass 1: expanded=0 unique_new=0 skipped=True sat_trig=False stop=saturated.
- band 640 pass 2: expanded=0 unique_new=0 skipped=True sat_trig=False stop=saturated.
- band 640 pass 3: expanded=100000 unique_new=0 skipped=False sat_trig=True stop=budget.
- band 1280 pass 0: expanded=200000 unique_new=93677 skipped=False sat_trig=False stop=budget.

- Post-Deal 1 `53504b310100002804063a2c360835042302310b050515191b11282d0c2b1a2901083b270615342332312400041413121d00022d2400030d0c26040818360a2a28070605040302090002122700093d3c3b3a39383726080003171635131a2233193717013325290b1c22343c3d381b09320a2c1d1839030525140d0116072121112a1c2b`: **slice saturated/skipped** — pass=1 skipped at bands>=320 bands=[320, 640].
- Post-Deal 2 `53504b310100001e04073a2c360835042302310b0d050615191b11282d0c2b1a290101093b27061534233231241600051413121d0700032d242100040d0c2621040918360a2a280706050403020911000312272a000a3d3c3b3a39383726081c00041716352b131a2233193717013325290b1c22343c3d381b09320a2c1d183903052514`: **slice saturated/skipped** — pass=1 skipped at bands>=320 bands=[320, 640].
- Post-Deal 3 `53504b310100001404083a2c360835042302310b0d32050715191b11282d0c2b1a29010a010a3b2706153423323124162c00061413121d071d00042d24211800050d0c262139040a18360a2a28070605040302091103000412272a05000b3d3c3b3a39383726081c2500051716352b14131a2233193717013325290b1c22343c3d381b09`: **slice saturated/skipped** — pass=1 skipped at bands>=320 bands=[320, 640].
- Post-Deal 4 `53504b310100000a04093a2c360835042302310b0d3229050815191b11282d0c2b1a29010a0b010b3b2706153423323124162c1c00071413121d071d2200052d2421183400060d0c2621393c040b18360a2a280706050403020911033d000512272a0538000c3d3c3b3a39383726081c251b00061716352b1409131a2233193717013325`: **slice saturated/skipped** — pass=1 skipped at bands>=320 bands=[320, 640].
- Post-Deal 5 `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`: **slice saturated/skipped** — pass=1 skipped at bands>=320 bands=[320, 640].
- Stock-empty `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`: **slice saturated/skipped** — pass=1 skipped at bands>=320 bands=[320, 640].

## 7. Stock-empty state

- digest `53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`
- depth=43 pass=0 expansion=452788 remaining=277
- fd=14 fu=90 empties=0 foundations=0
- legal tableau A/B/C/D=1/4/0/0
- Deal legal=False
- has Tier-A=True broader=True
- immediate foundation moves=0
- same-suit joins=16 mixed=17
- movable same-suit blocks=0
- longest exposed same-suit run=1
- later Pass 1/2/3: unseen / unseen / unseen

## 8. Foundation proximity

- After Deal 1 (stock=4, fd=14): longest_run=1 adjacencies=16 blocks=0 complete_KA=0 immediate_foundation_moves=0.
- After Deal 2 (stock=3, fd=14): longest_run=1 adjacencies=16 blocks=0 complete_KA=0 immediate_foundation_moves=0.
- After Deal 3 (stock=2, fd=14): longest_run=1 adjacencies=16 blocks=0 complete_KA=0 immediate_foundation_moves=0.
- After Deal 4 (stock=1, fd=14): longest_run=1 adjacencies=16 blocks=0 complete_KA=0 immediate_foundation_moves=0.
- After Deal 5 (stock=0, fd=14): longest_run=1 adjacencies=16 blocks=0 complete_KA=0 immediate_foundation_moves=0.
- Terminal (stock=0, fd=14): longest_run=1 adjacencies=16 blocks=0 complete_KA=0 immediate_foundation_moves=0.

## 9. Aggregate checkpoint continuation

- Checkpoint Deal children entered: **140** (tt-skip 0, total 140).
- Median descendants per entered child: **12.0**.
- Distribution: 0=0 1–10=37 11–100=103 101–1000=0 >1000=0.
- Later revisited in wider passes: **0**.
- Never revisited wider: **140**.
- Max foundations by any checkpoint descendant: **0**.
- Max foundations search-wide: **0**.

Replay-valid best FD by deals completed:

| Deals completed | Best replay-valid FD | Foundations | Depth |
| ---: | ---: | ---: | ---: |
| 0 | 14 | 0 | 36 |
| 1 | 14 | 0 | 39 |
| 2 | 14 | 0 | 40 |
| 3 | 14 | 0 | 41 |
| 4 | 14 | 0 | 42 |
| 5 | 14 | 0 | 43 |

## 10. Dominant blocker

The coupled lineage L_COUPLED_FD14_DEALS5_DEPTH43 is one replay-valid path that holds fd=14 through all five Deals and ends stock-empty at depth 43 with 0 foundations. Every hop is Pass 0. Deal's ordinary tier on this path is D (3), so only the best-reveal probe inserts those Deals. Post-Deal tableaus have B legal moves at every hop (A/B after Deals 1–5 = 2/5, 1/3, 0/7, 2/6, 1/4) and Pass 0 continuation is tiny (median checkpoint descendants 12.0; never >100). Pass 1 is the first pass that would permit those B moves. Band 160 Pass 1 had unique_new=0 and saturated Pass 1; the coupled states were then discovered in Band 320 Pass 0, whose Pass 1 and Pass 2 slices were skipped. Saturated passes=[1, 2, 3]. 0 of 140 checkpoint children later reopened at Pass 1/2/3. Band 320 Pass 3 did run 100k nodes from the root and did not generate these exact children. Stock-empty fd=14 pass=0 A/B/C/D=1/4/0/0 immediate_foundation=False longest_same_suit_run=1 movable_blocks=0. We therefore cannot tell whether broader play would assemble a suit: the good states never received that coverage. Post-Deal A=0 and B>0 hops=[3]; later-widened hops=none. Unique states=286853 matches the v0.5 treatment, so search behaviour is equivalent. Verdict TT_OR_SATURATION_BLOCKS_POST_DEAL_CONTINUATION / hypothesis SATURATION_SCHEDULE_SKIPS_WIDER_CONTINUATION.

## 11. Runtime overhead

| | v0.5 treatment | v0.6 audit |
| --- | ---: | ---: |
| Expanded | 1000000 | 1000000 |
| Unique | 286853 | 286853 |
| States/s | 1016.8 | 995.4 |
| Time s | 983.5 | 1004.6 |
| RSS MiB | 262.16015625 | 254.1171875 |
| Stop | node limit | node limit |

Elapsed ratio vs v0.5: 1.021. Throughput ratio: 0.979.

## 12. Exactly one next recommendation

Do not change Deal scoring and do not add foundation heuristics. Next: keep Pass 1 live on the depth band that first records the coupled post-Deal fd-14 states; do not let unique_new=0 in a shallower band saturate that pass away.

## Integrity

Base SHA `e5982af22f0b98b716feb86e60708f3fee9b15fd`. Deal `deals/4925153.txt`.
Post-deal audit default OFF. Probe default OFF. Engine
`enumerate_legal_actions` / `can_deal(MW_RULES)` remain the Deal authority.
Canonical 4925153 route was not used to guide search. No search-policy change.

