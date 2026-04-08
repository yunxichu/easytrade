import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'backend')
from cross_section_api import get_all_prices, run_backtest, get_latest_portfolio

prices = get_all_prices(504)
result = run_backtest(prices)
m = result['metrics']
print("=== 回测指标 ===")
print("年化收益:", m['ann_return'], '%')
print("总收益:  ", m['total_return'], '%')
print("夏普比率:", m['sharpe'])
print("最大回撤:", m['max_drawdown'], '%')
print("年化波动:", m['ann_vol'], '%')
print("胜率:    ", m['win_rate'], '%')
print("Calmar:  ", m['calmar'])
print()

port = get_latest_portfolio(prices)
print("=== 最新持仓 ===")
for p in port:
    print(p['asset'], p['side'], 'score=', p['factor_score'])

print()
print("IC均值:", result['mean_ic'])
print("月度收益条数:", len(result['monthly_rets']))
