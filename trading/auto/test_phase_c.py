"""Test that prompts include technical indicators section."""
import sys
sys.path.insert(0, '/app/auto')
import prompts
sp = prompts.build_system_prompt()
up = prompts.build_user_prompt(
    symbol='BTC-USDT', current_price=64000,
    regime={'regime': 'TRENDING_UP', 'regime_description': 'test',
            'indicators': {'atr_ratio': 0.9, 'range_to_net_ratio': 3.0, 'direction_changes_10d': 2},
            'trend': 'uptrend', 'regime_strategy_hints': {},
            'technical_indicators': {
                'support_resistance': {'support': [{'price': 62000}], 'resistance': [{'price': 65000}]},
                'fibonacci_retracement': {'0.5': 63500},
                'vsa': {'vsa': 'normal', 'volume': 'normal', 'spread': 'normal'},
                'candlestick': {'pattern': 'none', 'direction': 'neutral', 'reliability': 'low'}}},
    confluence={'total_score': 3, 'weighted_score': 3.6, 'bullish_tfs': 3, 'bearish_tfs': 0,
               'direction_bias': 'long',
               'timeframes': {'15m': {'trend': 'UP', 'momentum': 'UP', 'rsi': 60},
                              '1d': {'rsi': 55}}},
    open_positions=[], recent_trades=[], capital=10000, daily_pnl=0
)
print('Has Technical indicators section:', 'Technical indicators' in up)
print('Has Support levels:', 'Support levels' in up)
print('Has Resistance levels:', 'Resistance levels' in up)
print('Has VSA signal:', 'VSA signal' in up)
print('Has Candlestick:', 'Candlestick:' in up)
print('Has Fibonacci:', 'Fibonacci' in up)
print('User prompt size:', len(up), 'chars')
