import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from app import get_commodity_data, get_contract_info, SUPPORTED_COMMODITIES

print("=" * 60)
print("测试修复后的数据获取")
print("=" * 60)

for name, info in SUPPORTED_COMMODITIES.items():
    symbol = info['symbol']
    full_name = info['name']
    
    print(f"\n正在测试: {name} ({symbol})")
    try:
        # 测试获取历史数据
        print("  正在获取历史数据...")
        data = get_commodity_data(symbol, period='1mo')
        if data is not None and not data.empty:
            print(f"  ✓ 成功获取历史数据，共 {len(data)} 条记录")
            print(f"    日期范围: {data.index[0]} 至 {data.index[-1]}")
            print(f"    最新收盘价: {data['Close'][-1]:.2f}")
        else:
            print("  ✗ 历史数据获取失败")
        
        # 测试获取商品信息
        print("  正在获取商品信息...")
        info_data = get_contract_info(symbol)
        if info_data:
            print(f"  ✓ 成功获取商品信息")
            print(f"    名称: {info_data.get('name', 'N/A')}")
            print(f"    最新价: {info_data.get('currentPrice', 'N/A')}")
        else:
            print("  ✗ 商品信息获取失败")
            
    except Exception as e:
        print(f"  ✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
