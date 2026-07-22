"""Execution adapter interfaces and safe paper implementations."""

from .base import ExecutionAdapter, ExecutionAdapterError
from .okx_demo_adapter import OKXDemoExecutionAdapter
from .paper_adapter import PaperExecutionAdapter
from .stubs import MT5Adapter, OandaAdapter

__all__ = [
    "ExecutionAdapter",
    "ExecutionAdapterError",
    "MT5Adapter",
    "OandaAdapter",
    "OKXDemoExecutionAdapter",
    "PaperExecutionAdapter",
]
