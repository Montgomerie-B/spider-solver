"""v0.79 bounded F3→F4 tactical bridge from the v0.78 g141 state.

Does not change whole-game scheduling, rollout integration, or rows=1
tactical selection. Canonical 172 is not read. Continuation-table suffixes
are not used during search. Digest is loaded from the v0.78 artefact.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.foundation_cashout import (
    is_target_cashout,
    search_foundation_cashout,
    suit_foundation_count,
)
from spider.g128_focused_endgame import FocusedSnapshotTracker
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW
from spider.metrics import replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import (
    apply_action,
    as_actions,
    dump_actions,
    face_down_count,
    is_deal,
    step_cost,
    stock_rows,
    tableau_actions,
)
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V078_JSON = ROOT / "docs" / "research" / "g128_focused_endgame_v0_78.json"

BRIDGE_CEILING = 186
STAGE_A_S = 60.0
STAGE_A_UNIQUE = 100_000
STAGE_B_S = 60.0
STAGE_B_N = 2
STAGE_B_UNIQUE = 100_000
TACTICAL_BUDGET_S = 360.0
F4_PER_TARGET = 8
F4_PORTFOLIO_MAX = 16
TOTAL_S = SEARCH_TIME_S
# kept for provenance-only recovery after a complete candidate
RECOVER_S = 180.0
RECOVER_UNIQUE = 200_000


def assembly_slack(ceiling: int, f: int) -> int:
    """Established convention: slack = ceiling - f. Positive means under ceiling."""

    return int(ceiling) - int(f)


def load_g141_record() -> dict:
    data = json.loads(V078_JSON.read_text(encoding="utf-8"))
    for rec in data.get("frontier_list") or []:
        if int(rec.get("F") or rec.get("foundations") or 0) == 3 and int(rec.get("g") or 0) == 141:
            return dict(rec)
    raise KeyError("v0.78 cheapest F3 g=141 record missing")


def expected_g141_digest() -> str:
    return load_g141_record()["ordered_digest"]


def inspect_f3_state(digest: Optional[str] = None, g: int = 141) -> dict:
    digest = digest or expected_g141_digest()
    state = unpack_state(bytes.fromhex(digest))
    s = current_tableau_summary(state)
    ranked = rank_ready_suits(state, g=g)
    h = int(stock_empty_assembly_h(state, g))
    f = int(g) + h
    counts: Dict[str, int] = {}
    for suit in s["foundation_suits"]:
        counts[suit] = counts.get(suit, 0) + 1
    remaining = []
    for i, rec in enumerate(ranked.get("ranked") or []):
        suit = rec["suit"]
        remaining.append(
            {
                "suit": suit,
                "operational_rank": i + 1,
                "already_founded": int(counts.get(suit) or 0),
                "target_foundations_before": int(suit_foundation_count(state, suit)),
                "cover": rec.get("cover"),
                "blockers": rec.get("relevant_blockers"),
                "inaccessible_joins": rec.get("inaccessible_joins"),
                "k_access": rec.get("k_min_blockers"),
                "a_access": rec.get("a_min_blockers"),
                "gap": rec.get("gap"),
                "merge_edges": rec.get("legal_merge_edges"),
                "buried_components": rec.get("buried_components"),
                "exposed_components": rec.get("exposed_components"),
                "movable_exposed": rec.get("movable_exposed"),
            }
        )
    return {
        "ok": (
            stock_rows(state) == 0
            and len(state.foundations) == 3
            and int(s["face_down"]) == 2
            and int(s["empty_n"]) == 2
        ),
        "g": int(g),
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(state)),
        "boundaries": int(s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": f,
        "slack": assembly_slack(BRIDGE_CEILING, f),
        "n_ready": int(ranked.get("n_ready") or 0),
        "ready_suits": list(ranked.get("ready_suits") or []),
        "best_suit": ranked.get("best_suit"),
        "second_suit": ranked.get("second_suit"),
        "remaining_targets": remaining,
        "ordered_digest": digest,
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "can_deal": bool(state.can_deal()),
    }


def verify_g141_root() -> dict:
    """Load v0.78 artefact, unpack, recompute. Digest is not a policy constant."""

    rec = load_g141_record()
    digest = rec.get("ordered_digest")
    if not digest:
        return {"ok": False, "reason": "missing_digest", "record": rec}
    info = inspect_f3_state(digest, g=141)
    expected = {
        "g": 141,
        "foundations": 3,
        "assembly_h": 33,
        "assembly_f": 174,
        "face_down": 2,
        "empty_n": 2,
        "legal_tableau": 41,
        "slack": 12,
    }
    mismatches = {
        k: {"expected": v, "got": info.get(k)}
        for k, v in expected.items()
        if info.get(k) != v
    }
    rec_mismatch = []
    if int(rec.get("h") or rec.get("assembly_h") or 0) != 33:
        rec_mismatch.append("h")
    if int(rec.get("f") or rec.get("assembly_f") or 0) != 174:
        rec_mismatch.append("f")
    if int(rec.get("legal") or rec.get("legal_tableau") or 0) != 41:
        rec_mismatch.append("legal")
    info["boundaries_recorded"] = rec.get("boundaries") or rec.get("boundaries_total")
    info["boundaries_note"] = (
        "v0.78 stored harvest boundaries=28; independent visible_runs on the same digest is "
        f"{info.get('boundaries')}"
    )
    ok = info.get("ok") and not mismatches
    info["ok"] = bool(ok)
    info["mismatches"] = mismatches
    info["record_mismatch"] = rec_mismatch
    info["reason"] = None if ok else "g141_recompute_mismatch"
    info["record"] = {k: rec.get(k) for k in rec if k != "full_actions"}
    return info


def replay_from_f3(digest: str, root_g: int, actions) -> dict:
    state = unpack_state(bytes.fromhex(digest))
    g = int(root_g)
    path = as_actions(actions)
    if any(is_deal(a) for a in path):
        return {"ok": False, "reason": "deal_in_tactical"}
    for action in path:
        g += int(step_cost(state, action))
        apply_action(state, action)
    return {
        "ok": True,
        "g": g,
        "foundations": len(state.foundations),
        "stock_rows": stock_rows(state),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "state": state,
    }


class _HObserver:
    def __init__(self) -> None:
        self.min_h: Optional[int] = None
        self.min_f: Optional[int] = None

    def __call__(self, progress, st, g, node_i) -> None:
        if stock_rows(st) != 0:
            return
        h = int(stock_empty_assembly_h(st, int(g)))
        f = int(g) + h
        self.min_h = h if self.min_h is None else min(self.min_h, h)
        self.min_f = f if self.min_f is None else min(self.min_f, f)


def _probe_one(f3: dict, target: dict, *, time_s: float, unique: int, stage: str) -> dict:
    suit = target["suit"]
    before = int(target["target_foundations_before"])
    obs = _HObserver()
    t0 = time.perf_counter()
    result = search_foundation_cashout(
        ordered_digest=f3["ordered_digest"],
        root_g=int(f3["g"]),
        target_suit=suit,
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        cost_ceiling=BRIDGE_CEILING,
        portfolio_limit=F4_PER_TARGET,
        skip_preview=True,
        on_progress=obs,
    )
    terminals = []
    for term in list(result.portfolio or [])[:F4_PER_TARGET]:
        actions = as_actions(term.get("actions") or result.path or [])
        if any(is_deal(a) for a in actions):
            continue
        replayed = replay_from_f3(f3["ordered_digest"], int(f3["g"]), actions)
        if not replayed.get("ok") or replayed["g"] != int(term["g"]):
            continue
        st = replayed["state"]
        if not is_target_cashout(st, suit, before):
            continue
        if stock_rows(st) != 0 or len(st.foundations) < 4:
            continue
        s = current_tableau_summary(st)
        h = int(stock_empty_assembly_h(st, replayed["g"]))
        f = int(replayed["g"]) + h
        terminals.append(
            {
                "g": int(replayed["g"]),
                "delta_g": int(replayed["g"]) - int(f3["g"]),
                "foundations": len(st.foundations),
                "foundation_suits": list(s["foundation_suits"]),
                "face_down": face_down_count(st),
                "empty_n": int(s["empty_n"]),
                "legal_tableau": len(tableau_actions(st)),
                "boundaries": int(s.get("visible_runs") or 0),
                "visible_components": int(s.get("visible_runs") or 0),
                "assembly_h": h,
                "assembly_f": f,
                "slack": assembly_slack(BRIDGE_CEILING, f),
                "ordered_digest": replayed["ordered_digest"],
                "whole_game_identity": replayed["whole_game_identity"],
                "ident": replayed["whole_game_identity"],
                "full_actions": dump_actions(actions),
                "n_actions": len(actions),
                "tactical_target": suit,
                "operational_rank": target.get("operational_rank"),
                "stock_rows": 0,
                "lineage": ["v078_f3_g141", f"f3_bridge_{suit}"],
                "portfolio_cat": "f4_tactical_bridge",
            }
        )
    prog = result.progress or {}
    return {
        "suit": suit,
        "stage": stage,
        "operational_rank": target.get("operational_rank"),
        "already_founded": target.get("already_founded"),
        "target_foundations_before": before,
        "found": bool(result.found),
        "cheapest_g": result.cheapest_g,
        "first_g": result.first_g,
        "first_s": result.first_s,
        "delta_g": result.delta_g,
        "n_terminals": len(result.terminals),
        "n_admitted": len(terminals),
        "elapsed_s": time.perf_counter() - t0,
        "unique": result.unique,
        "expanded": result.expanded,
        "generated": result.generated,
        "stop_reason": result.stop_reason,
        "lane_exp": dict(result.lane_exp or {}),
        "min_cover": prog.get("min_cover"),
        "min_blockers": prog.get("min_blockers"),
        "best_k_access": prog.get("best_k_access"),
        "best_a_access": prog.get("best_a_access"),
        "min_h": obs.min_h,
        "min_f": obs.min_f,
        "terminals": terminals,
    }


def _family_key(probe: dict) -> tuple:
    if probe.get("found") and probe.get("cheapest_g") is not None:
        terms = probe.get("terminals") or []
        min_f = min((int(t["assembly_f"]) for t in terms), default=10**9)
        min_h = min((int(t["assembly_h"]) for t in terms), default=10**9)
        return (0, int(probe["cheapest_g"]), min_f, min_h, -int(probe.get("n_terminals") or 0))
    return (
        1,
        int(probe.get("min_cover") if probe.get("min_cover") is not None else 10**9),
        int(probe.get("min_blockers") if probe.get("min_blockers") is not None else 10**9),
        int(probe.get("min_f") if probe.get("min_f") is not None else 10**9),
        -int(probe.get("unique") or 0),
    )


def select_f4_portfolio(terminals: List[dict], *, hard_max: int = F4_PORTFOLIO_MAX) -> List[dict]:
    """Generic diverse F4 set. No fitted scalar. No canonical."""

    dedup = {}
    for rec in terminals:
        ident = rec.get("ident") or rec.get("whole_game_identity")
        if not ident:
            continue
        prev = dedup.get(ident)
        if prev is None or int(rec["g"]) < int(prev["g"]):
            dedup[ident] = rec
    pool = list(dedup.values())
    if not pool:
        return []
    picks = []
    seen = set()

    def take(rec):
        ident = rec.get("ident")
        if ident in seen:
            return
        seen.add(ident)
        picks.append(rec)

    take(min(pool, key=lambda r: (int(r["g"]), r["ordered_digest"])))
    take(min(pool, key=lambda r: (int(r["assembly_f"]), int(r["g"]))))
    take(min(pool, key=lambda r: (int(r["assembly_h"]), int(r["g"]))))
    take(max(pool, key=lambda r: (int(r["legal_tableau"]), -int(r["g"]))))
    take(min(pool, key=lambda r: (int(r.get("boundaries") or 10**9), int(r["g"]))))
    by_suit: Dict[str, list] = {}
    for rec in pool:
        by_suit.setdefault(rec.get("tactical_target") or "?", []).append(rec)
    for suit in sorted(by_suit):
        take(min(by_suit[suit], key=lambda r: (int(r["assembly_f"]), int(r["g"]))))
        if len(picks) >= hard_max:
            break
    rest = sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["g"]), r["ordered_digest"]))
    for rec in rest:
        if len(picks) >= hard_max:
            break
        take(rec)
    return picks[:hard_max]


def run_tactical_bridge(f3: dict) -> dict:
    """Stage A equal probes + Stage B confirmation. Total tactical <= 360 s."""

    inspect = inspect_f3_state(f3["ordered_digest"], g=int(f3["g"]))
    targets = list(inspect["remaining_targets"] or [])
    t0 = time.perf_counter()
    stage_a = []
    for tgt in targets[:4]:
        stage_a.append(
            _probe_one(f3, tgt, time_s=STAGE_A_S, unique=STAGE_A_UNIQUE, stage="A")
        )
    used = time.perf_counter() - t0
    remain_b = max(0.0, TACTICAL_BUDGET_S - used)
    ordered = sorted(stage_a, key=_family_key)
    promote = ordered[:STAGE_B_N]
    tgt_by_suit = {t["suit"]: t for t in targets}
    stage_b = []
    if remain_b >= 1.0 and promote:
        per = min(STAGE_B_S, remain_b / float(len(promote)))
        for pr in promote:
            tgt = tgt_by_suit.get(pr["suit"])
            if tgt is None:
                continue
            stage_b.append(
                _probe_one(f3, tgt, time_s=per, unique=STAGE_B_UNIQUE, stage="B")
            )
    all_terms = []
    for pr in stage_a + stage_b:
        all_terms.extend(pr.get("terminals") or [])
    portfolio = select_f4_portfolio(all_terms, hard_max=F4_PORTFOLIO_MAX)
    elapsed = time.perf_counter() - t0
    cheapest = None if not all_terms else min(all_terms, key=lambda r: (int(r["g"]), int(r["assembly_f"])))
    first = None
    for pr in stage_a + stage_b:
        if pr.get("first_s") is None:
            continue
        if first is None or float(pr["first_s"]) < float(first["first_s"]):
            first = pr
    return {
        "inspect": inspect,
        "stage_a": stage_a,
        "stage_b": stage_b,
        "promoted_suits": [p.get("suit") for p in promote],
        "elapsed_s": elapsed,
        "stage_a_s": sum(float(p.get("elapsed_s") or 0) for p in stage_a),
        "stage_b_s": sum(float(p.get("elapsed_s") or 0) for p in stage_b),
        "budget_s": TACTICAL_BUDGET_S,
        "n_f4": len(portfolio),
        "any_f4": bool(portfolio),
        "f4_roots": portfolio,
        "cheapest_f4_g": None if cheapest is None else int(cheapest["g"]),
        "cheapest_f4_h": None if cheapest is None else cheapest.get("assembly_h"),
        "cheapest_f4_f": None if cheapest is None else cheapest.get("assembly_f"),
        "cheapest_f4_target": None if cheapest is None else cheapest.get("tactical_target"),
        "first_f4_s": None if first is None else first.get("first_s"),
        "first_f4_g": None if first is None else first.get("first_g"),
        "first_f4_target": None if first is None else first.get("suit"),
    }


def search_f4_portfolio(opening, f4_roots: List[dict], *, time_s: float, unique: int):
    """Frozen stock-empty continuation from the F4 tactical portfolio."""

    if not f4_roots or time_s < 1.0:
        return None
    roots = []
    for rec in f4_roots:
        roots.append(
            {
                "g": int(rec["g"]),
                "ordered_digest": rec["ordered_digest"],
                "ident": rec.get("ident") or rec.get("whole_game_identity"),
                "whole_game_identity": rec.get("whole_game_identity") or rec.get("ident"),
                "full_actions": rec.get("full_actions") or [],
                "stock_rows": 0,
                "foundations": rec["foundations"],
                "face_down": rec["face_down"],
                "lineage": list(rec.get("lineage") or []),
                "portfolio_cat": rec.get("portfolio_cat") or "f4_tactical_bridge",
                "assembly_h": rec.get("assembly_h"),
                "assembly_f": rec.get("assembly_f"),
            }
        )
    tracker = FocusedSnapshotTracker(start_F=int(roots[0]["foundations"]), start_g=int(roots[0]["g"]))
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": AUTONOMOUS_INCUMBENT_MW},
        cost_ceiling=BRIDGE_CEILING,
        incumbent_by_rows={},
        initial_roots=roots,
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        harvest_cats=OP_HARVEST_CATS,
        enrich_fn=enrich_assembly,
        lane_names=COMPLETION_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=None,
        continuation_table=None,
        extra_track=tracker.extra_track,
        abort_when=tracker.abort_when,
    )
    tracker.finalize(result)
    result.snapshot_tracker = tracker
    return result


class DigestHunter:
    """Provenance-only: abort when the exact v0.78 g141 digest is generated."""

    def __init__(self, digest: str) -> None:
        self.digest = digest
        self.hit: Optional[dict] = None
        self.n_seen = 0

    def _consider(self, rec: dict) -> None:
        self.n_seen += 1
        if rec.get("ordered_digest") != self.digest or not rec.get("full_actions"):
            return
        if self.hit is None or int(rec["g"]) < int(self.hit["g"]):
            self.hit = {
                "g": int(rec["g"]),
                "ordered_digest": rec["ordered_digest"],
                "full_actions": rec["full_actions"],
                "ident": rec.get("ident") or rec.get("whole_game_identity"),
            }

    def extra_track(self, tops, rec, min_root_g, class_best) -> None:
        self._consider(rec)

    def abort_when(self, out, rec) -> bool:
        self._consider(rec)
        return self.hit is not None and int(self.hit["g"]) <= 141


def recover_g141(opening, post: dict, *, time_s: float = RECOVER_S, unique: int = RECOVER_UNIQUE) -> dict:
    """Opening provenance for a complete candidate. Not used to guide search."""

    digest = expected_g141_digest()
    hunter = DigestHunter(digest)
    root = {
        "g": int(post["g"]),
        "ordered_digest": post["ordered_digest"],
        "ident": post["whole_game_identity"],
        "whole_game_identity": post["whole_game_identity"],
        "full_actions": post["full_actions"],
        "stock_rows": 0,
        "foundations": post["foundations"],
        "face_down": post["face_down"],
        "lineage": ["g128_tactical_v071"],
        "portfolio_cat": "g129_recover_root",
    }
    t0 = time.perf_counter()
    res = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": AUTONOMOUS_INCUMBENT_MW},
        cost_ceiling=BRIDGE_CEILING,
        incumbent_by_rows={},
        initial_roots=[root],
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        harvest_cats=OP_HARVEST_CATS,
        enrich_fn=enrich_assembly,
        lane_names=COMPLETION_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=None,
        continuation_table=None,
        extra_track=hunter.extra_track,
        abort_when=hunter.abort_when,
    )
    hit = hunter.hit
    ok = False
    replay_g = None
    if hit is not None:
        end = opening.clone()
        try:
            replay_g = replay_actions(end, as_actions(hit["full_actions"]))
        except Exception:
            replay_g = None
        ok = replay_g == int(hit["g"]) and pack_state(end).hex() == digest and int(hit["g"]) == 141
    return {
        "ok": ok,
        "reason": None if ok else ("digest_not_recovered" if hit is None else "g141_replay_mismatch"),
        "elapsed_s": time.perf_counter() - t0,
        "unique": res.unique,
        "expanded": res.expanded,
        "stop_reason": res.stop_reason,
        "hit": hit,
        "replay_g": replay_g,
        "expected_digest": digest,
    }


def evaluate_187_f3_f4(opening) -> dict:
    """Post-freeze evaluation only. Does not affect search policy."""

    from spider.metrics import parse_moves_file
    from spider.state_convergence import V074_MOVES, foundation_progression

    actions = parse_moves_file(V074_MOVES)
    prog = foundation_progression(opening, list(actions))
    f3 = next((p for p in prog if int(p.get("F") or 0) == 3), None)
    f4 = next((p for p in prog if int(p.get("F") or 0) == 4), None)
    if f3 is None or f4 is None:
        return {"ok": False, "reason": "missing_f3_or_f4"}
    state = unpack_state(bytes.fromhex(f3["ordered_digest"]))
    ranked = rank_ready_suits(state, g=int(f3["g"]))
    before = list(current_tableau_summary(state)["foundation_suits"])
    after_state = unpack_state(bytes.fromhex(f4["ordered_digest"]))
    after = list(current_tableau_summary(after_state)["foundation_suits"])
    added = None
    before_c = {}
    for s in before:
        before_c[s] = before_c.get(s, 0) + 1
    after_c = {}
    for s in after:
        after_c[s] = after_c.get(s, 0) + 1
    for s, n in after_c.items():
        if n > before_c.get(s, 0):
            added = s
            break
    rank = None
    for i, rec in enumerate(ranked.get("ranked") or []):
        if rec.get("suit") == added:
            rank = i + 1
            break
    return {
        "ok": True,
        "f3_g": f3.get("g"),
        "f3_h": f3.get("assembly_h"),
        "f3_f": f3.get("assembly_f"),
        "f3_fd": f3.get("face_down"),
        "f3_suits": before,
        "f4_g": f4.get("g"),
        "f4_h": f4.get("assembly_h"),
        "f4_f": f4.get("assembly_f"),
        "delta_g": int(f4["g"]) - int(f3["g"]),
        "next_suit": added,
        "next_suit_rank_at_f3": rank,
        "n_ready_at_f3": ranked.get("n_ready"),
        "ready_suits_at_f3": ranked.get("ready_suits"),
    }


def choose_bridge_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F3_TACTICAL_BRIDGE_CONTRACT_FAILURE", p.get("contract_reason") or "root/accounting/identity/provenance/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    max_f = int(p.get("max_foundations") or 0)
    n_f4 = int((p.get("bridge") or {}).get("n_f4") or 0)
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "F3_TACTICAL_BRIDGE_COST_IMPROVED", f"solved at g={best}"
    if n_f4 > 0 and max_f >= 5:
        return "F3_TACTICAL_BRIDGE_DEEP_ENDGAME", f"F4 portfolio n={n_f4} maxF={max_f}"
    if n_f4 > 0 or max_f >= 4:
        return "F3_TACTICAL_BRIDGE_REACHES_F4", f"F4 portfolio n={n_f4} maxF={max_f}"
    probes = ((p.get("bridge") or {}).get("stage_a") or []) + ((p.get("bridge") or {}).get("stage_b") or [])
    strong = any(int(pr.get("unique") or 0) >= 10_000 for pr in probes)
    if strong:
        return "F3_TACTICAL_BRIDGE_SEARCH_LIMITED", "strong target progress but no F4"
    return "F3_TACTICAL_BRIDGE_NO_F4", "no target produced F4 within the bounded tactical experiment"
