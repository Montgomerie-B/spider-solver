"""Versioned packed exact structural state for Opt012.

Binary layout (version 1):
  magic(4) | version(u8) | n_foundations(u8) | n_stock(u16)
  for each of 10 columns:
    n_fd(u8) | n_fu(u8) | cards...
  each card: suit(u2 in low bits)+rank(u4) packed as u8: (suit_idx<<4)|rank
  stock cards...
  foundation sequences: each n(u8)+cards..., order sorted for canonicity

Authoritative equality is exact bytes equality.
"""

from __future__ import annotations

import struct
from typing import List, Sequence, Tuple

from .cards import Card
from .engine import Column, SpiderState
from .state_identity import CanonicalStateKey, card_tuple, canonical_state_key

PACKED_MAGIC = b"SPK1"
PACKED_VERSION = 1
SUIT_IDX = {"s": 0, "h": 1, "d": 2, "c": 3}
IDX_SUIT = "shdc"


def _enc_card(c: Card) -> int:
    return (SUIT_IDX[c.suit] << 4) | (c.rank & 0x0F)


def _dec_card(b: int) -> Card:
    return Card(IDX_SUIT[(b >> 4) & 0x3], b & 0x0F)


def pack_state(state: SpiderState) -> bytes:
    """Pack SpiderState into immutable exact key bytes."""
    parts: List[bytes] = [PACKED_MAGIC, bytes([PACKED_VERSION])]
    found = sorted(
        [tuple(card_tuple(c) for c in seq) for seq in state.foundations]
    )
    parts.append(bytes([len(found)]))
    parts.append(struct.pack(">H", len(state.stock)))
    for col in state.columns:
        n_fd = len(col.face_down)
        n_fu = len(col.face_up)
        if n_fd > 255 or n_fu > 255:
            raise ValueError("column too deep for u8 packing")
        parts.append(bytes([n_fd, n_fu]))
        parts.append(bytes(_enc_card(c) for c in col.face_down))
        parts.append(bytes(_enc_card(c) for c in col.face_up))
    parts.append(bytes(_enc_card(c) for c in state.stock))
    for seq in found:
        parts.append(bytes([len(seq)]))
        parts.append(bytes((SUIT_IDX[s] << 4) | (r & 0x0F) for s, r in seq))
    return b"".join(parts)


def pack_canonical_key(key: CanonicalStateKey) -> bytes:
    """Pack already-canonical key without building SpiderState."""
    parts: List[bytes] = [PACKED_MAGIC, bytes([PACKED_VERSION])]
    parts.append(bytes([len(key.foundations)]))
    parts.append(struct.pack(">H", len(key.stock)))
    for fd, fu in key.columns:
        parts.append(bytes([len(fd), len(fu)]))
        parts.append(bytes((SUIT_IDX[s] << 4) | (r & 0x0F) for s, r in fd))
        parts.append(bytes((SUIT_IDX[s] << 4) | (r & 0x0F) for s, r in fu))
    parts.append(bytes((SUIT_IDX[s] << 4) | (r & 0x0F) for s, r in key.stock))
    for seq in key.foundations:
        parts.append(bytes([len(seq)]))
        parts.append(bytes((SUIT_IDX[s] << 4) | (r & 0x0F) for s, r in seq))
    return b"".join(parts)


def unpack_state(blob: bytes) -> SpiderState:
    if blob[:4] != PACKED_MAGIC:
        raise ValueError("bad packed magic")
    ver = blob[4]
    if ver != PACKED_VERSION:
        raise ValueError(f"unsupported packed version {ver}")
    n_found = blob[5]
    n_stock = struct.unpack_from(">H", blob, 6)[0]
    i = 8
    columns: List[Column] = []
    for _ in range(10):
        n_fd = blob[i]
        n_fu = blob[i + 1]
        i += 2
        fd = [_dec_card(blob[i + j]) for j in range(n_fd)]
        i += n_fd
        fu = [_dec_card(blob[i + j]) for j in range(n_fu)]
        i += n_fu
        columns.append(Column(fd, fu))
    stock = [_dec_card(blob[i + j]) for j in range(n_stock)]
    i += n_stock
    foundations: List[List[Card]] = []
    for _ in range(n_found):
        n = blob[i]
        i += 1
        foundations.append([_dec_card(blob[i + j]) for j in range(n)])
        i += n
    return SpiderState(columns, stock, foundations)


def packed_roundtrip_ok(state: SpiderState) -> bool:
    blob = pack_state(state)
    st2 = unpack_state(blob)
    return pack_state(st2) == blob and canonical_state_key(state) == canonical_state_key(st2)
