"""Force LLM call with full 2.6K context using mock STRONG data."""
import sys
sys.path.insert(0, '/app/auto')
import json
import prompts
import brain
import journal

# Build mock STRONG data: confluence +3, regime TRENDING_UP, non-CHOPPY
confluence = {
    "total_score": 3,
    "weighted_score": 3.6,
    "bullish_tfs": 3,
    "bearish_tfs": 0,
    "direction_bias": "long",
    "timeframes": {
        "15m": {"trend": "UP", "momentum": "UP", "rsi": 58.3, "close": 64050},
        "1h":  {"trend": "UP", "momentum": "UP", "rsi": 55.1, "close": 64050},
        "4h":  {"trend": "UP", "momentum": "UP", "rsi": 52.8, "close": 64050},
        "1d":  {"trend": "UP", "momentum": "UP", "rsi": 48.2, "close": 64050},
        "1w":  {"trend": "UP", "momentum": "UP", "rsi": None, "close": 64050}
    }
}

# Mock regime output (real regime.py + indicators)
import subprocess
regime_real = json.loads(subprocess.run(
    ['python', '/app/regime/regime.py', '--symbol', 'BTC-USDT', '--json'],
    capture_output=True, text=True
).stdout)

# Override regime to non-CHOPPY for test
regime_real["regime"] = "TRENDING_UP"
regime_real["trend"] = "uptrend"
regime_real["regime_description"] = "Sustained uptrend - momentum alphas likely to work"
regime_real["indicators"]["range_to_net_ratio"] = 2.0
regime_real["indicators"]["direction_changes_10d"] = 1

print("=== Calling LLM with full 2.6K context ===")
print(f"Regime: {regime_real['regime']}")
print(f"Confluence: {confluence['total_score']:+d} (weighted {confluence['weighted_score']:+.2f})")
print(f"Direction: {confluence['direction_bias']}")
print(f"Technical indicators: {len(regime_real['technical_indicators'])} categories")
print()

# Build the full user prompt
system_prompt = prompts.build_system_prompt()
user_prompt = prompts.build_user_prompt(
    symbol="BTC-USDT",
    current_price=64050.0,
    regime=regime_real,
    confluence=confluence,
    open_positions=[],
    recent_trades=[],
    capital=10000,
    daily_pnl=0,
)

print(f"System prompt: {len(system_prompt)} chars")
print(f"User prompt: {len(user_prompt)} chars")
print(f"Total context: {len(system_prompt) + len(user_prompt)} chars")
print()

# Call LLM
try:
    decision = brain.call_brain(system_prompt, user_prompt)
    print("=== LLM Decision ===")
    print(json.dumps({k: v for k, v in decision.items() if not k.startswith('_')},
                     indent=2, ensure_ascii=False))
    print()
    print(f"LLM latency: {decision.get('_latency_s')}s")
    print(f"Model: {decision.get('_model')}")

    # Log to journal
    journal.append_decision("llm", {
        "model": decision.get("_model"),
        "latency_s": decision.get("_latency_s"),
        "action": decision.get("action"),
        "confidence": decision.get("confidence"),
        "entry": decision.get("entry"),
        "stop_loss": decision.get("stop_loss"),
        "take_profit": decision.get("take_profit"),
        "position_size_pct": decision.get("position_size_pct"),
        "reasoning": decision.get("reasoning", "")[:300],
    })
    print()
    print("Decision logged to journal.")
except brain.BrainError as e:
    print(f"BrainError: {e}")
