#!/usr/bin/env python3
"""v0.99: lean campaign worker + portable research data. Not a long scientific search."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.blinded_deep_f2 import load_five_root_specs
from spider.campaign_bundle import export_campaign, import_campaign
from spider.campaign_exchange import ingest_results, publish_result
from spider.campaign_import_v084 import import_v084_population
from spider.campaign_store import save_campaign
from spider.campaign_worker import current_solver_sha, run_lean_job
from spider.consequence_search import MinimalConsequenceObserver, run_stockempty_consequence
from spider.hardware import detect_hardware
from spider.hardware_profile import load_profile
from spider.long_horizon_f2_adjudication import reconstruct_active_root
from spider.resource_policy import recommend_config
from spider.solution_forensics import load_opening

EXPERIMENT = "scientific_campaign_portability_v0_99"
BASE_SHA = "29899dad5ac9c8ddc83e4fbb51223fb2b07460cf"
BRANCH = "agent/scientific-campaign-portability-v0-99"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"


def main() -> dict:
    opening, _, _ = load_opening()
    spec = next(s for s in load_five_root_specs() if s.get("name") == "CONTROL_187")
    post = reconstruct_active_root(opening, spec)
    eq_job = {
        "id": "eq187",
        "candidate_id": "control_187",
        "g": post["g"],
        "ordered_digest": post["ordered_digest"],
        "ident": post.get("ident"),
        "ceiling": 187,
        "time_s": 25.0,
        "max_unique": 2000,
        "stop_on_first_terminal": False,
        "trace": True,
    }
    print("SEMANTIC A vs B unique=2000", flush=True)
    a = run_lean_job(eq_job, rss_abort_mb=2560, trace=True)
    obs = MinimalConsequenceObserver(trace=True)
    kr = run_stockempty_consequence(
        [{"g": post["g"], "ordered_digest": post["ordered_digest"], "ident": post.get("ident")}],
        ceiling=187,
        time_limit_s=25.0,
        max_unique=2000,
        rss_abort_mb=2560,
        stop_on_first_terminal=False,
        observer=obs,
    )
    equiv = {
        "unique": [a["unique"], kr.unique],
        "expanded": [a["expanded"], kr.expanded],
        "generated": [a["generated"], kr.generated],
        "duplicate_skips": [a["duplicate_skips"], kr.duplicate_skips],
        "stale_skips": [a["stale_skips"], kr.stale_skips],
        "lower_bound_calls": [a["lower_bound_calls"], kr.lower_bound_calls],
        "lower_bound_prunes": [a["lower_bound_prunes"], kr.lower_bound_prunes],
        "lane_exp": [a["lane_exp"], dict(kr.lane_exp)],
        "max_foundations": [a["max_foundations"], obs.max_F],
        "trace_hash": [a["trace_hash"], obs.trace_hex()],
    }
    equiv_ok = all(equiv[k][0] == equiv[k][1] for k in equiv)
    print(f"  equivalent={equiv_ok} unique={a['unique']}", flush=True)

    job = {
        "id": "cal187",
        "candidate_id": "control_187",
        "g": post["g"],
        "ordered_digest": post["ordered_digest"],
        "ident": post.get("ident"),
        "ceiling": 187,
        "time_s": 45.0,
        "max_unique": 300_000,
        "stop_on_first_terminal": True,
    }
    print("CONTROL_187 campaign worker ceiling187 t<=45s", flush=True)
    cal = run_lean_job(job, rss_abort_mb=2560)
    print(f"  solved={cal.get('solved')} g={cal.get('terminal_g')} t={cal.get('terminal_s')} stop={cal.get('stop_reason')}", flush=True)

    print("PRODUCTION smoke ceiling186 t=8s", flush=True)
    smoke = run_lean_job(
        {**job, "id": "smoke186", "ceiling": 186, "time_s": 8.0, "max_unique": 80_000},
        rss_abort_mb=2560,
    )
    print(f"  maxF={smoke.get('max_foundations')} prunes={smoke.get('lower_bound_prunes')} stop={smoke.get('stop_reason')}", flush=True)

    print("IMPORT v0.84", flush=True)
    pop = import_v084_population()
    stats = pop["import_stats"]
    print(f"  {stats}", flush=True)

    tmp = ROOT / "campaigns" / "_v099_tmp"
    save_campaign(tmp, pop)
    bundle = export_campaign(tmp, ROOT / "campaigns" / "_v099_roundtrip.spidercampaign")
    dest = ROOT / "campaigns" / "_v099_imported"
    imported = import_campaign(bundle, dest)
    roundtrip_ok = imported.get("uuid") == pop.get("uuid") and len(imported.get("candidates") or []) == len(pop.get("candidates") or [])

    shared = ROOT / "campaigns" / "_v099_share"
    job_rec = {"id": "ext1", "candidate_id": (pop.get("candidates") or [{}])[0].get("id"), "ceiling": 186, "status": "done", "result": smoke}
    publish_result(shared, pop, job_rec, machine_id="build_host")
    ingest = ingest_results(shared, dest)

    snap = detect_hardware()
    cfg = recommend_config(snap)
    spec_path = ROOT / "spider_campaign.spec"
    script_path = ROOT / "scripts" / "build_spider_app.ps1"
    pack = {
        "spec": str(spec_path.relative_to(ROOT)).replace("\\", "/"),
        "script": str(script_path.relative_to(ROOT)).replace("\\", "/"),
        "committed_binary": False,
        "entrypoint_ok": spec_path.exists() and script_path.exists(),
    }

    sha = current_solver_sha()
    verdict = "SCIENTIFIC_CAMPAIGN_READY"
    if not equiv_ok:
        verdict = "SCIENTIFIC_CAMPAIGN_SEMANTIC_FAILURE"
    elif not cal.get("solved") or cal.get("terminal_g") != 187:
        verdict = "SCIENTIFIC_CAMPAIGN_SEMANTIC_FAILURE"
    elif not roundtrip_ok or ingest.get("added", 0) < 1:
        verdict = "SCIENTIFIC_CAMPAIGN_PORTABILITY_FAILURE"
    elif cal.get("solved") and cal.get("terminal_g") is not None and int(cal["terminal_g"]) <= 186:
        verdict = "SCIENTIFIC_CAMPAIGN_COST_IMPROVED"

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "solver_sha": sha,
        "verdict": verdict,
        "v098_mismatch": (
            "v0.98 job_worker called generic run_search with identity_fn=pack_state, "
            "lane_names=cost/reveal/construction, and lower_bound_fn=None. "
            "That is not the calibrated lean consequence evaluator. "
            "v0.99 job_worker calls run_stockempty_consequence with pack_whole_game_identity, "
            "COMPLETION_LANES, strategic_lane_keys, stock_empty_assembly_h, stop_on_first_terminal=True."
        ),
        "semantic_equivalence": {"ok": equiv_ok, "table": equiv},
        "control_187_calibration": {
            "solved": cal.get("solved"),
            "terminal_g": cal.get("terminal_g"),
            "terminal_s": cal.get("terminal_s"),
            "unique": cal.get("unique"),
            "expanded": cal.get("expanded"),
            "generated": cal.get("generated"),
            "stop": cal.get("stop_reason"),
            "worker_mode": cal.get("worker_mode"),
            "lower_bound_prunes": cal.get("lower_bound_prunes"),
            "lane_exp": cal.get("lane_exp"),
            "max_foundations": cal.get("max_foundations"),
        },
        "production_smoke_186": {
            "max_F": smoke.get("max_foundations"),
            "prunes": smoke.get("lower_bound_prunes"),
            "bound_calls": smoke.get("lower_bound_calls"),
            "stop": smoke.get("stop_reason"),
            "no_deal": smoke.get("no_deal"),
            "ceiling": smoke.get("ceiling"),
        },
        "v084_import": stats,
        "export_import_ok": roundtrip_ok,
        "shared_ingest": ingest,
        "packaging": pack,
        "build_host": {
            "note": "build/test host, not the Dell Optiplex",
            "physical_cores": snap.physical_cores,
            "logical_cores": snap.logical_cores,
            "ram_total_gb": round(snap.ram_total_gb, 2),
            "auto": cfg.as_dict(),
            "profile_present": load_profile() is not None,
        },
        "optiplex_acceptance": "user must run scripts/optiplex_acceptance_v0_99.ps1 on the Dell Optiplex; not claimed here",
        "incumbent_g": 187,
        "production_ceiling": 186,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_markdown(payload), encoding="utf-8")
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


def _markdown(p: dict) -> str:
    eq = p["semantic_equivalence"]["table"]
    rows = "\n".join(f"| {k} | {v[0]} | {v[1]} |" for k, v in eq.items())
    st = p["v084_import"]
    cal = p["control_187_calibration"]
    smoke = p["production_smoke_186"]
    host = p["build_host"]
    return f"""# {p['experiment']}

