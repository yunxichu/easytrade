"""
Project: 截面多空交易系统 (Cross-Sectional Long-Short Trading System)

核心逻辑：
1. 截面动量因子：在多个品种之间横向排名，买入强势、卖出弱势
2. 多因子融合：动量(1M/3M/6M)、波动率倒数、RSI因子
3. Z-score 标准化截面信号
4. 等权多空组合构建（TOP分位做多 / BOTTOM分位做空）
5. 完整回测引擎：净值曲线、夏普、最大回撤、IC分析
"""

from flask import Blueprint, jsonify, request
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

cs_bp = Blueprint('cross_section', __name__, url_prefix='/api/cross-section')

# ──────────────────────────────────────────────
# 数据生成层（GBM合成，可替换为真实数据）
# ──────────────────────────────────────────────

UNIVERSE = {
    '黄金':   {'mu': 0.0002, 'sigma': 0.010, 'base': 2050},
    '原油':   {'mu': 0.0001, 'sigma': 0.022, 'base': 78},
    '白银':   {'mu': 0.0003, 'sigma': 0.016, 'base': 24},
    '铜':     {'mu': 0.0002, 'sigma': 0.014, 'base': 4.2},
    '天然气': {'mu': -0.0001,'sigma': 0.028, 'base': 2.8},
    '铝':     {'mu': 0.0001, 'sigma': 0.013, 'base': 2200},
    '锌':     {'mu': 0.0002, 'sigma': 0.015, 'base': 2500},
    '镍':     {'mu': 0.0001, 'sigma': 0.020, 'base': 17000},
    '大豆':   {'mu': 0.0001, 'sigma': 0.012, 'base': 1420},
    '玉米':   {'mu': 0.0001, 'sigma': 0.011, 'base': 680},
    '小麦':   {'mu': 0.0000, 'sigma': 0.013, 'base': 590},
    '棉花':   {'mu': 0.0001, 'sigma': 0.015, 'base': 80},
}


def generate_price_series(name, n=504, seed=None):
    """GBM 生成价格序列（约2年日线数据）"""
    params = UNIVERSE[name]
    if seed is None:
        seed = sum(ord(c) for c in name)
    rng = np.random.default_rng(seed)
    dt = 1 / 252
    rets = (params['mu'] - 0.5 * params['sigma']**2) * dt + \
           params['sigma'] * np.sqrt(dt) * rng.standard_normal(n)
    prices = params['base'] * np.exp(np.cumsum(rets))
    # 使用纯日期索引（无时间分量），避免并发时间戳不对齐
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.Series(prices, index=dates, name=name)


def get_all_prices(n=504):
    """获取全品种价格矩阵 DataFrame (rows=dates, cols=commodities)"""
    # 先生成统一日期范围
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    data = {}
    for name in UNIVERSE:
        params = UNIVERSE[name]
        seed = sum(ord(c) for c in name)
        rng = np.random.default_rng(seed)
        dt = 1 / 252
        rets = (params['mu'] - 0.5 * params['sigma']**2) * dt + \
               params['sigma'] * np.sqrt(dt) * rng.standard_normal(n)
        data[name] = params['base'] * np.exp(np.cumsum(rets))
    df = pd.DataFrame(data, index=dates)
    df.index.name = 'date'
    return df


# ──────────────────────────────────────────────
# 因子计算模块
# ──────────────────────────────────────────────

def compute_momentum(prices, window):
    """滚动动量因子 = 过去 window 天收益率"""
    return prices.pct_change(window, fill_method=None)


def compute_volatility_inverse(prices, window=20):
    """波动率倒数因子（低波动溢价）"""
    vol = prices.pct_change(fill_method=None).rolling(window).std()
    return 1.0 / (vol + 1e-8)


def compute_rsi_factor(prices, window=14):
    """RSI 因子 (超卖品种做多 → 均值回归)"""
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / (loss + 1e-8)
    rsi = 100 - 100 / (1 + rs)
    # 转成因子：RSI低的品种得分高（均值回归信号）
    return 100 - rsi


def compute_ma_deviation(prices, short=5, long=20):
    """均线偏离因子 = MA短/MA长 - 1（趋势跟踪）"""
    return prices.rolling(short).mean() / prices.rolling(long).mean() - 1


def zscore_cross_section(factor_df):
    """截面 Z-score 标准化：每行（每个交易日）对所有品种标准化"""
    mean = factor_df.mean(axis=1)
    std = factor_df.std(axis=1).replace(0, np.nan)
    return factor_df.sub(mean, axis=0).div(std, axis=0)


