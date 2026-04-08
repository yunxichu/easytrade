"""
quant_api.py  —  量化全流程 API 接口预设
===========================================
架构：数据接入 → 因子库 → 模型层 → 组合优化 → 信号输出

接入方式：
    from quant_api import quant_bp
    app.register_blueprint(quant_bp)

所有接口均以 /api/quant/ 为前缀。
当你完成具体模块后，只需替换对应函数体即可；
接口签名（路径、参数、返回格式）不需要改动。
"""

from flask import Blueprint, jsonify, request
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

quant_bp = Blueprint('quant', __name__, url_prefix='/api/quant')

# ===========================================================
# 辅助：占位返回（接口已注册但尚未实现）
# ===========================================================
def _stub(module: str, detail: str = "", **kwargs):
    """返回统一的「待实现」结构，前端可据此渲染 placeholder UI"""
    return {
        "status": "stub",           # stub | ok | error
        "module": module,
        "message": f"[待接入] {module} 模块接口已预设，请实现后替换此占位体。{detail}",
        "timestamp": datetime.now().isoformat(),
        **kwargs
    }


# ===========================================================
# ① 数据接入层  /api/quant/data/*
# ===========================================================

@quant_bp.route('/data/sources', methods=['GET'])
def list_data_sources():
    """
    列出当前已注册的数据源及其状态。
    返回：
        [{ id, name, type, status, fields, latency_ms }]
    接入说明：
        - 替换 sources 列表，接入你的实际数据源（AKShare / tqsdk / Wind / Bloomberg 等）
        - status: "active" | "inactive" | "error"
    """
    sources = [
        {
            "id": "akshare",
            "name": "AKShare（外盘期货）",
            "type": "market_data",
            "status": "inactive",          # ← 替换为实际连通性检测
            "fields": ["open", "high", "low", "close", "volume", "open_interest"],
            "latency_ms": None,
            "note": "futures_foreign_hist / spot_price 系列接口"
        },
        {
            "id": "yfinance",
            "name": "Yahoo Finance（ETF/股票）",
            "type": "market_data",
            "status": "inactive",          # ← 需要代理时设为 inactive
            "fields": ["open", "high", "low", "close", "volume"],
            "latency_ms": None,
            "note": "yf.download，需 HTTPS_PROXY 代理"
        },
        {
            "id": "tqsdk",
            "name": "天勤 TqSdk（国内期货）",
            "type": "market_data",
            "status": "inactive",
            "fields": ["open", "high", "low", "close", "volume", "open_interest", "settlement"],
            "latency_ms": None,
            "note": "需天勤账号；支持实时 tick 与历史 kline"
        },
        {
            "id": "synthetic",
            "name": "GBM 合成数据（回测用）",
            "type": "synthetic",
            "status": "active",
            "fields": ["open", "high", "low", "close", "volume"],
            "latency_ms": 0,
            "note": "基于真实参数的几何布朗运动，用于无网络时的 CI 保障"
        },
        {
            "id": "custom_csv",
            "name": "自定义 CSV / Parquet",
            "type": "file",
            "status": "ready",
            "fields": ["any"],
            "latency_ms": 0,
            "note": "上传后通过 /api/quant/data/upload 接入"
        }
    ]
    return jsonify({"status": "ok", "sources": sources})


