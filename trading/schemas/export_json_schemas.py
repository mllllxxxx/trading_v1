"""Export shared dataclass contracts as JSON schema artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .json_schema import schemas_for_export
except ImportError:  # pragma: no cover - script execution fallback
    from json_schema import schemas_for_export  # type: ignore


SCHEMA_DIR = Path(__file__).resolve().parent


def build_artifacts() -> dict[Path, str]:
    """Build JSON schema artifact content."""
    artifacts: dict[Path, str] = {}
    for filename, schema in schemas_for_export().items():
        artifacts[SCHEMA_DIR / filename] = (
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    return artifacts


def write_artifacts(artifacts: dict[Path, str]) -> None:
    """Write schema artifacts to disk."""
    for path, content in artifacts.items():
        path.write_text(content, encoding="utf-8")


def check_artifacts(artifacts: dict[Path, str]) -> list[str]:
    """Return schema files that are missing or stale."""
    stale: list[str] = []
    for path, expected in artifacts.items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            stale.append(path.name)
    return stale


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if schema files are stale")
    args = parser.parse_args(argv)
    artifacts = build_artifacts()
    if args.check:
        stale = check_artifacts(artifacts)
        if stale:
            print("Schema artifacts are stale or missing:", file=sys.stderr)
            for name in stale:
                print(f"  - {name}", file=sys.stderr)
            return 1
        print(f"Schema check passed ({len(artifacts)} artifacts).")
        return 0
    write_artifacts(artifacts)
    print(f"Exported {len(artifacts)} schema artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
