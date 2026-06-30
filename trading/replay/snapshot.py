"""Snapshot loading helpers for replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_snapshot_bundle(
    decision_id: str,
    *,
    snapshots_root: str | Path | None = None,
    date_key: str | None = None,
) -> dict[str, Any]:
    """Load snapshot artifacts for a decision ID."""
    if snapshots_root is None:
        try:
            from auto import journal
        except ImportError:  # pragma: no cover - direct script import fallback
            import journal  # type: ignore
        return journal.read_lifecycle_snapshots(decision_id, date_key=date_key)

    root = Path(snapshots_root)
    roots = [root / date_key] if date_key else sorted(path for path in root.glob("*") if path.is_dir())
    safe_id = _safe_fragment(decision_id)
    bundle: dict[str, Any] = {}
    for folder in roots:
        if not folder.exists():
            continue
        for path in sorted(folder.glob(f"{safe_id}.*.json")):
            artifact_type = path.name[len(safe_id) + 1:-5]
            bundle[artifact_type] = json.loads(path.read_text(encoding="utf-8"))
    return bundle


def _safe_fragment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in value).strip("._") or "unknown"
