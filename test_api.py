import requests
import json

print("=" * 80)
print("外盘商品走势分析与预测系统 - 功能测试示例")
print("=" * 80)

print("\n【测试1：期限结构分析】")
print("-" * 80)
response = requests.get('http://localhost:5000/api/term-structure/黄金')
data = response.json()

print(f"商品：{data['name']}")
print(f"期限结构：{data['structure']}")
print(f"价差：{data['spread']}")
print(f"价差百分比：{data['spreadPercent']}%")
print("\n不同月份合约价格：")
for item in data['termStructure']:
    print(f"  {item['month']}: {item['price']}")

print("\n交易策略建议：")
for strategy in data['strategies']:
    print(f"  - {strategy['name']}: {strategy['description']}")

print("\n" + "=" * 80)
print("【测试2：交易策略回测】")
print("-" * 80)
response = requests.get('http://localhost:5000/api/strategy/backtest/原油/1y')
data = response.json()

print(f"商品：{data['name']}")
print(f"策略：{data['strategy']['name']}")
print(f"策略描述：{data['strategy']['description']}")
print(f"初始资金：${data['initialCapital']:,}")
print(f"最终资金：${data['finalCapital']:,}")

print("\n量化指标：")
metrics = data['metrics']
print(f"  总交易次数：{metrics['totalTrades']}")
print(f"  盈利次数：{metrics['winningTrades']}")
print(f"  亏损次数：{metrics['losingTrades']}")
print(f"  胜率：{metrics['winRate']}%")
print(f"  赔率：{metrics['oddsRatio']}")
print(f"  平均盈利：${metrics['avgWin']}")
print(f"  平均亏损：${metrics['avgLoss']}")
print(f"  总收益率：{metrics['totalReturn']}%")
print(f"  最大回撤：{metrics['maxDrawdown']}%")
print(f"  夏普比率：{metrics['sharpeRatio']}")

print("\n交易记录（前5条）：")
for i, trade in enumerate(data['trades'][:5]):
    print(f"  {i+1}. {trade['date']} - {trade['type']} - ${trade['price']} - {trade['reason']}")

print("\n" + "=" * 80)
print("测试完成！系统运行正常！")
print("=" * 80)
