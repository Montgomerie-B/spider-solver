"""v0.83 F3 bridge calibration: slack vs assembly at equal probe cost.

Loads three NEW v0.82 Pareto F3s by recorded metrics (no baked digests)
and runs equal-resource proof-aware next-foundation probes. Does not
harvest. Does not resume g141/g158 or exhausted v0.80/v0.81 F4/F5 roots.
Canonical 172 is not read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.f3_quality_frontier import control_digests, enrich_stock_empty_state, is_known_closed
from spider.f3_tactical_bridge import select_f4_portfolio
from spider.proof_aware_tactical_bridge import is_proof_viable
from spider.whole_game_epoch_scheduler import SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V082_JSON = ROOT / "docs" / "research" / "f3_quality_frontier_v0_82.json"

# 60s exceeds the v0.80 g141 first-viable time (~48.8s). 10s was not a fair test.
STAGE_A_S = 60.0
STAGE_A_UNIQUE = 100_000
N_ROOTS = 3
TOTAL_S = SEARCH_TIME_S
CONTINUATION_RESERVE_S = 150.0
G141_FIRST_VIABLE_S = 48.8
PORTFOLIO_MAX = 16

# Metrics-only selectors. Digests come from the v0.82 artefact.
ROOT_SPECS = (
    {
        "name": "A_high_slack",
        "g": 142,
        "h": 32,
        "f": 174,
        "slack": 12,
        "face_down": 2,
        "empty_n": 2,
        "legal_tableau": 47,
        "boundaries": 35,
    },
    {
        "name": "B_interior",
        "g": 160,
        "h": 23,
        "f": 183,
        "slack": 3,
        "face_down": 2,
        "empty_n": 3,
        "legal_tableau": 76,
        "boundaries": 26,
    },
    {
        "name": "C_assembled",
        "g": 161,
        "h": 22,
        "f": 183,
        "slack": 3,
        "face_down": 2,
        "empty_n": 4,
        "legal_tableau": 95,
        "boundaries": 25,
    },
)


def _metric_key(rec: dict) -> tuple:
    return (
        int(rec.get("g") or -1),
        int(rec.get("assembly_h") if rec.get("assembly_h") is not None else rec.get("h") or -1),
        int(rec.get("assembly_f") if rec.get("assembly_f") is not None else rec.get("f") or -1),
        int(rec.get("empty_n") or -1),
        int(rec.get("legal_tableau") or rec.get("legal") or -1),
        int(rec.get("boundaries") or -1),
    )


def _spec_key(spec: dict) -> tuple:
    return (
        int(spec["g"]),
        int(spec["h"]),
        int(spec["f"]),
        int(spec["empty_n"]),
        int(spec["legal_tableau"]),
        int(spec["boundaries"]),
    )


def load_v082_f3_pool() -> List[dict]:
    data = json.loads(V082_JSON.read_text(encoding="utf-8"))
    pool = []
    seen = set()
    for rec in list(data.get("pareto") or []) + list(data.get("selected") or []):
        digest = rec.get("ordered_digest")
        if not digest or digest in seen:
            continue
        seen.add(digest)
        pool.append(dict(rec))
    return pool


def load_calibration_root(spec: dict, pool: Optional[Sequence[dict]] = None) -> dict:
    """Load one F3 by metrics from the v0.82 artefact. Digest is not a policy constant."""

    pool = list(pool) if pool is not None else load_v082_f3_pool()
    want = _spec_key(spec)
    hit = next((r for r in pool if _metric_key(r) == want), None)
    if hit is None:
        raise KeyError(f"v0.82 F3 not found for spec {spec['name']}: {want}")
    rec = dict(hit)
    rec["calibration_name"] = spec["name"]
    return rec


def load_calibration_roots() -> List[dict]:
    pool = load_v082_f3_pool()
    return [load_calibration_root(spec, pool) for spec in ROOT_SPECS]


def verify_calibration_root(spec: dict, rec: dict) -> dict:
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
        "boundaries": spec["boundaries"],
        "stock_rows": 0,
        "can_deal": False,
    }
    mismatches = {
        k: {"expected": v, "got": info.get(k)}
        for k, v in expected.items()
        if info.get(k) != v
    }
    is_control = digest in (controls["g141"], controls["g158"]) or info.get("ident") in (
        controls["g141_ident"],
        controls["g158_ident"],
    )
    ok = not mismatches and not is_control and info.get("viable")
    info["ok"] = bool(ok)
    info["reason"] = None if ok else ("control_digest" if is_control else "recompute_mismatch")
    info["mismatches"] = mismatches
    info["is_control"] = bool(is_control)
    info["calibration_name"] = spec["name"]
    info["n_actions"] = rec.get("n_actions")
    return info


def verify_all_calibration_roots() -> dict:
    roots = load_calibration_roots()
    verified = []
    ok = True
    for spec, rec in zip(ROOT_SPECS, roots):
        info = verify_calibration_root(spec, rec)
        verified.append(info)
        if not info.get("ok"):
            ok = False
    return {"ok": ok, "roots": verified, "n": len(verified)}


def equal_f_composition_differs(g160: Optional[dict], g161: Optional[dict]) -> bool:
    """True if equal-f roots have materially different bridge outcomes."""

    if not g160 or not g161:
        return False
    f160 = g160.get("best_terminal_f")
    f161 = g161.get("best_terminal_f")
    if (f160 is None) != (f161 is None):
        return True
    if f160 is None:
        return (g160.get("stop_class") or "") != (g161.get("stop_class") or "")
    if int(f160) != int(f161):
        return True
    loss160 = g160.get("bridge_loss")
    loss161 = g161.get("bridge_loss")
    if loss160 is not None and loss161 is not None and int(loss160) != int(loss161):
        return True
    h160 = g160.get("lowest_terminal_h")
    h161 = g161.get("lowest_terminal_h")
    if h160 is not None and h161 is not None and int(h160) != int(h161):
        return True
    return False


def select_calibration_portfolio(aggs: Sequence[dict], closed: dict, *, hard_max: int = PORTFOLIO_MAX) -> List[dict]:
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


def choose_calibration_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F3_CALIBRATION_CONTRACT_FAILURE", p.get("contract_reason") or "root/identity/proof/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "F3_CALIBRATION_COST_IMPROVED", f"solved at g={best}"
    best_f = p.get("best_new_f")
    best_loss = p.get("best_bridge_loss")
    max_f = int(p.get("max_foundations") or 0)
    if best_f is not None and int(best_f) <= 184:
        return "F3_CALIBRATION_FINDS_STRONG_SURPLUS", f"next-foundation f={best_f} loss={best_loss}"
    if max_f >= 6:
        return "F3_CALIBRATION_DEEP_ENDGAME", f"maxF={max_f}"
    if p.get("composition_differs"):
        return "F3_CALIBRATION_REVEALS_F_COMPOSITION", "g160/g161 equal-f states have different bridge economics"
    if best_f is not None and int(best_f) == 185:
        return "F3_CALIBRATION_MATCHES_G158", f"next-foundation f=185 loss={best_loss}"
    if best_f is not None and int(best_f) == 186:
        return "F3_CALIBRATION_ZERO_SLACK_ONLY", f"next-foundation f=186 loss={best_loss}"
    if p.get("screening_time_limited"):
        return "F3_CALIBRATION_SEARCH_LIMITED", "positive-slack F3s remain time-limited after 60s/target"
    return "F3_CALIBRATION_NO_CONVERSION", "fair 60s probes produced no next foundation and relevant searches completed"


def next_recommendation(verdict: str) -> str:
    if verdict == "F3_CALIBRATION_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "F3_CALIBRATION_FINDS_STRONG_SURPLUS":
        return "Make the strong-surplus next-foundation the next hierarchical root; preserve this F3 class."
    if verdict == "F3_CALIBRATION_REVEALS_F_COMPOSITION":
        return "Value lower h / greater assembly separately from total f in final-epoch F3 selection."
    if verdict == "F3_CALIBRATION_MATCHES_G158":
        return "Treat assembled F3s with leftover slack like g158; do not resume closed F4/F5 roots."
    if verdict == "F3_CALIBRATION_ZERO_SLACK_ONLY":
        return (
            "g158 remains the only F3 that converted with leftover slack. "
            "Stop mining this g128 F3 family; produce a better post-SD5 F2/root. "
            "Do not resume closed F4/F5 roots."
        )
    if verdict == "F3_CALIBRATION_DEEP_ENDGAME":
        return "Continue hierarchical decomposition from the new F6-capable root, excluding exact closed identities."
    if verdict == "F3_CALIBRATION_SEARCH_LIMITED":
        return "Keep equal 60s probes on these three F3s; do not harvest again and do not widen wall time."
    if verdict == "F3_CALIBRATION_NO_CONVERSION":
        return "Stop further F3 decomposition on this g128 post-SD5 branch; produce a better post-SD5 F2/root."
    return "Do not promote; diagnose the contract."
