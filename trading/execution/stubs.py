"""Inert forex execution adapter stubs."""

from __future__ import annotations

from schemas.models import CompiledOrder, OrderResult


class _InertBrokerStub:
    broker_name = "stub"

    def get_account(self) -> dict:
        """Return inert adapter metadata."""
        return {"broker": self.broker_name, "implemented": False, "live": False}

    def get_positions(self) -> list[dict]:
        """No positions are available for inert stubs."""
        return []

    def get_quote(self, symbol: str) -> dict:
        """Quote retrieval is not implemented for inert stubs."""
        raise NotImplementedError(f"{self.broker_name} quote adapter is not implemented")

    def place_bracket_order(
        self,
        order: CompiledOrder,
        *,
        idempotency_key: str | None = None,
    ) -> OrderResult:
        """Order placement is intentionally unavailable."""
        raise NotImplementedError(f"{self.broker_name} execution adapter is not implemented")

    def close_position(self, position_id: str) -> OrderResult:
        """Position closing is intentionally unavailable."""
        raise NotImplementedError(f"{self.broker_name} execution adapter is not implemented")


class OandaAdapter(_InertBrokerStub):
    """OANDA interface placeholder; live execution is not enabled."""

    broker_name = "oanda"


class MT5Adapter(_InertBrokerStub):
    """MT5 interface placeholder; live execution is not enabled."""

    broker_name = "mt5"
