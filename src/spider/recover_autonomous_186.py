"""Recover v0.99 Optiplex Winner A/B ancestry and verify autonomous g=186.

The v0.84 artefact dropped F2 full_actions. This module re-runs the exact
Diamond harvest from trusted g123 and matches ordered digests exactly.
Canonical/human routes are not read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from spider.campaign_worker import run_lean_job
from spider.f2_quality_frontier import (
    HARVEST_UNIQUE,
    apply_exact_final_deal,
    g123_ready_targets,
    harvest_f2_target,
    verify_g123_root,
)
from spider.metrics import export_actions_to_moves_file, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import as_actions, dump_actions, is_deal, stock_rows
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[2]
SOLUTION_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_100.moves"
SOLUTION_JSON = ROOT / "solutions" / "4925153_autonomous_v0_100.json"
CANON = ROOT / "solutions" / "4925153_canonical.moves"

WINNER_A = {
    "id": "79e127c0-bb18-4a6f-958e-386eeeab516b",
    "name": "WINNER_A",
    "pre_g": 130,
    "pre_digest": (
        "53504b310102000a00020d2900023221000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a391800022634"
        "0003363504000d3d3c3b3a3938373635343d3c0b000928270605242332313800000009080716151413121109131a2233193717"
        "0133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201"
    ),
    "post_g": 131,
    "post_digest": (
        "53504b310102000000030d2913000332211a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a391833"
        "0003263419000436350437000e3d3c3b3a3938373635343d3c0b17000a28270605242332313801000133000a08071615141312"
        "1109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201"
    ),
}
WINNER_B = {
    "id": "e5836707-d614-4ef6-a89b-11236e544de5",
    "name": "WINNER_B",
    "pre_g": 130,
    "pre_digest": (
        "53504b310102000a00030d2938000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d2c1b3a391800022634"
        "000436350421000d3d3c3b3a3938373635343d3c0b0008282706052423323100000009080716151413121109131a2233193717"
        "0133250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201"
    ),
    "post_g": 131,
    "post_digest": (
        "53504b310102000000040d2938130002321a000d0a1918171615140302111c1b22020f31122d0c3b1a1d1c2b2a1d2c1b3a391833"
        "000326341900053635042137000e3d3c3b3a3938373635343d3c0b170009282706052423323101000133000a08071615141312"
        "1109250d2d2c2b2a2928272625242322210d0d0c0b0a090807060504030201"
    ),
}

# v0.84 diamond per-target envelope: HARVEST_S/n_ready = 360/2 = 180s.
DIAMOND_HARVEST_S = 180.0
VERIFY_TIME_S = 60.0
VERIFY_UNIQUE = 300_000
VERIFY_CEILING = 186


def _join(rec: dict) -> dict:
    out = dict(rec)
    out["pre_digest"] = rec["pre_digest"].replace("\n", "").replace(" ", "")
    out["post_digest"] = rec["post_digest"].replace("\n", "").replace(" ", "")
    return out


WINNERS = (_join(WINNER_A), _join(WINNER_B))


def diamond_target(g123: dict) -> dict:
    st = unpack_state(bytes.fromhex(g123["ordered_digest"]))
    ready = g123_ready_targets(st, int(g123["g"]))
    for rec in ready:
        if rec.get("suit") == "d":
            return rec
    return {"suit": "d", "operational_rank": 1}


def harvest_diamond_winners(
    g123: dict,
    *,
    time_s: float = DIAMOND_HARVEST_S,
    unique: int = HARVEST_UNIQUE,
) -> dict:
    tgt = diamond_target(g123)
    hv = harvest_f2_target(g123, tgt, time_s=float(time_s), unique=int(unique), ceiling=186)
    wanted = {w["pre_digest"]: w for w in WINNERS}
    found: Dict[str, dict] = {}
    for term in hv.get("terminals") or []:
        digest = term.get("ordered_digest")
        if digest in wanted and digest not in found:
            item = dict(term)
            item["winner"] = wanted[digest]["name"]
            item["winner_id"] = wanted[digest]["id"]
            found[digest] = item
        if len(found) >= 2:
            break
    return {
        "harvest": {k: hv.get(k) for k in ("elapsed_s", "unique", "expanded", "generated", "stop_reason", "n_f2", "n_unique", "cheapest_g")},
        "target": tgt,
        "found": found,
        "n_found": len(found),
        "winner_a": found.get(WINNERS[0]["pre_digest"]),
        "winner_b": found.get(WINNERS[1]["pre_digest"]),
    }


def apply_and_check_sd5(pre: dict, winner: dict) -> dict:
    post = apply_exact_final_deal(
        {
            "g": pre["g"],
            "ordered_digest": pre["ordered_digest"],
            "full_actions": pre.get("full_actions"),
        }
    )
    ok = (
        bool(post.get("ok"))
        and int(post.get("post_g") or 0) == int(winner["post_g"])
        and post.get("post_digest") == winner["post_digest"]
        and int(pre.get("g") or 0) == int(winner["pre_g"])
        and pre.get("ordered_digest") == winner["pre_digest"]
    )
    post["match_ok"] = bool(ok)
    post["winner"] = winner["name"]
    return post


def replay_complete(full_actions: list) -> dict:
    opening = opening_state()
    end = opening.clone()
    acts = as_actions(full_actions)
    try:
        g = replay_actions(end, acts)
    except Exception as exc:
        return {"ok": False, "reason": f"illegal:{exc}"}
    n_deal = sum(1 for a in acts if is_deal(a))
    ok = (
        g == 186
        and n_deal == 5
        and bool(end.is_solved())
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
        and stock_rows(end) == 0
    )
    return {
        "ok": bool(ok),
        "g": g,
        "n_deal": n_deal,
        "foundations": len(end.foundations),
        "solved": bool(end.is_solved()),
        "stock_empty": not end.stock,
        "tableau_empty": all(c.is_empty() for c in end.columns),
        "n_actions": len(acts),
        "reason": None if ok else "replay_contract_failed",
    }


def verify_winner(pre: dict, winner: dict, *, time_s: float = VERIFY_TIME_S) -> dict:
    opening = opening_state()
    prefix = as_actions(pre.get("full_actions") or [])
    end = opening.clone()
    try:
        g_pre = replay_actions(end, prefix)
    except Exception as exc:
        return {"ok": False, "reason": f"prefix_illegal:{exc}", "winner": winner["name"]}
    pre_ok = g_pre == int(winner["pre_g"]) and pack_state(end).hex() == winner["pre_digest"]
    post = apply_and_check_sd5(pre, winner)
    if not pre_ok or not post.get("match_ok"):
        return {
            "ok": False,
            "reason": "digest_mismatch",
            "pre_ok": pre_ok,
            "sd5_ok": post.get("match_ok"),
            "winner": winner["name"],
            "post": post,
        }
    job = {
        "id": f"verify_{winner['name']}",
        "candidate_id": winner["id"],
        "g": int(post["post_g"]),
        "ordered_digest": post["post_digest"],
        "ident": post.get("ident"),
        "assembly_h": post.get("assembly_h"),
        "ceiling": VERIFY_CEILING,
        "time_s": float(time_s),
        "max_unique": VERIFY_UNIQUE,
        "stop_on_first_terminal": True,
    }
    lean = run_lean_job(job, rss_abort_mb=2560)
    if not lean.get("solved") or lean.get("terminal_g") is None:
        return {
            "ok": False,
            "reason": "stockempty_unsolved",
            "winner": winner["name"],
            "lean": {k: lean.get(k) for k in ("solved", "terminal_g", "stop_reason", "unique", "elapsed_s", "max_foundations")},
            "post": post,
        }
    suffix = as_actions(lean.get("terminal_actions") or [])
    full = dump_actions(as_actions(post.get("full_actions") or []) + suffix)
    replay = replay_complete(full)
    return {
        "ok": bool(replay.get("ok")),
        "winner": winner["name"],
        "winner_id": winner["id"],
        "pre_g": winner["pre_g"],
        "post_g": winner["post_g"],
        "tactical_delta_g": int(pre["g"]) - 123,
        "full_actions": full,
        "replay": replay,
        "lean": {
            "terminal_g": lean.get("terminal_g"),
            "terminal_s": lean.get("terminal_s"),
            "unique": lean.get("unique"),
            "stop": lean.get("stop_reason"),
            "elapsed_s": lean.get("elapsed_s"),
            "max_foundations": lean.get("max_foundations"),
        },
        "post": {"post_g": post.get("post_g"), "post_digest": post.get("post_digest"), "match_ok": post.get("match_ok")},
        "reason": replay.get("reason"),
    }


def save_verified_solution(verified: dict) -> dict:
    if not verified.get("ok"):
        return {"ok": False, "reason": "not_verified"}
    acts = as_actions(verified["full_actions"])
    SOLUTION_MOVES.parent.mkdir(parents=True, exist_ok=True)
    export_actions_to_moves_file(
        acts,
        SOLUTION_MOVES,
        header="autonomous v0.100 verified g=186; no canonical input",
    )
    payload = {
        "experiment": "hierarchical_deep_campaign_v0_100",
        "incumbent_before": 187,
        "incumbent_after": 186,
        "production_ceiling_before": 186,
        "production_ceiling_after": 185,
        "winner": verified.get("winner"),
        "winner_id": verified.get("winner_id"),
        "replay": verified.get("replay"),
        "lean": verified.get("lean"),
        "tactical_delta_g": verified.get("tactical_delta_g"),
        "n_actions": len(acts),
        "moves_path": str(SOLUTION_MOVES.relative_to(ROOT)).replace("\\", "/"),
        "canonical_used": False,
    }
    SOLUTION_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "moves": str(SOLUTION_MOVES), "json": str(SOLUTION_JSON)}


def recover_and_verify(*, harvest_s: float = DIAMOND_HARVEST_S, verify_s: float = VERIFY_TIME_S) -> dict:
    if CANON.exists():
        # Firewall: recovery code must not parse the canonical file.
        pass
    g123 = verify_g123_root()
    if not g123.get("ok"):
        return {"ok": False, "reason": "g123_failed", "g123": {k: g123.get(k) for k in ("ok", "g", "reason")}}
    n_deal_g123 = sum(1 for a in as_actions(g123.get("prefix_actions") or []) if is_deal(a))
    if n_deal_g123 != 4:
        return {"ok": False, "reason": f"g123_deals_{n_deal_g123}", "g123": g123}
    harvested = harvest_diamond_winners(g123, time_s=harvest_s)
    verified = None
    attempts: List[dict] = []
    for key, winner in (("winner_a", WINNERS[0]), ("winner_b", WINNERS[1])):
        pre = harvested.get(key)
        if not pre:
            attempts.append({"winner": winner["name"], "recovered": False})
            continue
        rec = verify_winner(pre, winner, time_s=verify_s)
        attempts.append(rec)
        if rec.get("ok") and verified is None:
            verified = rec
            break
    saved = save_verified_solution(verified) if verified and verified.get("ok") else {"ok": False}
    return {
        "ok": bool(verified and verified.get("ok") and saved.get("ok")),
        "g123": {
            "ok": g123.get("ok"),
            "g": g123.get("g"),
            "foundations": g123.get("foundations"),
            "face_down": g123.get("face_down"),
            "stock_rows": g123.get("stock_rows"),
            "digest_ok": g123.get("digest_ok"),
            "n_deal": n_deal_g123,
            "n_prefix": len(as_actions(g123.get("prefix_actions") or [])),
        },
        "harvest": harvested.get("harvest"),
        "n_found": harvested.get("n_found"),
        "winner_a_recovered": bool(harvested.get("winner_a")),
        "winner_b_recovered": bool(harvested.get("winner_b")),
        "verified": None if not verified else {k: verified.get(k) for k in verified if k != "full_actions"},
        "saved": saved,
        "attempts": [{k: a.get(k) for k in a if k not in ("full_actions", "post")} for a in attempts],
        "incumbent_after": 186 if saved.get("ok") else 187,
        "ceiling_after": 185 if saved.get("ok") else 186,
        "canonical_used": False,
    }
