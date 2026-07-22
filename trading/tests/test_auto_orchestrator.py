from __future__ import annotations

import auto


def test_legacy_scheduler_enabled_flag_defaults_on(monkeypatch) -> None:
    monkeypatch.delenv("AUTO_LEGACY_SCHEDULER_ENABLED", raising=False)

    assert auto.legacy_scheduler_enabled() is True


def test_legacy_scheduler_enabled_flag_can_disable_scheduler(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_LEGACY_SCHEDULER_ENABLED", "false")

    assert auto.legacy_scheduler_enabled() is False