@quant_bp.route('/data/fetch', methods=['POST'])
def fetch_data():
    """
    统一数据获取接口。
    Body (JSON):
        {
          "source":   "akshare" | "yfinance" | "tqsdk" | "synthetic",
          "symbols":  ["GC=F", "CL=F", ...],
          "start":    "2023-01-01",          // 可选
          "end":      "2024-12-31",          // 可选
          "period":   "1y",                  // 可选，与 start/end 二选一
          "freq":     "1d" | "1h" | "1min"  // K线频率
        }
    返回：
        {
          "status": "ok",
          "data": {
            "GC=F": [{"date":..., "open":..., "high":..., "low":..., "close":..., "volume":...}, ...]
          },
          "meta": {"source": ..., "rows": ..., "freq": ...}
        }
    接入说明：
        - 解析 body，调用对应数据源 SDK
        - 统一转为上述格式后返回
    """
    body = request.get_json(silent=True) or {}
    source  = body.get("source", "synthetic")
    symbols = body.get("symbols", ["GC=F"])
    period  = body.get("period", "1y")
    freq    = body.get("freq", "1d")

    # ── 当前仅 synthetic 已实现 ──────────────────────────────
    if source == "synthetic":
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))
        try:
            from data_fetcher import generate_synthetic
            result_data = {}
            for sym in symbols:
                df = generate_synthetic(sym, period)
                df.index = df.index.strftime('%Y-%m-%d')
                result_data[sym] = df.reset_index().rename(
                    columns={'Date': 'date', 'Open': 'open', 'High': 'high',
                             'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
                ).to_dict('records')
            return jsonify({
                "status": "ok",
                "data": result_data,
                "meta": {"source": "synthetic", "rows": {s: len(v) for s, v in result_data.items()}, "freq": freq}
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── 其他数据源：待实现占位 ───────────────────────────────
    return jsonify(_stub(
        module=f"data_fetch/{source}",
        detail=f"请在 quant_api.py fetch_data() 中实现 {source} 数据源",
        requested=body
    ))


@quant_bp.route('/data/upload', methods=['POST'])
def upload_data():
    """
    上传自定义 CSV/Parquet 数据文件。
    接入说明：
        - 解析 multipart/form-data，读取文件，存为 research/user_data/<filename>
        - 返回文件摘要（行数、列名、时间范围）
    """
    return jsonify(_stub(
        module="data_upload",
        detail="接收 multipart/form-data，字段 file=<your_file.csv>"
    ))


# ===========================================================
# ② 因子库  /api/quant/factors/*
# ===========================================================

@quant_bp.route('/factors/catalog', methods=['GET'])
def factor_catalog():
    """
    返回可用因子目录。
    接入说明：
        - 在 factors 列表中注册你实现的因子，前端自动渲染
        - category: "technical" | "fundamental" | "alternative" | "macro" | "custom"
        - status: "implemented" | "stub"
    """
    factors = [
        # ── 技术因子 ──────────────────────────────────────────
        {"id": "momentum_1m",   "name": "1个月动量",    "category": "technical",
         "formula": "close_t / close_{t-21} - 1",     "status": "stub"},
        {"id": "momentum_3m",   "name": "3个月动量",    "category": "technical",
         "formula": "close_t / close_{t-63} - 1",     "status": "stub"},
        {"id": "rsi_14",        "name": "RSI(14)",      "category": "technical",
         "formula": "Wilder RSI 14日",                 "status": "stub"},
        {"id": "macd_signal",   "name": "MACD信号",     "category": "technical",
         "formula": "EMA12 - EMA26，信号线 EMA9",      "status": "stub"},
        {"id": "bb_width",      "name": "布林带宽度",   "category": "technical",
         "formula": "(upper - lower) / middle",        "status": "stub"},
        {"id": "atr_14",        "name": "ATR(14)",      "category": "technical",
         "formula": "真实波幅14日均值",                 "status": "stub"},
        {"id": "vol_ratio",     "name": "量比",          "category": "technical",
         "formula": "volume / avg_volume_5d",          "status": "stub"},
        {"id": "hv20",          "name": "20日历史波动率","category": "technical",
         "formula": "std(log_ret, 20) * sqrt(252)",   "status": "implemented"},  # 已在主应用实现
        # ── 宏观/基本面因子（需接入外部数据）──────────────────
        {"id": "carry",         "name": "期限结构Carry", "category": "fundamental",
         "formula": "(spot - front_future) / spot",   "status": "stub"},
        {"id": "basis",         "name": "基差",          "category": "fundamental",
         "formula": "spot - front_future",             "status": "stub"},
        {"id": "cot_net",       "name": "COT净持仓",     "category": "alternative",
         "formula": "CFTC商业净持仓变化",               "status": "stub"},
        {"id": "dollar_idx",    "name": "美元指数相关性","category": "macro",
         "formula": "rolling corr(commodity, DXY, 60)","status": "stub"},
        # ── 自定义因子（预留槽位）────────────────────────────
        {"id": "custom_1",      "name": "自定义因子 1",  "category": "custom",
         "formula": "待定义",                           "status": "stub"},
        {"id": "custom_2",      "name": "自定义因子 2",  "category": "custom",
         "formula": "待定义",                           "status": "stub"},
    ]
    return jsonify({"status": "ok", "factors": factors, "total": len(factors)})


@quant_bp.route('/factors/compute', methods=['POST'])
def compute_factors():
    """
    计算指定因子值。
    Body (JSON):
        {
          "factor_ids": ["momentum_1m", "hv20", ...],
          "symbols":    ["GC=F", "CL=F"],
          "period":     "1y",
          "source":     "synthetic"
        }
    返回：
        {
          "status": "ok",
          "factor_matrix": {
            "GC=F": {"momentum_1m": 0.043, "hv20": 15.2, ...},
            ...
          }
        }
    接入说明：
        - 对每个 factor_id 调用对应的计算函数
        - 将 hv20 已实现的部分作为范例，逐步替换 stub
    """
    body       = request.get_json(silent=True) or {}
    factor_ids = body.get("factor_ids", ["hv20"])
    symbols    = body.get("symbols", ["GC=F"])
    period     = body.get("period", "1y")

    # 仅 hv20 已实现，其余返回 stub
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))
    factor_matrix = {}
    for sym in symbols:
        factor_matrix[sym] = {}
        for fid in factor_ids:
            if fid == "hv20":
                try:
                    from data_fetcher import generate_synthetic
                    df = generate_synthetic(sym, period)
                    log_r = np.log(df['Close'].values[1:] / df['Close'].values[:-1])
                    hv = float(np.std(log_r[-20:], ddof=1) * np.sqrt(252) * 100)
                    factor_matrix[sym][fid] = round(hv, 4)
                except Exception:
                    factor_matrix[sym][fid] = None
            else:
                factor_matrix[sym][fid] = None   # stub

    stubs = [fid for fid in factor_ids if fid != "hv20"]
    return jsonify({
        "status": "ok",
        "factor_matrix": factor_matrix,
        "implemented": ["hv20"],
        "stubs": stubs,
        "note": "stubs 字段中的因子尚未实现，返回 null"
    })


@quant_bp.route('/factors/ic', methods=['POST'])
def factor_ic():
    """
    因子 IC（信息系数）分析 — Rank IC 与 ICIR。
    Body (JSON):
        {
          "factor_id": "momentum_1m",
          "symbols":   [...],
          "period":    "2y",
          "forward_days": 5    // 预测未来 N 日收益
        }
    返回：
        {
          "status": "ok" | "stub",
          "ic_series": [{"date":..., "ic":...}, ...],
          "mean_ic": ..., "icir": ...
        }
    """
    return jsonify(_stub(
        module="factor_ic",
        detail="实现 Rank IC 计算：rank(factor) 与 rank(forward_return) 的 Spearman 相关"
    ))


# ===========================================================
# ③ 模型层  /api/quant/models/*
# ===========================================================

@quant_bp.route('/models/registry', methods=['GET'])
def model_registry():
    """
    返回已注册的预测/分类模型列表。
    接入说明：
        - status: "implemented" | "stub"
        - 在 models 列表中添加你实现的模型
    """
    models = [
        {
            "id": "linear_reg",
            "name": "线性回归（趋势基线）",
            "type": "regression",
            "inputs": ["price_series"],
            "outputs": ["predicted_price"],
            "status": "implemented",        # 已在 app.py 中实现
            "note": "OLS 拟合，用于价格趋势外推"
        },
        {
            "id": "ma_crossover",
            "name": "双均线策略（MA5/MA20）",
            "type": "rule_based",
            "inputs": ["close"],
            "outputs": ["signal: +1/0/-1"],
            "status": "implemented",
            "note": "金叉买入，死叉卖出"
        },
        {
            "id": "macd_strategy",
            "name": "MACD策略（12,26,9）",
            "type": "rule_based",
            "inputs": ["close"],
            "outputs": ["signal: +1/0/-1"],
            "status": "implemented",
            "note": "已在 research/strategy_tqsdk.py 实现"
        },
        {
            "id": "xgboost_cls",
            "name": "XGBoost 分类器",
            "type": "ml_classification",
            "inputs": ["factor_vector"],
            "outputs": ["signal: +1/-1", "proba"],
            "status": "stub",
            "note": "特征：因子向量；标签：未来 5 日涨跌"
        },
        {
            "id": "lgbm_reg",
            "name": "LightGBM 回归",
            "type": "ml_regression",
            "inputs": ["factor_vector"],
            "outputs": ["predicted_return"],
            "status": "stub",
            "note": "预测未来 N 日收益率"
        },
        {
            "id": "lstm_seq",
            "name": "LSTM 序列模型",
            "type": "deep_learning",
            "inputs": ["price_sequence", "factor_sequence"],
            "outputs": ["predicted_price", "predicted_return"],
            "status": "stub",
            "note": "PyTorch / TensorFlow；窗口长度可配置"
        },
        {
            "id": "transformer_ts",
            "name": "Transformer 时序模型",
            "type": "deep_learning",
            "inputs": ["multi_feature_sequence"],
            "outputs": ["predicted_return"],
            "status": "stub",
            "note": "预留接口，接入你的时序 Transformer"
        },
        {
            "id": "cointegration_pairs",
            "name": "协整套利模型",
            "type": "statistical_arb",
            "inputs": ["pair_prices"],
            "outputs": ["zscore", "signal", "hedge_ratio"],
            "status": "implemented",
            "note": "已在 research/cointegration_arbitrage.py 实现"
        },
        {
            "id": "custom_model",
            "name": "自定义模型（预留槽位）",
            "type": "custom",
            "inputs": ["any"],
            "outputs": ["any"],
            "status": "stub",
            "note": "实现后在此注册"
        }
    ]
    return jsonify({"status": "ok", "models": models, "total": len(models)})


@quant_bp.route('/models/train', methods=['POST'])
def train_model():
    """
    触发模型训练。
    Body (JSON):
        {
          "model_id":    "xgboost_cls",
          "factor_ids":  ["momentum_1m", "hv20", "rsi_14"],
          "symbols":     ["GC=F", "CL=F"],
          "train_start": "2020-01-01",
          "train_end":   "2023-12-31",
          "params":      {}           // 模型超参，可选
        }
    返回：
        {
          "status": "ok" | "stub",
          "job_id": "...",            // 异步任务 ID
          "metrics": {
            "train_accuracy": ..., "val_accuracy": ...,
            "ic_mean": ..., "icir": ...
          }
        }
    接入说明：
        - 对每个 model_id，实现对应的训练逻辑
        - 建议异步执行（celery / threading），返回 job_id 轮询状态
    """
    body = request.get_json(silent=True) or {}
    model_id = body.get("model_id", "")

    if model_id in ("ma_crossover", "macd_strategy", "linear_reg", "cointegration_pairs"):
        return jsonify({
            "status": "ok",
            "message": f"{model_id} 为规则/统计模型，无需训练，直接调用 /api/quant/models/predict",
            "model_id": model_id
        })

    return jsonify(_stub(
        module=f"model_train/{model_id}",
        detail="实现 ML/DL 模型训练逻辑，建议异步执行",
        model_id=model_id,
        params=body.get("params", {})
    ))


@quant_bp.route('/models/predict', methods=['POST'])
def model_predict():
    """
    模型推理 / 信号生成。
    Body (JSON):
        {
          "model_id":  "ma_crossover",
          "symbols":   ["GC=F"],
          "period":    "1y",
          "source":    "synthetic"
        }
    返回：
        {
          "status": "ok",
          "signals": {
            "GC=F": {
              "signal":   1,          // +1 多 / 0 中性 / -1 空
              "confidence": 0.72,     // [0,1]，规则型置为 1.0
              "reason":   "MA5上穿MA20",
              "latest_price": 1835.2,
              "generated_at": "2026-04-02T12:00:00"
            }
          }
        }
    接入说明：
        - ma_crossover / macd_strategy 已有完整实现可迁移
        - ML/DL 模型：加载训练好的权重，推理最新因子向量
    """
    body     = request.get_json(silent=True) or {}
    model_id = body.get("model_id", "ma_crossover")
    symbols  = body.get("symbols", ["GC=F"])
    period   = body.get("period", "1y")

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))

    signals = {}
    for sym in symbols:
        try:
            from data_fetcher import generate_synthetic
            df = generate_synthetic(sym, period)

            if model_id == "ma_crossover":
                df['MA5']  = df['Close'].rolling(5).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                last, prev = df.iloc[-1], df.iloc[-2]
                if prev['MA5'] <= prev['MA20'] and last['MA5'] > last['MA20']:
                    sig, reason = 1, "MA5上穿MA20（金叉）"
                elif prev['MA5'] >= prev['MA20'] and last['MA5'] < last['MA20']:
                    sig, reason = -1, "MA5下穿MA20（死叉）"
                else:
                    sig = 1 if last['MA5'] > last['MA20'] else -1
                    reason = "趋势持续"
                signals[sym] = {
                    "signal": sig, "confidence": 1.0,
                    "reason": reason,
                    "latest_price": round(float(last['Close']), 4),
                    "generated_at": datetime.now().isoformat()
                }
            elif model_id == "macd_strategy":
                ema12 = df['Close'].ewm(span=12, adjust=False).mean()
                ema26 = df['Close'].ewm(span=26, adjust=False).mean()
                macd  = ema12 - ema26
                signal_line = macd.ewm(span=9, adjust=False).mean()
                hist = macd - signal_line
                sig = 1 if hist.iloc[-1] > 0 else -1
                signals[sym] = {
                    "signal": sig, "confidence": 1.0,
                    "reason": f"MACD柱 {'正' if sig == 1 else '负'}",
                    "macd": round(float(macd.iloc[-1]), 6),
                    "signal_line": round(float(signal_line.iloc[-1]), 6),
                    "hist": round(float(hist.iloc[-1]), 6),
                    "latest_price": round(float(df['Close'].iloc[-1]), 4),
                    "generated_at": datetime.now().isoformat()
                }
            else:
                signals[sym] = _stub(
                    module=f"predict/{model_id}",
                    detail=f"在 quant_api.py model_predict() 中实现 {model_id} 推理逻辑"
                )
        except Exception as e:
            signals[sym] = {"status": "error", "message": str(e)}

    return jsonify({"status": "ok", "model_id": model_id, "signals": signals})


