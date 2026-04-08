"""
作业2：股票市场信息模块
使用 AKShare 获取 A股市场数据，包含反爬机制处理
"""

from flask import Blueprint, jsonify, request
import pandas as pd
import numpy as np
import akshare as ak
import time
import random
import logging
from datetime import datetime, timedelta
from functools import wraps
import threading

logger = logging.getLogger(__name__)

stock_bp = Blueprint('stock', __name__, url_prefix='/api/stock')

# ──────────────────────────────────────────────
# 缓存层：避免频繁请求触发反爬
# ──────────────────────────────────────────────
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5分钟缓存


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)
        if item and time.time() - item['ts'] < CACHE_TTL:
            return item['data']
        return None


def cache_set(key, data):
    with _cache_lock:
        _cache[key] = {'data': data, 'ts': time.time()}


def anti_crawl_delay(min_s=0.5, max_s=1.5):
    """随机延迟，模拟人类访问节奏，避免触发反爬"""
    time.sleep(random.uniform(min_s, max_s))


def safe_akshare(func, *args, retries=2, **kwargs):
    """
    带重试和反爬延迟的 AKShare 调用包装器
    AKShare 内部已有 User-Agent 随机化；此处补充随机延迟 + 重试
    """
    for attempt in range(retries):
        try:
            anti_crawl_delay(0.3, 0.8)
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            logger.warning(f"AKShare 调用失败 (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(random.uniform(1.0, 2.0))
    return None


# ──────────────────────────────────────────────
# 生成模拟股票数据（当 AKShare 受限时备用）
# ──────────────────────────────────────────────

def mock_stock_list():
    """返回模拟的沪深300成分股数据"""
    stocks = [
        {'code': '600519', 'name': '贵州茅台', 'market': '上交所', 'industry': '食品饮料'},
        {'code': '000858', 'name': '五粮液', 'market': '深交所', 'industry': '食品饮料'},
        {'code': '601318', 'name': '中国平安', 'market': '上交所', 'industry': '金融'},
        {'code': '000001', 'name': '平安银行', 'market': '深交所', 'industry': '金融'},
        {'code': '600036', 'name': '招商银行', 'market': '上交所', 'industry': '金融'},
        {'code': '601166', 'name': '兴业银行', 'market': '上交所', 'industry': '金融'},
        {'code': '000333', 'name': '美的集团', 'market': '深交所', 'industry': '家电'},
        {'code': '600900', 'name': '长江电力', 'market': '上交所', 'industry': '电力'},
        {'code': '601012', 'name': '隆基绿能', 'market': '上交所', 'industry': '新能源'},
        {'code': '002594', 'name': '比亚迪', 'market': '深交所', 'industry': '新能源车'},
        {'code': '600276', 'name': '恒瑞医药', 'market': '上交所', 'industry': '医药'},
        {'code': '000651', 'name': '格力电器', 'market': '深交所', 'industry': '家电'},
        {'code': '601888', 'name': '中国中免', 'market': '上交所', 'industry': '零售'},
        {'code': '600887', 'name': '伊利股份', 'market': '上交所', 'industry': '食品饮料'},
        {'code': '002415', 'name': '海康威视', 'market': '深交所', 'industry': '科技'},
        {'code': '600030', 'name': '中信证券', 'market': '上交所', 'industry': '证券'},
        {'code': '601728', 'name': '中国电信', 'market': '上交所', 'industry': '通信'},
        {'code': '000725', 'name': '京东方A', 'market': '深交所', 'industry': '电子'},
        {'code': '601601', 'name': '中国太保', 'market': '上交所', 'industry': '保险'},
        {'code': '600309', 'name': '万华化学', 'market': '上交所', 'industry': '化工'},
    ]
    np.random.seed(42)
    for s in stocks:
        price_base = np.random.uniform(10, 1800)
        change_pct = np.random.uniform(-3.5, 4.0)
        s['price'] = round(price_base, 2)
        s['change'] = round(price_base * change_pct / 100, 2)
        s['change_pct'] = round(change_pct, 2)
        s['volume'] = int(np.random.uniform(1e6, 5e8))
        s['turnover'] = round(s['volume'] * price_base / 1e8, 2)
        s['pe_ttm'] = round(np.random.uniform(8, 80), 1)
        s['pb'] = round(np.random.uniform(0.5, 8.0), 2)
        s['market_cap'] = round(price_base * np.random.uniform(1e8, 1e10) / 1e8, 1)
    return stocks


def mock_market_overview():
    """模拟大盘指数数据"""
    indices = [
        {'name': '上证指数', 'code': 'sh000001', 'price': 3285.51, 'change': 12.35, 'change_pct': 0.38},
        {'name': '深证成指', 'code': 'sz399001', 'price': 10521.83, 'change': -23.4, 'change_pct': -0.22},
        {'name': '创业板指', 'code': 'sz399006', 'price': 2098.76, 'change': 8.91, 'change_pct': 0.43},
        {'name': '科创50', 'code': 'sh000688', 'price': 986.42, 'change': -4.12, 'change_pct': -0.42},
        {'name': '沪深300', 'code': 'sh000300', 'price': 3812.55, 'change': 15.6, 'change_pct': 0.41},
    ]
    return indices


def mock_sector_data():
    """模拟行业板块数据"""
    sectors = [
        {'name': '新能源', 'change_pct': 3.21, 'volume': 8521},
        {'name': '半导体', 'change_pct': 2.87, 'volume': 6234},
        {'name': '人工智能', 'change_pct': 2.54, 'volume': 7890},
        {'name': '医药生物', 'change_pct': 1.32, 'volume': 4521},
        {'name': '食品饮料', 'change_pct': 0.87, 'volume': 3201},
        {'name': '金融', 'change_pct': 0.43, 'volume': 5632},
        {'name': '地产', 'change_pct': -0.65, 'volume': 2341},
        {'name': '钢铁', 'change_pct': -1.23, 'volume': 1892},
        {'name': '煤炭', 'change_pct': -1.87, 'volume': 2156},
        {'name': '航运', 'change_pct': -2.34, 'volume': 1543},
    ]
    return sectors


def mock_kline(code, period='daily'):
    """生成模拟K线数据"""
    np.random.seed(hash(code) % 100)
    n = 120
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0.0003, 0.018)))
    prices = np.array(prices)
    opens = prices * (1 + np.random.uniform(-0.005, 0.005, n))
    highs = np.maximum(prices, opens) * (1 + np.abs(np.random.normal(0, 0.008, n)))
    lows = np.minimum(prices, opens) * (1 - np.abs(np.random.normal(0, 0.008, n)))
    volumes = np.random.uniform(1e6, 5e7, n).astype(int)
    result = []
    for i in range(n):
        result.append({
            'date': dates[i].strftime('%Y-%m-%d'),
            'open': round(float(opens[i]), 2),
            'high': round(float(highs[i]), 2),
            'low': round(float(lows[i]), 2),
            'close': round(float(prices[i]), 2),
            'volume': int(volumes[i]),
        })
    return result


