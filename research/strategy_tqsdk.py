"""
strategy_tqsdk.py
=================
天勤量化（TqSdk）策略测试模块。

由于 TqSdk 需要账户授权和实时连接，本模块实现：
  1. 完全兼容天勤 API 风格的离线回测框架（不依赖 tqsdk 账户）
  2. 两个典型策略：
     - 双均线策略（MA5/MA20 金叉/死叉）
     - MACD 策略（信号线穿越）
  3. 输出：交易记录、资金曲线、回测指标

天勤 TqSdk 说明（如需接入真实行情）：
  pip install tqsdk
  需要在 https://www.shinnytech.com/ 注册账户
  代码示例见文件末尾注释
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import get_data, YAHOO_TICKERS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────
#  指标计算
# ─────────────────────────────────────────────

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    # 均线
    d['MA5']  = d['Close'].rolling(5).mean()
    d['MA10'] = d['Close'].rolling(10).mean()
    d['MA20'] = d['Close'].rolling(20).mean()
    d['MA60'] = d['Close'].rolling(60).mean()
    # MACD
    ema12 = d['Close'].ewm(span=12, adjust=False).mean()
    ema26 = d['Close'].ewm(span=26, adjust=False).mean()
    d['MACD_DIF'] = ema12 - ema26
    d['MACD_DEA'] = d['MACD_DIF'].ewm(span=9, adjust=False).mean()
    d['MACD_BAR'] = 2 * (d['MACD_DIF'] - d['MACD_DEA'])
    # RSI
    delta = d['Close'].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    d['RSI'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # 布林带
    d['BB_MID']   = d['Close'].rolling(20).mean()
    d['BB_STD']   = d['Close'].rolling(20).std(ddof=1)
    d['BB_UPPER'] = d['BB_MID'] + 2 * d['BB_STD']
    d['BB_LOWER'] = d['BB_MID'] - 2 * d['BB_STD']
    # ATR
    hl   = d['High'] - d['Low']
    hc   = (d['High'] - d['Close'].shift()).abs()
    lc   = (d['Low']  - d['Close'].shift()).abs()
    d['ATR'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    return d


# ─────────────────────────────────────────────
#  策略一：双均线（MA5/MA20，仿天勤风格）
# ─────────────────────────────────────────────

def backtest_ma_cross(df: pd.DataFrame, fast: int = 5, slow: int = 20,
                      init_capital: float = 100_000,
                      commission_rate: float = 0.0003,
                      slippage: float = 0.0001) -> dict:
    """
    双均线回测（模拟天勤 MA Cross 策略）
    commission_rate: 单边手续费率
    slippage: 单边滑点率
    """
    d = df.copy()
    d['MA_fast'] = d['Close'].rolling(fast).mean()
    d['MA_slow'] = d['Close'].rolling(slow).mean()
    d = d.dropna(subset=['MA_fast', 'MA_slow'])

    # 信号生成
    d['Signal'] = 0
    d.loc[(d['MA_fast'] > d['MA_slow']) & (d['MA_fast'].shift() <= d['MA_slow'].shift()), 'Signal'] = 1   # 金叉买入
    d.loc[(d['MA_fast'] < d['MA_slow']) & (d['MA_fast'].shift() >= d['MA_slow'].shift()), 'Signal'] = -1  # 死叉卖出

    # 回测撮合
    capital   = init_capital
    position  = 0   # 持有数量
    entry_px  = 0.0
    trades    = []
    equity    = []

    for idx, row in d.iterrows():
        px = float(row['Close'])

        if row['Signal'] == 1 and position == 0:
            # 买入：使用 30% 仓位
            invest   = capital * 0.30
            fee      = invest * commission_rate
            slip_cost = invest * slippage
            shares   = int(invest / px)
            if shares > 0:
                cost     = shares * px * (1 + commission_rate + slippage)
                if cost <= capital:
                    capital  -= cost
                    position  = shares
                    entry_px  = px
                    trades.append({'date': str(idx)[:10], 'action': 'BUY',
                                   'price': round(px, 4), 'shares': shares,
                                   'commission': round(shares * px * commission_rate, 4),
                                   'capital_after': round(capital, 2)})

        elif row['Signal'] == -1 and position > 0:
            # 卖出
            proceeds = position * px * (1 - commission_rate - slippage)
            fee      = position * px * commission_rate
            pnl      = proceeds - position * entry_px
            capital += proceeds
            trades.append({'date': str(idx)[:10], 'action': 'SELL',
                           'price': round(px, 4), 'shares': position,
                           'commission': round(position * px * commission_rate, 4),
                           'pnl': round(pnl, 2),
                           'pnl_pct': round(pnl / (position * entry_px) * 100, 2),
                           'capital_after': round(capital, 2)})
            position = 0

        equity.append({'date': str(idx)[:10],
                       'equity': round(capital + position * px, 2)})

    # 平仓最后持仓
    if position > 0:
        px = float(d['Close'].iloc[-1])
        proceeds = position * px * (1 - commission_rate - slippage)
        pnl      = proceeds - position * entry_px
        capital += proceeds
        trades.append({'date': str(d.index[-1])[:10], 'action': 'SELL(close)',
                       'price': round(px, 4), 'shares': position,
                       'commission': round(position * px * commission_rate, 4),
                       'pnl': round(pnl, 2),
                       'pnl_pct': round(pnl / (position * entry_px) * 100, 2),
                       'capital_after': round(capital, 2)})
        position = 0

    # ── 绩效指标 ──
    eq_series = pd.Series([e['equity'] for e in equity],
                          index=pd.to_datetime([e['date'] for e in equity]))
    total_return  = (capital - init_capital) / init_capital * 100
    daily_ret     = eq_series.pct_change().dropna()
    annual_ret    = daily_ret.mean() * 252 * 100
    annual_vol    = daily_ret.std() * np.sqrt(252) * 100
    sharpe        = (daily_ret.mean() - 0.03/252) / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    rolling_max   = eq_series.cummax()
    drawdown      = (eq_series - rolling_max) / rolling_max * 100
    max_dd        = drawdown.min()

    sell_trades   = [t for t in trades if 'pnl' in t]
    win_trades    = [t for t in sell_trades if t['pnl'] > 0]
    total_commission = sum(t['commission'] for t in trades)
    total_pnl        = sum(t.get('pnl', 0) for t in sell_trades)

    metrics = {
        'strategy':        f'双均线 MA{fast}/MA{slow}',
        'init_capital':    init_capital,
        'final_capital':   round(capital, 2),
        'total_return_pct': round(total_return, 2),
        'annual_return_pct': round(annual_ret, 2),
        'annual_vol_pct':   round(annual_vol, 2),
        'sharpe_ratio':     round(float(sharpe), 3),
        'max_drawdown_pct': round(float(max_dd), 2),
        'total_trades':     len(sell_trades),
        'win_trades':       len(win_trades),
        'loss_trades':      len(sell_trades) - len(win_trades),
        'win_rate_pct':     round(len(win_trades) / len(sell_trades) * 100, 1) if sell_trades else 0,
        'total_commission': round(total_commission, 2),
        'total_pnl':        round(total_pnl, 2),
        'commission_ratio': round(total_commission / max(abs(total_pnl), 1) * 100, 2),
        'avg_pnl_per_trade': round(total_pnl / len(sell_trades), 2) if sell_trades else 0,
    }

    return {'metrics': metrics, 'trades': trades, 'equity': equity, 'df': d}


# ─────────────────────────────────────────────
#  策略二：MACD 策略
# ─────────────────────────────────────────────

def backtest_macd(df: pd.DataFrame,
                  init_capital: float = 100_000,
                  commission_rate: float = 0.0003,
                  slippage: float = 0.0001) -> dict:
    """MACD DIF 上穿 DEA 买入，下穿卖出"""
    d = calc_indicators(df)
    d = d.dropna(subset=['MACD_DIF', 'MACD_DEA'])

    d['Signal'] = 0
    d.loc[(d['MACD_DIF'] > d['MACD_DEA']) & (d['MACD_DIF'].shift() <= d['MACD_DEA'].shift()), 'Signal'] = 1
    d.loc[(d['MACD_DIF'] < d['MACD_DEA']) & (d['MACD_DIF'].shift() >= d['MACD_DEA'].shift()), 'Signal'] = -1

    capital  = init_capital
    position = 0
    entry_px = 0.0
    trades   = []
    equity   = []

    for idx, row in d.iterrows():
        px = float(row['Close'])

        if row['Signal'] == 1 and position == 0:
            invest = capital * 0.30
            shares = int(invest / px)
            if shares > 0:
                cost    = shares * px * (1 + commission_rate + slippage)
                if cost <= capital:
                    capital -= cost
                    position = shares
                    entry_px = px
                    trades.append({'date': str(idx)[:10], 'action': 'BUY',
                                   'price': round(px, 4), 'shares': shares,
                                   'commission': round(shares * px * commission_rate, 4),
                                   'capital_after': round(capital, 2)})

        elif row['Signal'] == -1 and position > 0:
            proceeds = position * px * (1 - commission_rate - slippage)
            pnl      = proceeds - position * entry_px
            capital += proceeds
            trades.append({'date': str(idx)[:10], 'action': 'SELL',
                           'price': round(px, 4), 'shares': position,
                           'commission': round(position * px * commission_rate, 4),
                           'pnl': round(pnl, 2),
                           'pnl_pct': round(pnl / (position * entry_px) * 100, 2),
                           'capital_after': round(capital, 2)})
            position = 0

        equity.append({'date': str(idx)[:10],
                       'equity': round(capital + position * px, 2)})

    if position > 0:
        px = float(d['Close'].iloc[-1])
        proceeds = position * px * (1 - commission_rate - slippage)
        pnl      = proceeds - position * entry_px
        capital += proceeds
        trades.append({'date': str(d.index[-1])[:10], 'action': 'SELL(close)',
                       'price': round(px, 4), 'shares': position,
                       'commission': round(position * px * commission_rate, 4),
                       'pnl': round(pnl, 2),
                       'pnl_pct': round(pnl / (position * entry_px) * 100, 2),
                       'capital_after': round(capital, 2)})
        position = 0

    eq_series   = pd.Series([e['equity'] for e in equity],
                            index=pd.to_datetime([e['date'] for e in equity]))
    total_return = (capital - init_capital) / init_capital * 100
    daily_ret    = eq_series.pct_change().dropna()
    sharpe       = (daily_ret.mean() - 0.03/252) / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    rolling_max  = eq_series.cummax()
    drawdown     = (eq_series - rolling_max) / rolling_max * 100
    max_dd       = drawdown.min()

    sell_trades      = [t for t in trades if 'pnl' in t]
    win_trades       = [t for t in sell_trades if t['pnl'] > 0]
    total_commission = sum(t['commission'] for t in trades)
    total_pnl        = sum(t.get('pnl', 0) for t in sell_trades)

    metrics = {
        'strategy':         'MACD(12,26,9)',
        'init_capital':     init_capital,
        'final_capital':    round(capital, 2),
        'total_return_pct': round(total_return, 2),
        'annual_return_pct': round(daily_ret.mean() * 252 * 100, 2),
        'annual_vol_pct':    round(daily_ret.std() * np.sqrt(252) * 100, 2),
        'sharpe_ratio':      round(float(sharpe), 3),
        'max_drawdown_pct':  round(float(max_dd), 2),
        'total_trades':      len(sell_trades),
        'win_trades':        len(win_trades),
        'loss_trades':       len(sell_trades) - len(win_trades),
        'win_rate_pct':      round(len(win_trades) / len(sell_trades) * 100, 1) if sell_trades else 0,
        'total_commission':  round(total_commission, 2),
        'total_pnl':         round(total_pnl, 2),
        'commission_ratio':  round(total_commission / max(abs(total_pnl), 1) * 100, 2),
        'avg_pnl_per_trade': round(total_pnl / len(sell_trades), 2) if sell_trades else 0,
    }

    return {'metrics': metrics, 'trades': trades, 'equity': equity, 'df': d}


# ─────────────────────────────────────────────
#  可视化
# ─────────────────────────────────────────────

def plot_strategy(result: dict, title: str, save_path: str) -> str:
    d      = result['df']
    equity = result['equity']
    trades = result['trades']
    m      = result['metrics']

    fig = plt.figure(figsize=(16, 12), facecolor='#0d1117')
    gs  = GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

    ax1 = fig.add_subplot(gs[0, :])   # 价格 + 均线/MACD
    ax2 = fig.add_subplot(gs[1, :])   # 资金曲线
    ax3 = fig.add_subplot(gs[2, 0])   # 盈亏分布
    ax4 = fig.add_subplot(gs[2, 1])   # 指标总结

    def style(ax):
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e', labelsize=8)
        for s in ax.spines.values():
            s.set_color('#30363d')

    # ── 价格图 ──
    style(ax1)
    ax1.plot(d.index, d['Close'], color='#58a6ff', lw=1.2, label='收盘价')
    if 'MA_fast' in d.columns:
        ax1.plot(d.index, d['MA_fast'], color='#f0c040', lw=1, label=f"MA{m['strategy'].split('/')[0].split('MA')[-1]}")
        ax1.plot(d.index, d['MA_slow'], color='#ff7b72', lw=1, label=f"MA{m['strategy'].split('/')[1]}")
    elif 'MACD_DIF' in d.columns:
        pass  # MACD 在下方
    # 标记交易点
    buys  = [t for t in trades if t['action'] == 'BUY']
    sells = [t for t in trades if 'SELL' in t['action']]
    buy_dates  = pd.to_datetime([t['date'] for t in buys])
    sell_dates = pd.to_datetime([t['date'] for t in sells])
    buy_prices  = [t['price'] for t in buys]
    sell_prices = [t['price'] for t in sells]
    ax1.scatter(buy_dates,  buy_prices,  marker='^', color='#e84855', s=60, zorder=5, label='买入')
    ax1.scatter(sell_dates, sell_prices, marker='v', color='#00c875', s=60, zorder=5, label='卖出')
    ax1.set_title(f'{title} - 价格走势与信号', color='#e6edf3', fontsize=11, pad=8)
    ax1.legend(fontsize=7, loc='upper left', facecolor='#21262d', edgecolor='#30363d',
               labelcolor='#e6edf3')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # ── 资金曲线 ──
    style(ax2)
    eq_df = pd.DataFrame(equity)
    eq_df['date'] = pd.to_datetime(eq_df['date'])
    ax2.plot(eq_df['date'], eq_df['equity'], color='#3fb950', lw=1.5)
    ax2.axhline(m['init_capital'], color='#8b949e', lw=0.8, ls='--', label='初始资金')
    ax2.fill_between(eq_df['date'], m['init_capital'], eq_df['equity'],
                     where=eq_df['equity'] >= m['init_capital'], alpha=0.15, color='#3fb950')
    ax2.fill_between(eq_df['date'], m['init_capital'], eq_df['equity'],
                     where=eq_df['equity'] < m['init_capital'],  alpha=0.15, color='#e84855')
    ax2.set_title('策略资金曲线', color='#e6edf3', fontsize=10)
    ax2.legend(fontsize=7, facecolor='#21262d', edgecolor='#30363d', labelcolor='#e6edf3')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # ── 盈亏分布 ──
    style(ax3)
    sell_pnls = [t['pnl'] for t in trades if 'pnl' in t]
    if sell_pnls:
        colors = ['#e84855' if p > 0 else '#00c875' for p in sell_pnls]
        ax3.bar(range(len(sell_pnls)), sell_pnls, color=colors, width=0.7)
        ax3.axhline(0, color='#8b949e', lw=0.8)
        ax3.set_title('逐笔盈亏', color='#e6edf3', fontsize=10)
        ax3.set_xlabel('交易编号', color='#8b949e', fontsize=8)
        ax3.set_ylabel('盈亏 ($)', color='#8b949e', fontsize=8)

    # ── 指标文字 ──
    ax4.set_facecolor('#161b22')
    ax4.axis('off')
    lines = [
        ('策略',          m['strategy']),
        ('总收益',         f"{m['total_return_pct']:+.2f}%"),
        ('年化收益',        f"{m['annual_return_pct']:+.2f}%"),
        ('年化波动率',       f"{m['annual_vol_pct']:.2f}%"),
        ('夏普比率',        f"{m['sharpe_ratio']:.3f}"),
        ('最大回撤',        f"{m['max_drawdown_pct']:.2f}%"),
        ('总交易次数',       str(m['total_trades'])),
        ('盈利次数',        str(m['win_trades'])),
        ('亏损次数',        str(m['loss_trades'])),
        ('胜率',           f"{m['win_rate_pct']:.1f}%"),
        ('总手续费',        f"${m['total_commission']:.2f}"),
        ('手续费/盈亏占比',   f"{m['commission_ratio']:.1f}%"),
        ('每笔平均盈亏',     f"${m['avg_pnl_per_trade']:.2f}"),
    ]
    y_pos = 0.97
    for label, val in lines:
        ax4.text(0.02, y_pos, f"{label}:", color='#8b949e', fontsize=8.5,
                 transform=ax4.transAxes, va='top')
        color = '#3fb950' if ('+' in str(val) and '%' in str(val)) else \
                '#e84855' if ('-' in str(val) and '%' in str(val)) else '#e6edf3'
        ax4.text(0.55, y_pos, val, color=color, fontsize=8.5,
                 transform=ax4.transAxes, va='top', fontweight='bold')
        y_pos -= 0.072
    ax4.set_title('回测绩效指标', color='#e6edf3', fontsize=10)

    fig.suptitle(f'天勤量化策略回测 — {title}', color='#e6edf3', fontsize=13, y=0.98)
    plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    return save_path


# ─────────────────────────────────────────────
#  主运行入口
# ─────────────────────────────────────────────

def run_all(tickers=None, period='2y'):
    if tickers is None:
        tickers = ['GC=F', 'CL=F', 'GLD']

    all_results = {}
    for ticker in tickers:
        name = YAHOO_TICKERS.get(ticker, ticker)
        print(f"\n{'='*55}")
        print(f"  回测标的: {ticker} ({name})")
        print(f"{'='*55}")

        df, src = get_data(ticker, period)
        if df is None or len(df) < 60:
            print(f"  ⚠ 数据不足，跳过")
            continue
        print(f"  数据来源: {src}，共 {len(df)} 条记录")
        print(f"  时间范围: {df.index[0].date()} ~ {df.index[-1].date()}")

        df_ind = calc_indicators(df)

        # 策略 1：MA5/MA20
        res_ma = backtest_ma_cross(df_ind)
        m1 = res_ma['metrics']
        print(f"\n  [MA5/MA20] 总收益={m1['total_return_pct']:+.2f}%  夏普={m1['sharpe_ratio']:.3f}"
              f"  胜率={m1['win_rate_pct']:.1f}%  手续费=${m1['total_commission']:.2f}"
              f"  手续费占比={m1['commission_ratio']:.1f}%")
        img1 = plot_strategy(res_ma, f'{ticker}({name})', 
                             os.path.join(OUTPUT_DIR, f'ma_cross_{ticker.replace("=","_")}.png'))

        # 策略 2：MACD
        res_macd = backtest_macd(df_ind)
        m2 = res_macd['metrics']
        print(f"  [MACD]    总收益={m2['total_return_pct']:+.2f}%  夏普={m2['sharpe_ratio']:.3f}"
              f"  胜率={m2['win_rate_pct']:.1f}%  手续费=${m2['total_commission']:.2f}"
              f"  手续费占比={m2['commission_ratio']:.1f}%")
        img2 = plot_strategy(res_macd, f'{ticker}({name}) MACD',
                             os.path.join(OUTPUT_DIR, f'macd_{ticker.replace("=","_")}.png'))

        all_results[ticker] = {
            'name': name, 'source': src,
            'ma_cross': res_ma, 'macd': res_macd,
            'img_ma': img1, 'img_macd': img2
        }

    # 保存汇总
    summary = {}
    for t, r in all_results.items():
        summary[t] = {
            'name': r['name'], 'source': r['source'],
            'ma_cross': r['ma_cross']['metrics'],
            'macd':     r['macd']['metrics'],
        }
    out_json = os.path.join(OUTPUT_DIR, 'strategy_results.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 策略结果已保存: {out_json}")

    return all_results


# ─────────────────────────────────────────────
# 附：天勤 TqSdk 真实策略示例（注释）
# ─────────────────────────────────────────────
"""
# 若已安装 tqsdk 并注册账户，可使用以下真实代码连接天勤行情：
#
# from tqsdk import TqApi, TqAuth, TqBacktest, TqSim
# from tqsdk.tafunc import ma
# from datetime import date
#
# api = TqApi(TqSim(init_balance=100000),
#             auth=TqAuth("your_username", "your_password"),
#             backtest=TqBacktest(start_dt=date(2023,1,1), end_dt=date(2024,12,31)))
#
# klines = api.get_kline_serial("SHFE.au2412", 60*60*24)  # 黄金主力，日K
#
# while True:
#     api.wait_update()
#     if api.is_changing(klines.iloc[-1], "datetime"):
#         fast_ma = ma(klines["close"], 5)
#         slow_ma = ma(klines["close"], 20)
#         if fast_ma.iloc[-1] > slow_ma.iloc[-1] and fast_ma.iloc[-2] <= slow_ma.iloc[-2]:
#             print("金叉：买入信号")
#         elif fast_ma.iloc[-1] < slow_ma.iloc[-1] and fast_ma.iloc[-2] >= slow_ma.iloc[-2]:
#             print("死叉：卖出信号")
# api.close()
"""


if __name__ == '__main__':
    results = run_all(tickers=['GC=F', 'CL=F', 'GLD'], period='2y')
    print("\n=== 完成 ===")
