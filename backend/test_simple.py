import sys
sys.path.insert(0, '.')
from app import get_commodity_data, get_contract_info, SUPPORTED_COMMODITIES

print('=' * 60)
print('测试修复后的数据获取')
print('=' * 60)

for name, info in SUPPORTED_COMMODITIES.items():
    symbol = info['symbol']
    print('\n正在测试: {} ({})'.format(name, symbol))
    try:
        print('  正在获取历史数据...')
        data = get_commodity_data(symbol, period='1mo')
        if data is not None and not data.empty:
            print('  ✓ 成功获取历史数据，共 {} 条记录'.format(len(data)))
            print('    最新收盘价: {:.2f}'.format(data['Close'][-1]))
        else:
            print('  ✗ 历史数据获取失败')
        
        print('  正在获取商品信息...')
        info_data = get_contract_info(symbol)
        if info_data:
            print('  ✓ 成功获取商品信息')
            print('    最新价: {}'.format(info_data.get('currentPrice', 'N/A')))
        else:
            print('  ✗ 商品信息获取失败')
    except Exception as e:
        print('  ✗ 发生错误: {}'.format(e))
        import traceback
        traceback.print_exc()

print('\n' + '=' * 60)
print('测试完成')
print('=' * 60)