@quant_bp.route('/models/backtest', methods=['POST'])
def model_backtest():
    """
    策略回测（统一入口）。
    Body (JSON):
        {
          "model_id":    "ma_crossover",
          "symbols":     ["GC=F", "CL=F"],
          "period":      "2y",
          "source":      "synthetic",
          "commission":  0.0003,         // 手续费率
          "slippage":    0.0001,         // 滑点
          "init_capital": 1000000
        }
    返回：
        {
          "status": "ok",
          "results": {
            "GC=F": {
              "total_return": 11.2,
              "sharpe": 0.85,
              "max_drawdown": -8.3,
              "win_rate": 62.5,
              "total_trades": 24,
              "commission_ratio": 0.4,
              "equity_curve": [{"date":..., "equity":...}, ...],
              "trades": [...]
            }
          }
        }
    接入说明：
        - 已有 app.py backtest_strategy() 可迁移；
        - research/strategy_tqsdk.py 已有带手续费的完整实现
    """
    body       = request.get_json(silent=True) or {}
    model_id   = body.get("model_id", "ma_crossover")
    symbols    = body.get("symbols", ["GC=F"])
    period     = body.get("period", "2y")
    commission = body.get("commission", 0.0003)
    init_cap   = body.get("init_capital", 1_000_000)

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))

    results = {}
    for sym in symbols:
        try:
            from data_fetcher import generate_synthetic
            df = generate_synthetic(sym, period).copy()

            if model_id in ("ma_crossover", "macd_strategy"):
                # ── 复用 research/strategy_tqsdk.py 核心回测逻辑 ──
                df['MA5']  = df['Close'].rolling(5).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df = df.dropna()

                position, entry_price, capital = 0, 0.0, float(init_cap)
                shares_held = 0
                trades, equity_curve = [], []
                peak = capital

                for i in range(1, len(df)):
                    price = float(df['Close'].iloc[i])
                    date  = df.index[i].strftime('%Y-%m-%d')
                    ma5_prev  = float(df['MA5'].iloc[i-1])
                    ma20_prev = float(df['MA20'].iloc[i-1])
                    ma5_now   = float(df['MA5'].iloc[i])
                    ma20_now  = float(df['MA20'].iloc[i])

                    if position == 0 and ma5_prev <= ma20_prev and ma5_now > ma20_now:
                        shares_held = int((capital * 0.95) / price)
                        cost = shares_held * price * (1 + commission)
                        capital -= cost
                        position = 1; entry_price = price
                        trades.append({"date": date, "type": "buy", "price": round(price, 4), "shares": shares_held})

                    elif position == 1 and ma5_prev >= ma20_prev and ma5_now < ma20_now:
                        proceeds = shares_held * price * (1 - commission)
                        pnl = proceeds - shares_held * entry_price
                        capital += proceeds
                        position = 0
                        trades.append({"date": date, "type": "sell", "price": round(price, 4),
                                       "shares": shares_held, "pnl": round(float(pnl), 4)})

                    equity = capital + (shares_held * price if position == 1 else 0)
                    if equity > peak: peak = equity
                    equity_curve.append({"date": date, "equity": round(float(equity), 2)})

                sell_trades = [t for t in trades if t["type"] == "sell"]
                wins = [t for t in sell_trades if t.get("pnl", 0) > 0]
                total_pnl = sum(t.get("pnl", 0) for t in sell_trades)
                total_commission = sum(
                    t["price"] * t["shares"] * commission
                    for t in trades
                )
                final_equity = float(equity_curve[-1]["equity"]) if equity_curve else init_cap

                returns_arr = np.array([
                    (equity_curve[i]["equity"] - equity_curve[i-1]["equity"]) / equity_curve[i-1]["equity"]
                    for i in range(1, len(equity_curve))
                    if equity_curve[i-1]["equity"] > 0
                ])
                sharpe = float(np.mean(returns_arr) / np.std(returns_arr) * np.sqrt(252)) if len(returns_arr) > 1 and np.std(returns_arr) > 0 else 0.0
                max_dd_val = float(min(
                    (equity_curve[i]["equity"] - peak) / peak
                    for i, peak in [(j, max(e["equity"] for e in equity_curve[:j+1])) for j in range(len(equity_curve))]
                )) if equity_curve else 0.0

                results[sym] = {
                    "total_return": round((final_equity - init_cap) / init_cap * 100, 2),
                    "sharpe": round(sharpe, 3),
                    "max_drawdown": round(max_dd_val * 100, 2),
                    "win_rate": round(len(wins) / len(sell_trades) * 100, 2) if sell_trades else 0,
                    "total_trades": len(sell_trades),
                    "total_pnl": round(total_pnl, 2),
                    "commission_total": round(total_commission, 2),
                    "commission_ratio": round(total_commission / abs(total_pnl) * 100, 2) if abs(total_pnl) > 0 else 0,
                    "equity_curve": equity_curve[::5],   # 每5根采样，减小响应体
                    "trades": trades[-20:]               # 最近20笔
                }
            else:
                results[sym] = _stub(module=f"backtest/{model_id}", detail="ML/DL 回测逻辑待实现")

        except Exception as e:
            results[sym] = {"status": "error", "message": str(e)}

    return jsonify({"status": "ok", "model_id": model_id, "commission": commission, "results": results})


