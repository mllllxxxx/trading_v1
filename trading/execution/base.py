"""Execution adapter contract for compiled orders."""

from __future__ import annotations

from typing import Protocol

from schemas.models import CompiledOrder, OrderResult


class ExecutionAdapterError(RuntimeError):
    """Raised when an execution adapter refuses an unsafe request."""


class ExecutionAdapter(Protocol):
    """Broker boundary that accepts compiled orders only."""

    def get_account(self) -> dict:
        """Return account metadata for the adapter mode."""

    def get_positions(self) -> list[dict]:
        """Return positions known to the adapter."""

    def get_quote(self, symbol: str) -> dict:
        """Return a quote for a symbol."""

    def place_bracket_order(
        self,
        order: CompiledOrder,
        *,
        idempotency_key: str | None = None,
    ) -> OrderResult:
        """Place or simulate a compiled bracket order."""

    def close_position(self, position_id: str) -> OrderResult:
        """Close a known position."""


def require_compiled_order(order: CompiledOrder) -> CompiledOrder:
    """Validate that callers did not pass raw LLM or broker payloads."""
    if not isinstance(order, CompiledOrder):
        raise ExecutionAdapterError("execution adapters require CompiledOrder")
    return order
