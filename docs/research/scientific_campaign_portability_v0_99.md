# scientific_campaign_portability_v0_99

Verdict: `SCIENTIFIC_CAMPAIGN_READY`

Branch: `agent/scientific-campaign-portability-v0-99`  
Base: `29899dad5ac9c8ddc83e4fbb51223fb2b07460cf`

## v0.98 worker mismatch and v0.99 correction

v0.98 job_worker called generic run_search with identity_fn=pack_state, lane_names=cost/reveal/construction, and lower_bound_fn=None. That is not the calibrated lean consequence evaluator. v0.99 job_worker calls run_stockempty_consequence with pack_whole_game_identity, COMPLETION_LANES, strategic_lane_keys, stock_empty_assembly_h, stop_on_first_terminal=True.

## Lean semantic-equivalence table (CONTROL_187, unique=2000, before terminal)

| counter | campaign worker | direct run_stockempty_consequence |
|---|---|---|
| unique | 2000 | 2000 |
| expanded | 160 | 160 |
| generated | 3656 | 3656 |
| duplicate_skips | 1639 | 1639 |
| stale_skips | 47 | 47 |
| lower_bound_calls | 2017 | 2017 |
| lower_bound_prunes | 142 | 142 |
| lane_exp | {'cost': 19, 'reveal': 34, 'construction': 35, 'readiness': 34, 'horizon': 0, 'economy': 14, 'completion': 24} | {'cost': 19, 'reveal': 34, 'construction': 35, 'readiness': 34, 'horizon': 0, 'economy': 14, 'completion': 24} |
| max_foundations | 2 | 2 |
| trace_hash | dd9be99423b170214b8b7e0d9c836505af955364c27c9f2f5740e4c0834d4708 | dd9be99423b170214b8b7e0d9c836505af955364c27c9f2f5740e4c0834d4708 |

Equivalent: `True`

## CONTROL_187 campaign calibration (ceiling 187, t<=45s)

- solved: `True`
- terminal g: `187`
- terminal t: `27.69185909999942`
- unique: `8290`
- stop: `solved`
- worker_mode: `LEAN_CONSEQUENCE`

## Production-ceiling smoke (ceiling 186, 8s)

- ceiling: `186`
- max F: `2`
- lower-bound prunes: `71`
- no Deal: `True`
- stop: `time limit`

## v0.84 population import

- raw F2 (artefact count): `279`
- persisted reconstructable pre-SD5 states: `56` (the JSON did not retain all 279 harvest terminals)
- reconstructed: `56`
- unique post-stock identities: `56`
- proof-live <=186: `56`
- proof-dead >186: `0`
- ancestry failures: `0`
- closed pruned: `0`
- lower-g reopenings: `0`
- closed registry n: `30`

## Export / import / shared folder

- export/import round-trip: `True`
- shared ingest: added=1, second sync skipped=1, conflicts=0 (idempotent)
- machine profile excluded from bundle: yes
- architecture: local live campaign + immutable `exchange/<uuid>/<machine_id>/` packages

## Campaign result schema

Persisted job results include solver SHA/version, candidate ID, starting g/h/f, ceiling, wall time, max unique, RSS cap, unique/expanded/generated, duplicate/stale skips, lower-bound calls/prunes, lane expansions, max foundation, first/cheapest/lowest-f milestones, terminal g/time/path, stop reason, machine ID as provenance only, and timestamp.

Candidates persist post-stock digest, absolute g, physical identity, full_actions when present, otherwise an immutable v0.84 g123 prefix artefact reference, source experiment, source candidate ID, and deal count.

## Packaging

- spec: `spider_campaign.spec`
- script: `scripts/build_spider_app.ps1`
- PyInstaller 6.22.3 one-folder build succeeded on the build/test host
- exe: `dist/SpiderCampaign/SpiderCampaign.exe` (not committed)

## Build/test host resource profile

This is the **build/test host**, not the Dell Optiplex.

- CPU: 8 physical / 8 logical
- RAM: 15.88 GB
- AUTO: `{'mode': 'AUTO', 'workers': 1, 'per_worker_rss_mb': 2560.0, 'global_ram_limit_gb': 10.88, 'max_unique': 300000, 'notes': 'AUTO from 8p/8l 16GB; disk speed unused'}`

## Actual Optiplex acceptance

Do **not** treat this Build run as Optiplex acceptance.

On the Dell Optiplex, run `scripts/optiplex_acceptance_v0_99.ps1` and then:

1. Launch the app (`run_campaign_gui.bat` or `dist/SpiderCampaign/SpiderCampaign.exe`).
2. Confirm hardware detection.
3. Run ~15s Recalibrate.
4. Confirm AUTO workers / RSS / global RAM.
5. Confirm CONTROL_187 scientific calibration passes.
6. New Campaign, Import v0.84 F2s.
7. Start 2–3 short jobs.
8. Pause after current job.
9. Close.
10. Reopen.
11. Resume — completed work must remain completed.
12. Export Campaign.
13. Import the `.spidercampaign` into a new local folder.
14. Verify completed work and ancestry are intact; `hardware_profile.json` is absent from the bundle.

## Incumbent / ceiling

- incumbent: `187`
- production ceiling: `186`
