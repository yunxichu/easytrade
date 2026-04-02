"""
cointegration_arbitrage.py
==========================
协整套利全市场扫描与模拟交易模块

理论基础：
  Engle-Granger 两步协整检验
  1. 对价格序列做 ADF 单位根检验（各自 I(1)）
  2. OLS 配对回归，对残差做 ADF → 残差 I(0) 则协整
  3. 利用残差 z-score 作为交易信号：
     - z > threshold → 做空 Y，做多 X（价差均值回归）
     - z < -threshold → 做多 Y，做空 X

套利执行：
  - 信号阈值：z > 2 开仓，z < 0.5 平仓
  - 止损：z > 3.5 触发
  - 半衰期滚动窗口（Ornstein-Uhlenbeck 均值回复速度估计）

量化指标输出：
  - 总盈亏、年化收益
  - 手续费金额、手续费占盈亏比
  - 胜率、交易次数
  - 夏普比率、最大回撤
  - Calmar 比率
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from itertools import combinations
import json
import os
import sys
import warnings
warnings.filterwarnings('ignore')

from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from scipy import stats

sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import get_multi_close, YAHOO_TICKERS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────
#  全市场候选标的（分组，同组内做套利更有逻辑性）
# ─────────────────────────────────────────────
SCAN_GROUPS = {
    '贵金属':  ['GC=F', 'SI=F', 'GLD', 'SLV', 'NEM', 'GOLD'],
    '能源':    ['CL=F', 'BZ=F', 'NG=F', 'USO', 'XOM', 'CVX'],
    '工业金属': ['HG=F', 'FCX', 'BHP'],
    '农产品':  ['ZW=F', 'ZC=F', 'ZS=F'],
    '跨板块':  ['GC=F', 'CL=F', 'HG=F', 'ZW=F', 'ZS=F'],
}

# 仅扫描以下组（可调整）
DEFAULT_SCAN = ['贵金属', '能源', '工业金属']


# ─────────────────────────────────────────────
#  ADF 单位根 & 协整检验
# ─────────────────────────────────────────────

def adf_test(series: pd.Series, sig_level: float = 0.05) -> tuple[bool, float]:
    """返回 (是否单位根, p值)"""
    result = adfuller(series.dropna(), autolag='AIC')
    return result[1] > sig_level, result[1]


def engle_granger_coint(y: pd.Series, x: pd.Series, sig_level: float = 0.10) -> dict:
    """
    Engle-Granger 协整检验
    返回详细检验结果
    """
    # 对齐
    common = y.index.intersection(x.index)
    y = y[common].dropna()
    x = x[common].dropna()
    common = y.index.intersection(x.index)
    y, x = y[common], x[common]

    if len(common) < 60:
        return {'cointegrated': False, 'reason': 'insufficient_data'}

    # 步骤1：各序列 ADF
    y_is_unit, y_pval = adf_test(y)
    x_is_unit, x_pval = adf_test(x)

    # 步骤2：OLS 残差
    X = add_constant(x.values)
    model = OLS(y.values, X).fit()
    beta   = model.params[1]
    alpha  = model.params[0]
    resid  = pd.Series(model.resid, index=common)

    # 步骤3：残差 ADF
    resid_is_unit, resid_pval = adf_test(resid)
    cointegrated = (not resid_is_unit) and (resid_pval < sig_level)

    # 使用 statsmodels coint 函数做双重验证
    coint_t, coint_pval, _ = coint(y.values, x.values)
    cointegrated = cointegrated or (coint_pval < sig_level)

    # 半衰期（OU 过程估计）
    half_life = estimate_half_life(resid)

    # 相关系数
    corr = float(np.corrcoef(y.values, x.values)[0, 1])

    return {
        'cointegrated':   cointegrated,
        'beta':           round(float(beta), 6),
        'alpha':          round(float(alpha), 6),
        'resid_adf_pval': round(float(resid_pval), 4),
        'coint_pval':     round(float(coint_pval), 4),
        'corr':           round(corr, 4),
        'half_life':      round(float(half_life), 1),
        'n_obs':          len(common),
        'y_adf_pval':     round(float(y_pval), 4),
        'x_adf_pval':     round(float(x_pval), 4),
        'resid':          resid,
    }


def estimate_half_life(spread: pd.Series) -> float:
    """通过 AR(1) 估计 OU 过程的半衰期（天）"""
    spread_lag  = spread.shift(1).dropna()
    spread_diff = spread.diff().dropna()
    common      = spread_lag.index.intersection(spread_diff.index)
    X = add_constant(spread_lag[common].values)
    model = OLS(spread_diff[common].values, X).fit()
    lam = model.params[1]
    if lam >= 0:
        return 999.0  # 不均值回复
    return float(-np.log(2) / lam)


# ─────────────────────────────────────────────
#  全市场扫描
# ─────────────────────────────────────────────

def scan_all_pairs(close_df: pd.DataFrame, groups: list[str] = None,
                   sig_level: float = 0.10) -> pd.DataFrame:
    """
    遍历所有候选配对，返回协整结果 DataFrame（按 p 值排序）
    """
    if groups is None:
        groups = DEFAULT_SCAN

    # 收集需扫描的标的
    scan_tickers = set()
    for g in groups:
        for t in SCAN_GROUPS.get(g, []):
            if t in close_df.columns:
                scan_tickers.add(t)
    scan_tickers = list(scan_tickers)

    print(f"\n扫描 {len(scan_tickers)} 个标的，共 {len(list(combinations(scan_tickers,2)))} 对...")

    records = []
    for y_t, x_t in combinations(scan_tickers, 2):
        r = engle_granger_coint(close_df[y_t], close_df[x_t], sig_level=sig_level)
        if 'reason' in r:
            continue
        records.append({
            'y_ticker':      y_t,
            'x_ticker':      x_t,
            'y_name':        YAHOO_TICKERS.get(y_t, y_t),
            'x_name':        YAHOO_TICKERS.get(x_t, x_t),
            'cointegrated':  r['cointegrated'],
            'coint_pval':    r['coint_pval'],
            'resid_adf_pval':r['resid_adf_pval'],
            'corr':          r['corr'],
            'beta':          r['beta'],
            'alpha':         r['alpha'],
            'half_life':     r['half_life'],
            'n_obs':         r['n_obs'],
        })

    df_scan = pd.DataFrame(records)
    if df_scan.empty:
        return df_scan
    df_scan = df_scan.sort_values('coint_pval')
    return df_scan


# ─────────────────────────────────────────────
#  协整套利模拟交易
# ─────────────────────────────────────────────

def simulate_arbitrage(close_df: pd.DataFrame, y_ticker: str, x_ticker: str,
                       beta: float = None, alpha: float = None,
                       entry_z: float = 2.0, exit_z: float = 0.5, stop_z: float = 3.5,
                       roll_window: int = 60,
                       init_capital: float = 200_000,
                       position_pct: float = 0.20,
                       commission_rate: float = 0.0003,
                       slippage: float = 0.0001) -> dict:
    """
    协整套利模拟交易（z-score 均值回归策略）

    position_pct: 每次开仓占总资金比例
    commission_rate: 单边手续费（对 y 和 x 各收一次）
    """
    # 对齐序列
    common = close_df[y_ticker].dropna().index.intersection(
             close_df[x_ticker].dropna().index)
    y = close_df[y_ticker][common]
    x = close_df[x_ticker][common]

    # 滚动回归计算价差
    if beta is None:
        # 用全样本 OLS 确定对冲比例
        X = add_constant(x.values)
        model = OLS(y.values, X).fit()
        beta  = model.params[1]
        alpha = model.params[0]

    spread = y - beta * x - alpha

    # 滚动 z-score
    roll_mean = spread.rolling(roll_window).mean()
    roll_std  = spread.rolling(roll_window).std(ddof=1)
    z_score   = (spread - roll_mean) / roll_std.replace(0, np.nan)
    z_score   = z_score.dropna()

    # ── 回测 ──
    capital    = init_capital
    position   = None   # None | 'long_spread' | 'short_spread'
    entry_idx  = None
    entry_z_val= 0.0
    trades     = []
    equity     = []
    peak_cap   = init_capital

    dates = z_score.index
    for i, date in enumerate(dates):
        z = float(z_score[date])
        y_px = float(y[date])
        x_px = float(x[date])

        # ── 开仓 ──
        if position is None:
            invest = capital * position_pct
            y_shares = int(invest / (y_px * 2))   # 投 50% 到 Y
            x_shares = int(invest * abs(beta) / (x_px * 2))  # 50% 到 X（对冲）
            if y_shares < 1 or x_shares < 1:
                equity.append({'date': str(date)[:10], 'equity': round(capital, 2)})
                continue

            if z > entry_z:
                # 价差偏高 → 做空 Y 做多 X
                cost_y = y_shares * y_px * (commission_rate + slippage)
                cost_x = x_shares * x_px * (commission_rate + slippage)
                total_cost = cost_y + cost_x
                if total_cost < capital * 0.1:
                    position    = 'short_spread'
                    entry_idx   = i
                    entry_z_val = z
                    entry_y_px  = y_px
                    entry_x_px  = x_px
                    entry_y_sh  = y_shares
                    entry_x_sh  = x_shares
                    capital    -= total_cost  # 只扣手续费，保证金另算
                    trades.append({'date': str(date)[:10], 'action': 'SHORT_SPREAD',
                                   'y_price': round(y_px, 4), 'x_price': round(x_px, 4),
                                   'z_score': round(z, 3),
                                   'y_shares': y_shares, 'x_shares': x_shares,
                                   'commission': round(total_cost, 4)})

            elif z < -entry_z:
                # 价差偏低 → 做多 Y 做空 X
                cost_y = y_shares * y_px * (commission_rate + slippage)
                cost_x = x_shares * x_px * (commission_rate + slippage)
                total_cost = cost_y + cost_x
                if total_cost < capital * 0.1:
                    position    = 'long_spread'
                    entry_idx   = i
                    entry_z_val = z
                    entry_y_px  = y_px
                    entry_x_px  = x_px
                    entry_y_sh  = y_shares
                    entry_x_sh  = x_shares
                    capital    -= total_cost
                    trades.append({'date': str(date)[:10], 'action': 'LONG_SPREAD',
                                   'y_price': round(y_px, 4), 'x_price': round(x_px, 4),
                                   'z_score': round(z, 3),
                                   'y_shares': y_shares, 'x_shares': x_shares,
                                   'commission': round(total_cost, 4)})

        # ── 平仓 ──
        elif position == 'short_spread':
            close_cond = abs(z) < exit_z
            stop_cond  = z > stop_z  # 继续扩大 → 止损

            if close_cond or stop_cond:
                # Y: 平空 → 盈利 = entry - exit
                pnl_y =  entry_y_sh * (entry_y_px - y_px)
                # X: 平多 → 盈利 = exit - entry
                pnl_x =  entry_x_sh * (x_px - entry_x_px)
                total_pnl = pnl_y + pnl_x
                # 平仓手续费
                close_comm = (entry_y_sh * y_px + entry_x_sh * x_px) * (commission_rate + slippage)
                net_pnl    = total_pnl - close_comm
                capital   += net_pnl
                reason     = '止损' if stop_cond else '均值回归平仓'
                trades.append({'date': str(date)[:10], 'action': 'CLOSE_SHORT',
                               'y_price': round(y_px, 4), 'x_price': round(x_px, 4),
                               'z_score': round(z, 3),
                               'pnl': round(net_pnl, 2),
                               'commission': round(close_comm, 4),
                               'reason': reason,
                               'hold_days': i - entry_idx})
                position = None

        elif position == 'long_spread':
            close_cond = abs(z) < exit_z
            stop_cond  = z < -stop_z

            if close_cond or stop_cond:
                pnl_y = entry_y_sh * (y_px - entry_y_px)
                pnl_x = entry_x_sh * (entry_x_px - x_px)
                total_pnl = pnl_y + pnl_x
                close_comm = (entry_y_sh * y_px + entry_x_sh * x_px) * (commission_rate + slippage)
                net_pnl    = total_pnl - close_comm
                capital   += net_pnl
                reason     = '止损' if stop_cond else '均值回归平仓'
                trades.append({'date': str(date)[:10], 'action': 'CLOSE_LONG',
                               'y_price': round(y_px, 4), 'x_price': round(x_px, 4),
                               'z_score': round(z, 3),
                               'pnl': round(net_pnl, 2),
                               'commission': round(close_comm, 4),
                               'reason': reason,
                               'hold_days': i - entry_idx})
                position = None

        # 资金曲线（含未平仓浮动盈亏）
        if position in ('short_spread',):
            unrealized = entry_y_sh * (entry_y_px - y_px) + entry_x_sh * (x_px - entry_x_px)
        elif position in ('long_spread',):
            unrealized = entry_y_sh * (y_px - entry_y_px) + entry_x_sh * (entry_x_px - x_px)
        else:
            unrealized = 0
        curr_equity = capital + unrealized
        equity.append({'date': str(date)[:10], 'equity': round(curr_equity, 2)})
        if curr_equity > peak_cap:
            peak_cap = curr_equity

    # 强制平仓最后持仓
    if position is not None:
        y_px = float(y.iloc[-1])
        x_px = float(x.iloc[-1])
        if position == 'short_spread':
            pnl_y = entry_y_sh * (entry_y_px - y_px)
            pnl_x = entry_x_sh * (x_px - entry_x_px)
        else:
            pnl_y = entry_y_sh * (y_px - entry_y_px)
            pnl_x = entry_x_sh * (entry_x_px - x_px)
        close_comm = (entry_y_sh * y_px + entry_x_sh * x_px) * (commission_rate + slippage)
        net_pnl = pnl_y + pnl_x - close_comm
        capital += net_pnl
        trades.append({'date': str(dates[-1])[:10], 'action': 'FORCE_CLOSE',
                       'pnl': round(net_pnl, 2), 'commission': round(close_comm, 4),
                       'reason': '到期强制平仓'})

    # ── 绩效统计 ──
    close_trades   = [t for t in trades if 'pnl' in t]
    win_trades     = [t for t in close_trades if t['pnl'] > 0]
    total_pnl      = sum(t['pnl'] for t in close_trades)
    total_comm     = sum(t['commission'] for t in trades)
    total_return   = (capital - init_capital) / init_capital * 100

    eq_series = pd.Series([e['equity'] for e in equity],
                          index=pd.to_datetime([e['date'] for e in equity]))
    daily_ret = eq_series.pct_change().dropna()
    ann_ret   = daily_ret.mean() * 252 * 100
    ann_vol   = daily_ret.std() * np.sqrt(252) * 100
    sharpe    = (daily_ret.mean() - 0.03/252) / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    dd        = (eq_series - eq_series.cummax()) / eq_series.cummax() * 100
    max_dd    = float(dd.min())
    calmar    = ann_ret / abs(max_dd) if max_dd < 0 else 0

    avg_hold  = np.mean([t.get('hold_days', 0) for t in close_trades]) if close_trades else 0

    metrics = {
        'pair':               f'{y_ticker} / {x_ticker}',
        'pair_name':          f'{YAHOO_TICKERS.get(y_ticker,y_ticker)} / {YAHOO_TICKERS.get(x_ticker,x_ticker)}',
        'beta':               round(float(beta), 4),
        'init_capital':       init_capital,
        'final_capital':      round(capital, 2),
        'total_return_pct':   round(total_return, 2),
        'annual_return_pct':  round(ann_ret, 2),
        'annual_vol_pct':     round(ann_vol, 2),
        'sharpe_ratio':       round(float(sharpe), 3),
        'max_drawdown_pct':   round(max_dd, 2),
        'calmar_ratio':       round(calmar, 3),
        'total_trades':       len(close_trades),
        'win_trades':         len(win_trades),
        'loss_trades':        len(close_trades) - len(win_trades),
        'win_rate_pct':       round(len(win_trades) / len(close_trades) * 100, 1) if close_trades else 0,
        'total_pnl':          round(total_pnl, 2),
        'total_commission':   round(total_comm, 2),
        'commission_ratio':   round(total_comm / max(abs(total_pnl), 1) * 100, 2),
        'avg_hold_days':      round(avg_hold, 1),
        'avg_pnl_per_trade':  round(total_pnl / len(close_trades), 2) if close_trades else 0,
    }

    return {
        'metrics': metrics, 'trades': trades, 'equity': equity,
        'spread': spread, 'z_score': z_score,
        'y': y, 'x': x
    }


# ─────────────────────────────────────────────
#  可视化
# ─────────────────────────────────────────────

def plot_arbitrage(result: dict, save_path: str) -> str:
    m       = result['metrics']
    spread  = result['spread']
    z_score = result['z_score']
    equity  = result['equity']
    trades  = result['trades']
    y_ser   = result['y']
    x_ser   = result['x']

    fig = plt.figure(figsize=(18, 14), facecolor='#0d1117')
    gs  = GridSpec(4, 2, figure=fig, hspace=0.50, wspace=0.35)

    ax1 = fig.add_subplot(gs[0, :])   # 双价格归一化
    ax2 = fig.add_subplot(gs[1, :])   # 价差 + z-score
    ax3 = fig.add_subplot(gs[2, :])   # 资金曲线
    ax4 = fig.add_subplot(gs[3, 0])   # 盈亏分布
    ax5 = fig.add_subplot(gs[3, 1])   # 绩效

    def style(ax):
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e', labelsize=8)
        for s in ax.spines.values():
            s.set_color('#30363d')

    y_norm = y_ser / y_ser.iloc[0] * 100
    x_norm = x_ser / x_ser.iloc[0] * 100

    # ── 归一化价格 ──
    style(ax1)
    ax1.plot(y_norm.index, y_norm, color='#58a6ff', lw=1.2,
             label=f'{m["pair"].split("/")[0].strip()} (Y)')
    ax1.plot(x_norm.index, x_norm, color='#f0c040', lw=1.2,
             label=f'{m["pair"].split("/")[1].strip()} (X)')
    ax1.set_title(f'协整套利 — {m["pair_name"]}  归一化价格（基=100）',
                  color='#e6edf3', fontsize=11)
    ax1.legend(fontsize=8, facecolor='#21262d', edgecolor='#30363d', labelcolor='#e6edf3')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # ── 价差 z-score ──
    style(ax2)
    ax2_twin = ax2.twinx()
    ax2_twin.set_facecolor('#161b22')
    ax2.plot(spread.index, spread, color='#8b949e', lw=0.8, alpha=0.6, label='价差')
    ax2_twin.plot(z_score.index, z_score, color='#da8eff', lw=1.2, label='z-score')
    ax2_twin.axhline(2.0,  color='#e84855', lw=0.8, ls='--', alpha=0.7)
    ax2_twin.axhline(-2.0, color='#00c875', lw=0.8, ls='--', alpha=0.7)
    ax2_twin.axhline(0,    color='#8b949e', lw=0.8, ls='-',  alpha=0.5)
    ax2_twin.axhline(3.5,  color='#e84855', lw=0.6, ls=':',  alpha=0.5)
    ax2_twin.axhline(-3.5, color='#00c875', lw=0.6, ls=':',  alpha=0.5)
    # 标记开平仓
    open_trades  = [t for t in trades if 'SPREAD' in t.get('action','') and 'CLOSE' not in t.get('action','')]
    close_trades = [t for t in trades if 'CLOSE' in t.get('action','')]
    if open_trades:
        ax2_twin.scatter(pd.to_datetime([t['date'] for t in open_trades]),
                         [t.get('z_score', 0) for t in open_trades],
                         marker='o', color='#ffa657', s=40, zorder=5, label='开仓')
    if close_trades:
        ok = [t for t in close_trades if 'pnl' in t]
        if ok:
            ax2_twin.scatter(pd.to_datetime([t['date'] for t in ok]),
                             [t.get('z_score', 0) for t in ok],
                             marker='x', color='#3fb950', s=40, zorder=5, label='平仓')
    ax2.set_title('价差与 z-score（±2 开仓，±0.5 平仓，±3.5 止损）', color='#e6edf3', fontsize=10)
    ax2.set_ylabel('价差', color='#8b949e', fontsize=8)
    ax2_twin.set_ylabel('z-score', color='#da8eff', fontsize=8)
    ax2_twin.legend(fontsize=7, facecolor='#21262d', edgecolor='#30363d', labelcolor='#e6edf3', loc='upper right')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # ── 资金曲线 ──
    style(ax3)
    eq_df = pd.DataFrame(equity)
    eq_df['date'] = pd.to_datetime(eq_df['date'])
    ax3.plot(eq_df['date'], eq_df['equity'], color='#3fb950', lw=1.5)
    ax3.axhline(m['init_capital'], color='#8b949e', lw=0.8, ls='--')
    ax3.fill_between(eq_df['date'], m['init_capital'], eq_df['equity'],
                     where=eq_df['equity'] >= m['init_capital'], alpha=0.12, color='#3fb950')
    ax3.fill_between(eq_df['date'], m['init_capital'], eq_df['equity'],
                     where=eq_df['equity'] < m['init_capital'],  alpha=0.12, color='#e84855')
    ax3.set_title('套利资金曲线', color='#e6edf3', fontsize=10)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # ── 逐笔盈亏 ──
    style(ax4)
    pnls = [t['pnl'] for t in trades if 'pnl' in t]
    if pnls:
        colors = ['#e84855' if p > 0 else '#00c875' for p in pnls]
        ax4.bar(range(len(pnls)), pnls, color=colors, width=0.7)
        ax4.axhline(0, color='#8b949e', lw=0.8)
        ax4.set_title('逐笔套利盈亏', color='#e6edf3', fontsize=10)
        ax4.set_xlabel('交易编号', color='#8b949e', fontsize=8)
        ax4.set_ylabel('盈亏 ($)', color='#8b949e', fontsize=8)

    # ── 绩效 ──
    ax5.set_facecolor('#161b22')
    ax5.axis('off')
    lines = [
        ('套利对',          m['pair_name']),
        ('对冲比例 β',       f"{m['beta']:.4f}"),
        ('总收益',          f"{m['total_return_pct']:+.2f}%"),
        ('年化收益',         f"{m['annual_return_pct']:+.2f}%"),
        ('年化波动率',        f"{m['annual_vol_pct']:.2f}%"),
        ('夏普比率',         f"{m['sharpe_ratio']:.3f}"),
        ('最大回撤',         f"{m['max_drawdown_pct']:.2f}%"),
        ('Calmar 比率',     f"{m['calmar_ratio']:.3f}"),
        ('总交易次数',        str(m['total_trades'])),
        ('胜率',            f"{m['win_rate_pct']:.1f}%"),
        ('平均持仓天数',      f"{m['avg_hold_days']:.1f} 天"),
        ('总手续费',         f"${m['total_commission']:.2f}"),
        ('手续费/盈亏占比',    f"{m['commission_ratio']:.1f}%"),
        ('每笔平均盈亏',      f"${m['avg_pnl_per_trade']:.2f}"),
    ]
    y_pos = 0.98
    for label, val in lines:
        ax5.text(0.02, y_pos, f"{label}:", color='#8b949e', fontsize=8,
                 transform=ax5.transAxes, va='top')
        color = '#3fb950' if '+' in str(val) else '#e84855' if '-' in str(val) else '#e6edf3'
        ax5.text(0.58, y_pos, val, color=color, fontsize=8,
                 transform=ax5.transAxes, va='top', fontweight='bold')
        y_pos -= 0.065
    ax5.set_title('套利绩效指标', color='#e6edf3', fontsize=10)

    fig.suptitle(f'协整套利回测 — {m["pair_name"]}', color='#e6edf3', fontsize=13, y=0.99)
    plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    return save_path


# ─────────────────────────────────────────────
#  主运行入口
# ─────────────────────────────────────────────

def run_scan_and_trade(period='2y', top_n=3):
    """全市场扫描 + 对最优配对模拟交易"""

    # 汇总所有候选标的
    all_tickers = []
    for g in DEFAULT_SCAN:
        all_tickers.extend(SCAN_GROUPS.get(g, []))
    all_tickers = list(dict.fromkeys(all_tickers))  # 去重

    print(f"=== 协整套利全市场扫描 ===")
    print(f"候选标的: {len(all_tickers)} 个")
    print(f"获取数据中（period={period}）...")

    close_df, sources = get_multi_close(all_tickers, period)
    if close_df.empty:
        print("获取数据失败，退出")
        return {}

    print(f"\n成功获取 {len(close_df.columns)} 个标的，{len(close_df)} 个交易日")
    print(f"数据来源: {set(sources.values())}")

    # 协整扫描
    scan_df = scan_all_pairs(close_df)
    if scan_df.empty:
        print("未找到协整配对")
        return {}

    cointegrated = scan_df[scan_df['cointegrated'] == True]
    print(f"\n发现协整配对: {len(cointegrated)} / {len(scan_df)} 对")
    print("\nTop 10 协整对（按协整 p 值排序）：")
    print(cointegrated[['y_name','x_name','coint_pval','corr','half_life','beta']].head(10).to_string(index=False))

    # 保存扫描结果
    scan_out = os.path.join(OUTPUT_DIR, 'cointegration_scan.csv')
    scan_df.to_csv(scan_out, index=False, encoding='utf-8-sig')
    print(f"\n[OK] 扫描结果已保存: {scan_out}")

    # 对 Top-N 进行模拟交易
    top_pairs = cointegrated.head(top_n)
    arb_results = {}
    img_paths   = []

    for _, row in top_pairs.iterrows():
        y_t = row['y_ticker']
        x_t = row['x_ticker']
        b   = row['beta']
        a   = row['alpha']
        print(f"\n{'─'*55}")
        print(f"  套利对: {row['y_name']} / {row['x_name']}")
        print(f"  协整 p={row['coint_pval']:.4f}  β={b:.4f}  半衰期={row['half_life']:.1f}天")

        res = simulate_arbitrage(close_df, y_t, x_t, beta=b, alpha=a)
        m   = res['metrics']
        print(f"  总收益={m['total_return_pct']:+.2f}%  夏普={m['sharpe_ratio']:.3f}"
              f"  胜率={m['win_rate_pct']:.1f}%  手续费占比={m['commission_ratio']:.1f}%"
              f"  交易次数={m['total_trades']}")

        img_name = f"arb_{y_t.replace('=','_')}_{x_t.replace('=','_')}.png"
        img_path = os.path.join(OUTPUT_DIR, img_name)
        plot_arbitrage(res, img_path)
        img_paths.append(img_path)
        arb_results[f'{y_t}_{x_t}'] = {**res, 'img': img_path, 'scan_info': row.to_dict()}

    # 保存套利结果 JSON
    summary = {}
    for k, v in arb_results.items():
        summary[k] = v['metrics']
    out_json = os.path.join(OUTPUT_DIR, 'arbitrage_results.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 套利结果已保存: {out_json}")

    return {
        'scan_df':     scan_df,
        'arb_results': arb_results,
        'img_paths':   img_paths,
        'close_df':    close_df,
    }


if __name__ == '__main__':
    results = run_scan_and_trade(period='2y', top_n=3)
    print("\n=== 完成 ===")
