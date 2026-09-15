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
from spider.campaign_status import GENERATION_UNRESOLVED_TIME, classify_outcome, proof_dead_label
from spider.campaign_store import add_candidate, enqueue_job
from spider.campaign_worker import run_lean_job
from spider.incumbent import production_ceiling
from spider.f2_quality_frontier import (
    HARVEST_UNIQUE,
    apply_exact_final_deal,
    g123_ready_targets,
    harvest_f2_target,
    verify_g123_root,
)
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
        cost_ceiling=int(campaign.get("production_ceiling") or production_ceiling()),
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


def expand_f2_children(campaign: dict, node: dict, *, time_s: float = 8.0, max_unique: int = 12_000, suit: Optional[str] = None) -> dict:
    """Deepenable generation. Timeout is GENERATION_UNRESOLVED_TIME, never exhausted."""

    st = unpack_state(bytes.fromhex(node["ordered_digest"]))
    targets = g123_ready_targets(st, int(node["g"]))
    if suit:
        targets = [t for t in targets if t.get("suit") == suit] or [{"suit": suit, "operational_rank": 1}]
    if not targets:
        targets = [{"suit": "d", "operational_rank": 1}]
    prefix = as_actions(node.get("full_actions") or [])
    g123_like = {
        "g": node["g"],
        "ordered_digest": node["ordered_digest"],
        "prefix_actions": dump_actions(prefix),
    }
    n_new = 0
    n_dup = 0
    n_reopen = 0
    cheapest = None
    children = []
    n_raw = 0
    n_unique = 0
    stop = ""
    elapsed = 0.0
    unique_used = 0
    for tgt in targets:
        hv = harvest_f2_target(g123_like, tgt, time_s=float(time_s), unique=int(max_unique))
        n_raw += int(hv.get("n_raw") or 0)
        n_unique += int(hv.get("n_unique") or hv.get("n_f2") or 0)
        unique_used = max(unique_used, int(hv.get("unique") or 0))
        elapsed += float(hv.get("elapsed_s") or 0.0)
        stop = hv.get("stop_reason") or stop
        if hv.get("cheapest_g") is not None:
            cheapest = hv["cheapest_g"] if cheapest is None else min(cheapest, int(hv["cheapest_g"]))
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
                    "tactical_target": term.get("tactical_target") or tgt.get("suit"),
                    "tactical_actions": term.get("tactical_actions"),
                    "generation_budget_s": float(time_s),
                    "generation_unique": hv.get("unique"),
                },
            )
            stored = add_node(campaign, child)
            arrival = stored.get("arrival") or "new"
            if arrival == "new":
                n_new += 1
            elif arrival == "lower_g_reopening":
                n_reopen += 1
            else:
                n_dup += 1
            children.append(stored)
    outcome = GENERATION_UNRESOLVED_TIME if stop == "time limit" else (stop or "complete")
    rec = {
        "target_suit": suit or ",".join(t.get("suit") or "" for t in targets),
        "time_budget_s": float(time_s),
        "unique_budget": int(max_unique),
        "n_raw": n_raw,
        "n_unique": n_unique,
        "n_new": n_new,
        "n_duplicate": n_dup,
        "n_reopen": n_reopen,
        "cheapest_g": cheapest,
        "stop_reason": stop,
        "elapsed_s": elapsed,
        "outcome": outcome,
        "unique_used": unique_used,
    }
    node.setdefault("generation_runs", []).append(rec)
    node["generation_status"] = outcome
    node["deepest_generation_s"] = max(float(node.get("deepest_generation_s") or 0.0), float(time_s))
    if outcome == GENERATION_UNRESOLVED_TIME and node.get("status") not in ("SOLVED",):
        node["status"] = GENERATION_UNRESOLVED_TIME
    return {
        "children": children,
        "n_children": n_new,
        "n_new": n_new,
        "n_duplicate": n_dup,
        "n_reopen": n_reopen,
        "history": rec,
    }


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
    stored = add_node(campaign, child)
    if stored.get("n_deal") != 5 and stored.get("arrival") == "new":
        stored["n_deal"] = sum(1 for a in as_actions(stored.get("full_actions") or []) if is_deal(a))
    _attach_stockempty_candidate(campaign, stored)
    return stored


def bulk_sd5(campaign: dict) -> dict:
    """Apply exact SD5 to every eligible pre-SD5 F2. No one-node clicking."""

    n_new = 0
    n_skip = 0
    n_reuse = 0
    n_fail = 0
    for node in list(campaign.get("nodes") or []):
        if node.get("kind") != "PRE_STOCK" or int(node.get("stock_rows") or 0) != 1:
            continue
        has = any(
            node["id"] in (c.get("parent_ids") or []) and c.get("kind") == "STOCK_EMPTY"
            for c in campaign.get("nodes") or []
        )
        if has:
            n_skip += 1
            continue
        child = expand_sd5_child(campaign, node)
        if child is None:
            n_fail += 1
            continue
        if child.get("arrival") in ("duplicate", "lower_g_reopening"):
            n_reuse += 1
        else:
            n_new += 1
    return {"n_new": n_new, "n_skip": n_skip, "n_reuse": n_reuse, "n_fail": n_fail}


def proof_filter(campaign: dict) -> dict:
    from spider.incumbent import production_ceiling as live_ceiling

    ceiling = int(campaign.get("production_ceiling") or live_ceiling())
    n_dead = 0
    n_live = 0
    label = proof_dead_label(ceiling)
    for node in campaign.get("nodes") or []:
        if node.get("kind") not in ("STOCK_EMPTY", "SOLVED"):
            continue
        h = node.get("assembly_h")
        f = node.get("assembly_f")
        if f is None and h is not None:
            f = int(node["g"]) + int(h)
            node["assembly_f"] = f
        if f is None:
            continue
        if int(f) > ceiling:
            node.setdefault("proof", {})["proof_dead"] = True
            node["proof"]["ceiling"] = ceiling
            if node.get("status") != "SOLVED":
                node["status"] = label
                n_dead += 1
        else:
            n_live += 1
            node.setdefault("proof", {})["proof_dead"] = False
            node["proof"]["ceiling"] = ceiling
    return {"ceiling": ceiling, "proof_dead": n_dead, "proof_live": n_live, "label": label}


def evaluate_stockempty(campaign: dict, node: dict, *, time_s: float, max_unique: int, rss_mb: float = 2560.0) -> dict:
    ceiling = int(campaign.get("production_ceiling") or production_ceiling())
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
        summary = expand_f2_children(
            campaign,
            node,
            time_s=kwargs.get("time_s", 8.0),
            max_unique=kwargs.get("max_unique", HARVEST_UNIQUE),
            suit=kwargs.get("suit"),
        )
        ids = [c["id"] for c in summary.get("children") or []]
        return {"op": "expand_f2", "n_children": int(summary.get("n_new") or 0), "children": ids, "history": summary.get("history"), "n_duplicate": summary.get("n_duplicate")}
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
    st = str(node.get("status") or "")
    if st.startswith("PROOF_DEAD") or st in ("EXHAUSTED", "SOLVED", "KNOWN_CLOSED"):
        return None
    _attach_stockempty_candidate(campaign, node)
    cid = node.get("candidate_id")
    if not cid:
        return None
    return enqueue_job(
        campaign,
        cid,
        ceiling=int(campaign.get("production_ceiling") or production_ceiling()),
        time_s=float(time_s),
        max_unique=int(max_unique),
        round_n=round_n,
    )
