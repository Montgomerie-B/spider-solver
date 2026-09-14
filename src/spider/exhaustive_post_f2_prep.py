"""v0.89 exhaustive post-Deal evaluation of the v0.88 preparation archive.

Search semantics are frozen. ARCHIVE_EVAL is ALL Deal-legal candidates.
Canonical 172 is not read.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import prep_cost_band
from spider.proof_aware_tactical_bridge import ExactHCache, is_proof_viable
from spider.research_actions import apply_action, as_actions, dump_actions, rss_mb, stock_rows, tableau_actions
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.whole_game_epoch_scheduler import SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V088_JSON = ROOT / "docs" / "research" / "post_f2_predeal_preparation_v0_88.json"
EXPECTED_A = 50119
EXPECTED_B = 37408
EXPECTED_TOTAL = 87527
ARCHIVE_EVAL_ALL = "ALL"
ROLLOUT_N = 16
STAGE_A_S = 10.0
STAGE_B_S = 20.0
STAGE_B_N = 4
PORTFOLIO_MAX = 24
TOTAL_S = SEARCH_TIME_S
F_BUCKETS = (
    ("le169", lambda f: int(f) <= 169),
    ("170", lambda f: int(f) == 170),
    ("171", lambda f: int(f) == 171),
    ("172", lambda f: int(f) == 172),
    ("173", lambda f: int(f) == 173),
    ("174", lambda f: int(f) == 174),
    ("175_176", lambda f: 175 <= int(f) <= 176),
    ("177_180", lambda f: 177 <= int(f) <= 180),
    ("181_186", lambda f: 181 <= int(f) <= 186),
    ("gt186", lambda f: int(f) > 186),
)
WINNER_KEYS = (
    ("lowest_f", lambda r: (int(r["assembly_f"]), int(r["post_g"]), r.get("post_digest") or "")),
    ("lowest_h", lambda r: (int(r["assembly_h"]), int(r["post_g"]), r.get("post_digest") or "")),
    ("lowest_g", lambda r: (int(r["post_g"]), int(r["assembly_f"]), r.get("post_digest") or "")),
    ("greatest_slack", lambda r: (-int(r["slack"]), int(r["post_g"]), r.get("post_digest") or "")),
    ("greatest_F", lambda r: (-int(r["foundations"]), int(r["assembly_f"]), int(r["post_g"]))),
    ("greatest_mobility", lambda r: (-int(r["legal"]), int(r["assembly_f"]), int(r["post_g"]))),
    ("most_empties", lambda r: (-int(r["empty_n"]), int(r["assembly_f"]), int(r["post_g"]))),
    ("lowest_mixed", lambda r: (int(r["mixed_suit_boundaries"]), int(r["assembly_f"]), int(r["post_g"]))),
    ("lowest_visible_runs", lambda r: (int(r["visible_runs"]), int(r["assembly_f"]), int(r["post_g"]))),
)


def archive_mode() -> str:
    """v0.88 JSON stored counts and an 80-state sample, not 87k digests."""

    if not V088_JSON.exists():
        return "ARCHIVE_REGENERATED"
    data = json.loads(V088_JSON.read_text(encoding="utf-8"))
    persisted = data.get("candidates") or data.get("archive") or data.get("prep_candidates")
    n_persisted = len(persisted) if isinstance(persisted, list) else 0
    n_reported = int(data.get("prep_a_n") or 0) + int(data.get("prep_b_n") or 0)
    if n_persisted >= EXPECTED_TOTAL - 10 and n_reported >= EXPECTED_TOTAL - 10:
        return "ARCHIVE_REUSED"
    return "ARCHIVE_REGENERATED"


def f_bucket(f: int) -> str:
    for name, pred in F_BUCKETS:
        if pred(int(f)):
            return name
    return "gt186"


def bucket_counts(posts: Sequence[dict]) -> Dict[str, int]:
    c = {name: 0 for name, _ in F_BUCKETS}
    for rec in posts:
        c[f_bucket(int(rec["assembly_f"]))] += 1
    return c


def bucket_counts_grouped(posts: Sequence[dict], key: str) -> Dict[str, Dict[str, int]]:
    groups: Dict[str, Dict[str, int]] = {}
    for rec in posts:
        k = str(rec.get(key) or "unknown")
        if k not in groups:
            groups[k] = {name: 0 for name, _ in F_BUCKETS}
        groups[k][f_bucket(int(rec["assembly_f"]))] += 1
    return groups


def any_f_lt_171(posts: Sequence[dict]) -> bool:
    return any(int(r.get("assembly_f") or 10**9) < 171 for r in posts)


def posts_at_f(posts: Sequence[dict], f: int) -> List[dict]:
    return [r for r in posts if int(r.get("assembly_f") or 0) == int(f)]


def exhaustive_post_deal(cands: Sequence[dict], *, cache: Optional[ExactHCache] = None) -> dict:
    """Deal every candidate. h/f only for cheapest-g unique post identities."""

    cache = cache or ExactHCache()
    winners: Dict[str, dict] = {}
    t_deal = 0.0
    t_dedup = 0.0
    n_eval = 0
    n_illegal = 0
    peak = rss_mb()
    t0_all = time.perf_counter()
    for rec in cands:
        t0 = time.perf_counter()
        try:
            st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        except Exception:
            n_illegal += 1
            continue
        if stock_rows(st) != 1 or not st.can_deal():
            n_illegal += 1
            continue
        apply_action(st, ("deal",))
        g = int(rec["g"]) + 1
        ident = pack_whole_game_identity(st).hex()
        t_deal += time.perf_counter() - t0
        n_eval += 1
        t1 = time.perf_counter()
        prev = winners.get(ident)
        if prev is not None:
            conv = int(prev.get("convergence") or 1) + 1
            if int(g) >= int(prev["post_g"]):
                prev["convergence"] = conv
                t_dedup += time.perf_counter() - t1
                continue
        else:
            conv = 1
        winners[ident] = {
            "ident": ident,
            "whole_game_identity": ident,
            "post_g": g,
            "pre_g": int(rec["g"]),
            "source": rec.get("source"),
            "prep_delta_g": rec.get("prep_delta_g"),
            "prep_band": rec.get("prep_band") or prep_cost_band(int(rec.get("prep_delta_g") or 0)),
            "pre_digest": rec["ordered_digest"],
            "node": rec.get("node"),
            "convergence": conv,
            "_state": st,
        }
        t_dedup += time.perf_counter() - t1
        if n_eval % 10000 == 0:
            peak = max(x for x in (peak, rss_mb()) if x is not None) if peak is not None or rss_mb() is not None else peak
            print(f"  eval {n_eval}/{len(cands)} unique={len(winners)}", flush=True)
    t_h = 0.0
    posts = []
    for ident, rec in winners.items():
        st = rec.pop("_state")
        t0 = time.perf_counter()
        h = int(cache(st, int(rec["post_g"])))
        t_h += time.perf_counter() - t0
        g = int(rec["post_g"])
        f = g + h
        s = current_tableau_summary(st)
        tel = structural_telemetry(st)
        rec.update(
            {
                "ok": stock_rows(st) == 0,
                "stock_rows": stock_rows(st),
                "post_digest": pack_state(st).hex(),
                "foundations": len(st.foundations),
                "face_down": int(s["face_down"]),
                "empty_n": int(s["empty_n"]),
                "legal": len(tableau_actions(st)),
                "legal_tableau": len(tableau_actions(st)),
                "boundaries": int(s.get("visible_runs") or 0),
                "visible_runs": tel["visible_runs"],
                "visible_components": tel["visible_components"],
                "mixed_suit_boundaries": tel["mixed_suit_boundaries"],
                "assembly_h": h,
                "assembly_f": f,
                "slack": assembly_slack(BRIDGE_CEILING, f),
                "viable": is_proof_viable(g, h, BRIDGE_CEILING),
                "post_class": "PROOF_VIABLE" if is_proof_viable(g, h, BRIDGE_CEILING) else "PROOF_DEAD",
            }
        )
        posts.append(rec)
    conv = [int(r.get("convergence") or 1) for r in posts]
    elapsed = time.perf_counter() - t0_all
    cur = rss_mb()
    if peak is None:
        peak = cur
    elif cur is not None:
        peak = max(peak, cur)
    return {
        "n_pre": len(cands),
        "n_eval": n_eval,
        "n_illegal": n_illegal,
        "n_unique_post": len(posts),
        "posts": posts,
        "t_deal_s": t_deal,
        "t_h_s": t_h,
        "t_dedup_s": t_dedup,
        "elapsed_s": elapsed,
        "eval_per_s": (n_eval / elapsed) if elapsed > 0 else None,
        "h_cache": cache.stats(),
        "convergence_max": 0 if not conv else max(conv),
        "convergence_mean": 0.0 if not conv else sum(conv) / float(len(conv)),
        "n_viable": sum(1 for r in posts if r.get("viable")),
        "n_dead": sum(1 for r in posts if not r.get("viable")),
        "peak_rss_mb": peak,
    }


def exhaustive_pareto(records: Sequence[dict]) -> List[dict]:
    pool = [r for r in records if r.get("viable") and r.get("ok")]
    pool = sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r.get("post_digest") or ""))
    frontier: List[dict] = []
    for rec in pool:
        if any(_ex_better(other, rec) for other in frontier):
            continue
        frontier = [other for other in frontier if not _ex_better(rec, other)]
        frontier.append(rec)
    return sorted(frontier, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r.get("post_digest") or ""))


def _ex_not_worse(a: dict, b: dict) -> bool:
    return (
        int(a["post_g"]) <= int(b["post_g"])
        and int(a["assembly_h"]) <= int(b["assembly_h"])
        and int(a["assembly_f"]) <= int(b["assembly_f"])
        and int(a["slack"]) >= int(b["slack"])
        and int(a["foundations"]) >= int(b["foundations"])
        and int(a["face_down"]) <= int(b["face_down"])
        and int(a["empty_n"]) >= int(b["empty_n"])
        and int(a["legal"]) >= int(b["legal"])
        and int(a["visible_runs"]) <= int(b["visible_runs"])
        and int(a["mixed_suit_boundaries"]) <= int(b["mixed_suit_boundaries"])
    )


def _ex_better(a: dict, b: dict) -> bool:
    if not _ex_not_worse(a, b):
        return False
    return (
        int(a["post_g"]) < int(b["post_g"])
        or int(a["assembly_h"]) < int(b["assembly_h"])
        or int(a["assembly_f"]) < int(b["assembly_f"])
        or int(a["slack"]) > int(b["slack"])
        or int(a["foundations"]) > int(b["foundations"])
        or int(a["face_down"]) < int(b["face_down"])
        or int(a["empty_n"]) > int(b["empty_n"])
        or int(a["legal"]) > int(b["legal"])
        or int(a["visible_runs"]) < int(b["visible_runs"])
        or int(a["mixed_suit_boundaries"]) < int(b["mixed_suit_boundaries"])
    )


def v088_sample_digests() -> Set[str]:
    if not V088_JSON.exists():
        return set()
    data = json.loads(V088_JSON.read_text(encoding="utf-8"))
    out = set()
    for rec in list(data.get("selected") or []) + list(data.get("pareto") or []) + list(data.get("evaluated") or []):
        d = rec.get("post_digest")
        if d:
            out.add(d)
    return out


def compare_sample_coverage(pareto: Sequence[dict], posts: Sequence[dict], sample: Set[str], min_f: Optional[int]) -> dict:
    captured = [r for r in pareto if r.get("post_digest") in sample]
    missed = [r for r in pareto if r.get("post_digest") not in sample]
    best_f_posts = [] if min_f is None else [r for r in posts if int(r["assembly_f"]) == int(min_f)]
    f171 = posts_at_f(posts, 171)
    f171_mob = None
    if f171:
        f171_mob = max(f171, key=lambda r: (int(r["legal"]), -int(r["post_g"]), r.get("post_digest") or ""))
    return {
        "pareto_n": len(pareto),
        "pareto_captured": len(captured),
        "pareto_missed": len(missed),
        "best_f_sampled": any(r.get("post_digest") in sample for r in best_f_posts),
        "f171_mobility_sampled": bool(f171_mob and f171_mob.get("post_digest") in sample),
        "sample_n": len(sample),
    }


def analyze_f171(posts: Sequence[dict]) -> dict:
    rows = posts_at_f(posts, 171)
    if not rows:
        return {"n": 0}
    return {
        "n": len(rows),
        "sources": dict(Counter(r.get("source") for r in rows)),
        "bands": dict(Counter(r.get("prep_band") for r in rows)),
        "g_h": sorted({(int(r["post_g"]), int(r["assembly_h"])) for r in rows}),
        "legal_min": min(int(r["legal"]) for r in rows),
        "legal_max": max(int(r["legal"]) for r in rows),
        "empty_min": min(int(r["empty_n"]) for r in rows),
        "empty_max": max(int(r["empty_n"]) for r in rows),
        "visible_min": min(int(r["visible_runs"]) for r in rows),
        "visible_max": max(int(r["visible_runs"]) for r in rows),
        "mixed_min": min(int(r["mixed_suit_boundaries"]) for r in rows),
        "mixed_max": max(int(r["mixed_suit_boundaries"]) for r in rows),
    }


def best_post_states(posts: Sequence[dict]) -> Dict[str, dict]:
    if not posts:
        return {}
    out = {}
    for name, key in WINNER_KEYS:
        rec = min(posts, key=key)
        out[name] = rec
    return out


def slim_winner(r: dict) -> dict:
    return {
        k: r.get(k)
        for k in (
            "source",
            "prep_delta_g",
            "prep_band",
            "pre_g",
            "post_g",
            "foundations",
            "assembly_h",
            "assembly_f",
            "slack",
            "legal",
            "empty_n",
            "visible_runs",
            "mixed_suit_boundaries",
            "face_down",
            "viable",
            "post_class",
            "selection_role",
            "post_digest",
            "ident",
            "convergence",
            "pre_digest",
        )
    }


def select_exhaustive_rollout(posts: Sequence[dict], controls: Sequence[dict], *, k: int = ROLLOUT_N) -> List[dict]:
    pool = [r for r in posts if r.get("viable")]
    picks: List[dict] = []
    seen: Set[str] = set()

    def take(rec, role):
        if rec is None:
            return
        ident = rec.get("ident")
        if not ident or ident in seen:
            return
        seen.add(ident)
        item = dict(rec)
        item["selection_role"] = role
        picks.append(item)

    for c in controls:
        take(c, "immediate_deal")
    if pool:
        take(min(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]))), "lowest_f")
        f171 = posts_at_f(pool, 171)
        if f171:
            take(max(f171, key=lambda r: (int(r["legal"]), -int(r["post_g"]))), "f171_mobility")
            take(max(f171, key=lambda r: (int(r["empty_n"]), int(r["legal"]))), "f171_empties")
            take(min(f171, key=lambda r: (int(r["mixed_suit_boundaries"]), int(r["visible_runs"]))), "f171_topology")
            take(min(f171, key=lambda r: (int(r["visible_runs"]), int(r["assembly_f"]))), "f171_runs")
        f172 = posts_at_f(pool, 172)
        if f172:
            take(max(f172, key=lambda r: (int(r["legal"]), -int(r["post_g"]))), "f172_mobility")
            take(min(f172, key=lambda r: (int(r["mixed_suit_boundaries"]), int(r["visible_runs"]))), "f172_topology")
        take(max(pool, key=lambda r: (int(r["legal"]), -int(r["assembly_f"]))), "highest_mobility")
        take(max(pool, key=lambda r: (int(r["empty_n"]), -int(r["assembly_f"]))), "most_empties")
        take(min(pool, key=lambda r: (int(r["mixed_suit_boundaries"]), int(r["assembly_f"]))), "lowest_mixed")
        take(min(pool, key=lambda r: (int(r["visible_runs"]), int(r["assembly_f"]))), "lowest_runs")
        take(min(pool, key=lambda r: (int(r["assembly_h"]), int(r["post_g"]))), "lowest_h")
        pareto = exhaustive_pareto(pool)
        if pareto:
            mid = pareto[len(pareto) // 2]
            take(mid, "pareto_balanced")
        for src in ("NEW_G128_F2", "INCUMBENT_G129_F2"):
            srcs = [r for r in pool if r.get("source") == src]
            if srcs:
                take(min(srcs, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]))), f"src_{src}")
        for rec in sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r.get("post_digest") or "")):
            if len(picks) >= int(k):
                break
            take(rec, "fill")
    return picks[: int(k)]


def attach_full_actions(post: dict, harvests: dict) -> dict:
    src = post.get("source")
    h = harvests.get(src) or {}
    kr = h.get("kernel")
    prefix = as_actions(h.get("prefix") or [])
    node = post.get("node")
    path = []
    if kr is not None and node:
        path = kr.reconstruct(int(node))
    post = dict(post)
    existing = post.get("full_actions")
    if existing:
        return post
    post["full_actions"] = dump_actions(prefix + path + [("deal",)])
    return post


def choose_exhaustive_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "EXHAUSTIVE_PREP_CONTRACT_FAILURE", p.get("contract_reason") or "archive/state/rules/accounting/firewall failure"
    if p.get("archive_contract_fail"):
        return "EXHAUSTIVE_PREP_CONTRACT_FAILURE", p.get("contract_reason") or "archive totals disagree with v0.88"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "EXHAUSTIVE_PREP_COST_IMPROVED", f"solved at g={best}"
    if p.get("any_f_lt_171"):
        return "EXHAUSTIVE_PREP_FINDS_LOWER_F", f"min_f={p.get('min_f')}"
    if p.get("superior_prep"):
        winner_f = p.get("superior_f")
        if winner_f is not None and int(winner_f) == 171:
            return "EXHAUSTIVE_PREP_SAME_F_TOPOLOGY_WINS", p.get("superior_reason") or "same-f topology beats immediate Deal"
        return "EXHAUSTIVE_PREP_FINDS_SUPERIOR_ROOT", p.get("superior_reason") or "prepared post-SD5 state materially superior to the controls"
    if p.get("search_limited_downstream"):
        return "EXHAUSTIVE_PREP_SEARCH_LIMITED", "a genuinely superior new candidate remains unresolved under downstream resource limits"
    return "EXHAUSTIVE_PREP_NO_GAIN", "full generated archive evaluated; no preparation materially beats immediate Deal"


def next_recommendation(verdict: str) -> str:
    if verdict == "EXHAUSTIVE_PREP_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "EXHAUSTIVE_PREP_FINDS_LOWER_F":
        return "Focus the next endgame on the lowest-f prepared post-SD5 root."
    if verdict == "EXHAUSTIVE_PREP_SAME_F_TOPOLOGY_WINS":
        return "Focus the next endgame on the stronger same-f171 prepared topology."
    if verdict == "EXHAUSTIVE_PREP_FINDS_SUPERIOR_ROOT":
        return "Make the prepared post-SD5 state the next focused endgame control. Do not move upstream yet."
    if verdict == "EXHAUSTIVE_PREP_SEARCH_LIMITED":
        return "Keep the stronger prepared root as the focused control; do not widen wall time."
    if verdict == "EXHAUSTIVE_PREP_NO_GAIN":
        return "Move upstream to rows=1 before F2: strategic F1 preparation → tactical F2 cash-out → exact SD5."
    return "Do not promote; diagnose the contract."
