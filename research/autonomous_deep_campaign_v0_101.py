#!/usr/bin/env python3
"""v0.101: incumbent registry, packaged 186, progressive deepen, autonomous smoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.campaign_autonomous import run_autonomous_campaign
from spider.campaign_schedule import next_round_for_node
from spider.campaign_store import load_campaign, new_campaign, save_campaign
from spider.hardware import detect_hardware
from spider.incumbent import current_incumbent_g, incumbent_moves_path, load_incumbent, production_ceiling
from spider.metrics import parse_moves_file, replay_actions
from spider.resource_policy import recommend_config
from spider.whole_game_anytime import opening_state

EXPERIMENT = "autonomous_deep_campaign_v0_101"
BASE_SHA = "dcde6bc20ba898c45c37ac102c72e9326f33331d"
BRANCH = "agent/autonomous-deep-campaign-v0-101"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"


def main() -> dict:
    rec = load_incumbent()
    g = replay_actions(opening_state().clone(), parse_moves_file(incumbent_moves_path()))
    rounds = [
        next_round_for_node({"deepest_budget_s": t})["round"]
        for t in (0, 60, 300, 1800, 7200, 28800, 86400)
    ]
    spec = (ROOT / "spider_campaign.spec").read_text(encoding="utf-8")
    packaged = "solutions/4925153_incumbent.json" in spec and "solutions/4925153_autonomous_v0_100.moves" in spec
    print("INCUMBENT", rec["incumbent_g"], rec["production_ceiling"], "replay", g, flush=True)
    print("ROUNDS", rounds, flush=True)
    folder = ROOT / "campaigns" / "_v101_smoke"
    save_campaign(folder, new_campaign())
    cfg = recommend_config(detect_hardware())
    print("AUTONOMOUS SMOKE", flush=True)
    smoke = run_autonomous_campaign(folder, cfg, profile="SMOKE")
    print(f"  {smoke}", flush=True)
    data = load_campaign(folder)
    snap = detect_hardware()
    ok = (
        rec["incumbent_g"] == 186
        and rec["production_ceiling"] == 185
        and g == 186
        and rounds == [1, 2, 3, 4, 5, 6, 7]
        and packaged
        and smoke.get("nodes", 0) >= 2
        and data.get("g123_id")
    )
    verdict = "AUTONOMOUS_DEEP_CAMPAIGN_READY" if ok else "AUTONOMOUS_DEEP_CAMPAIGN_CONTRACT_FAILURE"
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "incumbent": rec,
        "replay_g": g,
        "next_rounds": rounds,
        "packaged_incumbent": packaged,
        "autonomous_smoke": smoke,
        "build_host_note": "build/test host, not the Dell Optiplex",
        "build_host": {
            "physical_cores": snap.physical_cores,
            "logical_cores": snap.logical_cores,
            "ram_total_gb": round(snap.ram_total_gb, 2),
        },
        "incumbent_g": rec["incumbent_g"],
        "production_ceiling": rec["production_ceiling"],
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(
        f"# {EXPERIMENT}\n\nVerdict: `{verdict}`\n\n"
        f"Incumbent registry: g={rec['incumbent_g']} ceiling={rec['production_ceiling']} "
        f"moves={rec['moves_path']} replay_g={g}.\n\n"
        f"Deepening next rounds from budgets 0/60/300/1800/7200/28800/86400: {rounds}.\n\n"
        f"Packaged incumbent+v0.100 solution in spider_campaign.spec: {packaged}.\n\n"
        f"Autonomous SMOKE: {smoke}.\n\n"
        "Start on the Optiplex with Create Known g123 Campaign, profile DEEP or OVERNIGHT, then Start.\n",
        encoding="utf-8",
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