# ──────────────────────────────────────────────
# AKShare 真实数据获取（含反爬处理）
# ──────────────────────────────────────────────

def get_real_market_overview():
    """获取大盘指数行情（AKShare）"""
    cached = cache_get('market_overview')
    if cached:
        return cached

    try:
        # stock_zh_index_spot_sina: 实时指数行情
        df = safe_akshare(ak.stock_zh_index_spot_sina)
        if df is None or df.empty:
            raise ValueError("空数据")

        target_codes = ['sh000001', 'sz399001', 'sz399006', 'sh000688', 'sh000300']
        result = []
        for _, row in df.iterrows():
            code = str(row.get('代码', row.get('code', ''))).lower()
            if code in target_codes:
                try:
                    price = float(row.get('最新价', row.get('close', 0)))
                    change = float(row.get('涨跌额', row.get('change', 0)))
                    change_pct = float(str(row.get('涨跌幅', row.get('pct_chg', '0%'))).replace('%', ''))
                except:
                    price = change = change_pct = 0.0
                result.append({
                    'name': str(row.get('名称', row.get('name', code))),
                    'code': code,
                    'price': round(price, 2),
                    'change': round(change, 2),
                    'change_pct': round(change_pct, 2),
                    'source': 'akshare'
                })

        if result:
            cache_set('market_overview', result)
            return result
    except Exception as e:
        logger.warning(f"AKShare 大盘行情获取失败: {e}")

    data = mock_market_overview()
    cache_set('market_overview', data)
    return data


def get_real_stock_list():
    """获取A股实时行情（AKShare）"""
    cached = cache_get('stock_list')
    if cached:
        return cached

    try:
        # stock_zh_a_spot_em: 东方财富实时行情
        df = safe_akshare(ak.stock_zh_a_spot_em)
        if df is None or df.empty:
            raise ValueError("空数据")

        df = df.head(50)  # 只取前50只
        result = []
        for _, row in df.iterrows():
            try:
                result.append({
                    'code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'price': round(float(row.get('最新价', 0) or 0), 2),
                    'change': round(float(row.get('涨跌额', 0) or 0), 2),
                    'change_pct': round(float(row.get('涨跌幅', 0) or 0), 2),
                    'volume': int(row.get('成交量', 0) or 0),
                    'turnover': round(float(row.get('成交额', 0) or 0) / 1e8, 2),
                    'pe_ttm': round(float(row.get('市盈率-动态', 0) or 0), 1),
                    'pb': round(float(row.get('市净率', 0) or 0), 2),
                    'market_cap': round(float(row.get('总市值', 0) or 0) / 1e8, 1),
                    'industry': str(row.get('所属行业', '—')),
                    'market': '上交所' if str(row.get('代码', '')).startswith('6') else '深交所',
                    'source': 'akshare'
                })
            except:
                continue

        if result:
            cache_set('stock_list', result)
            return result
    except Exception as e:
        logger.warning(f"AKShare 股票列表获取失败: {e}")

    data = mock_stock_list()
    cache_set('stock_list', data)
    return data


