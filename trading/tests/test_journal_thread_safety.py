"""Tests for journal.py thread-safety and corruption handling (H1, H4)."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest


def _make_position(symbol: str = "BTC-USDT") -> dict:
    return {
        "symbol": symbol,
        "side": "buy",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "position_size": 0.1,
        "risk_usd": 50.0,
    }


class TestJournalThreadSafety:
    """H1: All writers (add/remove positions, write stats) must be atomic."""

    def test_concurrent_add_positions_no_loss(self, isolated_journal, tmp_data_dir):
        """20 threads × 5 adds = 100 positions, none lost."""
        journal = isolated_journal
        journal.ensure_dirs()

        def add_one(i: int) -> None:
            journal.add_position(_make_position(f"SYM-{i}"))

        with ThreadPoolExecutor(max_workers=20) as ex:
            list(ex.map(add_one, range(50)))

        positions = journal.read_positions()
        assert len(positions) == 50
        symbols = {p["symbol"] for p in positions}
        assert len(symbols) == 50

    def test_concurrent_add_then_remove(self, isolated_journal):
        """Concurrent add + remove should never leave duplicates or lose state."""
        journal = isolated_journal
        journal.ensure_dirs()

        # Pre-populate
        for i in range(10):
            journal.add_position(_make_position(f"SYM-{i}"))

        results = []

        def add(i: int) -> None:
            journal.add_position(_make_position(f"NEW-{i}"))

        def rem(symbol: str) -> None:
            removed = journal.remove_position(symbol)
            results.append(removed is not None)

        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = []
            for i in range(10):
                futs.append(ex.submit(add, i))
            for i in range(10):
                futs.append(ex.submit(rem, f"SYM-{i}"))
            for f in futs:
                f.result()

        final = journal.read_positions()
        # All 10 NEW-* added, all 10 SYM-* removed
        syms = {p["symbol"] for p in final}
        assert all(s.startswith("NEW-") for s in syms)
        assert len(syms) == 10
        assert all(results)  # all remove calls returned a position

    def test_write_stats_atomic(self, isolated_journal):
        """Concurrent write_stats must not corrupt the file."""
        journal = isolated_journal
        journal.ensure_dirs()

        def write_one(i: int) -> None:
            journal.write_stats({"total_trades": i, "wins": i, "losses": 0,
                                  "total_pnl_usd": float(i)})

        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(write_one, range(30)))

        # Must be parseable
        stats = journal.read_stats()
        assert "total_trades" in stats
        assert isinstance(stats["total_trades"], int)

    def test_append_decisions_jsonl_safe(self, isolated_journal):
        """Concurrent append_decision must produce N well-formed JSON lines."""
        journal = isolated_journal
        journal.ensure_dirs()

        def append_one(i: int) -> None:
            journal.append_decision("test", {"i": i})

        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(append_one, range(100)))

        with journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) == 100
        # Every line must parse
        for line in lines:
            obj = json.loads(line)
            assert "ts" in obj
            assert obj["type"] == "test"


class TestJournalCorruption:
    """H4: read_positions must fail loud on corrupt JSON, not silently return []."""

    def test_corrupt_positions_raises(self, isolated_journal):
        journal = isolated_journal
        journal.ensure_dirs()
        # Write garbage
        journal.POSITIONS_FILE.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(journal.JournalCorruptError):
            journal.read_positions()

    def test_corrupt_positions_creates_backup(self, isolated_journal, tmp_data_dir):
        journal = isolated_journal
        journal.ensure_dirs()
        journal.POSITIONS_FILE.write_text("garbage", encoding="utf-8")

        with pytest.raises(journal.JournalCorruptError):
            journal.read_positions()

        backups = list(tmp_data_dir.glob("journal/positions.corrupt.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "garbage"

    def test_repeated_corrupt_reads_reuse_content_backup(
        self, isolated_journal, tmp_data_dir
    ):
        """Dashboard polling must not create one backup per failed read."""
        journal = isolated_journal
        journal.ensure_dirs()
        journal.POSITIONS_FILE.write_text("garbage", encoding="utf-8")

        for _ in range(5):
            with pytest.raises(journal.JournalCorruptError):
                journal.read_positions()

        backups = list(tmp_data_dir.glob("journal/positions.corrupt.*.bak"))
        assert len(backups) == 1
        assert "sha256-" in backups[0].name

    def test_write_positions_uses_atomic_replace(self, isolated_journal, monkeypatch):
        journal = isolated_journal
        journal.ensure_dirs()
        replacements: list[tuple[object, object]] = []
        original_replace = journal.os.replace

        def capture_replace(source, target):
            replacements.append((source, target))
            return original_replace(source, target)

        monkeypatch.setattr(journal.os, "replace", capture_replace)
        journal.write_positions([_make_position("BTC-USDT")])

        assert len(replacements) == 1
        source, target = replacements[0]
        assert target == journal.POSITIONS_FILE
        assert source.parent == journal.POSITIONS_FILE.parent
        assert source.name.startswith("positions.json.tmp.")
        assert journal.read_positions()[0]["symbol"] == "BTC-USDT"
        assert not list(journal.JOURNAL_DIR.glob("positions.json.tmp.*"))

    def test_empty_positions_returns_list(self, isolated_journal):
        """Backward compat: first run with empty file returns []."""
        journal = isolated_journal
        journal.ensure_dirs()
        result = journal.read_positions()
        assert result == []

    def test_valid_positions_returns_list(self, isolated_journal):
        journal = isolated_journal
        journal.ensure_dirs()
        journal.add_position(_make_position("BTC-USDT"))
        result = journal.read_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "BTC-USDT"

    def test_ensure_dirs_preserves_existing_positions(self, isolated_journal):
        journal = isolated_journal
        journal.ensure_dirs()
        journal.add_position(_make_position("BTC-USDT"))

        journal.ensure_dirs()

        result = journal.read_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "BTC-USDT"
