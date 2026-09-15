#!/usr/bin/env python3
"""v0.100: verify autonomous 186 and smoke the hierarchical campaign. Not a long search."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.campaign_bundle import export_campaign, import_campaign
from spider.campaign_expand import (
    create_g123_campaign,
    create_opening_campaign,
    expand_node,
    expand_sd5_child,
)
from spider.campaign_nodes import get_node
from spider.campaign_status import classify_outcome
from spider.campaign_store import new_campaign, save_campaign
from spider.recover_autonomous_186 import recover_and_verify
from spider.hardware import detect_hardware

EXPERIMENT = "hierarchical_deep_campaign_v0_100"
BASE_SHA = "1a5a765ced06a01fdfa3ceb7f29659b6800e1c80"
BRANCH = "agent/hierarchical-deep-campaign-v0-100"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"


def _smoke_hierarchy() -> dict:
    camp = new_campaign(incumbent_g=187, ceiling=186)
    opening = create_opening_campaign(camp)
    g123_camp = new_campaign(incumbent_g=187, ceiling=186)
    g123 = create_g123_campaign(g123_camp)
    f2s = expand_node(g123_camp, g123, time_s=12.0, max_unique=12_000, suit="d")
    sd5 = None
    children = [get_node(g123_camp, cid) for cid in f2s.get("children") or []]
    pre = next((c for c in children if c and int(c.get("stock_rows") or 0) == 1), None)
    if pre is not None:
        sd5 = expand_sd5_child(g123_camp, pre)
    opening_kids = expand_node(camp, opening, time_s=2.5, max_unique=800)
    tmp = ROOT / "campaigns" / "_v100_graph"
    save_campaign(tmp, g123_camp)
    bundle = export_campaign(tmp, ROOT / "campaigns" / "_v100_graph.spidercampaign")
    dest = ROOT / "campaigns" / "_v100_imported"
    imported = import_campaign(bundle, dest)
    timeout = classify_outcome({"stop_reason": "time limit", "solved": False}, ceiling=186, assembly_f=171)
    return {
        "opening_id": opening.get("id"),
        "opening_g": opening.get("g"),
        "opening_actions": opening.get("full_actions"),
        "opening_children": opening_kids.get("n_children"),
        "g123_ok": g123.get("ancestry_verified"),
        "g123_g": g123.get("g"),
        "g123_n_deal": g123.get("n_deal"),
        "f2_children": f2s.get("n_children"),
        "sd5_child": None if sd5 is None else sd5.get("kind"),
        "graph_roundtrip": imported.get("uuid") == g123_camp.get("uuid") and len(imported.get("nodes") or []) == len(g123_camp.get("nodes") or []),
        "timeout_status": timeout,
        "n_nodes": len(g123_camp.get("nodes") or []),
        "n_edges": len(g123_camp.get("edges") or []),
    }


def main() -> dict:
    print("RECOVER 186", flush=True)
    rec = recover_and_verify()
    print(
        f"  ok={rec.get('ok')} foundA={rec.get('winner_a_recovered')} foundB={rec.get('winner_b_recovered')} "
        f"incumbent={rec.get('incumbent_after')} ceiling={rec.get('ceiling_after')}",
        flush=True,
    )
    print("HIERARCHY SMOKE", flush=True)
    smoke = _smoke_hierarchy()
    print(f"  { {k: smoke[k] for k in smoke if k != 'opening_actions'} }", flush=True)

    if rec.get("ok") and smoke.get("graph_roundtrip") and smoke.get("timeout_status") == "UNRESOLVED_TIME":
        verdict = "HIERARCHICAL_CAMPAIGN_186_VERIFIED"
    elif rec.get("ok"):
        verdict = "AUTONOMOUS_186_RECOVERY_ONLY"
    elif smoke.get("g123_ok") and smoke.get("graph_roundtrip"):
        verdict = "HIERARCHICAL_CAMPAIGN_READY"
    else:
        verdict = "HIERARCHICAL_CAMPAIGN_CONTRACT_FAILURE"

    snap = detect_hardware()
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "recovery": rec,
        "hierarchy_smoke": smoke,
        "build_host_note": "build/test host, not the Dell Optiplex",
        "build_host": {"physical_cores": snap.physical_cores, "logical_cores": snap.logical_cores, "ram_total_gb": round(snap.ram_total_gb, 2)},
        "incumbent_g": rec.get("incumbent_after"),
        "production_ceiling": rec.get("ceiling_after"),
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_md(payload), encoding="utf-8")
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


def _md(p: dict) -> str:
    rec = p.get("recovery") or {}
    sm = p.get("hierarchy_smoke") or {}
    v = rec.get("verified") or {}
    rp = (v.get("replay") or {})
    return f"""# {p['experiment']}

Verdict: `{p['verdict']}`

Branch: `{p['branch']}`
Base: `{p['base_sha']}`

## 186 recovery

- winner A recovered: `{rec.get('winner_a_recovered')}`
- winner B recovered: `{rec.get('winner_b_recovered')}`
- verified winner: `{v.get('winner')}`
- harvest: `{rec.get('harvest')}`
- g123: `{rec.get('g123')}`
- full replay g: `{rp.get('g')}`
- deals: `{rp.get('n_deal')}`
- foundations: `{rp.get('foundations')}`
- solved: `{rp.get('solved')}`
- incumbent before/after: 187 / `{p.get('incumbent_g')}`
- production ceiling before/after: 186 / `{p.get('production_ceiling')}`

## Architecture smoke

- opening root g=0 empty actions: `{sm.get('opening_g')} {sm.get('opening_actions')}`
- opening children: `{sm.get('opening_children')}`
- g123 verified: `{sm.get('g123_ok')} g={sm.get('g123_g')} deals={sm.get('g123_n_deal')}`
- F2 children: `{sm.get('f2_children')}`
- SD5 child: `{sm.get('sd5_child')}`
- graph export/import: `{sm.get('graph_roundtrip')}`
- timeout classification: `{sm.get('timeout_status')}`

Timeout is UNRESOLVED_TIME, never PROOF_DEAD.

## Optiplex next campaign

On the Dell Optiplex: Create Known g123 Campaign, Generate Children (diamonds),
exact SD5, then Deepen All Unresolved with Round 2+ budgets. Do not treat
Round-1 60s timeouts as dead states.
"""


if __name__ == "__main__":
    main()
