"""Broker-free paper execution adapter."""

from __future__ import annotations

from schemas.models import CompiledOrder, OrderResult

from .base import ExecutionAdapterError, require_compiled_order


class PaperExecutionAdapter:
    """Dry-run adapter that records intent without placing broker orders."""

    def __init__(self, *, mode: str = "paper") -> None:
        mode_normalized = mode.strip().lower()
        if mode_normalized not in {"paper", "dry_run", "replay"}:
            raise ExecutionAdapterError("PaperExecutionAdapter only supports paper, dry_run, or replay mode")
        self.mode = mode_normalized
        self._positions: list[dict] = []

    def get_account(self) -> dict:
        """Return broker-free account metadata."""
        return {"mode": self.mode, "broker": "paper", "live": False}

    def get_positions(self) -> list[dict]:
        """Return simulated positions."""
        return list(self._positions)

    def get_quote(self, symbol: str) -> dict:
        """Return an intentionally minimal quote placeholder."""
        return {"symbol": symbol, "mode": self.mode, "source": "paper_adapter"}

    def place_bracket_order(
        self,
        order: CompiledOrder,
        *,
        idempotency_key: str | None = None,
    ) -> OrderResult:
        """Accept a compiled order into paper state without broker calls."""
        compiled = require_compiled_order(order)
        position = {
            "symbol": compiled.symbol,
            "side": compiled.side,
            "entry": compiled.entry,
            "stop_loss": compiled.stop_loss,
            "take_profit": compiled.take_profit,
            "position_size_units": compiled.position_size_units,
            "position_notional_usd": compiled.position_notional_usd,
            "idempotency_key": idempotency_key,
            "mode": self.mode,
        }
        self._positions.append(position)
        return OrderResult(
            status="paper_accepted",
            broker_order_id=None,
            raw={"broker_calls": 0, "position": position},
        )

    def close_position(self, position_id: str) -> OrderResult:
        """Close is simulated and does not call a broker."""
        return OrderResult(
            status="paper_closed",
            broker_order_id=None,
            raw={"broker_calls": 0, "position_id": position_id, "mode": self.mode},
        )
