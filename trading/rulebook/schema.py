"""Validation helpers for rulebook source records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


GENERATED_NOTICE = (
    "DO NOT EDIT - generated from trading/rulebook/source by compile_rulebook.py"
)

SOURCE_DIRS: dict[str, str] = {
    "hard": "HARD_",
    "soft": "SOFT_",
    "playbooks": "PB_",
    "cases": "CASE_",
    "data_policies": "DATA_",
    "execution_policies": "EXEC_",
    "model_policies": "MODEL_",
}

ALLOWED_STATUS = {"active", "deprecated", "retired"}


class RulebookValidationError(ValueError):
    """Raised when rulebook source records fail validation."""


@dataclass(frozen=True)
class SourceRecord:
    """Loaded rulebook source record with file metadata."""

    category: str
    path: Path
    data: dict[str, Any]

    @property
    def rule_id(self) -> str:
        """Return the stable rulebook identifier."""
        return str(self.data["id"])


def validate_record_shape(record: SourceRecord) -> None:
    """Validate one source record's local shape."""
    data = record.data
    required = {"id", "title", "type", "status", "markets", "description"}
    missing = sorted(required - data.keys())
    if missing:
        raise RulebookValidationError(
            f"{record.path}: missing required fields: {', '.join(missing)}"
        )

    rule_id = str(data["id"])
    expected_prefix = SOURCE_DIRS[record.category]
    if not rule_id.startswith(expected_prefix):
        raise RulebookValidationError(
            f"{record.path}: id {rule_id!r} must start with {expected_prefix!r}"
        )

    status = str(data["status"])
    if status not in ALLOWED_STATUS:
        raise RulebookValidationError(
            f"{record.path}: status {status!r} must be one of {sorted(ALLOWED_STATUS)}"
        )

    if not isinstance(data["markets"], list) or not data["markets"]:
        raise RulebookValidationError(f"{record.path}: markets must be a non-empty list")

    if record.category == "hard" and not isinstance(data.get("enforcement"), dict):
        raise RulebookValidationError(
            f"{record.path}: hard rules must define machine-readable enforcement"
        )


def validate_references(records: list[SourceRecord]) -> None:
    """Validate cross-record references after all records are loaded."""
    by_id = {record.rule_id: record for record in records}
    if len(by_id) != len(records):
        seen: set[str] = set()
        duplicates: set[str] = set()
        for record in records:
            if record.rule_id in seen:
                duplicates.add(record.rule_id)
            seen.add(record.rule_id)
        raise RulebookValidationError(
            f"duplicate rulebook IDs: {', '.join(sorted(duplicates))}"
        )

    for record in records:
        data = record.data
        if record.category == "playbooks":
            for hard_id in data.get("required_hard_rules", []):
                if hard_id not in by_id:
                    raise RulebookValidationError(
                        f"{record.path}: missing required hard rule {hard_id}"
                    )
                if by_id[hard_id].category != "hard":
                    raise RulebookValidationError(
                        f"{record.path}: {hard_id} is not a hard rule"
                    )

        if record.category == "cases":
            playbook_id = data.get("playbook_id")
            if playbook_id and playbook_id not in by_id:
                raise RulebookValidationError(
                    f"{record.path}: missing playbook {playbook_id}"
                )
            for ref_id in data.get("rule_citations", []) + data.get("referenced_rules", []):
                if ref_id not in by_id:
                    raise RulebookValidationError(
                        f"{record.path}: missing referenced rule {ref_id}"
                    )

