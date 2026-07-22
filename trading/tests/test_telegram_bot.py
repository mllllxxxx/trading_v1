"""Behavior tests for Telegram auth, callbacks, and alert noise control."""
from __future__ import annotations

import importlib
from pathlib import Path


def _load_bot(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_USER_ID", "456")
    import telegram

    return importlib.reload(telegram)


def test_private_operator_requires_chat_and_user(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    message = {
        "chat": {"id": 123, "type": "private"},
        "from": {"id": 456},
    }

    assert telegram._is_authorized(message) is True
    assert telegram._is_authorized({**message, "from": {"id": 999}}) is False
    assert telegram._is_authorized({**message, "chat": {"id": 999, "type": "private"}}) is False


def test_private_chat_can_safely_inherit_user_id(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
    import telegram

    telegram = importlib.reload(telegram)
    assert telegram._is_authorized(
        {"chat": {"id": 123, "type": "private"}, "from": {"id": 123}}
    )
    assert not telegram._is_authorized(
        {"chat": {"id": 123, "type": "group"}, "from": {"id": 123}}
    )


def test_callback_routes_only_read_only_dashboard_views(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    routed: list[tuple[str, int, str | None, bool]] = []
    answered: list[str] = []
    monkeypatch.setattr(
        telegram,
        "_show_view",
        lambda view, page=0, detail_key=None, acknowledge=True: routed.append(
            (view, page, detail_key, acknowledge)
        ),
    )
    monkeypatch.setattr(telegram, "_answer_callback", lambda callback_id, text="": answered.append(callback_id))

    telegram._handle_callback(
        {
            "id": "callback-1",
            "from": {"id": 456},
            "message": {"chat": {"id": 123, "type": "private"}},
            "data": "dash:teams:0",
        }
    )

    assert answered == ["callback-1"]
    assert routed == [("teams", 0, None, False)]


def test_decisions_refresh_dashboard_without_push_spam(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)

    class FakeDashboard:
        dirty = 0

        def mark_dirty(self) -> None:
            self.dirty += 1

    fake = FakeDashboard()
    sent: list[str] = []
    monkeypatch.setattr(telegram, "_DASHBOARD", fake)
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text) or True)

    telegram._on_alert("final_ticket", {"symbol": "BTC-USDT", "action": "HOLD"})

    assert fake.dirty == 1
    assert sent == []


def test_llm_budget_pushes_only_at_eighty_percent_or_more(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text) or True)

    telegram._on_alert("llm_cost_alert", {"pct": 50, "cost_usd": 0.1, "cap_usd": 0.2})
    telegram._on_alert("llm_cost_alert", {"pct": 80, "cost_usd": 0.16, "cap_usd": 0.2})

    assert len(sent) == 1
    assert "80%" in sent[0]


def test_dashboard_creates_pins_and_then_edits_one_persisted_message(
    monkeypatch,
    tmp_path: Path,
) -> None:
    telegram = _load_bot(monkeypatch)
    monkeypatch.setattr(telegram.journal, "DATA_DIR", tmp_path)
    controller = telegram.TelegramDashboardController()
    snapshots = [
        {"running": True, "timestamp": "2026-07-19T12:00:00+07:00"},
        {"running": True, "timestamp": "2026-07-19T12:01:00+07:00"},
    ]
    monkeypatch.setattr(controller.provider, "load", lambda: snapshots.pop(0))
    sent: list[str] = []
    edited: list[int] = []
    pinned: list[int] = []
    monkeypatch.setattr(
        telegram,
        "_send_message",
        lambda text, **kwargs: sent.append(text) or 77,
    )
    monkeypatch.setattr(
        telegram,
        "_edit_message",
        lambda message_id, rendered: edited.append(message_id) or True,
    )
    monkeypatch.setattr(
        telegram,
        "_pin_message",
        lambda message_id: pinned.append(message_id) or True,
    )

    assert controller.refresh(force=True) is True
    assert controller.refresh(force=True) is True

    assert len(sent) == 1
    assert pinned == [77]
    assert edited == [77]
    assert controller.store.load().message_id == 77


def test_pause_blocks_new_entries_but_keeps_dashboard_refreshable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    telegram = _load_bot(monkeypatch)

    class FakeDashboard:
        dirty = 0

        def mark_dirty(self) -> None:
            self.dirty += 1

    fake = FakeDashboard()
    kill_switch = tmp_path / "STOP"
    decisions: list[tuple[str, dict]] = []
    sent: list[str] = []
    monkeypatch.setattr(telegram.journal, "KILL_SWITCH", kill_switch)
    monkeypatch.setattr(
        telegram.journal,
        "append_decision",
        lambda event_type, payload: decisions.append((event_type, payload)),
    )
    monkeypatch.setattr(telegram, "_DASHBOARD", fake)
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text) or True)

    telegram._handle_pause()

    assert kill_switch.exists()
    assert fake.dirty == 1
    assert decisions[0][0] == "telegram_pause"
    assert sent


