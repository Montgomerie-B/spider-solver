"""Import the persisted v0.84 F2 population into a portable campaign.

Loads the existing 279 F2 states, reconstructs exact post-stock identity
via exact SD5, deduplicates by physical identity at cheapest g, computes
h/f, marks proof-dead when g+h > production ceiling 186, and attaches
ancestry / prefix artefact references. Does not run the long campaign.
"""

from __future__ import annotations

import json

from spider.app_paths import research_json
from spider.campaign_closed import apply_closed_pruning, load_known_closed_registry
from spider.campaign_schedule import DEFAULT_ROUNDS
from spider.campaign_store import add_candidate, enqueue_job, new_campaign
from spider.f2_quality_frontier import apply_exact_final_deal

V084_ARTEFACT = "docs/research/f2_quality_frontier_v0_84.json"


def _v084_json() -> dict:
    path = research_json("f2_quality_frontier_v0_84.json")
    return json.loads(path.read_text(encoding="utf-8"))


def import_v084_population(*, ceiling: int = 186, enqueue_round1: bool = True, max_unique: int = 300_000) -> dict:
    data = _v084_json()
    raw_n = int(data.get("n_f2") or 0)
    g123 = data.get("g123") or {}
    prefix_artefact = {
        "artefact": V084_ARTEFACT,
        "g123_digest": g123.get("ordered_digest"),
        "g123_g": g123.get("g"),
        "g123_n_prefix": g123.get("n_prefix"),
        "note": "immutable prefix artefact; F2 harvest path is the pre_digest plus exact SD5",
    }
    actions_by_pre = {}
    n_deal_by_pre = {}
    pre_by_digest = {}

    def _take_pre(rec: dict) -> None:
        is_f2 = rec.get("class") == "F2_TERMINAL" or rec.get("pre_class") == "F2_TERMINAL" or int(rec.get("foundations") or 0) == 2
        if rec.get("pre_digest"):
            digest = rec["pre_digest"]
            if digest not in pre_by_digest:
                pre_by_digest[digest] = {
                    "ordered_digest": digest,
                    "g": rec.get("pre_g") or rec.get("g"),
                    "control_tag": rec.get("control_tag"),
                    "tactical_target": rec.get("tactical_target") or rec.get("target"),
                    "class": rec.get("pre_class") or rec.get("class") or "F2_TERMINAL",
                }
        if is_f2 and rec.get("ordered_digest") and rec.get("stock_rows") == 1:
            digest = rec["ordered_digest"]
            prev = pre_by_digest.get(digest)
            if prev is None or (rec.get("g") is not None and int(rec["g"]) < int(prev.get("g") or rec["g"])):
                pre_by_digest[digest] = {
                    "ordered_digest": digest,
                    "g": rec.get("g"),
                    "control_tag": rec.get("control_tag"),
                    "tactical_target": rec.get("tactical_target"),
                    "class": rec.get("class") or "F2_TERMINAL",
                }
        if rec.get("pre_digest") and rec.get("full_actions") and rec["pre_digest"] not in actions_by_pre:
            actions_by_pre[rec["pre_digest"]] = rec.get("full_actions")
            n_deal_by_pre[rec["pre_digest"]] = rec.get("n_deal")

    def _walk(obj) -> None:
        if isinstance(obj, dict):
            if obj.get("ordered_digest") or obj.get("pre_digest"):
                _take_pre(obj)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(data)
    pre = list(pre_by_digest.values())

    campaign = new_campaign(incumbent_g=187, ceiling=int(ceiling))
    campaign["source"] = "v0.84_f2_quality_frontier"
    campaign["schedule"] = [dict(r) for r in DEFAULT_ROUNDS]
    reconstructed = 0
    ancestry_fail = 0
    by_ident = {}
    for rec in pre:
        digest = rec.get("ordered_digest")
        if not digest:
            ancestry_fail += 1
            continue
        try:
            post = apply_exact_final_deal(
                {
                    "g": rec.get("g"),
                    "ordered_digest": digest,
                    "control_tag": rec.get("control_tag"),
                    "tactical_target": rec.get("tactical_target"),
                }
            )
            if not post.get("ok") or not post.get("post_digest"):
                ancestry_fail += 1
                continue
            ident = post.get("ident") or post.get("whole_game_identity")
            g = int(post["post_g"])
            h = int(post.get("assembly_h") or 0)
            f = int(post.get("assembly_f") or (g + h))
        except Exception:
            ancestry_fail += 1
            continue
        reconstructed += 1
        prev = by_ident.get(ident)
        if prev is not None and int(prev["g"]) <= g:
            continue
        full_actions = actions_by_pre.get(digest)
        by_ident[ident] = {
            "g": g,
            "ordered_digest": post["post_digest"],
            "ident": ident,
            "whole_game_identity": ident,
            "assembly_h": h,
            "assembly_f": f,
            "full_actions": full_actions,
            "n_deal": n_deal_by_pre.get(digest) or 5,
            "pre_digest": digest,
            "pre_g": rec.get("g"),
            "prefix_artefact": prefix_artefact,
            "label": rec.get("control_tag") or rec.get("tactical_target") or rec.get("class"),
            "proof_dead": f > int(ceiling),
            "source_experiment": "f2_quality_frontier_v0_84",
            "source_candidate_id": rec.get("control_tag") or digest[:16],
        }

    live = 0
    dead = 0
    for rec in by_ident.values():
        add_candidate(
            campaign,
            g=rec["g"],
            ordered_digest=rec["ordered_digest"],
            ident=rec["ident"],
            whole_game_identity=rec["whole_game_identity"],
            assembly_h=rec["assembly_h"],
            assembly_f=rec["assembly_f"],
            full_actions=rec.get("full_actions"),
            n_deal=rec.get("n_deal"),
            label=rec.get("label"),
            proof_dead=rec["proof_dead"],
            source_experiment=rec["source_experiment"],
            source_candidate_id=rec.get("source_candidate_id"),
            pre_digest=rec.get("pre_digest"),
            prefix_artefact=rec.get("prefix_artefact"),
        )
        campaign["candidates"][-1]["pre_g"] = rec.get("pre_g")
        if rec["proof_dead"]:
            dead += 1
        else:
            live += 1
            campaign["candidates"][-1]["schedule"] = {"round": 1, "time_s": 60}

    closed = load_known_closed_registry(ceiling=int(ceiling))
    campaign["closed_registry"] = list(closed.values())
    prune_stats = apply_closed_pruning(campaign["candidates"], closed, ceiling=int(ceiling))

    if enqueue_round1:
        for cand in campaign["candidates"]:
            if cand.get("proof_dead") and not cand.get("lower_g_reopening"):
                continue
            if cand.get("known_closed") and not cand.get("lower_g_reopening"):
                continue
            enqueue_job(
                campaign,
                cand["id"],
                ceiling=int(ceiling),
                time_s=60.0,
                max_unique=int(max_unique),
                round_n=1,
            )

    campaign["import_stats"] = {
        "raw_n_f2": raw_n,
        "n_persisted_pre": len(pre),
        "reconstructed": reconstructed,
        "unique_post_stock": len(by_ident),
        "proof_live": live,
        "proof_dead": dead,
        "ancestry_failures": ancestry_fail,
        "closed_pruned": prune_stats["closed_pruned"],
        "lower_g_reopenings": prune_stats["lower_g_reopenings"],
        "closed_registry_n": prune_stats["registry_n"],
        "round1_jobs": sum(1 for j in campaign.get("jobs") or [] if j.get("round") == 1),
    }
    return campaign
