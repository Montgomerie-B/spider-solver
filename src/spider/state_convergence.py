"""v0.74 exact autonomous state-convergence splice.

The v0.73 pre-SD5 F2 digest equals the v0.67 F2 digest. A cheaper prefix
to that node plus the old autonomous suffix is ordinary transposition,
not canonical imitation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Tuple

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.foundation_cashout import (
    replay_to_stock_rows,
    search_foundation_cashout,
    select_tactical_target,
)
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
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
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
)

ROOT = Path(__file__).resolve().parents[2]
V067_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V074_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
V074_SPLICE_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_74_splice191.moves"
V074_BEST_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_74_best.moves"
V073_JSON = ROOT / "docs" / "research" / "maturity_aware_tactical_roots_v0_73.json"
V073_F2_DIGEST = (
    "53504b310102000a00020d29000132000c0a1918171615140302111c1b020e31122d0c3b1a1d1c2b2a1d"
    "2c1b3a391800022634000436350421000d3d3c3b3a3938373635343d3c0b0009282706052423323138"
    "00000009080716151413121109131a22331937170133250d2d2c2b2a2928272625242322210d0d0c0b"
    "0a090807060504030201"
)
OLD_F2_G = 130
NEW_F2_G = 129
SUFFIX_COST = 62
SPLICED_G = 191
FOCUSED_ROOT_G = 130
PARENT_INCUMBENT_G = 192


def v073_f2_digest() -> str:
    if V073_JSON.exists():
        import json

        data = json.loads(V073_JSON.read_text(encoding="utf-8"))
        digest = ((data.get("best_presd5_f2") or {}).get("digest")) or (
            ((data.get("foundations") or {}).get("cheap") or {}).get("2") or {}
        ).get("ordered_digest")
        if digest:
            return str(digest)
    return V073_F2_DIGEST


def verify_old_192(opening=None) -> dict:
    opening = opening or opening_state()
    actions = parse_moves_file(V067_MOVES)
    end = opening.clone()
    g = replay_actions(end, list(actions))
    deals = sum(1 for a in actions if is_deal(a))
    ok = (
        g == PARENT_INCUMBENT_G
        and deals == 5
        and end.is_solved()
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
    )
    return {
        "ok": ok,
        "g": g,
        "deals": deals,
        "n_actions": len(actions),
        "solved": end.is_solved(),
        "actions": actions,
    }


def locate_old_f2(opening=None, *, digest: Optional[str] = None) -> dict:
    opening = opening or opening_state()
    digest = digest or v073_f2_digest()
    actions = parse_moves_file(V067_MOVES)
    state = opening.clone()
    g = 0
    deals = 0
    hits = []
    for i, action in enumerate(actions):
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        if is_deal(action):
            deals += 1
        if pack_state(state).hex() == digest:
            hits.append(
                {
                    "action_index": i,
                    "n_prefix": i + 1,
                    "g": g,
                    "deals": deals,
                    "stock_rows": stock_rows(state),
                    "face_down": face_down_count(state),
                    "foundations": len(state.foundations),
                    "foundation_suits": [run[0].suit for run in state.foundations if run],
                    "digest": digest,
                    "suffix": dump_actions(actions[i + 1 :]),
                    "n_suffix": len(actions) - (i + 1),
                }
            )
    if len(hits) != 1:
        return {"ok": False, "n_hits": len(hits), "hits": hits, "digest": digest}
    hit = hits[0]
    ok = (
        int(hit["g"]) == OLD_F2_G
        and int(hit["stock_rows"]) == 1
        and int(hit["face_down"]) == 2
        and int(hit["foundations"]) == 2
        and set(hit["foundation_suits"]) == {"s", "d"}
    )
    hit["ok"] = ok
    hit["n_hits"] = 1
    return hit


def reconstruct_v073_prefix(
    opening=None,
    *,
    digest: Optional[str] = None,
    time_limit_s: float = 15.0,
    max_unique: int = 20_000,
) -> dict:
    """Rebuild opening → rows=1 checkpoint → tactical cash-out to the F2 digest.

    The v0.73 report slimmed action lists. The planner is deterministic, so
    replaying the stored checkpoint then searching to the recorded digest
    reconstructs the prefix without hand-edited moves.
    """

    opening = opening or opening_state()
    digest = digest or v073_f2_digest()
    old = verify_old_192(opening)
    if not old["ok"]:
        return {"ok": False, "reason": "old_192_invalid"}
    ck = replay_to_stock_rows(opening, old["actions"], target_rows=1)
    if int(ck["g"]) != 123 or int(ck["stock_rows"]) != 1:
        return {"ok": False, "reason": "checkpoint_mismatch", "checkpoint": ck}
    state = unpack_state(bytes.fromhex(ck["ordered_digest"]))
    target = select_tactical_target(state, int(ck["g"]))
    result = search_foundation_cashout(
        ordered_digest=ck["ordered_digest"],
        root_g=int(ck["g"]),
        target_suit=target["suit"],
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=2.5 * 1024,
        cost_ceiling=191,
        portfolio_limit=16,
        skip_preview=True,
    )
    match = None
    for term in result.portfolio or result.terminals or []:
        if term.get("ordered_digest") == digest and int(term.get("g") or 0) == NEW_F2_G:
            match = term
            break
    if match is None:
        for term in result.terminals or []:
            if term.get("ordered_digest") == digest:
                match = term
                break
    if match is None or not match.get("actions"):
        return {
            "ok": False,
            "reason": "prefix_not_found",
            "cheapest_g": result.cheapest_g,
            "cheapest_digest": result.cheapest_digest,
            "n_terminals": len(result.terminals or []),
            "target": target["suit"],
        }
    prefix = as_actions(ck["prefix_actions"]) + as_actions(match["actions"])
    end = opening.clone()
    g = replay_actions(end, list(prefix))
    ok = (
        g == NEW_F2_G
        and pack_state(end).hex() == digest
        and stock_rows(end) == 1
        and face_down_count(end) == 2
        and len(end.foundations) == 2
        and set(run[0].suit for run in end.foundations if run) == {"s", "d"}
        and not any(is_deal(a) for a in as_actions(match["actions"]))
    )
    return {
        "ok": ok,
        "g": g,
        "digest": pack_state(end).hex(),
        "stock_rows": stock_rows(end),
        "face_down": face_down_count(end),
        "foundations": len(end.foundations),
        "foundation_suits": [run[0].suit for run in end.foundations if run],
        "n_checkpoint": int(ck["n_prefix"]),
        "checkpoint_g": int(ck["g"]),
        "tactical_actions": dump_actions(as_actions(match["actions"])),
        "n_tactical": len(as_actions(match["actions"])),
        "full_actions": dump_actions(prefix),
        "target_suit": target["suit"],
        "reason": None if ok else "replay_mismatch",
    }


def splice_candidate(prefix_actions: List[Action], suffix_actions: List[Action]) -> List[Action]:
    return list(prefix_actions) + list(suffix_actions)


def replay_spliced(opening, actions: List[Action], *, splice_digest: str, prefix_n: int) -> dict:
    state = opening.clone()
    g = 0
    deals = 0
    splice_g = None
    splice_ok = False
    for i, action in enumerate(actions):
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        if is_deal(action):
            deals += 1
        if i + 1 == int(prefix_n):
            splice_g = g
            splice_ok = pack_state(state).hex() == splice_digest
    ok = (
        g == SPLICED_G
        and deals == 5
        and state.is_solved()
        and len(state.foundations) == 8
        and not state.stock
        and all(c.is_empty() for c in state.columns)
        and splice_ok
        and splice_g == NEW_F2_G
    )
    return {
        "ok": ok,
        "g": g,
        "deals": deals,
        "solved": state.is_solved(),
        "splice_ok": splice_ok,
        "splice_g": splice_g,
        "n_actions": len(actions),
    }


def apply_final_deal(opening, prefix_actions: List[Action]) -> dict:
    state = opening.clone()
    g = replay_actions(state, list(prefix_actions))
    pre_digest = pack_state(state).hex()
    if stock_rows(state) != 1:
        return {"ok": False, "reason": "not_rows1", "g": g}
    from spider.research_actions import apply_action as _apply

    deal_c = _apply(state, ("deal",))
    g += int(deal_c)
    s = current_tableau_summary(state)
    from spider.assembly_lower_bound import stock_empty_assembly_h

    h = int(stock_empty_assembly_h(state, g))
    return {
        "ok": g == FOCUSED_ROOT_G and stock_rows(state) == 0,
        "g": g,
        "deal_cost": deal_c,
        "pre_digest": pre_digest,
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "stock_rows": stock_rows(state),
        "foundations": int(s["foundations"]),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(state)),
        "legal_mobility": len(tableau_actions(state)),
        "boundaries_total": int(s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": g + h,
        "full_actions": dump_actions(list(prefix_actions) + [("deal",)]),
    }


def old_post_sd5(opening, old_f2: dict) -> dict:
    """Immediate Deal from the identical F2. Old absolute g is 131."""

    actions = parse_moves_file(V067_MOVES)
    n = int(old_f2["n_prefix"])
    state = opening.clone()
    g = replay_actions(state, actions[:n])
    if stock_rows(state) != 1:
        return {"ok": False, "reason": "not_rows1", "g": g}
    apply_action(state, ("deal",))
    g += 1
    return {
        "ok": True,
        "g": g,
        "kind": "immediate_deal_from_f2",
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "face_down": face_down_count(state),
    }


def old_actual_post_sd5(opening, old_f2: dict) -> dict:
    """Where the 192 route actually deals after F2 (not necessarily immediately)."""

    suffix = as_actions(old_f2["suffix"])
    deal_i = next((i for i, action in enumerate(suffix) if is_deal(action)), None)
    if deal_i is None:
        return {"ok": False, "reason": "no_deal_in_suffix"}
    actions = parse_moves_file(V067_MOVES)
    n = int(old_f2["n_prefix"])
    state = opening.clone()
    g = replay_actions(state, actions[:n] + suffix[: deal_i + 1])
    return {
        "ok": True,
        "g": g,
        "kind": "actual_192_deal",
        "deal_suffix_index": deal_i,
        "tableau_before_deal": deal_i,
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "face_down": face_down_count(state),
    }


def verify_suffix_sequence(opening, prefix: List[Action], suffix: List[Action]) -> dict:
    """Same suffix actions from the identical F2; new g is exactly one lower."""

    old_actions = parse_moves_file(V067_MOVES)
    loc = locate_old_f2(opening)
    if not loc.get("ok"):
        return {"ok": False, "reason": "locate_failed"}
    old_state = opening.clone()
    old_g = replay_actions(old_state, old_actions[: int(loc["n_prefix"])])
    new_state = opening.clone()
    new_g = replay_actions(new_state, list(prefix))
    if pack_state(old_state).hex() != pack_state(new_state).hex():
        return {"ok": False, "reason": "f2_digest_mismatch"}
    if old_g != OLD_F2_G or new_g != NEW_F2_G:
        return {"ok": False, "reason": "f2_g_mismatch", "old_g": old_g, "new_g": new_g}
    for i, action in enumerate(suffix):
        oc = 1 if is_deal(action) else step_cost(old_state, action)
        nc = 1 if is_deal(action) else step_cost(new_state, action)
        apply_action(old_state, action)
        apply_action(new_state, action)
        old_g += int(oc)
        new_g += int(nc)
        if pack_state(old_state).hex() != pack_state(new_state).hex() or new_g != old_g - 1 or oc != nc:
            return {
                "ok": False,
                "reason": "step_mismatch",
                "i": i,
                "old_g": old_g,
                "new_g": new_g,
                "cost_old": oc,
                "cost_new": nc,
            }
    return {
        "ok": True,
        "n": len(suffix),
        "terminal_old_g": old_g,
        "terminal_new_g": new_g,
        "solved": new_state.is_solved() and old_state.is_solved(),
    }


def foundation_progression(opening, actions: List[Action]) -> list:
    state = opening.clone()
    g = 0
    seen = {}
    order = []
    for action in actions:
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        n = len(state.foundations)
        if n not in seen:
            seen[n] = True
            s = current_tableau_summary(state)
            h = int(stock_empty_assembly_h(state, g)) if stock_rows(state) == 0 else 0
            order.append(
                {
                    "F": n,
                    "g": g,
                    "stock_rows": stock_rows(state),
                    "face_down": face_down_count(state),
                    "empty_n": int(s["empty_n"]),
                    "legal_tableau": len(tableau_actions(state)),
                    "assembly_h": h,
                    "assembly_f": g + h,
                    "slack_190": 190 - (g + h),
                    "ordered_digest": pack_state(state).hex(),
                }
            )
    return order


def _viability_snap(rec: dict) -> dict:
    g = rec.get("g")
    h = rec.get("assembly_h")
    f = rec.get("assembly_f")
    if f is None and g is not None and h is not None:
        f = int(g) + int(h)
    return {
        "g": g,
        "foundations": rec.get("foundations"),
        "face_down": rec.get("face_down"),
        "empty_n": rec.get("empty_n"),
        "legal_tableau": rec.get("legal_tableau"),
        "boundaries_total": rec.get("boundaries_total"),
        "cover": rec.get("cover"),
        "op_blockers": rec.get("op_blockers"),
        "assembly_h": h,
        "assembly_f": f,
        "slack_190": None if f is None else 190 - int(f),
        "ordered_digest": rec.get("ordered_digest"),
    }


class FocusedViabilityTracker:
    """Evaluation-only. Does not seed search or copy the old suffix."""

    def __init__(self, progress_path: Optional[Path] = None) -> None:
        self.started = time.perf_counter()
        self.n_seen = 0
        self.best_f = None
        self.best_h = None
        self.best_mobility = None
        self.best_boundaries = None
        self.best_operational = None
        self.progress_path = progress_path
        self._last_write = 0.0

    def summary(self) -> dict:
        return {
            "n_seen": self.n_seen,
            "best_f": self.best_f,
            "best_h": self.best_h,
            "best_mobility": self.best_mobility,
            "best_boundaries": self.best_boundaries,
            "best_operational": self.best_operational,
        }

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        self.n_seen += 1
        snap = _viability_snap(rec)
        f = snap.get("assembly_f")
        h = snap.get("assembly_h")
        if f is not None and (self.best_f is None or int(f) < int(self.best_f["assembly_f"])):
            self.best_f = snap
        if h is not None and (
            self.best_h is None
            or int(h) < int(self.best_h["assembly_h"])
            or (int(h) == int(self.best_h["assembly_h"]) and int(snap["g"]) < int(self.best_h["g"]))
        ):
            self.best_h = snap
        mob = snap.get("legal_tableau")
        if mob is not None and (
            self.best_mobility is None or int(mob) > int(self.best_mobility["legal_tableau"])
        ):
            self.best_mobility = snap
        b = snap.get("boundaries_total")
        if b is not None and (
            self.best_boundaries is None or int(b) < int(self.best_boundaries["boundaries_total"])
        ):
            self.best_boundaries = snap
        if rec.get("op_key") is not None and (
            self.best_operational is None
            or tuple(rec["op_key"]) < tuple(self.best_operational.get("op_key") or ())
        ):
            self.best_operational = snap | {"op_key": list(rec["op_key"])}
        now = time.perf_counter()
        if self.progress_path is not None and now - self._last_write >= 30.0:
            self._last_write = now
            try:
                import json

                payload = {
                    "phase": "focused_search",
                    "elapsed_s": now - self.started,
                    "n_seen": self.n_seen,
                    "best_f": self.best_f,
                    "max_foundations": rec.get("foundations"),
                }
                temp = self.progress_path.with_suffix(self.progress_path.suffix + ".tmp")
                temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                temp.replace(self.progress_path)
            except OSError:
                pass


def build_verified_191(opening=None, *, reconstruct_s: float = 15.0) -> dict:
    opening = opening or opening_state()
    old = verify_old_192(opening)
    if not old["ok"]:
        return {"ok": False, "verdict": "STATE_CONVERGENCE_CONTRACT_FAILURE", "old": old}
    digest = v073_f2_digest()
    loc = locate_old_f2(opening, digest=digest)
    if not loc.get("ok"):
        return {
            "ok": False,
            "verdict": "STATE_CONVERGENCE_DIGEST_MISMATCH",
            "old": old,
            "locate": loc,
        }
    pre = reconstruct_v073_prefix(opening, digest=digest, time_limit_s=reconstruct_s)
    if not pre.get("ok"):
        return {
            "ok": False,
            "verdict": "STATE_CONVERGENCE_PREFIX_PROVENANCE_FAILURE",
            "old": old,
            "locate": loc,
            "prefix": pre,
        }
    prefix = as_actions(pre["full_actions"])
    suffix = as_actions(loc["suffix"])
    spliced = splice_candidate(prefix, suffix)
    replay = replay_spliced(
        opening, spliced, splice_digest=digest, prefix_n=len(prefix)
    )
    if not replay.get("ok"):
        return {
            "ok": False,
            "verdict": "STATE_CONVERGENCE_CONTRACT_FAILURE",
            "old": old,
            "locate": loc,
            "prefix": pre,
            "replay": replay,
        }
    seq = verify_suffix_sequence(opening, prefix, suffix)
    if not seq.get("ok"):
        return {
            "ok": False,
            "verdict": "STATE_CONVERGENCE_CONTRACT_FAILURE",
            "old": old,
            "locate": loc,
            "prefix": pre,
            "replay": replay,
            "suffix_sequence": seq,
        }
    focused = apply_final_deal(opening, prefix)
    old_post = old_post_sd5(opening, loc)
    actual_post = old_actual_post_sd5(opening, loc)
    post_match = focused.get("ordered_digest") == old_post.get("ordered_digest")
    return {
        "ok": True,
        "verdict": "STATE_CONVERGENCE_191_VERIFIED",
        "old": {k: old[k] for k in old if k != "actions"},
        "locate": {k: loc[k] for k in loc if k != "suffix"} | {"n_suffix": loc["n_suffix"]},
        "prefix": {k: pre[k] for k in pre if k != "full_actions"},
        "replay": replay,
        "suffix_sequence": seq,
        "digest": digest,
        "suffix": loc["suffix"],
        "prefix_actions": pre["full_actions"],
        "spliced_actions": dump_actions(spliced),
        "suffix_cost": PARENT_INCUMBENT_G - OLD_F2_G,
        "expected_g": NEW_F2_G + (PARENT_INCUMBENT_G - OLD_F2_G),
        "focused": focused,
        "old_post_sd5": old_post,
        "old_actual_post_sd5": actual_post,
        "post_sd5_match": post_match,
        "actual_post_sd5_same": focused.get("ordered_digest") == actual_post.get("ordered_digest"),
        "n_prefix": len(prefix),
        "n_suffix": len(suffix),
        "n_spliced": len(spliced),
        "split_ok": len(prefix) + len(suffix) == len(spliced),
    }


def search_focused_endgame(
    *,
    opening=None,
    focused: dict,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
    progress_path: Optional[Path] = None,
):
    """Stock-empty search from the spliced post-SD5 state. No suffix actions."""

    opening = opening or opening_state()
    root = {
        "g": int(focused["g"]),
        "ordered_digest": focused["ordered_digest"],
        "ident": focused["whole_game_identity"],
        "whole_game_identity": focused["whole_game_identity"],
        "full_actions": focused["full_actions"],
        "stock_rows": 0,
        "foundations": focused["foundations"],
        "face_down": focused["face_down"],
        "lineage": ["state_convergence_v074"],
        "portfolio_cat": "focused_root",
    }
    viability = FocusedViabilityTracker(progress_path=progress_path)
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": SPLICED_G},
        cost_ceiling=SPLICED_G - 1,
        incumbent_by_rows={},
        initial_roots=[root],
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
        harvest_cats=OP_HARVEST_CATS,
        enrich_fn=enrich_assembly,
        lane_names=COMPLETION_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=None,
        extra_track=viability,
    )
    result.viability = viability
    return result


def choose_convergence_verdict(p: dict) -> Tuple[str, str]:
    if p.get("verdict_pre"):
        return p["verdict_pre"], p.get("verdict_reason") or p["verdict_pre"]
    if p.get("accounting_fail") or (p.get("spliced_ok") is False):
        return "STATE_CONVERGENCE_CONTRACT_FAILURE", "replay or accounting failed"
    if not p.get("spliced_ok"):
        return "STATE_CONVERGENCE_CONTRACT_FAILURE", "191 splice not verified"
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) <= 190:
        return "STATE_CONVERGENCE_ENDGAME_COST_IMPROVED", f"solved at g={best}"
    min_f = p.get("min_f")
    max_f = int(p.get("max_foundations") or 0)
    if max_f >= 6 and min_f is not None and int(min_f) <= 190:
        return (
            "STATE_CONVERGENCE_191_VERIFIED_SEARCH_LIMITED",
            "191 verified; focused search reached a viable late frontier without a <=190 terminal",
        )
    return "STATE_CONVERGENCE_PROMOTES_191", "exact autonomous splice replays at 191; focused search did not beat it"