# ===========================================================
# ④ 组合优化层  /api/quant/portfolio/*
# ===========================================================

@quant_bp.route('/portfolio/optimize', methods=['POST'])
def portfolio_optimize():
    """
    组合权重优化（Markowitz / 风险平价 / 最大化 Sharpe）。
    Body (JSON):
        {
          "symbols":    ["GC=F", "CL=F", "SI=F"],
          "method":     "max_sharpe" | "min_variance" | "risk_parity" | "equal_weight",
          "period":     "2y",
          "constraints": {
            "min_weight": 0.05,
            "max_weight": 0.40,
            "long_only":  true
          }
        }
    返回：
        {
          "status": "ok",
          "weights":   {"GC=F": 0.45, "CL=F": 0.30, "SI=F": 0.25},
          "metrics":   {
            "expected_return": 8.2,
            "expected_vol":    12.5,
            "sharpe":          0.66,
            "max_drawdown":   -9.1
          },
          "efficient_frontier": [{"vol":..., "ret":...}, ...]   // 可选
        }
    接入说明：
        - 已有 scipy.optimize / cvxpy 可直接实现 max_sharpe / min_variance
        - risk_parity 需实现协方差矩阵的风险分解
    """
    body    = request.get_json(silent=True) or {}
    symbols = body.get("symbols", ["GC=F", "CL=F", "SI=F"])
    method  = body.get("method", "equal_weight")
    period  = body.get("period", "2y")

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))

    # equal_weight 已实现，其余占位
    if method == "equal_weight":
        n = len(symbols)
        w = round(1.0 / n, 4)
        weights = {s: w for s in symbols}
        try:
            from data_fetcher import generate_synthetic
            rets = {}
            for s in symbols:
                df = generate_synthetic(s, period)
                lr = np.log(df['Close'].values[1:] / df['Close'].values[:-1])
                rets[s] = lr
            min_len = min(len(v) for v in rets.values())
            ret_mat = np.array([v[-min_len:] for v in rets.values()])
            port_ret = np.dot([w] * n, ret_mat)
            ann_ret  = float(np.mean(port_ret) * 252 * 100)
            ann_vol  = float(np.std(port_ret, ddof=1) * np.sqrt(252) * 100)
            sharpe   = ann_ret / ann_vol if ann_vol > 0 else 0
        except Exception:
            ann_ret, ann_vol, sharpe = 0, 0, 0

        return jsonify({
            "status": "ok", "method": method,
            "weights": weights,
            "metrics": {
                "expected_return": round(ann_ret, 2),
                "expected_vol":    round(ann_vol, 2),
                "sharpe":          round(sharpe, 3)
            }
        })

    return jsonify(_stub(
        module=f"portfolio_optimize/{method}",
        detail=f"在 quant_api.py portfolio_optimize() 中实现 {method} 优化逻辑（scipy / cvxpy）",
        method=method, symbols=symbols
    ))


