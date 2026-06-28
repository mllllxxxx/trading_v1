"""Pytest fixtures for trading tests.

Isolates the journal DATA_DIR per test so concurrent tests don't clobber each
other's journal files. Mocks ccxt / yfinance / OpenAI by default.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRADING_DIR = REPO_ROOT
AUTO_DIR = TRADING_DIR / "auto"

if str(TRADING_DIR) not in sys.path:
    sys.path.insert(0, str(TRADING_DIR))
if str(AUTO_DIR) not in sys.path:
    sys.path.insert(0, str(AUTO_DIR))


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect journal DATA_DIR to a temp directory for the test."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("VIBE_TRADING_HOME", str(data))
    yield data


@pytest.fixture
def isolated_journal(tmp_data_dir):
    """Import journal with DATA_DIR already redirected to tmp."""
    import importlib
    import journal  # type: ignore
    importlib.reload(journal)
    yield journal
    importlib.reload(journal)