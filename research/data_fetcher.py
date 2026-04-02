"""
data_fetcher.py
===============
统一数据获取模块：优先使用 yfinance（真实数据），回退到 AKShare。
支持的标的覆盖：外盘期货、贵金属 ETF、能源股，用于协整扫描。

Yahoo Finance 说明：
  - yfinance 直接访问 Yahoo Finance API，国内网络下可能需要代理。
  - 若出现超时，请设置环境变量 HTTP_PROXY / HTTPS_PROXY，或在本机开启代理。
  - AKShare 数据源通常国内可直连。
"""

import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
import time

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# 全市场扫描标的列表（Yahoo Finance Ticker）
# ─────────────────────────────────────────────
YAHOO_TICKERS = {
    # 贵金属期货/ETF
    'GC=F':  '黄金期货(COMEX)',
    'SI=F':  '白银期货(COMEX)',
    'GLD':   '黄金ETF(SPDR)',
    'SLV':   '白银ETF(iShares)',
    'PPLT':  '铂金ETF',

    # 能源
    'CL=F':  'WTI原油期货',
    'BZ=F':  '布伦特原油期货',
    'NG=F':  '天然气期货',
    'USO':   '原油ETF(USO)',
    'UNG':   '天然气ETF(UNG)',

    # 工业金属
    'HG=F':  '铜期货(COMEX)',
    'ALI=F': '铝期货',
    'PL=F':  '铂期货',
    'PA=F':  '钯金期货',

    # 农产品
    'ZW=F':  '小麦期货',
    'ZC=F':  '玉米期货',
    'ZS=F':  '大豆期货',
    'CT=F':  '棉花期货',
    'KC=F':  '咖啡期货',
    'SB=F':  '白糖期货',

    # 相关股票 (可用于跨品种协整)
    'XOM':   '埃克森美孚(石油)',
    'CVX':   '雪佛龙(石油)',
    'NEM':   '纽蒙特(黄金矿业)',
    'GOLD':  'Barrick黄金',
    'FCX':   '自由港(铜矿)',
    'BHP':   '必和必拓(矿业)',
}

# AKShare 对应映射（仅 5 个基础品种）
AKSHARE_MAP = {
    'GC=F':  'COMEX黄金',
    'SI=F':  'COMEX白银',
    'CL=F':  'WTI原油',
    'HG=F':  'COMEX铜',
    'NG=F':  'NYMEX天然气',
}


def fetch_yfinance(ticker: str, period: str = '2y') -> pd.DataFrame | None:
    """
    用 yfinance 获取 OHLCV 数据（带重试）。
    period 支持: 1mo 3mo 6mo 1y 2y 5y max
    """
    import yfinance as yf
    # 先尝试 download（通常比 Ticker.history 更稳定）
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=period, auto_adjust=True,
                             progress=False, timeout=20)
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                # yfinance >=0.2 返回 MultiIndex 列时需要展开
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
                df.index.name = 'Date'
                return df
        except Exception as e:
            print(f"  [yfinance] {ticker} 第{attempt+1}次失败: {e}")
            time.sleep(2 + attempt * 2)
    return None


def fetch_akshare(symbol: str, period: str = '2y') -> pd.DataFrame | None:
    """用 AKShare 获取外盘期货数据"""
    try:
        import akshare as ak
        df = ak.futures_foreign_hist(symbol=symbol)
        if df is None or df.empty:
            return None
        df['日期'] = pd.to_datetime(df['日期'])
        df.set_index('日期', inplace=True)
        df = df.rename(columns={'开盘': 'Open', '最高': 'High', '最低': 'Low',
                                '收盘': 'Close', '成交量': 'Volume'})
        # 截断到指定周期
        end = datetime.now()
        period_days = {'1mo': 30, '3mo': 90, '6mo': 180, '1y': 365, '2y': 730, '5y': 1825}
        days = period_days.get(period, 730)
        start = end - timedelta(days=days)
        df = df[df.index >= start]
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
        return df
    except Exception as e:
        print(f"  [akshare] {symbol} 获取失败: {e}")
        return None


