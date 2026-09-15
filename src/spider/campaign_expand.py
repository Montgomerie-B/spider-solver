"""Dispatch expand/evaluate/deepen to existing proven engines.

STOCK_EMPTY -> run_stockempty_consequence
PRE_STOCK / g123 -> harvest_f2_target
OPENING / EPOCH -> search_epoch_portfolio
Exact SD5 is an explicit child transition, never implicit.
"""

from __future__ import annotations

from typing import Optional

from spider.campaign_nodes import (
    add_node,
    classify_kind,
    make_node,
    opening_node,
    record_node_run,
)
from spider.campaign_status import classify_outcome
from spider.campaign_store import add_candidate, enqueue_job
from spider.campaign_worker import run_lean_job
from spider.f2_quality_frontier import apply_exact_final_deal, g123_ready_targets, harvest_f2_target, verify_g123_root
from spider.packed_state import unpack_state
from spider.research_actions import as_actions, dump_actions, is_deal
from spider.whole_game_epoch_scheduler import search_epoch_portfolio


def create_opening_campaign(campaign: dict) -> dict:
    node = opening_node()
    add_node(campaign, node)
    campaign["root_id"] = node["id"]
    campaign["kind"] = "OPENING"
    return node


def create_g123_campaign(campaign: dict) -> dict:
    opening = opening_node()
    add_node(campaign, opening)
    g123 = verify_g123_root()
    if not g123.get("ok"):
        raise ValueError(g123.get("reason") or "g123_failed")
    node = make_node(
        g=int(g123["g"]),
        ordered_digest=g123["ordered_digest"],
        full_actions=g123.get("prefix_actions") or [],
        kind="CHECKPOINT",
        parent_ids=[opening["id"]],
        source="known_g123",
        label="g123 CHECKPOINT F1 rows=1",
        ancestry_verified=True,
        extra={"stock_rows": 1, "foundations": 1, "face_down": 2},
    )
    add_node(campaign, node)
    campaign["root_id"] = opening["id"]
    campaign["g123_id"] = node["id"]
    campaign["kind"] = "G123"
    return node


def _attach_stockempty_candidate(campaign: dict, node: dict) -> None:
    if node.get("kind") != "STOCK_EMPTY" or node.get("candidate_id"):
        return
    rec = add_candidate(
        campaign,
        g=int(node["g"]),
        ordered_digest=node["ordered_digest"],
        ident=node.get("ident"),
        full_actions=node.get("full_actions"),
        n_deal=node.get("n_deal"),
        source_experiment=node.get("source"),
        source_candidate_id=node.get("id"),
    )
    node["candidate_id"] = rec["id"]


def expand_opening(campaign: dict, node: dict, *, time_s: float = 3.0, max_unique: int = 1200) -> list:
    harvested = []

    def on_harvest(_rows, _picked, _cats, attached):
        harvested.extend(attached)

    search_epoch_portfolio(
        time_limit_s=float(time_s),
        max_unique=int(max_unique),
        portfolio_width=8,
        cost_ceiling=int(campaign.get("production_ceiling") or 186),
        on_harvest=on_harvest,
        initial_roots=[
            {
                "g": int(node["g"]),
                "ordered_digest": node["ordered_digest"],
                "full_actions": node.get("full_actions") or [],
                "whole_game_identity": node.get("whole_game_identity") or node.get("ident"),
            }
        ],
    )
    children = []
    seen = set()
    for rec in harvested:
        digest = rec.get("ordered_digest")
        if not digest or digest in seen:
            continue
        if not rec.get("full_actions"):
            continue
        seen.add(digest)
        child = make_node(
            g=int(rec["g"]),
            ordered_digest=digest,
            full_actions=rec.get("full_actions"),
            parent_ids=[node["id"]],
            source="epoch_portfolio",
            ancestry_verified=True,
            extra={"portfolio_cat": rec.get("portfolio_cat")},
        )
        add_node(campaign, child)
        _attach_stockempty_candidate(campaign, child)
        children.append(child)
        if len(children) >= 12:
            break
    return children


def expand_f2_children(campaign: dict, node: dict, *, time_s: float = 8.0, max_unique: int = 12_000, suit: Optional[str] = None) -> list:
    st = unpack_state(bytes.fromhex(node["ordered_digest"]))
    targets = g123_ready_targets(st, int(node["g"]))
    if suit:
        targets = [t for t in targets if t.get("suit") == suit] or [{"suit": suit, "operational_rank": 1}]
    if not targets:
        targets = [{"suit": "d", "operational_rank": 1}]
    children = []
    prefix = as_actions(node.get("full_actions") or [])
    g123_like = {
        "g": node["g"],
        "ordered_digest": node["ordered_digest"],
        "prefix_actions": dump_actions(prefix),
    }
    per = float(time_s) / float(max(1, len(targets)))
    for tgt in targets:
        hv = harvest_f2_target(g123_like, tgt, time_s=per, unique=int(max_unique))
        for term in hv.get("terminals") or []:
            if not term.get("full_actions"):
                continue
            child = make_node(
                g=int(term["g"]),
                ordered_digest=term["ordered_digest"],
                full_actions=term["full_actions"],
                kind="PRE_STOCK",
                parent_ids=[node["id"]],
                source="f2_harvest",
                ancestry_verified=True,
                extra={
                    "tactical_target": term.get("tactical_target"),
                    "tactical_actions": term.get("tactical_actions"),
                    "generation_budget_s": per,
                    "generation_unique": hv.get("unique"),
                },
            )
            add_node(campaign, child)
            children.append(child)
    return children


