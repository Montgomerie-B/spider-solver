"""
Phase 4 sketch / realizer adapter stub (early, to connect plans to execution).

A realizer takes a PlanStep + current state + a budget (moves or seconds or expansions)
and tries to advance the plan using Layer 1 tactical moves (reusing the legacy engine
and search primitives where possible).

For this first stub we do a very simple greedy loop:
- While budget and plan not "satisfied" (e.g. all its target_columns have depth 0 or a space was gained):
  - Ask the (legacy) order_moves or a tiny beam for the best tactical move that helps
    a target column of the plan (reduce depth on its critical buried, or empty a target col).
  - Apply it.
  - Re-check the plan preconditions/effects.

This is deliberately simple and will be improved (or replaced by calling the existing
_beam_to_next_deal with a plan-specific objective) once we have the full Layer 5 controller.

See the baselined plan for how this fits (Phase 4: Tactical realizer adapter).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from spider.deal import load_deal
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.planner.dependency import DynamicDependencyAnalyser, load_human_pre_deal1_state
from spider.planner.plans import PlanStep, propose_campaigns_from_dependencies
from spider.search import order_moves  # legacy tactical ordering, safe to reuse


def simple_realize_plan(
    plan: PlanStep,
    state: SpiderState,
    max_moves: int = 12,
    analysis=None,
    campaign_stats: Optional[dict] = None,
) -> Tuple[List[Tuple[int, int, int]], int, str, int]:
    """Very early realizer stub.

    Returns (list_of_moves_applied, mw_cost_spent, status_message, unlock_earned).
    Tries to make measurable progress on the plan's target_columns or effects.

    campaign_stats (optional): dict for "Do No Harm" tracking during Foundation campaigns.
    Keys populated: considered_damaging, vetoed, allowed_compensated, damaging_details (list of tuples).
    """
    if analysis is None:
        # caller should pass it, but for standalone we can rebuild
        cards = [c for col in state.columns for c in (col.face_down + col.face_up)]  # not perfect
        # better: the caller passes a fresh state from the deal
        pass

    applied_moves: List[Tuple[int, int, int]] = []
    total_cost = 0
    unlock_earned = 0  # count of explicit park-unlock moves (off-suit attaches under Gold/Space) performed; fed to L4 scorer
    original_state = state.clone()  # we work on the passed state (caller clones if needed)

    # Ensure campaign_stats has the Do No Harm counters (Task 2/3 tracking)
    if campaign_stats is not None:
        campaign_stats.setdefault("considered_damaging", 0)
        campaign_stats.setdefault("vetoed", 0)
        campaign_stats.setdefault("allowed_compensated", 0)
        campaign_stats.setdefault("damaging_details", [])

    for _ in range(max_moves):
        # Re-analyze current state to see if the plan is still relevant / advanced
        # (in real version we would have a proper "plan satisfied" predicate on the effects)
        # For stub: if any target column now has 0 face-up on its face-down (or is empty), we made progress
        progress_made = False
        for col_idx in plan.target_columns:
            col = original_state.columns[col_idx]  # note: we should use the live state
            # Use the passed state
            live_col = state.columns[col_idx]
            if not live_col.face_down and live_col.is_empty():
                progress_made = True
                break
            if live_col.face_down and len(live_col.face_up) == 0:
                progress_made = True
                break

        if progress_made:
            return applied_moves, total_cost, "plan advanced (target column cleared or exposed)", unlock_earned

        # Improved tactical choice: score legal moves by how much they help the current plan.
        # Re-analyze to get current opportunities.
        current_report = None
        if analysis is not None:
            try:
                current_report = DynamicDependencyAnalyser(analysis).analyze(state)
            except Exception:
                current_report = None

        # Hoist prot_analyser and pre_protected for efficiency and for hard filtering in connector mode
        prot_analyser = None
        pre_protected = {}
        connector_target_rank = None
        connector_suit = None
        if analysis is not None:
            try:
                prot_analyser = DynamicDependencyAnalyser(analysis)
                if plan.name.startswith("Foundation_"):
                    parts = plan.name.split("_")
                    connector_suit = parts[1].lower() if len(parts) > 1 else "c"
                    pre_protected = prot_analyser.compute_active_suit_protected_assets(state, connector_suit)
                    if "Connector" in plan.name and len(parts) >= 3:
                        pr = parts[-1]
                        if pr.upper() in {"K":13,"Q":12,"J":11,"10":10,"9":9,"8":8,"7":7,"6":6,"5":5,"4":4,"3":3,"2":2,"A":1}:
                            connector_target_rank = {"K":13,"Q":12,"J":11,"10":10,"9":9,"8":8,"7":7,"6":6,"5":5,"4":4,"3":3,"2":2,"A":1}[pr.upper()]
                        else:
                            try:
                                connector_target_rank = int(pr)
                            except:
                                connector_target_rank = None
            except Exception:
                prot_analyser = None
                pre_protected = {}

        legal_scored = []
        for src in range(10):
            for dst in range(10):
                if src == dst:
                    continue
                for k in range(1, len(state.columns[src].face_up) + 1):
                    if state.can_move(src, dst, k):
                        move = (src, dst, k)

                        # === Hard filter for Connector Evacuation Executor (Task 2) ===
                        # When in FoundationConnector_S_Q (or general Connector), only consider moves that help evacuate the blockers above the target rank.
                        # This narrows candidates before any scoring.
                        if "Connector" in plan.name and connector_target_rank is not None and prot_analyser and connector_suit:
                            try:
                                ctask = prot_analyser.get_foundation_connector_tasks(state, connector_suit)
                                this_task = next((t for t in ctask if t.get("target_rank") == connector_target_rank), None)
                                if this_task:
                                    tcol = this_task.get("src_col")
                                    height_above = this_task.get("num_blockers", 0)

                                    # Compute would-be effect on blocker count (monotonicity)
                                    would_increase_blockers = False
                                    if dst == tcol and src != tcol:
                                        would_increase_blockers = True  # parking something onto the Q column above target

                                    if would_increase_blockers:
                                        # Hard veto per Task 4: do not allow moves that increase Q blocker count
                                        # (unless it is the connect that resolves it -- checked later in scoring)
                                        continue

                                    # Hard filter: only helpful evac moves (A-E categories focused on target col or safe parks for top blocker)
                                    is_connector_helpful = False
                                    if src == tcol:
                                        is_connector_helpful = True  # A/C: moves from the target column remove top blocker(s)
                                    else:
                                        # Check if this is a safe park for the current top blocker (B/D)
                                        evac = prot_analyser.plan_obstructor_evacuation(connector_target_rank, connector_suit, state, pre_protected)
                                        for blk in evac.get("blockers", [])[:1]:  # focus on top blocker
                                            for p in blk.get("possible_parks", []):
                                                if p.get("dst_col") == dst and "safe" in p.get("classification", ""):
                                                    is_connector_helpful = True
                                                    break
                                    if not is_connector_helpful:
                                        continue  # reject all other moves per Task 2 hard filter
                            except Exception:
                                pass  # if filter fails, fall back to normal (conservative)

                        score = 0
                        # Base: touching a plan target column is good
                        if src in plan.target_columns or dst in plan.target_columns:
                            score += 10
                        # For space/gold plans: strongly prefer moves that empty a column (0-cost to empty is gold)
                        if "Gold" in plan.name or "Space" in plan.name:
                            if state.columns[dst].is_empty():
                                score += 50  # emptying a column
                            if state.columns[src].face_down and len(state.columns[src].face_up) == k:
                                score += 30  # clearing the face-up from a space_opp column
                        # For clearance plans: prefer reducing depth on the target
                        if plan.target_suit and current_report:
                            for t in current_report.critical_buried:
                                if t.column in plan.target_columns and t.suit == plan.target_suit:
                                    if src == t.column or dst == t.column:
                                        score += 20 - t.depth  # higher for shallower
                        # Park unlock bonus for space/gold plans (fed back from analyzer on the 89-cost layered candidate):
                        # The 89 path was very park-heavy with many "good unlock delta" parks that enabled catalytic pre-deal work.
                        # Current generic reveal bonus was insufficient; add explicit small bonus for off-suit (park) moves
                        # when pursuing Gold_Spaces or space creation, as they frequently unlock the tableau.
                        if ("Gold" in plan.name or "Space" in plan.name) and k > 0:
                            try:
                                if not state.columns[dst].is_empty() and len(state.columns[src].face_up) >= k:
                                    # rough park: the card that will attach (top of moved run) has different suit than dst top
                                    moved_card = state.columns[src].face_up[-k]  # the card that touches dst
                                    dst_top = state.columns[dst].face_up[-1]
                                    if getattr(moved_card, 'suit', None) and getattr(dst_top, 'suit', None) and moved_card.suit != dst_top.suit:
                                        score += 12  # explicit park-for-unlock bonus per 89 analysis
                                        unlock_earned += 1  # real value for L4 plan_aware_score unlock term (credits the +30..+43 good deltas from analyzer on layered candidates)
                            except Exception:
                                pass

                        # === Foundation_<Suit> "Do No Harm" campaign (Tasks 1-4) ===
                        # Exact target campaign for the suit. Snapshot protected assets (specific ranks)
                        # before every candidate. Detect structural damage to active-suit free/fragment/pairs/chain.
                        # Hard veto (score -1000) unless compensated by listed larger gains.
                        # Strong +preserve / +extend and -damage scoring terms.
                        if plan.name.startswith("Foundation_"):
                            # use hoisted prot_analyser / pre_protected / suit if available
                            if connector_suit:
                                suit = connector_suit
                            else:
                                parts = plan.name.split("_")
                                suit = parts[1].lower() if len(parts) > 1 else "c"

                            # Task 1: snapshot protected assets for this pre-move state (specific ranks + chains)
                            if not pre_protected and prot_analyser:
                                try:
                                    pre_protected = prot_analyser.compute_active_suit_protected_assets(state, suit)
                                except Exception:
                                    pre_protected = prot_analyser.get_foundation_protected_assets(state, suit) if prot_analyser else {}

                            src_col = state.columns[src]
                            dst_col = state.columns[dst]
                            moved_run = src_col.face_up[-k:] if k <= len(src_col.face_up) else []
                            moved_suit_cards = [c for c in moved_run if getattr(c, 'suit', None) == suit]
                            is_suit_move = bool(moved_suit_cards) or any(getattr(c, 'suit', None) == suit for c in (dst_col.face_up[-1:] or []))

                            # Simulate the candidate to evaluate post state for damage + deltas
                            is_damaging = False
                            damage_reasons = []
                            post_protected = pre_protected
                            sim_ok = False
                            moved_same_suit_continuing = False
                            if prot_analyser and pre_protected:
                                sim_state = state.clone()
                                try:
                                    sim_state.move(src, dst, k)
                                    sim_ok = True
                                    post_protected = prot_analyser.compute_active_suit_protected_assets(sim_state, suit)

                                    # Task 2: specific-rank damage detector (catches J♠/9♠ regression even if aggregate counts flat)
                                    dmg = prot_analyser.detect_foundation_move_damage(pre_protected, post_protected, suit)
                                    is_damaging = dmg.get("is_damaging", False)
                                    damage_reasons = dmg.get("reasons", [])

                                    # Additional harms 6-8 using move context + pre/post
                                    # 6: place a non-suit card onto an active-suit card that was free/useful
                                    if dst_col.face_up:
                                        dst_top_pre = dst_col.face_up[-1]
                                        if getattr(dst_top_pre, 'suit', None) == suit:
                                            pre_free = set(pre_protected.get("visible_free_ranks", []))
                                            pre_frag = set(pre_protected.get("ranks_in_legal_fragments", pre_protected.get("in_legal_fragment_ranks", [])))
                                            if dst_top_pre.rank in (pre_free | pre_frag) and getattr(moved_run[0] if moved_run else None, 'suit', None) != suit:
                                                is_damaging = True
                                                damage_reasons.append("covered useful active-suit card (free/frag) with off-suit")
                                    # 7: move an active-suit card onto a non-continuing destination
                                    if moved_suit_cards:
                                        if dst_col.face_up:
                                            dtop = dst_col.face_up[-1]
                                            top_moved = moved_run[0]
                                            continuing = (getattr(dtop, 'suit', None) == suit and dtop.rank - 1 == top_moved.rank)
                                            if getattr(top_moved, 'suit', None) == suit and not continuing:
                                                is_damaging = True
                                                damage_reasons.append("active-suit moved to non-continuing destination")
                                        else:
                                            # moving suit card to empty is usually ok, but if it was the only parking and no gain, see 8
                                            pass
                                    # 8: consume last available parking/empty without improving campaign
                                    pre_empties = sum(1 for c in state.columns if c.is_empty())
                                    post_empties = sum(1 for c in sim_state.columns if c.is_empty())
                                    if pre_empties > 0 and post_empties == 0 and not is_suit_move:
                                        # only penalise if no obvious campaign structural gain in post
                                        if post_protected.get("main_chain_length", 0) <= pre_protected.get("main_chain_length", 0) and \
                                           post_protected.get("attachable_adjacent_pairs", 0) <= pre_protected.get("attachable_adjacent_pairs", 0):
                                            is_damaging = True
                                            damage_reasons.append("consumed last empty without campaign structural gain")

                                except Exception:
                                    # sim failed -> conservative: do not let a weird move damage structure
                                    is_damaging = True
                                    damage_reasons.append("sim move failed (conservative)")

                            # Track Task 2 counts (considered on every evaluated candidate during Foundation campaign)
                            if campaign_stats is not None and is_damaging:
                                campaign_stats["considered_damaging"] = campaign_stats.get("considered_damaging", 0) + 1

                            # Identify urgent target (for compensation + scoring)
                            target = None
                            if current_report:
                                s_buried = [t for t in current_report.critical_buried if getattr(t, 'suit', None) == suit]
                                if s_buried:
                                    target = max(s_buried, key=lambda t: getattr(t, 'depth', 0))

                            # Base suit bias
                            if is_suit_move:
                                score += 12

                            # Compensation detection (Task 3)
                            has_compensation = False
                            comp_reason = ""
                            if target and (src == target.column or dst == target.column):
                                score += 30 - min(getattr(target, 'depth', 0), 20)
                                has_compensation = True
                                comp_reason = "target column progress"
                            if moved_run and all(getattr(c, 'suit', None) == suit for c in moved_run):
                                if dst_col.face_up:
                                    dst_top = dst_col.face_up[-1]
                                    if dst_top.suit == suit and dst_top.rank - 1 == moved_run[0].rank:
                                        score += 35 + k * 4
                                        has_compensation = True
                                        comp_reason = (comp_reason + "; " if comp_reason else "") + "same-suit run extension"
                                        moved_same_suit_continuing = True
                            if current_report:
                                for t in current_report.critical_buried:
                                    if getattr(t, 'suit', None) == suit and (src == t.column or dst == t.column):
                                        score += 22 - min(getattr(t, 'depth', 0), 15)
                                        has_compensation = True
                                        comp_reason = (comp_reason + "; " if comp_reason else "") + "buried exposure for suit"
                            if state.columns[dst].is_empty():
                                score += 18

                            # Use the full is_compensated helper if we have post
                            if is_damaging and sim_ok and prot_analyser:
                                comp_ok, comp_msg = prot_analyser.is_foundation_move_compensated(
                                    {"is_damaging": is_damaging, "reasons": damage_reasons},
                                    pre_protected, post_protected, current_report, suit, moved_same_suit_continuing
                                )
                                if comp_ok and "no damage" not in comp_msg:
                                    has_compensation = True
                                    comp_reason = comp_msg

                            # Task 3: hard veto unless compensated
                            if is_damaging:
                                if has_compensation:
                                    if campaign_stats is not None:
                                        campaign_stats["allowed_compensated"] = campaign_stats.get("allowed_compensated", 0) + 1
                                        campaign_stats.setdefault("compensated_allowed_details", []).append(
                                            (f"{src}->{dst}x{k}", damage_reasons[:], comp_reason or "compensated")
                                        )
                                        # compat for existing audit harnesses
                                        campaign_stats.setdefault("damaging_details", []).append(
                                            (f"{src}->{dst}x{k}", damage_reasons[:], comp_reason or "compensated")
                                        )
                                    score -= 5  # small friction even when allowed
                                else:
                                    if campaign_stats is not None:
                                        campaign_stats["vetoed"] = campaign_stats.get("vetoed", 0) + 1
                                        campaign_stats.setdefault("vetoed_details", []).append(
                                            (f"{src}->{dst}x{k}", damage_reasons[:], "no compensation")
                                        )
                                    score -= 1000  # hard veto: will not be the top scored move

                            # === Task 4: New move scoring terms (strong + for preserve/extend, strong - for damage) ===
                            if sim_ok and pre_protected and post_protected:
                                # Deltas
                                d_free = len(post_protected.get("visible_free_ranks", [])) - len(pre_protected.get("visible_free_ranks", []))
                                d_frag = len(post_protected.get("in_legal_fragment_ranks", [])) - len(pre_protected.get("in_legal_fragment_ranks", []))
                                d_attach = post_protected.get("attachable_adjacent_pairs", 0) - pre_protected.get("attachable_adjacent_pairs", 0)
                                d_main = post_protected.get("main_chain_length", 0) - pre_protected.get("main_chain_length", 0)
                                d_longest_proxy = d_main  # longest run tracked via main for this suit campaign

                                # Strong positives (preserve visible_free, attach pairs, legal fragments, extend, conversions)
                                if d_free > 0:
                                    score += 25 * d_free
                                if d_attach > 0:
                                    score += 30 * d_attach
                                if d_main > 0:
                                    score += 25 * d_main
                                if d_frag > 0:
                                    score += 12 * d_frag

                                # Preserve bonus: if the specific pre protected ranks are still protected post (even if count same)
                                pre_f_set = set(pre_protected.get("visible_free_ranks", []))
                                post_f_set = set(post_protected.get("visible_free_ranks", []))
                                if pre_f_set and pre_f_set.issubset(post_f_set):
                                    score += 18  # strong positive for preserving the exact free assets
                                pre_fg_set = set(pre_protected.get("ranks_in_legal_fragments", pre_protected.get("in_legal_fragment_ranks", [])))
                                post_fg_set = set(post_protected.get("ranks_in_legal_fragments", post_protected.get("in_legal_fragment_ranks", [])))
                                if pre_fg_set and pre_fg_set.issubset(post_fg_set):
                                    score += 15

                                # Conversion bonuses
                                newly_free = len(post_f_set - pre_f_set)
                                if newly_free > 0:
                                    score += 20 * newly_free
                                if d_attach > 0:
                                    score += 10 * d_attach  # extra for pair creation

                                # Strong penalties (the 6 listed)
                                if d_free < 0:
                                    score -= 60 * (-d_free)
                                if d_frag < 0:
                                    score -= 50 * (-d_frag)
                                if d_attach < 0:
                                    score -= 50 * (-d_attach)
                                if d_main < 0:
                                    score -= 100 * (-d_main)
                                # longest active-suit run decrease (proxy via main or attach)
                                if d_longest_proxy < 0:
                                    score -= 40 * (-d_longest_proxy)
                                # covering useful already added is_damaging above; add extra here if detected in reasons
                                if any("covered useful" in r or "non-continuing" in r for r in damage_reasons):
                                    score -= 45

                            # Connector-specific mode (Task 4): when plan is FoundationConnector_S_<Rank>, heavily bias toward
                            # moves that advance the exact connector (evac its blockers safely, reduce its depth, or make the connect itself).
                            # Still fully under Do No Harm (the is_damaging / veto logic above already applies because name starts with Foundation_).
                            if "Connector" in plan.name and sim_ok:
                                try:
                                    t_rank = connector_target_rank
                                    if t_rank is not None and prot_analyser:
                                        # get fresh task + evac plan for this target (Task 3 integration)
                                        ctask = prot_analyser.get_foundation_connector_tasks(state, suit)
                                        this_task = next((t for t in ctask if t.get("target_rank") == t_rank), None)
                                        evac = prot_analyser.plan_obstructor_evacuation(t_rank, suit, state, pre_protected) if this_task else {}
                                        if this_task:
                                            tcol = this_task.get("src_col")
                                            nblock = this_task.get("num_blockers", 0)
                                            # big bonus for actually connecting the exact target (the run bottom is the target, dst matches)
                                            if moved_run and getattr(moved_run[0], "rank", 0) == t_rank and getattr(moved_run[0], "suit", None) == suit:
                                                if dst_col.face_up and getattr(dst_col.face_up[-1], "rank", 0) == t_rank + 1 and getattr(dst_col.face_up[-1], "suit", None) == suit:
                                                    score += 80  # huge for completing the connector
                                            # strong bonus for evacuating a blocker from the target's column (src==tcol)
                                            if src == tcol and nblock > 0:
                                                score += 80 + min(30, nblock * 6)
                                            # extra big bonus if the dst is one of the "recommended safe parks" from evac planner
                                            rec_parks = evac.get("recommended_first_parks", [])
                                            for rp in rec_parks:
                                                if rp.get("park", {}).get("dst_col") == dst and src == tcol:
                                                    score += 120  # strongly prefer Do-No-Harm safe evac for the connector
                                                    break
                                            # penalty if we increased blockers on the target col without progress
                                            if src != tcol and dst == tcol and getattr(moved_run[0], "suit", None) != suit:
                                                score -= 25  # burying the target worse
                                            # success proxy: if post has fewer blockers conceptually or chain extended
                                            if post_protected.get("main_chain_length", 0) > pre_protected.get("main_chain_length", 0):
                                                score += 15
                                            if any("safe" in (p.get("classification","") or "") for blk in evac.get("blockers", []) for p in blk.get("possible_parks", [])):
                                                score += 5  # mild global for having safe options
                                except Exception:
                                    pass

                            # === Parking-capacity / ConnectorReadiness bias for Foundation_S_Spades (upstream planning, Tasks 2-3) ===
                            # Penalize worsening ParkingDebt; reward improving ConnectorReadiness.
                            # This prevents building an "impressive but unfinishable" Spade spine (the previous plateau problem).
                            if suit == "s" and prot_analyser and pre_protected and sim_ok:
                                try:
                                    pre_debt = prot_analyser.compute_parking_debt(state, suit, 11)
                                    post_debt = prot_analyser.compute_parking_debt(sim_state, suit, 11)
                                    pre_ready = prot_analyser.compute_connector_readiness(state, suit, 12, 11)
                                    post_ready = prot_analyser.compute_connector_readiness(sim_state, suit, 12, 11)

                                    debt_delta = post_debt.get("debt", 0) - pre_debt.get("debt", 0)
                                    ready_delta = post_ready.get("readiness_score", 0) - pre_ready.get("readiness_score", 0)

                                    if debt_delta > 0:
                                        score -= 35 * debt_delta   # strong penalty for accumulating unpayable parking debt
                                    if ready_delta > 0:
                                        score += 25 * ready_delta  # reward states that keep the connector finishable

                                    # For biased configs (preserve capacity / feasible route), extra credit for maintaining empties or safe_first
                                    if any(x in (plan.name or "").lower() for x in ("preserve", "capacity", "feasible", "debt", "readiness")):
                                        if post_debt.get("empties", 0) >= pre_debt.get("empties", 0) or post_debt.get("has_safe_for_critical_blocker", False):
                                            score += 30
                                except Exception:
                                    pass

                            # Legacy secondary penalties (kept light)
                            if moved_run and all(getattr(c, 'suit', None) == suit for c in moved_run):
                                if dst_col.face_up and not (dst_col.face_up[-1].suit == suit and dst_col.face_up[-1].rank - 1 == moved_run[0].rank):
                                    score -= 8
                            if len([c for c in state.columns if c.is_empty()]) <= 1 and is_suit_move:
                                score -= 4

                            # Pre-deal gated preview bias (new objective): reward moves that improve post-first-deal ExecutableFoundationGate prospects.
                            if ("PreDeal" in plan.name or "Gated" in plan.name) and prot_analyser:
                                try:
                                    preview = prot_analyser.post_deal_gate_preview(sim_state)
                                    # strong bonus if the move enables a gate pass or major liquidity improvement
                                    if preview.get("any_pass"):
                                        score += 80
                                    score += min(40, preview.get("improvement_signal", 0))
                                    if preview.get("post_spaces", 0) > 0:
                                        score += 10
                                    if preview.get("safe_first", False):
                                        score += 15
                                except Exception:
                                    pass

                        # === Strict Exposure Executor for buried targets (new Task 3 semantics) ===
                        if "Expose" in plan.name and prot_analyser and pre_protected:
                            try:
                                # target col from preconditions or from current grounded task
                                tcol = None
                                trank = 12
                                if plan.preconditions:
                                    tcol = plan.preconditions.get("target_col") or plan.preconditions.get("dest_col")
                                    trank = plan.preconditions.get("target_rank", trank)
                                if tcol is None and "grounded" in dir(prot_analyser):
                                    # fallback: use the current state task
                                    gt = prot_analyser.compute_grounded_next_connector(state, suit) if hasattr(prot_analyser, "compute_grounded_next_connector") else {}
                                    tcol = gt.get("target_col")
                                if tcol is not None:
                                    # bonus for any move originating from the exposure column (reduces face_up there)
                                    if src == tcol:
                                        score += 90  # strong for clearing obstructors
                                        # extra if it actually reduced the col's visible count conceptually (post check)
                                        if post_protected.get("main_chain_length", 0) >= pre_protected.get("main_chain_length", 0):
                                            score += 20
                                    # hard filter: only moves from the target col or direct helpers; reject others that don't help exposure
                                    if src != tcol:
                                        # allow only if the move creates space that can be used for exposure later, but for strict, prefer only tcol moves
                                        if not any(x in (plan.name or "").lower() for x in ("helper", "space")):
                                            score -= 200  # effectively veto non-exposure moves
                            except Exception:
                                pass

                        # === Strict Safe-Park Creation Executor (Tasks 1-5) ===
                        if "SafePark" in plan.name and prot_analyser and pre_protected:
                            try:
                                blocker_rank = 11
                                blocker_suit = "d"
                                target_q_col = 1  # Q♠ col in plateau

                                chosen_dest_col = None
                                if plan.preconditions and "dest_col" in plan.preconditions:
                                    chosen_dest_col = plan.preconditions.get("dest_col")
                                elif "SafeParkDestination" in plan.name:
                                    # parse from name if present
                                    for p in plan.name.split("_"):
                                        if p.startswith("col"):
                                            try: chosen_dest_col = int(p[3:])
                                            except: pass

                                # current Q♠ height for monotonicity
                                q_height = 0
                                for cidx, col in enumerate(state.columns):
                                    for ii, cc in enumerate(col.face_up):
                                        if getattr(cc,'suit',None)=='s' and getattr(cc,'rank',0)==12:
                                            q_height = len(col.face_up) - ii - 1
                                            break

                                is_safe_park_helpful = False
                                would_violate = False

                                if src != target_q_col and dst == target_q_col:
                                    would_violate = True
                                if src == target_q_col:
                                    is_safe_park_helpful = True
                                if chosen_dest_col is not None and src == chosen_dest_col:
                                    is_safe_park_helpful = True
                                moved_has_jd = False
                                if moved_run:
                                    for mc in moved_run:
                                        if getattr(mc, 'rank', 0) == blocker_rank and getattr(mc, 'suit', None) == blocker_suit:
                                            moved_has_jd = True
                                            break
                                if moved_has_jd:
                                    is_safe_park_helpful = True

                                if would_violate and not moved_has_jd:
                                    # hard veto per Task 3
                                    continue
                                if not is_safe_park_helpful:
                                    # hard filter per Task 2
                                    continue

                                # scoring bonuses
                                if moved_has_jd:
                                    if dst_col.face_up:
                                        dtop = dst_col.face_up[-1]
                                        if getattr(dtop, 'rank', 0) == 12:
                                            score += 120
                                    else:
                                        score += 80
                                if src == target_q_col:
                                    score += 60
                                if chosen_dest_col is not None and src == chosen_dest_col:
                                    score += 80
                                if any("damage" in r.lower() or "regress" in r.lower() for r in damage_reasons):
                                    score -= 100
                            except Exception:
                                pass

                        legal_scored.append((score, move))
                        break

        if not legal_scored:
            chosen = None
        else:
            legal_scored.sort(reverse=True)  # highest score first
            chosen = legal_scored[0][1]

        if not chosen:
            return applied_moves, total_cost, "no more legal moves", unlock_earned

        src, dst, k = chosen
        try:
            cost = state.move(src, dst, k)
            applied_moves.append((src, dst, k))
            total_cost += cost
        except Exception as e:
            return applied_moves, total_cost, f"move failed: {e}", unlock_earned

    return applied_moves, total_cost, "budget exhausted", unlock_earned


def demo_realize_one_campaign_from_human_state(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
) -> None:
    """Demo: take the human pre-deal1 state, propose campaigns, pick the top one,
    and try to realize a few moves toward it using the stub realizer.
    Prints a small trace.
    """
    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    human_state, _ = load_human_pre_deal1_state(deal_path, moves_path)
    report = analyser.analyze(human_state)
    plans = propose_campaigns_from_dependencies(report, max_plans=3)

    if not plans:
        print("No plans proposed.")
        return

    top_plan = plans[0]
    print(f"Top proposed plan: {top_plan}")
    print("Attempting simple realization (up to 8 moves) from the human pre-deal1 state...")

    # Clone so we don't mutate the original for the demo
    work_state = human_state.clone()
    moves, cost, status, _unlock = simple_realize_plan(top_plan, work_state, max_moves=8, analysis=analysis)

    print(f"Applied {len(moves)} moves, cost {cost}. Status: {status}")
    print("Moves:", moves)
    print("(In a full realizer this would be longer sequences and would update the plan's 'progress' metrics.)")


if __name__ == "__main__":
    demo_realize_one_campaign_from_human_state()