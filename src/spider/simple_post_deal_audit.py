"""Post-Deal continuation diagnostics for the simple progressive solver.

Telemetry only.  Does not order moves, prune, promote Deal, widen passes,
or insert counterfactual actions into search.  Census uses the engine
legal-action API and existing ``classify_tier``; it never feeds a list
back into the child iterator.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state
from spider.rules import MW_RULES, MobilityWareRules


LINEAGE_ID_PREFIX = "L_COUPLED"
SUPPRESSION_REASONS = (
    "did_widen",
    "slice never scheduled",
    "slice saturated/skipped",
    "node budget ended",
    "time ended",
    "depth coverage TT prune",
    "child dedup",
    "active-path recurrence",
    "other",
)
DESCENDANT_BUCKETS = ("0", "1-10", "11-100", "101-1000", ">1000")


def key_hex(key: bytes) -> str:
    return key.hex()


def _solver():
    from spider import simple_progressive_solver as sps

    return sps


def census_legal_by_tier(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> Dict[str, Any]:
    """Read-only A/B/C/D census of engine-legal actions.  Does not order."""

    sps = _solver()
    landing = sps.evaluate_deal_landings(state, rules=rules)
    total = [0, 0, 0, 0]
    tableau = [0, 0, 0, 0]
    deal_tier = None
    deal_legal = False
    immediate = 0
    for action in sps.enumerate_actions(state, rules=rules):
        tier = int(sps.classify_tier(state, action, landing=landing))
        total[tier] += 1
        if sps.is_deal(action):
            deal_tier = tier
            deal_legal = True
            continue
        tableau[tier] += 1
        src, dst, k = action
        if sps._would_complete_foundation(state, src, dst, k):
            immediate += 1
    return {
        "legal": sum(total),
        "legal_tableau": sum(tableau),
        "a": total[0],
        "b": total[1],
        "c": total[2],
        "d": total[3],
        "tableau_a": tableau[0],
        "tableau_b": tableau[1],
        "tableau_c": tableau[2],
        "tableau_d": tableau[3],
        "deal_tier": deal_tier,
        "deal_legal": deal_legal,
        "landing_score": None if landing is None else landing.score,
        "immediate_foundation_moves": immediate,
        "has_immediate_foundation_move": immediate > 0,
        "has_tier_a": total[0] > 0,
        "has_broader_than_a": (total[1] + total[2] + total[3]) > 0,
    }


def exposed_run_metrics(state: SpiderState) -> Dict[str, int]:
    """Cheap face-up same-suit geometry.  No campaign analysis."""

    longest = 0
    adjacencies = 0
    blocks = 0
    complete_ka = 0
    for col in state.columns:
        up = col.face_up
        if not up:
            continue
        run = 1
        for index in range(len(up) - 1, 0, -1):
            left, right = up[index - 1], up[index]
            if left.suit == right.suit and left.rank == right.rank + 1:
                run += 1
            else:
                break
        longest = max(longest, run)
        if run >= 2:
            blocks += 1
        if run >= 13 and up[-13].rank == 13 and SpiderState.is_movable_run(up[-13:]):
            complete_ka += 1
        for index in range(len(up) - 1):
            left, right = up[index], up[index + 1]
            if left.suit == right.suit and left.rank == right.rank + 1:
                adjacencies += 1
    return {
        "longest_exposed_same_suit_run": longest,
        "exposed_same_suit_adjacencies": adjacencies,
        "movable_same_suit_blocks": blocks,
        "exposed_complete_ka_runs": complete_ka,
    }


def foundation_proximity(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> Dict[str, Any]:
    """Descriptive cheap facts.  Not a search heuristic."""

    census = census_legal_by_tier(state, rules=rules)
    runs = exposed_run_metrics(state)
    return {
        **runs,
        "immediate_foundation_moves": census["immediate_foundation_moves"],
        "has_immediate_foundation_move": census["has_immediate_foundation_move"],
        "legal_tableau": census["legal_tableau"],
        "tableau_a": census["tableau_a"],
        "tableau_b": census["tableau_b"],
        "tableau_c": census["tableau_c"],
        "tableau_d": census["tableau_d"],
    }


def inspect_state(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> Dict[str, Any]:
    """One read-only snapshot: identity, census, cheap structure, proximity."""

    census = census_legal_by_tier(state, rules=rules)
    runs = exposed_run_metrics(state)
    structure = {
        "fd": sum(len(col.face_down) for col in state.columns),
        "fu": sum(len(col.face_up) for col in state.columns),
        "empties": sum(1 for col in state.columns if col.is_empty()),
        "foundations": len(state.foundations),
        "stock_rows": len(state.stock) // 10,
    }
    return {
        "key_hex": pack_state(state).hex(),
        **structure,
        "census": census,
        "proximity": {
            **runs,
            "immediate_foundation_moves": census["immediate_foundation_moves"],
            "has_immediate_foundation_move": census["has_immediate_foundation_move"],
        },
        "same_suit_joins": _same_suit_joins(state),
        "mixed_joins": _mixed_joins(state),
    }


def _same_suit_joins(state: SpiderState) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for index in range(len(up) - 1):
            left, right = up[index], up[index + 1]
            if left.rank == right.rank + 1 and left.suit == right.suit:
                n += 1
    return n


def _mixed_joins(state: SpiderState) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for index in range(len(up) - 1):
            left, right = up[index], up[index + 1]
            if left.rank == right.rank + 1 and left.suit != right.suit:
                n += 1
    return n


def permitted_at_pass(census: Dict[str, Any], pass_level: int) -> int:
    n = 0
    labels = ("tableau_a", "tableau_b", "tableau_c", "tableau_d")
    for tier, label in enumerate(labels):
        if tier <= pass_level:
            n += int(census.get(label) or 0)
    deal_tier = census.get("deal_tier")
    if census.get("deal_legal") and deal_tier is not None and int(deal_tier) <= pass_level:
        n += 1
    return n


def permission_delta(
    census: Dict[str, Any], from_pass: int, to_pass: int
) -> Dict[str, Any]:
    """Legal actions newly permitted when the pass ceiling rises."""

    labels = ("tableau_a", "tableau_b", "tableau_c", "tableau_d")
    newly = 0
    by_tier: List[Dict[str, Any]] = []
    lo = min(from_pass, to_pass)
    hi = max(from_pass, to_pass)
    start = lo + 1
    end = hi
    if to_pass < from_pass:
        start, end = to_pass + 1, from_pass
    for tier in range(start, end + 1):
        if 0 <= tier < len(labels):
            count = int(census.get(labels[tier]) or 0)
        else:
            count = 0
        deal_tier = census.get("deal_tier")
        if census.get("deal_legal") and deal_tier is not None and int(deal_tier) == tier:
            count += 1
        newly += count
        by_tier.append({"tier": tier, "count": count})
    return {
        "from_pass": from_pass,
        "to_pass": to_pass,
        "newly_permitted": newly if to_pass > from_pass else -newly,
        "by_tier": by_tier,
        "permitted_from": permitted_at_pass(census, from_pass),
        "permitted_to": permitted_at_pass(census, to_pass),
    }


def descendant_bucket(n: int) -> str:
    if n <= 0:
        return "0"
    if n <= 10:
        return "1-10"
    if n <= 100:
        return "11-100"
    if n <= 1000:
        return "101-1000"
    return ">1000"


def median_int(values: Sequence[int]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def classify_suppression_reason(
    *,
    first_pass: int,
    encounters: Sequence[dict],
    band_pass_reports: Sequence[dict],
    stop_reason: str,
    max_pass: int,
    first_band: Optional[int] = None,
) -> Tuple[str, str]:
    """Exact mechanism that prevented wider-pass expansion.

    Returns ``(reason, detail)``.  Reason is one of ``SUPPRESSION_REASONS``.
    """

    later_expanded = [
        item
        for item in encounters
        if int(item.get("pass", -1)) > first_pass and item.get("expanded")
    ]
    if later_expanded:
        passes = sorted({int(item["pass"]) for item in later_expanded})
        return "did_widen", f"expanded_at_passes={passes}"

    later_tt = [
        item
        for item in encounters
        if int(item.get("pass", -1)) > first_pass and item.get("tt_skip")
    ]
    if later_tt:
        sample = later_tt[0]
        return (
            "depth coverage TT prune",
            "pass={p} remaining={remaining} covered={covered} where={where}".format(
                p=sample.get("pass"),
                remaining=sample.get("remaining"),
                covered=sample.get("covered_remaining"),
                where=sample.get("where"),
            ),
        )

    later_dedup = [
        item
        for item in encounters
        if int(item.get("pass", -1)) > first_pass and item.get("child_dedup")
    ]
    if later_dedup:
        return "child dedup", f"events={len(later_dedup)}"

    later_cycle = [
        item
        for item in encounters
        if int(item.get("pass", -1)) > first_pass and item.get("path_cycle")
    ]
    if later_cycle:
        return "active-path recurrence", f"events={len(later_cycle)}"

    if first_band is None:
        for item in encounters:
            if item.get("expanded") and item.get("band") is not None:
                first_band = int(item["band"])
                break

    needed = first_pass + 1
    if first_band is not None and needed <= max_pass:
        next_at_band = [
            report
            for report in band_pass_reports
            if int(report.get("pass", -1)) == needed
            and int(report.get("band") or 0) >= first_band
        ]
        if next_at_band and all(
            report.get("skipped") or report.get("stop") == "saturated"
            for report in next_at_band
        ):
            bands = sorted({report.get("band") for report in next_at_band})
            return (
                "slice saturated/skipped",
                f"pass={needed} skipped at bands>={first_band} bands={bands}",
            )
        if not next_at_band:
            later_at_band = [
                report
                for report in band_pass_reports
                if int(report.get("pass", -1)) > first_pass
                and int(report.get("band") or 0) >= first_band
            ]
            if not later_at_band:
                if stop_reason == "node limit":
                    return (
                        "node budget ended",
                        f"no_pass_gt_{first_pass}_slice_at_bands>={first_band}",
                    )
                if stop_reason == "time limit":
                    return (
                        "time ended",
                        f"no_pass_gt_{first_pass}_slice_at_bands>={first_band}",
                    )
                return (
                    "slice never scheduled",
                    f"no_pass_gt_{first_pass}_slice_at_bands>={first_band} stop={stop_reason}",
                )

    later_slices = [
        report
        for report in band_pass_reports
        if int(report.get("pass", -1)) > first_pass
    ]
    ran = [
        report
        for report in later_slices
        if not report.get("skipped") and int(report.get("expanded") or 0) > 0
    ]
    saturated = [
        report
        for report in later_slices
        if report.get("skipped") or report.get("stop") == "saturated"
    ]
    if first_pass >= max_pass:
        return "slice never scheduled", f"first_pass={first_pass} max_pass={max_pass}"
    if saturated and not ran:
        bands = sorted({report.get("band") for report in saturated})
        return (
            "slice saturated/skipped",
            f"saturated_bands={bands} skipped_slices={len(saturated)}",
        )
    if not later_slices:
        if stop_reason == "node limit":
            return "node budget ended", "no_later_pass_slice_recorded"
        if stop_reason == "time limit":
            return "time ended", "no_later_pass_slice_recorded"
        return "slice never scheduled", f"stop={stop_reason}"
    if not ran:
        if stop_reason == "node limit":
            return "node budget ended", "later_slices_present_but_zero_expanded"
        if stop_reason == "time limit":
            return "time ended", "later_slices_present_but_zero_expanded"
        return "slice never scheduled", f"stop={stop_reason} later_slices={len(later_slices)}"

    generated = [
        item
        for item in encounters
        if int(item.get("pass", -1)) > first_pass and item.get("where") == "child_gen"
    ]
    if first_band is not None:
        ran_at_band = [
            report
            for report in ran
            if int(report.get("band") or 0) >= first_band
        ]
    else:
        ran_at_band = ran
    expanded_later_slices = sum(int(report.get("expanded") or 0) for report in ran_at_band)
    if not generated:
        detail = (
            "wider_slice_ran_but_state_not_reached "
            f"later_slice_expansions={expanded_later_slices} stop={stop_reason} "
            f"first_band={first_band}"
        )
        if stop_reason == "node limit":
            return "node budget ended", detail
        if stop_reason == "time limit":
            return "time ended", detail
        return "other", detail
    return "other", f"generated_but_not_expanded events={len(generated)} stop={stop_reason}"


def reconstruct_coupled_lineage(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    rules: MobilityWareRules = MW_RULES,
    lineage_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Replay one stored path and split it on Deal.  Does not search."""

    sps = _solver()
    state = opening.clone()
    segments: List[dict] = []
    prefix: List[Action] = []
    depth = 0
    for action in actions:
        if sps.is_deal(action):
            pre = inspect_state(state, rules=rules)
            pre["depth"] = depth
            pre["stock_rows_remaining"] = pre["stock_rows"]
            snap = sps._capture(state, action)
            try:
                sps.apply_action(state, action, rules=rules)
            except (ValueError, AssertionError):
                sps._restore(state, snap)
                raise
            depth += 1
            prefix.append(("deal",))
            post = inspect_state(state, rules=rules)
            post["depth"] = depth
            post["stock_rows_remaining"] = post["stock_rows"]
            segments.append(
                {
                    "deal_index": len(segments) + 1,
                    "pre": pre,
                    "post": post,
                    "prefix_length": len(prefix),
                }
            )
            continue
        sps.apply_action(state, action, rules=rules)
        depth += 1
        prefix.append(action)  # type: ignore[arg-type]
    terminal = inspect_state(state, rules=rules)
    terminal["depth"] = depth
    fd = terminal["fd"]
    deals = len(segments)
    ident = lineage_id or f"{LINEAGE_ID_PREFIX}_FD{fd}_DEALS{deals}_DEPTH{depth}"
    return {
        "lineage_id": ident,
        "actions": list(actions),
        "n_deals": deals,
        "terminal": terminal,
        "segments": segments,
        "replay_ok": True,
        "path_length": len(actions),
    }


