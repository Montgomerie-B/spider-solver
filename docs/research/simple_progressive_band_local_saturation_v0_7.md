# Simple Progressive Search v0.7: Band-Local Saturation

## 1. Verdict

`BAND_LOCAL_SATURATION_CAUSES_STATE_EXPLOSION` — deeper-band slices spent their budget reopening shallower coverage and never generated the fd-14 coupled states.

## 2. Saturation contract before/after

Before (control, v0.3–v0.6): a pass with `unique_new=0` is saturated
globally. Later depth bands skip that pass.

After (treatment): saturation is keyed by `(depth_band, pass)`. A zero-novel
slice at band 160 Pass 1 saturates only that cell. Band 320 Pass 1 is
schedulable again. Depth-aware TT is not cleared.

Control slices skipped=4 saturated_passes=[1, 2, 3].
Treatment slices skipped=0 saturated_band_passes=[{'band': 160, 'pass': 1}, {'band': 160, 'pass': 2}, {'band': 320, 'pass': 0}, {'band': 320, 'pass': 1}, {'band': 320, 'pass': 2}, {'band': 640, 'pass': 0}, {'band': 640, 'pass': 1}, {'band': 640, 'pass': 2}, {'band': 640, 'pass': 3}, {'band': 1280, 'pass': 0}, {'band': 1280, 'pass': 1}, {'band': 1280, 'pass': 2}, {'band': 1280, 'pass': 3}].

## 3. Control reproduction

- nodes=1000000 unique=286853 deals=16065 fnd=0 stop=node limit.
- Best FD by deals: 0=14, 1=14, 2=14, 3=14, 4=14, 5=14.
- Band 320 Pass 1: {'band': 320, 'budget_redirected': 33333, 'depth_prunes': 0, 'expanded': 0, 'pass': 1, 'reopens': 0, 'saturation_inherited': True, 'saturation_triggered': False, 'scheduled': False, 'skipped': True, 'stop': 'saturated', 'tt_hits': 0, 'unique_new': 0}.
- Checkpoint later Pass 1/2/3: 0/0/0.

## 4. Band/pass scheduling

| Band | Pass | Control scheduled | Treatment scheduled | Control unique_new | Treatment unique_new | Treatment inherited |
| ---: | ---: | --- | --- | ---: | ---: | --- |
| 80 | 0 | True | True | 47541 | 47541 | False |
| 80 | 1 | True | True | 7441 | 7441 | False |
| 80 | 2 | True | True | 3000 | 3000 | False |
| 80 | 3 | True | True | 44354 | 44354 | False |
| 160 | 0 | True | True | 590 | 590 | False |
| 160 | 1 | True | True | 0 | 0 | False |
| 160 | 2 | True | True | 0 | 0 | False |
| 160 | 3 | True | True | 42701 | 42701 | False |
| 320 | 0 | True | True | 42916 | 0 | False |
| 320 | 1 | False | True | 0 | 0 | False |
| 320 | 2 | False | True | 0 | 0 | False |
| 320 | 3 | True | True | 4591 | 2102 | False |
| 640 | 0 | True | True | 42 | 0 | False |
| 640 | 1 | False | True | 0 | 0 | False |
| 640 | 2 | False | True | 0 | 0 | False |
| 640 | 3 | True | True | 0 | 0 | False |
| 1280 | 0 | True | True | 93677 | 0 | False |
| 1280 | 1 | — | True | — | 0 | False |
| 1280 | 2 | — | True | — | 0 | False |
| 1280 | 3 | — | True | — | 0 | False |

## 5. TT interaction

- Control TT hits=1819094 prunes=1819094 reopens=712625.
- Treatment TT hits=1861595 prunes=1861595 reopens=851749.
- Treatment does not clear TT. Deeper remaining-depth still reopens; equal or
  shallower remaining-depth is still pruned.

## 6. Checkpoint wider coverage

| | Control | Treatment |
| --- | ---: | ---: |
| Checkpoint children | 140 | 130 |
| Pass 0 only | 140 | 130 |
| Later Pass 1 | 0 | 0 |
| Later Pass 2 | 0 | 0 |
| Later Pass 3 | 0 | 0 |
| First broader @320 | None | None |
| First broader @640 | None | None |
| First broader @1280 | None | None |

## 7. fd-14 stock-empty lifecycle

- digest `53504b3101000000040a3a2c360835042332310b0d322913050915191b11282d0c2b1a29010a0b1a01093b2706153424162c1c22020631122d1d071d22330008141312242118341900070d0c2621393c37040c18360a2a280706050403020911033d1700071716272a05380100072302081c251b33000d3d3c3b3a39383726352b140925`
- fd=16 depth=38 pass=0
- A/B/C/D=1/4/0/0
- longest run=1 adjacencies=16 foundations=0
- Pass 1/2/3 expanded: False/False/False
- suppression: node budget ended (wider_slice_ran_but_state_not_reached later_slice_expansions=750000 stop=node limit first_band=80)
- v0.6 fd-14 coupled keys seen in treatment: 0/6.

Tier-B children from stock-empty at Pass 1+:

- none recorded.

## 8. Coupled progress

| Deals completed | Best FD control | Best FD treatment | Fnd control | Fnd treatment |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 14 | 16 | 0 | 0 |
| 1 | 14 | 16 | 0 | 0 |
| 2 | 14 | 16 | 0 | 0 |
| 3 | 14 | 16 | 0 | 0 |
| 4 | 14 | 16 | 0 | 0 |
| 5 | 14 | 16 | 0 | 0 |

## 9. Foundation result

Control foundations=0; treatment=0; first treatment node=None.
No replay-valid foundation.

## 10. Complete solution result

No complete solution.

## 11. Runtime/coverage trade-off

| | Control | Treatment |
| --- | ---: | ---: |
| Expanded | 1000000 | 1000000 |
| Unique | 286853 | 147729 |
| Unique/exp | 0.2869 | 0.1477 |
| States/s | 986.5 | 850.4 |
| TT hits | 1819094 | 1861595 |
| Reopens | 712625 | 851749 |
| Max depth | 365 | 356 |
| Deals | 16065 | 16058 |
| RSS MiB | 251.921875 | 252.1796875 |
| Time s | 1013.7 | 1175.9 |

## 12. Exactly one next recommendation

Keep band-local saturation as the correct contract and keep the probe. Do not restore cross-band saturation. Next: stop deeper-band slices from spending their node budget reopening shallower remaining-depth coverage before they can generate the fd-14 coupled states.

## Integrity

Control band 320 Pass 1 skipped=True inherited=True expanded=0. Treatment band 320 Pass 1 scheduled=True skipped=False inherited=False expanded=50000 unique_new=0 reopens=50000. Checkpoint later Pass 1/2/3 control=0/0/0 treatment=0/0/0. Seeded coupled states widened=False. Stock-empty fd=16 pass=0 A/B/C/D=1/4/0/0 Tier-B children recorded=0 expanded=0. Max foundations control=0 treatment=0. Verdict BAND_LOCAL_SATURATION_CAUSES_STATE_EXPLOSION.

Base SHA `bcb2d872fbcbc7b790645a269bc4d79eb463a0b8`. Deal `deals/4925153.txt`.
Probe ON both arms. Band-local saturation default OFF. Engine
`enumerate_legal_actions` / `can_deal(MW_RULES)` remain the Deal authority.
No post-Deal service, Deal preparation, or foundation heuristic was added.

