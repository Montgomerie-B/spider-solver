"""Hierarchical campaign graph. A verified state anywhere may be a node.

Full ancestry is part of the node contract. Never discard available full_actions.
Graph, not only a tree: parent/child edges; cheaper arrivals are LOWER_G_REOPENING.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from spider.campaign_status import OPEN
from spider.campaign_worker import current_solver_sha
from spider.hardware import SOLVER_VERSION
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, dump_actions, face_down_count, is_deal, stock_rows
from spider.whole_game_anytime import opening_state

NODE_TYPES = ("OPENING", "EPOCH", "CHECKPOINT", "PRE_STOCK", "STOCK_EMPTY", "SOLVED")
DEAL_ID = "4925153"
RULES = "mobilityware_unrestricted"


def verified_incumbent() -> tuple:
    from spider.incumbent import current_incumbent_g, production_ceiling

    return current_incumbent_g(), production_ceiling()


def classify_kind(*, stock_rows_n: int, foundations: int, solved: bool, g: int) -> str:
    if solved or (foundations >= 8 and stock_rows_n == 0 and g > 0):
        return "SOLVED"
    if stock_rows_n == 0:
        return "STOCK_EMPTY"
    if stock_rows_n == 1 and foundations >= 1:
        return "PRE_STOCK"
    if g == 0 and foundations == 0:
        return "OPENING"
    if foundations >= 1:
        return "CHECKPOINT"
    return "EPOCH"


def identity_key(node: dict) -> tuple:
    """Exact ordered state is the scientific node identity. Never merge distinct ordered_digests."""

    return ("ordered", node.get("ordered_digest"))


def symmetry_key(node: dict) -> Optional[str]:
    """Post-stock whole-column permutation identity. None while stock remains."""

    if int(node.get("stock_rows") or 0) != 0:
        return None
    return node.get("ident") or node.get("whole_game_identity")


def telemetry_from_digest(digest: str, g: int, full_actions=None) -> dict:
    st = unpack_state(bytes.fromhex(digest))
    acts = as_actions(full_actions or [])
    return {
        "foundations": len(st.foundations),
        "face_down": face_down_count(st),
        "stock_rows": stock_rows(st),
        "n_deal": sum(1 for a in acts if is_deal(a)),
        "action_count": len(acts),
        "ident": pack_whole_game_identity(st).hex(),
        "whole_game_identity": pack_whole_game_identity(st).hex(),
        "ordered_digest": pack_state(st).hex() if not digest else digest,
    }


def make_node(
    *,
    g: int,
    ordered_digest: str,
    full_actions,
    kind: Optional[str] = None,
    parent_ids: Optional[list] = None,
    source: str = "manual",
    label: Optional[str] = None,
    ident: Optional[str] = None,
    ancestry_verified: bool = False,
    extra: Optional[dict] = None,
) -> dict:
    acts = dump_actions(as_actions(full_actions or []))
    tel = telemetry_from_digest(ordered_digest, g, acts)
    solved = False
    try:
        st = unpack_state(bytes.fromhex(ordered_digest))
        solved = bool(st.is_solved())
    except Exception:
        solved = False
    node_kind = kind or classify_kind(
        stock_rows_n=int(tel["stock_rows"]),
        foundations=int(tel["foundations"]),
        solved=solved,
        g=int(g),
    )
    rec = {
        "id": str(uuid.uuid4()),
        "parent_ids": list(parent_ids or []),
        "child_ids": [],
        "deal_id": DEAL_ID,
        "rules_profile": RULES,
        "kind": node_kind,
        "ordered_digest": ordered_digest,
        "ident": ident or tel["ident"],
        "whole_game_identity": tel["whole_game_identity"],
        "g": int(g),
        "foundations": tel["foundations"],
        "face_down": tel["face_down"],
        "stock_rows": tel["stock_rows"],
        "n_deal": tel["n_deal"],
        "full_actions": acts,
        "action_count": tel["action_count"],
        "ancestry_verified": bool(ancestry_verified),
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "solver_sha": current_solver_sha(),
        "solver_version": SOLVER_VERSION,
        "status": OPEN if not solved else "SOLVED",
        "runs": [],
        "best_consequence": None,
        "proof": {},
        "label": label or f"{node_kind} g={g} F={tel['foundations']}",
        "lower_g_reopening": False,
        "max_foundations": tel["foundations"],
        "deepest_budget_s": 0.0,
        "total_search_s": 0.0,
    }
    if extra:
        rec.update(extra)
    if rec["kind"] != "OPENING" and rec["full_actions"] is None:
        raise ValueError("full_actions must not be discarded")
    return rec


def opening_node() -> dict:
    opening = opening_state()
    digest = pack_state(opening).hex()
    return make_node(
        g=0,
        ordered_digest=digest,
        full_actions=[],
        kind="OPENING",
        source="opening",
        label="OPENING g=0",
        ancestry_verified=True,
    )


def _link_symmetry_group(campaign: dict, node: dict) -> None:
    key = symmetry_key(node)
    if not key:
        return
    group = None
    for prev in campaign.get("nodes") or []:
        if prev.get("id") == node.get("id"):
            continue
        if symmetry_key(prev) == key:
            group = prev.get("symmetry_group_id") or prev.get("id")
            prev["symmetry_group_id"] = group
            break
    node["symmetry_group_id"] = group or node.get("id")
    if group:
        node["symmetry_equivalent"] = True


def add_node(campaign: dict, node: dict) -> dict:
    """Exact ordered_digest is the node. Symmetric-but-different ordered states stay separate.

    Same ordered_digest + cheaper g: update representative and sync candidate.
    Same post-stock symmetry, different ordered_digest, cheaper g: new searchable
    LOWER_G_REOPENING node; do not overwrite the other ancestry.
    """

    from spider.campaign_integrity import recompute_assembly, refilter_graph, sync_candidate_from_node

    campaign.setdefault("nodes", [])
    campaign.setdefault("edges", [])
    key = identity_key(node)
    existing = None
    for prev in campaign["nodes"]:
        if identity_key(prev) == key:
            existing = prev
            break
    if existing is not None:
        alt = {
            "g": node.get("g"),
            "parent_ids": list(node.get("parent_ids") or []),
            "full_actions": node.get("full_actions"),
            "source": node.get("source"),
            "n_deal": node.get("n_deal"),
            "ordered_digest": node.get("ordered_digest"),
        }
        if int(node["g"]) < int(existing["g"]):
            existing.setdefault("alternate_ancestries", []).append(
                {
                    "g": existing.get("g"),
                    "full_actions": existing.get("full_actions"),
                    "parent_ids": list(existing.get("parent_ids") or []),
                    "n_deal": existing.get("n_deal"),
                    "ordered_digest": existing.get("ordered_digest"),
                }
            )
            existing["g"] = int(node["g"])
            existing["full_actions"] = node.get("full_actions")
            existing["action_count"] = node.get("action_count") or existing.get("action_count")
            existing["n_deal"] = node.get("n_deal")
            existing["ordered_digest"] = node.get("ordered_digest")
            existing["lower_g_reopening"] = True
            existing["status"] = "LOWER_G_REOPENING"
            existing["prior_g"] = existing["alternate_ancestries"][-1]["g"]
            existing["arrival"] = "lower_g_reopening"
            recompute_assembly(existing)
            sync_candidate_from_node(campaign, existing)
            refilter_graph(campaign)
        else:
            existing.setdefault("alternate_ancestries", []).append(alt)
            existing["duplicate_arrivals"] = int(existing.get("duplicate_arrivals") or 0) + 1
            existing["arrival"] = "duplicate"
        for pid in node.get("parent_ids") or []:
            add_edge(campaign, pid, existing["id"])
        return existing
    node["arrival"] = "new"
    _link_symmetry_group(campaign, node)
    if node.get("symmetry_equivalent") and int(node.get("g") or 0) < min(
        (int(p.get("g") or 10**9) for p in campaign["nodes"] if symmetry_key(p) == symmetry_key(node)),
        default=10**9,
    ):
        node["lower_g_reopening"] = True
        node["status"] = "LOWER_G_REOPENING"
        node["arrival"] = "lower_g_reopening_ordered"
        recompute_assembly(node)
    campaign["nodes"].append(node)
    for pid in node.get("parent_ids") or []:
        add_edge(campaign, pid, node["id"])
    return node


def add_edge(campaign: dict, parent_id: str, child_id: str) -> None:
    edge = {"parent": parent_id, "child": child_id}
    edges = campaign.setdefault("edges", [])
    if edge not in edges:
        edges.append(edge)
    nodes = {n["id"]: n for n in campaign.get("nodes") or []}
    parent = nodes.get(parent_id)
    child = nodes.get(child_id)
    if parent is not None and child_id not in (parent.get("child_ids") or []):
        parent.setdefault("child_ids", []).append(child_id)
    if child is not None and parent_id not in (child.get("parent_ids") or []):
        child.setdefault("parent_ids", []).append(parent_id)


def get_node(campaign: dict, node_id: str) -> Optional[dict]:
    for n in campaign.get("nodes") or []:
        if n.get("id") == node_id:
            return n
    return None


def record_node_run(node: dict, run: dict) -> None:
    node.setdefault("runs", []).append(run)
    node["total_search_s"] = float(node.get("total_search_s") or 0.0) + float(run.get("elapsed_s") or run.get("time_s") or 0.0)
    budget = float(run.get("time_s") or 0.0)
    if budget > float(node.get("deepest_budget_s") or 0.0):
        node["deepest_budget_s"] = budget
    max_f = run.get("max_foundations")
    if max_f is not None and int(max_f) >= int(node.get("max_foundations") or 0):
        node["max_foundations"] = int(max_f)
    status = run.get("outcome") or node.get("status")
    prev = node.get("status")
    if status == "SOLVED" or prev == "SOLVED":
        node["status"] = "SOLVED"
        node["best_consequence"] = run
    elif prev != "SOLVED":
        node["status"] = status
    if run.get("solved"):
        node["best_terminal_g"] = run.get("terminal_g")


def deepen_priority(node: dict) -> tuple:
    """Queue order only. Does not prove state quality. Does not discard."""

    status = node.get("status")
    rank = 8
    if status == "SOLVED":
        rank = 0
    elif node.get("lower_g_reopening"):
        rank = 1
    elif int(node.get("max_foundations") or 0) >= 6:
        rank = 2
    elif node.get("best_consequence") and (node["best_consequence"].get("min_f") is not None):
        rank = 4
    elif status_unresolved(node):
        rank = 3
    min_f = 10**9
    bc = node.get("best_consequence") or {}
    if bc.get("starting_f") is not None:
        min_f = int(bc["starting_f"])
    return (
        rank,
        -int(node.get("max_foundations") or 0),
        min_f,
        -float(node.get("deepest_budget_s") or 0.0),
        node.get("ordered_digest") or "",
    )


def status_unresolved(node: dict) -> bool:
    s = str(node.get("status") or "")
    if s.startswith("PROOF_DEAD") or s in ("SOLVED", "EXHAUSTED", "KNOWN_CLOSED", "FAILED_CONTRACT"):
        return False
    return s in ("OPEN", "UNRESOLVED_TIME", "UNRESOLVED_UNIQUE", "GENERATION_UNRESOLVED_TIME", "LOWER_G_REOPENING", "")
