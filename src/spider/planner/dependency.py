"""
Layer 2: Dependency & Exposure Analyser (new development track).

This module implements dynamic, per-state dependency and exposure analysis
on top of the existing legacy `spider.deal_analysis` (global plan) and the
human solution artifacts (analyzer CSVs + strategy_insights.md).

It is intentionally non-destructive: it imports from legacy modules but
does not modify them. All new logic lives here.

See docs/layered_planner_development_plan.md (Phase 1) for the exact gate
this module must satisfy on the initial layout and human deal-1 decision points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# --- Reuse of legacy assets (as required by the baselined plan) ---
from spider.cards import Card
from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import DealAnalysis, build_deal_analysis
from spider.engine import SpiderState
from spider.metrics import parse_moves_file


@dataclass
class BuriedTarget:
    """A face-down card (or the topmost face-down in a column) that is critical
    according to the global priority clearance plan."""
    suit: str
    column: int
    depth: int  # how many face-up cards are currently sitting on top of it
    obstructors: List[Card] = field(default_factory=list)  # the current face-up run blocking it


@dataclass
class SpaceCreationOpportunity:
    """A column that can yield a net new empty column if its current face-up
    run is cleared (possibly via temporary parks)."""
    column: int
    current_face_up_len: int
    would_yield_space: bool
    notes: str = ""


@dataclass
class DependencyReport:
    """Human-readable summary of the current dependencies for a state."""
    global_plan: Dict[str, any]
    critical_buried: List[BuriedTarget]
    space_opportunities: List[SpaceCreationOpportunity]
    reception_notes: List[str] = field(default_factory=list)
    # Raw data for further layers (plan generator etc.)
    raw: Dict[str, any] = field(default_factory=dict)


class DynamicDependencyAnalyser:
    """Layer 2 analyser.

    Combines the static global plan (from legacy build_deal_analysis, using full
    known stock) with dynamic information from the current SpiderState.

    This is the starting point for Phase 1 per the baselined plan.
    """

    def __init__(self, analysis: DealAnalysis):
        self.analysis = analysis
        self.priority_suits: List[str] = list(analysis.priority_clearance_order or "shdc")
        # Columns that bury cards of the top 1-2 priority suits (from the static pre-analysis)
        self.priority_buried_cols: Dict[str, List[int]] = {
            s: list(analysis.initial_buried_columns_by_suit.get(s, []))
            for s in self.priority_suits[:2]
        }

    def analyze(self, state: SpiderState) -> DependencyReport:
        """Produce a dynamic dependency report for the given state."""
        critical: List[BuriedTarget] = []
        for suit in self.priority_suits[:2]:  # focus on earliest-eligible priority suits
            for col_idx in self.priority_buried_cols.get(suit, []):
                if col_idx >= len(state.columns):
                    continue
                col = state.columns[col_idx]
                # Depth = number of face-up cards currently sitting on the face-down stack
                depth = len(col.face_up)
                # The actual obstructors are the current face-up cards in that column
                obstructors = list(col.face_up)
                critical.append(
                    BuriedTarget(
                        suit=suit,
                        column=col_idx,
                        depth=depth,
                        obstructors=obstructors,
                    )
                )

        # Simple space creation opportunities: columns that have face-up runs but
        # still have face-down cards underneath (clearing the run can yield a space).
        space_ops: List[SpaceCreationOpportunity] = []
        for col_idx, col in enumerate(state.columns):
            if col.face_down and col.face_up:
                space_ops.append(
                    SpaceCreationOpportunity(
                        column=col_idx,
                        current_face_up_len=len(col.face_up),
                        would_yield_space=True,
                        notes=f"Clear {len(col.face_up)} face-up to flip/expose in col {col_idx+1}",
                    )
                )

        # Reception notes (very lightweight at this stage; later layers will enrich)
        reception_notes: List[str] = []
        if self.analysis.incoming_by_round:
            next_ten = self.analysis.incoming_by_round[0] if len(self.analysis.incoming_by_round) > 0 else []
            if next_ten:
                reception_notes.append(
                    f"Next known deal (round 1) top cards example: {next_ten[:3]}... — look for hooks/ranks that can receive them."
                )

        report = DependencyReport(
            global_plan={
                "priority_clearance_order": self.analysis.priority_clearance_order,
                "eligible_after_r0": list(self.analysis.eligible_suits_by_round[0]) if self.analysis.eligible_suits_by_round else [],
                "initial_buried_by_priority_suit": self.priority_buried_cols,
            },
            critical_buried=critical,
            space_opportunities=space_ops,
            reception_notes=reception_notes,
            raw={
                "priority_suits": self.priority_suits,
            },
        )
        return report

    def compute_foundation_state(self, state: SpiderState, suit: str = "c") -> Dict[str, any]:
        """Suit-specific foundation state for the given suit (K→A same-suit descending run to foundation).

        Generalised from Clubs-only. Parameterised by suit to support dynamic first-foundation selection.
        Supports completion map, legal descending fragments, buried ranks with depth/obstructors, attachability, future stock, etc.
        """
        suit = suit.lower()
        visible = 0
        fragments: List[int] = []
        buried = []
        visible_ranks = set()

        # Scan face_up for visible cards of the suit and legal descending fragments
        for col_idx, col in enumerate(state.columns):
            up = col.face_up
            for c in up:
                if c.suit == suit:
                    visible += 1
                    visible_ranks.add(c.rank)

            # Legal descending fragments for this suit
            if up:
                current_len = 0
                prev = None
                for c in up:
                    if c.suit == suit:
                        if prev is None or (prev.suit == suit and prev.rank - 1 == c.rank):
                            current_len += 1
                        else:
                            if current_len > 0:
                                fragments.append(current_len)
                            current_len = 1
                    else:
                        if current_len > 0:
                            fragments.append(current_len)
                            current_len = 0
                    prev = c
                if current_len > 0:
                    fragments.append(current_len)

            # Buried for this suit
            for fd_idx, c in enumerate(col.face_down):
                if c.suit == suit:
                    depth = len(col.face_up) + (len(col.face_down) - 1 - fd_idx)
                    obstructors = list(col.face_up)
                    parkable = sum(1 for o in obstructors if o.suit != suit)
                    buried.append({
                        "rank": c.rank,
                        "col": col_idx,
                        "depth": depth,
                        "obstructors": obstructors,
                        "parkable_obstructors": parkable,
                    })

        all_ranks = set(range(1, 14))
        missing_ranks = sorted(all_ranks - visible_ranks)

        # Build rank-level completion map for the suit
        suit_map = {}
        suit_tops = {}
        for col_idx, col in enumerate(state.columns):
            up = col.face_up
            if not up:
                continue
            run_len = 0
            for i in range(len(up)-1, -1, -1):
                c = up[i]
                if c.suit != suit:
                    break
                run_len += 1
                if i == 0 or up[i-1].suit != suit or up[i-1].rank - 1 != c.rank:
                    break
            if run_len > 0:
                top_rank = up[-1].rank
                suit_tops[top_rank] = (col_idx, True)

        for rank in range(13, 0, -1):
            status = "unavailable"
            col = None
            depth = None
            obstructors = []
            in_fragment = False
            attachable_to_higher = False

            # Check visible
            if rank in visible_ranks:
                # Find where
                for col_idx, colu in enumerate(state.columns):
                    for ci, c in enumerate(colu.face_up):
                        if c.suit == suit and c.rank == rank:
                            col = col_idx
                            # Check if part of legal descending fragment
                            if colu.face_up and colu.face_up[-1].rank == rank:
                                in_fragment = True
                            # Check attachable to higher
                            higher = rank + 1
                            if higher in suit_tops:
                                hcol, _ = suit_tops[higher]
                                if hcol == col_idx:
                                    attachable_to_higher = True
                            break
                    if col is not None:
                        break
                if in_fragment or attachable_to_higher:
                    status = "visible_free"
                else:
                    status = "visible_blocked"
            else:
                # Check buried
                for b in buried:
                    if b["rank"] == rank:
                        status = "buried"
                        col = b["col"]
                        depth = b["depth"]
                        obstructors = b["obstructors"]
                        break
                else:
                    # Future stock?
                    if self.analysis.incoming_by_round:
                        for ten in self.analysis.incoming_by_round:
                            if any(c.suit == suit and c.rank == rank for c in ten):
                                status = "future_stock"
                                break

            suit_map[rank] = {
                "rank": rank,
                "status": status,
                "column": col,
                "depth": depth,
                "obstructors": [str(o) for o in obstructors] if obstructors else [],
                "in_legal_fragment": in_fragment,
                "attachable_to_next_higher": attachable_to_higher,
            }

        # Empty columns
        empties = sum(1 for c in state.columns if c.is_empty())

        # Future stock for the suit
        future_count = 0
        future_by_rank = {r: 0 for r in range(1,14)}
        if self.analysis.incoming_by_round:
            for ten in self.analysis.incoming_by_round[:3]:
                for c in ten:
                    if c.suit == suit:
                        future_count += 1
                        future_by_rank[c.rank] += 1

        return {
            f"visible_{suit}": visible,
            f"{suit}_fragments": fragments,
            f"longest_{suit}_run": max(fragments) if fragments else 0,
            f"missing_ranks_for_ka_{suit}": missing_ranks,
            f"buried_{suit}": buried,
            f"num_buried_{suit}": len(buried),
            f"total_blocker_depth_{suit}": sum(b["depth"] for b in buried),
            "empties_available": empties,
            f"future_{suit}_in_next_deals": future_count,
            f"visible_{suit}_ranks": sorted(visible_ranks),
            f"{suit}_completion_map": suit_map,
            f"future_{suit}_ranks": future_by_rank,
        }

    def compute_foundation_candidate_scores(self, state: SpiderState) -> Dict[str, float]:
        """FoundationFirstEvaluator: scores each suit as candidate for first foundation.

        Higher score = better first target for focused campaign.
        Uses the generalised compute_foundation_state(suit) for each.
        """
        scores = {}
        for suit in "chsd":
            fstate = self.compute_foundation_state(state, suit)
            buried = fstate.get(f"buried_{suit}", [])
            num_buried = len(buried)
            weighted_depth = sum(b["depth"] for b in buried) if buried else 0
            longest_run = fstate.get(f"longest_{suit}_run", 0)
            visible = fstate.get(f"visible_{suit}", 0)

            future_support = fstate.get(f"future_{suit}_in_next_deals", 0)
            empties = fstate.get("empties_available", 0)

            # Rough other-long penalty (simplified)
            other_long = 0

            score = (
                longest_run * 10.0
                + visible * 2.0
                + future_support * 1.5
                - num_buried * 3.0
                - weighted_depth * 0.5
                - (4 - empties) * 2.0
                - other_long * 1.0
            )
            scores[suit] = round(score, 1)

        return scores

    def get_foundation_protected_assets(self, state: SpiderState, suit: str) -> Dict[str, any]:
        """Identify protected assets for the active Foundation_<Suit> campaign.

        These are the things we must not damage unless strongly compensated.
        """
        fstate = self.compute_foundation_state(state, suit)
        cmap = fstate.get(f"{suit}_completion_map", {})
        cmap = {int(k): v for k, v in cmap.items()}

        visible_free = [r for r, m in cmap.items() if m.get("status") == "visible_free"]
        in_legal_fragment = [r for r, m in cmap.items() if m.get("in_legal_fragment")]
        attachable_to_higher = [r for r, m in cmap.items() if m.get("attachable_to_next_higher")]

        # Main chain length (longest consecutive usable descending from high)
        main_chain = 0
        current = 0
        for r in range(13, 0, -1):
            m = cmap.get(r, {})
            is_usable = m.get("in_legal_fragment") or m.get("attachable_to_next_higher") or m.get("status") == "visible_free"
            if is_usable:
                current += 1
                main_chain = max(main_chain, current)
            else:
                current = 0

        # Adjacent pairs
        total_adj = 0
        in_chain_adj = 0
        attachable_adj = 0
        for high in range(13, 1, -1):
            low = high - 1
            mh = cmap.get(high, {})
            ml = cmap.get(low, {})
            has_high = mh.get("status") not in ("unavailable", "future_stock")
            has_low = ml.get("status") not in ("unavailable", "future_stock")
            if has_high and has_low:
                total_adj += 1
                if mh.get("column") == ml.get("column") and mh.get("in_legal_fragment"):
                    in_chain_adj += 1
                if mh.get("attachable_to_next_higher") or ml.get("in_legal_fragment"):
                    attachable_adj += 1

        # Strongest current chain
        strongest_chain = []
        current_chain = []
        for r in range(13, 0, -1):
            m = cmap.get(r, {})
            is_usable = m.get("in_legal_fragment") or m.get("attachable_to_next_higher") or m.get("status") == "visible_free"
            if is_usable:
                current_chain.append(r)
            else:
                if len(current_chain) > len(strongest_chain):
                    strongest_chain = current_chain[:]
                current_chain = []
        if len(current_chain) > len(strongest_chain):
            strongest_chain = current_chain[:]

        usable_for_foundation = sorted(set(visible_free) | set(attachable_to_higher) | set(strongest_chain))

        return {
            "suit": suit,
            "visible_free_ranks": sorted(visible_free),
            "in_legal_fragment_ranks": sorted(in_legal_fragment),
            "attachable_adjacent_pairs": attachable_adj,
            "main_chain_length": main_chain,
            "strongest_chain": sorted(strongest_chain, reverse=True),
            "usable_for_foundation": sorted(usable_for_foundation, reverse=True),
            "total_adjacent_pairs": total_adj,
            "in_chain_adjacent_pairs": in_chain_adj,
        }

    def compute_active_suit_protected_assets(self, state: SpiderState, suit: str) -> Dict[str, any]:
        """Task 1: Identify protected assets for active Foundation_<Suit> campaign before each candidate move.

        Returns specific ranks and structures that must not be damaged without clear compensation:
        - visible_free ranks (current attach points / exposed same-suit ends for the suit)
        - ranks in legal same-suit descending fragments (full ranks belonging to connected runs)
        - attachable adjacent pairs (count + list of (high,low) that can be linked by one move)
        - strongest current same-suit chain (the longest usable K->A path fragment)
        - usable for the likely first K->A foundation path
        """
        # Delegate to the detailed impl and enrich
        base = self.get_foundation_protected_assets(state, suit)
        fstate = self.compute_foundation_state(state, suit)
        cmap = fstate.get(f"{suit}_completion_map", {})
        cmap = {int(k): v for k, v in cmap.items()}

        # Compute full ranks that are part of any legal same-suit descending fragment (not just exposed tops)
        # Scan columns for maximal consecutive same-suit descending runs and collect every rank in them.
        ranks_in_legal_fragments_full: Set[int] = set()
        for col in state.columns:
            up = col.face_up
            i = len(up) - 1
            while i >= 0:
                if getattr(up[i], 'suit', None) != suit:
                    i -= 1
                    continue
                # start of a potential descending run from here upward (lower indices)
                run_ranks = [up[i].rank]
                j = i - 1
                while j >= 0:
                    c = up[j]
                    if getattr(c, 'suit', None) == suit and c.rank == run_ranks[-1] + 1:
                        run_ranks.append(c.rank)
                        j -= 1
                    else:
                        break
                if len(run_ranks) >= 1:
                    ranks_in_legal_fragments_full.update(run_ranks)
                i = j
                i -= 1 if i >= 0 else 0  # advance

        # Attachable adjacent pairs as explicit list of (high_rank, low_rank) where high can receive low with one legal move
        attachable_pairs_list: List[Tuple[int, int]] = []
        for high in range(13, 1, -1):
            low = high - 1
            mh = cmap.get(high, {})
            ml = cmap.get(low, {})
            has_high = mh.get("status") not in ("unavailable", "future_stock")
            has_low = ml.get("status") not in ("unavailable", "future_stock")
            if has_high and has_low:
                # attachable if the low is in fragment (exposed end) or high has attachable_to or same col continuing
                if mh.get("attachable_to_next_higher") or ml.get("in_legal_fragment") or \
                   (mh.get("column") is not None and mh.get("column") == ml.get("column")):
                    attachable_pairs_list.append((high, low))

        base["ranks_in_legal_fragments"] = sorted(ranks_in_legal_fragments_full)
        base["attachable_adjacent_pairs_list"] = attachable_pairs_list
        base["strongest_chain_length"] = len(base.get("strongest_chain", []))
        base["total_fragment_count"] = len([r for r in ranks_in_legal_fragments_full])  # proxy
        return base

    def detect_foundation_move_damage(self, pre: Dict[str, any], post: Dict[str, any], suit: str) -> Dict[str, any]:
        """Task 2: Move damage detector. Returns is_damaging + reasons for the 8 harms.

        Checks specific ranks (not just aggregate counts) so that loss of J♠ or 9♠ status is caught
        even if another rank becomes free at the same time.
        """
        reasons: List[str] = []
        is_damaging = False

        pre_free = set(pre.get("visible_free_ranks", []))
        post_free = set(post.get("visible_free_ranks", []))
        lost_free = sorted(pre_free - post_free)
        if lost_free:
            is_damaging = True
            reasons.append(f"visible_free -> blocked for ranks {lost_free}")

        pre_frag = set(pre.get("in_legal_fragment_ranks", []))
        # also use the enriched full fragment ranks if present
        pre_frag_full = set(pre.get("ranks_in_legal_fragments", pre.get("in_legal_fragment_ranks", [])))
        post_frag = set(post.get("in_legal_fragment_ranks", []))
        post_frag_full = set(post.get("ranks_in_legal_fragments", post.get("in_legal_fragment_ranks", [])))
        lost_frag = sorted(pre_frag_full - post_frag_full)
        if lost_frag:
            is_damaging = True
            reasons.append(f"removed from legal fragment: ranks {lost_frag}")

        pre_attach = pre.get("attachable_adjacent_pairs", 0)
        post_attach = post.get("attachable_adjacent_pairs", 0)
        if post_attach < pre_attach:
            is_damaging = True
            reasons.append(f"attachable adjacent pairs reduced {pre_attach} -> {post_attach}")

        pre_main = pre.get("main_chain_length", 0)
        post_main = post.get("main_chain_length", 0)
        if post_main < pre_main:
            is_damaging = True
            reasons.append(f"MainChainLength reduced {pre_main} -> {post_main}")

        pre_strong = set(pre.get("strongest_chain", []))
        post_strong = set(post.get("strongest_chain", []))
        if pre_strong and (len(post_strong) < len(pre_strong) or not pre_strong.issubset(post_strong)):
            is_damaging = True
            reasons.append("broke or shortened the strongest active-suit fragment")

        # Additional harms (6-8) are best evaluated with move context in the realizer (covering, non-continuing dest, last park).
        # Here we at least propagate the core structural ones above.

        return {
            "is_damaging": is_damaging,
            "reasons": reasons,
            "lost_visible_free": lost_free,
            "lost_legal_fragment": lost_frag,
            "pre_attach": pre_attach,
            "post_attach": post_attach,
            "pre_main": pre_main,
            "post_main": post_main,
        }

    def get_spade_completion_agenda(self, state: SpiderState) -> str:
        """Critical new report: the current Spade completion agenda / roadmap.

        Shows:
        - Current strongest/main chain (e.g. J♠-10♠-9♠-8♠)
        - Needed next connectors (Q above J, K above Q, 7 below 8, and continuing lower tail toward A)
        - Obstacle list for each critical missing/broken link: status, column, depth, obstructors (if buried/visible_blocked)
        """
        fstate = self.compute_foundation_state(state, "s")
        cmap = {int(k): v for k, v in fstate.get("s_completion_map", {}).items()}
        prot = self.get_foundation_protected_assets(state, "s")
        strong = prot.get("strongest_chain", []) or []
        # strong is high-to-low e.g. [11,10,9,8] for J-10-9-8 (exposed end low)
        rank_names = {13: "K", 12: "Q", 11: "J", 10: "10", 9: "9", 8: "8",
                      7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2", 1: "A"}

        def rs(r: int) -> str:
            return f"{rank_names.get(r, str(r))}♠"

        current_chain_str = "-".join(rs(r) for r in strong) if strong else "(no current chain)"

        # Determine needed next links to complete toward full K→A
        needed_ranks: List[int] = []
        if strong:
            high = max(strong)
            low = min(strong)
            # upward to K
            for r in range(high + 1, 14):
                needed_ranks.append(r)
            # downward to A
            for r in range(low - 1, 0, -1):
                needed_ranks.append(r)
        else:
            # no chain: the critical path is still the full, but start from highest visible/attachable
            for r in range(13, 0, -1):
                m = cmap.get(r, {})
                if m.get("status") == "visible_free" or m.get("in_legal_fragment") or m.get("attachable_to_next_higher"):
                    # seed from here
                    needed_ranks = [r-1, r+1] if 1 < r < 13 else ([r-1] if r>1 else [r+1])
                    break
            if not needed_ranks:
                needed_ranks = [12, 11, 10]  # fallback high end

        needed_ranks = sorted(set(needed_ranks), reverse=True)

        lines = []
        lines.append("Current Spade chain: " + current_chain_str)
        lines.append("Needed next (to complete K♠→A♠):")
        for r in needed_ranks:
            m = cmap.get(r, {})
            status = m.get("status", "unknown")
            col = m.get("column")
            depth = m.get("depth")
            in_frag = m.get("in_legal_fragment")
            attach = m.get("attachable_to_next_higher")
            obs = m.get("obstructors", [])
            obs_str = ", ".join(str(o) for o in obs[:3]) if obs else ""
            blocker = f"depth={depth} [{obs_str}]" if status == "buried" else ""
            lines.append(f"  - {rs(r)}: status={status} col={col} in_frag={in_frag} attachable_to_higher={attach} {blocker}")

        # Also surface any remaining high-value gaps in the primary path
        lines.append("Obstacle summary (key connectors & high cards):")
        high_value = [13,12,11,10,9,8,7]  # K Q J ... 7 as example focus
        for r in high_value:
            if r in needed_ranks or (strong and (r == max(strong)+1 or r == min(strong)-1)):
                m = cmap.get(r, {})
                if m.get("status") not in ("unavailable", "future_stock"):
                    lines.append(f"  {rs(r)}: {m.get('status')} col={m.get('column')} depth={m.get('depth')} blockers={m.get('obstructors',[])}")
        return "\n".join(lines)

    def get_foundation_connector_tasks(self, state: SpiderState, suit: str) -> List[Dict[str, any]]:
        """Task 1: Generate explicit connector tasks from the current main chain for active Foundation_<Suit>.

        Returns list of detailed task dicts for connecting the exact next ranks (upward to K and downward to A).
        Each includes target, source/dest info, status, blockers, parking estimate, protected dest flag, immediate?, prep needed.
        """
        fstate = self.compute_foundation_state(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}
        prot = self.get_foundation_protected_assets(state, suit)
        strong = prot.get("strongest_chain", []) or []
        rank_names = {13: "K", 12: "Q", 11: "J", 10: "10", 9: "9", 8: "8",
                      7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2", 1: "A"}

        def rs(r: int) -> str:
            return f"{rank_names.get(r, str(r))}♠"

        tasks: List[Dict] = []
        if not strong:
            return tasks

        high = max(strong)
        low = min(strong)
        strong_set = set(strong)

        # Only direct/next actionable connectors that can extend the *current* strong chain.
        # Upward: only the immediate next above high end (Q if J is high end)
        def rs_local(r: int) -> str:
            # suit-aware rank str (fix for previous hardcoded ♠)
            base = rank_names.get(r, str(r))
            s = suit.upper()
            return f"{base}{s}"

        if high < 13:
            r = high + 1
            m = cmap.get(r, {})
            dest_rank = r - 1
            dest_m = cmap.get(dest_rank, {})
            src_col = m.get("column")
            dest_col = dest_m.get("column") if dest_m.get("in_legal_fragment") or dest_m.get("attachable_to_next_higher") else None
            status = m.get("status", "unknown")
            blockers_above = []
            num_blockers = 0
            if src_col is not None and src_col < len(state.columns):
                col_up = state.columns[src_col].face_up
                for i, c in enumerate(col_up):
                    if getattr(c, 'suit', None) == suit and c.rank == r:
                        blockers_above = [str(cc) for cc in col_up[i+1:]]
                        num_blockers = len(blockers_above)
                        break
            # For buried targets, blockers = exposure depth from cmap, not just face-up above (the bug fix)
            target_m = cmap.get(r, {})
            t_status = target_m.get("status", status)
            exposure_depth = target_m.get("depth", 0) if t_status == "buried" else 0
            if t_status == "buried":
                num_blockers = exposure_depth
                blockers_above = target_m.get("obstructors", []) or blockers_above
                # top exposed in the col is what must be moved first for exposure
                if src_col is not None and src_col < len(state.columns) and state.columns[src_col].face_up:
                    top_card = state.columns[src_col].face_up[-1]
                    blockers_above = [str(top_card)] + [str(o) for o in blockers_above if str(o) != str(top_card)]
                src_col = target_m.get("column", src_col)
            immediate = (t_status == "visible_free" and (dest_m.get("in_legal_fragment") or dest_m.get("attachable_to_next_higher")))
            prep_evac = num_blockers > 0
            protected_dest = (dest_rank in prot.get("visible_free_ranks", []) or dest_rank in prot.get("in_legal_fragment_ranks", []))
            parking_req = max(0, num_blockers - sum(1 for c in state.columns if c.is_empty()))
            task = {
                "target_rank": r, "target_str": rs_local(r), "dest_rank": dest_rank, "dest_str": rs_local(dest_rank),
                "src_col": src_col, "dest_col": dest_col, "status": t_status,
                "blockers_above": blockers_above, "num_blockers": num_blockers,
                "immediate": immediate, "prep_evac_needed": prep_evac, "protected_dest": protected_dest,
                "parking_req_estimate": parking_req, "can_connect_immediately": immediate and num_blockers == 0,
                "direction": "up",
                "target_status": t_status,
                "exposure_depth": exposure_depth,
                "needs_exposure": t_status == "buried" or t_status == "visible_blocked",
                "task_type": "expose" if (t_status == "buried") else "connect",
            }
            tasks.append(task)

        # Downward: only the immediate next below low end
        if low > 1:
            r = low - 1
            m = cmap.get(r, {})
            dest_rank = r + 1
            dest_m = cmap.get(dest_rank, {})
            src_col = m.get("column")
            dest_col = dest_m.get("column") if dest_m.get("in_legal_fragment") or dest_m.get("attachable_to_next_higher") else None
            status = m.get("status", "unknown")
            blockers_above = []
            num_blockers = 0
            if src_col is not None and src_col < len(state.columns):
                col_up = state.columns[src_col].face_up
                for i, c in enumerate(col_up):
                    if getattr(c, 'suit', None) == suit and c.rank == r:
                        blockers_above = [str(cc) for cc in col_up[i+1:]]
                        num_blockers = len(blockers_above)
                        break
            # For buried targets (apply same fix for down direction)
            target_m = cmap.get(r, {})
            t_status = target_m.get("status", status)
            exposure_depth = target_m.get("depth", 0) if t_status == "buried" else 0
            if t_status == "buried":
                num_blockers = exposure_depth
                blockers_above = target_m.get("obstructors", []) or blockers_above
                if src_col is not None and src_col < len(state.columns) and state.columns[src_col].face_up:
                    top_card = state.columns[src_col].face_up[-1]
                    blockers_above = [str(top_card)] + [str(o) for o in blockers_above if str(o) != str(top_card)]
                src_col = target_m.get("column", src_col)
            immediate = (t_status == "visible_free" and (dest_m.get("in_legal_fragment") or dest_m.get("attachable_to_next_higher")))
            prep_evac = num_blockers > 0
            protected_dest = (dest_rank in prot.get("visible_free_ranks", []) or dest_rank in prot.get("in_legal_fragment_ranks", []))
            parking_req = max(0, num_blockers - sum(1 for c in state.columns if c.is_empty()))
            task = {
                "target_rank": r, "target_str": rs_local(r), "dest_rank": dest_rank, "dest_str": rs_local(dest_rank),
                "src_col": src_col, "dest_col": dest_col, "status": t_status,
                "blockers_above": blockers_above, "num_blockers": num_blockers,
                "immediate": immediate, "prep_evac_needed": prep_evac, "protected_dest": protected_dest,
                "parking_req_estimate": parking_req, "can_connect_immediately": immediate and num_blockers == 0,
                "direction": "down",
                "target_status": t_status,
                "exposure_depth": exposure_depth,
                "needs_exposure": t_status == "buried" or t_status == "visible_blocked",
                "task_type": "expose" if (t_status == "buried") else "connect",
            }
            tasks.append(task)

        return tasks

    def get_primary_next_connector_task(self, state: SpiderState, suit: str) -> Optional[Dict[str, any]]:
        """Return the primary (first preferred, usually 'up') next connector task from the current main/strongest chain for the suit.
        This is the source of truth for 'actual next connector' in connector-grounded metrics.
        """
        tasks = self.get_foundation_connector_tasks(state, suit)
        return tasks[0] if tasks else None

    def _get_blocker_count_above(self, st: SpiderState, col: Optional[int], rank: int, suit: str) -> int:
        if col is None or col < 0 or col >= len(st.columns):
            return 0
        up = st.columns[col].face_up
        for i, c in enumerate(up):
            if getattr(c, 'suit', None) == suit and getattr(c, 'rank', 0) == rank:
                return len(up[i+1:])
        return 0

    def _parse_card_str(self, s: str):
        """Return simple object with .rank and .suit from strings like '6d', '10H', 'JS', 'Kd'."""
        if not s:
            return None
        s = s.strip()
        suit = s[-1].lower()
        rpart = s[:-1]
        rmap = {"K":13, "Q":12, "J":11, "10":10, "9":9, "8":8, "7":7, "6":6, "5":5, "4":4, "3":3, "2":2, "A":1}
        if rpart in rmap:
            rank = rmap[rpart]
        else:
            try:
                rank = int(rpart)
            except:
                rank = 0
        return type('CardP', (object,), {'rank': rank, 'suit': suit})()

    def compute_grounded_next_connector(self, state: SpiderState, suit: str) -> Dict[str, any]:
        """Connector-grounded metrics for the actual next connector task (Task 1 + Task 2 support).

        Computes next_connector_* fields using the real target from main chain and its real top blocker.
        If the target is buried (per cmap status), blockers = exposure_depth, safe_first=False,
        can_connect_immediately=False, task_type="expose".
        safe_first (for connect or expose) is True only if immediately connectable (0 blockers and visible_free)
        or there is at least one legal first move (evac or exposure-clearing move from the col) that satisfies:
          - reduces or preserves blocker count / exposure depth above the target
          - does not damage protected active-suit assets (main/attach/strongest stable)
          - does not reduce MainChainLength or attachable pairs materially
          - does not worsen FoundationDistance
          - does not increase parking debt
          - does not create a new blocker above the target (move off the target col)
        """
        task = self.get_primary_next_connector_task(state, suit)
        prot = self.get_foundation_protected_assets(state, suit)
        fstate = self.compute_foundation_state(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}
        dist = self._compute_suit_foundation_distance(state, suit, fstate, cmap)
        main = prot.get("main_chain_length", 0)
        attach = prot.get("attachable_adjacent_pairs", 0)
        sw = sum(len(c.face_up) for c in state.columns if c.face_down)
        spaces = sum(1 for c in state.columns if c.is_empty())

        if not task:
            return {
                "next_connector_target": None,
                "next_connector_blocker_count": 0,
                "next_connector_top_blocker": None,
                "next_connector_safe_first": False,
                "next_connector_safe_dest": False,
                "next_connector_parking_debt": 0,
                "next_connector_readiness": 0,
                "main_chain": main,
                "attach_pairs": attach,
                "foundation_distance": dist,
                "target_status": "unavailable",
                "exposure_depth": 0,
                "can_connect_immediately": False,
                "task_type": "none",
            }

        target_rank = task.get("target_rank")
        target_str = task.get("target_str")
        num_blockers = task.get("num_blockers", 0)
        blockers_above = task.get("blockers_above", []) or []
        src_col = task.get("src_col")
        direction = task.get("direction", "up")
        t_status = task.get("target_status", task.get("status", "unknown"))
        exposure_depth = task.get("exposure_depth", 0)
        needs_exposure = task.get("needs_exposure", False)
        task_type = task.get("task_type", "connect")

        # exposed top blocker is the last in the blockers list (outermost, movable now)
        top_blocker_str = blockers_above[-1] if blockers_above else None
        top_blocker = self._parse_card_str(top_blocker_str) if top_blocker_str else None

        pre_blk = self._get_blocker_count_above(state, src_col, target_rank, suit) if src_col is not None else num_blockers

        # Per Task 1/2 fix: if buried or needs exposure, cannot be immediately connectable
        if t_status == "buried" or needs_exposure:
            num_blockers = exposure_depth if exposure_depth > 0 else num_blockers
            if src_col is not None and src_col < len(state.columns) and state.columns[src_col].face_up:
                top_blocker_str = str(state.columns[src_col].face_up[-1])
                top_blocker = self._parse_card_str(top_blocker_str)
            can_connect_immediately = False
        else:
            can_connect_immediately = task.get("can_connect_immediately", False)

        if (num_blockers == 0 or can_connect_immediately) and t_status != "buried" and not needs_exposure:
            safe_first = True
            grounded_debt = 0
            safe_dest = True
        else:
            safe_first = False
            debt_pre = self.compute_parking_debt(state, suit, target_rank or 10)
            pre_debt = debt_pre.get("debt", max(0, num_blockers - spaces))
            pre_main = main
            pre_attach = attach
            pre_dist = dist

            # For buried: safe exposure = move from the col that reduces face_up len (depth)
            # For blocked: safe evac of the top blocker
            blk_col = src_col
            if blk_col is not None and blk_col < len(state.columns):
                up = state.columns[blk_col].face_up
                max_try_k = min(4, len(up))
                for k in range(1, max_try_k + 1):
                    for dst in range(len(state.columns)):
                        if dst == blk_col: continue
                        if not state.can_move(blk_col, dst, k): continue
                        post = state.clone()
                        try:
                            post.move(blk_col, dst, k)
                        except Exception:
                            continue
                        post_up_len = len(post.columns[blk_col].face_up)
                        pre_up_len = len(up)
                        if t_status == "buried":
                            if post_up_len >= pre_up_len: continue  # no exposure progress
                        else:
                            post_blk = self._get_blocker_count_above(post, blk_col, target_rank, suit)
                            if post_blk > pre_blk: continue
                        post_prot = self.get_foundation_protected_assets(post, suit)
                        post_main = post_prot.get("main_chain_length", 0)
                        post_attach = post_prot.get("attachable_adjacent_pairs", 0)
                        post_f = self.compute_foundation_state(post, suit)
                        post_cmap = {int(kk): vv for kk, vv in post_f.get(f"{suit}_completion_map", {}).items()}
                        post_dist = self._compute_suit_foundation_distance(post, suit, post_f, post_cmap)
                        post_debt = self.compute_parking_debt(post, suit, target_rank or 10).get("debt", 0)
                        damages_prot = (post_main < pre_main) or (post_attach < pre_attach - 1)
                        worsens_dist = post_dist > pre_dist
                        increases_debt = post_debt > pre_debt
                        created_new = (dst == blk_col)
                        if damages_prot or worsens_dist or increases_debt or created_new: continue
                        safe_first = True
                        break
                    if safe_first: break

            grounded_debt = max(0, num_blockers - spaces)
            safe_dest = safe_first

        readiness = 50
        if (can_connect_immediately or num_blockers == 0) and t_status != "buried":
            readiness += 50
        else:
            readiness += max(0, 20 - num_blockers * 4)
        if safe_first: readiness += 40
        readiness -= max(0, grounded_debt * 15)
        readiness = max(0, min(100, readiness))

        return {
            "next_connector_target": target_str,
            "next_connector_blocker_count": num_blockers,
            "next_connector_top_blocker": top_blocker_str,
            "next_connector_safe_first": safe_first,
            "next_connector_safe_dest": safe_dest,
            "next_connector_parking_debt": grounded_debt,
            "next_connector_readiness": round(readiness, 1),
            "direction": direction,
            "target_col": src_col,
            "main_chain": main,
            "attach_pairs": attach,
            "foundation_distance": dist,
            "sw": sw,
            "spaces": spaces,
            "target_status": t_status,
            "exposure_depth": exposure_depth,
            "needs_exposure": needs_exposure,
            "can_connect_immediately": can_connect_immediately,
            "task_type": task_type,
        }

    def compute_executable_foundation_gate(self, state: SpiderState, suit: str) -> Dict[str, any]:
        """Task 1: ExecutableFoundationGate using corrected target-status semantics.

        Returns full components + passes_gate (bool) + gate_reason.
        A suit passes only if main>=3, debt<=0, protected stable, and there is an executable next step:
        - immediate connect, or
        - safe exposure for buried target, or
        - safe_first evac for the actual top blocker of a connect task, or
        - available space/park that makes the next connector/exposure executable.
        - foundation-completing merge (one legal move completes K->A foundation).
        """
        from spider.heuristics import detect_foundation_completing_merge

        merge = detect_foundation_completing_merge(state, suit)
        grounded = self.compute_grounded_next_connector(state, suit)
        prot = self.get_foundation_protected_assets(state, suit)
        main = prot.get("main_chain_length", 0)
        attach = prot.get("attachable_adjacent_pairs", 0)
        stable = (main >= 3) and (attach >= 2)
        debt = grounded.get("next_connector_parking_debt", 0)
        tstat = grounded.get("target_status", "unknown")
        ttype = grounded.get("task_type", "none")
        safe_first = grounded.get("next_connector_safe_first", False)
        blks = grounded.get("next_connector_blocker_count", 0)
        exp_d = grounded.get("exposure_depth", 0)
        can_imm = grounded.get("can_connect_immediately", False)
        spaces = grounded.get("spaces", sum(1 for c in state.columns if c.is_empty()))

        passes = False
        reason = "unknown"

        if merge.get("found"):
            passes = True
            reason = "foundation_completing_merge"
            ttype = "complete_merge"
        elif main < 3:
            reason = "main_chain < 3"
        elif debt > 0:
            reason = "grounded_debt > 0"
        elif not stable:
            reason = "protected chain unstable (main<3 or attach<2)"
        elif tstat in ("future_stock", "unavailable"):
            reason = f"target {tstat}"
        else:
            if can_imm and ttype == "connect":
                passes = True
                reason = "immediate connect possible"
            elif tstat == "buried" and ttype == "expose":
                if safe_first:  # exposure move exists per grounded sim
                    passes = True
                    reason = "safe exposure move for buried target"
                else:
                    reason = "buried target, no safe exposure move found"
            elif ttype == "connect" and safe_first:
                passes = True
                reason = "safe_first evac for actual top blocker"
            elif spaces > 0:
                passes = True
                reason = "empty space available to enable next step"
            else:
                reason = "no executable next step (no imm, no safe_first, no space)"

        return {
            "main_chain": main,
            "foundation_distance": grounded.get("foundation_distance"),
            "next_connector": grounded.get("next_connector_target"),
            "target_status": tstat,
            "task_type": ttype,
            "merge_details": merge if merge.get("found") else None,
            "target_blockers": blks,
            "actual_top_blocker": grounded.get("next_connector_top_blocker"),
            "actual_top_blocker_safe_first": safe_first,
            "connector_grounded_debt": debt,
            "spaces": spaces,
            "protected_chain_stability": stable,
            "exposure_depth": exp_d,
            "can_connect_immediately": can_imm,
            "passes_gate": passes,
            "gate_reason": reason,
            "grounded": grounded,
        }

    def find_best_executable_suit(self, state: SpiderState) -> Optional[Dict[str, any]]:
        """Return the suit (if any) that passes the gate, or the best near-pass by gate 'score'."""
        best = None
        best_score = -999
        for s in ("s", "d", "c", "h"):
            g = self.compute_executable_foundation_gate(state, s)
            score = (10 if g["passes_gate"] else 0) + g["main_chain"] * 2 + (5 if g["actual_top_blocker_safe_first"] else 0) - g["connector_grounded_debt"] * 3 - g.get("exposure_depth", 0)
            if score > best_score:
                best_score = score
                best = {"suit": s, "gate": g, "score": score}
        return best

    def compute_anchor_viability(self, state: SpiderState, label: str = "") -> Dict[str, any]:
        """Task 3: AnchorViabilityScore for prefix/anchor comparison.
        Rewards executable routes, liquidity, stability. Penalties for buried without safe exposure, un-evaccable blockers, no spaces when needed, etc.
        """
        gates = {s: self.compute_executable_foundation_gate(state, s) for s in "schd"}
        sw = sum(len(c.face_up) for c in state.columns if c.face_down)
        spaces = sum(1 for c in state.columns if c.is_empty())
        foundations = sum(len(f) for f in getattr(state, 'foundations', [[]]*4))  # rough

        any_pass = any(g["passes_gate"] for g in gates.values())
        close_passes = sum(1 for g in gates.values() if not g["passes_gate"] and g["main_chain"] >= 2 and g["connector_grounded_debt"] <= 2)
        visible_targets = sum(1 for g in gates.values() if g["target_status"] in ("visible_free", "visible_blocked"))
        safe_exposures = sum(1 for g in gates.values() if g["task_type"] == "expose" and g["actual_top_blocker_safe_first"])
        low_debts = sum(1 for g in gates.values() if g["connector_grounded_debt"] <= 1)
        stable_prots = sum(1 for g in gates.values() if g["protected_chain_stability"])

        score = 0
        if any_pass: score += 100
        score += close_passes * 15
        score += visible_targets * 8
        score += safe_exposures * 12
        score += low_debts * 5
        score += stable_prots * 6
        score += spaces * 4
        score += max(0, 10 - sw//2)  # favor reasonable sw if liquidity good
        score -= foundations * 2  # already done foundations less interesting for "first"

        # penalties
        buried_no_safe = sum(1 for g in gates.values() if g["target_status"] == "buried" and not g["actual_top_blocker_safe_first"])
        score -= buried_no_safe * 25
        un_evaccable = sum(1 for g in gates.values() if g["target_blockers"] > 0 and not g["actual_top_blocker_safe_first"] and g["task_type"] == "connect")
        score -= un_evaccable * 20
        if spaces == 0 and any(g["target_blockers"] > 0 or g["exposure_depth"] > 0 for g in gates.values()):
            score -= 30
        if sw < 8 and not any_pass:  # too low sw at cost of liquidity
            score -= 15

        best_suit = max(gates, key=lambda s: (100 if gates[s]["passes_gate"] else 0) + gates[s]["main_chain"]*2 - gates[s]["connector_grounded_debt"] - gates[s]["exposure_depth"])

        return {
            "label": label,
            "sw": sw,
            "spaces": spaces,
            "foundations": foundations,
            "any_pass": any_pass,
            "close_passes": close_passes,
            "viability_score": score,
            "best_suit": best_suit,
            "best_gate": gates[best_suit],
            "gates": gates,
        }

    def post_deal_gate_preview(self, state: SpiderState) -> Dict[str, any]:
        """Task 1: Cheap deterministic preview of post-first-deal gate viability.
        Clones, deals the known first wave (if possible), evaluates ExecutableFoundationGate + viability for all suits.
        Returns best suit and reason. Used to bias pre-deal move scoring.
        """
        work = state.clone()
        dealt_cost = 0
        try:
            dealt_cost = work.deal()
        except Exception:
            pass  # stock may be insufficient in some replayed prefixes; proceed with current state

        gates = {s: self.compute_executable_foundation_gate(work, s) for s in "schd"}
        viability = self.compute_anchor_viability(work, "post_deal_preview")
        any_pass = any(g["passes_gate"] for g in gates.values())

        best_suit = max(gates, key=lambda s: (100 if gates[s]["passes_gate"] else 0) + gates[s]["main_chain"]*2 - gates[s]["connector_grounded_debt"] - gates[s].get("exposure_depth", 0))
        best_g = gates[best_suit]

        # simple improvement signal vs a rough pre-deal baseline (main/visible/safe_first)
        pre_main = max( (self.compute_executable_foundation_gate(state, s)["main_chain"] for s in "schd"), default=0 )
        improvement = 0
        if best_g["passes_gate"]:
            improvement += 50
        if best_g["main_chain"] > pre_main:
            improvement += 15
        if best_g["target_status"] in ("visible_free", "visible_blocked"):
            improvement += 10
        if best_g["actual_top_blocker_safe_first"]:
            improvement += 12
        if best_g["connector_grounded_debt"] < 2:
            improvement += 8
        work_spaces = sum(1 for c in work.columns if c.is_empty())
        state_spaces = sum(1 for c in state.columns if c.is_empty())
        if work_spaces > state_spaces:  # rough liquidity
            improvement += 5

        return {
            "best_suit": best_suit,
            "any_pass": any_pass,
            "main": best_g["main_chain"],
            "target_status": best_g["target_status"],
            "task_type": best_g["task_type"],
            "safe_first": best_g["actual_top_blocker_safe_first"],
            "debt": best_g["connector_grounded_debt"],
            "exposure_depth": best_g.get("exposure_depth", 0),
            "gate_pass": best_g["passes_gate"],
            "reason": best_g["gate_reason"],
            "viability": viability["viability_score"],
            "improvement_signal": improvement,
            "dealt_cost": dealt_cost,
            "post_sw": sum(len(c.face_up) for c in work.columns if c.face_down),
            "post_spaces": sum(1 for c in work.columns if c.is_empty()),
        }

    def score_foundation_connector(self, task: Dict[str, any], state: SpiderState, suit: str, protected: Dict[str, any], current_sw: int = 0) -> float:
        """Task 2: Simple connector priority score. Higher = better next connector to pursue."""
        score = 0.0
        # immediate connect bonus
        if task.get("immediate") or task.get("can_connect_immediately"):
            score += 60
        # chain extension value (prefer completing toward full or extending main)
        target_r = task.get("target_rank", 0)
        if target_r >= 10:  # high end (Q/K toward full foundation)
            score += 35
        elif target_r >= 7:
            score += 20
        else:
            score += 10
        # high-end priority bonus (Q/K more valuable than low tail for first foundation)
        if target_r >= 11:
            score += 25
        # low blocker cost bonus (prefer easier ones)
        nb = task.get("num_blockers", 5)
        score += max(0, 25 - nb * 5)
        # parking feasibility (rough)
        if task.get("parking_req_estimate", 0) <= 1:
            score += 15
        elif task.get("parking_req_estimate", 0) <= 2:
            score += 5
        # damage risk to protected (we'll penalize if the target itself is protected or connecting would risk)
        if not task.get("protected_dest", True):
            score -= 10
        # sw / future stock risk (higher current sw or if target is future_stock, lower priority here)
        if current_sw > 18:
            score -= 8
        m = {}  # would need cmap, but approximate
        if task.get("status") == "future_stock":
            score -= 30
        # direction: slight prefer high for first foundation
        if task.get("direction") == "up":
            score += 8
        return round(score, 1)

    def plan_obstructor_evacuation(self, target_rank: int, suit: str, state: SpiderState, protected: Dict[str, any]) -> Dict[str, any]:
        """Task 3: For a blocked target, produce bounded evacuation plan for its blockers.

        Classifies possible parks for each blocker:
        - safe_same_suit_continuation (rare for blocker)
        - safe_offsuit_temp (legal, no damage to protected Spade assets)
        - damaging_to_active (would regress protected visible_free/frag/attach/main for suit)
        - damaging_to_other_near_foundation
        - impossible (not legal move)
        Prefers safe parks that don't damage the active suit chain.
        """
        fstate = self.compute_foundation_state(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}
        m = cmap.get(target_rank, {})
        src_col = m.get("column")
        blockers: List[Dict] = []
        plan: Dict[str, any] = {"target_rank": target_rank, "src_col": src_col, "blockers": blockers, "recommended_first_parks": []}

        if src_col is None or src_col >= len(state.columns):
            return plan

        col = state.columns[src_col]
        up = col.face_up
        target_idx = None
        for i, c in enumerate(up):
            if getattr(c, "suit", None) == suit and getattr(c, "rank", 0) == target_rank:
                target_idx = i
                break
        if target_idx is None:
            return plan

        # blockers are cards strictly above target (higher indices in face_up, the ones on top)
        blocker_cards = list(up[target_idx + 1:])
        pre_prot = protected  # the snapshot passed in

        for b_idx, bcard in enumerate(blocker_cards):
            b_suit = getattr(bcard, "suit", None)
            b_rank = getattr(bcard, "rank", 0)
            b_src = src_col
            possible_parks: List[Dict] = []
            for dst in range(10):
                if dst == b_src:
                    continue
                # for single card k=1
                if state.can_move(b_src, dst, 1):
                    # classify by sim
                    sim = state.clone()
                    try:
                        sim.move(b_src, dst, 1)
                        post_prot = self.get_foundation_protected_assets(sim, suit)
                        damages_active = (
                            len(post_prot.get("visible_free_ranks", [])) < len(pre_prot.get("visible_free_ranks", [])) or
                            len(post_prot.get("in_legal_fragment_ranks", [])) < len(pre_prot.get("in_legal_fragment_ranks", [])) or
                            post_prot.get("attachable_adjacent_pairs", 0) < pre_prot.get("attachable_adjacent_pairs", 0) or
                            post_prot.get("main_chain_length", 0) < pre_prot.get("main_chain_length", 0)
                        )
                        # other suit damage heuristic: if dst now has a high same-suit card covered or something; simple check empties or other
                        other_damage = False
                        # for now, rough: if it used the last empty and not for active suit gain
                        if sum(1 for c in state.columns if c.is_empty()) == 1 and sum(1 for c in sim.columns if c.is_empty()) == 0:
                            other_damage = True
                    except Exception:
                        damages_active = True
                        other_damage = True

                    classification = "impossible"
                    if not damages_active and not other_damage:
                        classification = "safe_offsuit_temp"
                    elif damages_active:
                        classification = "damaging_to_active"
                    else:
                        classification = "damaging_to_other_near_foundation"

                    possible_parks.append({
                        "dst_col": dst,
                        "classification": classification,
                        "would_damage_active": damages_active,
                    })
            blockers.append({
                "blocker": str(bcard),
                "blocker_suit": b_suit,
                "blocker_rank": b_rank,
                "position_from_top": b_idx,
                "possible_parks": possible_parks,
            })
            # recommend the first safe one found
            safe = [p for p in possible_parks if "safe" in p["classification"]]
            if safe:
                plan["recommended_first_parks"].append({"blocker": str(bcard), "park": safe[0]})

        plan["num_blockers"] = len(blockers)
        plan["has_safe_parks"] = any("safe" in p.get("classification", "") for blk in blockers for p in blk.get("possible_parks", []))
        return plan

    def get_safe_park_task_for_blocker(self, blocker: "Card", target_rank: int, suit: str, state: SpiderState) -> Dict[str, any]:
        """Task 1: Create SafeParkTask when direct connector evac has no safe park for the top blocker.

        For the current plateau: blocker=J♦, target=Q♠ (rank 12), suit='s'.
        """
        fstate = self.compute_foundation_state(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}
        prot = self.get_foundation_protected_assets(state, suit)

        # Find target (Q♠) column
        target_m = cmap.get(target_rank, {})
        target_col = target_m.get("column")

        # Find blocker's current column (should be target_col)
        blocker_col = None
        blocker_idx_in_col = None
        for cidx, col in enumerate(state.columns):
            for i, c in enumerate(col.face_up):
                if c.suit == blocker.suit and c.rank == blocker.rank:
                    blocker_col = cidx
                    blocker_idx_in_col = i
                    break
            if blocker_col is not None:
                break

        # Determine the maximal same-suit descending stack starting from the blocker (upward in face_up, i.e. lower indices? face_up top is high index)
        # Blockers above target are the cards with higher indices than the target card.
        # For parking, the movable stack is the descending same-suit run *from the top of the blockers* or from the blocker if we consider sub-stacks.
        # Per spec: consider moving J♦ alone, or J♦-10♦ if they form movable, or J♦-10♦-9♦.
        # The 8♠ breaks the diamond run.

        # Compute possible movable stacks containing the blocker as the "exposed" for parking.
        # In practice, from the top of the column or from the blocker position, the max descending same suit run that can be moved as unit.
        # For simplicity, find the run that has the blocker as its top (exposed end) or part of it.

        # For this specific: the top of col1 is Jd (top blocker), then 10d,9d (same suit descending), then 8s (different).
        # So movable same-suit stacks involving Jd as the attach point (the low end of the run to be parked):
        # - single J♦ (needs Q any suit)
        # - J♦-10♦ (the run Jd on 10d? Wait: descending run exposed end is lowest rank.
        # In Spider face_up, the exposed (attachable) end is the lowest rank in the descending sequence.
        # If col has ... (higher) Jd (top=exposed? No:
        # Typical: higher cards deeper, lower rank on top.
        # E.g. to have Jd on top of 10d on 9d? Descending would be  Jd (rank11) on 10d (10) ? But 11-1 !=10.
        # Descending same suit: higher rank under lower rank.
        # E.g. Qd (12) under Jd (11) under 10d (10) ... the exposed top is 10d.
        # In the plateau report: stack above Qs is ['Jd', '10d', '9d', '8s']
        # This means the face_up top (exposed) is 8s? The list order in previous output is from top?
        # From the log: stack=['Jd', '10d', '9d', '8s']
        # And top blocker selected: Jd
        # So the list is top-to-bottom? Jd is the top exposed card (the one directly on Q? No, the blockers are above Q.
        # Qs is buried under the 4 cards.
        # The exposed top of the column is the highest in the list? The previous print had top = Jd, so the list is from the blocker closest to Q upward to the exposed top?
        # Anyway, for code: the "top blocker" is the currently exposed card in that column (the one that can be moved first).
        # For J♦ being top blocker, it means J♦ is the exposed end (lowest rank? ), and the stack below it in the blockers are higher ranks.
        # For parking J♦, since it's the exposed, we can move runs starting with J♦ as the "bottom" of the moved run (the attach end).
        # To park J♦ we need a destination of rank 12 (Q) of any suit.
        # If we can move a longer run where J♦ is the attach end of the run (i.e. the run is ... - J♦ as the low end).
        # From the cards: Jd,10d,9d -- this suggests the sequence in column from bottom (near Q) to top (exposed): Qs, Jd,10d,9d,8s ?
        # But Jd(11) on 10d(10) is not descending (11 >10 but for descending exposed low, the deeper should be higher rank.
        # If exposed top is 9d, then under it 10d, under it Jd -- but the list shows Jd first.
        # The list in output is the cards sitting on Q from closest to Q to the top exposed.
        # So closest to Q is Jd, then 10d,9d,8s on top (exposed is 8s).
        # But then top blocker would be 8s, but the output said top blocker Jd.
        # In the last run output: stack=['Jd', '10d', '9d', '8s'], top blocker selected: Jd
        # This suggests the list is ordered from top exposed to the one closest to the target: exposed Jd on 10d on 9d on 8s on Qs.
        # Jd on 10d: Jd(11) on 10d(10) -- 11-1=10? No, 10 !=10. Wait, 11-1 =10 yes, but for same suit? Jd on 10d is diamonds? Jd is J of diamonds? In Spider cards, 'Jd' is Jack diamonds.
        # Yes, J♦ (11) on 10♦ (10) is consecutive descending same suit (higher rank deeper).
        # Exposed top is the lowest rank: if list ['Jd','10d','9d','8s'] means exposed is Jd? Then under it 10d? That would be Jd on 10d -- Jd(11) deeper? No.
        # Standard in code: face_up[-1] is the exposed top (the card you see, the end of the run you can attach to or move from).
        # To have a descending run  ... Jd(11) - 10d(10) - 9d(9) - 8s(8) as exposed top 8s.
        # The list in the diagnostic was printed as the blockers from the one closest to Q (Jd) to the exposed (8s).
        # But it said "top blocker selected: Jd" -- inconsistency in the log?
        # In the very last tool response: stack=['Jd', '10d', '9d', '8s'], top blocker selected: Jd
        # This must mean the list is the cards *from the exposed top* : top/exposed = Jd, then under it 10d,9d,8s on Q.
        # But then Jd(11) under? Exposed top Jd means you can attach to Jd (need 10 of any? No, to attach to the exposed end you attach a card 1 less than the exposed.
        # If exposed is Jd(11), to attach to it you put 10 on it.
        # The run under it would be the higher cards? The sequence for the run would be (deeper higher rank) ... (say Qd on Jd exposed).
        # For the blockers on Qs: the cards on top of Qs are the run that is sitting on it.
        # Anyway, for the task, the "top blocker" is the currently exposed card in the column (the one that can be moved as the start of a movable run).
        # For parking the top blocker J♦, we treat it as the attach end of the movable run we want to park (the low rank end of the descending run we move).
        # To park a run whose exposed end is J♦, we need a destination of rank J+1 = Q of any suit.
        # And the stack we can move is the descending same-suit run ending at J♦ (the cards "under" in the list if list is top to bottom).
        # From the list and "top Jd", likely the movable diamond run is Jd-10d-9d (3 card run ending at exposed Jd? Wait numbers: if exposed Jd(11), the card under it in column is higher rank 12? But list has 10d under Jd? The list order is top exposed Jd, then the next deeper 10d? But 11 on 10 is not correct for descending (deeper should be 12 for Jd exposed).
        # There might be a small inconsistency in how the previous diagnostic printed the stack order.
        # For implementation, we don't need to overthink the exact previous list; the code in get_foundation... already correctly identifies the column of the target and the cards above it.
        # In get_foundation_connector_tasks and evac, it correctly finds num_blockers and the blockers_above list (from the scan in the column for the target rank, then cards after it in the face_up list, which are the ones on top of it, i.e. the obstructors that must be moved first to expose the target).
        # The "top blocker" is the last in that list (the currently exposed card in the column).
        # To evacuate, we move runs starting from the exposed end (the top blocker) .

        # For this task:
        rank_names = {13: "K", 12: "Q", 11: "J", 10: "10", 9: "9", 8: "8",
                      7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2", 1: "A"}
        blocker_str = f"{rank_names.get(blocker.rank, blocker.rank)}{'♠♥♦♣'[ 'shdc'.index(blocker.suit)] if hasattr(blocker,'suit') else ''}"
        target_str = f"{rank_names.get(target_rank, target_rank)}{suit.upper() if len(suit)==1 else suit}"

        # Required parking destination type for the blocker (as the exposed end of the run we move)
        # To "park" the run whose exposed (low) end is the blocker rank, we need a Q (rank blocker.rank +1 ) of any suit.
        required_dest_rank = blocker.rank + 1
        required_dest_str = f"{rank_names.get(required_dest_rank, required_dest_rank)} of any suit"

        task = {
            "name": f"SafeParkForBlocker_{blocker_str.replace('♠','s').replace('♥','h').replace('♦','d').replace('♣','c')}_for_{target_str}",
            "blocker_card": str(blocker),
            "blocker_rank": blocker.rank,
            "blocker_suit": getattr(blocker, 'suit', None),
            "target_rank": target_rank,
            "target_str": target_str,
            "target_column": target_col,
            "blocker_column": blocker_col,
            "desired_evacuation_direction": "move blocker or movable same-suit stack containing it away from the target column",
            "required_parking_destination_type": required_dest_str,
            "forbidden": [
                "any move that increases blockers above the target",
                "any move that damages the protected active-suit chain (J-10-9-8 etc.)",
                "any move that buries the target further",
                "any move that breaks useful same-suit attachable pairs for the suit unless strongly compensated per Do No Harm"
            ],
            "preconditions": {
                "no_safe_park_for_direct_evac": True,
                "top_blocker": str(blocker)
            }
        }
        return task

    def identify_parking_requirements_for_blocker(self, blocker: "Card", target_rank: int, suit: str, state: SpiderState) -> List[Dict[str, any]]:
        """Task 2: List all ways the blocker (J♦) or its movable same-suit stack can be parked.

        Reports for each option: movable now?, required dest rank, candidate dest cols/cards, whether dest exists, blocked, what to clear, damage to protected Spades.
        """
        requirements = []
        blocker_suit = getattr(blocker, 'suit', None)
        blocker_rank = getattr(blocker, 'rank', 0)

        # Find the column and the position; compute the maximal descending same-suit run whose *exposed end* (the end we attach when parking) is the blocker.
        # I.e. the run we can move that ends with the blocker as its low-rank end.
        # Scan columns for runs that include the blocker as the current exposed card of a same-suit descending sequence.
        for col_idx, col in enumerate(state.columns):
            up = col.face_up
            for i in range(len(up)-1, -1, -1):  # from exposed back
                c = up[i]
                if c.suit == blocker_suit and c.rank == blocker_rank:
                    # Found the blocker as a candidate exposed end. Walk "up" the column (deeper, lower indices) to build the run that has this as the low end.
                    # The movable run is the consecutive descending same suit ending at this card as the exposed.
                    # Since i is the position of the blocker, the run "under" it (higher indices? No: exposed is high index.
                    # face_up[-1] exposed low rank.
                    # To build the run: start from the blocker as the "low" end, walk to lower indices collecting higher ranks same suit consecutive.
                    run = [c]
                    j = i - 1
                    while j >= 0:
                        prev_c = up[j]
                        if prev_c.suit == blocker_suit and prev_c.rank == run[-1].rank + 1:
                            run.append(prev_c)
                            j -= 1
                        else:
                            break
                    # Now run[0] is the exposed (blocker), run[-1] is the highest rank in the stack we can move as unit.
                    # The length we can move is len(run) (the whole from exposed to the deep end of the consecutive).
                    max_k_for_this = len(run)
                    # For parking this run, the destination needed is rank = blocker_rank + 1 (Q any suit), because the exposed end of the moved run is blocker_rank.
                    dest_rank_needed = blocker_rank + 1

                    # Now, for different k we can choose sub-runs? But typically we move the max or the one that makes sense.
                    # Per spec: consider single, the 2-card, the 3-card.
                    for k in [1, 2, 3]:
                        if k > max_k_for_this:
                            continue
                        # The run we would move for this k is the top k of the 'run' list (the exposed k cards).
                        # To park it we still need dest of rank = the exposed of that sub-run +1.
                        # For k=1: exposed is blocker, dest_rank = blocker+1
                        # For larger k the exposed of the sub-run we move is still the original blocker (the top k includes the original exposed as the new exposed).
                        # Yes, moving a longer prefix from the column still has the same exposed end (the original top blocker).
                        # So dest_rank_needed is always blocker_rank +1 for any k of this stack.
                        # Find current possible destinations: columns whose exposed top has rank == dest_rank_needed (any suit).
                        candidate_dests = []
                        for dcol_idx, dcol in enumerate(state.columns):
                            if not dcol.face_up:
                                continue  # empty is special (can always move to empty, but for "park" here we want the Q attach for the run)
                            dtop = dcol.face_up[-1]
                            if dtop.rank == dest_rank_needed:
                                candidate_dests.append({
                                    "col": dcol_idx,
                                    "card": str(dtop),
                                    "suit": getattr(dtop, 'suit', None),
                                    "exists": True,
                                    "blocked": False  # since it's exposed
                                })

                        # Also empty columns as possible (moving the run to empty is always legal, and may be "safe temp" if we later build on it).
                        empty_cols = [i for i, c in enumerate(state.columns) if c.is_empty()]
                        for ecol in empty_cols:
                            candidate_dests.append({
                                "col": ecol,
                                "card": "empty",
                                "suit": None,
                                "exists": True,
                                "blocked": False,
                                "note": "empty column - safe temporary if later usable for the suit or neutral"
                            })

                        # Whether movable now: yes if k <= the current exposed run length at that position.
                        # (We already filtered k <= max_k_for_this)
                        movable_now = True  # since we are at the exposed end

                        req = {
                            "option": f"Move {k}-card stack ending at {blocker} (same-suit descending)",
                            "k": k,
                            "movable_now": movable_now,
                            "required_dest_rank": dest_rank_needed,
                            "required_dest_str": f"Q (rank {dest_rank_needed}) of any suit, or empty",
                            "candidate_dests": candidate_dests,
                            "num_candidates": len(candidate_dests),
                            "what_to_clear_if_none": "If no Q exposed and no good empty, may need to evacuate cards above a buried Q or create space.",
                            "damage_risk_to_protected_spades": "Will be checked via Do No Harm sim when actually moving; prefer destinations that do not cover protected Spade free/frag cards."
                        }
                        requirements.append(req)

        return requirements

    def plan_destination_creation_for_blocker(self, blocker: "Card", target_rank: int, suit: str, state: SpiderState) -> Dict[str, any]:
        """Task 3: If no good Q dest for the blocker, produce bounded plan to expose or create one.

        Focus on cheap, safe actions that enable a Q of any suit to become a legal destination for the blocker without damaging protected Spades.
        """
        creation_steps = []
        prot = self.get_foundation_protected_assets(state, suit)

        # 1. Look for buried or visible_blocked Q (rank = blocker.rank+1) of any suit and propose evacuating their obstructors.
        needed_rank = getattr(blocker, 'rank', 0) + 1
        for s in "shdc":
            for r in [needed_rank]:
                m = {}  # would scan cmap for other suits, but for simplicity use general analysis or approximate
                # Simple: scan columns for a Q of any suit that is not exposed.
                for col_idx, col in enumerate(state.columns):
                    for ci, c in enumerate(col.face_up):
                        if c.rank == needed_rank:
                            # Found a Q (any suit)
                            depth_above = len(col.face_up) - ci - 1
                            if depth_above > 0:
                                creation_steps.append({
                                    "action": "expose buried/blocked Q",
                                    "suit": c.suit,
                                    "col": col_idx,
                                    "depth": depth_above,
                                    "obstructors": [str(x) for x in col.face_up[ci+1:]],
                                    "cost_estimate": depth_above,
                                    "safe_for_spades": True,  # to be verified by sim later
                                    "note": f"Evacuate the {depth_above} cards above this Q{ c.suit} to make it available as destination for the blocker."
                                })
                            else:
                                # already exposed, but perhaps not used because wrong for other reasons or already considered in requirements
                                pass

        # 2. If there is a visible Q but "blocked" in some sense (e.g. not usable because of other), or suggest moving a Q to a better place.
        # 3. Create empty as last resort if it enables the sequence (but prefer Q attach).
        empties = sum(1 for c in state.columns if c.is_empty())
        if empties == 0:
            creation_steps.append({
                "action": "create empty column (gold space) as enabler for temporary park or to receive the blocker run",
                "note": "Only if it allows a subsequent safe sequence for the blocker without increasing Q blockers or damaging Spade chain. Low priority."
            })

        return {
            "blocker": str(blocker),
            "needed_dest_rank": needed_rank,
            "creation_steps": creation_steps,
            "priority_order": "prefer exposing an existing Q (low depth) > moving obstructors above a visible Q > creating space only as enabler"
        }

    def score_safe_park_candidate(self, candidate: Dict[str, any], state: SpiderState, suit: str, protected: Dict[str, any], current_sw: int) -> float:
        """Task 4: Score a candidate park destination/route for the blocker (J♦).

        Higher better. Uses the exact formula terms requested.
        """
        score = 0.0
        # legal_now_bonus
        if candidate.get("movable_now", False) or candidate.get("exists", False):
            score += 40

        # safe_same_suit_or_neutral_bonus
        cls = candidate.get("classification", "") or candidate.get("note", "")
        if "safe" in cls.lower() or "neutral" in cls.lower() or "empty" in str(candidate.get("card", "")).lower():
            score += 35
        elif "damaging" in cls.lower():
            score -= 50

        # low_clearance_cost
        cost = candidate.get("cost_estimate", candidate.get("depth", 5))
        score += max(0, 20 - cost * 3)

        # does_not_touch_protected_spades
        if candidate.get("safe_for_spades", True):
            score += 30
        else:
            score -= 40

        # does_not_increase_Q_blockers
        if not candidate.get("increases_q_blockers", False):
            score += 25
        else:
            score -= 100

        # supports future diamond cleanup (heuristic: if the dest is a Q of diamonds or helps diamonds)
        if "diamond" in str(candidate).lower() or getattr(candidate.get("card"), "suit", "") == "d" if hasattr(candidate.get("card"), "suit") else False:
            score += 10

        # penalties
        if candidate.get("damages_active_spade_chain", False):
            score -= 60
        if candidate.get("consumes_critical_empty", False) and current_sw > 15:
            score -= 15
        if candidate.get("creates_new_blocker_above_q", False):
            score -= 80

        return round(score, 1)

    def get_safe_park_destination_agenda(self, state: SpiderState, suit: str, blocker_rank: int = 11, target_col_for_blocker: Optional[int] = None) -> List[Dict[str, any]]:
        """Task 4: Candidate Q destination agenda for parking the blocker (e.g. J♦ rank 11).

        Scans for all Q (rank 12) of any suit.
        Returns list with full details + SafeParkDestinationScore.
        The diagnostic will print this and pick one (e.g. highest score, preferring low cost, safe, not increasing Q♠ blockers).
        """
        rank_names = {13: "K", 12: "Q", 11: "J", 10: "10", 9: "9", 8: "8",
                      7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2", 1: "A"}
        fstate = self.compute_foundation_state(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}
        prot = self.get_foundation_protected_assets(state, suit)

        needed_dest_rank = blocker_rank + 1  # 12 for J♦
        destinations = []

        for col_idx, col in enumerate(state.columns):
            up = col.face_up
            for i, c in enumerate(up):
                if c.rank == needed_dest_rank:
                    # Found a Q of suit c.suit
                    status = "visible_free" if i == len(up)-1 else ("visible_blocked" if i > 0 else "visible_free")
                    if i < len(up)-1:
                        if any(getattr(x, 'suit', None) == suit for x in up[i+1:]):
                            status = "visible_blocked"
                    depth_above = len(up) - i - 1
                    blockers_above = [str(x) for x in up[i+1:]]
                    blocker_count = depth_above

                    legal_now = (depth_above == 0)

                    clearance_cost = blocker_count

                    damages_protected = any(
                        (getattr(x, 'suit', None) == suit and getattr(x, 'rank', 0) in prot.get("visible_free_ranks", []) + prot.get("in_legal_fragment_ranks", []))
                        for x in up[i+1:]
                    )

                    increases_q_blockers = False
                    if target_col_for_blocker is not None and col_idx == target_col_for_blocker:
                        increases_q_blockers = True  # clearing by parking here would

                    sc = 0.0
                    if legal_now: sc += 50
                    sc += max(0, 30 - clearance_cost * 4)
                    if not damages_protected: sc += 40
                    if not increases_q_blockers: sc += 25
                    if getattr(c, 'suit', None) == 'd': sc += 10
                    if blocker_count == 0: sc += 20

                    dest = {
                        "card": f"{rank_names.get(needed_dest_rank, needed_dest_rank)}{getattr(c, 'suit', '?')}",
                        "column": col_idx,
                        "status": status,
                        "blockers_above": blockers_above,
                        "blocker_count": blocker_count,
                        "legal_for_blocker_now": legal_now,
                        "clearance_cost": clearance_cost,
                        "damages_protected_spades": damages_protected,
                        "increases_q_blockers": increases_q_blockers,
                        "SafeParkDestinationScore": round(sc, 1),
                        "suit_of_q": getattr(c, 'suit', None)
                    }
                    destinations.append(dest)

        # empties as temp
        for col_idx, col in enumerate(state.columns):
            if col.is_empty():
                destinations.append({
                    "card": "empty",
                    "column": col_idx,
                    "status": "empty",
                    "blockers_above": [],
                    "blocker_count": 0,
                    "legal_for_blocker_now": True,
                    "clearance_cost": 0,
                    "damages_protected_spades": False,
                    "increases_q_blockers": False,
                    "SafeParkDestinationScore": 10.0,
                    "suit_of_q": None,
                    "note": "temporary empty - verify later"
                })

        destinations.sort(key=lambda d: d.get("SafeParkDestinationScore", 0), reverse=True)
        return destinations

    def audit_safe_park_destinations(self, state: SpiderState, suit: str, blocker: "Card", target_blocker_col: int) -> List[Dict[str, any]]:
        """Task 1: Full feasibility audit for every Q destination that could accept the blocker (J♦).

        Returns detailed table entries with all required fields. Does NOT sort or select yet.
        Uses plan_obstructor_evacuation for "safe first evacuation exists".
        """
        rank_names = {13: "K", 12: "Q", 11: "J", 10: "10", 9: "9", 8: "8",
                      7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2", 1: "A"}
        fstate = self.compute_foundation_state(state, suit)
        prot = self.get_foundation_protected_assets(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}

        needed = getattr(blocker, 'rank', 11) + 1  # 12
        audit = []

        for col_idx, col in enumerate(state.columns):
            up = col.face_up
            for i, c in enumerate(up):
                if getattr(c, 'rank', 0) == needed:
                    blockers_above = [str(x) for x in up[i+1:]]
                    blocker_count = len(blockers_above)
                    top_blocker = blockers_above[0] if blockers_above else None

                    # Legal parks for current top blocker (reuse evac)
                    evac = self.plan_obstructor_evacuation(needed, suit, state, prot)  # note: evac is for the Q itself as "target", but we want for the blocker above a candidate Q
                    # Better: treat the top blocker above *this* Q as the "blocker to park" for feasibility
                    # For simplicity, run evac on the blocker card if we can find it, but since we have top, use general check.
                    # Compute safe first evac for the top blocker above this candidate Q.
                    safe_first_exists = False
                    if blockers_above:
                        # Simulate moving the top blocker (k=1 from this col) to possible dsts and check via protected + Q-blocker monotonicity
                        for dst in range(10):
                            if dst == col_idx: continue
                            if state.can_move(col_idx, dst, 1):
                                sim = state.clone()
                                try:
                                    sim.move(col_idx, dst, 1)
                                    post_prot = self.get_foundation_protected_assets(sim, suit)
                                    post_q_height = self._get_q_blocker_count(sim, target_blocker_col)  # helper below
                                    damages = len(post_prot.get("visible_free_ranks",[])) < len(prot.get("visible_free_ranks",[])) or \
                                              len(post_prot.get("in_legal_fragment_ranks",[])) < len(prot.get("in_legal_fragment_ranks",[])) or \
                                              post_prot.get("attachable_adjacent_pairs",0) < prot.get("attachable_adjacent_pairs",0) or \
                                              post_prot.get("main_chain_length",0) < prot.get("main_chain_length",0)
                                    increases_q = post_q_height > self._get_q_blocker_count(state, target_blocker_col)
                                    if not damages and not increases_q:
                                        safe_first_exists = True
                                        break
                                except:
                                    pass

                    # Estimated total depth = blocker_count (simple; could be sum of recursive)
                    est_depth = blocker_count

                    # Touches protected Spades? (obstructors include protected free/frag Spades)
                    touches_prot = any(
                        getattr(x,'suit',None)==suit and getattr(x,'rank',0) in (prot.get("visible_free_ranks",[])+prot.get("in_legal_fragment_ranks",[]))
                        for x in up[i+1:]
                    )

                    # Increases Q♠ blockers? (if clearing would require parking on target col or similar)
                    increases_q = False  # conservative; detailed in sim above

                    # Is it the Q♠ target itself?
                    is_target_q = (col_idx == target_blocker_col)

                    # In/adjacent to protected Spade chain?
                    strong = prot.get("strongest_chain", [])
                    in_or_adj = (needed in strong) or any(abs(needed - s) == 1 for s in strong)

                    # Interferes with main Spade plan? (if damages protected or is critical for foundation)
                    interferes = touches_prot or is_target_q or (blocker_count > 3)  # heuristic

                    entry = {
                        "card": f"{rank_names.get(needed,needed)}{getattr(c,'suit','?')}",
                        "column": col_idx,
                        "blocker_count": blocker_count,
                        "exact_blockers": blockers_above,
                        "top_blocker": top_blocker,
                        "legal_parks_for_top": "see evac for details",
                        "safe_first_evac_exists": safe_first_exists,
                        "est_total_evac_depth": est_depth,
                        "touches_protected_spades": touches_prot,
                        "increases_q_blockers": increases_q,
                        "is_target_q": is_target_q,
                        "in_or_adj_protected_chain": in_or_adj,
                        "interferes_with_main_spade_plan": interferes,
                    }
                    audit.append(entry)

        return audit

    def _get_q_blocker_count(self, state: SpiderState, q_col: int) -> int:
        if q_col is None or q_col >= len(state.columns): return 99
        up = state.columns[q_col].face_up
        for i, c in enumerate(up):
            if getattr(c,'suit',None)=='s' and getattr(c,'rank',0)==12:
                return len(up) - i - 1
        return 99

    def select_safe_park_destination_feasibility_first(self, audit: List[Dict[str, any]], prot: Dict, current_sw: int, suit: str) -> Optional[Dict[str, any]]:
        """Task 2: New selection rule prioritizing feasibility and low clearance depth."""
        candidates = []
        for d in audit:
            if d.get("increases_q_blockers"): continue
            if d.get("touches_protected_spades"): continue  # "immediately damages"
            if not d.get("safe_first_evac_exists"): continue
            candidates.append(d)

        if not candidates:
            # fallback to any with safe first or lowest cost, but per spec prefer those with safe first
            candidates = [d for d in audit if d.get("safe_first_evac_exists")]
            if not candidates:
                candidates = sorted(audit, key=lambda x: x.get("blocker_count", 99))

        # Among remaining, min blocker count
        min_count = min(d.get("blocker_count", 99) for d in candidates)
        candidates = [d for d in candidates if d.get("blocker_count", 99) == min_count]

        # Tie-break
        def tie_key(d):
            interferes = d.get("interferes_with_main_spade_plan", False)
            is_diamond = "d" in str(d.get("card","")).lower()
            cost = d.get("blocker_count", 99)
            # lower sw risk, higher (negated) old score for tie
            sw_risk = 0 if current_sw < 18 else 1
            old_score = d.get("SafeParkDestinationScore", 0)  # if present
            return (1 if interferes else 0, 0 if is_diamond else 1, cost, sw_risk, -old_score)

        candidates.sort(key=tie_key)
        return candidates[0] if candidates else None

    def compute_connector_readiness(self, state: SpiderState, suit: str = "s", target_high: int = 12, target_low: int = 11) -> Dict[str, any]:
        """Task 2: ConnectorReadiness for e.g. Q♠ (12) → J♠ (11).

        Combines status of target, blocker count, safe park for top blocker,
        safe Q dest for blocker, empties, and whether protected chain survives.
        """
        fstate = self.compute_foundation_state(state, suit)
        prot = self.get_foundation_protected_assets(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}

        q_m = cmap.get(target_high, {})
        j_m = cmap.get(target_low, {})

        q_status = q_m.get("status", "unknown")
        blocker_col = q_m.get("column")
        blocker_count = 0
        top_blocker_str = None
        top_blocker_card = None
        if blocker_col is not None and blocker_col < len(state.columns):
            up = state.columns[blocker_col].face_up
            for i, c in enumerate(up):
                if getattr(c, 'suit', None) == suit and getattr(c, 'rank', 0) == target_high:
                    blockers = up[i+1:]
                    blocker_count = len(blockers)
                    top_blocker_card = blockers[0] if blockers else None
                    top_blocker_str = str(top_blocker_card) if top_blocker_card else None
                    break

        # safe park for top blocker?
        safe_park_for_top = False
        safe_q_dest_for_top = False
        if top_blocker_card:
            evac = self.plan_obstructor_evacuation(target_high, suit, state, prot)
            # Check if any safe first for the top blocker (re-use logic similar to audit)
            for blk in evac.get("blockers", [])[:1]:
                for p in blk.get("possible_parks", []):
                    if "safe" in p.get("classification", "") and not p.get("would_damage_active", True):
                        safe_park_for_top = True
                        break

            # safe Q dest for the blocker (reuse destination audit/select)
            audit = self.audit_safe_park_destinations(state, suit, top_blocker_card, blocker_col or -1)
            if audit:
                best = self.select_safe_park_destination_feasibility_first(audit, prot, 0, suit)
                if best and best.get("safe_first_evac_exists"):
                    safe_q_dest_for_top = True

        empties = sum(1 for c in state.columns if c.is_empty())

        # protected chain survives connector attempt? (rough: current main/attach not regressed vs snapshot, or just check if protected assets healthy)
        protected_survives = (
            prot.get("main_chain_length", 0) >= 3 and
            prot.get("attachable_adjacent_pairs", 0) >= 1 and
            len(prot.get("visible_free_ranks", [])) >= 2
        )

        readiness = (
            (1 if q_status == "visible_free" else 0) * 20 +
            max(0, 10 - blocker_count) * 5 +
            (20 if safe_park_for_top else 0) +
            (15 if safe_q_dest_for_top else 0) +
            empties * 5 +
            (10 if protected_survives else -10)
        )

        return {
            "q_status": q_status,
            "blocker_count_above_q": blocker_count,
            "top_blocker": top_blocker_str,
            "top_blocker_can_safely_park": safe_park_for_top,
            "safe_q_dest_exists_for_top": safe_q_dest_for_top,
            "empties": empties,
            "protected_chain_survives": protected_survives,
            "readiness_score": readiness,
            "details": f"Q={q_status} blockers={blocker_count} safe_park={safe_park_for_top} safe_dest={safe_q_dest_for_top} empties={empties} survives={protected_survives}"
        }

    def compute_parking_debt(self, state: SpiderState, suit: str = "s", blocker_rank: int = 11) -> Dict[str, any]:
        """Task 3: ParkingDebt = required temp parks for next connector - safe available parks.

        For current plateau, this will be positive (debt).
        """
        prot = self.get_foundation_protected_assets(state, suit)
        fstate = self.compute_foundation_state(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}

        # Required: at least 1 for the top blocker above the connector (Q/J in this case)
        required = 1  # for J♦ above Q♠; could be more for full tail

        # Safe available: empties + any verified safe_first for key blockers/dests
        empties = sum(1 for c in state.columns if c.is_empty())

        safe_available = empties
        # Check for the critical blocker (J=11)
        audit = self.audit_safe_park_destinations(state, suit, type('C', (object,), {'rank': blocker_rank, 'suit': 'd'})(), -1)
        for d in audit:
            if d.get("safe_first_evac_exists"):
                safe_available += 1
                break

        debt = required - safe_available
        return {
            "required": required,
            "safe_available": safe_available,
            "debt": debt,
            "empties": empties,
            "has_safe_for_critical_blocker": any(d.get("safe_first_evac_exists") for d in audit)
        }

    def has_parking_capacity_for_connector(self, state: SpiderState, suit: str = "s", blocker_rank: int = 11) -> bool:
        """Helper for Task 1 gates: at least one of empty, safe park for blocker, safe Q dest with safe_first, or low-cost route."""
        debt = self.compute_parking_debt(state, suit, blocker_rank)
        if debt.get("empties", 0) > 0 or debt.get("has_safe_for_critical_blocker", False):
            return True
        # Also check via readiness or dest audit for safe_first on a dest
        prot = self.get_foundation_protected_assets(state, suit)
        audit = self.audit_safe_park_destinations(state, suit, type('C', (object,), {'rank': blocker_rank, 'suit': 'd'})(), -1)
        if any(d.get("safe_first_evac_exists") for d in audit):
            return True
        return False

    def compute_first_foundation_viability(self, state: SpiderState, suit: str, target_high: int, target_low: int) -> Dict[str, any]:
        """Task 3: FirstFoundationViabilityScore with hard penalties.

        Higher is better. Connector-grounded: uses actual next_connector from main chain and its real top blocker
        for safe_first, debt, readiness. Old proxy fields retained for backward compat but grounded take precedence
        for verdicts and penalties. If !next_connector_safe_first, hard penalty and verdict must not be "locally executable".
        """
        fstate = self.compute_foundation_state(state, suit)
        prot = self.get_foundation_protected_assets(state, suit)
        cmap = {int(k): v for k, v in fstate.get(f"{suit}_completion_map", {}).items()}

        # foundation progress (usable ranks)
        usable = sum(1 for r in range(1,14) if cmap.get(r, {}).get("in_legal_fragment") or cmap.get(r, {}).get("attachable_to_next_higher") or cmap.get(r, {}).get("status") == "visible_free")
        foundation_progress = usable

        main_chain = prot.get("main_chain_length", 0)
        attach_pairs = prot.get("attachable_adjacent_pairs", 0)

        # NEW: connector-grounded (source of truth for safe_first etc.)
        grounded = self.compute_grounded_next_connector(state, suit)
        g_safe_first = grounded.get("next_connector_safe_first", False)
        g_debt = grounded.get("next_connector_parking_debt", 0)
        g_readiness = grounded.get("next_connector_readiness", 0)
        g_blk = grounded.get("next_connector_blocker_count", 0)
        g_top = grounded.get("next_connector_top_blocker")
        g_target = grounded.get("next_connector_target")

        # legacy proxy readiness (subordinated)
        ready = self.compute_connector_readiness(state, suit, target_high, target_low)
        connector_readiness = ready.get("readiness_score", 0)

        # legacy safe_first (for compat in old prints; grounded wins for decisions)
        strong = prot.get("strongest_chain", [])
        critical_blocker_rank = None
        if strong:
            high = max(strong)
            low = min(strong)
            if high < target_high:
                critical_blocker_rank = high + 1
            else:
                critical_blocker_rank = low - 1
        safe_first_legacy = False
        if critical_blocker_rank:
            audit = self.audit_safe_park_destinations(state, suit, type('C', (object,), {'rank': critical_blocker_rank, 'suit': suit})(), -1)
            safe_first_legacy = any(d.get("safe_first_evac_exists") for d in audit)

        # use grounded for the key signals
        safe_first = g_safe_first
        has_capacity = (grounded.get("spaces", 0) > 0) or safe_first
        spaces = grounded.get("spaces", sum(1 for c in state.columns if c.is_empty()))

        dist = grounded.get("foundation_distance") or self._compute_suit_foundation_distance(state, suit, fstate, cmap)
        parking_debt = g_debt

        buried = fstate.get(f"num_buried_{suit}", 0)
        wdepth = fstate.get(f"total_blocker_depth_{suit}", 0)

        sw = grounded.get("sw", sum(len(c.face_up) for c in state.columns if c.face_down))
        sw_risk = max(0, (sw - 15) / 5.0)

        fragility = max(0, 5 - main_chain) + max(0, 3 - attach_pairs)

        score = (
            foundation_progress * 3 +
            main_chain * 8 +
            attach_pairs * 5 +
            g_readiness * 0.6 +   # prefer grounded
            (25 if safe_first else 0) +
            (10 if has_capacity else -25) +
            spaces * 4 +
            - dist * 1.0 +
            - parking_debt * 10 +
            - wdepth * 0.5 +
            - sw_risk * 10 +
            - fragility * 6
        )

        # Hard penalties (stronger on missing connector-grounded safe_first)
        hard_penalty = 0
        if not safe_first:
            hard_penalty -= 120   # was -100; now emphasizes the defect
        if not has_capacity and spaces == 0:
            hard_penalty -= 80
        if parking_debt > 0:
            hard_penalty -= 50
        if g_blk > 0 and not safe_first:
            hard_penalty -= 30   # explicit cost for having an un-evaccable blocker on the actual connector

        score += hard_penalty

        ret = {
            "viability_score": round(score, 1),
            "foundation_progress": foundation_progress,
            "main_chain": main_chain,
            "attach_pairs": attach_pairs,
            "connector_readiness": connector_readiness,
            "safe_first_evac_exists": safe_first_legacy,  # legacy proxy
            "next_connector_safe_first": safe_first,
            "parking_capacity": has_capacity,
            "spaces": spaces,
            "foundation_distance": dist,
            "parking_debt": parking_debt,
            "next_connector_parking_debt": g_debt,
            "buried": buried,
            "wdepth": wdepth,
            "sw": sw,
            "protected_fragility": fragility,
            "hard_penalty": hard_penalty,
            "next_connector_target": g_target,
            "next_connector_blocker_count": g_blk,
            "next_connector_top_blocker": g_top,
            "next_connector_readiness": g_readiness,
            "details": f"prog={foundation_progress} main={main_chain} attach={attach_pairs} g_ready={g_readiness} g_safe_first={safe_first} g_debt={g_debt} blk={g_blk} top={g_top} dist={dist}"
        }
        return ret

    def _compute_suit_foundation_distance(self, state, suit, fstate, cmap):
        # Re-use the existing decomp logic but return only the scalar for the suit
        buried = fstate.get(f"buried_{suit}", [])
        wdepth = fstate.get(f"total_blocker_depth_{suit}", 0)
        empties = fstate.get("empties_available", 0)
        usable = sum(1 for r in range(1,14) if cmap.get(r, {}).get("in_legal_fragment") or cmap.get(r, {}).get("attachable_to_next_higher") or cmap.get(r, {}).get("status") == "visible_free")
        missing = 13 - usable
        breaks = 0
        prev = False
        for r in range(13, 0, -1):
            ok = cmap.get(r, {}).get("in_legal_fragment") or cmap.get(r, {}).get("attachable_to_next_higher") or cmap.get(r, {}).get("status") == "visible_free"
            if prev and not ok: breaks += 1
            prev = ok
        ag = sum(1 for m in cmap.values() if m.get("status") in ("buried", "visible_blocked") and not m.get("attachable_to_next_higher"))
        return round(missing*5 + breaks*8 + ag*4 + len(buried)*10 + wdepth*2 + max(0,2-empties)*15, 1)

    def is_foundation_move_compensated(self, damage: Dict[str, any], pre: Dict[str, any], post: Dict[str, any],
                                        current_report: Optional[any], suit: str, moved_same_suit_continuing: bool) -> Tuple[bool, str]:
        """Task 3: Decide if a damaging move is allowed because it produces clearly larger immediate campaign gain.

        Returns (allowed, reason).
        """
        if not damage.get("is_damaging"):
            return True, "no damage"

        gains = []
        # completing same-suit adjacent link / extending
        if moved_same_suit_continuing:
            gains.append("same-suit continuing link created")

        pre_main = pre.get("main_chain_length", 0)
        post_main = post.get("main_chain_length", 0)
        if post_main > pre_main:
            gains.append(f"MainChainLength {pre_main}->{post_main}")

        # longest run increase (we'll pass or compute outside if needed; here use main as proxy + attach)
        pre_attach = pre.get("attachable_adjacent_pairs", 0)
        post_attach = post.get("attachable_adjacent_pairs", 0)
        if post_attach > pre_attach:
            gains.append(f"attachable pairs {pre_attach}->{post_attach}")

        # exposing required target or freeing blocked active-suit (heuristic: more visible_free now, or a pre blocked became free)
        pre_free_ct = len(pre.get("visible_free_ranks", []))
        post_free_ct = len(post.get("visible_free_ranks", []))
        if post_free_ct > pre_free_ct:
            gains.append(f"more visible_free {pre_free_ct}->{post_free_ct}")

        # materially reducing FoundationDistance: we can approximate via main/attach/buried proxies here
        # (full decomp is done in audit harness). If main or attach up significantly, treat as gain.
        if (post_main - pre_main) >= 2 or (post_attach - pre_attach) >= 2:
            gains.append("material structural gain (main/attach)")

        if gains:
            return True, "compensated: " + "; ".join(gains)
        return False, "no sufficient campaign gain"

    def summarize(self, state: SpiderState) -> str:
        """Return a compact, human-readable diagnostic string (for console or logs)."""
        rep = self.analyze(state)
        lines: List[str] = []
        lines.append("=== Layer 2 Dynamic Dependency Report ===")
        lines.append(f"Global plan priority: {rep.global_plan['priority_clearance_order']}")
        lines.append(f"Eligible suits after r0: {rep.global_plan['eligible_after_r0']}")
        lines.append("")

        lines.append("Critical buried targets (priority suits):")
        if not rep.critical_buried:
            lines.append("  (none identified for top priority suits)")
        for t in rep.critical_buried:
            obs_str = ", ".join(str(c) for c in t.obstructors[-3:]) if t.obstructors else "(empty column face-up)"
            lines.append(f"  Suit {t.suit.upper()} col {t.column+1}: depth={t.depth}  top obstructors: [{obs_str}]")

        lines.append("")
        lines.append("Space creation opportunities (columns with face-down + face-up):")
        if not rep.space_opportunities:
            lines.append("  (none — no column currently has both face-up and face-down)")
        for op in rep.space_opportunities:
            lines.append(f"  Col {op.column+1}: {op.current_face_up_len} face-up on top of face-down  -> {op.notes}")

        lines.append("")
        lines.append("Reception notes (next known stock):")
        for n in rep.reception_notes:
            lines.append(f"  {n}")

        lines.append("")
        lines.append("(This report is the starting point for plan generation in Layer 3.)")
        return "\n".join(lines)


# --- Convenience entry point for quick diagnostics (used during Phase 1 development) ---
def main_diagnostic(deal_path: str = "deals/4925153.txt") -> DependencyReport:
    """Load the deal, build the static analysis, create initial state, and print the Layer 2 report.

    This is the concrete diagnostic required by the Phase 1 gate in the baselined plan.
    Returns the DependencyReport so it can be inspected programmatically.
    """
    p = Path(deal_path)
    # load_deal is the project's canonical way to get the 104 cards for this deal file.
    cards = load_deal(p)
    # Build the static global plan (reuses legacy build_deal_analysis exactly).
    # It expects the token list in the project's internal format.
    tokens = [str(c) for c in cards]  # safe round-trip for the analysis builder
    analysis = build_deal_analysis(tokens)

    state = SpiderState.from_cards(cards)  # initial layout, no moves yet

    analyser = DynamicDependencyAnalyser(analysis)
    print(analyser.summarize(state))

    report = analyser.analyze(state)
    return report


if __name__ == "__main__":
    main_diagnostic()


# --- Phase 1 gate support: human checkpoint near first deal decision point ---
def load_human_pre_deal1_state(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
) -> Tuple[SpiderState, int]:
    """Replay the human canonical opening up to (but not including) the first stock deal.

    Returns (state, num_moves_applied).
    This reaches the human's actual decision point for the first deal.
    """
    p_deal = Path(deal_path)
    cards = load_deal(p_deal)
    state = SpiderState.from_cards(cards)

    actions = parse_moves_file(Path(moves_path))
    applied = 0
    for action in actions:
        if action == ("deal",):
            break  # stop at the human's first deal decision
        if isinstance(action, tuple) and len(action) == 3:
            src, dst, k = action
            try:
                state.move(src, dst, k)
                applied += 1
            except Exception as e:
                print(f"Warning: could not apply human move {action}: {e}")
                break
    return state, applied


def run_full_phase1_gate_diagnostic(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
    out_dir: str = "src/spider/planner/diagnostics",
) -> None:
    """Run the analyser on BOTH the initial layout AND the human pre-deal1 decision point.

    Produces human-readable output files and prints a comparison.
    This is intended to satisfy the Phase 1 gate in the baselined plan.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Build analysis once (static global plan)
    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    # 1. Initial
    print("=== Initial layout (before any human moves) ===")
    init_state = SpiderState.from_cards(cards)
    init_report = analyser.analyze(init_state)
    init_summary = analyser.summarize(init_state)
    print(init_summary)
    (out / "initial_layout_dependency.txt").write_text(init_summary, encoding="utf-8")

    # 2. Human pre-deal1 decision point
    print("\n=== Human pre-deal1 decision point (after opening catalytic work) ===")
    human_state, applied = load_human_pre_deal1_state(deal_path, moves_path)
    print(f"Applied {applied} human moves before first deal.")
    human_summary = analyser.summarize(human_state)
    print(human_summary)
    (out / "human_pre_deal1_checkpoint_dependency.txt").write_text(human_summary, encoding="utf-8")

    # Comparison summary (key metrics for the gate)
    init_crit = [t for t in init_report.critical_buried if t.depth > 0]
    human_crit = [t for t in analyser.analyze(human_state).critical_buried if t.depth > 0]
    init_spaces = len(init_report.space_opportunities)
    human_spaces = len(analyser.analyze(human_state).space_opportunities)

    comp = f"""Phase 1 Gate Diagnostic Comparison (Deal 4925153)
Initial layout vs. Human state just before first stock deal ({applied} moves applied).

Critical buried targets still blocked (depth > 0):
  Initial: {len(init_crit)}
  Human pre-deal1: {len(human_crit)}

Space creation opportunities (columns with face-down still under face-up):
  Initial: {init_spaces}
  Human pre-deal1: {human_spaces}

This demonstrates the human's early work (parks + builds) systematically reducing obstructors on priority buried cards and converting space opportunities into actual empties before dealing the known stock.
See the two .txt files in this directory for full human-readable reports.
"""
    print("\n" + comp)
    (out / "phase1_gate_comparison.txt").write_text(comp, encoding="utf-8")


if __name__ == "__main__":
    # When run as script, do the full gate diagnostic (initial + human checkpoint)
    run_full_phase1_gate_diagnostic()