def generate_synthetic(ticker: str, period: str = '2y') -> pd.DataFrame:
    """
    生成高质量合成数据（基于真实历史均值/波动率参数）
    网络不可用时用作兜底，保证 Case 可运行。
    参数来源：2020-2024 年实际历史统计。
    """
    # (起始价, 年化波动率, 年化漂移率)
    params = {
        'GC=F':  (1800,  0.16,  0.10),  # 黄金
        'SI=F':  (22,    0.28,  0.05),  # 白银
        'CL=F':  (75,    0.40,  0.02),  # WTI原油
        'BZ=F':  (80,    0.38,  0.02),  # 布伦特原油
        'NG=F':  (3.0,   0.60, -0.05),  # 天然气
        'HG=F':  (3.8,   0.22,  0.04),  # 铜
        'ALI=F': (2200,  0.18,  0.02),  # 铝
        'PL=F':  (950,   0.20, -0.02),  # 铂
        'PA=F':  (1600,  0.30, -0.08),  # 钯
        'ZW=F':  (580,   0.30,  0.01),  # 小麦
        'ZC=F':  (460,   0.25, -0.01),  # 玉米
        'ZS=F':  (1300,  0.22,  0.01),  # 大豆
        'CT=F':  (80,    0.25,  0.00),  # 棉花
        'KC=F':  (180,   0.35,  0.05),  # 咖啡
        'SB=F':  (20,    0.28,  0.03),  # 白糖
        'GLD':   (170,   0.16,  0.10),  # 黄金ETF
        'SLV':   (20,    0.28,  0.05),  # 白银ETF
        'PPLT':  (80,    0.20,  0.00),  # 铂金ETF
        'USO':   (65,    0.40,  0.02),  # 原油ETF
        'UNG':   (15,    0.60, -0.05),  # 天然气ETF
        'XOM':   (90,    0.22,  0.08),  # 埃克森
        'CVX':   (140,   0.22,  0.07),  # 雪佛龙
        'NEM':   (45,    0.28,  0.03),  # 纽蒙特
        'GOLD':  (18,    0.32,  0.02),  # Barrick
        'FCX':   (35,    0.35,  0.05),  # 自由港
        'BHP':   (55,    0.25,  0.06),  # 必和必拓
    }
    p0, ann_vol, ann_drift = params.get(ticker, (100, 0.25, 0.03))
    period_days = {'1mo': 22, '3mo': 66, '6mo': 132, '1y': 252, '2y': 504, '5y': 1260}
    n = period_days.get(period, 504)

    np.random.seed(abs(hash(ticker)) % (2**31))
    dt       = 1 / 252
    mu       = ann_drift * dt
    sigma    = ann_vol   * np.sqrt(dt)
    log_ret  = np.random.normal(mu - 0.5 * sigma**2, sigma, n)
    prices   = p0 * np.exp(np.cumsum(log_ret))
    prices   = np.maximum(prices, p0 * 0.2)

    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dates = pd.date_range(end=end, periods=n, freq='B')

    noise = np.abs(np.random.normal(0, sigma, n))
    highs = prices * (1 + noise)
    lows  = prices * (1 - noise)
    opens = prices * (1 + np.random.normal(0, sigma * 0.5, n))
    vols  = np.random.lognormal(12, 1, n).astype(int)

    df = pd.DataFrame({
        'Open': opens, 'High': highs, 'Low': lows,
        'Close': prices, 'Volume': vols
    }, index=dates)
    df.index.name = 'Date'
    return df


def get_data(ticker: str, period: str = '2y', source: str = 'auto') -> tuple[pd.DataFrame | None, str]:
    """
    获取数据，返回 (DataFrame, 数据源名称)
    source: 'auto'(yf优先→ak回退→合成兜底) | 'yfinance' | 'akshare' | 'synthetic'
    """
    df = None
    src = 'none'

    if source in ('auto', 'yfinance'):
        df = fetch_yfinance(ticker, period)
        if df is not None and not df.empty:
            src = 'Yahoo Finance'

    if df is None and source in ('auto', 'akshare'):
        ak_sym = AKSHARE_MAP.get(ticker)
        if ak_sym:
            df = fetch_akshare(ak_sym, period)
            if df is not None and not df.empty:
                src = 'AKShare'

    # 合成数据兜底（确保 Case 可运行）
    if df is None or df.empty:
        df = generate_synthetic(ticker, period)
        src = '合成数据(GBM模型)'

    return df, src


def get_multi_close(tickers: list[str], period: str = '2y') -> tuple[pd.DataFrame, dict]:
    """
    批量获取多个标的的收盘价，对齐时间轴。
    返回 (close_df, {ticker: source_name})
    注意：网络不可用时自动使用合成数据，保证 Case 可运行。
    """
    closes = {}
    sources = {}
    for ticker in tickers:
        print(f"  获取 {ticker} ({YAHOO_TICKERS.get(ticker, ticker)}) ...")
        df, src = get_data(ticker, period)   # 已含合成数据兜底
        if df is not None and not df.empty and len(df) >= 60:
            closes[ticker] = df['Close']
            sources[ticker] = src
        else:
            print(f"    WARNING: {ticker} 数据不足，跳过")
        time.sleep(0.3)  # 避免频率限制

    if not closes:
        return pd.DataFrame(), sources

    close_df = pd.DataFrame(closes)
    # 保留至少有 50% 列有值的行（thresh = 最少非NaN列数）
    min_cols = max(1, int(len(close_df.columns) * 0.5))
    close_df = close_df.dropna(thresh=min_cols)
    close_df = close_df.fillna(method='ffill').fillna(method='bfill')
    return close_df, sources


if __name__ == '__main__':
    # 快速测试
    print("=== 测试数据获取 ===")
    for t in ['GC=F', 'GLD', 'CL=F']:
        df, src = get_data(t, '1y')
        if df is not None:
            print(f"  {t} ({YAHOO_TICKERS[t]}): {len(df)} 行, 来源={src}, 最新收盘={df['Close'].iloc[-1]:.2f}")
        else:
            print(f"  {t}: 获取失败")
