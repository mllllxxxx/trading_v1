from __future__ import annotations

import pytest

from execution import MT5Adapter, OandaAdapter, PaperExecutionAdapter
from execution.base import ExecutionAdapterError
from schemas.models import CompiledOrder


def _compiled_order() -> CompiledOrder:
    return CompiledOrder(
        symbol="BTC-USDT-SWAP",
        side="buy",
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        risk_pct_equity=0.01,
        risk_amount_usd=100.0,
        position_size_units=20.0,
        position_notional_usd=2000.0,
    )


def test_paper_adapter_accepts_compiled_order_without_broker_call() -> None:
    adapter = PaperExecutionAdapter()

    result = adapter.place_bracket_order(_compiled_order(), idempotency_key="dec-1")

    assert result.status == "paper_accepted"
    assert result.broker_order_id is None
    assert result.raw["broker_calls"] == 0
    assert adapter.get_account()["live"] is False
    assert adapter.get_positions()[0]["idempotency_key"] == "dec-1"


def test_paper_adapter_rejects_raw_ticket_payload() -> None:
    adapter = PaperExecutionAdapter()

    with pytest.raises(ExecutionAdapterError, match="CompiledOrder"):
        adapter.place_bracket_order({"action": "OPEN_LONG"})  # type: ignore[arg-type]


def test_paper_adapter_rejects_live_mode() -> None:
    with pytest.raises(ExecutionAdapterError, match="only supports"):
        PaperExecutionAdapter(mode="live")


@pytest.mark.parametrize("adapter_cls", [OandaAdapter, MT5Adapter])
def test_forex_stubs_cannot_place_orders(adapter_cls) -> None:
    adapter = adapter_cls()

    assert adapter.get_account()["live"] is False
    with pytest.raises(NotImplementedError):
        adapter.place_bracket_order(_compiled_order())