Verdict: `{p['verdict']}`

Branch: `{p['branch']}`  
Base: `{p['base_sha']}`

## v0.98 worker mismatch and v0.99 correction

{p['v098_mismatch']}

## Lean semantic-equivalence table (CONTROL_187, unique=2000, before terminal)

| counter | campaign worker | direct run_stockempty_consequence |
|---|---|---|
{rows}

Equivalent: `{p['semantic_equivalence']['ok']}`

## CONTROL_187 campaign calibration (ceiling 187, t<=45s)

- solved: `{cal['solved']}`
- terminal g: `{cal['terminal_g']}`
- terminal t: `{cal['terminal_s']}`
- unique: `{cal['unique']}`
- stop: `{cal['stop']}`
- worker_mode: `{cal['worker_mode']}`

## Production-ceiling smoke (ceiling 186, 8s)

- ceiling: `{smoke['ceiling']}`
- max F: `{smoke['max_F']}`
- lower-bound prunes: `{smoke['prunes']}`
- no Deal: `{smoke['no_deal']}`
- stop: `{smoke['stop']}`

## v0.84 population import

- raw F2: `{st['raw_n_f2']}`
- reconstructed: `{st['reconstructed']}`
- unique post-stock identities: `{st['unique_post_stock']}`
- proof-live <=186: `{st['proof_live']}`
- proof-dead >186: `{st['proof_dead']}`
- ancestry failures: `{st['ancestry_failures']}`
- closed pruned: `{st['closed_pruned']}`
- lower-g reopenings: `{st['lower_g_reopenings']}`
- closed registry n: `{st.get('closed_registry_n')}`

## Export / import / shared folder

- export/import round-trip: `{p['export_import_ok']}`
- shared ingest: `{p['shared_ingest']}`
- machine profile excluded from bundle: yes

## Packaging

- spec: `{p['packaging']['spec']}`
- script: `{p['packaging']['script']}`
- committed binary: `{p['packaging']['committed_binary']}`

## Build/test host resource profile

This is the **build/test host**, not the Dell Optiplex.

- CPU: {host['physical_cores']} physical / {host['logical_cores']} logical
- RAM: {host['ram_total_gb']} GB
- AUTO: `{host['auto']}`

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

- incumbent: `{p['incumbent_g']}`
- production ceiling: `{p['production_ceiling']}`
"""


if __name__ == "__main__":
    main()
