"""v0.95 blinded lean consequence evaluation of five existing F2 roots.

Search receives only state, g, and ceiling. Labels are attached after freeze.
Canonical 172 is not read. The 187 suffix is not used as search guidance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.consequence_search import MinimalConsequenceObserver, run_stockempty_consequence
from spider.long_horizon_f2_adjudication import (
    identify_controls,
    load_v084_population,
    reconstruct_active_root,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import stock_rows, tableau_actions
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB

ROOT = Path(__file__).resolve().parents[2]
V092_JSON = ROOT / "docs" / "research" / "long_horizon_f2_adjudication_v0_92.json"
V094_RESULT = ROOT / "docs" / "research" / "lean_consequence_evaluator_v0_94.json"
V094_PROGRESS = ROOT / "docs" / "research" / "lean_consequence_evaluator_progress_v0_94.json"
V094_REPORT = ROOT / "docs" / "research" / "lean_consequence_evaluator_v0_94.md"

STAGE_A_S = 30.0
STAGE_A_CEILING = 186
STAGE_A_UNIQUE = 300_000
STAGE_B_S = 45.0
STAGE_B_CEILING = 187
STAGE_B_UNIQUE = 300_000
STAGE_C_S = 180.0
STAGE_C_CEILING = 186
STAGE_C_UNIQUE = 800_000
STAGE_C_N = 1
ROOT_NAMES = ("CONTROL_187", "CONTROL_ROOT_A", "NOVEL_A", "NOVEL_B", "NOVEL_C")


def load_v092_named_root(name: str) -> dict:
    data = json.loads(V092_JSON.read_text(encoding="utf-8"))
    for rec in data.get("active_roots") or []:
        if rec.get("name") == name:
            return dict(rec)
    freeze = data.get("selection_freeze") or {}
    if name in freeze:
        rec = dict(freeze[name])
        rec["name"] = name
        return rec
    raise KeyError(name)


def load_five_root_specs() -> List[dict]:
    """Bookkeeping identities only. Not search inputs."""

    specs = []
    specs.append(load_v092_named_root("CONTROL_187"))
    pop = load_v084_population()
    ctrls = identify_controls(pop)
    a = dict(ctrls["control_root_a"])
    a["name"] = "CONTROL_ROOT_A"
    specs.append(a)
    for name in ("NOVEL_A", "NOVEL_B", "NOVEL_C"):
        specs.append(load_v092_named_root(name))
    return specs


def search_spec(post: dict) -> dict:
    """Strip labels so search policy cannot see root names."""

    return {
        "g": int(post.get("g") or post.get("post_g")),
        "ordered_digest": post.get("ordered_digest") or post.get("post_digest"),
    }


def run_blinded_lean(post: dict, *, ceiling: int, time_s: float, max_unique: int):
    spec = search_spec(post)
    obs = MinimalConsequenceObserver()
    kr = run_stockempty_consequence(
        [spec],
        ceiling=int(ceiling),
        time_limit_s=float(time_s),
        max_unique=int(max_unique),
        rss_abort_mb=SEARCH_RSS_MB,
        stop_on_first_terminal=True,
        observer=obs,
    )
    return kr, obs


def classify_root(stage_a: dict, stage_b: dict) -> str:
    if stage_a.get("solved") and stage_a.get("terminal_g") is not None and int(stage_a["terminal_g"]) <= 186:
        return "CLASS_186"
    if stage_b.get("solved") and stage_b.get("terminal_g") is not None and int(stage_b["terminal_g"]) == 187:
        return "CLASS_187"
    return "UNRESOLVED_187"


def select_stage_c(rows: Sequence[dict]) -> Optional[dict]:
    novels = [r for r in rows if str(r.get("name") or "").startswith("NOVEL_")]
    qualify = [
        r
        for r in novels
        if r.get("cls") == "CLASS_187" and not (r.get("stage_a") or {}).get("solved")
    ]
    if qualify:
        return min(
            qualify,
            key=lambda r: (
                int((r.get("stage_b") or {}).get("unique") or 10**9),
                int(r.get("start_g") or 10**9),
                int(r.get("start_f") or 10**9),
                r.get("post_digest") or "",
            ),
        )
    deep = [
        r
        for r in novels
        if r.get("cls") == "UNRESOLVED_187" and int((r.get("stage_b") or {}).get("max_F") or 0) >= 5
    ]
    if not deep:
        return None
    return max(deep, key=lambda r: (int((r.get("stage_b") or {}).get("max_F") or 0), -(r.get("start_f") or 0), r.get("post_digest") or ""))


def choose_blinded_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail"):
        return "BLINDED_F2_CONTRACT_FAILURE", p.get("contract_reason") or "root/replay/accounting/identity/firewall failure"
    if p.get("calibration_failure"):
        return "BLINDED_F2_CALIBRATION_FAILURE", "CONTROL_187 did not rediscover 187 under Stage B"
    if p.get("novel_le_186") and p.get("replay_ok"):
        return "BLINDED_F2_COST_IMPROVED", f"novel g={p.get('best_novel_g')}"
    classes = p.get("classes") or {}
    n187 = sum(1 for k, v in classes.items() if v == "CLASS_187" and k != "CONTROL_187")
    ctrl = classes.get("CONTROL_187")
    if ctrl == "CLASS_187" and n187 >= 1:
        return "BLINDED_F2_MULTIPLE_187_CLASS", f"CONTROL_187 plus {n187} novel 187-class root(s)"
    if ctrl == "CLASS_187" and n187 == 0:
        return "BLINDED_F2_CONTROL_DISTINGUISHED", "only CONTROL_187 solved 187 in Stage B"
    if p.get("stage_c") and int((p.get("stage_c") or {}).get("max_F") or 0) >= 5:
        return "BLINDED_F2_PRODUCTION_CANDIDATE", "novel remains live at ceiling 186"
    return "BLINDED_F2_NO_DISCRIMINATION", "calibration passed but deep results do not distinguish roots"


def next_recommendation(verdict: str) -> str:
    if verdict == "BLINDED_F2_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "BLINDED_F2_MULTIPLE_187_CLASS":
        return "Search those exact novel 187-class F2s at ceiling 186. Do not return to shallow-ranked roots."
    if verdict == "BLINDED_F2_CONTROL_DISTINGUISHED":
        return (
            "The lean evaluator is a practical F2 discriminator. Move upstream: "
            "rows=1 F1 → tactical F2 → SD5 → lean deep consequence evaluation."
        )
    if verdict == "BLINDED_F2_PRODUCTION_CANDIDATE":
        return "Continue the selected novel root at ceiling 186."
    if verdict == "BLINDED_F2_CALIBRATION_FAILURE":
        return "Repair evaluator nondeterminism/performance before broadening."
    return "Do not generate new F1 candidates; diagnose discrimination."


def _lane_keys_have_no_label() -> bool:
    src = Path(__file__).read_text(encoding="utf-8")
    return "CONTROL_187" not in __import__("inspect").getsource(strategic_lane_keys)
