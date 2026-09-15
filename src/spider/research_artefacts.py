"""Small helpers for research JSON consistency. No search policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def artefact_verdicts_agree(result_path: Path, progress_path: Path, report_path: Optional[Path] = None) -> dict:
    result = load_json(result_path)
    progress = load_json(progress_path)
    rv = result.get("verdict")
    pv = progress.get("verdict")
    report_ok = True
    if report_path is not None and report_path.exists():
        text = report_path.read_text(encoding="utf-8")
        report_ok = f"`{rv}`" in text or f"Verdict: `{rv}`" in text or f"**{rv}**" in text
    return {
        "ok": rv is not None and rv == pv and report_ok,
        "result_verdict": rv,
        "progress_verdict": pv,
        "report_ok": report_ok,
    }
