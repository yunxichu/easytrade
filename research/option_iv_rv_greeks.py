"""
option_iv_rv_greeks.py
======================
Minute-level futures option analysis for the course assignment.

The script is designed for commodity futures options, so it uses the
Black-76 model: the option's underlying is the futures price F rather than a
spot asset price S. It computes:

1. Realized volatility (RV) from 1-minute futures log returns and its
   historical percentile.
2. Implied volatility (IV) from option mid prices and its historical
   percentile.
3. Black-76 Greeks: delta, gamma, vega, theta, rho.
4. A Greek-based explanation of option price changes.

Run a reproducible demo:

    python research/option_iv_rv_greeks.py --demo

Run on a single merged CSV:

    python research/option_iv_rv_greeks.py --input data/minute_options.csv

Expected merged CSV columns can use either English or common Chinese names:
datetime/time, futures_price/underlying_price/期货价格/标的价格,
option_price/mid/期权价格, strike/行权价, expiry/到期日,
option_type/call_put/期权类型, option_symbol/期权代码.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm


TRADING_DAYS_PER_YEAR = 252
MINUTES_PER_TRADING_DAY = 390
DEFAULT_MINUTES_PER_YEAR = TRADING_DAYS_PER_YEAR * MINUTES_PER_TRADING_DAY
YEAR_SECONDS = 365.0 * 24.0 * 60.0 * 60.0


COLUMN_ALIASES = {
    "datetime": [
        "datetime",
        "timestamp",
        "time",
        "date_time",
        "trade_time",
        "交易时间",
        "日期时间",
        "时间",
        "日期",
    ],
    "futures_price": [
        "futures_price",
        "future_price",
        "underlying_price",
        "underlying",
        "f",
        "标的价格",
        "期货价格",
        "标的收盘价",
        "期货收盘价",
        "close_futures",
        "future_close",
        "close_f",
    ],
    "option_price": [
        "option_price",
        "option_mid",
        "mid",
        "price",
        "last",
        "last_price",
        "期权价格",
        "期权中间价",
        "期权收盘价",
        "权利金",
        "close_option",
        "option_close",
        "close_o",
    ],
    "bid": ["bid", "bid_price", "买价", "买一价"],
    "ask": ["ask", "ask_price", "卖价", "卖一价"],
    "strike": ["strike", "k", "exercise_price", "行权价", "执行价"],
    "expiry": ["expiry", "expiration", "maturity", "expire_date", "到期日", "到期日期"],
    "option_type": ["option_type", "type", "call_put", "cp", "认购认沽", "期权类型"],
    "option_symbol": ["option_symbol", "symbol", "contract", "期权代码", "期权合约", "合约代码"],
    "rate": ["rate", "risk_free_rate", "r", "无风险利率"],
}


@dataclass
class AnalysisConfig:
    rate: float = 0.02
    rv_window: int = 240
    percentile_window: int = 1200
    minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR
    output_dir: Path = Path("research/outputs/options")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute IV/RV percentiles, Greeks, and option price attribution."
    )
    parser.add_argument("--input", type=Path, help="Merged minute option CSV.")
    parser.add_argument("--futures", type=Path, help="Minute futures CSV.")
    parser.add_argument("--options", type=Path, help="Minute options CSV.")
    parser.add_argument("--demo", action="store_true", help="Generate and analyze demo data.")
    parser.add_argument("--output-dir", type=Path, default=Path("research/outputs/options"))
    parser.add_argument("--rate", type=float, default=0.02, help="Risk-free rate, annualized.")
    parser.add_argument("--rv-window", type=int, default=240, help="Rolling minute window for RV.")
    parser.add_argument(
        "--percentile-window",
        type=int,
        default=1200,
        help="Rolling historical window for IV/RV percentile.",
    )
    parser.add_argument(
        "--minutes-per-year",
        type=int,
        default=DEFAULT_MINUTES_PER_YEAR,
        help="Annualization factor for minute RV.",
    )
    parser.add_argument("--datetime-col", help="Override datetime column.")
    parser.add_argument("--futures-price-col", help="Override futures price column.")
    parser.add_argument("--option-price-col", help="Override option price column.")
    parser.add_argument("--strike-col", help="Override strike column.")
    parser.add_argument("--expiry-col", help="Override expiry column.")
    parser.add_argument("--option-type-col", help="Override option type column.")
    parser.add_argument("--option-symbol-col", help="Override option symbol column.")
    return parser.parse_args()


def normalized_columns(df: pd.DataFrame) -> dict[str, str]:
    return {str(col).strip().lower(): str(col) for col in df.columns}


def find_column(
    df: pd.DataFrame,
    logical_name: str,
    explicit: str | None = None,
    required: bool = True,
) -> str | None:
    if explicit:
        if explicit not in df.columns:
            raise ValueError(f"Column override '{explicit}' was not found.")
        return explicit

    lookup = normalized_columns(df)
    for alias in COLUMN_ALIASES[logical_name]:
        hit = lookup.get(alias.lower())
        if hit is not None:
            return hit
    if required:
        aliases = ", ".join(COLUMN_ALIASES[logical_name])
        raise ValueError(f"Missing required column for {logical_name}. Tried: {aliases}")
    return None


def normalize_option_type(value: object) -> str:
    text = str(value).strip().lower()
    call_values = {"c", "call", "认购", "购", "看涨", "1"}
    put_values = {"p", "put", "认沽", "沽", "看跌", "-1", "0"}
    if text in call_values or "call" in text or "认购" in text or "看涨" in text:
        return "call"
    if text in put_values or "put" in text or "认沽" in text or "看跌" in text:
        return "put"
    raise ValueError(f"Unknown option type: {value!r}")


def black76_price(
    futures_price: float,
    strike: float,
    tte_years: float,
    rate: float,
    sigma: float,
    option_type: str,
) -> float:
    if futures_price <= 0 or strike <= 0 or tte_years <= 0 or sigma <= 0:
        return np.nan
    df = math.exp(-rate * tte_years)
    vol_sqrt_t = sigma * math.sqrt(tte_years)
    if vol_sqrt_t <= 0:
        return np.nan
    d1 = (math.log(futures_price / strike) + 0.5 * sigma * sigma * tte_years) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    if option_type == "call":
        return df * (futures_price * norm.cdf(d1) - strike * norm.cdf(d2))
    return df * (strike * norm.cdf(-d2) - futures_price * norm.cdf(-d1))


def implied_vol_black76(
    market_price: float,
    futures_price: float,
    strike: float,
    tte_years: float,
    rate: float,
    option_type: str,
) -> float:
    if (
        not np.isfinite(market_price)
        or not np.isfinite(futures_price)
        or not np.isfinite(strike)
        or market_price <= 0
        or futures_price <= 0
        or strike <= 0
        or tte_years <= 0
    ):
        return np.nan

    discount = math.exp(-rate * tte_years)
    intrinsic = max(futures_price - strike, 0.0) if option_type == "call" else max(strike - futures_price, 0.0)
    lower_bound = discount * intrinsic
    upper_bound = discount * futures_price if option_type == "call" else discount * strike

    if market_price < lower_bound - 1e-8 or market_price > upper_bound + 1e-8:
        return np.nan
    if abs(market_price - lower_bound) <= 1e-8:
        return 1e-6

    def objective(sigma: float) -> float:
        return black76_price(futures_price, strike, tte_years, rate, sigma, option_type) - market_price

    try:
        return brentq(objective, 1e-6, 5.0, maxiter=100)
    except ValueError:
        return np.nan


def black76_greeks(
    price: float,
    futures_price: float,
    strike: float,
    tte_years: float,
    rate: float,
    sigma: float,
    option_type: str,
) -> dict[str, float]:
    if (
        not np.isfinite(price)
        or not np.isfinite(futures_price)
        or not np.isfinite(strike)
        or not np.isfinite(sigma)
        or futures_price <= 0
        or strike <= 0
        or sigma <= 0
        or tte_years <= 0
    ):
        return {"delta": np.nan, "gamma": np.nan, "vega": np.nan, "theta": np.nan, "rho": np.nan}

    discount = math.exp(-rate * tte_years)
    sqrt_t = math.sqrt(tte_years)
    d1 = (math.log(futures_price / strike) + 0.5 * sigma * sigma * tte_years) / (sigma * sqrt_t)
    pdf_d1 = norm.pdf(d1)
    if option_type == "call":
        delta = discount * norm.cdf(d1)
    else:
        delta = -discount * norm.cdf(-d1)
    gamma = discount * pdf_d1 / (futures_price * sigma * sqrt_t)
    vega = discount * futures_price * pdf_d1 * sqrt_t
    theta = -(discount * futures_price * pdf_d1 * sigma) / (2.0 * sqrt_t) + rate * price
    rho = -tte_years * price
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def rolling_last_percentile(series: pd.Series, window: int, min_periods: int = 10) -> pd.Series:
    def percentile(values: np.ndarray) -> float:
        values = values[np.isfinite(values)]
        if len(values) == 0:
            return np.nan
        return float(np.mean(values <= values[-1]))

    return series.rolling(window=window, min_periods=min(min_periods, window)).apply(percentile, raw=True)


def generate_demo_data() -> pd.DataFrame:
    rng = np.random.default_rng(20260429)
    periods = 7 * MINUTES_PER_TRADING_DAY
    start = pd.Timestamp("2026-04-20 09:30:00")
    minutes = []
    current = start
    for _ in range(7):
        day_start = current.normalize() + pd.Timedelta(hours=9, minutes=30)
        minutes.extend(pd.date_range(day_start, periods=MINUTES_PER_TRADING_DAY, freq="min"))
        current = day_start + pd.Timedelta(days=1)
    dt_index = pd.DatetimeIndex(minutes[:periods])

    minute_vol = 0.28 / math.sqrt(DEFAULT_MINUTES_PER_YEAR)
    shocks = rng.normal(loc=0.0, scale=minute_vol, size=len(dt_index))
    futures = 78.0 * np.exp(np.cumsum(shocks))
    expiry = dt_index[0] + pd.Timedelta(days=45)
    strike = 78.0
    rate = 0.02
    base_iv = 0.32 + 0.03 * np.sin(np.linspace(0, 5 * math.pi, len(dt_index)))
    base_iv += rng.normal(0.0, 0.006, size=len(dt_index))
    base_iv = np.clip(base_iv, 0.20, 0.55)

    rows = []
    for i, ts in enumerate(dt_index):
        tte = max((expiry - ts).total_seconds() / YEAR_SECONDS, 1e-8)
        for option_type in ("call", "put"):
            symbol = f"CLM26-{option_type[0].upper()}-{int(strike)}"
            fair = black76_price(futures[i], strike, tte, rate, float(base_iv[i]), option_type)
            noise = rng.normal(0.0, max(fair * 0.004, 0.003))
            mid = max(fair + noise, 0.01)
            spread = max(mid * 0.012, 0.02)
            rows.append(
                {
                    "datetime": ts,
                    "futures_symbol": "CLM26",
                    "option_symbol": symbol,
                    "option_type": option_type,
                    "strike": strike,
                    "expiry": expiry.date().isoformat(),
                    "futures_price": futures[i],
                    "option_price": mid,
                    "bid": max(mid - spread / 2.0, 0.01),
                    "ask": mid + spread / 2.0,
                    "rate": rate,
                }
            )
    return pd.DataFrame(rows)


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def standardize_merged_data(df: pd.DataFrame, args: argparse.Namespace, default_rate: float) -> pd.DataFrame:
    dt_col = find_column(df, "datetime", args.datetime_col)
    fut_col = find_column(df, "futures_price", args.futures_price_col)
    opt_col = find_column(df, "option_price", args.option_price_col, required=False)
    bid_col = find_column(df, "bid", required=False)
    ask_col = find_column(df, "ask", required=False)
    strike_col = find_column(df, "strike", args.strike_col)
    expiry_col = find_column(df, "expiry", args.expiry_col)
    type_col = find_column(df, "option_type", args.option_type_col)
    symbol_col = find_column(df, "option_symbol", args.option_symbol_col, required=False)
    rate_col = find_column(df, "rate", required=False)

    out = pd.DataFrame()
    out["timestamp"] = pd.to_datetime(df[dt_col], errors="coerce")
    out["futures_price"] = pd.to_numeric(df[fut_col], errors="coerce")
    if opt_col is not None:
        out["option_mid"] = pd.to_numeric(df[opt_col], errors="coerce")
    elif bid_col is not None and ask_col is not None:
        out["option_mid"] = (
            pd.to_numeric(df[bid_col], errors="coerce") + pd.to_numeric(df[ask_col], errors="coerce")
        ) / 2.0
    else:
        raise ValueError("Need option price, or both bid and ask columns.")

    if bid_col is not None:
        out["bid"] = pd.to_numeric(df[bid_col], errors="coerce")
    if ask_col is not None:
        out["ask"] = pd.to_numeric(df[ask_col], errors="coerce")

    out["strike"] = pd.to_numeric(df[strike_col], errors="coerce")
    out["expiry"] = pd.to_datetime(df[expiry_col], errors="coerce")
    out["option_type"] = df[type_col].map(normalize_option_type)
    if symbol_col is not None:
        out["option_symbol"] = df[symbol_col].astype(str)
    else:
        out["option_symbol"] = (
            out["option_type"].str.upper().str[0]
            + "-"
            + out["strike"].round(4).astype(str)
            + "-"
            + out["expiry"].dt.strftime("%Y%m%d")
        )
    if rate_col is not None:
        out["rate"] = pd.to_numeric(df[rate_col], errors="coerce").fillna(default_rate)
    else:
        out["rate"] = default_rate

    out = out.dropna(subset=["timestamp", "futures_price", "option_mid", "strike", "expiry"])
    out = out[out["expiry"] > out["timestamp"]]
    return out.sort_values(["option_symbol", "timestamp"]).reset_index(drop=True)


def load_data(args: argparse.Namespace, config: AnalysisConfig) -> tuple[pd.DataFrame, bool]:
    if args.demo:
        return standardize_merged_data(generate_demo_data(), args, config.rate), True

    if args.input:
        return standardize_merged_data(read_csv(args.input), args, config.rate), False

    if args.futures and args.options:
        futures_raw = read_csv(args.futures)
        options_raw = read_csv(args.options)

        fut_dt_col = find_column(futures_raw, "datetime", args.datetime_col)
        fut_price_col = find_column(futures_raw, "futures_price", args.futures_price_col)
        futures = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(futures_raw[fut_dt_col], errors="coerce"),
                "futures_price": pd.to_numeric(futures_raw[fut_price_col], errors="coerce"),
            }
        ).dropna()
        futures = futures.sort_values("timestamp")

        options_args = argparse.Namespace(**vars(args))
        options_args.futures_price_col = None
        options = options_raw.copy()
        option_dt_col = find_column(options, "datetime", args.datetime_col)
        options["timestamp"] = pd.to_datetime(options[option_dt_col], errors="coerce")
        options = options.sort_values("timestamp")

        merged = pd.merge_asof(options, futures, on="timestamp", direction="nearest", tolerance=pd.Timedelta("60s"))
        return standardize_merged_data(merged, options_args, config.rate), False

    raise ValueError("Provide --demo, --input, or both --futures and --options.")


def compute_realized_volatility(df: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    futures = df[["timestamp", "futures_price"]].drop_duplicates("timestamp").sort_values("timestamp")
    futures["log_return"] = np.log(futures["futures_price"]).diff()
    futures["rv"] = (
        futures["log_return"].rolling(config.rv_window, min_periods=min(10, config.rv_window)).std()
        * math.sqrt(config.minutes_per_year)
    )
    futures["rv_percentile"] = rolling_last_percentile(futures["rv"], config.percentile_window)
    return df.merge(futures[["timestamp", "log_return", "rv", "rv_percentile"]], on="timestamp", how="left")


def compute_iv_and_greeks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["tte_years"] = (out["expiry"] - out["timestamp"]).dt.total_seconds() / YEAR_SECONDS

    iv_values = []
    greek_rows = []
    for row in out.itertuples(index=False):
        iv = implied_vol_black76(
            market_price=float(row.option_mid),
            futures_price=float(row.futures_price),
            strike=float(row.strike),
            tte_years=float(row.tte_years),
            rate=float(row.rate),
            option_type=str(row.option_type),
        )
        iv_values.append(iv)
        greek_rows.append(
            black76_greeks(
                price=float(row.option_mid),
                futures_price=float(row.futures_price),
                strike=float(row.strike),
                tte_years=float(row.tte_years),
                rate=float(row.rate),
                sigma=float(iv) if np.isfinite(iv) else np.nan,
                option_type=str(row.option_type),
            )
        )

    out["iv"] = iv_values
    greeks = pd.DataFrame(greek_rows)
    return pd.concat([out.reset_index(drop=True), greeks], axis=1)


def add_percentiles(df: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    out = df.sort_values(["option_symbol", "timestamp"]).copy()
    out["iv_percentile"] = out.groupby("option_symbol", group_keys=False)["iv"].apply(
        lambda s: rolling_last_percentile(s, config.percentile_window)
    )
    out["iv_minus_rv"] = out["iv"] - out["rv"]
    out["iv_rv_ratio"] = out["iv"] / out["rv"]
    out["spread_percentile"] = out.groupby("option_symbol", group_keys=False)["iv_minus_rv"].apply(
        lambda s: rolling_last_percentile(s, config.percentile_window)
    )
    return out


def explain_price_changes(df: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for _, group in df.sort_values("timestamp").groupby("option_symbol", sort=False):
        group = group.sort_values("timestamp").copy()
        prev = group.shift(1)
        attribution = pd.DataFrame(
            {
                "timestamp": group["timestamp"],
                "option_symbol": group["option_symbol"],
                "option_type": group["option_type"],
                "price_change": group["option_mid"] - prev["option_mid"],
                "delta_effect": prev["delta"] * (group["futures_price"] - prev["futures_price"]),
                "gamma_effect": 0.5
                * prev["gamma"]
                * (group["futures_price"] - prev["futures_price"])
                * (group["futures_price"] - prev["futures_price"]),
                "vega_effect": prev["vega"] * (group["iv"] - prev["iv"]),
                "theta_effect": prev["theta"]
                * ((group["timestamp"] - prev["timestamp"]).dt.total_seconds() / YEAR_SECONDS),
                "rho_effect": prev["rho"] * (group["rate"] - prev["rate"]),
            }
        )
        explained_cols = ["delta_effect", "gamma_effect", "vega_effect", "theta_effect", "rho_effect"]
        attribution["explained_change"] = attribution[explained_cols].sum(axis=1)
        attribution["residual"] = attribution["price_change"] - attribution["explained_change"]
        frames.append(attribution)
    return pd.concat(frames, ignore_index=True).dropna(subset=["price_change"])


def recommend_strategy(row: pd.Series) -> str:
    ivp = row.get("iv_percentile", np.nan)
    rvp = row.get("rv_percentile", np.nan)
    spread = row.get("iv_minus_rv", np.nan)
    spreadp = row.get("spread_percentile", np.nan)

    if np.isfinite(ivp) and np.isfinite(spreadp) and ivp >= 0.75 and spread > 0 and spreadp >= 0.65:
        return "IV高且明显高于RV：偏卖波动率，考虑卖跨式/宽跨式或铁鹰，并用期货做Delta对冲。"
    if np.isfinite(ivp) and np.isfinite(rvp) and ivp <= 0.25 and rvp >= 0.50:
        return "IV低但RV不低：偏买波动率，考虑买跨式/宽跨式或买入期权价差。"
    if np.isfinite(ivp) and np.isfinite(rvp) and ivp >= 0.75 and rvp >= 0.75:
        return "IV和RV都高：波动已放大，优先用有限风险价差，避免裸卖Gamma。"
    if np.isfinite(ivp) and ivp <= 0.25:
        return "IV低分位：期权相对便宜，可用买权利仓表达方向或事件波动。"
    if np.isfinite(spread) and spread < 0:
        return "IV低于RV：市场定价波动偏低，卖波动胜率不足，更适合买波动或观望。"
    return "IV/RV处于中性区间：以方向判断和风险预算为主，可做Delta较小的价差策略。"


def build_latest_summary(df: pd.DataFrame) -> pd.DataFrame:
    latest = df.sort_values("timestamp").groupby("option_symbol", as_index=False).tail(1).copy()
    latest["strategy"] = latest.apply(recommend_strategy, axis=1)
    columns = [
        "timestamp",
        "option_symbol",
        "option_type",
        "strike",
        "expiry",
        "futures_price",
        "option_mid",
        "rv",
        "rv_percentile",
        "iv",
        "iv_percentile",
        "iv_minus_rv",
        "iv_rv_ratio",
        "spread_percentile",
        "delta",
        "gamma",
        "vega",
        "theta",
        "rho",
        "strategy",
    ]
    return latest[columns].sort_values("option_symbol")


def build_volatility_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol, group in df.sort_values("timestamp").groupby("option_symbol", sort=False):
        iv = group["iv"].dropna()
        rv = group["rv"].dropna()
        timestamps = group["timestamp"].sort_values()
        gaps = timestamps.diff().dt.total_seconds().div(60).dropna()
        rows.append(
            {
                "option_symbol": symbol,
                "row_count": int(len(group)),
                "start_time": timestamps.iloc[0],
                "end_time": timestamps.iloc[-1],
                "gap_count_gt_1m": int((gaps > 1).sum()),
                "max_gap_minutes": float(gaps.max()) if not gaps.empty else 0.0,
                "iv_min": float(iv.min()) if not iv.empty else np.nan,
                "iv_median": float(iv.median()) if not iv.empty else np.nan,
                "iv_mean": float(iv.mean()) if not iv.empty else np.nan,
                "iv_max": float(iv.max()) if not iv.empty else np.nan,
                "iv_std": float(iv.std()) if len(iv) > 1 else np.nan,
                "rv_min": float(rv.min()) if not rv.empty else np.nan,
                "rv_median": float(rv.median()) if not rv.empty else np.nan,
                "rv_mean": float(rv.mean()) if not rv.empty else np.nan,
                "rv_max": float(rv.max()) if not rv.empty else np.nan,
                "rv_std": float(rv.std()) if len(rv) > 1 else np.nan,
                "rv_latest": float(group["rv"].dropna().iloc[-1]) if not rv.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_summary_json(latest: pd.DataFrame, attribution: pd.DataFrame, used_demo: bool) -> dict[str, object]:
    attr_summary = {}
    for symbol, group in attribution.groupby("option_symbol"):
        totals = group[
            ["price_change", "delta_effect", "gamma_effect", "vega_effect", "theta_effect", "rho_effect", "residual"]
        ].sum()
        attr_summary[symbol] = {k: float(v) for k, v in totals.items()}

    latest_records = latest.copy()
    for col in latest_records.select_dtypes(include=["datetime64[ns]"]).columns:
        latest_records[col] = latest_records[col].astype(str)
    return {
        "used_demo_data": used_demo,
        "latest": latest_records.to_dict(orient="records"),
        "price_attribution_totals": attr_summary,
    }


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    text = df.astype(str).replace("nan", "")
    columns = list(text.columns)
    rows = text.values.tolist()
    widths = []
    for i, col in enumerate(columns):
        widths.append(max(len(str(col)), *(len(row[i]) for row in rows)))

    def fmt_row(values: Iterable[object]) -> str:
        cells = [str(value).ljust(widths[i]) for i, value in enumerate(values)]
        return "| " + " | ".join(cells) + " |"

    header = fmt_row(columns)
    divider = "| " + " | ".join("-" * width for width in widths) + " |"
    body = [fmt_row(row) for row in rows]
    return "\n".join([header, divider, *body])


def break_time_gaps(frame: pd.DataFrame, value_cols: list[str], gap_minutes: int = 5) -> pd.DataFrame:
    out = frame.sort_values("timestamp").copy()
    large_gap = out["timestamp"].diff() > pd.Timedelta(minutes=gap_minutes)
    for col in value_cols:
        out.loc[large_gap, col] = np.nan
    return out


def save_plots(df: pd.DataFrame, attribution: pd.DataFrame, output_dir: Path, config: AnalysisConfig) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    first_symbol = str(df["option_symbol"].iloc[0])
    sample = df[df["option_symbol"] == first_symbol].sort_values("timestamp")
    sample = break_time_gaps(sample, ["iv", "rv"])

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    axes[0].plot(sample["timestamp"], sample["iv"], label="IV", color="#1f77b4")
    axes[0].set_ylabel("IV")
    axes[0].set_title(f"Minute IV and rolling RV: {first_symbol}")
    axes[0].legend(loc="upper left")
    axes[1].plot(sample["timestamp"], sample["rv"], label=f"RV ({config.rv_window}-min rolling)", color="#ff7f0e")
    axes[1].set_ylabel("RV")
    axes[1].set_xlabel("Time")
    axes[1].legend(loc="upper left")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_dir / "iv_vs_rv.png", dpi=160)
    plt.close()

    attr = attribution[attribution["option_symbol"] == first_symbol].sort_values("timestamp").copy()
    if not attr.empty:
        effect_cols = ["delta_effect", "gamma_effect", "vega_effect", "theta_effect", "rho_effect"]
        attr["actual_cum"] = attr["price_change"].cumsum()
        attr["explained_cum"] = attr[effect_cols].sum(axis=1).cumsum()
        attr["residual_cum"] = attr["residual"].cumsum()

        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        axes[0].plot(attr["timestamp"], attr["actual_cum"], label="Actual", color="#1f77b4")
        axes[0].plot(
            attr["timestamp"],
            attr["explained_cum"],
            label="Greeks explained",
            color="#ff7f0e",
            linestyle="--",
        )
        axes[0].set_title(f"Full-day cumulative price attribution: {first_symbol}")
        axes[0].set_ylabel("Cumulative option price change")
        axes[0].legend(loc="upper left")
        axes[0].grid(True, alpha=0.25)
        axes[1].plot(attr["timestamp"], attr["residual_cum"], label="Cumulative residual", color="#2ca02c")
        axes[1].axhline(0, color="#666666", linewidth=0.8, alpha=0.6)
        axes[1].set_ylabel("Residual")
        axes[1].set_xlabel("Time")
        axes[1].grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(output_dir / "price_attribution.png", dpi=160)
        plt.close()


def write_markdown_report(
    latest: pd.DataFrame,
    summary: dict[str, object],
    output_dir: Path,
    used_demo: bool,
    config: AnalysisConfig,
) -> None:
    lines = [
        "# 期货期权1分钟数据 IV/RV、希腊字母与价格归因报告",
        "",
        f"- 数据类型：{'脚本生成的可复现demo数据' if used_demo else '用户输入的分钟数据'}",
        f"- RV窗口：{config.rv_window}分钟",
        f"- 历史分位窗口：{config.percentile_window}分钟",
        f"- 分钟年化因子：{config.minutes_per_year}",
        "",
        "## 最新合约结论",
        "",
    ]
    display_cols = [
        "option_symbol",
        "option_type",
        "futures_price",
        "option_mid",
        "iv",
        "iv_percentile",
        "rv",
        "rv_percentile",
        "delta",
        "gamma",
        "vega",
        "theta",
        "strategy",
    ]
    rounded = latest[display_cols].copy()
    for col in ["futures_price", "option_mid", "iv", "rv", "delta", "gamma", "vega", "theta"]:
        rounded[col] = rounded[col].map(lambda x: "" if pd.isna(x) else f"{x:.6f}")
    for col in ["iv_percentile", "rv_percentile"]:
        rounded[col] = rounded[col].map(lambda x: "" if pd.isna(x) else f"{x:.2%}")
    lines.append(dataframe_to_markdown(rounded))
    lines.extend(
        [
            "",
            "## 方法说明",
            "",
            "- RV：用期货1分钟对数收益率滚动标准差年化。",
            "- IV：用Black-76期货期权定价模型反解隐含波动率。",
            "- 分位：当前值在滚动历史窗口中小于等于自身的比例。",
            "- 价格解释：dV约等于Delta*dF + 0.5*Gamma*dF^2 + Vega*dIV + Theta*dt + Rho*dr，剩余部分记为residual。",
            "",
            "## 价格变动归因汇总",
            "",
        ]
    )
    attr = pd.DataFrame(summary["price_attribution_totals"]).T.reset_index(names="option_symbol")
    if not attr.empty:
        for col in attr.columns:
            if col != "option_symbol":
                attr[col] = attr[col].map(lambda x: f"{x:.6f}")
        lines.append(dataframe_to_markdown(attr))
    (output_dir / "option_analysis_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_analysis(args: argparse.Namespace) -> None:
    config = AnalysisConfig(
        rate=args.rate,
        rv_window=args.rv_window,
        percentile_window=args.percentile_window,
        minutes_per_year=args.minutes_per_year,
        output_dir=args.output_dir,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)

    raw, used_demo = load_data(args, config)
    if used_demo:
        raw.to_csv(config.output_dir / "demo_minute_options.csv", index=False, encoding="utf-8-sig")

    analyzed = compute_realized_volatility(raw, config)
    analyzed = compute_iv_and_greeks(analyzed)
    analyzed = add_percentiles(analyzed, config)
    attribution = explain_price_changes(analyzed)
    latest = build_latest_summary(analyzed)
    volatility_stats = build_volatility_stats(analyzed)
    summary = build_summary_json(latest, attribution, used_demo)

    analyzed.to_csv(config.output_dir / "option_iv_rv_greeks.csv", index=False, encoding="utf-8-sig")
    latest.to_csv(config.output_dir / "option_latest_summary.csv", index=False, encoding="utf-8-sig")
    volatility_stats.to_csv(config.output_dir / "daily_volatility_summary.csv", index=False, encoding="utf-8-sig")
    attribution.to_csv(config.output_dir / "option_price_attribution.csv", index=False, encoding="utf-8-sig")
    (config.output_dir / "option_analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_plots(analyzed, attribution, config.output_dir, config)
    write_markdown_report(latest, summary, config.output_dir, used_demo, config)

    print(f"Rows analyzed: {len(analyzed)}")
    print(f"Output directory: {config.output_dir.resolve()}")
    print(latest[["option_symbol", "iv", "iv_percentile", "rv", "rv_percentile", "strategy"]].to_string(index=False))


def main() -> None:
    args = parse_args()
    run_analysis(args)


if __name__ == "__main__":
    main()