def _encounter_record(
    *,
    pass_level: int,
    remaining: int,
    expansion: int,
    depth: int,
    fd: int,
    foundations: int,
    stock_rows: int,
    tt_status: str,
    expanded: bool,
    tt_skip: bool,
    covered_remaining: int,
    where: str,
    child_dedup: bool = False,
    path_cycle: bool = False,
    band: Optional[int] = None,
) -> dict:
    return {
        "pass": pass_level,
        "remaining": remaining,
        "expansion": expansion,
        "depth": depth,
        "fd": fd,
        "foundations": foundations,
        "stock_rows": stock_rows,
        "tt_status": tt_status,
        "expanded": expanded,
        "tt_skip": tt_skip,
        "covered_remaining": covered_remaining,
        "where": where,
        "child_dedup": child_dedup,
        "path_cycle": path_cycle,
        "band": band,
    }


@dataclass
class PostDealAudit:
    """Side-channel collector.  Search must not read these fields."""

    watched: Dict[bytes, dict] = field(default_factory=dict)
    encounters: Dict[bytes, List[dict]] = field(default_factory=dict)
    checkpoint_children: List[dict] = field(default_factory=list)
    frame_finishes: Dict[bytes, List[dict]] = field(default_factory=dict)
    stock_empty_best: Optional[dict] = field(default=None)
    stock_empty_candidates: List[dict] = field(default_factory=list)
    best_empty_fd: int = field(default=10**9)
    empty_pass_b_children: List[dict] = field(default_factory=list)
    lineage: Optional[dict] = field(default=None)
    summary: Optional[dict] = field(default=None)
    current_band: int = 0

    def watch(self, key: bytes, *, origin: str, **meta: Any) -> None:
        slot = self.watched.get(key)
        if slot is None:
            self.watched[key] = {"origin": origin, "origins": [origin], **meta}
            self.encounters.setdefault(key, [])
            return
        if origin not in slot["origins"]:
            slot["origins"].append(origin)
        for name, value in meta.items():
            slot.setdefault(name, value)

    def is_watched(self, key: bytes) -> bool:
        return key in self.watched

    def record_encounter(self, key: bytes, record: dict) -> None:
        if key not in self.watched:
            return
        self.encounters.setdefault(key, []).append(record)

    def on_expand(
        self,
        *,
        key: bytes,
        pass_level: int,
        remaining: int,
        expansion: int,
        depth: int,
        fd: int,
        foundations: int,
        stock_rows: int,
        tt_status: str,
        covered_remaining: int,
        snapshot: Optional[dict] = None,
    ) -> None:
        if key not in self.watched:
            return
        self.record_encounter(
            key,
            _encounter_record(
                pass_level=pass_level,
                remaining=remaining,
                expansion=expansion,
                depth=depth,
                fd=fd,
                foundations=foundations,
                stock_rows=stock_rows,
                tt_status=tt_status,
                expanded=True,
                tt_skip=False,
                covered_remaining=covered_remaining,
                where="expand",
                band=self.current_band,
            ),
        )
        slot = self.watched[key]
        slot["last_snapshot"] = snapshot
        slot["last_pass"] = pass_level
        slot.setdefault("first_snapshot", snapshot)

    def on_tt_skip(
        self,
        *,
        key: bytes,
        pass_level: int,
        remaining: int,
        expansion: int,
        depth: int,
        fd: int,
        foundations: int,
        stock_rows: int,
        covered_remaining: int,
        where: str,
    ) -> None:
        if key not in self.watched:
            return
        self.record_encounter(
            key,
            _encounter_record(
                pass_level=pass_level,
                remaining=remaining,
                expansion=expansion,
                depth=depth,
                fd=fd,
                foundations=foundations,
                stock_rows=stock_rows,
                tt_status="skip",
                expanded=False,
                tt_skip=True,
                covered_remaining=covered_remaining,
                where=where,
                band=self.current_band,
            ),
        )

    def on_child_blocked(
        self,
        *,
        key: bytes,
        pass_level: int,
        remaining: int,
        expansion: int,
        depth: int,
        kind: str,
    ) -> None:
        if key not in self.watched:
            return
        self.record_encounter(
            key,
            _encounter_record(
                pass_level=pass_level,
                remaining=remaining,
                expansion=expansion,
                depth=depth,
                fd=-1,
                foundations=-1,
                stock_rows=-1,
                tt_status=kind,
                expanded=False,
                tt_skip=False,
                covered_remaining=-1,
                where="child_gen",
                child_dedup=kind == "child_dedup",
                path_cycle=kind == "path_cycle",
                band=self.current_band,
            ),
        )

    def on_checkpoint_deal(
        self,
        *,
        parent_key: bytes,
        child_key: bytes,
        dealt: int,
        pass_level: int,
        depth: int,
        remaining: int,
        pre: dict,
        post: dict,
        child_novel: bool,
        tt_skip: bool,
        expanded: bool,
        n_tableau: int,
        probe: bool,
    ) -> None:
        self.watch(
            parent_key,
            origin="checkpoint_parent",
            dealt=dealt,
            pass_level=pass_level,
        )
        self.watch(
            child_key,
            origin="probe_deal_child" if probe else "checkpoint_deal_child",
            dealt=dealt,
            parent_key_hex=parent_key.hex(),
            pass_level=pass_level,
        )
        self.checkpoint_children.append(
            {
                "dealt": dealt,
                "parent_key_hex": parent_key.hex(),
                "child_key_hex": child_key.hex(),
                "pass": pass_level,
                "depth": depth,
                "remaining": remaining,
                "pre": pre,
                "post": post,
                "child_novel": child_novel,
                "tt_skip": tt_skip,
                "expanded": expanded,
                "n_tableau": n_tableau,
                "probe": probe,
                "descendant_expansions": 0,
                "direct_expanded": 0,
                "exp_before_next_deal": 0,
                "best_descendant_fd": post.get("fd"),
                "best_descendant_foundations": post.get("foundations") or 0,
                "next_deal_reached": False,
                "pop_reason": None,
            }
        )

    def on_frame_finished(
        self,
        *,
        key: bytes,
        pass_level: int,
        descendant_expansions: int,
        direct_expanded: int,
        exp_before_next_deal: int,
        best_descendant_fd: int,
        best_descendant_foundations: int,
        next_deal_reached: bool,
        pop_reason: str,
        from_deal: bool,
    ) -> None:
        record = {
            "pass": pass_level,
            "descendant_expansions": descendant_expansions,
            "direct_expanded": direct_expanded,
            "exp_before_next_deal": exp_before_next_deal,
            "best_descendant_fd": best_descendant_fd
            if best_descendant_fd < 10**9
            else None,
            "best_descendant_foundations": best_descendant_foundations,
            "next_deal_reached": next_deal_reached,
            "pop_reason": pop_reason,
            "from_deal": from_deal,
            "band": self.current_band,
        }
        self.frame_finishes.setdefault(key, []).append(record)
        hex_key = key.hex()
        for child in reversed(self.checkpoint_children):
            if child["child_key_hex"] == hex_key and child["pass"] == pass_level:
                child["descendant_expansions"] = descendant_expansions
                child["direct_expanded"] = direct_expanded
                child["exp_before_next_deal"] = exp_before_next_deal
                child["best_descendant_fd"] = record["best_descendant_fd"]
                child["best_descendant_foundations"] = best_descendant_foundations
                child["next_deal_reached"] = next_deal_reached
                child["pop_reason"] = pop_reason
                break

    def note_empty_b_child(
        self,
        *,
        parent_key: bytes,
        action: Any,
        child_key: bytes,
        pass_level: int,
        band: int,
        novel: bool,
        tt_skip: bool,
        expanded: bool,
        fd: int,
        foundations: int,
    ) -> None:
        self.watch(child_key, origin="empty_tier_b_child", parent_key_hex=parent_key.hex())
        self.empty_pass_b_children.append(
            {
                "parent_key_hex": parent_key.hex(),
                "child_key_hex": child_key.hex(),
                "action": list(action) if isinstance(action, tuple) else action,
                "pass": pass_level,
                "band": band,
                "novel": novel,
                "tt_covered": tt_skip,
                "expanded": expanded,
                "fd": fd,
                "foundations": foundations,
            }
        )

    def on_stock_empty(
        self,
        *,
        key: bytes,
        pass_level: int,
        remaining: int,
        expansion: int,
        depth: int,
        snapshot: dict,
    ) -> None:
        fd = int(snapshot["fd"])
        record = {
            "key_hex": snapshot["key_hex"],
            "pass": pass_level,
            "remaining": remaining,
            "expansion": expansion,
            "depth": depth,
            "fd": fd,
            "fu": snapshot["fu"],
            "empties": snapshot["empties"],
            "foundations": snapshot["foundations"],
            "census": snapshot["census"],
            "proximity": snapshot["proximity"],
            "same_suit_joins": snapshot["same_suit_joins"],
            "mixed_joins": snapshot["mixed_joins"],
        }
        self.watch(key, origin="stock_empty", fd=fd, pass_level=pass_level)
        if fd < self.best_empty_fd:
            self.best_empty_fd = fd
            self.stock_empty_best = record
            self.stock_empty_candidates = [record]
        elif fd == self.best_empty_fd:
            self.stock_empty_candidates.append(record)
            if self.stock_empty_best is None or (
                depth,
                expansion,
            ) < (
                self.stock_empty_best.get("depth") or 10**9,
                self.stock_empty_best.get("expansion") or 10**9,
            ):
                self.stock_empty_best = record

    def finalize(
        self,
        *,
        opening: SpiderState,
        fd_by_stock: Sequence[dict],
        band_pass_reports: Sequence[dict],
        stop_reason: str,
        max_pass: int,
        saturated_passes: Sequence[int],
        max_foundations: int,
        nodes: int,
        rules: MobilityWareRules = MW_RULES,
    ) -> dict:
        strongest = None
        for dealt in range(5, -1, -1):
            cell = fd_by_stock[dealt] if dealt < len(fd_by_stock) else None
            if cell and cell.get("face_down") is not None and cell.get("actions") is not None:
                strongest = cell
                break
        lineage = None
        if strongest is not None:
            actions = list(strongest.get("actions") or [])
            lineage = reconstruct_coupled_lineage(
                opening,
                actions,
                rules=rules,
                lineage_id=(
                    f"{LINEAGE_ID_PREFIX}_FD{strongest['face_down']}"
                    f"_DEALS{strongest['deals_completed']}"
                    f"_DEPTH{strongest['depth']}"
                ),
            )
            lineage["source"] = {
                "deals_completed": strongest["deals_completed"],
                "face_down": strongest["face_down"],
                "stock_rows": strongest["stock_rows"],
                "foundations": strongest["foundations"],
                "depth": strongest["depth"],
                "cost": strongest["cost"],
            }
            for segment in lineage["segments"]:
                self._join_segment(segment, band_pass_reports, stop_reason, max_pass)
            self._join_terminal(
                lineage["terminal"], band_pass_reports, stop_reason, max_pass
            )
        self.lineage = lineage

        descendants = [
            int(child.get("descendant_expansions") or 0)
            for child in self.checkpoint_children
            if child.get("expanded")
        ]
        dist = {label: 0 for label in DESCENDANT_BUCKETS}
        for value in descendants:
            dist[descendant_bucket(value)] += 1
        reopened = 0
        never = 0
        reasons: Dict[str, int] = defaultdict(int)
        checkpoint_lifecycle: List[dict] = []
        for child in self.checkpoint_children:
            key = bytes.fromhex(child["child_key_hex"])
            first_pass = int(child.get("pass") or 0)
            life = self._pass_lifecycle(
                key, child.get("post", {}).get("census"), band_pass_reports, stop_reason, max_pass
            )
            child["wider_pass"] = life
            reason = life["suppression_reason"]
            reasons[reason] += 1
            if reason == "did_widen":
                reopened += 1
            else:
                never += 1
            checkpoint_lifecycle.append(
                {
                    "child_key_hex": child["child_key_hex"],
                    "dealt": child["dealt"],
                    "first_pass": first_pass,
                    "suppression_reason": reason,
                    "suppression_detail": life["suppression_detail"],
                    "passes": life["passes"],
                }
            )

        if self.stock_empty_best is not None:
            empty_key = bytes.fromhex(self.stock_empty_best["key_hex"])
            empty_life = self._pass_lifecycle(
                empty_key,
                self.stock_empty_best.get("census"),
                band_pass_reports,
                stop_reason,
                max_pass,
            )
            self.stock_empty_best["wider_pass"] = empty_life

        max_fnd_desc = 0
        for child in self.checkpoint_children:
            max_fnd_desc = max(
                max_fnd_desc, int(child.get("best_descendant_foundations") or 0)
            )

        summary = {
            "lineage": lineage,
            "stock_empty": self.stock_empty_best,
            "aggregate": {
                "checkpoint_children_entered": sum(
                    1 for child in self.checkpoint_children if child.get("expanded")
                ),
                "checkpoint_children_tt_skip": sum(
                    1 for child in self.checkpoint_children if child.get("tt_skip")
                ),
                "checkpoint_children_total": len(self.checkpoint_children),
                "median_descendants": median_int(descendants),
                "descendant_distribution": dist,
                "reopened_wider": reopened,
                "never_widened": never,
                "non_widen_reasons": dict(reasons),
                "max_foundations_checkpoint_descendant": max_fnd_desc,
                "max_foundations_search": max_foundations,
            },
            "checkpoint_lifecycle": checkpoint_lifecycle,
            "saturated_passes": list(saturated_passes),
            "stop_reason": stop_reason,
            "nodes": nodes,
            "watched": len(self.watched),
        }
        summary["verdict"] = choose_verdict(summary)
        summary["hypothesis"] = classify_hypothesis(summary)
        self.summary = summary
        return summary

    def _join_segment(
        self,
        segment: dict,
        band_pass_reports: Sequence[dict],
        stop_reason: str,
        max_pass: int,
    ) -> None:
        pre_key = bytes.fromhex(segment["pre"]["key_hex"])
        post_key = bytes.fromhex(segment["post"]["key_hex"])
        segment["pre"]["encounters"] = [
            dict(item) for item in self.encounters.get(pre_key, [])
        ]
        segment["post"]["encounters"] = [
            dict(item) for item in self.encounters.get(post_key, [])
        ]
        segment["pre"]["wider_pass"] = self._pass_lifecycle(
            pre_key, segment["pre"].get("census"), band_pass_reports, stop_reason, max_pass
        )
        segment["post"]["wider_pass"] = self._pass_lifecycle(
            post_key,
            segment["post"].get("census"),
            band_pass_reports,
            stop_reason,
            max_pass,
        )
        hex_post = segment["post"]["key_hex"]
        match = None
        for child in self.checkpoint_children:
            if child["child_key_hex"] == hex_post:
                match = child
                break
        if match is None:
            finishes = self.frame_finishes.get(post_key) or []
            finish = finishes[0] if finishes else None
            segment["continuation"] = {
                "matched_checkpoint": False,
                "descendant_expansions": None if finish is None else finish["descendant_expansions"],
                "direct_expanded": None if finish is None else finish["direct_expanded"],
                "exp_before_next_deal": None if finish is None else finish["exp_before_next_deal"],
                "best_descendant_fd": None if finish is None else finish["best_descendant_fd"],
                "best_descendant_foundations": None
                if finish is None
                else finish["best_descendant_foundations"],
                "next_deal_reached": None if finish is None else finish["next_deal_reached"],
                "pop_reason": None if finish is None else finish["pop_reason"],
            }
        else:
            segment["continuation"] = {
                "matched_checkpoint": True,
                "descendant_expansions": match.get("descendant_expansions"),
                "direct_expanded": match.get("direct_expanded"),
                "exp_before_next_deal": match.get("exp_before_next_deal"),
                "best_descendant_fd": match.get("best_descendant_fd"),
                "best_descendant_foundations": match.get("best_descendant_foundations"),
                "next_deal_reached": match.get("next_deal_reached"),
                "pop_reason": match.get("pop_reason"),
                "expanded_at_pass": match.get("direct_expanded"),
            }

    def _join_terminal(
        self,
        terminal: dict,
        band_pass_reports: Sequence[dict],
        stop_reason: str,
        max_pass: int,
    ) -> None:
        key = bytes.fromhex(terminal["key_hex"])
        terminal["encounters"] = [dict(item) for item in self.encounters.get(key, [])]
        terminal["wider_pass"] = self._pass_lifecycle(
            key, terminal.get("census"), band_pass_reports, stop_reason, max_pass
        )

    def _pass_lifecycle(
        self,
        key: bytes,
        census: Optional[dict],
        band_pass_reports: Sequence[dict],
        stop_reason: str,
        max_pass: int,
    ) -> dict:
        events = self.encounters.get(key, [])
        by_pass: Dict[int, dict] = {}
        first_pass = None
        for event in events:
            pass_level = int(event["pass"])
            slot = by_pass.get(pass_level)
            if slot is None:
                newly = None
                if census is not None and first_pass is not None:
                    newly = permission_delta(census, first_pass, pass_level)[
                        "newly_permitted"
                    ]
                elif census is not None:
                    newly = 0
                slot = {
                    "pass": pass_level,
                    "first_expansion": event["expansion"] if event.get("expanded") else None,
                    "first_event_expansion": event["expansion"],
                    "remaining": event.get("remaining"),
                    "tt_status": event.get("tt_status"),
                    "expanded": bool(event.get("expanded")),
                    "tt_skip": bool(event.get("tt_skip")),
                    "newly_permitted_vs_first_pass": newly,
                    "encounters": 0,
                    "descendants": None,
                    "best_progress_fd": event.get("fd") if event.get("fd", -1) >= 0 else None,
                    "best_progress_foundations": event.get("foundations")
                    if event.get("foundations", -1) >= 0
                    else None,
                }
                by_pass[pass_level] = slot
            slot["encounters"] += 1
            if event.get("expanded"):
                slot["expanded"] = True
                if slot["first_expansion"] is None:
                    slot["first_expansion"] = event["expansion"]
            if event.get("tt_skip"):
                slot["tt_skip"] = True
            if first_pass is None:
                first_pass = pass_level
        finishes = self.frame_finishes.get(key) or []
        for finish in finishes:
            slot = by_pass.get(int(finish["pass"]))
            if slot is None:
                continue
            slot["descendants"] = finish.get("descendant_expansions")
            if finish.get("best_descendant_fd") is not None:
                prev = slot["best_progress_fd"]
                slot["best_progress_fd"] = (
                    finish["best_descendant_fd"]
                    if prev is None
                    else min(prev, finish["best_descendant_fd"])
                )
            fnd = finish.get("best_descendant_foundations") or 0
            prev_f = slot["best_progress_foundations"] or 0
            slot["best_progress_foundations"] = max(prev_f, fnd)
        if first_pass is None:
            first_pass = 0
        first_band = None
        for event in events:
            if event.get("expanded") and event.get("band") is not None:
                first_band = int(event["band"])
                break
        reason, detail = classify_suppression_reason(
            first_pass=first_pass,
            encounters=events,
            band_pass_reports=band_pass_reports,
            stop_reason=stop_reason,
            max_pass=max_pass,
            first_band=first_band,
        )
        return {
            "first_pass": first_pass,
            "passes": {str(index): by_pass.get(index) for index in range(4)},
            "suppression_reason": reason,
            "suppression_detail": detail,
            "seen": bool(events),
        }


