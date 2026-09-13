"""Healthy F1 lineage continuation v0.64."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.healthy_f1 import (
    CANDIDATE_CEILING,
    F1_FD,
    F1_G,
    F1_N,
    F1_ROWS,
    LINEAGE_TAG,
    f1_abort,
    verify_f1_prefix,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_LANES, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.prospective_debt import DEBT_LANES
from spider.research_actions import is_deal
from spider.whole_game_anytime import opening_root, opening_state
from spider.whole_game_epoch_scheduler import _dedup_roots, search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src" / "spider" / "healthy_f1.py"
OP = ROOT / "src" / "spider" / "operational_policy.py"
ARTEFACT = ROOT / "docs" / "research" / "healthy_f1_lineage_v0_64.json"
INCUMBENT = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def test_no_canonical_and_no_new_heuristic():
    for path in (POLICY, OP):
        text = path.read_text(encoding="utf-8")
        assert "4925153_canonical" not in text
        assert "canonical.moves" not in text
        assert _simple_imports(path) == []
    assert "durability" not in OP_LANES
    assert "durability" in DEBT_LANES
    src = inspect.getsource(search_operational_optimisation)
    assert "operational_lane_keys" in src
    assert "durability_key" not in src
    assert "reception_fitness" not in POLICY.read_text(encoding="utf-8")


def test_verify_f1_rejects_opening():
    opening = opening_state()
    snap = verify_f1_prefix(opening, [])
    assert snap["replay_ok"] is False
    assert snap["g"] == 0
    assert CANDIDATE_CEILING == 197
    assert F1_G == 71 and F1_FD == 10 and F1_ROWS == 3 and F1_N == 1


def test_lineage_does_not_change_packed_identity():
    opening = opening_state()
    a = pack_state(opening)
    b = pack_whole_game_identity(opening)
    root = opening_root(opening)
    root["lineage"] = [LINEAGE_TAG]
    assert pack_state(opening) == a
    assert pack_whole_game_identity(opening) == b
    st2 = opening.clone()
    assert pack_state(st2) == a


def test_lineage_merge_on_same_exact_state():
    cheap = {
        "ident": "aa",
        "g": 80,
        "ordered_digest": "00",
        "lineage": [LINEAGE_TAG],
        "categories": ["readiness"],
    }
    other = {
        "ident": "aa",
        "g": 90,
        "ordered_digest": "00",
        "lineage": ["other"],
        "categories": ["cheap"],
    }
    out = _dedup_roots([other, cheap])
    assert out["unique"] == 1
    kept = out["states"][0]
    assert kept["g"] == 80
    assert LINEAGE_TAG in kept["lineage"]
    assert "other" in kept["lineage"]


def test_initial_roots_keep_absolute_g_and_ceiling():
    opening = opening_state()
    root = opening_root(opening)
    root["g"] = 5
    root["lineage"] = [LINEAGE_TAG]
    res = search_epoch_portfolio(
        opening=opening,
        initial_roots=[root],
        max_unique=16,
        time_limit_s=1.0,
        rss_abort_mb=4096,
        cost_ceiling=197,
        portfolio_width=8,
    )
    assert res.min_g is None or res.min_g >= 5
    assert res.candidate_ceiling == 197
    src = inspect.getsource(search_operational_optimisation)
    assert "incumbent_g - 1" in src or "cost_ceiling" in src


def test_f1_abort_predicate_and_incumbent_198():
    rec = {
        "foundations": 1,
        "g": 71,
        "face_down": 10,
        "stock_rows": 3,
        "full_actions": [["deal"]],
    }
    assert f1_abort(None, rec) is True
    rec_no_path = dict(rec)
    rec_no_path.pop("full_actions")
    assert f1_abort(None, rec_no_path) is True
    rec2 = dict(rec, g=70)
    assert f1_abort(None, rec2) is False
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT)
    end = opening.clone()
    assert replay_actions(end, actions) == 198
    assert end.is_solved()
    assert sum(1 for a in actions if is_deal(a)) == 5


def test_reconstructed_prefix_if_artefact_present():
    if not ARTEFACT.exists():
        return
    import json

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    prefix = data.get("f1_prefix_actions")
    if not prefix:
        return
    opening = opening_state()
    actions = []
    for item in prefix:
        if item == ["deal"] or item == "deal":
            actions.append(("deal",))
        else:
            actions.append((int(item[0]), int(item[1]), int(item[2])))
    snap = verify_f1_prefix(opening, actions)
    assert snap["replay_ok"]
    assert snap["g"] == 71
    assert snap["face_down"] == 10
    assert snap["stock_rows"] == 3
    assert snap["foundations"] == 1
    if data.get("f1_digest"):
        assert snap["ordered_digest"] == data["f1_digest"]
    packed = pack_state(opening)
    assert "v063_f1" not in packed.hex()
