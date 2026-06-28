"""Quick test for Phase B - 3-tier MTF + regime trend."""
import json, subprocess
r = subprocess.run(['python', '/app/confluence/confluence.py', '--symbol', 'BTC-USDT', '--json'], capture_output=True, text=True)
d = json.loads(r.stdout)
print('=== Phase B6+B7: 3-tier MTF with weights ===')
print(f'Flat score:    {d["total_score"]:+d}/5')
print(f'Weighted score: {d["weighted_score"]:+.2f}/6.2')
print(f'Direction bias: {d["direction_bias"]} ({d["bullish_tfs"]}L / {d["bearish_tfs"]}S)')
print()
print('Tiers:')
for tf_label in ['15m', '1h', '4h', '1d', '1w']:
    tf = d['timeframes'].get(tf_label, {})
    print(f'  {tf_label}: tier={tf.get("tier")} weight={tf.get("weight")} score={tf["score"]:+d}')

r2 = subprocess.run(['python', '/app/regime/regime.py', '--symbol', 'BTC-USDT', '--json'], capture_output=True, text=True)
d2 = json.loads(r2.stdout)
print()
print('=== Phase B8: Regime trend ===')
print(f'Regime: {d2["regime"]}')
print(f'Trend (S0): {d2.get("trend")}')
print(f'ATR_14: {d2["indicators"].get("atr_14")}')
