"""v0.79 bounded F3→F4 tactical bridge from the v0.78 g141 state.

Does not change whole-game scheduling, rollout integration, or rows=1
tactical selection. Canonical 172 is not read. Continuation-table suffixes
are not used during search.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.foundation_cashout import search_foundation_cashout
from spider.g128_focused_endgame import (
    FOCUSED_CEILING,
    reconstruct_g128_root,
    search_g128_focused,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW
from spider.metrics import replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, dump_actions, face_down_count, is_deal, stock_rows, tableau_actions
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V078_JSON = ROOT / "docs" / "research" / "g128_focused_endgame_v0_78.json"

BRIDGE_CEILING = 186
RECOVER_S = 180.0
RECOVER_UNIQUE = 200_000
TACTICAL_PER_S = 75.0
TACTICAL_PER_UNIQUE = 80_000
F4_PORTFOLIO_MAX = 16
TOTAL_S = SEARCH_TIME_S


def expected_g141_digest() -> str:
    data = json.loads(V078_JSON.read_text(encoding="utf-8"))
    for rec in data.get("frontier_list") or []:
        if int(rec.get("F") or 0) == 3 and int(rec.get("g") or 0) == 141:
            return rec["ordered_digest"]
    raise KeyError("v0.78 g141 F3 digest missing")


def inspect_f3_state(digest: Optional[str] = None, g: int = 141) -> dict:
    digest = digest or expected_g141_digest()
    state = unpack_state(bytes.fromhex(digest))
    s = current_tableau_summary(state)
    ranked = rank_ready_suits(state, g=g)
    h = int(stock_empty_assembly_h(state, g))
    remaining = []
    founded = list(s["foundation_suits"])
    counts: Dict[str, int] = {}
    for suit in founded:
        counts[suit] = counts.get(suit, 0) + 1
    for rec in ranked.get("ranked") or []:
        suit = rec["suit"]
        remaining.append(
            {
                "suit": suit,
                "already_founded": int(counts.get(suit) or 0),
                "cover": rec.get("cover"),
                "blockers": rec.get("relevant_blockers"),
                "k_access": rec.get("k_min_blockers"),
                "a_access": rec.get("a_min_blockers"),
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
        "foundation_suits": founded,
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(state)),
        "assembly_h": h,
        "assembly_f": int(g) + h,
        "n_ready": int(ranked.get("n_ready") or 0),
        "ready_suits": list(ranked.get("ready_suits") or []),
        "best_suit": ranked.get("best_suit"),
        "second_suit": ranked.get("second_suit"),
        "remaining_targets": remaining,
        "ordered_digest": digest,
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "can_deal": bool(state.can_deal()),
    }


class DigestHunter:
    """Abort when the exact v0.78 g141 digest is generated. Does not seed search."""

    def __init__(self, digest: str) -> None:
        self.digest = digest
        self.hit: Optional[dict] = None
        self.n_seen = 0

    def _consider(self, rec: dict) -> None:
        self.n_seen += 1
        if rec.get("ordered_digest") != self.digest:
            return
        if not rec.get("full_actions"):
            return
        if self.hit is None or int(rec["g"]) < int(self.hit["g"]):
            self.hit = {
                "g": int(rec["g"]),
                "ordered_digest": rec["ordered_digest"],
                "ident": rec.get("ident") or rec.get("whole_game_identity"),
                "whole_game_identity": rec.get("whole_game_identity") or rec.get("ident"),
                "full_actions": rec["full_actions"],
                "foundations": rec.get("foundations"),
                "face_down": rec.get("face_down"),
                "empty_n": rec.get("empty_n"),
                "legal_tableau": rec.get("legal_tableau"),
                "boundaries_total": rec.get("boundaries_total"),
                "assembly_h": rec.get("assembly_h"),
                "assembly_f": rec.get("assembly_f"),
            }

    def extra_track(self, tops, rec, min_root_g, class_best) -> None:
        self._consider(rec)

    def abort_when(self, out, rec) -> bool:
        self._consider(rec)
        return self.hit is not None and int(self.hit["g"]) <= 141


def recover_g141(opening, post: dict, *, time_s: float = RECOVER_S, unique: int = RECOVER_UNIQUE) -> dict:
    """Replay-valid path from the g129 root to the exact v0.78 g141 digest."""

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
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
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
        ok = (
            replay_g == int(hit["g"])
            and pack_state(end).hex() == digest
            and len(end.foundations) == 3
            and stock_rows(end) == 0
            and int(hit["g"]) == 141
        )
    return {
        "ok": ok,
        "reason": None if ok else ("digest_not_recovered" if hit is None else "g141_replay_mismatch"),
        "elapsed_s": time.perf_counter() - t0,
        "search_elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "expanded": res.expanded,
        "stop_reason": res.stop_reason,
        "n_seen": hunter.n_seen,
        "hit": hit,
        "replay_g": replay_g,
        "expected_digest": digest,
    }


def probe_ready_suits(opening, f3: dict, *, time_s: float = TACTICAL_PER_S, unique: int = TACTICAL_PER_UNIQUE) -> dict:
    """One frozen tactical cash-out per materially-ready remaining suit."""

    inspect = inspect_f3_state(f3["ordered_digest"], g=int(f3["g"]))
    probes = []
    f4_roots = []
    t0 = time.perf_counter()
    seen = set()
    for rec in inspect["remaining_targets"]:
        suit = rec["suit"]
        if suit in seen:
            continue
        seen.add(suit)
        t_probe = time.perf_counter()
        result = search_foundation_cashout(
            ordered_digest=f3["ordered_digest"],
            root_g=int(f3["g"]),
            target_suit=suit,
            max_unique=int(unique),
            time_limit_s=float(time_s),
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=BRIDGE_CEILING,
            portfolio_limit=8,
            skip_preview=True,
        )
        slim_terms = []
        for term in (result.portfolio or [])[:8]:
            prefix = as_actions(f3["full_actions"]) + as_actions(term.get("actions") or result.path or [])
            end = opening.clone()
            try:
                g = replay_actions(end, list(prefix))
            except Exception:
                continue
            if g != int(term["g"]) or len(end.foundations) < 4 or stock_rows(end) != 0:
                continue
            if any(is_deal(a) for a in as_actions(term.get("actions") or [])):
                continue
            h = int(stock_empty_assembly_h(end, g))
            s = current_tableau_summary(end)
            root = {
                "g": int(g),
                "ordered_digest": pack_state(end).hex(),
                "ident": pack_whole_game_identity(end).hex(),
                "whole_game_identity": pack_whole_game_identity(end).hex(),
                "full_actions": dump_actions(prefix),
                "stock_rows": 0,
                "foundations": len(end.foundations),
                "face_down": face_down_count(end),
                "empty_n": int(s["empty_n"]),
                "legal_tableau": len(tableau_actions(end)),
                "assembly_h": h,
                "assembly_f": int(g) + h,
                "lineage": ["g128_tactical_v071", "v078_f3_g141", f"f3_bridge_{suit}"],
                "portfolio_cat": "f4_tactical_bridge",
                "tactical_target": suit,
            }
            slim_terms.append(
                {
                    "g": root["g"],
                    "delta_g": int(g) - int(f3["g"]),
                    "h": h,
                    "f": int(g) + h,
                    "foundations": root["foundations"],
                    "face_down": root["face_down"],
                    "legal": root["legal_tableau"],
                    "ordered_digest": root["ordered_digest"],
                    "n_actions": len(as_actions(term.get("actions") or [])),
                }
            )
            f4_roots.append(root)
        probes.append(
            {
                "suit": suit,
                "already_founded": rec["already_founded"],
                "found": bool(result.found),
                "cheapest_g": result.cheapest_g,
                "first_g": result.first_g,
                "first_s": result.first_s,
                "delta_g": result.delta_g,
                "n_terminals": len(result.terminals),
                "n_admitted": len(slim_terms),
                "elapsed_s": time.perf_counter() - t_probe,
                "unique": result.unique,
                "expanded": result.expanded,
                "stop_reason": result.stop_reason,
                "lane_exp": dict(result.lane_exp or {}),
                "terminals": slim_terms,
            }
        )
    # cheapest unique F4 identities
    dedup = {}
    for root in f4_roots:
        ident = root["ident"]
        prev = dedup.get(ident)
        if prev is None or int(root["g"]) < int(prev["g"]):
            dedup[ident] = root
    ranked = sorted(dedup.values(), key=lambda r: (int(r["g"]), r["ordered_digest"]))
    return {
        "inspect": inspect,
        "probes": probes,
        "n_f4": len(ranked),
        "f4_roots": ranked[:F4_PORTFOLIO_MAX],
        "elapsed_s": time.perf_counter() - t0,
        "any_f4": bool(ranked),
        "cheapest_f4_g": None if not ranked else int(ranked[0]["g"]),
        "cheapest_f4_h": None if not ranked else ranked[0].get("assembly_h"),
        "cheapest_f4_target": None if not ranked else ranked[0].get("tactical_target"),
    }


def continue_from_f4(opening, f4_roots: List[dict], *, time_s: float, unique: int):
    """Frozen stock-empty endgame from the F4 tactical portfolio."""

    if not f4_roots or time_s < 1.0:
        return None
    return search_g128_focused(
        opening=opening,
        post=f4_roots[0] | {
            "g": f4_roots[0]["g"],
            "ordered_digest": f4_roots[0]["ordered_digest"],
            "whole_game_identity": f4_roots[0]["whole_game_identity"],
            "full_actions": f4_roots[0]["full_actions"],
            "foundations": f4_roots[0]["foundations"],
            "face_down": f4_roots[0]["face_down"],
            "assembly_h": f4_roots[0].get("assembly_h"),
            "assembly_f": f4_roots[0].get("assembly_f"),
            "legal_tableau": f4_roots[0].get("legal_tableau"),
            "boundaries_total": f4_roots[0].get("boundaries_total"),
            "empty_n": f4_roots[0].get("empty_n"),
        },
        max_unique=unique,
        time_limit_s=time_s,
        rss_abort_mb=SEARCH_RSS_MB,
    )


def search_f4_portfolio(opening, f4_roots: List[dict], *, time_s: float, unique: int):
    """Multi-root frozen continuation when several F4s exist."""

    if not f4_roots or time_s < 1.0:
        return None
    roots = []
    for rec in f4_roots:
        roots.append(
            {
                "g": int(rec["g"]),
                "ordered_digest": rec["ordered_digest"],
                "ident": rec["ident"],
                "whole_game_identity": rec["whole_game_identity"],
                "full_actions": rec["full_actions"],
                "stock_rows": 0,
                "foundations": rec["foundations"],
                "face_down": rec["face_down"],
                "lineage": list(rec.get("lineage") or []),
                "portfolio_cat": rec.get("portfolio_cat") or "f4_tactical_bridge",
                "assembly_h": rec.get("assembly_h"),
                "assembly_f": rec.get("assembly_f"),
            }
        )
    from spider.g128_focused_endgame import FocusedSnapshotTracker

    tracker = FocusedSnapshotTracker(start_F=4, start_g=int(roots[0]["g"]))
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


def choose_bridge_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F3_BRIDGE_CONTRACT_FAILURE", p.get("contract_reason") or "prefix/root/replay/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    max_f = int(p.get("max_foundations") or 0)
    n_f4 = int((p.get("bridge") or {}).get("n_f4") or 0)
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "F3_BRIDGE_COST_IMPROVED", f"solved at g={best}"
    if p.get("solved") and p.get("replay_ok") and best is not None:
        return "F3_BRIDGE_SOLVES_NO_GAIN", f"solved at g={best} not below {inc}"
    if n_f4 > 0 or max_f >= 4:
        return "F3_BRIDGE_REACHES_F4", f"F4 portfolio n={n_f4} maxF={max_f}"
    return "F3_BRIDGE_NO_F4", "no F4 from per-suit tactical probes"
