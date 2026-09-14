"""v0.86 new-family F3 topology vs proof-aware bridge.

Loads the v0.85 cheapest and first F3s (same g/h/f as old g141, different
digest) and runs equal 90s proof-aware probes. Canonical 172 is not read.
The historical old g141 is a frozen control, never an active search root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence

from spider.f2_quality_frontier import load_f2_closed_table
from spider.f3_quality_frontier import control_digests, enrich_stock_empty_state, is_known_closed
from spider.f3_tactical_bridge import select_f4_portfolio
from spider.proof_aware_tactical_bridge import is_proof_viable
from spider.whole_game_epoch_scheduler import SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V085_JSON = ROOT / "docs" / "research" / "superior_f2_focused_endgame_v0_85.json"

STAGE_A_S = 90.0
STAGE_A_UNIQUE = 150_000
N_ROOTS = 2
TOTAL_S = SEARCH_TIME_S
CONTINUATION_RESERVE_S = 180.0
PORTFOLIO_MAX = 16
OLD_G141 = {"g": 141, "h": 33, "f": 174, "best_next_g": 161, "best_next_h": 25, "best_next_f": 186, "bridge_loss": 12}

ROOT_SPECS = (
    {
        "name": "NEW_CHEAP_F3",
        "json_path": ("cheap_F", "3"),
        "g": 141,
        "h": 33,
        "f": 174,
        "slack": 12,
        "face_down": 2,
        "empty_n": 2,
        "legal_tableau": 43,
        "boundaries": 28,
    },
    {
        "name": "NEW_FIRST_F3",
        "json_path": ("first_F", "3"),
        "g": 148,
        "h": 29,
        "f": 177,
        "slack": 9,
        "face_down": 2,
        "empty_n": 2,
        "legal_tableau": 43,
        "boundaries": 24,
    },
)


def _get_path(data: dict, path: tuple) -> dict:
    cur = data
    for key in path:
        cur = (cur or {}).get(key) if isinstance(cur, dict) else None
        if cur is None:
            cur = (data.get(path[0]) or {}).get(int(path[1])) if len(path) == 2 else None
            break
    return dict(cur) if isinstance(cur, dict) else {}


def load_new_family_f3(spec: dict, data: Optional[dict] = None) -> dict:
    """Load one F3 from v0.85 telemetry. Digest is not a policy constant."""

    data = data if data is not None else json.loads(V085_JSON.read_text(encoding="utf-8"))
    rec = _get_path(data, spec["json_path"])
    if not rec.get("ordered_digest"):
        raise KeyError(f"v0.85 {spec['name']} missing ordered_digest")
    if int(rec.get("g") or 0) != spec["g"] or int(rec.get("h") or 0) != spec["h"] or int(rec.get("f") or 0) != spec["f"]:
        raise KeyError(f"v0.85 {spec['name']} metrics mismatch: {rec}")
    rec["calibration_name"] = spec["name"]
    rec["assembly_h"] = int(rec.get("h") or rec.get("assembly_h") or 0)
    rec["assembly_f"] = int(rec.get("f") or rec.get("assembly_f") or 0)
    rec["legal_tableau"] = int(rec.get("legal") or rec.get("legal_tableau") or 0)
    return rec


def load_new_family_roots() -> List[dict]:
    data = json.loads(V085_JSON.read_text(encoding="utf-8"))
    return [load_new_family_f3(spec, data) for spec in ROOT_SPECS]


def verify_new_family_root(spec: dict, rec: dict) -> dict:
    digest = rec.get("ordered_digest")
    if not digest:
        return {"ok": False, "reason": "missing_digest", "name": spec["name"]}
    controls = control_digests()
    info = enrich_stock_empty_state(digest, int(spec["g"]))
    expected = {
        "g": spec["g"],
        "foundations": 3,
        "assembly_h": spec["h"],
        "assembly_f": spec["f"],
        "slack": spec["slack"],
        "face_down": spec["face_down"],
        "empty_n": spec["empty_n"],
        "legal_tableau": spec["legal_tableau"],
        "stock_rows": 0,
        "can_deal": False,
    }
    mismatches = {
        k: {"expected": v, "got": info.get(k)}
        for k, v in expected.items()
        if info.get(k) != v
    }
    is_old = digest == controls["g141"] or info.get("ident") == controls["g141_ident"]
    ok = not mismatches and not is_old and info.get("viable")
    info["ok"] = bool(ok)
    info["reason"] = None if ok else ("old_g141_digest" if is_old else "recompute_mismatch")
    info["mismatches"] = mismatches
    info["is_old_g141"] = bool(is_old)
    info["calibration_name"] = spec["name"]
    info["boundaries_recorded"] = spec["boundaries"]
    info["differs_from_old_digest"] = digest != controls["g141"]
    info["differs_from_old_ident"] = info.get("ident") != controls["g141_ident"]
    return info


def verify_all_new_family_roots() -> dict:
    roots = load_new_family_roots()
    verified = []
    ok = True
    for spec, rec in zip(ROOT_SPECS, roots):
        info = verify_new_family_root(spec, rec)
        verified.append(info)
        if not info.get("ok"):
            ok = False
    return {"ok": ok, "roots": verified, "n": len(verified)}


def load_new_family_closed_table() -> dict:
    return load_f2_closed_table()


def select_new_family_portfolio(aggs: Sequence[dict], closed: dict, *, hard_max: int = PORTFOLIO_MAX) -> List[dict]:
    pool = []
    for agg in aggs:
        for rec in agg.get("viable_terminals") or []:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            item = dict(rec)
            item["ident"] = ident
            item["root_g"] = agg.get("root_g")
            item["closed"] = bool(ident and is_known_closed(ident, int(rec["g"]), closed))
            if item["closed"]:
                item["closed_tag"] = "KNOWN_CLOSED_STATE"
            if item["closed"] or not is_proof_viable(int(rec["g"]), int(rec["assembly_h"])):
                continue
            pool.append(item)
    return select_f4_portfolio(pool, hard_max=int(hard_max))[: int(hard_max)]


def topology_beats_old(best_f, loss) -> bool:
    if best_f is None:
        return False
    if int(best_f) < int(OLD_G141["best_next_f"]):
        return True
    if loss is not None and int(loss) < int(OLD_G141["bridge_loss"]):
        return True
    return False


def choose_new_family_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "NEW_F3_BRIDGE_CONTRACT_FAILURE", p.get("contract_reason") or "state/provenance/proof/accounting/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "NEW_F3_BRIDGE_COST_IMPROVED", f"solved at g={best}"
    best_f = p.get("best_new_f")
    max_f = int(p.get("max_foundations") or 0)
    if best_f is not None and int(best_f) <= 184:
        return "NEW_F3_BRIDGE_FINDS_STRONG_SURPLUS", f"next-foundation f={best_f}"
    if max_f >= 6:
        return "NEW_F3_BRIDGE_DEEP_ENDGAME", f"maxF={max_f}"
    cheap = p.get("new_g141") or {}
    if topology_beats_old(cheap.get("best_terminal_f"), cheap.get("bridge_loss")):
        return "NEW_F3_TOPOLOGY_BEATS_OLD", f"new g141 next f={cheap.get('best_terminal_f')} loss={cheap.get('bridge_loss')}"
    if best_f is not None and int(best_f) == 185:
        return "NEW_F3_BRIDGE_FINDS_SURPLUS", "best next f=185"
    if best_f is not None and int(best_f) == 186:
        return "NEW_F3_BRIDGE_ZERO_SLACK", "best next f=186 only"
    if p.get("screening_time_limited"):
        return "NEW_F3_BRIDGE_SEARCH_LIMITED", "important target probes remain resource-limited"
    return "NEW_F3_BRIDGE_NO_CONVERSION", "fair tactical probes produced no viable next foundation"


def next_recommendation(verdict: str) -> str:
    if verdict == "NEW_F3_BRIDGE_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "NEW_F3_TOPOLOGY_BEATS_OLD":
        return "Use the topological differences at equal g/h/f to design the next state-value feature."
    if verdict == "NEW_F3_BRIDGE_FINDS_STRONG_SURPLUS":
        return "Make the strong-surplus next-foundation the next hierarchical root."
    if verdict == "NEW_F3_BRIDGE_FINDS_SURPLUS":
        return "Continue hierarchical decomposition from the surplus F4; do not resume closed old-family F4s."
    if verdict == "NEW_F3_BRIDGE_ZERO_SLACK":
        return "Stop mining this F3 family; perform pre-Deal preparation after F2 before SD5."
    if verdict == "NEW_F3_BRIDGE_DEEP_ENDGAME":
        return "Continue from the live F6+ descendant, excluding exact closed identities."
    if verdict == "NEW_F3_BRIDGE_SEARCH_LIMITED":
        return "Keep equal 90s probes on these two F3s; do not widen wall time."
    if verdict == "NEW_F3_BRIDGE_NO_CONVERSION":
        return "Stop mining this F3 family; perform pre-Deal preparation after F2 before SD5."
    return "Do not promote; diagnose the contract."
