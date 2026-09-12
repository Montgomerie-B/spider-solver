"""Generic research root replay and cheapest-g dedup.

Callers supply opening state, identity function, and provenance. No baked
portfolio paths.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.research_actions import as_actions, dump_actions, stock_rows


def load_json_records(path: Path, *, keep: Optional[Callable[[dict], bool]] = None) -> List[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    if keep is not None:
        rows = [r for r in rows if keep(r)]
    return rows


def replay_root(
    opening: SpiderState,
    rec: dict,
    *,
    require_stock_zero: bool = True,
    require_foundation_count: Optional[int] = None,
    require_foundation_suit: Optional[str] = None,
) -> Optional[dict]:
    end = opening.clone()
    try:
        cost = replay_actions(end, as_actions(rec["full_actions"]))
    except Exception:
        return None
    want = int(rec.get("g", rec.get("full_cost", -1)))
    if cost != want:
        return None
    if require_stock_zero and stock_rows(end) != 0:
        return None
    if require_foundation_count is not None and len(end.foundations) != require_foundation_count:
        return None
    if require_foundation_suit is not None:
        if not end.foundations or end.foundations[0][0].suit != require_foundation_suit:
            return None
    if rec.get("ordered_digest") and pack_state(end).hex() != rec["ordered_digest"]:
        return None
    ident_ord = pack_state(end)
    ident_sym = pack_post_stock_symmetry_state(end) if not end.stock else ident_ord
    out = dict(rec)
    out["g"] = cost
    out["full_actions"] = dump_actions(as_actions(rec["full_actions"]))
    out["ordered_digest"] = ident_ord.hex()
    out["symmetry_digest"] = ident_sym.hex()
    out["stock_rows"] = stock_rows(end)
    out["foundations"] = len(end.foundations)
    return out


def dedup_roots(rows: Sequence[dict], *, identity_key: str = "symmetry_digest") -> dict:
    classes: Dict[str, dict] = {}
    convergences = 0
    for rec in rows:
        ident = rec[identity_key]
        prev = classes.get(ident)
        if prev is None:
            item = dict(rec)
            item["timings"] = list(rec.get("timings") or ([rec["timing"]] if rec.get("timing") else []))
            item["categories"] = list(rec.get("categories") or [])
            item["lineages"] = list(rec.get("lineages") or [])
            classes[ident] = item
            continue
        timings = sorted(set(prev.get("timings") or []) | set(rec.get("timings") or ([rec.get("timing")] if rec.get("timing") else [])))
        if rec.get("timing") and rec.get("timing") != prev.get("timing"):
            convergences += 1
        cats = sorted(set((prev.get("categories") or []) + (rec.get("categories") or [])))
        lins = sorted(set((prev.get("lineages") or []) + (rec.get("lineages") or [])))
        if rec["g"] < prev["g"]:
            item = dict(rec)
            item["timings"] = timings
            item["categories"] = cats
            item["lineages"] = lins
            if len(timings) > 1:
                item["timing"] = "MULTIPLE"
            classes[ident] = item
        else:
            prev["timings"] = timings
            prev["categories"] = cats
            prev["lineages"] = lins
            if len(timings) > 1:
                prev["timing"] = "MULTIPLE"
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "combined_raw": len(rows),
        "symmetry_unique": len(kept),
        "convergences": convergences,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "timing": dict(Counter(r.get("timing") for r in kept)),
        "states": kept,
    }
