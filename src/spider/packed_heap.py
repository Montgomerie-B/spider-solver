"""Order-preserving packed keys for the seven suit-search lanes.

Each heap item is one integer. Its high bits are the lane key and its low
bits are the same monotonic tie sequence the reference tuples use. Stale
entries stay until they are popped, so round-robin does not change.

A component outside the recorded limits raises ``PackedKeyOverflow``. The
search stops instead of silently changing which node expands next.
"""

from __future__ import annotations

from typing import Sequence, Tuple

# 67,108,864 pushes. The 100k opening used about 710,000.
SEQ_BITS = 26
SEQ_MASK = (1 << SEQ_BITS) - 1

# Inclusive bounds with headroom over the 100,000-identity opening sample.
# foundation score reached -4854, bonds -55, corrected cost 141, foundations -4.
_LANE_LIMITS = {
    "cost": ((0, 4095),),
    "foundation": ((-15, 0), (-65535, 0), (0, 255), (0, 15), (0, 4095)),
    "reveal": ((0, 255), (-15, 0), (-15, 0), (0, 4095)),
    "workspace": ((-15, 0), (0, 255), (-255, 0), (0, 4095)),
    "construction": ((-255, 0), (-31, 0), (-511, 0), (0, 255), (0, 4095)),
    "prep": ((-15, 0), (0, 255), (-255, 0), (-15, 0), (0, 4095)),
    "epoch": ((0, 15), (-15, 0), (0, 255), (0, 4095)),
}


class PackedKeyOverflow(ValueError):
    """A lane key or tie sequence does not fit the order-preserving packing."""


def _widths(limits: Sequence[Tuple[int, int]]) -> Tuple[Tuple[int, int], ...]:
    spec = []
    for low, high in limits:
        if high < low:
            raise ValueError(f"empty key range {low}..{high}")
        span = high - low + 1
        spec.append((int(low), (span - 1).bit_length()))
    return tuple(spec)


_SPECS = {name: _widths(limits) for name, limits in _LANE_LIMITS.items()}


def pack_lane_key(lane: str, key: Sequence[int], seq: int) -> int:
    """Pack one lane key and its tie sequence. Smaller tuples stay smaller."""

    spec = _SPECS.get(lane)
    if spec is None:
        raise PackedKeyOverflow(f"lane {lane!r} has no packed layout")
    if len(key) != len(spec):
        raise PackedKeyOverflow(f"lane {lane!r} expected {len(spec)} components, got {len(key)}")
    if seq < 0 or seq > SEQ_MASK:
        raise PackedKeyOverflow(f"tie sequence {seq} is outside 0..{SEQ_MASK}")
    packed = 0
    for value, (low, width) in zip(key, spec):
        shifted = int(value) - low
        if shifted < 0 or shifted >= (1 << width):
            raise PackedKeyOverflow(f"lane {lane!r} component {int(value)} is outside the packed range")
        packed = (packed << width) | shifted
    return (packed << SEQ_BITS) | int(seq)


def unpack_lane_key(lane: str, packed: int) -> Tuple[Tuple[int, ...], int]:
    """Inverse of ``pack_lane_key``. Used by tests and retained-memory reports."""

    spec = _SPECS.get(lane)
    if spec is None:
        raise PackedKeyOverflow(f"lane {lane!r} has no packed layout")
    seq = int(packed) & SEQ_MASK
    rest = int(packed) >> SEQ_BITS
    components = []
    for low, width in reversed(spec):
        components.append((rest & ((1 << width) - 1)) + low)
        rest >>= width
    components.reverse()
    return tuple(components), seq