@quant_bp.route('/portfolio/rebalance', methods=['POST'])
def portfolio_rebalance():
    """
    组合再平衡建议。
    Body (JSON):
        {
          "current_weights": {"GC=F": 0.5, "CL=F": 0.3, "SI=F": 0.2},
          "target_weights":  {"GC=F": 0.4, "CL=F": 0.35, "SI=F": 0.25},
          "total_value":     1000000,
          "commission":      0.0003
        }
    返回：
        {
          "orders": [{"symbol":..., "action":"buy"/"sell", "amount":..., "value":...}],
          "total_cost": ...
        }
    """
    return jsonify(_stub(
        module="portfolio_rebalance",
        detail="计算当前权重与目标权重之差，生成调仓订单清单"
    ))


@quant_bp.route('/portfolio/risk', methods=['POST'])
def portfolio_risk():
    """
    组合风险归因（VaR / CVaR / 因子暴露）。
    Body: { "weights": {...}, "period": "1y", "confidence": 0.95 }
    返回: { "var_95": ..., "cvar_95": ..., "factor_exposure": {...} }
    """
    return jsonify(_stub(
        module="portfolio_risk",
        detail="实现历史/参数法 VaR，以及因子暴露分解"
    ))


# ===========================================================
# ⑤ 信号输出层  /api/quant/signals/*
# ===========================================================