def classify_hypothesis(summary: dict) -> str:
    lineage = summary.get("lineage") or {}
    aggregate = summary.get("aggregate") or {}
    stock_empty = summary.get("stock_empty")
    segments = lineage.get("segments") or []
    reasons = aggregate.get("non_widen_reasons") or {}
    median_desc = aggregate.get("median_descendants")
    reopened = int(aggregate.get("reopened_wider") or 0)
    never = int(aggregate.get("never_widened") or 0)
    entered = int(aggregate.get("checkpoint_children_entered") or 0)

    pass0_exhausted = False
    broader_available = False
    for segment in segments:
        post = segment.get("post") or {}
        census = post.get("census") or {}
        if int(census.get("tableau_a") or 0) == 0 and (
            int(census.get("tableau_b") or 0)
            + int(census.get("tableau_c") or 0)
            + int(census.get("tableau_d") or 0)
        ) > 0:
            pass0_exhausted = True
            broader_available = True

    empty_reached = (
        stock_empty is not None
        and lineage.get("source", {}).get("stock_rows") == 0
    )
    lineage_sat = any(
        ((segment.get("post") or {}).get("wider_pass") or {}).get("suppression_reason")
        == "slice saturated/skipped"
        for segment in segments
    )
    if lineage_sat:
        return "SATURATION_SCHEDULE_SKIPS_WIDER_CONTINUATION"
    plenty = median_desc is not None and median_desc >= 100
    tt_or_sat = (
        int(reasons.get("depth coverage TT prune") or 0)
        + int(reasons.get("slice saturated/skipped") or 0)
    )
    dominant_tt = entered > 0 and tt_or_sat >= max(1, entered // 2)

    if empty_reached and plenty and reopened >= never and not pass0_exhausted:
        return "STOCK_EMPTY_CONVERSION_FAILURE"
    if empty_reached and (median_desc is None or median_desc < 20) and pass0_exhausted and never > reopened:
        # reached empty via probe chain but each hop was starved
        if dominant_tt:
            return "SATURATION_SCHEDULE_SKIPS_WIDER_CONTINUATION"
        return "USEFUL_STATE_NEVER_REOPENS_WIDER"
    if pass0_exhausted and reopened > never:
        return "USEFUL_STATE_REOPENS_AT_WIDER_PASS"
    if pass0_exhausted and never > reopened and not dominant_tt:
        return "USEFUL_STATE_NEVER_REOPENS_WIDER"
    if dominant_tt:
        if int(reasons.get("slice saturated/skipped") or 0) >= int(
            reasons.get("depth coverage TT prune") or 0
        ):
            return "SATURATION_SCHEDULE_SKIPS_WIDER_CONTINUATION"
        return "DEPTH_TT_CORRECTLY_SUPPRESSES_REVISIT"
    if pass0_exhausted:
        return "PASS0_CONTINUATION_EXHAUSTED"
    if plenty and int(aggregate.get("max_foundations_search") or 0) == 0:
        return "POST_DEAL_LINEAGE_HAS_PLENTY_OF_ALLOWED_PLAY"
    if empty_reached:
        return "STOCK_EMPTY_CONVERSION_FAILURE"
    return "MULTIPLE_CAUSES"


def choose_verdict(summary: dict) -> str:
    """Exactly one primary verdict from gathered evidence."""

    if not summary.get("lineage"):
        return "INCONCLUSIVE"
    hypothesis = classify_hypothesis(summary)
    aggregate = summary.get("aggregate") or {}
    reasons = aggregate.get("non_widen_reasons") or {}
    reopened = int(aggregate.get("reopened_wider") or 0)
    never = int(aggregate.get("never_widened") or 0)
    median_desc = aggregate.get("median_descendants")
    stock_empty = summary.get("stock_empty")
    max_fnd = int(aggregate.get("max_foundations_search") or 0)
    lineage = summary["lineage"]
    terminal = lineage.get("terminal") or {}
    segments = lineage.get("segments") or []

    post_starved = False
    post_broad_legal = False
    post_widened = False
    for segment in segments:
        census = (segment.get("post") or {}).get("census") or {}
        life = (segment.get("post") or {}).get("wider_pass") or {}
        a = int(census.get("tableau_a") or 0)
        broader = (
            int(census.get("tableau_b") or 0)
            + int(census.get("tableau_c") or 0)
            + int(census.get("tableau_d") or 0)
        )
        if a == 0 and broader > 0:
            post_starved = True
            post_broad_legal = True
        if life.get("suppression_reason") == "did_widen":
            post_widened = True

    sat_or_tt = (
        int(reasons.get("slice saturated/skipped") or 0)
        + int(reasons.get("depth coverage TT prune") or 0)
        + int(reasons.get("node budget ended") or 0)
        + int(reasons.get("slice never scheduled") or 0)
    )

    deep = median_desc is not None and median_desc >= 100
    empty_fd = None if stock_empty is None else stock_empty.get("fd")
    empty_pass = None if stock_empty is None else stock_empty.get("pass")
    empty_a = (
        None
        if stock_empty is None
        else (stock_empty.get("census") or {}).get("tableau_a")
    )
    empty_broader = 0
    if stock_empty is not None:
        census = stock_empty.get("census") or {}
        empty_broader = (
            int(census.get("tableau_b") or 0)
            + int(census.get("tableau_c") or 0)
            + int(census.get("tableau_d") or 0)
        )
    empty_widened = (
        (stock_empty or {}).get("wider_pass", {}).get("suppression_reason") == "did_widen"
    )
    reached_empty = stock_empty is not None and terminal.get("stock_rows") == 0

    # Dominant: good lineage survives all Deals; stall is conversion after stock empty.
    if (
        reached_empty
        and (empty_a or 0) + empty_broader > 0
        and (empty_widened or (empty_pass is not None and empty_pass >= 1) or deep)
        and max_fnd == 0
        and not (post_starved and never > reopened and not post_widened)
    ):
        return "STOCK_EMPTY_CONVERSION_IS_PRIMARY_BLOCKER"

    if post_starved and post_broad_legal and not post_widened and never > reopened:
        if sat_or_tt >= max(1, never // 2):
            return "TT_OR_SATURATION_BLOCKS_POST_DEAL_CONTINUATION"
        return "POST_DEAL_PASS_STARVATION_CONFIRMED"

    if post_starved and post_widened and reopened >= never:
        if max_fnd == 0 and deep:
            return "POST_DEAL_SEARCH_IS_DEEP_BUT_UNPRODUCTIVE"
        return "POST_DEAL_WIDER_COVERAGE_ALREADY_EFFECTIVE"

    if sat_or_tt > reopened and never > reopened:
        return "TT_OR_SATURATION_BLOCKS_POST_DEAL_CONTINUATION"

    if deep and max_fnd == 0:
        return "POST_DEAL_SEARCH_IS_DEEP_BUT_UNPRODUCTIVE"

    if hypothesis == "MULTIPLE_CAUSES":
        return "MULTIPLE_CAUSES"
    if hypothesis == "STOCK_EMPTY_CONVERSION_FAILURE":
        return "STOCK_EMPTY_CONVERSION_IS_PRIMARY_BLOCKER"
    if hypothesis == "USEFUL_STATE_NEVER_REOPENS_WIDER":
        return "POST_DEAL_PASS_STARVATION_CONFIRMED"
    if hypothesis == "USEFUL_STATE_REOPENS_AT_WIDER_PASS":
        return "POST_DEAL_WIDER_COVERAGE_ALREADY_EFFECTIVE"
    if hypothesis in (
        "SATURATION_SCHEDULE_SKIPS_WIDER_CONTINUATION",
        "DEPTH_TT_CORRECTLY_SUPPRESSES_REVISIT",
    ):
        return "TT_OR_SATURATION_BLOCKS_POST_DEAL_CONTINUATION"
    if hypothesis == "POST_DEAL_LINEAGE_HAS_PLENTY_OF_ALLOWED_PLAY":
        return "POST_DEAL_SEARCH_IS_DEEP_BUT_UNPRODUCTIVE"
    if hypothesis == "PASS0_CONTINUATION_EXHAUSTED":
        return "POST_DEAL_PASS_STARVATION_CONFIRMED"
    return "MULTIPLE_CAUSES"


def next_recommendation(verdict: str) -> str:
    if verdict == "POST_DEAL_PASS_STARVATION_CONFIRMED":
        return (
            "Keep the best-reveal Deal probe. Next: give the coupled post-Deal "
            "fd-record states a bounded same-slice Pass-1 continuation, without "
            "Deal preparation or foundation heuristics."
        )
    if verdict == "POST_DEAL_WIDER_COVERAGE_ALREADY_EFFECTIVE":
        return (
            "Do not add post-Deal pass promotion. Next: inspect why wider-pass "
            "continuation from the coupled lineage still fails to assemble a suit."
        )
    if verdict == "STOCK_EMPTY_CONVERSION_IS_PRIMARY_BLOCKER":
        return (
            "Keep the probe and do not add Deal preparation. Next: diagnose "
            "stock-empty conversion from the fd-14 empty-stock tableau using "
            "existing cheap same-suit run facts only."
        )
    if verdict == "TT_OR_SATURATION_BLOCKS_POST_DEAL_CONTINUATION":
        return (
            "Do not change Deal scoring and do not add foundation heuristics. "
            "Next: keep Pass 1 live on the depth band that first records the "
            "coupled post-Deal fd-14 states; do not let unique_new=0 in a "
            "shallower band saturate that pass away."
        )
    if verdict == "POST_DEAL_SEARCH_IS_DEEP_BUT_UNPRODUCTIVE":
        return (
            "Do not widen Pass 0 after Deal and do not add quotas. Next: add a "
            "descriptive same-suit assembly audit on the coupled stock-empty "
            "lineage; still no new search heuristic."
        )
    if verdict == "MULTIPLE_CAUSES":
        return (
            "Do not implement a combined fix. Next: isolate the coupled "
            "stock-empty node under a single-pass replay before changing scheduling."
        )
    return (
        "Reproduce the v0.5 fd-14 Deal-5 lineage with telemetry on before "
        "changing search policy."
    )


def compact_lineage_for_json(lineage: Optional[dict]) -> Optional[dict]:
    if lineage is None:
        return None
    segments = []
    for segment in lineage.get("segments") or []:
        pre = segment.get("pre") or {}
        post = segment.get("post") or {}
        cont = segment.get("continuation") or {}
        census_pre = pre.get("census") or {}
        census_post = post.get("census") or {}
        segments.append(
            {
                "deal_index": segment.get("deal_index"),
                "pre": {
                    "key_hex": pre.get("key_hex"),
                    "depth": pre.get("depth"),
                    "fd": pre.get("fd"),
                    "fu": pre.get("fu"),
                    "empties": pre.get("empties"),
                    "foundations": pre.get("foundations"),
                    "stock_rows": pre.get("stock_rows"),
                    "census": census_pre,
                    "proximity": pre.get("proximity"),
                    "wider_pass": _compact_wider(pre.get("wider_pass")),
                },
                "post": {
                    "key_hex": post.get("key_hex"),
                    "depth": post.get("depth"),
                    "fd": post.get("fd"),
                    "fu": post.get("fu"),
                    "empties": post.get("empties"),
                    "foundations": post.get("foundations"),
                    "stock_rows": post.get("stock_rows"),
                    "census": census_post,
                    "proximity": post.get("proximity"),
                    "wider_pass": _compact_wider(post.get("wider_pass")),
                },
                "continuation": cont,
            }
        )
    terminal = lineage.get("terminal") or {}
    return {
        "lineage_id": lineage.get("lineage_id"),
        "source": lineage.get("source"),
        "n_deals": lineage.get("n_deals"),
        "path_length": lineage.get("path_length"),
        "replay_ok": lineage.get("replay_ok"),
        "segments": segments,
        "terminal": {
            "key_hex": terminal.get("key_hex"),
            "depth": terminal.get("depth"),
            "fd": terminal.get("fd"),
            "fu": terminal.get("fu"),
            "empties": terminal.get("empties"),
            "foundations": terminal.get("foundations"),
            "stock_rows": terminal.get("stock_rows"),
            "census": terminal.get("census"),
            "proximity": terminal.get("proximity"),
            "wider_pass": _compact_wider(terminal.get("wider_pass")),
        },
    }


def _compact_wider(life: Optional[dict]) -> Optional[dict]:
    if not life:
        return None
    passes = {}
    for label, slot in (life.get("passes") or {}).items():
        if slot is None:
            passes[label] = None
            continue
        passes[label] = {
            "pass": slot.get("pass"),
            "first_expansion": slot.get("first_expansion"),
            "remaining": slot.get("remaining"),
            "tt_status": slot.get("tt_status"),
            "expanded": slot.get("expanded"),
            "tt_skip": slot.get("tt_skip"),
            "newly_permitted_vs_first_pass": slot.get("newly_permitted_vs_first_pass"),
            "encounters": slot.get("encounters"),
            "descendants": slot.get("descendants"),
            "best_progress_fd": slot.get("best_progress_fd"),
            "best_progress_foundations": slot.get("best_progress_foundations"),
        }
    return {
        "first_pass": life.get("first_pass"),
        "passes": passes,
        "suppression_reason": life.get("suppression_reason"),
        "suppression_detail": life.get("suppression_detail"),
        "seen": life.get("seen"),
    }