def expand_sd5_child(campaign: dict, node: dict) -> Optional[dict]:
    if int(node.get("stock_rows") or 0) != 1:
        return None
    post = apply_exact_final_deal(
        {
            "g": node["g"],
            "ordered_digest": node["ordered_digest"],
            "full_actions": node.get("full_actions"),
        }
    )
    if not post.get("ok"):
        return None
    child = make_node(
        g=int(post["post_g"]),
        ordered_digest=post["post_digest"],
        full_actions=post.get("full_actions"),
        kind="STOCK_EMPTY",
        parent_ids=[node["id"]],
        source="exact_sd5",
        ancestry_verified=True,
        extra={"assembly_h": post.get("assembly_h"), "assembly_f": post.get("assembly_f")},
    )
    add_node(campaign, child)
    _attach_stockempty_candidate(campaign, child)
    return child


def evaluate_stockempty(campaign: dict, node: dict, *, time_s: float, max_unique: int, rss_mb: float = 2560.0) -> dict:
    ceiling = int(campaign.get("production_ceiling") or 186)
    job = {
        "id": f"eval_{node['id'][:8]}",
        "candidate_id": node.get("candidate_id") or node["id"],
        "g": node["g"],
        "ordered_digest": node["ordered_digest"],
        "ident": node.get("ident"),
        "assembly_h": node.get("assembly_h"),
        "ceiling": ceiling,
        "time_s": float(time_s),
        "max_unique": int(max_unique),
        "stop_on_first_terminal": True,
    }
    result = run_lean_job(job, rss_abort_mb=float(rss_mb))
    outcome = classify_outcome(result, ceiling=ceiling, assembly_f=node.get("assembly_f"))
    result["outcome"] = outcome
    record_node_run(node, {**result, "time_s": time_s, "outcome": outcome})
    if outcome == "SOLVED" and result.get("terminal_actions") and node.get("full_actions"):
        from spider.campaign_promote import reconstruct_and_replay
        replay = reconstruct_and_replay(node, result)
        result["replay"] = replay
        if replay.get("ok"):
            node["kind"] = "SOLVED"
            node["status"] = "SOLVED"
            node["solved_full_actions"] = replay.get("full_actions")
    return result


def expand_node(campaign: dict, node: dict, **kwargs) -> dict:
    kind = node.get("kind")
    if kind in ("OPENING", "EPOCH"):
        children = expand_opening(campaign, node, time_s=kwargs.get("time_s", 3.0), max_unique=kwargs.get("max_unique", 1200))
        return {"op": "expand_opening", "n_children": len(children), "children": [c["id"] for c in children]}
    if kind in ("CHECKPOINT", "PRE_STOCK") and int(node.get("stock_rows") or 0) == 1:
        if kwargs.get("sd5"):
            child = expand_sd5_child(campaign, node)
            return {"op": "sd5", "child": None if child is None else child["id"]}
        children = expand_f2_children(
            campaign,
            node,
            time_s=kwargs.get("time_s", 8.0),
            max_unique=kwargs.get("max_unique", 12_000),
            suit=kwargs.get("suit"),
        )
        return {"op": "expand_f2", "n_children": len(children), "children": [c["id"] for c in children]}
    if kind == "STOCK_EMPTY":
        return evaluate_node(campaign, node, **kwargs)
    return {"op": "noop", "reason": f"no expander for {kind}"}


def evaluate_node(campaign: dict, node: dict, **kwargs) -> dict:
    if node.get("kind") == "STOCK_EMPTY" or int(node.get("stock_rows") or 0) == 0:
        _attach_stockempty_candidate(campaign, node)
        result = evaluate_stockempty(
            campaign,
            node,
            time_s=float(kwargs.get("time_s") or 8.0),
            max_unique=int(kwargs.get("max_unique") or 20_000),
            rss_mb=float(kwargs.get("rss_mb") or 2560.0),
        )
        return {"op": "evaluate_stockempty", "outcome": result.get("outcome"), "result": result}
    return expand_node(campaign, node, **kwargs)


def deepen_node(campaign: dict, node: dict, *, time_s: float, max_unique: int = 300_000) -> dict:
    return evaluate_node(campaign, node, time_s=time_s, max_unique=max_unique)


def enqueue_deepen(campaign: dict, node: dict, *, time_s: float, max_unique: int, round_n: Optional[int] = None) -> Optional[dict]:
    _attach_stockempty_candidate(campaign, node)
    cid = node.get("candidate_id")
    if not cid:
        return None
    return enqueue_job(
        campaign,
        cid,
        ceiling=int(campaign.get("production_ceiling") or 186),
        time_s=float(time_s),
        max_unique=int(max_unique),
        round_n=round_n,
    )
