from __future__ import annotations

import json

import pytest

from market_dossier import (
    MarketDossierBuildError,
    build_market_dossier,
    classify_candidate_direction,
    dossier_hash,
)
from schemas.models import DataQuality


def test_build_market_dossier_returns_json_serializable_short_context() -> None:
    dossier = build_market_dossier(
        symbol="BTC-USDT-SWAP",
        current_price=65000,
        confluence={"total_score": -3},
        regime={"name": "TRENDING_DOWN"},
        min_confluence=2,
        data_source="okx",
        data_age_s=12,
    )

    payload = dossier.to_dict()
    assert payload["candidate_direction"] == "short"
    assert payload["data_quality"] == "A"
    assert payload["trend_state"] == "down"
    assert json.loads(json.dumps(payload))["symbol"] == "BTC-USDT-SWAP"
    assert len(dossier_hash(dossier)) == 64


@pytest.mark.parametrize(
    ("score", "expected"),
    [(4, "long"), (-4, "short"), (1, "none"), (-1, "none"), (0, "none")],
)
def test_classify_candidate_direction_uses_absolute_threshold(
    score: float,
    expected: str,
) -> None:
    assert classify_candidate_direction(score, min_confluence=2) == expected


def test_missing_confluence_score_fails_closed() -> None:
    with pytest.raises(MarketDossierBuildError, match="confluence score"):
        build_market_dossier(
            symbol="BTC-USDT-SWAP",
            current_price=65000,
            confluence={},
            regime={"name": "TRENDING_UP"},
        )


def test_negative_current_price_fails_closed() -> None:
    with pytest.raises(MarketDossierBuildError, match="current_price"):
        build_market_dossier(
            symbol="BTC-USDT-SWAP",
            current_price=-1,
            confluence=3,
            regime={"name": "TRENDING_UP"},
        )


def test_missing_regime_fails_closed() -> None:
    with pytest.raises(MarketDossierBuildError, match="regime"):
        build_market_dossier(
            symbol="BTC-USDT-SWAP",
            current_price=65000,
            confluence=3,
            regime=None,
        )


def test_stale_data_marks_quality_c_with_warning() -> None:
    dossier = build_market_dossier(
        symbol="BTC-USDT-SWAP",
        current_price=65000,
        confluence=3,
        regime="TRENDING_UP",
        data_source="okx",
        data_age_s=90,
        max_data_age_s=30,
    )

    assert dossier.data_quality is DataQuality.C
    assert "stale_market_data" in dossier.portfolio_exposure["warnings"]


def test_corrupt_journal_reader_fails_closed() -> None:
    def broken_reader() -> list[dict]:
        raise RuntimeError("corrupt")

    with pytest.raises(MarketDossierBuildError, match="journal"):
        build_market_dossier(
            symbol="BTC-USDT-SWAP",
            current_price=65000,
            confluence=3,
            regime="TRENDING_UP",
            open_positions_reader=broken_reader,
        )
