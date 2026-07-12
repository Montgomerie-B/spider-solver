"""Exact zero-cost free-relocation quotient for Opt012 corridor search.

A free relocation (corrected MobilityWare cost 0) moves an entire face-up
column with no face-down cards onto an empty column. Under target-compatible
corridor conditions these moves form a reversible permutation group on the
set of {complete open free piles} ∪ {empty slots}.

The command-42 free closure has size 6! = 720 = one component of 5 free
piles + 1 empty.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state
from spider.rules import mobilityware_move_cost
from spider.state_identity import CanonicalStateKey, canonical_state_key

# Column index with face-up cards fully open (no face-down) that form one
# legal movable unit for free relocation (entire face_up).
FreePile = Tuple[Tuple[Tuple[str, int], ...], ...]  # just the face_up cards as tuples


def is_free_relocation(st: SpiderState, a: Action) -> bool:
    """True iff tableau move is corrected cost 0 under MW rules."""
    if a == ("deal",):
        return False
    s, d, k = a  # type: ignore
    return (
        mobilityware_move_cost(
            cards_moved=k,
            source_face_up_count=len(st.columns[s].face_up),
            dest_was_empty=st.columns[d].is_empty(),
            source_face_down_count=len(st.columns[s].face_down),
        )
        == 0
    )


def free_moves(st: SpiderState) -> List[Action]:
    out: List[Action] = []
    for a in st.enumerate_moves():
        if is_free_relocation(st, a):
            out.append(a)
    return out


def apply_action(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
        return st.deal()
    s, d, k = a  # type: ignore
    return st.move(s, d, k)


def free_closure(start: SpiderState) -> Dict[CanonicalStateKey, SpiderState]:
    """Brute-force zero-cost connected component as key → representative."""
    sk = canonical_state_key(start)
    members: Dict[CanonicalStateKey, SpiderState] = {sk: start.clone()}
    dq: deque[SpiderState] = deque([start.clone()])
    while dq:
        u = dq.popleft()
        for a in free_moves(u):
            v = u.clone()
            apply_action(v, a)
            k = canonical_state_key(v)
            if k not in members:
                members[k] = v
                dq.append(v)
    return members


def free_slot_analysis(st: SpiderState) -> Dict[str, Any]:
    """Classify columns into fixed vs freely permutable slots."""
    free_indices: List[int] = []
    free_piles: List[Tuple[Tuple[str, int], ...]] = []
    empty_indices: List[int] = []
    fixed: List[int] = []
    for i, col in enumerate(st.columns):
        if col.is_empty():
            empty_indices.append(i)
            free_indices.append(i)
        elif len(col.face_down) == 0 and len(col.face_up) > 0:
            # entire open column is free-relocatable iff free move exists to some empty
            # Characterisation: no face-down + can move full face_up as unit (desc run)
            fu = col.face_up
            is_run = all(fu[j].rank - 1 == fu[j + 1].rank for j in range(len(fu) - 1))
            if is_run:
                free_indices.append(i)
                free_piles.append(tuple((c.suit, c.rank) for c in fu))
            else:
                fixed.append(i)
        else:
            fixed.append(i)
    return {
        "free_indices": free_indices,
        "empty_indices": empty_indices,
        "free_piles": free_piles,
        "fixed_indices": fixed,
        "n_slots": len(free_indices),
        "n_piles": len(free_piles),
        "n_empty": len(empty_indices),
        "factorial_slots": math.factorial(len(free_indices))
        if len(free_indices) <= 12
        else None,
    }


@dataclass(frozen=True)
class ComponentKey:
    """Exact quotient identity for a zero-cost free-relocation component.

    Fixed columns are stored packed-by-index. Free piles are a sorted multiset
    (as packed card sequences) plus empty slot count; free column indices are
    the invariant set of slots.
    """

    packed_fixed: bytes  # concatenation of (col_index, packed column content)
    free_slot_indices: Tuple[int, ...]  # sorted
    free_pile_multiset: Tuple[bytes, ...]  # sorted packed face-up sequences
    n_empty: int
    packed_stock: bytes
    packed_foundations: bytes

    def to_bytes(self) -> bytes:
        # Versioned compact key for dict / checkpoint
        parts = [
            b"CQ01",
            bytes([len(self.free_slot_indices), self.n_empty]),
            bytes(self.free_slot_indices),
            struct_pack_u32(len(self.free_pile_multiset)),
        ]
        for p in self.free_pile_multiset:
            parts.append(struct_pack_u16(len(p)))
            parts.append(p)
        parts.append(struct_pack_u32(len(self.packed_fixed)))
        parts.append(self.packed_fixed)
        parts.append(struct_pack_u16(len(self.packed_stock)))
        parts.append(self.packed_stock)
        parts.append(struct_pack_u16(len(self.packed_foundations)))
        parts.append(self.packed_foundations)
        return b"".join(parts)


def struct_pack_u16(n: int) -> bytes:
    return bytes([(n >> 8) & 0xFF, n & 0xFF])


def struct_pack_u32(n: int) -> bytes:
    return bytes([(n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])


def _pack_cards(cards: Sequence) -> bytes:
    from spider.packed_state import SUIT_IDX

    out = bytearray()
    for c in cards:
        if hasattr(c, "suit"):
            out.append((SUIT_IDX[c.suit] << 4) | (c.rank & 0x0F))
        else:
            s, r = c
            out.append((SUIT_IDX[s] << 4) | (r & 0x0F))
    return bytes(out)


def component_key_from_state(st: SpiderState) -> ComponentKey:
    analysis = free_slot_analysis(st)
    free_set = set(analysis["free_indices"])
    fixed_parts = bytearray()
    for i, col in enumerate(st.columns):
        if i in free_set:
            continue
        fixed_parts.append(i)
        fixed_parts.append(len(col.face_down))
        fixed_parts.append(len(col.face_up))
        fixed_parts.extend(_pack_cards(col.face_down))
        fixed_parts.extend(_pack_cards(col.face_up))
    piles = sorted(_pack_cards(p) for p in analysis["free_piles"])
    stock = _pack_cards(st.stock)
    found = sorted(
        _pack_cards([(c.suit, c.rank) for c in seq]) for seq in st.foundations
    )
    found_blob = bytearray()
    for f in found:
        found_blob.append(len(f))
        found_blob.extend(f)
    return ComponentKey(
        packed_fixed=bytes(fixed_parts),
        free_slot_indices=tuple(sorted(analysis["free_indices"])),
        free_pile_multiset=tuple(piles),
        n_empty=int(analysis["n_empty"]),
        packed_stock=stock,
        packed_foundations=bytes(found_blob),
    )


def free_move_reversible(st: SpiderState, a: Action) -> bool:
    """Prove reversibility of a free relocation: move back to original empty."""
    if not is_free_relocation(st, a):
        return False
    s, d, k = a  # type: ignore
    st2 = st.clone()
    apply_action(st2, a)
    # reverse: from d back to s (now empty) with same k
    rev = (d, s, k)
    if not is_free_relocation(st2, rev):
        return False
    st3 = st2.clone()
    apply_action(st3, rev)
    return canonical_state_key(st3) == canonical_state_key(st)


def all_free_moves_reversible_in_component(start: SpiderState) -> Tuple[bool, Optional[str]]:
    members = free_closure(start)
    for st in members.values():
        for a in free_moves(st):
            if not free_move_reversible(st, a):
                return False, f"irreversible free move {a} from state"
    return True, None


def paid_successors(
    st: SpiderState, *, allow_deals: bool = False
) -> List[Tuple[Action, int, SpiderState]]:
    """Legal moves with corrected cost 1 (and optionally deals)."""
    out: List[Tuple[Action, int, SpiderState]] = []
    for a in st.enumerate_moves():
        if a == ("deal",) and not allow_deals:
            continue
        cost = (
            1
            if a == ("deal",)
            else mobilityware_move_cost(
                cards_moved=a[2],  # type: ignore
                source_face_up_count=len(st.columns[a[0]].face_up),  # type: ignore
                dest_was_empty=st.columns[a[1]].is_empty(),  # type: ignore
                source_face_down_count=len(st.columns[a[0]].face_down),  # type: ignore
            )
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


def expand_component_paid(
    representative: SpiderState,
    *,
    members: Optional[Dict[CanonicalStateKey, SpiderState]] = None,
) -> List[Dict[str, Any]]:
    """All distinct paid transitions out of a free component.

    Returns list of {action, pre_free_path, paid_cost, succ_state, succ_component_key}.
    pre_free_path is empty when expanding all members explicitly.
    """
    if members is None:
        members = free_closure(representative)
    # Map successor component -> best transition record
    best: Dict[bytes, Dict[str, Any]] = {}
    for st in members.values():
        # free path from representative is reconstructed later if needed;
        # for expansion we store the actual pre-state key
        for a, cost, st2 in paid_successors(st):
            ck = component_key_from_state(st2).to_bytes()
            rec = {
                "action": a,
                "from_key": canonical_state_key(st),
                "paid_cost": cost,
                "succ_state": st2,
                "succ_component_key": ck,
                "succ_component": component_key_from_state(st2),
            }
            # dedupe by successor component (any pre-state is fine for reachability)
            if ck not in best:
                best[ck] = rec
    return list(best.values())


def reconstruct_free_path(
    start: SpiderState, goal_key: CanonicalStateKey
) -> Optional[List[Action]]:
    """BFS free-only path from start to a state with goal_key."""
    sk = canonical_state_key(start)
    if sk == goal_key:
        return []
    parent: Dict[CanonicalStateKey, Tuple[CanonicalStateKey, Action]] = {}
    seen = {sk}
    dq: deque[SpiderState] = deque([start.clone()])
    key_of: Dict[CanonicalStateKey, SpiderState] = {sk: start}
    while dq:
        u = dq.popleft()
        uk = canonical_state_key(u)
        for a in free_moves(u):
            v = u.clone()
            apply_action(v, a)
            vk = canonical_state_key(v)
            if vk in seen:
                continue
            seen.add(vk)
            parent[vk] = (uk, a)
            key_of[vk] = v
            if vk == goal_key:
                # reconstruct
                path: List[Action] = []
                cur = vk
                while cur in parent:
                    p, act = parent[cur]
                    path.append(act)
                    cur = p
                path.reverse()
                return path
            dq.append(v)
    return None
