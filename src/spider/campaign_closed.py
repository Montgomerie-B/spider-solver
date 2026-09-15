"""Exact known-closed registry from historical complete/exhaustive searches.

Prune only on exact physical identity, complete prior search under ceiling
<= current ceiling, and current arrival g >= prior arrival g.
Lower arrival g is LOWER_G_REOPENING. No approximation.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

from spider.app_paths import research_json
from spider.packed_state import pack_whole_game_identity, unpack_state

SOURCES = (
    ("v080", "proof_aware_tactical_bridge_v0_80.json"),
    ("v081", "g158_proof_aware_f4_v0_81.json"),
    ("v087", "strong_surplus_f4_bridge_v0_87.json"),
    ("v091", "long_horizon_f3_adjudication_v0_91.json"),
    ("v097", "f5_production_candidate_v0_97.json"),
)


def _ident_from(rec: dict) -> Optional[str]:
    ident = rec.get("ident") or rec.get("whole_game_identity")
    digest = rec.get("ordered_digest") or rec.get("post_digest")
    if ident:
        return str(ident)
    if not digest:
        return None
    try:
        return pack_whole_game_identity(unpack_state(bytes.fromhex(digest))).hex()
    except Exception:
        return None


def _add(table: Dict[str, dict], rec: dict, *, source: str, complete: bool, ceiling: int) -> None:
    ident = _ident_from(rec)
    if not ident:
        return
    g = rec.get("g")
    if g is None:
        g = rec.get("closed_g") or rec.get("arrival_g") or rec.get("post_g")
    if g is None:
        return
    digest = rec.get("ordered_digest") or rec.get("post_digest")
    prev = table.get(ident)
    item = {
        "ident": ident,
        "ordered_digest": digest,
        "g": int(g),
        "source": source,
        "ceiling": int(ceiling),
        "complete": bool(complete),
    }
    if prev is None or int(g) < int(prev["g"]):
        table[ident] = item


def _walk(obj, table: dict, *, source: str, ceiling: int) -> None:
    if isinstance(obj, dict):
        closed = bool(obj.get("closed") or obj.get("closed_tag") == "KNOWN_CLOSED_STATE")
        exhausted = bool(obj.get("exhausted"))
        stop = str(obj.get("stop_reason") or obj.get("stop") or "")
        complete = closed or exhausted or stop == "complete"
        if complete and (obj.get("ident") or obj.get("ordered_digest") or obj.get("whole_game_identity")):
            _add(table, obj, source=source, complete=True, ceiling=int(obj.get("ceiling") or ceiling))
        for v in obj.values():
            _walk(v, table, source=source, ceiling=ceiling)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, table, source=source, ceiling=ceiling)


def load_known_closed_registry(*, ceiling: int = 186) -> Dict[str, dict]:
    """Exact closures with sufficient records. Incomplete searches are skipped."""

    table: Dict[str, dict] = {}
    for source, name in SOURCES:
        path = research_json(name)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if source in ("v080", "v081"):
            for rec in (data.get("bridge") or {}).get("f4_roots") or []:
                _add(table, rec, source=source, complete=True, ceiling=int(ceiling))
        if source == "v087":
            for rec in data.get("portfolio") or []:
                _add(table, rec, source=source, complete=True, ceiling=int(ceiling))
        if source == "v091":
            complete_roles = {
                rec.get("role") or rec.get("source_f3")
                for rec in data.get("scorecard") or []
                if rec.get("exhausted") or rec.get("stop_reason") == "complete"
            }
            for rec in data.get("portfolio") or []:
                role = rec.get("portfolio_role") or rec.get("root_name")
                if rec.get("exhausted") or rec.get("stop_reason") == "complete" or role in complete_roles or (
                    rec.get("ident") and any(
                        (s.get("f4_g") == rec.get("g") and (s.get("exhausted") or s.get("stop_reason") == "complete"))
                        for s in data.get("scorecard") or []
                    )
                ):
                    _add(table, rec, source=source, complete=True, ceiling=int(data.get("candidate_ceiling") or ceiling))
        if source == "v097":
            if str(data.get("stop_reason") or "") == "complete":
                _walk(data, table, source=source, ceiling=int(data.get("candidate_ceiling") or ceiling))
            for rec in (data.get("closed_audit") or {}).get("hits") or []:
                # Already-known closures observed during v0.97; provenance only.
                if rec.get("ident") and rec.get("closed_g") is not None:
                    item = dict(rec)
                    item["g"] = rec.get("closed_g")
                    _add(
                        table,
                        item,
                        source=str(rec.get("closed_source") or source),
                        complete=True,
                        ceiling=int(data.get("candidate_ceiling") or ceiling),
                    )
        _walk(data, table, source=source, ceiling=int(data.get("candidate_ceiling") or ceiling))
    return table


def classify_arrival(ident: str, arrival_g: int, table: dict, *, ceiling: int = 186) -> dict:
    prior = table.get(ident)
    if not prior:
        return {"status": "open"}
    if not prior.get("complete"):
        return {"status": "open", "prior": prior, "reason": "prior_not_complete"}
    if int(prior.get("ceiling") or 186) > int(ceiling):
        return {"status": "open", "prior": prior, "reason": "prior_ceiling_higher"}
    if int(arrival_g) >= int(prior["g"]):
        return {"status": "known_closed", "prior": prior}
    return {"status": "LOWER_G_REOPENING", "prior": prior}


def apply_closed_pruning(candidates: list, table: Optional[dict] = None, *, ceiling: int = 186) -> dict:
    table = table if table is not None else load_known_closed_registry(ceiling=ceiling)
    prune = 0
    reopen = 0
    for cand in candidates:
        ident = cand.get("ident") or cand.get("whole_game_identity")
        if not ident:
            continue
        decision = classify_arrival(ident, int(cand.get("g") or 0), table, ceiling=ceiling)
        if decision["status"] == "known_closed":
            cand["known_closed"] = True
            cand["closed_source"] = (decision.get("prior") or {}).get("source")
            cand["closed_g"] = (decision.get("prior") or {}).get("g")
            prune += 1
        elif decision["status"] == "LOWER_G_REOPENING":
            cand["lower_g_reopening"] = True
            cand["closed_source"] = (decision.get("prior") or {}).get("source")
            cand["closed_g"] = (decision.get("prior") or {}).get("g")
            reopen += 1
    return {"closed_pruned": prune, "lower_g_reopenings": reopen, "registry_n": len(table)}
