"""Quick integration test: LLM says hold when overbought+high vol."""
import sys
import json
sys.path.insert(0, "/app/auto")
import brain
import prompts
import validator

sp = prompts.build_system_prompt()
up = """## Market state
- Symbol: BTC-USDT
- Current price: $64050.00
- Regime: HIGH_VOLATILITY
- Confluence score: +3 (5 timeframes)
- 1d RSI: 78.0 (OVERBOUGHT)
- ATR ratio: 1.8 (elevated)

Timeframes: all 5 timeframes bullish
Open positions: 2 already
Daily P&L: +$0
Capital: $10000

Despite high confluence, RSI is overbought on 1d (78), ATR is elevated (1.8x),
and we already have 2 open positions. Should we open a third long position?
Apply avoid_overbought_long and high_vol_caution skills.
Provide your decision in JSON format."""

print("=== LLM Call (forced hold scenario) ===")
try:
    d = brain.call_brain(sp, up)
    print("Decision:")
    print(json.dumps({k: v for k, v in d.items() if not k.startswith("_")},
                     indent=2, ensure_ascii=False))
    print()
    if d.get("action") == "hold":
        print("=== LLM override HOLD ===")
        rq_ok, rq_msg = validator.check_reasoning_quality(d.get("reasoning", ""))
        print(f"Reasoning quality: ok={rq_ok} msg={rq_msg}")
        print("Rules would have said: LONG (confluence +3)")
        print("LLM overrode: HOLD (overbought + high vol + 2 positions)")
    else:
        action = d.get("action", "?")
        print(f"=== LLM said {action.upper()} ===")
except brain.BrainError as e:
    print(f"BrainError: {e}")
