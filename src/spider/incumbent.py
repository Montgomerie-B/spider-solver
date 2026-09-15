"""Single source of truth for the current autonomous incumbent.

Historical v0.74 g=187 remains an immutable parent artefact. Current
campaigns, packaging, and promotions consult this registry only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.app_paths import local_app_root, repo_root
from spider.hardware import SOLVER_VERSION

BUNDLED_NAME = "4925153_incumbent.json"
DEAL_ID = "4925153"


def bundled_incumbent_path() -> Path:
    return repo_root() / "solutions" / BUNDLED_NAME


def local_incumbent_path() -> Path:
    return local_app_root() / "incumbent.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_incumbent() -> dict:
    bundled = bundled_incumbent_path()
    if not bundled.exists():
        raise FileNotFoundError(f"missing bundled incumbent registry: {bundled}")
    data = _read(bundled)
    local = local_incumbent_path()
    if local.exists():
        overlay = _read(local)
        # Lower g is a better incumbent. A worse overlay must not hide the bundled 186.
        if int(overlay.get("incumbent_g") or 10**9) <= int(data.get("incumbent_g") or 10**9):
            overlay["_overlay"] = True
            return overlay
    data["_overlay"] = False
    return data


def current_incumbent_g() -> int:
    return int(load_incumbent()["incumbent_g"])


def production_ceiling() -> int:
    return int(load_incumbent()["production_ceiling"])


def incumbent_moves_path() -> Path:
    rec = load_incumbent()
    rel = rec.get("moves_path") or "solutions/4925153_autonomous_v0_100.moves"
    p = Path(rel)
    if p.is_absolute() and p.exists():
        return p
    bundled = repo_root() / rel
    if bundled.exists():
        return bundled
    local = local_app_root() / rel
    if local.exists():
        return local
    local2 = local_app_root() / "solutions" / Path(rel).name
    if local2.exists():
        return local2
    return bundled


def incumbent_metadata_path() -> Optional[Path]:
    rec = load_incumbent()
    rel = rec.get("metadata_path")
    if not rel:
        return None
    p = repo_root() / rel
    return p if p.exists() else None


def save_incumbent(data: dict, *, path: Optional[Path] = None) -> Path:
    dest = path or local_incumbent_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload.pop("_overlay", None)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return dest


def promote_incumbent(
    *,
    g: int,
    moves_path: str,
    metadata_path: Optional[str] = None,
    source: str = "campaign_promote",
    solver_sha: Optional[str] = None,
) -> dict:
    rec = {
        "deal_id": DEAL_ID,
        "incumbent_g": int(g),
        "production_ceiling": int(g) - 1,
        "moves_path": moves_path,
        "metadata_path": metadata_path,
        "solver_version": SOLVER_VERSION,
        "solver_sha": solver_sha,
        "verified_replay": True,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "rules_profile": "mobilityware_unrestricted",
    }
    save_incumbent(rec)
    return rec
