from flask import Flask, jsonify, render_template
from flask_cors import CORS
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
import akshare as ak
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__, 
            template_folder='../frontend/templates',
            static_folder='../frontend/static')
CORS(app)

SUPPORTED_COMMODITIES = {
    '黄金': {'symbol': 'COMEX黄金', 'name': 'COMEX黄金'},
    '原油': {'symbol': 'WTI原油', 'name': 'WTI原油'},
    '白银': {'symbol': 'COMEX白银', 'name': 'COMEX白银'},
    '铜': {'symbol': 'COMEX铜', 'name': 'COMEX铜'},
    '天然气': {'symbol': 'NYMEX天然气', 'name': 'NYMEX天然气'}
}


def get_commodity_data(commodity_name, period='1y'):
    try:
        print(f"正在从AKShare获取数据: {commodity_name}")
        
        try:
            data = ak.futures_foreign_hist(symbol=commodity_name)
        except Exception as e:
            print(f"AKShare获取失败: {e}")
            return generate_sample_data(commodity_name, period)
        
        if data is None or data.empty:
            print("数据为空，使用模拟数据")
            return generate_sample_data(commodity_name, period)
        
        data['日期'] = pd.to_datetime(data['日期'])
        data.set_index('日期', inplace=True)
        
        data = data.rename(columns={
            '开盘': 'Open',
            '最高': 'High',
            '最低': 'Low',
            '收盘': 'Close',
            '成交量': 'Volume'
        })
        
        end_date = datetime.now()
        if period == '1mo':
            start_date = end_date - timedelta(days=30)
        elif period == '3mo':
            start_date = end_date - timedelta(days=90)
        elif period == '6mo':
            start_date = end_date - timedelta(days=180)
        elif period == '2y':
            start_date = end_date - timedelta(days=730)
        elif period == '5y':
            start_date = end_date - timedelta(days=1825)
        else:
            start_date = end_date - timedelta(days=365)
        
        data = data[data.index >= start_date]
        
        print(f"成功获取 {len(data)} 条记录")
        return data
    except Exception as e:
        print(f"获取数据失败: {e}")
        import traceback
        traceback.print_exc()
        return generate_sample_data(commodity_name, period)


def generate_sample_data(commodity_name, period='1y'):
    print(f"生成模拟数据: {commodity_name}")
    
    end_date = datetime.now()
    if period == '1mo':
        days = 30
    elif period == '3mo':
        days = 90
    elif period == '6mo':
        days = 180
    elif period == '2y':
        days = 730
    elif period == '5y':
        days = 1825
    else:
        days = 365
    
    base_prices = {
        'COMEX黄金': 2000,
        'WTI原油': 80,
        'COMEX白银': 25,
        'COMEX铜': 4,
        'NYMEX天然气': 3
    }
    
    base_price = base_prices.get(commodity_name, 100)
    
    dates = [end_date - timedelta(days=i) for i in range(days, 0, -1)]
    
    np.random.seed(42)
    prices = []
    current_price = base_price
    for _ in range(days):
        change = np.random.normal(0, base_price * 0.01)
        current_price += change
        current_price = max(current_price, base_price * 0.7)
        prices.append(current_price)
    
    data = pd.DataFrame({
        'Open': prices,
        'High': [p * (1 + np.random.uniform(0, 0.02)) for p in prices],
        'Low': [p * (1 - np.random.uniform(0, 0.02)) for p in prices],
        'Close': prices,
        'Volume': np.random.randint(100000, 1000000, days)
    }, index=dates)
    
    print(f"生成了 {len(data)} 条模拟数据")
    return data


