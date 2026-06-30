"""Execution adapter interfaces and safe paper implementations."""

from .base import ExecutionAdapter, ExecutionAdapterError
from .paper_adapter import PaperExecutionAdapter
from .stubs import MT5Adapter, OandaAdapter

__all__ = [
    "ExecutionAdapter",
    "ExecutionAdapterError",
    "MT5Adapter",
    "OandaAdapter",
    "PaperExecutionAdapter",
]
