#!/usr/bin/env python3
"""Opt013 — algebraic free-component expansion (exact).

Production path: expand_component_algebraic
Oracle path:     expand_component_bruteforce  (Opt012 free_closure enumeration)

A free component is the set of labelled arrangements of free movable piles
and empty slots on a fixed free-slot index set, with fixed columns invariant.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state
from spider.planner.diagnostics.opt012_free_quotient import (
    apply_action,
    component_key_from_state,
    expand_component_paid,
    free_closure,
    free_moves,
    free_slot_analysis,
    is_free_relocation,
    reconstruct_free_path,
)
from spider.rules import mobilityware_move_cost
from spider.state_identity import CanonicalStateKey, card_tuple, canonical_state_key

BACKEND_ID = "opt013_algebraic_v1"
ORACLE_BACKEND_ID = "opt012_bruteforce_v1"

CardT = Tuple[str, int]
PileT = Tuple[CardT, ...]


# ---------------------------------------------------------------------------
# Symbolic component model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FreeEntity:
    """A complete movable open pile (no face-down)."""

    cards: PileT
    _packed: bytes = field(init=False, repr=False, compare=False, hash=False)
    _height: int = field(init=False, repr=False, compare=False, hash=False)
    _card_objs: tuple = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        from spider.cards import Card
        from spider.packed_state import SUIT_IDX

        packed = bytes((SUIT_IDX[s] << 4) | (r & 0x0F) for s, r in self.cards)
        objs = tuple(Card(s, r) for s, r in self.cards)
        object.__setattr__(self, "_packed", packed)
        object.__setattr__(self, "_height", len(self.cards))
        object.__setattr__(self, "_card_objs", objs)

    @property
    def packed(self) -> bytes:
        return self._packed

    @property
    def height(self) -> int:
        return self._height

    @property
    def card_objs(self):
        return self._card_objs


@dataclass(frozen=True)
class ComponentModel:
    """Immutable symbolic view of a free-relocation component."""

    free_slots: Tuple[int, ...]  # sorted column indices
    free_piles: Tuple[FreeEntity, ...]  # multiset as sorted tuple of piles
    n_empty: int
    fixed_snapshot: bytes  # packed fixed columns (from component_key)
    stock: Tuple[CardT, ...]
    foundations: Tuple[Tuple[CardT, ...], ...]
    # labelled fixed columns: col_idx -> (fd cards, fu cards)
    fixed_columns: Tuple[Tuple[int, Tuple[CardT, ...], Tuple[CardT, ...]], ...]

    @property
    def n_slots(self) -> int:
        return len(self.free_slots)


def model_from_state(st: SpiderState) -> ComponentModel:
    analysis = free_slot_analysis(st)
    free_set = set(analysis["free_indices"])
    piles = tuple(
        sorted(
            (FreeEntity(p) for p in analysis["free_piles"]),
            key=lambda e: e.packed,
        )
    )
    fixed: List[Tuple[int, Tuple[CardT, ...], Tuple[CardT, ...]]] = []
    for i, col in enumerate(st.columns):
        if i in free_set:
            continue
        fixed.append(
            (
                i,
                tuple(card_tuple(c) for c in col.face_down),
                tuple(card_tuple(c) for c in col.face_up),
            )
        )
    fixed.sort(key=lambda x: x[0])
    return ComponentModel(
        free_slots=tuple(sorted(analysis["free_indices"])),
        free_piles=piles,
        n_empty=int(analysis["n_empty"]),
        fixed_snapshot=component_key_from_state(st).packed_fixed,
        stock=tuple(card_tuple(c) for c in st.stock),
        foundations=tuple(
            sorted(tuple(card_tuple(c) for c in seq) for seq in st.foundations)
        ),
        fixed_columns=tuple(fixed),
    )


# ---------------------------------------------------------------------------
# Arrangement: assignment of piles/empties to free slots
# ---------------------------------------------------------------------------

# For each free slot: None = empty, or FreeEntity
Arrangement = Dict[int, Optional[FreeEntity]]


def arrangement_from_state(st: SpiderState) -> Arrangement:
    analysis = free_slot_analysis(st)
    free_set = set(analysis["free_indices"])
    arr: Arrangement = {}
    for i in free_set:
        col = st.columns[i]
        if col.is_empty():
            arr[i] = None
        else:
            arr[i] = FreeEntity(tuple(card_tuple(c) for c in col.face_up))
    return arr


def build_state_from_arrangement(
    model: ComponentModel, arr: Arrangement, template: SpiderState
) -> SpiderState:
    """Materialise a labelled arrangement into a SpiderState (clone of template base).

    Fixed columns are taken from ``template`` when they already match the model
    (typical free-rearrangement case); free slots are rewritten from ``arr``.
    """
    from spider.engine import Column

    st = template.clone()
    # Free slots only — fixed columns already correct on a free-orbit member.
    for i in model.free_slots:
        ent = arr[i]
        if ent is None:
            st.columns[i] = Column([], [])
        else:
            st.columns[i] = Column([], list(ent.card_objs))
    return st


def _arrangement_signature(model: ComponentModel, arr: Arrangement) -> Tuple:
    """Immutable exact signature of a free-slot assignment (for witness dedupe)."""
    return tuple(
        None if arr[s] is None else arr[s].packed for s in model.free_slots  # type: ignore
    )


def canonical_arrangement(model: ComponentModel) -> Arrangement:
    """Deterministic placement: sorted piles into sorted free slots, empties last."""
    slots = list(model.free_slots)
    piles = list(model.free_piles)
    arr: Arrangement = {s: None for s in slots}
    for s, p in zip(slots[: len(piles)], piles):
        arr[s] = p
    return arr


# ---------------------------------------------------------------------------
# plan_free_rearrangement — cycle decomposition with empty token
# ---------------------------------------------------------------------------


def plan_free_rearrangement(
    source: Arrangement, target: Arrangement
) -> List[Action]:
    """Zero-cost moves transforming source arrangement into target.

    Tokens are uniquely identified pile instances (multiset-aware) plus empties.
    All moves place a complete pile onto a currently empty free slot.
    """
    if set(source) != set(target):
        raise ValueError("arrangement slot mismatch")
    slots = sorted(source.keys())

    src_ids: Dict[int, Optional[int]] = {}
    id_to_entity: Dict[int, FreeEntity] = {}
    next_id = 0
    for s in slots:
        if source[s] is None:
            src_ids[s] = None
        else:
            src_ids[s] = next_id
            id_to_entity[next_id] = source[s]  # type: ignore
            next_id += 1

    used_ids: Set[int] = set()
    tgt_ids: Dict[int, Optional[int]] = {}
    for s in slots:
        if target[s] is None:
            tgt_ids[s] = None
            continue
        want = target[s].packed  # type: ignore
        chosen = None
        for sid, ent in id_to_entity.items():
            if sid in used_ids:
                continue
            if ent.packed == want:
                chosen = sid
                break
        if chosen is None:
            raise RuntimeError("target arrangement not same multiset")
        used_ids.add(chosen)
        tgt_ids[s] = chosen

    cur = dict(src_ids)
    moves: List[Action] = []

    def empties() -> List[int]:
        return sorted(s for s, v in cur.items() if v is None)

    def locate(iid: int) -> int:
        for s, v in cur.items():
            if v == iid:
                return s
        raise RuntimeError("token missing")

    def do_move(src: int, dest: int) -> None:
        iid = cur[src]
        assert iid is not None and cur[dest] is None
        ent = id_to_entity[iid]
        moves.append((src, dest, ent.height))
        cur[dest] = iid
        cur[src] = None

    max_steps = len(slots) * len(slots) * 8 + 32
    steps = 0
    while cur != tgt_ids and steps < max_steps:
        steps += 1
        e_list = empties()
        if not e_list:
            raise RuntimeError("no empty slot")
        # Prefer filling an empty whose target token is known (follows the blank)
        progressed = False
        for e in e_list:
            want = tgt_ids[e]
            if want is None:
                continue  # empty already home
            src = locate(want)
            do_move(src, e)
            progressed = True
            break
        if progressed:
            continue
        # All empties are home. Move any misplaced pile into an empty.
        for s in slots:
            if cur[s] is not None and cur[s] != tgt_ids[s]:
                do_move(s, e_list[0])
                progressed = True
                break
        if not progressed:
            break
    if cur != tgt_ids:
        raise RuntimeError("plan_free_rearrangement failed to converge")
    return moves


def apply_arrangement_moves(
    st: SpiderState, moves: Sequence[Action]
) -> SpiderState:
    st2 = st.clone()
    for a in moves:
        if not is_free_relocation(st2, a):
            raise ValueError(f"non-free move in free plan: {a}")
        apply_action(st2, a)
    return st2


# ---------------------------------------------------------------------------
# Brute-force oracle
# ---------------------------------------------------------------------------


def expand_component_bruteforce(
    representative: SpiderState,
    *,
    members: Optional[Dict[CanonicalStateKey, SpiderState]] = None,
) -> List[Dict[str, Any]]:
    """Oracle: Opt012 enumeration of all paid outs from every free member."""
    if members is None:
        members = free_closure(representative)
    best: Dict[bytes, Dict[str, Any]] = {}
    for st in members.values():
        for a, cost, st2 in _paid_successors(st):
            ck = component_key_from_state(st2).to_bytes()
            if ck not in best:
                best[ck] = {
                    "action": a,
                    "from_key": canonical_state_key(st),
                    "paid_cost": cost,
                    "succ_state": st2,
                    "succ_component_key": ck,
                    "backend": ORACLE_BACKEND_ID,
                }
    return list(best.values())


def _paid_successors(st: SpiderState) -> List[Tuple[Action, int, SpiderState]]:
    out: List[Tuple[Action, int, SpiderState]] = []
    for a in st.enumerate_moves():
        if a == ("deal",):
            continue
        s, d, k = a  # type: ignore
        cost = mobilityware_move_cost(
            cards_moved=k,
            source_face_up_count=len(st.columns[s].face_up),
            dest_was_empty=st.columns[d].is_empty(),
            source_face_down_count=len(st.columns[s].face_down),
        )
        if cost != 1:
            continue
        st2 = st.clone()
        try:
            apply_action(st2, a)
        except Exception:
            continue
        out.append((a, cost, st2))
    return out


# ---------------------------------------------------------------------------
# Algebraic paid expansion
# ---------------------------------------------------------------------------


def _legal_suffix_lengths(cards: Sequence[CardT]) -> List[int]:
    """Heights k such that the top-k cards form a legal desc run (engine rule)."""
    if not cards:
        return []
    # cards are bottom-to-top; top is last
    n = len(cards)
    ok = [1]
    for k in range(2, n + 1):
        run = cards[n - k :]
        good = all(run[j][1] - 1 == run[j + 1][1] for j in range(len(run) - 1))
        if good:
            ok.append(k)
        else:
            break
    return ok


def expand_component_algebraic(
    representative: SpiderState,
) -> List[Dict[str, Any]]:
    """Enumerate distinct paid successor components without full free-closure walk.

    Free orbit rule
    ---------------
    * ``n_empty == 0``: free-closure is a singleton.  Only the representative
      arrangement is legal; inventing permutations would leave the component.
    * ``n_empty >= 1``: empty-buffer free moves generate the full multiset
      orbit of free piles on free slots.  We materialise a covering set of
      labelled witnesses and enumerate paid moves from each.

    For each paid transition we retain a reconstructible free-path script from
    the representative to the pre-move labelled state (algebraic planner).
    """
    model = model_from_state(representative)
    piles = list(model.free_piles)
    slots = list(model.free_slots)
    arr_rep = arrangement_from_state(representative)

    best: Dict[bytes, Dict[str, Any]] = {}
    # Witness arrangements already expanded (exact signature of free assignment)
    seen_arr: Set[Tuple] = set()

    def record(
        st_pre: SpiderState,
        a: Action,
        st_post: SpiderState,
        arr_pre: Optional[Arrangement] = None,
    ) -> None:
        s, d, k = a  # type: ignore
        cost = mobilityware_move_cost(
            cards_moved=k,
            source_face_up_count=len(st_pre.columns[s].face_up),
            dest_was_empty=st_pre.columns[d].is_empty(),
            source_face_down_count=len(st_pre.columns[s].face_down),
        )
        if cost != 1:
            return
        ck = component_key_from_state(st_post).to_bytes()
        if ck in best:
            return
        if arr_pre is None:
            arr_pre = arrangement_from_state(st_pre)
        try:
            if model.n_empty >= 1 and set(arr_pre.keys()) == set(arr_rep.keys()):
                free_path = plan_free_rearrangement(arr_rep, arr_pre)
            elif arr_pre == arr_rep:
                free_path = []
            else:
                free_path = (
                    reconstruct_free_path(
                        representative, canonical_state_key(st_pre)
                    )
                    or []
                )
        except Exception:
            free_path = (
                reconstruct_free_path(representative, canonical_state_key(st_pre))
                or []
            )
        best[ck] = {
            "action": a,
            "from_key": canonical_state_key(st_pre),
            "paid_cost": cost,
            "succ_state": st_post,
            "succ_component_key": ck,
            "free_path": free_path,
            "backend": BACKEND_ID,
        }

    def try_all_paid_from(st: SpiderState, arr_pre: Optional[Arrangement] = None) -> None:
        for a in st.enumerate_moves():
            if a == ("deal",):
                continue
            s, d, k = a  # type: ignore
            cost = mobilityware_move_cost(
                cards_moved=k,
                source_face_up_count=len(st.columns[s].face_up),
                dest_was_empty=st.columns[d].is_empty(),
                source_face_down_count=len(st.columns[s].face_down),
            )
            if cost != 1:
                continue
            st2 = st.clone()
            try:
                apply_action(st2, a)
            except Exception:
                continue
            record(st, a, st2, arr_pre=arr_pre)

    def expand_arrangement(arr: Arrangement) -> None:
        sig = _arrangement_signature(model, arr)
        if sig in seen_arr:
            return
        seen_arr.add(sig)
        st = build_state_from_arrangement(model, arr, representative)
        try_all_paid_from(st, arr_pre=arr)

    # ----- n_empty == 0: singleton free component -----
    if model.n_empty == 0 or not slots:
        try_all_paid_from(representative, arr_pre=arr_rep)
        return list(best.values())

    # ----- n_empty >= 1: covering free-orbit witnesses -----
    # 1) Canonical arrangement
    expand_arrangement(canonical_arrangement(model))

    # 2) Free-pile sources at each free slot with a dedicated empty elsewhere
    seen_pile: Set[bytes] = set()
    for p in piles:
        if p.packed in seen_pile:
            continue
        seen_pile.add(p.packed)
        for src_slot in slots:
            for empty_slot in slots:
                if empty_slot == src_slot:
                    continue
                rest: List[FreeEntity] = []
                removed = False
                for x in piles:
                    if not removed and x.packed == p.packed:
                        removed = True
                        continue
                    rest.append(x)
                arr: Arrangement = {s: None for s in slots}
                arr[src_slot] = p
                arr[empty_slot] = None
                other_slots = [s for s in slots if s not in (src_slot, empty_slot)]
                for s, ent in zip(other_slots, rest):
                    arr[s] = ent
                expand_arrangement(arr)

    # 3) Each free pile forced onto each free slot as destination
    for dest_slot in slots:
        seen_dest: Set[bytes] = set()
        for p in piles:
            if p.packed in seen_dest:
                continue
            seen_dest.add(p.packed)
            rest = []
            removed = False
            for x in piles:
                if not removed and x.packed == p.packed:
                    removed = True
                    continue
                rest.append(x)
            arr = {s: None for s in slots}
            arr[dest_slot] = p
            others = [s for s in slots if s != dest_slot]
            for s, ent in zip(others, rest):
                arr[s] = ent
            expand_arrangement(arr)

    # 4) Representative arrangement
    expand_arrangement(arr_rep)

    return list(best.values())


def successor_key_set(records: Sequence[Dict[str, Any]]) -> Set[bytes]:
    return {r["succ_component_key"] for r in records}


def differential_expand(representative: SpiderState) -> Dict[str, Any]:
    """Compare algebraic vs bruteforce successor sets."""
    members = free_closure(representative)
    brute = expand_component_bruteforce(representative, members=members)
    alg = expand_component_algebraic(representative)
    sb, sa = successor_key_set(brute), successor_key_set(alg)
    return {
        "equal": sb == sa,
        "brute_n": len(sb),
        "alg_n": len(sa),
        "only_brute": len(sb - sa),
        "only_alg": len(sa - sb),
        "only_brute_keys": list(sb - sa)[:5],
        "only_alg_keys": list(sa - sb)[:5],
        "brute_keys": sb,
        "alg_keys": sa,
    }


def prove_all_arrangements_reachable(start: SpiderState) -> Dict[str, Any]:
    """Prove algebraic free planner reaches every free-closure member from start."""
    members = free_closure(start)
    arr0 = arrangement_from_state(start)
    fails = 0
    for st in members.values():
        path = plan_free_rearrangement(arr0, arrangement_from_state(st))
        st2 = apply_arrangement_moves(start, path)
        if canonical_state_key(st2) != canonical_state_key(st):
            fails += 1
    return {
        "n_members": len(members),
        "fails": fails,
        "ok": fails == 0 and len(members) == 720,
    }


def collect_components_through_ceiling(
    *,
    ceiling: int,
    expand_mode: str = "algebraic",
) -> List[SpiderState]:
    """Return one representative state per quotient component found at paid cost <= ceiling."""
    from spider.planner.diagnostics.opt012_compact_search import search_quotient
    from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
        build_corridor_endpoints,
    )
    from spider.packed_state import unpack_state

    # Lightweight collection by re-running search internals via public search_quotient
    # and re-expanding each layer — use search that stores reps.
    # Simpler: BFS ourselves with algebraic expand.
    from spider.planner.diagnostics.opt012_pruning import TargetMonotonicFilter

    ep = build_corridor_endpoints()
    start = ep["start_state"]
    target = ep["target_state"]
    filt = TargetMonotonicFilter(target=target, start=start, cost_ceiling=ceiling)
    start_ck = component_key_from_state(start).to_bytes()
    reps: Dict[bytes, SpiderState] = {start_ck: start.clone()}
    # layer by paid cost
    frontier = {start_ck}
    for cost in range(ceiling):
        nxt: Set[bytes] = set()
        for ck in frontier:
            rep = reps[ck]
            if expand_mode == "bruteforce":
                outs = expand_component_bruteforce(rep)
            else:
                outs = expand_component_algebraic(rep)
            for rec in outs:
                st2 = rec["succ_state"]
                if not filt.accept(st2, current_cost=cost + 1):
                    continue
                ck2 = rec["succ_component_key"]
                if ck2 not in reps:
                    m2 = model_from_state(st2)
                    if m2.n_empty == 0:
                        reps[ck2] = st2.clone()
                    else:
                        reps[ck2] = build_state_from_arrangement(
                            m2, canonical_arrangement(m2), st2
                        )
                    nxt.add(ck2)
        frontier = nxt
    return list(reps.values())


def differential_corpus_through_ceiling(ceiling: int = 6) -> Dict[str, Any]:
    """Full differential: every component through ``ceiling``."""
    reps = collect_components_through_ceiling(ceiling=ceiling, expand_mode="algebraic")
    mismatches = []
    for i, rep in enumerate(reps):
        d = differential_expand(rep)
        if not d["equal"]:
            mismatches.append(
                {
                    "index": i,
                    "only_brute": d["only_brute"],
                    "only_alg": d["only_alg"],
                    "brute_n": d["brute_n"],
                    "alg_n": d["alg_n"],
                }
            )
    return {
        "n_components": len(reps),
        "mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }
