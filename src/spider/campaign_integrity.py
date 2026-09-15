"""Scientific integrity helpers: ancestry invariant, node/candidate sync, import adopt."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.campaign_status import FAILED_CONTRACT, proof_dead_label
from spider.incumbent import current_incumbent_g, load_incumbent, production_ceiling, promote_incumbent
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import as_actions, is_deal, stock_rows
from spider.whole_game_anytime import opening_state


def recompute_assembly(node: dict) -> None:
    """Refresh h/f after a g change. h is g-independent; f = g+h."""

    if int(node.get("stock_rows") or 0) != 0:
        return
    digest = node.get("ordered_digest")
    if not digest:
        return
    st = unpack_state(bytes.fromhex(digest))
    g = int(node.get("g") or 0)
    h = int(stock_empty_assembly_h(st, g))
    node["assembly_h"] = h
    node["assembly_f"] = g + h


def sync_candidate_from_node(campaign: dict, node: dict) -> Optional[dict]:
    cid = node.get("candidate_id")
    if not cid:
        return None
    for cand in campaign.get("candidates") or []:
        if cand.get("id") != cid:
            continue
        cand["g"] = node.get("g")
        cand["ordered_digest"] = node.get("ordered_digest")
        cand["ident"] = node.get("ident")
        cand["whole_game_identity"] = node.get("whole_game_identity") or node.get("ident")
        cand["full_actions"] = node.get("full_actions")
        cand["n_deal"] = node.get("n_deal")
        cand["assembly_h"] = node.get("assembly_h")
        cand["assembly_f"] = node.get("assembly_f")
        cand["proof_dead"] = bool((node.get("proof") or {}).get("proof_dead")) or str(node.get("status") or "").startswith("PROOF_DEAD")
        cand["lower_g_reopening"] = bool(node.get("lower_g_reopening"))
        cand["source_state_id"] = node.get("id")
        return cand
    return None


def validate_node_ancestry(node: dict, *, force: bool = False) -> dict:
    """Replay full_actions; require g and ordered_digest match. Cache per (g, digest)."""

    acts = node.get("full_actions") or []
    if not acts and int(node.get("g") or 0) == 0:
        return {"ok": True, "cached": True, "reason": "opening"}
    if not acts:
        return {"ok": False, "reason": "missing_full_actions"}
    key = (int(node.get("g") or 0), node.get("ordered_digest") or "")
    cache = node.get("ancestry_cache") or {}
    if not force and cache.get("key") == list(key) and cache.get("ok"):
        return {"ok": True, "cached": True}
    opening = opening_state()
    end = opening.clone()
    try:
        g = replay_actions(end, as_actions(acts))
    except Exception as exc:
        rec = {"ok": False, "reason": f"illegal:{exc}", "outcome": FAILED_CONTRACT}
        node["ancestry_cache"] = {"key": list(key), "ok": False, "reason": rec["reason"]}
        return rec
    digest = pack_state(end).hex()
    ok = g == int(node.get("g") or -1) and digest == node.get("ordered_digest")
    rec = {
        "ok": bool(ok),
        "g": g,
        "ordered_digest": digest,
        "n_deal": sum(1 for a in as_actions(acts) if is_deal(a)),
        "reason": None if ok else "ancestry_mismatch",
        "outcome": None if ok else FAILED_CONTRACT,
    }
    node["ancestry_cache"] = {"key": list(key), "ok": rec["ok"], "reason": rec.get("reason")}
    return rec


def job_payload_from_node(node: dict, job: dict) -> dict:
    payload = dict(job)
    payload["g"] = node.get("g")
    payload["ordered_digest"] = node.get("ordered_digest")
    payload["ident"] = node.get("ident") or node.get("whole_game_identity")
    payload["assembly_h"] = node.get("assembly_h")
    payload["full_actions"] = node.get("full_actions")
    payload["node_id"] = node.get("id")
    payload["n_deal"] = node.get("n_deal")
    return payload


def refilter_graph(campaign: dict) -> dict:
    """Immediately apply current ceiling to all STOCK_EMPTY nodes and pending jobs."""

    ceiling = int(campaign.get("production_ceiling") or production_ceiling())
    n_dead = 0
    n_live = 0
    label = proof_dead_label(ceiling)
    for node in campaign.get("nodes") or []:
        if node.get("kind") not in ("STOCK_EMPTY", "SOLVED"):
            continue
        recompute_assembly(node)
        f = node.get("assembly_f")
        if f is None:
            continue
        if int(f) > ceiling and node.get("status") != "SOLVED":
            node.setdefault("proof", {})["proof_dead"] = True
            node["proof"]["ceiling"] = ceiling
            node["status"] = label
            n_dead += 1
        else:
            node.setdefault("proof", {})["proof_dead"] = False
            node["proof"]["ceiling"] = ceiling
            if str(node.get("status") or "").startswith("PROOF_DEAD") and int(f) <= ceiling:
                node["status"] = "LOWER_G_REOPENING" if node.get("lower_g_reopening") else "OPEN"
            n_live += 1
        sync_candidate_from_node(campaign, node)
    skipped = 0
    by_id = {n.get("id"): n for n in campaign.get("nodes") or []}
    for job in campaign.get("jobs") or []:
        if job.get("status") != "pending":
            continue
        node = by_id.get(job.get("node_id"))
        if node is None:
            for n in campaign.get("nodes") or []:
                if n.get("candidate_id") == job.get("candidate_id"):
                    node = n
                    break
        if node is None:
            continue
        if str(node.get("status") or "").startswith("PROOF_DEAD"):
            job["status"] = "skipped_proof_dead"
            skipped += 1
    return {"ceiling": ceiling, "proof_dead": n_dead, "proof_live": n_live, "label": label, "skipped_pending": skipped}


def extract_autonomous_pre_f2() -> dict:
    """Deterministic PRE_STOCK F2 from the verified autonomous 186 solution. No canonical."""

    from spider.incumbent import incumbent_moves_path
    from spider.research_actions import apply_action, dump_actions, face_down_count, stock_rows
    from spider.packed_state import pack_whole_game_identity

    acts = parse_moves_file(incumbent_moves_path())
    opening = opening_state()
    st = opening.clone()
    prefix = []
    g = 0
    for action in acts:
        if stock_rows(st) == 1 and len(st.foundations) >= 2:
            break
        g += int(apply_action(st, action))
        prefix.append(action)
    if not (stock_rows(st) == 1 and len(st.foundations) >= 2):
        return {"ok": False, "reason": "no_f2_in_autonomous_186"}
    return {
        "ok": True,
        "g": g,
        "ordered_digest": pack_state(st).hex(),
        "ident": pack_whole_game_identity(st).hex(),
        "full_actions": dump_actions(prefix),
        "n_deal": sum(1 for a in prefix if is_deal(a)),
        "foundations": len(st.foundations),
        "stock_rows": stock_rows(st),
        "face_down": face_down_count(st),
    }


def maybe_adopt_imported_incumbent(campaign: dict, dest_folder: Optional[Path] = None) -> dict:
    """Adopt imported incumbent only if lower g and full replay succeeds."""

    imported_g = campaign.get("incumbent_g")
    local_g = current_incumbent_g()
    if imported_g is None:
        return {"adopted": False, "reason": "no_imported_incumbent"}
    if int(imported_g) >= int(local_g):
        return {"adopted": False, "reason": "not_better", "imported_g": imported_g, "local_g": local_g}
    sol = campaign.get("incumbent") or {}
    acts = sol.get("full_actions")
    moves_path = None
    if dest_folder is not None:
        folder = Path(dest_folder) / "solutions"
        if folder.exists():
            cands = sorted(folder.glob("incumbent_g*.moves")) + sorted(folder.glob("*.moves"))
            if cands:
                moves_path = cands[0]
    if not acts and moves_path and moves_path.exists():
        acts = parse_moves_file(moves_path)
    if not acts:
        return {"adopted": False, "reason": "no_solution_artefact", "imported_g": imported_g}
    opening = opening_state()
    end = opening.clone()
    try:
        g = replay_actions(end, as_actions(acts))
    except Exception as exc:
        return {"adopted": False, "reason": f"illegal:{exc}"}
    ok = (
        g == int(imported_g)
        and end.is_solved()
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
        and sum(1 for a in as_actions(acts) if is_deal(a)) == 5
    )
    if not ok:
        return {"adopted": False, "reason": "replay_failed", "g": g}
    rec = promote_incumbent(
        g=int(g),
        moves_path=str(moves_path) if moves_path else f"imported_g{g}.moves",
        source="import_adopt",
    )
    return {"adopted": True, "g": g, "ceiling": rec["production_ceiling"], "local_before": local_g}
