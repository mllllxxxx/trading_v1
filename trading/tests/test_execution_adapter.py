from __future__ import annotations

import pytest

from execution import MT5Adapter, OKXDemoExecutionAdapter, OandaAdapter, PaperExecutionAdapter
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


def _near_compiled_order() -> CompiledOrder:
    return CompiledOrder(
        symbol="NEAR-USDT-SWAP",
        side="buy",
        entry=1.93,
        stop_loss=1.88,
        take_profit=2.03,
        risk_pct_equity=0.005,
        risk_amount_usd=1.0,
        position_size_units=20.0,
        position_notional_usd=38.6,
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


def test_okx_demo_adapter_rejects_live_like_env(monkeypatch) -> None:
    monkeypatch.setenv("OKX_TESTNET", "false")
    monkeypatch.setenv("OKX_SANDBOX", "true")

    adapter = OKXDemoExecutionAdapter(bracket_module=_FakeOkxBracket())

    with pytest.raises(ExecutionAdapterError, match="OKX_TESTNET"):
        adapter.place_bracket_order(_compiled_order())


def test_okx_demo_adapter_rejects_missing_credentials(monkeypatch) -> None:
    monkeypatch.setenv("OKX_TESTNET", "true")
    monkeypatch.setenv("OKX_SANDBOX", "true")

    adapter = OKXDemoExecutionAdapter(bracket_module=_FakeOkxBracket(api_key=""))

    with pytest.raises(ExecutionAdapterError, match="OKX_API_KEY"):
        adapter.place_bracket_order(_compiled_order())


def test_okx_demo_adapter_maps_compiled_order_to_testnet_bracket(monkeypatch) -> None:
    monkeypatch.setenv("OKX_TESTNET", "true")
    monkeypatch.setenv("OKX_SANDBOX", "true")
    fake = _FakeOkxBracket()
    adapter = OKXDemoExecutionAdapter(bracket_module=fake)

    result = adapter.place_bracket_order(_compiled_order(), idempotency_key="dec-okx-1")

    assert result.status == "okx_demo_accepted"
    assert result.broker_order_id == "algo-123"
    assert fake.seen["symbol"] == "BTC-USDT-SWAP"
    assert fake.seen["risk_pct"] == 0.01
    assert result.raw["broker_calls"] == 1
    assert result.raw["idempotency_key"] == "dec-okx-1"


def test_okx_demo_adapter_passes_exchange_contract_metadata(monkeypatch) -> None:
    monkeypatch.setenv("OKX_TESTNET", "true")
    monkeypatch.setenv("OKX_SANDBOX", "true")
    fake = _FakeOkxBracket(contract_metadata={"contract_size": 10, "min_qty": 0.1})
    adapter = OKXDemoExecutionAdapter(bracket_module=fake)

    result = adapter.place_bracket_order(_near_compiled_order(), idempotency_key="dec-near-1")

    assert result.status == "okx_demo_accepted"
    assert fake.seen["symbol"] == "NEAR-USDT-SWAP"
    assert fake.seen["contract_size"] == 10
    assert fake.seen["min_qty"] == 0.1


@pytest.mark.parametrize("adapter_cls", [OandaAdapter, MT5Adapter])
def test_forex_stubs_cannot_place_orders(adapter_cls) -> None:
    adapter = adapter_cls()

    assert adapter.get_account()["live"] is False
    with pytest.raises(NotImplementedError):
        adapter.place_bracket_order(_compiled_order())


class _FakeOkxBracket:
    def __init__(
        self,
        *,
        api_key: str = "key",
        contract_metadata: dict[str, float] | None = None,
    ) -> None:
        self.api_key = api_key
        self.contract_metadata = contract_metadata
        self.seen: dict[str, object] = {}

    def load_okx_config(self) -> dict:
        return {
            "api_key": self.api_key,
            "api_secret": "secret",
            "passphrase": "pass",
            "testnet": True,
            "sandbox": True,
        }

    def compute_bracket_futures(
        self,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        capital: float,
        risk_pct: float,
        contract_size: float | None = None,
        min_qty: float | None = None,
    ) -> dict:
        self.seen = {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "capital": capital,
            "risk_pct": risk_pct,
            "contract_size": contract_size,
            "min_qty": min_qty,
        }
        return {
            "symbol": symbol,
            "side": side,
            "is_long": side == "buy",
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_notional": 2000.0,
            "actual_risk_usd": 100.0,
            "rr_ratio": 2.0,
        }

    def fetch_contract_trade_metadata(self, _cfg: dict, _symbol: str) -> dict[str, float]:
        if self.contract_metadata is None:
            return {"contract_size": 1.0, "min_qty": 1.0}
        return dict(self.contract_metadata)

    def validate_futures(self, _proposal: dict) -> list[str]:
        return []

    def place_orders_futures(self, proposal: dict, cfg: dict, dry_run: bool = False) -> dict:
        return {
            "ok": True,
            "algo_order_id": "algo-123",
            "symbol": proposal["symbol"],
            "testnet": cfg["testnet"],
            "dry_run": dry_run,
        }
