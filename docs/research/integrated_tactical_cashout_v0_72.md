# integrated_tactical_cashout_v0_72

Verdict: `TACTICAL_INTEGRATION_NO_GAIN`

tactical probes added no meaningful additional states

## Architecture

Strategic lanes restored to v0.69/v0.68: COST, REVEAL, CONSTRUCTION, READINESS, HORIZON, ECONOMY, COMPLETION (stock-empty). `readiness_r2`/`readiness_r3` are inactive.

Rows=1 allocation is split 75% strategic / 25% tactical. After ordinary harvest, a small diverse ready-root set is probed with `search_foundation_cashout`. Terminals rejoin the pre-Deal set. Deal-preview and stock-empty assembly are unchanged.

## Envelope

- 900 s / 800,000 unique / 2.5 GiB / width 256 / ceiling 191
- augment fraction = 0.25
- tactical roots cap = 8
- terminals per probe cap = 8

## Search totals

- unique = 94764
- expanded = 22120
- generated = 190710
- elapsed = 900.2338945999509
- stop = time limit
- max F = 2
- solved = False g=None
- lane expansions = {'completion': 269, 'construction': 5495, 'cost': 2933, 'economy': 3594, 'horizon': 1834, 'readiness': 3172, 'reveal': 4361, 'target_access': 215, 'target_assembly': 247}

## Rows=1

- alloc_s = 128.23478764002212 (strategic 96.1760907300166)
- expanded = 698 unique=5599
- max F = 1
- ready roots in harvest = 251
- selected = 8

## Tactical probes

- probes attempted = 7
- producing foundation = 0
- terminals returned = 0 (raw 0)
- unique = 3016 expanded=692
- elapsed_s = 16.038555400038604 of alloc 32.05869691000552

- root_g=88 target=s found=False cheapest_g=None exp=109 t=4.009238699974958
- root_g=6 target=s found=False cheapest_g=None exp=187 t=3.439896499970928
- root_g=6 target=s found=False cheapest_g=None exp=130 t=2.860201200004667
- root_g=6 target=s found=False cheapest_g=None exp=120 t=2.287596400012262
- root_g=6 target=s found=False cheapest_g=None exp=79 t=1.7120914000552148
- root_g=6 target=h found=False cheapest_g=None exp=58 t=1.1374826999963261
- root_g=105 target=d found=False cheapest_g=None exp=9 t=0.5662324000149965

## Best pre-SD5 F2

none

## After-run comparison

- incumbent 192 F2 g = 130
- v0.71 F2 g = 128
- v0.72 best pre-SD5 F2 = None
- same as v0.71 = False
- same as incumbent = False

## Interpretation

tactical probes added no meaningful additional states

## Next recommendation

Increase tactical efficiency or improve tactical root selection rather than widening whole-game runtime.