def test_refresh_failure_is_contained_and_next_attempt_recovers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    telegram = _load_bot(monkeypatch)
    monkeypatch.setattr(telegram.journal, "DATA_DIR", tmp_path)
    controller = telegram.TelegramDashboardController()
    outcomes: list[Exception | bool] = [RuntimeError("broken snapshot"), True]
    journaled: list[tuple[str, dict]] = []

    def flaky_refresh(*, force: bool = False) -> bool:  # noqa: ARG001
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(controller, "refresh", flaky_refresh)
    monkeypatch.setattr(
        telegram.journal,
        "append_decision",
        lambda event_type, payload: journaled.append((event_type, payload)),
    )

    assert controller._refresh_safely() is False
    assert controller._refresh_safely() is True

    assert journaled[0][0] == "telegram_dashboard_refresh_error"
    assert controller._last_refresh_error == ""


def test_authorized_unknown_text_returns_command_help(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text) or True)

    handled = telegram._handle_message(
        {
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456},
            "text": "hello bot",
        }
    )

    assert handled is True
    assert len(sent) == 1
    assert "/help" in sent[0]


def test_typed_dashboard_command_refreshes_now_and_acknowledges(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    calls: list[tuple[str, int, str | None, bool]] = []
    sent: list[str] = []

    class FakeDashboard:
        def set_view(
            self,
            view: str,
            page: int = 0,
            detail_key: str | None = None,
            *,
            refresh_now: bool = False,
        ) -> bool:
            calls.append((view, page, detail_key, refresh_now))
            return True

    monkeypatch.setattr(telegram, "_DASHBOARD", FakeDashboard())
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text) or True)

    assert telegram._handle_status() is True

    assert calls == [("overview", 0, None, True)]
    assert len(sent) == 1
    assert "Tổng quan" in sent[0]


def test_typed_dashboard_command_reports_refresh_failure(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    sent: list[str] = []

    class FakeDashboard:
        def set_view(self, *args, **kwargs) -> bool:
            return False

    monkeypatch.setattr(telegram, "_DASHBOARD", FakeDashboard())
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text) or True)

    assert telegram._handle_positions() is False
    assert "chưa cập nhật được" in sent[0]


def test_supported_command_journals_receipt_and_outcome(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(telegram, "COMMANDS", {"/dashboard": lambda: True})
    monkeypatch.setattr(
        telegram.journal,
        "append_decision",
        lambda event_type, payload: events.append((event_type, payload)),
    )

    assert telegram._handle_message(
        {
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456},
            "text": "/dashboard",
        }
    )

    assert [payload["status"] for _, payload in events] == ["received", "succeeded"]
    assert all(event_type == "telegram_command" for event_type, _ in events)


def test_register_commands_uses_telegram_command_menu(monkeypatch) -> None:
    telegram = _load_bot(monkeypatch)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        telegram,
        "_api_request",
        lambda method, payload: calls.append((method, payload)) or {"ok": True},
    )

    assert telegram._register_commands() is True
    assert calls[0][0] == "setMyCommands"
    assert {item["command"] for item in calls[0][1]["commands"]} >= {
        "dashboard",
        "status",
        "positions",
        "refresh",
    }