def combine_factors(prices, factor_weights=None):
    """
    多因子合成：
    - MOM_1M (weight 0.3): 1个月动量
    - MOM_3M (weight 0.3): 3个月动量
    - VOL_INV (weight 0.2): 波动率倒数
    - RSI_REV (weight 0.1): RSI均值回归
    - MA_DEV (weight 0.1): 均线偏离
    返回截面 Z-score 合成因子
    """
    if factor_weights is None:
        factor_weights = {
            'MOM_1M': 0.3,
            'MOM_3M': 0.3,
            'VOL_INV': 0.2,
            'RSI_REV': 0.1,
            'MA_DEV':  0.1,
        }

    factors = {
        'MOM_1M': zscore_cross_section(compute_momentum(prices, 21)),
        'MOM_3M': zscore_cross_section(compute_momentum(prices, 63)),
        'VOL_INV': zscore_cross_section(compute_volatility_inverse(prices, 20)),
        'RSI_REV': zscore_cross_section(compute_rsi_factor(prices, 14)),
        'MA_DEV':  zscore_cross_section(compute_ma_deviation(prices)),
    }

    combined = sum(factors[k] * w for k, w in factor_weights.items())
    return combined, factors


# ──────────────────────────────────────────────
# 信号生成：多空分组
# ──────────────────────────────────────────────

def generate_signals(combined_factor, long_quantile=0.75, short_quantile=0.25):
    """
    截面多空信号：
    - signal > long_quantile  → +1 (做多)
    - signal < short_quantile → -1 (做空)
    - 其余                    →  0 (空仓)
    """
    signals = pd.DataFrame(0.0, index=combined_factor.index, columns=combined_factor.columns)
    for date, row in combined_factor.iterrows():
        valid = row.dropna()
        if len(valid) < 4:
            continue
        lo_thresh = valid.quantile(short_quantile)
        hi_thresh = valid.quantile(long_quantile)
        for asset, val in valid.items():
            if val >= hi_thresh:
                signals.loc[date, asset] = 1.0
            elif val <= lo_thresh:
                signals.loc[date, asset] = -1.0
    return signals


def compute_weights(signals, weighting='equal'):
    """
    组合权重计算
    equal: 多头等权 long / 空头等权 short
    factor: 按因子值大小加权（待实现）
    """
    weights = signals.copy()
    for date, row in signals.iterrows():
        long_mask = row == 1.0
        short_mask = row == -1.0
        n_long = long_mask.sum()
        n_short = short_mask.sum()
        if n_long > 0:
            weights.loc[date, long_mask] = 1.0 / n_long
        if n_short > 0:
            weights.loc[date, short_mask] = -1.0 / n_short
    return weights


# ──────────────────────────────────────────────
# 回测引擎
# ──────────────────────────────────────────────

def run_backtest(prices, rebalance_freq='weekly', long_q=0.75, short_q=0.25,
                 transaction_cost=0.0003, slippage=0.0002):
    """
    截面多空回测引擎
    参数：
        rebalance_freq: 'daily' | 'weekly'
        long_q / short_q: 多空分位阈值
        transaction_cost: 手续费率
        slippage: 滑点
    """
    # 1. 计算因子
    combined, factors = combine_factors(prices)

    # 2. 生成信号（基于前一日因子，避免未来信息）
    signals = generate_signals(combined.shift(1), long_q, short_q)
    weights = compute_weights(signals)

    # 3. 计算日收益率
    daily_rets = prices.pct_change(fill_method=None)

    # 4. 换仓频率过滤
    if rebalance_freq == 'weekly':
        # 每周一(dayofweek==0)或实际第一个交易日换仓，其余前向填充
        rebalance_mask = weights.index.to_series().dt.dayofweek == 0
        # 先置非换仓日权重为 NaN，再前向填充
        weights_rebal = weights.copy().astype(float)
        weights_rebal[~rebalance_mask] = np.nan
        weights_rebal = weights_rebal.ffill()
        weights_rebal = weights_rebal.fillna(0.0)
        weights = weights_rebal

    # 5. 组合收益
    port_rets = (weights * daily_rets).sum(axis=1)

    # 6. 扣除交易成本（换仓日扣除）
    weight_diff = weights.diff().abs().sum(axis=1)
    cost = weight_diff * (transaction_cost + slippage)
    port_rets = port_rets - cost

    # 7. 净值曲线
    port_rets = port_rets.fillna(0)
    nav = (1 + port_rets).cumprod()

    # 8. 分解：多头腿 / 空头腿
    long_weights = weights.clip(lower=0)
    short_weights = weights.clip(upper=0)
    long_rets = (long_weights * daily_rets).sum(axis=1).fillna(0)
    short_rets = (short_weights * daily_rets).sum(axis=1).fillna(0)
    long_nav = (1 + long_rets).cumprod()
    short_nav = (1 + short_rets).cumprod()

    # 9. 统计指标
    ann_factor = 252
    total_return = float(nav.iloc[-1] - 1) if len(nav) > 0 else 0
    ann_return = float((1 + total_return) ** (ann_factor / max(len(nav), 1)) - 1)
    ann_vol = float(port_rets.std() * np.sqrt(ann_factor))
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # 最大回撤
    rolling_max = nav.cummax()
    drawdown = (nav - rolling_max) / rolling_max
    max_dd = float(drawdown.min())

    # 胜率
    win_rate = float((port_rets > 0).mean())

    # Calmar Ratio
    calmar = ann_return / abs(max_dd) if max_dd != 0 else 0

    # 月度收益
    monthly_rets = port_rets.resample('ME').apply(lambda x: (1+x).prod() - 1)

    # 10. IC 分析（因子预测力）
    ic_series = {}
    for fname, fdf in factors.items():
        # IC = 因子值 与 未来1周收益率 的截面相关
        fwd_ret = daily_rets.shift(-5)  # 已用 fill_method=None
        ic_vals = []
        for date in fdf.index[:-10]:
            f_row = fdf.loc[date].dropna()
            r_row = fwd_ret.loc[date].dropna()
            common = f_row.index.intersection(r_row.index)
            if len(common) >= 4:
                ic = float(f_row[common].corr(r_row[common]))
                ic_vals.append({'date': date.strftime('%Y-%m-%d'), 'ic': round(ic, 4)})
        ic_series[fname] = ic_vals[-20:] if ic_vals else []  # 只返回最近20期

    mean_ic = {}
    for fname, ics in ic_series.items():
        vals = [x['ic'] for x in ics if not np.isnan(x['ic'])]
        mean_ic[fname] = round(float(np.mean(vals)), 4) if vals else 0.0

    return {
        'nav': [{'date': d.strftime('%Y-%m-%d'), 'nav': round(float(v), 4)}
                for d, v in nav.items()],
        'long_nav': [{'date': d.strftime('%Y-%m-%d'), 'nav': round(float(v), 4)}
                     for d, v in long_nav.items()],
        'short_nav': [{'date': d.strftime('%Y-%m-%d'), 'nav': round(float(v), 4)}
                      for d, v in short_nav.items()],
        'metrics': {
            'total_return': round(total_return * 100, 2),
            'ann_return': round(ann_return * 100, 2),
            'ann_vol': round(ann_vol * 100, 2),
            'sharpe': round(sharpe, 3),
            'max_drawdown': round(max_dd * 100, 2),
            'win_rate': round(win_rate * 100, 2),
            'calmar': round(calmar, 3),
        },
        'monthly_rets': [
            {'month': d.strftime('%Y-%m'), 'ret': round(float(v) * 100, 2)}
            for d, v in monthly_rets.items()
            if not np.isnan(v)
        ],
        'mean_ic': mean_ic,
        'ic_series': {k: v[-30:] for k, v in ic_series.items()},  # 最近30期
    }


