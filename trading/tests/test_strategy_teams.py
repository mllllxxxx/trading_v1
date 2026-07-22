from __future__ import annotations

from strategy_teams import build_team_dashboard, infer_team_id, resolve_team


def test_resolve_team_accepts_id_and_scanner_source() -> None:
    assert resolve_team("momentum").scanner_source == "team_momentum_scanner"
    assert resolve_team("team_mean_reversion_scanner").team_id == "mean_reversion"


def test_strategy_team_skill_profiles_are_distinct() -> None:
    momentum = resolve_team("momentum")
    mean_reversion = resolve_team("mean_reversion")
    volatility = resolve_team("volatility_breakout")

    assert momentum.preferred_playbook_ids == ("PB_CRYPTO_TREND_CONTINUATION_001",)
    assert mean_reversion.preferred_playbook_ids == ("PB_CRYPTO_MEAN_REVERSION_001",)
    assert volatility.preferred_playbook_ids == ("PB_CRYPTO_BREAKOUT_PULLBACK_001",)
    assert "SOFT_STRATEGY_TEAM_001" in momentum.required_soft_policy_ids
    assert "strong trends" in mean_reversion.llm_guidance
    assert "range expansion" in volatility.entry_style.lower()


def test_build_team_dashboard_uses_sample_adjusted_competition_metrics() -> None:
    positions = [
        {
            "symbol": "BTC-USDT",
            "team_id": "momentum",
            "unrealized_pnl": 1.25,
        }
    ]
    closed = [
        {"team_id": "berkshire", "closed_at": "2026-07-01T00:00:00Z", "pnl_usd": 5},
        {"team_id": "berkshire", "closed_at": "2026-07-02T00:00:00Z", "pnl_usd": -2},
        {"team_id": "momentum", "closed_at": "2026-07-03T00:00:00Z", "pnl_usd": -3},
    ]

    teams = {team["team_id"]: team for team in build_team_dashboard(positions, closed)}

    assert teams["berkshire"]["winrate"] == 50.0
    assert teams["berkshire"]["realized_pnl_usd"] == 3.0
    assert teams["berkshire"]["rank"] == 1
    assert teams["berkshire"]["ranking_status"] == "provisional"
    assert teams["berkshire"]["sample_reliability"] == round(2 / 30, 4)
    assert teams["berkshire"]["competition_score"] > teams["momentum"]["competition_score"]
    assert teams["momentum"]["open_positions"] == 1
    assert teams["momentum"]["unrealized_pnl_usd"] == 1.25
    assert teams["momentum"]["max_drawdown_usd"] == 3.0


def test_infer_team_id_reads_nested_source_context() -> None:
    record = {
        "open_rationale": {
            "source_context": {
                "source": "team_volatility_breakout_scanner",
            }
        }
    }

    assert infer_team_id(record) == "volatility_breakout"


def test_drawdown_percentage_is_not_diluted_by_later_equity_high() -> None:
    teams = {
        team["team_id"]: team
        for team in build_team_dashboard(
            [],
            [
                {
                    "team_id": "momentum",
                    "closed_at": "2026-07-01T00:00:00Z",
                    "pnl_usd": -100,
                },
                {
                    "team_id": "momentum",
                    "closed_at": "2026-07-02T00:00:00Z",
                    "pnl_usd": 1000,
                },
            ],
        )
    }

    assert teams["momentum"]["max_drawdown_usd"] == 100.0
    assert teams["momentum"]["max_drawdown_pct"] == 0.5