@quant_bp.route('/signals/latest', methods=['GET'])
def latest_signals():
    """
    返回所有品种最新信号汇总（Dashboard 首页展示用）。
    Query: ?model=ma_crossover&symbols=GC=F,CL=F,SI=F
    返回：
        {
          "status": "ok",
          "generated_at": "...",
          "signals": [
            {
              "symbol": "GC=F", "name": "黄金",
              "signal": 1, "signal_text": "多头",
              "confidence": 0.85,
              "price": 1835.2, "change_pct": 0.23,
              "factors": {"momentum_1m": 0.043, "hv20": 15.2},
              "model": "ma_crossover"
            }
          ]
        }
    """
    model_id = request.args.get("model", "ma_crossover")
    symbols_str = request.args.get("symbols", "GC=F,CL=F,SI=F,HG=F,NG=F")
    symbols = [s.strip() for s in symbols_str.split(",")]

    TICKER_NAMES = {
        "GC=F": "黄金", "SI=F": "白银", "CL=F": "WTI原油",
        "BZ=F": "布伦特原油", "NG=F": "天然气", "HG=F": "铜",
        "ZW=F": "小麦", "ZC=F": "玉米", "ZS=F": "大豆",
        "GLD": "黄金ETF", "SLV": "白银ETF", "USO": "原油ETF"
    }

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))

    output = []
    for sym in symbols:
        try:
            from data_fetcher import generate_synthetic
            df = generate_synthetic(sym, "1y")
            df['MA5']  = df['Close'].rolling(5).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            last, prev = df.iloc[-1], df.iloc[-2]

            if prev['MA5'] <= prev['MA20'] and last['MA5'] > last['MA20']:
                sig, reason = 1, "金叉（MA5上穿MA20）"
            elif prev['MA5'] >= prev['MA20'] and last['MA5'] < last['MA20']:
                sig, reason = -1, "死叉（MA5下穿MA20）"
            else:
                sig = 1 if last['MA5'] > last['MA20'] else -1
                reason = "趋势持续"

            sig_text = {1: "多头", -1: "空头", 0: "中性"}[sig]
            chg = float((last['Close'] - prev['Close']) / prev['Close'] * 100)
            log_r = np.log(df['Close'].values[1:] / df['Close'].values[:-1])
            hv20  = round(float(np.std(log_r[-20:], ddof=1) * np.sqrt(252) * 100), 2)

            output.append({
                "symbol": sym,
                "name": TICKER_NAMES.get(sym, sym),
                "signal": sig,
                "signal_text": sig_text,
                "confidence": 1.0,          # stub: 实际模型应输出概率
                "reason": reason,
                "price": round(float(last['Close']), 4),
                "change_pct": round(chg, 4),
                "factors": {"hv20": hv20},  # stub: 接入完整因子向量
                "model": model_id
            })
        except Exception as e:
            output.append({"symbol": sym, "status": "error", "message": str(e)})

    return jsonify({
        "status": "ok",
        "model": model_id,
        "generated_at": datetime.now().isoformat(),
        "signals": output
    })


