"""Compile canonical rulebook source records into runtime artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .schema import (
        GENERATED_NOTICE,
        SOURCE_DIRS,
        RulebookValidationError,
        SourceRecord,
        validate_record_shape,
        validate_references,
    )
except ImportError:  # pragma: no cover - script execution fallback
    from schema import (  # type: ignore
        GENERATED_NOTICE,
        SOURCE_DIRS,
        RulebookValidationError,
        SourceRecord,
        validate_record_shape,
        validate_references,
    )


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
RULEBOOK_DIR = ROOT / "rulebook"
SOURCE_ROOT = RULEBOOK_DIR / "source"
COMPILED_DIR = RULEBOOK_DIR / "compiled"
RENDERED_DIR = RULEBOOK_DIR / "rendered"
AUTO_SKILLS_PATH = ROOT / "auto" / "skills.json"


def load_records(source_root: Path = SOURCE_ROOT) -> list[SourceRecord]:
    """Load and validate source JSON records."""
    records: list[SourceRecord] = []
    for category in SOURCE_DIRS:
        category_dir = source_root / category
        if not category_dir.exists():
            continue
        for path in sorted(category_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            record = SourceRecord(category=category, path=path, data=data)
            validate_record_shape(record)
            records.append(record)
    validate_references(records)
    return records


def source_hash(records: list[SourceRecord]) -> str:
    """Return a deterministic hash of loaded source files."""
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: str(item.path.relative_to(SOURCE_ROOT))):
        rel = record.path.relative_to(SOURCE_ROOT).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(record.path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _json_dump(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _record_index(records: list[SourceRecord]) -> dict[str, Any]:
    return {
        record.rule_id: {
            "id": record.rule_id,
            "title": record.data["title"],
            "type": record.data["type"],
            "status": record.data["status"],
            "markets": record.data["markets"],
            "category": record.category,
            "source_path": record.path.relative_to(REPO_ROOT).as_posix(),
        }
        for record in sorted(records, key=lambda item: item.rule_id)
    }


def build_artifacts(records: list[SourceRecord]) -> dict[Path, str]:
    """Build compiled and rendered artifact content without writing files."""
    hash_value = source_hash(records)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.category] = counts.get(record.category, 0) + 1

    artifacts: dict[Path, str] = {}
    index = {
        "_generated_notice": GENERATED_NOTICE,
        "rulebook_version": "rulebook.v1",
        "source_hash": hash_value,
        "counts": counts,
        "rules": _record_index(records),
    }
    artifacts[COMPILED_DIR / "rule_index.json"] = _json_dump(index)

    hard_rules = [
        {
            "id": record.rule_id,
            "title": record.data["title"],
            "markets": record.data["markets"],
            "description": record.data["description"],
            "enforcement": record.data["enforcement"],
        }
        for record in sorted(records, key=lambda item: item.rule_id)
        if record.category == "hard" and record.data["status"] == "active"
    ]
    artifacts[COMPILED_DIR / "verifier_rules.json"] = _json_dump(
        {
            "_generated_notice": GENERATED_NOTICE,
            "source_hash": hash_value,
            "hard_rules": hard_rules,
        }
    )
    artifacts[COMPILED_DIR / "retriever_manifest.json"] = _json_dump(
        _retriever_manifest(records, hash_value)
    )

    legacy_hard: dict[str, Any] = {}
    legacy_soft: dict[str, str] = {}
    for record in sorted(records, key=lambda item: item.rule_id):
        compatibility = record.data.get("legacy_skills", {})
        if record.category == "hard":
            legacy_hard.update(compatibility.get("hard", {}))
        if record.category == "soft":
            legacy_soft.update(compatibility.get("soft", {}))

    compiled_skills = {
        "_generated": True,
        "_generated_notice": GENERATED_NOTICE,
        "_source": "trading/rulebook/source",
        "_do_not_edit": True,
        "source_hash": hash_value,
        "hard": legacy_hard,
        "soft": legacy_soft,
    }
    skills_content = _json_dump(compiled_skills)
    artifacts[COMPILED_DIR / "skills.json"] = skills_content
    artifacts[AUTO_SKILLS_PATH] = skills_content

    artifacts[RENDERED_DIR / "llm" / "hard_rules.md"] = _render_markdown(
        "Hard Rules", [record for record in records if record.category == "hard"]
    )
    artifacts[RENDERED_DIR / "llm" / "soft_policies.md"] = _render_markdown(
        "Soft Policies", [record for record in records if record.category == "soft"]
    )
    artifacts[RENDERED_DIR / "llm" / "playbooks.md"] = _render_markdown(
        "Playbooks", [record for record in records if record.category == "playbooks"]
    )
    artifacts[RENDERED_DIR / "llm" / "cases.md"] = _render_markdown(
        "Cases", [record for record in records if record.category == "cases"]
    )
    artifacts[RENDERED_DIR / "human" / "rulebook.md"] = _render_markdown(
        "Rulebook", records
    )
    artifacts[RENDERED_DIR / "human" / "playbook_catalog.md"] = _render_markdown(
        "Playbook Catalog", [record for record in records if record.category == "playbooks"]
    )
    return artifacts


def _render_markdown(title: str, records: list[SourceRecord]) -> str:
    lines = [GENERATED_NOTICE, "", f"# {title}", ""]
    for record in sorted(records, key=lambda item: item.rule_id):
        data = record.data
        lines.extend(
            [
                f"## {record.rule_id} - {data['title']}",
                "",
                f"- Type: `{data['type']}`",
                f"- Status: `{data['status']}`",
                f"- Markets: {', '.join(data['markets'])}",
                "",
                str(data["description"]).strip(),
                "",
            ]
        )
        llm_guidance = data.get("llm_guidance")
        if llm_guidance:
            lines.extend(["LLM guidance:", "", str(llm_guidance).strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _retriever_manifest(records: list[SourceRecord], hash_value: str) -> dict[str, Any]:
    """Build metadata and prompt snippets for deterministic retrieval."""
    return {
        "_generated_notice": GENERATED_NOTICE,
        "source_hash": hash_value,
        "rules": {
            record.rule_id: _retriever_record(record)
            for record in sorted(records, key=lambda item: item.rule_id)
        },
    }


def _retriever_record(record: SourceRecord) -> dict[str, Any]:
    data = record.data
    return {
        "id": record.rule_id,
        "title": data["title"],
        "type": data["type"],
        "category": record.category,
        "status": data["status"],
        "markets": data["markets"],
        "source_path": record.path.relative_to(REPO_ROOT).as_posix(),
        "description": data["description"],
        "directions": data.get("directions", []),
        "regimes": data.get("regimes", []),
        "timeframes": data.get("timeframes", []),
        "required_hard_rules": data.get("required_hard_rules", []),
        "related_soft_policies": data.get("related_soft_policies", []),
        "playbook_id": data.get("playbook_id"),
        "rule_citations": data.get("rule_citations", []),
        "llm_guidance": data.get("llm_guidance", ""),
        "markdown": _render_record_snippet(record),
    }


def _render_record_snippet(record: SourceRecord) -> str:
    data = record.data
    lines = [
        f"## {record.rule_id} - {data['title']}",
        "",
        f"- Type: `{data['type']}`",
        f"- Category: `{record.category}`",
        f"- Status: `{data['status']}`",
        f"- Markets: {', '.join(data['markets'])}",
    ]
    if data.get("directions"):
        lines.append(f"- Directions: {', '.join(data['directions'])}")
    if data.get("regimes"):
        lines.append(f"- Regimes: {', '.join(data['regimes'])}")
    if data.get("timeframes"):
        lines.append(f"- Timeframes: {', '.join(data['timeframes'])}")
    lines.extend(["", str(data["description"]).strip()])
    if data.get("llm_guidance"):
        lines.extend(["", "LLM guidance:", "", str(data["llm_guidance"]).strip()])
    return "\n".join(lines).rstrip()


def write_artifacts(artifacts: dict[Path, str]) -> None:
    """Write artifact contents to disk."""
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def check_artifacts(artifacts: dict[Path, str]) -> list[str]:
    """Return stale/missing artifact paths."""
    stale: list[str] = []
    for path, expected in artifacts.items():
        if not path.exists():
            stale.append(str(path.relative_to(REPO_ROOT)))
            continue
        if path.read_text(encoding="utf-8") != expected:
            stale.append(str(path.relative_to(REPO_ROOT)))
    return stale


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and fail if artifacts are stale")
    parser.add_argument("--write", action="store_true", help="write generated artifacts")
    args = parser.parse_args(argv)

    try:
        records = load_records()
        artifacts = build_artifacts(records)
        if args.check:
            stale = check_artifacts(artifacts)
            if stale:
                print("Rulebook generated artifacts are stale or missing:", file=sys.stderr)
                for path in stale:
                    print(f"  - {path}", file=sys.stderr)
                return 1
            print(f"Rulebook check passed ({len(records)} source records).")
            return 0

        write_artifacts(artifacts)
        print(f"Rulebook compiled ({len(records)} source records).")
        return 0
    except (OSError, json.JSONDecodeError, RulebookValidationError) as exc:
        print(f"Rulebook compile failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
