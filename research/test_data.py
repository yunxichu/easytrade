"""快速测试数据获取 - 输出重定向到文件"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import get_data, YAHOO_TICKERS

results = []
for t in ['GC=F', 'SI=F', 'CL=F', 'HG=F', 'GLD', 'SLV']:
    df, src = get_data(t, '1y')
    if df is not None:
        r = f'{t} ({YAHOO_TICKERS[t]}): {len(df)} rows, source={src}, latest={df["Close"].iloc[-1]:.3f}'
    else:
        r = f'{t}: FAILED'
    results.append(r)
    print(r)

out = os.path.join(os.path.dirname(__file__), 'outputs', 'data_test_result.txt')
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, 'w') as f:
    f.write('\n'.join(results))
print(f'Saved to {out}')