@quant_bp.route('/signals/history', methods=['GET'])
def signal_history():
    """
    历史信号序列（用于信号图叠加在价格图上）。
    Query: ?symbol=GC=F&model=ma_crossover&period=1y
    返回：
        {
          "status": "ok",
          "signal_series": [
            {"date":..., "price":..., "signal":..., "reason":...}
          ]
        }
    接入说明：
        - 对每个时间点运行模型推理，记录信号及触发原因
    """
    symbol   = request.args.get("symbol", "GC=F")
    model_id = request.args.get("model", "ma_crossover")
    period   = request.args.get("period", "1y")

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'research'))
    try:
        from data_fetcher import generate_synthetic
        df = generate_synthetic(symbol, period).copy()
        df['MA5']  = df['Close'].rolling(5).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df = df.dropna()

        series = []
        prev_sig = 0
        for i in range(1, len(df)):
            ma5p, ma20p = float(df['MA5'].iloc[i-1]), float(df['MA20'].iloc[i-1])
            ma5n, ma20n = float(df['MA5'].iloc[i]),   float(df['MA20'].iloc[i])
            price = float(df['Close'].iloc[i])
            date  = df.index[i].strftime('%Y-%m-%d')

            if ma5p <= ma20p and ma5n > ma20n:
                sig, reason = 1, "金叉"
            elif ma5p >= ma20p and ma5n < ma20n:
                sig, reason = -1, "死叉"
            else:
                sig = prev_sig
                reason = ""

            if sig != 0 and (sig != prev_sig or reason):
                series.append({"date": date, "price": round(price, 4),
                                "signal": sig, "reason": reason})
            prev_sig = sig

        return jsonify({"status": "ok", "symbol": symbol, "model": model_id,
                        "signal_series": series})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@quant_bp.route('/signals/export', methods=['POST'])
