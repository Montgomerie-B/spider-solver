#!/usr/bin/env python3
"""Reproduce the v0.7 CONTROL fd-14 stock-empty seed and write the fixture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import census_legal_by_tier, foundation_proximity
from spider.simple_progressive_solver import (
    DEFAULT_DEPTH_BANDS,
    format_moves_text,
    solve_progressive,
)

DEAL_PATH = ROOT / "deals" / "4925153.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
META = ROOT / "research" / "results" / "simple_progressive_seeded_pass1_v0_8" / "seed_meta.json"
EXPECTED_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)


def main() -> int:
    META.parent.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    print("START seed extraction control probe=1 band_local=0 nodes=1000000", flush=True)
    result = solve_progressive(
        opening,
        max_nodes=1_000_000,
        time_limit_s=1800.0,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
        depth_bands=DEFAULT_DEPTH_BANDS,
        enable_saturation=True,
        enable_audit=True,
        enable_best_reveal_deal_probe=True,
        enable_post_deal_audit=False,
        enable_band_local_saturation=False,
    )
    cell = result.best_fd_by_stock_dealt[5]
    actions = list(cell.get("actions") or [])
    end = opening.clone()
    cost = replay_actions(end, actions) if actions else 0
    digest = pack_state(end).hex()
    fd = sum(len(col.face_down) for col in end.columns)
    stock = len(end.stock) // 10
    fnd = len(end.foundations)
    census = census_legal_by_tier(end)
    prox = foundation_proximity(end)
    ok = (
        digest == EXPECTED_HEX
        and fd == 14
        and stock == 0
        and fnd == 0
        and cost == 43
        and len(actions) == 43
    )
    payload = {
        "ok": ok,
        "digest": digest,
        "expected": EXPECTED_HEX,
        "fd": fd,
        "stock_rows": stock,
        "foundations": fnd,
        "cost": cost,
        "path_length": len(actions),
        "census": census,
        "proximity": prox,
        "nodes": result.nodes,
        "unique": result.stats.unique_exact_states,
        "stop_reason": result.stop_reason,
    }
    META.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not ok:
        print(f"SEED_REPRODUCTION_FAILED digest={digest} fd={fd} stock={stock} cost={cost}", flush=True)
        print(f"WROTE {META}", flush=True)
        return 1
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        format_moves_text(
            actions,
            header=(
                "# v0.8 seed: 4925153 fd-14 stock-empty coupled witness\n"
                "# lineage: L_COUPLED_FD14_DEALS5_DEPTH43\n"
                f"# primitive_moves: {len(actions)}\n"
                f"# mobilityware_moves: {cost}\n"
                f"# digest: {digest}\n"
            ),
        ),
        encoding="utf-8",
    )
    print(f"SEED_OK digest={digest} fd={fd} stock={stock} cost={cost}", flush=True)
    print(f"WROTE {FIXTURE}", flush=True)
    print("VERDICT SEED_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
