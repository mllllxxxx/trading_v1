"""OKX demo/testnet execution adapter for compiled futures orders."""

from __future__ import annotations

import os
from types import ModuleType
from typing import Any

from schemas.models import CompiledOrder, OrderResult

from .base import ExecutionAdapterError, require_compiled_order


class OKXDemoExecutionAdapter:
    """Submit verified compiled orders to OKX demo/testnet only."""

    def __init__(
        self,
        *,
        mode: str = "demo",
        bracket_module: ModuleType | Any | None = None,
        dry_run: bool = False,
    ) -> None:
        mode_normalized = mode.strip().lower()
        if mode_normalized not in {"demo", "testnet"}:
            raise ExecutionAdapterError("OKXDemoExecutionAdapter only supports demo/testnet mode")
        self.mode = mode_normalized
        self.dry_run = dry_run
        self._bracket_module = bracket_module

    def get_account(self) -> dict[str, Any]:
        """Return redacted OKX demo adapter metadata."""
        module = self._module()
        cfg = module.load_okx_config()
        return {
            "broker": "okx",
            "mode": self.mode,
            "live": False,
            "testnet": bool(cfg.get("testnet", False)),
            "sandbox": _env_flag_true("OKX_SANDBOX"),
            "api_key_set": bool(cfg.get("api_key")),
            "dry_run": self.dry_run,
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """Position polling is handled by the existing monitor layer."""
        return []

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Return an adapter quote placeholder without private broker calls."""
        return {"symbol": symbol, "broker": "okx", "mode": self.mode, "source": "adapter_placeholder"}

    def place_bracket_order(
        self,
        order: CompiledOrder,
        *,
        idempotency_key: str | None = None,
    ) -> OrderResult:
        """Validate and place one OKX demo futures bracket order."""
        compiled = require_compiled_order(order)
        module = self._module()
        cfg = module.load_okx_config()
        self._require_demo_guard(cfg)

        capital = _capital_from_order(compiled)
        metadata = _contract_trade_metadata(module, cfg, compiled.symbol)
        proposal = module.compute_bracket_futures(
            compiled.symbol,
            compiled.side,
            compiled.entry,
            compiled.stop_loss,
            compiled.take_profit,
            capital,
            risk_pct=compiled.risk_pct_equity,
            **metadata,
        )
        violations = module.validate_futures(proposal)
        if violations:
            raise ExecutionAdapterError(f"OKX demo bracket validation failed: {violations}")

        result = module.place_orders_futures(proposal, cfg, dry_run=self.dry_run)
        raw = {
            "broker_calls": 0 if self.dry_run else 1,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "idempotency_key": idempotency_key,
            "proposal": proposal,
            "response": result,
        }
        if self.dry_run:
            return OrderResult(
                status="okx_demo_dry_run",
                broker_order_id=None,
                raw=raw,
            )
        if not bool(result.get("ok", False)):
            raise ExecutionAdapterError(str(result.get("error") or result))
        return OrderResult(
            status="okx_demo_accepted",
            broker_order_id=_broker_order_id(result),
            raw=raw,
        )

    def close_position(self, position_id: str) -> OrderResult:
        """Closing is intentionally left to the existing monitor/reconciler."""
        raise NotImplementedError("OKX demo close_position is handled by monitor/reconciliation")

    def _module(self) -> Any:
        if self._bracket_module is not None:
            return self._bracket_module
        try:
            from brackets import okx_futures_bracket
        except ImportError as exc:  # pragma: no cover - direct package topology fallback
            raise ExecutionAdapterError("okx_futures_bracket module is unavailable") from exc
        self._bracket_module = okx_futures_bracket
        return okx_futures_bracket

    def _require_demo_guard(self, cfg: dict[str, Any]) -> None:
        if not cfg.get("testnet", False) or not _env_flag_true("OKX_TESTNET"):
            raise ExecutionAdapterError("OKX demo adapter refuses execution when OKX_TESTNET is not true")
        if not _env_flag_true("OKX_SANDBOX"):
            raise ExecutionAdapterError("OKX demo adapter refuses execution when OKX_SANDBOX is not true")
        missing = [
            name
            for name, key in (
                ("OKX_API_KEY", "api_key"),
                ("OKX_API_SECRET", "api_secret"),
                ("OKX_PASSPHRASE", "passphrase"),
            )
            if not str(cfg.get(key, "")).strip()
        ]
        if missing:
            raise ExecutionAdapterError(f"OKX demo credentials missing: {', '.join(missing)}")


def _capital_from_order(order: CompiledOrder) -> float:
    if order.risk_pct_equity > 0:
        return max(order.position_notional_usd, order.risk_amount_usd / order.risk_pct_equity)
    return _runtime_equity(10_000.0)


def _runtime_equity(default: float) -> float:
    try:
        from auto.equity import runtime_equity  # type: ignore

        return runtime_equity(default)
    except Exception:
        try:
            return float(os.getenv("AUTO_CAPITAL", str(default)))
        except ValueError:
            return default


def _contract_trade_metadata(module: Any, cfg: dict[str, Any], symbol: str) -> dict[str, float]:
    """Return broker contract facts for futures sizing.

    The real OKX bracket module exposes `fetch_contract_trade_metadata`. Test
    doubles may omit it, in which case no override is passed.
    """
    fetcher = getattr(module, "fetch_contract_trade_metadata", None)
    if not callable(fetcher):
        return {}
    try:
        raw = fetcher(cfg, symbol)
    except Exception as exc:  # noqa: BLE001
        raise ExecutionAdapterError(f"OKX contract metadata unavailable for {symbol}: {exc}") from exc
    contract_size = _positive_float(raw.get("contract_size"))
    min_qty = _positive_float(raw.get("min_qty"))
    if contract_size is None or min_qty is None:
        raise ExecutionAdapterError(f"OKX contract metadata incomplete for {symbol}: {raw}")
    metadata = {"contract_size": contract_size, "min_qty": min_qty}
    qty_step = _positive_float(raw.get("qty_step"))
    if qty_step is not None:
        metadata["qty_step"] = qty_step
    return metadata


def _positive_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _env_flag_true(name: str) -> bool:
    return os.getenv(name, "true").strip().lower() in {"1", "true", "yes", "on"}


def _broker_order_id(result: dict[str, Any]) -> str | None:
    raw = result.get("algo_order_id") or result.get("ordId")
    if raw:
        return str(raw)
    data = result.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return str(first.get("algoId") or first.get("ordId") or "") or None
    return None
