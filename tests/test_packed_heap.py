"""Packed lane keys keep tuple order. These tests do not run a search."""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.packed_heap import PackedKeyOverflow, pack_lane_key, unpack_lane_key
from spider.packed_state import pack_state
from spider.research_actions import opening_from_deal
from spider.global_search_experiment import suit_lane_keys

DEAL = ROOT / "deals" / "4925153.txt"


def _assert_same_order(lane: str, keys):
    packed = [(pack_lane_key(lane, key, seq), key, seq) for seq, key in enumerate(keys)]
    by_tuple = sorted(packed, key=lambda item: (item[1], item[2]))
    by_int = sorted(packed, key=lambda item: item[0])
    assert [item[0] for item in by_tuple] == [item[0] for item in by_int]


def test_pack_matches_tuple_order_inside_each_lane():
    ranges = {
        "cost": [(0, 3)],
        "foundation": [(-2, 0), (-40, 0), (0, 3), (0, 2), (0, 3)],
        "reveal": [(0, 3), (-2, 0), (-2, 0), (0, 3)],
        "workspace": [(-2, 0), (0, 3), (-3, 0), (0, 3)],
        "construction": [(-3, 0), (-2, 0), (-3, 0), (0, 3), (0, 3)],
        "prep": [(-2, 0), (0, 3), (-3, 0), (-2, 0), (0, 3)],
        "epoch": [(0, 2), (-2, 0), (0, 3), (0, 3)],
    }
    for lane, bounds in ranges.items():
        space = [list(range(low, high + 1)) for low, high in bounds]
        keys = list(itertools.product(*space))
        _assert_same_order(lane, keys)
        for key in keys:
            packed = pack_lane_key(lane, key, 7)
            assert unpack_lane_key(lane, packed) == (tuple(key), 7)


def test_equal_keys_keep_the_earlier_tie_sequence_first():
    earlier = pack_lane_key("cost", (4,), 10)
    later = pack_lane_key("cost", (4,), 11)
    assert earlier < later


def test_out_of_range_component_raises_instead_of_reordering():
    try:
        pack_lane_key("foundation", (0, -65536, 0, 0, 0), 1)
    except PackedKeyOverflow:
        return
    raise AssertionError("an out-of-range score was packed")


def test_opening_suit_keys_round_trip():
    state = opening_from_deal(DEAL)
    keys = suit_lane_keys(state, 0)
    assert pack_state(state).startswith(b"SPK1")
    for lane, key in keys.items():
        packed = pack_lane_key(lane, key, 3)
        assert unpack_lane_key(lane, packed) == (tuple(key), 3)
        assert packed < pack_lane_key(lane, key, 4)


def test_random_keys_match_tuple_order():
    rng = random.Random(4925153)
    for _ in range(200):
        key_a = (
            rng.randint(-255, 0),
            rng.randint(-31, 0),
            rng.randint(-511, 0),
            rng.randint(0, 255),
            rng.randint(0, 4095),
        )
        key_b = (
            rng.randint(-255, 0),
            rng.randint(-31, 0),
            rng.randint(-511, 0),
            rng.randint(0, 255),
            rng.randint(0, 4095),
        )
        seq_a = rng.randint(0, 1000)
        seq_b = rng.randint(0, 1000)
        packed_a = pack_lane_key("construction", key_a, seq_a)
        packed_b = pack_lane_key("construction", key_b, seq_b)
        assert (packed_a < packed_b) == ((key_a, seq_a) < (key_b, seq_b))