def get_contract_info(commodity_name):
    try:
        data = get_commodity_data(commodity_name, period='5d')
        
        base_prices = {
            'COMEX黄金': 2000,
            'WTI原油': 80,
            'COMEX白银': 25,
            'COMEX铜': 4,
            'NYMEX天然气': 3
        }
        
        base_price = base_prices.get(commodity_name, 100)
        
        contract_info = {
            'name': commodity_name,
            'currentPrice': base_price,
            'change': base_price * 0.01,
            'changePercent': 0.01,
            'open': base_price * 0.995,
            'high': base_price * 1.01,
            'low': base_price * 0.99,
            'previousClose': base_price * 0.99,
            'volume': 500000,
            'openInterest': 100000
        }
        
        if data is not None and not data.empty and len(data) >= 2:
            last_row = data.iloc[-1]
            prev_row = data.iloc[-2]
            
            contract_info['currentPrice'] = float(last_row['Close'])
            contract_info['open'] = float(last_row['Open'])
            contract_info['high'] = float(last_row['High'])
            contract_info['low'] = float(last_row['Low'])
            contract_info['previousClose'] = float(prev_row['Close'])
            contract_info['volume'] = int(last_row['Volume']) if pd.notna(last_row['Volume']) else 500000
            
            change = last_row['Close'] - prev_row['Close']
            change_percent = change / prev_row['Close'] if prev_row['Close'] != 0 else 0
            
            contract_info['change'] = float(change)
            contract_info['changePercent'] = float(change_percent)
        
        return contract_info
    except Exception as e:
        print(f"获取合约信息失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def predict_price(data, days_ahead=30):
    if len(data) < 60:
        return None, None

    df = data.copy()
    df['Days'] = np.arange(len(df))

    X = df['Days'].values.reshape(-1, 1)
    y = df['Close'].values

    model = LinearRegression()
    model.fit(X, y)

    future_days = np.arange(len(df), len(df) + days_ahead).reshape(-1, 1)
    future_prices = model.predict(future_days)

    last_date = df.index[-1]
    future_dates = [last_date + timedelta(days=i+1) for i in range(days_ahead)]

    return future_dates, future_prices


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analysis')
def analysis():
    return render_template('analysis.html')


@app.route('/api/commodities', methods=['GET'])
def get_commodities():
    commodities_list = []
    for key, value in SUPPORTED_COMMODITIES.items():
        commodities_list.append({
            'key': key,
            'symbol': value['symbol'],
            'name': value['name']
        })
    return jsonify(commodities_list)


@app.route('/api/commodity/<commodity_key>/info', methods=['GET'])
def get_commodity_info_endpoint(commodity_key):
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400
    
    symbol = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    info = get_contract_info(symbol)
    
    if info:
        return jsonify(info)
    else:
        return jsonify({'error': '获取信息失败'}), 500


@app.route('/api/commodity/<commodity_key>/data', methods=['GET'])
@app.route('/api/commodity/<commodity_key>/data/<period>', methods=['GET'])
def get_commodity_historical_data(commodity_key, period='1y'):
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400
    
    symbol = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    data = get_commodity_data(symbol, period)
    
    if data is None or data.empty:
        return jsonify({'error': '获取数据失败'}), 500
    
    data_reset = data.reset_index()
    data_reset = data_reset.rename(columns={'index': 'Date'})
    data_reset['Date'] = data_reset['Date'].dt.strftime('%Y-%m-%d')
    
    historical_data = []
    for _, row in data_reset.iterrows():
        historical_data.append({
            'date': row['Date'],
            'open': float(row['Open']) if pd.notna(row['Open']) else None,
            'high': float(row['High']) if pd.notna(row['High']) else None,
            'low': float(row['Low']) if pd.notna(row['Low']) else None,
            'close': float(row['Close']) if pd.notna(row['Close']) else None,
            'volume': int(row['Volume']) if pd.notna(row['Volume']) else None
        })
    
    return jsonify(historical_data)


@app.route('/api/commodity/<commodity_key>/predict', methods=['GET'])
@app.route('/api/commodity/<commodity_key>/predict/<period>', methods=['GET'])
def get_prediction(commodity_key, period='1y'):
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400
    
    symbol = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    data = get_commodity_data(symbol, period)
    
    if data is None or data.empty:
        return jsonify({'error': '获取数据失败'}), 500
    
    future_dates, future_prices = predict_price(data, days_ahead=30)
    
    if future_dates is None:
        return jsonify({'error': '数据不足，无法预测'}), 400
    
    predictions = []
    for date, price in zip(future_dates, future_prices):
        predictions.append({
            'date': date.strftime('%Y-%m-%d'),
            'price': float(price)
        })
    
    return jsonify(predictions)


@app.route('/api/commodity/<commodity_key>/analyze', methods=['GET'])
@app.route('/api/commodity/<commodity_key>/analyze/<period>', methods=['GET'])
def analyze_commodity(commodity_key, period='1y'):
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400
    
    symbol = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    commodity_name = SUPPORTED_COMMODITIES[commodity_key]['name']
    
    data = get_commodity_data(symbol, period)
    if data is None or data.empty:
        return jsonify({'error': '获取数据失败'}), 500
    
    info = get_contract_info(symbol)
    
    data_reset = data.reset_index()
    data_reset = data_reset.rename(columns={'index': 'Date'})
    data_reset['Date'] = data_reset['Date'].dt.strftime('%Y-%m-%d')
    
    historical_data = []
    for _, row in data_reset.iterrows():
        historical_data.append({
            'date': row['Date'],
            'open': float(row['Open']) if pd.notna(row['Open']) else None,
            'high': float(row['High']) if pd.notna(row['High']) else None,
            'low': float(row['Low']) if pd.notna(row['Low']) else None,
            'close': float(row['Close']) if pd.notna(row['Close']) else None,
            'volume': int(row['Volume']) if pd.notna(row['Volume']) else None
        })
    
    future_dates, future_prices = predict_price(data, days_ahead=30)
    predictions = []
    if future_dates is not None:
        for date, price in zip(future_dates, future_prices):
            predictions.append({
                'date': date.strftime('%Y-%m-%d'),
                'price': float(price)
            })
    
    result = {
        'commodity': commodity_key,
        'name': commodity_name,
        'info': info,
        'historicalData': historical_data,
        'predictions': predictions
    }
    
    return jsonify(result)


@app.route('/api/term-structure/<commodity_key>', methods=['GET'])
def get_term_structure(commodity_key):
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400
    
    commodity_name = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    
    base_price = {
        'COMEX黄金': 2000,
        'WTI原油': 80,
        'COMEX白银': 25,
        'COMEX铜': 4,
        'NYMEX天然气': 3
    }.get(commodity_name, 100)
    
    months = ['近月', '次近月', '第3月', '第4月', '第5月', '第6月']
    
    np.random.seed(int(datetime.now().timestamp()) % 1000)
    prices = []
    current_price = base_price
    
    for i, month in enumerate(months):
        if i == 0:
            price = current_price
        else:
            contango = np.random.uniform(-0.02, 0.03)
            price = prices[-1]['price'] * (1 + contango)
        prices.append({
            'month': month,
            'price': round(price, 2),
            'contract': f"{commodity_key}{(i+1):02d}"
        })
    
    structure = 'contango' if prices[-1]['price'] > prices[0]['price'] else 'backwardation'
    structure_cn = '升水' if structure == 'contango' else '贴水'
    
    spread = prices[-1]['price'] - prices[0]['price']
    spread_pct = (spread / prices[0]['price']) * 100
    
    strategies = []
    if structure == 'backwardation':
        strategies.append({
            'name': '多头展期策略',
            'description': '在贴水结构下，持有多头头寸并展期可获得展期收益',
            'risk': '中等',
            'expectedReturn': '正展期收益'
        })
        strategies.append({
            'name': '跨期套利',
            'description': '买入近月合约，卖出远月合约，等待价差收敛',
            'risk': '较低',
            'expectedReturn': '价差收敛收益'
        })
    else:
        strategies.append({
            'name': '空头展期策略',
            'description': '在升水结构下，持有空头头寸并展期可获得展期收益',
            'risk': '中等',
            'expectedReturn': '正展期收益'
        })
        strategies.append({
            'name': '跨期套利',
            'description': '卖出近月合约，买入远月合约，等待价差收敛',
            'risk': '较低',
            'expectedReturn': '价差收敛收益'
        })
    
    result = {
        'commodity': commodity_key,
        'name': commodity_name,
        'termStructure': prices,
        'structure': structure_cn,
        'structureType': structure,
        'spread': round(spread, 2),
        'spreadPercent': round(spread_pct, 2),
        'strategies': strategies
    }
    
    return jsonify(result)


@app.route('/api/strategy/backtest/<commodity_key>', methods=['GET'])
@app.route('/api/strategy/backtest/<commodity_key>/<period>', methods=['GET'])
def backtest_strategy(commodity_key, period='1y'):
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400
    
    symbol = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    data = get_commodity_data(symbol, period)
    
    if data is None or data.empty:
        return jsonify({'error': '获取数据失败'}), 500
    
    df = data.copy()
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    
    initial_capital = 100000
    position_size = 0.1
    stop_loss_pct = 0.05
    take_profit_pct = 0.10
    
    trades = []
    position = 0
    entry_price = 0
    capital = initial_capital
    peak_capital = initial_capital
    max_drawdown = 0
    
    for i in range(20, len(df)):
        current_price = df['Close'].iloc[i]
        ma5 = df['MA5'].iloc[i]
        ma20 = df['MA20'].iloc[i]
        
        if position == 0:
            if ma5 > ma20 and df['MA5'].iloc[i-1] <= df['MA20'].iloc[i-1]:
                position = 1
                entry_price = current_price
                shares = int((capital * position_size) / current_price)
                trades.append({
                    'date': df.index[i].strftime('%Y-%m-%d'),
                    'type': 'buy',
                    'price': round(current_price, 2),
                    'shares': shares,
                    'reason': 'MA5上穿MA20，金叉买入信号'
                })
        else:
            pnl_pct = (current_price - entry_price) / entry_price
            
            if pnl_pct <= -stop_loss_pct:
                position = 0
                pnl = (current_price - entry_price) * shares
                capital += pnl
                trades.append({
                    'date': df.index[i].strftime('%Y-%m-%d'),
                    'type': 'sell',
                    'price': round(current_price, 2),
                    'shares': shares,
                    'pnl': round(pnl, 2),
                    'reason': f'触发止损（亏损{abs(pnl_pct)*100:.2f}%）'
                })
            elif pnl_pct >= take_profit_pct:
                position = 0
                pnl = (current_price - entry_price) * shares
                capital += pnl
                trades.append({
                    'date': df.index[i].strftime('%Y-%m-%d'),
                    'type': 'sell',
                    'price': round(current_price, 2),
                    'shares': shares,
                    'pnl': round(pnl, 2),
                    'reason': f'触发止盈（盈利{pnl_pct*100:.2f}%）'
                })
            elif ma5 < ma20 and df['MA5'].iloc[i-1] >= df['MA20'].iloc[i-1]:
                position = 0
                pnl = (current_price - entry_price) * shares
                capital += pnl
                trades.append({
                    'date': df.index[i].strftime('%Y-%m-%d'),
                    'type': 'sell',
                    'price': round(current_price, 2),
                    'shares': shares,
                    'pnl': round(pnl, 2),
                    'reason': 'MA5下穿MA20，死叉卖出信号'
                })
        
        if capital > peak_capital:
            peak_capital = capital
        drawdown = (peak_capital - capital) / peak_capital
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    winning_trades = [t for t in trades if t['type'] == 'sell' and t.get('pnl', 0) > 0]
    losing_trades = [t for t in trades if t['type'] == 'sell' and t.get('pnl', 0) < 0]
    total_trades = len([t for t in trades if t['type'] == 'sell'])
    
    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
    
    avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
    avg_loss = np.mean([abs(t['pnl']) for t in losing_trades]) if losing_trades else 0
    odds_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    
    total_return = (capital - initial_capital) / initial_capital
    
    returns = []
    for i in range(1, len(df)):
        daily_return = (df['Close'].iloc[i] - df['Close'].iloc[i-1]) / df['Close'].iloc[i-1]
        returns.append(daily_return)
    
    avg_return = np.mean(returns)
    std_return = np.std(returns)
    risk_free_rate = 0.03 / 252
    sharpe_ratio = (avg_return - risk_free_rate) / std_return * np.sqrt(252) if std_return > 0 else 0
    
    result = {
        'commodity': commodity_key,
        'name': SUPPORTED_COMMODITIES[commodity_key]['name'],
        'initialCapital': initial_capital,
        'finalCapital': round(capital, 2),
        'trades': trades,
        'metrics': {
            'totalTrades': total_trades,
            'winningTrades': len(winning_trades),
            'losingTrades': len(losing_trades),
            'winRate': round(win_rate * 100, 2),
            'oddsRatio': round(odds_ratio, 2),
            'avgWin': round(avg_win, 2),
            'avgLoss': round(avg_loss, 2),
            'totalReturn': round(total_return * 100, 2),
            'maxDrawdown': round(max_drawdown * 100, 2),
            'sharpeRatio': round(sharpe_ratio, 2)
        },
        'strategy': {
            'name': '双均线策略',
            'description': 'MA5上穿MA20买入，MA5下穿MA20卖出',
            'positionSize': f'{position_size*100}%',
            'stopLoss': f'{stop_loss_pct*100}%',
            'takeProfit': f'{take_profit_pct*100}%'
        }
    }
    
    return jsonify(result)


@app.route('/api/market/overview', methods=['GET'])
def market_overview():
    """一次性返回所有商品的最新行情摘要"""
    results = []
    for key, value in SUPPORTED_COMMODITIES.items():
        symbol = value['symbol']
        info = get_contract_info(symbol)
        if info:
            info['key'] = key
            results.append(info)
    return jsonify(results)


@app.route('/api/commodity/<commodity_key>/volatility', methods=['GET'])
@app.route('/api/commodity/<commodity_key>/volatility/<period>', methods=['GET'])
def get_volatility(commodity_key, period='1y'):
    """返回历史波动率序列"""
    if commodity_key not in SUPPORTED_COMMODITIES:
        return jsonify({'error': '不支持的商品'}), 400

    symbol = SUPPORTED_COMMODITIES[commodity_key]['symbol']
    data = get_commodity_data(symbol, period)

    if data is None or data.empty or len(data) < 21:
        return jsonify({'error': '数据不足'}), 400

    closes = data['Close'].dropna().values
    log_returns = np.log(closes[1:] / closes[:-1])

    hv_series = []
    dates = list(data.index.strftime('%Y-%m-%d'))

    for i in range(19, len(log_returns)):
        window = log_returns[i-19:i+1]
        mean = np.mean(window)
        std  = np.std(window, ddof=1)
        hv   = std * np.sqrt(252) * 100
        hv_series.append({
            'date': dates[i+1],
            'hv': round(float(hv), 4)
        })

    overall_hv20 = round(float(np.std(log_returns[-20:], ddof=1) * np.sqrt(252) * 100), 4)
    overall_hv60 = round(float(np.std(log_returns[-min(60,len(log_returns)):], ddof=1) * np.sqrt(252) * 100), 4)

    return jsonify({
        'commodity': commodity_key,
        'hv20': overall_hv20,
        'hv60': overall_hv60,
        'series': hv_series
    })


@app.route('/api/market/sentiment', methods=['GET'])
def market_sentiment():
    """返回简单的综合市场情绪指标"""
    sentiments = {}
    for key, value in SUPPORTED_COMMODITIES.items():
        symbol = value['symbol']
        data = get_commodity_data(symbol, '3mo')
        if data is None or data.empty or len(data) < 20:
            continue
        closes = data['Close'].dropna().values
        recent_change = (closes[-1] - closes[-20]) / closes[-20] * 100
        log_r = np.log(closes[1:] / closes[:-1])
        gains = log_r[log_r > 0]
        losses = -log_r[log_r < 0]
        rs = np.mean(gains[-14:]) / np.mean(losses[-14:]) if len(losses) > 0 else 100
        rsi = float(100 - 100 / (1 + rs))
        score = min(100, max(0, 50 + recent_change * 3 + (rsi - 50) * 0.5))
        sentiments[key] = {
            'score': round(score, 1),
            'rsi': round(rsi, 2),
            'change20d': round(float(recent_change), 2)
        }
    return jsonify(sentiments)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
