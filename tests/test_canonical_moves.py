"""Replay tests for solutions/4925153_canonical.moves."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState

CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
DEAL = ROOT / "deals" / "4925153.txt"

DEAL1_TOPS = ["Js", "9d", "4d", "Kh", "4d", "6d", "9s", "7d", "8s", "5c"]
DEAL2_TOPS = ["Ks", "As", "6h", "7s", "Ad", "Ad", "Ah", "10d", "Qh", "Jd"]
DEAL3_TOPS = ["2c", "10s", "Qd", "Kh", "8h", "9c", "3s", "5s", "5d", "4h"]
AFTER_SECTION_D_TOPS = ["6d", "6d", "6h", "Qh", "6s", "Ad", "Ah", "Ad", "4c", "10d"]
AFTER_SECTION_F_TOPS = ["Ad", "6d", "10d", "Kh", "2s", "8h", "Ah", "4h", "4c", "10s"]
DEAL4_TOPS = ["9d", "Js", "Qh", "2d", "4c", "Qc", "Kc", "8c", "Jh", "9s"]
AFTER_SECTION_H_TOPS = ["8h", "Jh", "4h", "Ah", "2c", "8c", "2s", "4c", "4c", "6d"]
DEAL5_TOPS = ["3h", "10h", "2d", "3c", "9h", "7c", "7h", "As", "3c", "5d"]
AFTER_DEAL5_MOVE1_TOPS = ["3h", "9h", "2d", "3c", "2c", "7c", "7h", "As", "3c", "5d"]
AFTER_DEAL5_MOVE2_TOPS = ["3h", "9h", "2d", "3c", None, "7c", "7h", "As", "2c", "5d"]
AFTER_DEAL5_MOVE3_TOPS = ["3h", "9h", "2d", "3c", "7h", "7c", "2s", "As", "2c", "5d"]
AFTER_DEAL5_MOVE4_TOPS = ["3h", "9h", "2d", "3c", "7h", "7c", "As", "4c", "2c", "5d"]
AFTER_DEAL5_MOVE5_TOPS = ["3h", "9h", "2d", "3c", "7h", "4c", "As", None, "2c", "5d"]
AFTER_DEAL5_MOVE6_TOPS = ["3h", "9h", "2d", "Ah", "7h", "3c", "As", None, "2c", "5d"]
AFTER_DEAL5_MOVE7_TOPS = ["Ah", "9h", "2d", "Ac", "7h", "3c", "As", None, "2c", "5d"]  # col 8 empty
AFTER_DEAL5_MOVE8_TOPS = ["Ah", "9h", "2d", None, "7h", "3c", "As", None, None, "5d"]
AFTER_DEAL5_MOVE9_TOPS = ["Ah", "9h", "4h", "2d", "7h", "3c", "As", None, None, "5d"]
AFTER_DEAL5_MOVE10_TOPS = ["Ah", "9h", "Ac", "2d", "4h", "3c", "As", None, None, "5d"]
AFTER_DEAL5_MOVE11_TOPS = ["8h", "9h", "Ac", "2d", "Ah", "3c", "As", None, None, "5d"]
AFTER_DEAL5_MOVE12_TOPS = ["8h", "9h", "3d", "2d", "Ah", "Ac", "As", None, None, "5d"]
AFTER_DEAL5_MOVE13_TOPS = ["8h", "9h", "2d", None, "Ah", "Ac", "As", None, None, "5d"]
AFTER_DEAL5_MOVE14_TOPS = ["8h", "9h", "2d", None, "Ah", "Ad", "As", "Ac", None, "5d"]
AFTER_DEAL5_MOVE15_TOPS = ["8h", "9h", "Ad", None, "Ah", "10c", "As", "Ac", None, "5d"]
AFTER_DEAL5_MOVE16_TOPS = ["8h", "9h", "Ad", None, "Ah", "Ac", "As", None, None, "5d"]
AFTER_DEAL5_MOVE17_TOPS = ["8h", "9h", "Ad", "Ac", "Ah", "Qs", "As", None, None, "5d"]  # cols 8-9 empty
AFTER_DEAL5_MOVE18_TOPS = ["8h", "9h", None, "Ac", "Ah", "Qs", "As", None, None, None]
AFTER_DEAL5_MOVE19_TOPS = ["8h", "9h", None, "Ac", "Ah", None, "Qc", None, None, None]
AFTER_DEAL5_MOVE20_TOPS = ["8h", "9h", None, None, "Ah", None, "Ah", None, None, None]
AFTER_DEAL5_MOVE21_TOPS = ["8h", None, None, None, "Ah", None, None, None, None, None]


def _replay(path: Path, stop_after_deal: int | None = None) -> SpiderState:
    state = SpiderState.from_cards(load_deal(DEAL))
    deal_n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "move":
            state.move(int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
        elif parts[0] == "deal":
            state.deal()
            deal_n += 1
            if deal_n == 1:
                assert [str(c) for c in state.top_row()] == DEAL1_TOPS
            elif deal_n == 2:
                assert [str(c) for c in state.top_row()] == DEAL2_TOPS
            elif deal_n == 3:
                assert [str(c) for c in state.top_row()] == DEAL3_TOPS
            elif deal_n == 4:
                assert [str(c) for c in state.top_row()] == DEAL4_TOPS
            elif deal_n == 5:
                assert [str(c) for c in state.top_row()] == DEAL5_TOPS
            if stop_after_deal is not None and deal_n >= stop_after_deal:
                break
    return state


def test_canonical_file_exists():
    assert CANONICAL.is_file()


def test_canonical_replay_through_deal2():
    state = _replay(CANONICAL, stop_after_deal=2)
    assert [str(c) for c in state.top_row()] == DEAL2_TOPS
    assert len(state.stock) == 30


def _replay_until_marker(path: Path, marker: str) -> SpiderState:
    """Replay until line containing marker in a comment (e.g. '# --- D:')."""
    state = SpiderState.from_cards(load_deal(DEAL))
    for line in path.read_text(encoding="utf-8").splitlines():
        if marker in line:
            break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "move":
            state.move(int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
        elif parts[0] == "deal":
            state.deal()
    return state


def test_canonical_replay_through_section_d():
    state = _replay_until_marker(CANONICAL, "# --- E:")
    assert [str(c) for c in state.top_row()] == AFTER_SECTION_D_TOPS
    assert len(state.foundations) == 1
    assert len(state.foundations[0]) == 13
    assert len(state.stock) == 30


def test_canonical_replay_through_section_f():
    state = _replay_until_marker(CANONICAL, "# --- G:")
    assert [str(c) for c in state.top_row()] == AFTER_SECTION_F_TOPS
    assert len(state.foundations) == 1
    assert len(state.foundations[0]) == 13
    assert len(state.stock) == 20


def test_canonical_replay_through_section_h():
    state = _replay_until_marker(CANONICAL, "# --- I:")
    assert [str(c) for c in state.top_row()] == AFTER_SECTION_H_TOPS
    assert len(state.foundations) == 2
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 10


def test_canonical_replay_through_deal5_move1():
    state = _replay_section_j_moves(1)
    assert [str(c) for c in state.top_row()] == AFTER_DEAL5_MOVE1_TOPS

def _replay_section_j_moves(n: int) -> SpiderState:
    state = SpiderState.from_cards(load_deal(DEAL))
    in_j = False
    j_moves = 0
    for line in CANONICAL.read_text(encoding="utf-8").splitlines():
        if "# --- J:" in line:
            in_j = True
            continue
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "move":
            if in_j:
                state.move(int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
                j_moves += 1
                if j_moves >= n:
                    return state
            else:
                state.move(int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
        elif parts[0] == "deal":
            state.deal()
    return state


def test_canonical_replay_through_deal5_move2():
    state = _replay_section_j_moves(2)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE2_TOPS
    assert len(state.foundations) == 2
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move3():
    state = _replay_section_j_moves(3)
    assert [str(c) for c in state.top_row()] == AFTER_DEAL5_MOVE3_TOPS
    assert len(state.foundations) == 2
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move4():
    state = _replay_section_j_moves(4)
    assert [str(c) for c in state.top_row()] == AFTER_DEAL5_MOVE4_TOPS
    assert len(state.foundations) == 2
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move5():
    state = _replay_section_j_moves(5)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE5_TOPS
    assert len(state.foundations) == 2
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move6():
    state = _replay_section_j_moves(6)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE6_TOPS
    assert len(state.foundations) == 2
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move7():
    state = _replay_section_j_moves(7)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE7_TOPS
    assert str(state.columns[3].face_up[-1]) == "Ac"
    assert len(state.foundations) == 2
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move8():
    state = _replay_section_j_moves(8)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE8_TOPS
    assert len(state.foundations) == 3
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move9():
    state = _replay_section_j_moves(9)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE9_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move10():
    state = _replay_section_j_moves(10)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE10_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move11():
    state = _replay_section_j_moves(11)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE11_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move12():
    state = _replay_section_j_moves(12)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE12_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move13():
    state = _replay_section_j_moves(13)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE13_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move14():
    state = _replay_section_j_moves(14)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE14_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move15():
    state = _replay_section_j_moves(15)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE15_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move16():
    state = _replay_section_j_moves(16)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE16_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move17():
    state = _replay_section_j_moves(17)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE17_TOPS
    assert len(state.foundations) == 3
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move18():
    state = _replay_section_j_moves(18)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE18_TOPS
    assert len(state.foundations) == 4
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move19():
    state = _replay_section_j_moves(19)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE19_TOPS
    assert len(state.foundations) == 5
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move20():
    state = _replay_section_j_moves(20)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE20_TOPS
    assert len(state.foundations) == 6
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 0


def test_canonical_replay_through_deal5_move21():
    state = _replay_section_j_moves(21)
    tops = [str(c) if c else None for c in state.top_row()]
    assert tops == AFTER_DEAL5_MOVE21_TOPS
    assert len(state.foundations) == 7
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 0


def test_canonical_game_won_after_deal5_move22():
    state = _replay(CANONICAL)
    assert all(c is None for c in state.top_row())
    assert state.is_solved()
    assert len(state.foundations) == 8
    assert all(len(p) == 13 for p in state.foundations)
    assert len(state.stock) == 0


def test_canonical_action_count():
    moves = deals = 0
    for line in CANONICAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.split()[0] == "move":
            moves += 1
        elif line.split()[0] == "deal":
            deals += 1
    assert moves == 169
    assert deals == 5