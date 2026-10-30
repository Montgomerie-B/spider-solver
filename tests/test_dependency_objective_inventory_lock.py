"""Record the inventory one-shot without searching again.

Freeze ``7b6a051d238e37888f4a0a1cbfe2ba48a2c7fb4c`` was searched once.
This module checks that those states still pack to the searched
identities and that the recorded statuses stay the documented ones.
It does not import the lookahead.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.dependency_objective_inventory import build_state, inventory_sources
from spider.packed_state import pack_state

_OBSERVED = (
    {
        "source_id": 'blocker-chain',
        "source_pack": '53504b3101040000010101370121113c2c1c0c3b2b1b0b3a2a0a391909281808271736261606352515053424140438290101211a01013112010102130101220d0101321d0101032d0101233d010133070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201',
        "status": 'inconclusive',
        "choice_id": '(3, 4, 1)',
        "baseline_id": '(3, 4, 1)',
        "candidates": (
        ('(3, 4, 1)', 'upper-unfinished', 'unique limit', 3, 20, ((1, 2, 1), (0, 1, 1))),
        ('(1, 2, 1)', 'upper-unfinished', 'unique limit', 2, 20, ((0, 1, 1),)),
        ),
    },
    {
        "source_id": 'immediate-join',
        "source_pack": '53504b31010400000121113c2c1c0c3b2b3a2a1a0a2919092818083727170736261606352515342414330403010121050101310d0101021d0101122d01010138010122390101323d0101130b0101231b0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201',
        "status": 'ranked',
        "choice_id": '(5, 6, 1)',
        "baseline_id": '(0, 1, 2)',
        "candidates": (
        ('(0, 1, 2)', 'exact', 'complete', 2, 2, ((5, 6, 1),)),
        ('(5, 6, 1)', 'exact', 'prefix-terminal', 1, 0, ()),
        ),
    },
    {
        "source_id": 'symmetric-tie',
        "source_pack": '53504b310104000001020138130120113c2c1c0c3b2b3a2a1a0a29190928180837271707362616063525150534143339010121240101310d010102040101121d0101222d0101323d0101030b0101231b0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201',
        "status": 'ranked',
        "choice_id": '(0, 2, 1)',
        "baseline_id": '(0, 2, 1)',
        "candidates": (
        ('(0, 2, 1)', 'exact', 'complete', 2, 4, ((0, 1, 1),)),
        ('(0, 4, 1)', 'exact', 'complete', 2, 4, ((0, 1, 1),)),
        ),
    },
    {
        "source_id": 'distractor-reveal',
        "source_pack": '53504b31010300000102013813012d113d3d2d1d3c3c2c1c3b3b2b1b0b3a3a2a1a0a3828180837372717363626160635352515053434140433332303390101212401013139010131090101020c0101120d0101221901013229010132070d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201',
        "status": 'inconclusive',
        "choice_id": '(5, 6, 1)',
        "baseline_id": '(5, 6, 1)',
        "candidates": (
        ('(5, 6, 1)', 'upper-unfinished', 'unique limit', 3, 20, ((0, 2, 1), (0, 1, 1))),
        ('(0, 2, 1)', 'upper-unfinished', 'unique limit', 2, 20, ((0, 1, 1),)),
        ),
    },
    {
        "source_id": 'three-deep-uncover',
        "source_pack": '53504b3101040000010301382413011f113d1d0d3c1c0c3b2b1b0b3a2a1a0a281808372717362616063525053414333901012104010131150101022c0101122d010122090101321901010329010123070d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201',
        "status": 'inconclusive',
        "choice_id": '(4, 5, 1)',
        "baseline_id": '(4, 5, 1)',
        "candidates": (
        ('(4, 5, 1)', 'upper-unfinished', 'unique limit', 4, 20, ((0, 2, 1), (0, 3, 1), (0, 1, 1))),
        ('(0, 2, 1)', 'upper-unfinished', 'unique limit', 3, 20, ((0, 3, 1), (0, 1, 1))),
        ('(2, 3, 1)', 'unknown', 'unique limit', None, 20, ()),
        ),
    },
    {
        "source_id": 'zero-cost-workspace',
        "source_pack": '53504b310104000001020138130122113c2c1c0c3b2b0b3a1a0a29190928180837271736261635251505342414043323033900012a0101211b00012d01013106010102070101120d0101221d0101323d0d3d3c3b3a3938373635343332310d2d2c2b2a2928272625242322210d1d1c1b1a1918171615141312110d0d0c0b0a090807060504030201',
        "status": 'inconclusive',
        "choice_id": '(5, 6, 1)',
        "baseline_id": '(5, 6, 1)',
        "candidates": (
        ('(5, 6, 1)', 'unknown', 'unique limit', None, 20, ()),
        ('(1, 2, 1)', 'exhausted-no-hit', 'complete', None, 2, ()),
        ('(2, 3, 1)', 'unknown', 'unique limit', None, 20, ()),
        ),
    },
)


def _candidate(row, option_id):
    for item in row["candidates"]:
        if item[0] == option_id:
            return item
    raise AssertionError(option_id)


def test_one_shot_packs_and_outcomes_stay_recorded():
    sources = {source.source_id: source for source in inventory_sources()}
    observed = {row["source_id"]: row for row in _OBSERVED}
    assert [row["source_id"] for row in _OBSERVED] == [source.source_id for source in inventory_sources()]
    for row in _OBSERVED:
        state = build_state(sources[row["source_id"]])
        assert pack_state(state).hex() == row["source_pack"]
        assert row["status"] in ("ranked", "inconclusive", "no-exact-in-scope")
        if row["status"] != "ranked":
            assert row["choice_id"] == row["baseline_id"]
            assert any(item[1] in ("unknown", "upper-unfinished") for item in row["candidates"])
    immediate = observed["immediate-join"]
    assert immediate["status"] == "ranked"
    assert immediate["choice_id"] == "(5, 6, 1)"
    assert _candidate(immediate, "(5, 6, 1)")[:4] == ("(5, 6, 1)", "exact", "prefix-terminal", 1)
    assert _candidate(immediate, "(0, 1, 2)")[3] == 2
    tie = observed["symmetric-tie"]
    assert tie["status"] == "ranked"
    assert tie["choice_id"] == tie["baseline_id"] == "(0, 2, 1)"
    assert _candidate(tie, "(0, 2, 1)")[3] == _candidate(tie, "(0, 4, 1)")[3] == 2
    for source_id in ("blocker-chain", "distractor-reveal", "three-deep-uncover", "zero-cost-workspace"):
        assert observed[source_id]["status"] == "inconclusive"