def export_signals():
    """
    导出信号为 CSV/JSON 文件。
    Body: { "model_id":..., "symbols":[...], "period":..., "format": "csv" | "json" }
    接入说明：保存到 research/outputs/signals_<timestamp>.csv
    """
    return jsonify(_stub(
        module="signal_export",
        detail="生成信号文件并返回下载链接"
    ))


# ===========================================================
# ⑥ 流程状态  /api/quant/pipeline
# ===========================================================

@quant_bp.route('/pipeline/status', methods=['GET'])
def pipeline_status():
    """
    返回量化全流程各环节的实现状态（供前端 Stepper 展示）。
    """
    steps = [
        {
            "id": "data",
            "name": "数据接入",
            "icon": "🗄️",
            "status": "partial",    # done | partial | stub
            "implemented": ["synthetic", "generate_synthetic"],
            "stubs": ["yfinance_live", "akshare_live", "tqsdk_live", "custom_upload"],
            "api_prefix": "/api/quant/data"
        },
        {
            "id": "factors",
            "name": "因子工程",
            "icon": "🧮",
            "status": "partial",
            "implemented": ["hv20"],
            "stubs": ["momentum", "rsi", "macd", "carry", "cot", "custom"],
            "api_prefix": "/api/quant/factors"
        },
        {
            "id": "models",
            "name": "模型层",
            "icon": "🤖",
            "status": "partial",
            "implemented": ["linear_reg", "ma_crossover", "macd_strategy", "cointegration_pairs"],
            "stubs": ["xgboost", "lgbm", "lstm", "transformer"],
            "api_prefix": "/api/quant/models"
        },
        {
            "id": "portfolio",
            "name": "组合优化",
            "icon": "⚖️",
            "status": "partial",
            "implemented": ["equal_weight"],
            "stubs": ["max_sharpe", "min_variance", "risk_parity", "rebalance"],
            "api_prefix": "/api/quant/portfolio"
        },
        {
            "id": "signals",
            "name": "信号输出",
            "icon": "📡",
            "status": "partial",
            "implemented": ["ma_crossover_signal", "signal_history"],
            "stubs": ["ml_signals", "export", "alert"],
            "api_prefix": "/api/quant/signals"
        }
    ]
    return jsonify({"status": "ok", "steps": steps})