def get_latest_portfolio(prices, long_q=0.75, short_q=0.25):
    """获取最新一期持仓"""
    combined, factors = combine_factors(prices)
    latest_factor = combined.iloc[-1].dropna()

    if len(latest_factor) < 4:
        return {}

    lo_thresh = latest_factor.quantile(short_q)
    hi_thresh = latest_factor.quantile(long_q)

    portfolio = []
    for asset, val in latest_factor.items():
        if val >= hi_thresh:
            side = 'long'
        elif val <= lo_thresh:
            side = 'short'
        else:
            side = 'flat'
        portfolio.append({
            'asset': asset,
            'factor_score': round(float(val), 3),
            'side': side,
            'price': round(float(prices[asset].iloc[-1]), 2),
            'ret_1m': round(float(prices[asset].pct_change(21).iloc[-1]) * 100, 2),
            'ret_3m': round(float(prices[asset].pct_change(63).iloc[-1]) * 100, 2),
        })
    portfolio.sort(key=lambda x: x['factor_score'], reverse=True)
    return portfolio


def get_factor_breakdown(prices):
    """返回各因子最新截面得分（用于热力图）"""
    _, factors = combine_factors(prices)
    result = {}
    for fname, fdf in factors.items():
        latest = fdf.iloc[-1].dropna()
        result[fname] = {
            asset: round(float(v), 3) for asset, v in latest.items()
        }
    return result


# ──────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────

@cs_bp.route('/universe')
def get_universe():
    """品种列表"""
    return jsonify({'success': True, 'data': list(UNIVERSE.keys())})


@cs_bp.route('/backtest')
def backtest():
    """运行回测"""
    freq = request.args.get('freq', 'weekly')
    long_q = float(request.args.get('long_q', 0.75))
    short_q = float(request.args.get('short_q', 0.25))
    cost = float(request.args.get('cost', 0.0003))

    try:
        prices = get_all_prices(504)
        result = run_backtest(prices, rebalance_freq=freq,
                              long_q=long_q, short_q=short_q,
                              transaction_cost=cost)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        logger.error(f"回测失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@cs_bp.route('/portfolio')
def current_portfolio():
    """最新持仓"""
    long_q = float(request.args.get('long_q', 0.75))
    short_q = float(request.args.get('short_q', 0.25))
    try:
        prices = get_all_prices(504)
        data = get_latest_portfolio(prices, long_q, short_q)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@cs_bp.route('/factors')
def factor_breakdown():
    """各因子截面得分分解"""
    try:
        prices = get_all_prices(504)
        data = get_factor_breakdown(prices)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@cs_bp.route('/prices/<asset>')
def asset_prices(asset):
    """单品种价格序列"""
    if asset not in UNIVERSE:
        return jsonify({'success': False, 'error': '品种不存在'}), 404
    prices = get_all_prices(504)
    series = prices[asset]
    data = [{'date': d.strftime('%Y-%m-%d'), 'price': round(float(v), 4)}
            for d, v in series.items()]
    return jsonify({'success': True, 'asset': asset, 'data': data})
