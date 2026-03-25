import akshare as ak
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False


class CommodityAnalyzer:
    def __init__(self):
        self.supported_commodities = {
            '黄金': {'symbol': 'GC=F', 'name': 'COMEX黄金'},
            '原油': {'symbol': 'CL=F', 'name': 'WTI原油'},
            '白银': {'symbol': 'SI=F', 'name': 'COMEX白银'},
            '铜': {'symbol': 'HG=F', 'name': 'COMEX铜'},
            '天然气': {'symbol': 'NG=F', 'name': 'NYMEX天然气'}
        }

    def get_commodity_data(self, symbol, period='1y'):
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period=period)
            if data.empty:
                raise ValueError("未获取到数据")
            return data
        except Exception as e:
            print(f"获取数据失败: {e}")
            return None

    def get_akshare_commodity_data(self, commodity='原油'):
        try:
            if commodity == '原油':
                data = ak.futures_foreign_hist(symbol="WTI原油")
            elif commodity == '黄金':
                data = ak.futures_foreign_hist(symbol="COMEX黄金")
            elif commodity == '白银':
                data = ak.futures_foreign_hist(symbol="COMEX白银")
            else:
                return None
            
            data['日期'] = pd.to_datetime(data['日期'])
            data.set_index('日期', inplace=True)
            return data
        except Exception as e:
            print(f"akshare获取数据失败: {e}")
            return None

    def plot_price_trend(self, data, commodity_name):
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            vertical_spacing=0.1,
                            row_heights=[0.7, 0.3])

        fig.add_trace(
            go.Candlestick(x=data.index,
                          open=data['Open'],
                          high=data['High'],
                          low=data['Low'],
                          close=data['Close'],
                          name='K线'),
            row=1, col=1
        )

        if 'Volume' in data.columns:
            fig.add_trace(
                go.Bar(x=data.index, y=data['Volume'], name='成交量',
                      marker_color='rgba(0, 100, 255, 0.5)'),
                row=2, col=1
            )

        fig.update_layout(
            title=f'{commodity_name} - 价格走势',
            xaxis_title='日期',
            yaxis_title='价格',
            hovermode='x unified',
            height=800
        )

        fig.update_xaxes(rangeslider_visible=False)
        return fig

    def plot_line_chart(self, data, commodity_name):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})

        ax1.plot(data.index, data['Close'], label='收盘价', linewidth=2, color='#2E86AB')
        ax1.plot(data.index, data['Close'].rolling(window=20).mean(), 
                label='20日均线', linewidth=1.5, color='#A23B72', linestyle='--')
        ax1.plot(data.index, data['Close'].rolling(window=60).mean(), 
                label='60日均线', linewidth=1.5, color='#F18F01', linestyle='--')
        
        ax1.set_title(f'{commodity_name} - 价格走势与均线', fontsize=16, fontweight='bold')
        ax1.set_ylabel('价格', fontsize=12)
        ax1.legend(loc='best', fontsize=10)
        ax1.grid(True, alpha=0.3)

        if 'Volume' in data.columns:
            ax2.bar(data.index, data['Volume'], color='#2E86AB', alpha=0.6, label='成交量')
            ax2.set_xlabel('日期', fontsize=12)
            ax2.set_ylabel('成交量', fontsize=12)
            ax2.legend(loc='best')
            ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        return fig

    def predict_price(self, data, days_ahead=30):
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

    def plot_prediction(self, data, future_dates, future_prices, commodity_name):
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=data.index, y=data['Close'],
            name='历史价格',
            line=dict(color='#2E86AB', width=2)
        ))

        fig.add_trace(go.Scatter(
            x=future_dates, y=future_prices,
            name='预测价格',
            line=dict(color='#F18F01', width=2, dash='dash')
        ))

        fig.update_layout(
            title=f'{commodity_name} - 价格预测（未来{len(future_dates)}天）',
            xaxis_title='日期',
            yaxis_title='价格',
            hovermode='x unified',
            height=600,
            showlegend=True
        )

        return fig

    def get_contract_info(self, symbol):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            contract_info = {
                '名称': info.get('shortName', 'N/A'),
                '最新价': info.get('regularMarketPrice', 'N/A'),
                '涨跌额': info.get('regularMarketChange', 'N/A'),
                '涨跌幅': info.get('regularMarketChangePercent', 'N/A'),
                '开盘价': info.get('regularMarketOpen', 'N/A'),
                '最高价': info.get('regularMarketDayHigh', 'N/A'),
                '最低价': info.get('regularMarketDayLow', 'N/A'),
                '前收盘价': info.get('regularMarketPreviousClose', 'N/A'),
                '成交量': info.get('regularMarketVolume', 'N/A'),
                '持仓量': info.get('openInterest', 'N/A')
            }
            
            return contract_info
        except Exception as e:
            print(f"获取合约信息失败: {e}")
            return None

    def display_contract_info(self, contract_info):
        if not contract_info:
            print("无法获取合约信息")
            return

        print("\n" + "="*60)
        print(f"{'合约信息':^60}")
        print("="*60)
        
        for key, value in contract_info.items():
            if key == '涨跌幅' and isinstance(value, (int, float)):
                print(f"{key:<15}: {value:+.2%}")
            elif isinstance(value, float):
                print(f"{key:<15}: {value:.2f}")
            else:
                print(f"{key:<15}: {value}")
        
        print("="*60 + "\n")

    def analyze_commodity(self, commodity_name, period='1y'):
        if commodity_name not in self.supported_commodities:
            print(f"不支持的品种: {commodity_name}")
            print(f"支持的品种: {list(self.supported_commodities.keys())}")
            return

        symbol = self.supported_commodities[commodity_name]['symbol']
        full_name = self.supported_commodities[commodity_name]['name']

        print(f"\n正在分析: {full_name}")
        print("="*60)

        data = self.get_commodity_data(symbol, period)
        if data is None or data.empty:
            print("无法获取数据，尝试使用akshare...")
            data = self.get_akshare_commodity_data(commodity_name)
            if data is None or data.empty:
                print("数据获取失败")
                return

        contract_info = self.get_contract_info(symbol)
        self.display_contract_info(contract_info)

        print("生成价格走势图...")
        fig_line = self.plot_line_chart(data, full_name)
        fig_line.savefig(f'{commodity_name}_走势.png', dpi=300, bbox_inches='tight')
        print(f"走势图已保存: {commodity_name}_走势.png")

        fig_candle = self.plot_price_trend(data, full_name)
        fig_candle.write_html(f'{commodity_name}_K线.html')
        print(f"K线图已保存: {commodity_name}_K线.html")

        print("\n进行价格预测...")
        future_dates, future_prices = self.predict_price(data, days_ahead=30)
        if future_dates is not None:
            fig_pred = self.plot_prediction(data, future_dates, future_prices, full_name)
            fig_pred.write_html(f'{commodity_name}_预测.html')
            print(f"预测图已保存: {commodity_name}_预测.html")

            print(f"\n预测结果（未来30天）:")
            print(f"起始日期: {future_dates[0].strftime('%Y-%m-%d')}, 预测价格: {future_prices[0]:.2f}")
            print(f"结束日期: {future_dates[-1].strftime('%Y-%m-%d')}, 预测价格: {future_prices[-1]:.2f}")
            
            change = future_prices[-1] - future_prices[0]
            change_pct = change / future_prices[0] * 100
            print(f"预测变化: {change:+.2f} ({change_pct:+.2f}%)")

        print("\n分析完成!")
        plt.close('all')


def main():
    print("="*60)
    print(f"{'外盘商品走势分析与预测系统':^60}")
    print("="*60)

    analyzer = CommodityAnalyzer()

    print("\n支持的商品品种:")
    for i, (name, info) in enumerate(analyzer.supported_commodities.items(), 1):
        print(f"  {i}. {name} ({info['name']})")

    print("\n请选择要分析的品种（输入品种名称或序号）:")
    choice = input("> ").strip()

    commodity_name = None
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(analyzer.supported_commodities):
            commodity_name = list(analyzer.supported_commodities.keys())[idx]
    elif choice in analyzer.supported_commodities:
        commodity_name = choice

    if not commodity_name:
        print("无效的选择，默认分析黄金...")
        commodity_name = '黄金'

    print("\n请选择时间周期（1mo, 3mo, 6mo, 1y, 2y, 5y, max）:")
    print("默认: 1y")
    period = input("> ").strip() or '1y'

    analyzer.analyze_commodity(commodity_name, period)


if __name__ == "__main__":
    main()