def get_real_sector_data():
    """获取行业板块涨跌（AKShare）"""
    cached = cache_get('sector_data')
    if cached:
        return cached

    try:
        df = safe_akshare(ak.stock_board_industry_name_em)
        if df is None or df.empty:
            raise ValueError("空数据")
        result = []
        for _, row in df.iterrows():
            try:
                result.append({
                    'name': str(row.get('板块名称', '')),
                    'change_pct': round(float(row.get('涨跌幅', 0) or 0), 2),
                    'volume': int(row.get('成交量', 0) or 0),
                    'source': 'akshare'
                })
            except:
                continue
        result.sort(key=lambda x: x['change_pct'], reverse=True)
        result = result[:20]
        if result:
            cache_set('sector_data', result)
            return result
    except Exception as e:
        logger.warning(f"AKShare 行业数据获取失败: {e}")

    data = mock_sector_data()
    cache_set('sector_data', data)
    return data


def get_real_kline(code, period='daily'):
    """获取个股K线（AKShare）"""
    cache_key = f'kline_{code}_{period}'
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        anti_crawl_delay(0.5, 1.0)
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=180)).strftime('%Y%m%d')
        df = ak.stock_zh_a_hist(symbol=code, period=period,
                                start_date=start, end_date=end, adjust='qfq')
        if df is None or df.empty:
            raise ValueError("空数据")

        result = []
        for _, row in df.iterrows():
            try:
                result.append({
                    'date': str(row.get('日期', '')),
                    'open': round(float(row.get('开盘', 0)), 2),
                    'high': round(float(row.get('最高', 0)), 2),
                    'low': round(float(row.get('最低', 0)), 2),
                    'close': round(float(row.get('收盘', 0)), 2),
                    'volume': int(row.get('成交量', 0)),
                })
            except:
                continue

        if result:
            cache_set(cache_key, result)
            return result
    except Exception as e:
        logger.warning(f"AKShare K线获取失败 {code}: {e}")

    data = mock_kline(code, period)
    cache_set(cache_key, data)
    return data


def get_market_breadth():
    """市场宽度：涨跌家数、涨停/跌停数"""
    cached = cache_get('market_breadth')
    if cached:
        return cached

    try:
        df = safe_akshare(ak.stock_zh_a_spot_em)
        if df is None or df.empty:
            raise ValueError("")
        changes = pd.to_numeric(df.get('涨跌幅', pd.Series()), errors='coerce').dropna()
        result = {
            'up': int((changes > 0).sum()),
            'down': int((changes < 0).sum()),
            'flat': int((changes == 0).sum()),
            'limit_up': int((changes >= 9.9).sum()),
            'limit_down': int((changes <= -9.9).sum()),
            'source': 'akshare'
        }
        cache_set('market_breadth', result)
        return result
    except Exception as e:
        logger.warning(f"市场宽度获取失败: {e}")
        result = {'up': 2156, 'down': 1823, 'flat': 312, 'limit_up': 23, 'limit_down': 8, 'source': 'mock'}
        cache_set('market_breadth', result)
        return result


# ──────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────

@stock_bp.route('/market/overview')
def market_overview():
    """大盘指数行情"""
    data = get_real_market_overview()
    return jsonify({'success': True, 'data': data})


@stock_bp.route('/list')
def stock_list():
    """A股实时行情列表（支持搜索）"""
    query = request.args.get('q', '').strip()
    data = get_real_stock_list()
    if query:
        data = [s for s in data if query in s.get('name', '') or query in s.get('code', '')]
    return jsonify({'success': True, 'data': data, 'total': len(data)})


@stock_bp.route('/sectors')
def sector_data():
    """行业板块涨跌幅"""
    data = get_real_sector_data()
    return jsonify({'success': True, 'data': data})


@stock_bp.route('/kline/<code>')
def stock_kline(code):
    """个股K线数据"""
    period = request.args.get('period', 'daily')
    data = get_real_kline(code, period)
    return jsonify({'success': True, 'code': code, 'data': data})


@stock_bp.route('/breadth')
def market_breadth():
    """市场宽度（涨跌家数）"""
    data = get_market_breadth()
    return jsonify({'success': True, 'data': data})


@stock_bp.route('/top-gainers')
def top_gainers():
    """涨幅榜 TOP10"""
    data = get_real_stock_list()
    sorted_data = sorted(data, key=lambda x: x.get('change_pct', 0), reverse=True)
    return jsonify({'success': True, 'data': sorted_data[:10]})


@stock_bp.route('/top-losers')
def top_losers():
    """跌幅榜 TOP10"""
    data = get_real_stock_list()
    sorted_data = sorted(data, key=lambda x: x.get('change_pct', 0))
    return jsonify({'success': True, 'data': sorted_data[:10]})


@stock_bp.route('/top-volume')
def top_volume():
    """成交额榜 TOP10"""
    data = get_real_stock_list()
    sorted_data = sorted(data, key=lambda x: x.get('turnover', 0), reverse=True)
    return jsonify({'success': True, 'data': sorted_data[:10]})
