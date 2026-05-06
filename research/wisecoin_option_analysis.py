"""
wisecoin_option_analysis.py
===========================

Reproducible homework analysis for a wisecoin_option-style option program.

The script has the same two core ideas as a typical option helper program:
1. download underlying and option-chain data;
2. form a market view and map that view to an option strategy.

It also adds two requested modules:
A. portfolio-level Greeks for an option combination strategy;
B. strategy P&L analysis at expiry and under spot/volatility scenarios.

Primary data source is Yahoo Finance through yfinance. If Yahoo is unavailable,
the script creates a deterministic synthetic option chain so the homework
package remains reproducible.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/wisecoin_option"
OUTPUT_DIR = ROOT / "research/outputs/wisecoin_option"
TICKER = "SPY"
RISK_FREE_RATE = 0.04
DIVIDEND_YIELD = 0.0
CONTRACT_MULTIPLIER = 100
RANDOM_SEED = 23300180062


@dataclass
class OptionLeg:
    contract_symbol: str
    option_type: str
    strike: float
    expiry: str
    quantity: int
    mid: float
    implied_volatility: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def clean_option_chain(chain: pd.DataFrame, expiry: str) -> pd.DataFrame:
    out = chain.copy()
    out["expiry"] = expiry
    for col in ["strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["mid"] = np.where(
        (out["bid"] > 0) & (out["ask"] > 0) & (out["ask"] >= out["bid"]),
        (out["bid"] + out["ask"]) / 2.0,
        out["lastPrice"],
    )
    out["relative_spread"] = np.where(out["mid"] > 0, (out["ask"] - out["bid"]) / out["mid"], np.nan)
    out = out.dropna(subset=["contractSymbol", "strike", "mid", "impliedVolatility"])
    out = out[(out["mid"] > 0) & (out["impliedVolatility"] > 0)]
    return out


def synthetic_history_and_chain() -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    rng = np.random.default_rng(RANDOM_SEED)
    end = pd.Timestamp(date.today())
    dates = pd.bdate_range(end=end, periods=252)
    log_returns = rng.normal(0.00035, 0.0105, size=len(dates))
    close = 520.0 * np.exp(np.cumsum(log_returns))
    hist = pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.002, size=len(dates))),
            "High": close * (1 + rng.uniform(0.001, 0.008, size=len(dates))),
            "Low": close * (1 - rng.uniform(0.001, 0.008, size=len(dates))),
            "Close": close,
            "Volume": rng.integers(50_000_000, 110_000_000, size=len(dates)),
        },
        index=dates,
    )
    spot = float(hist["Close"].iloc[-1])
    expiry_date = (end + pd.Timedelta(days=45)).date().isoformat()
    t = 45 / 365.0
    strikes = np.arange(round(spot * 0.85 / 5) * 5, round(spot * 1.16 / 5) * 5 + 5, 5.0)
    rows = []
    for opt_type in ["call", "put"]:
        for strike in strikes:
            moneyness = abs(math.log(strike / spot))
            iv = 0.18 + 0.28 * moneyness
            theo = black_scholes_price(spot, float(strike), t, RISK_FREE_RATE, iv, opt_type, DIVIDEND_YIELD)
            spread = max(0.02, theo * 0.015)
            rows.append(
                {
                    "contractSymbol": f"SYN{expiry_date.replace('-', '')}{opt_type[0].upper()}{int(strike * 1000)}",
                    "strike": float(strike),
                    "lastPrice": theo,
                    "bid": max(0.01, theo - spread / 2),
                    "ask": theo + spread / 2,
                    "volume": int(rng.integers(100, 6000)),
                    "openInterest": int(rng.integers(500, 25000)),
                    "impliedVolatility": iv,
                    "inTheMoney": (spot > strike if opt_type == "call" else spot < strike),
                    "option_type": opt_type,
                    "expiry": expiry_date,
                }
            )
    chain = clean_option_chain(pd.DataFrame(rows), expiry_date)
    return hist, chain, expiry_date, "synthetic_fallback"


def download_yahoo_data(ticker: str = TICKER) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    import yfinance as yf

    tkr = yf.Ticker(ticker)
    hist = tkr.history(period="1y", interval="1d", auto_adjust=False)
    if hist.empty:
        raise RuntimeError("Yahoo history is empty.")
    expirations = list(tkr.options)
    if not expirations:
        raise RuntimeError("Yahoo option expirations are empty.")

    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    candidates = []
    for exp in expirations:
        dte = (pd.Timestamp(exp) - today).days
        if dte >= 14:
            candidates.append((abs(dte - 45), dte, exp))
    if not candidates:
        candidates = [(999, (pd.Timestamp(exp) - today).days, exp) for exp in expirations]
    _, _, expiry = sorted(candidates)[0]

    option_chain = tkr.option_chain(expiry)
    calls = option_chain.calls.copy()
    puts = option_chain.puts.copy()
    calls["option_type"] = "call"
    puts["option_type"] = "put"
    chain = clean_option_chain(pd.concat([calls, puts], ignore_index=True), expiry)
    if chain.empty:
        raise RuntimeError("Yahoo option chain is empty after cleaning.")
    return hist, chain, expiry, "yfinance"


def get_market_data(ticker: str = TICKER) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    try:
        hist, chain, expiry, source = download_yahoo_data(ticker)
    except Exception as exc:
        print(f"Yahoo download failed, using deterministic fallback: {exc}")
        hist, chain, expiry, source = synthetic_history_and_chain()

    hist = hist.reset_index()
    if "Date" not in hist.columns:
        hist = hist.rename(columns={hist.columns[0]: "Date"})
    hist["Date"] = pd.to_datetime(hist["Date"]).dt.tz_localize(None)
    hist.to_csv(DATA_DIR / f"{ticker.lower()}_history.csv", index=False, encoding="utf-8-sig")
    chain.to_csv(DATA_DIR / f"{ticker.lower()}_option_chain_{expiry}.csv", index=False, encoding="utf-8-sig")
    return hist, chain, expiry, source


def compute_rsi(close: pd.Series, window: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1])


def form_view(hist: pd.DataFrame, chain: pd.DataFrame, expiry: str, source: str) -> dict[str, object]:
    close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    spot = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    ret20 = float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) > 21 else 0.0
    rv20 = float(np.log(close / close.shift(1)).rolling(20).std().iloc[-1] * math.sqrt(252))
    rv60 = float(np.log(close / close.shift(1)).rolling(60).std().iloc[-1] * math.sqrt(252))
    rsi14 = compute_rsi(close)

    atm = chain.loc[(chain["strike"] - spot).abs().sort_values().index[:10]]
    atm_iv = float(atm["impliedVolatility"].median())
    dte = max((pd.Timestamp(expiry) - pd.Timestamp(hist["Date"].iloc[-1])).days, 1)

    trend_score = 0
    if ma20 > ma60:
        trend_score += 1
    else:
        trend_score -= 1
    if ret20 > 0.02:
        trend_score += 1
    elif ret20 < -0.02:
        trend_score -= 1
    if rsi14 > 70:
        trend_score -= 1
    elif rsi14 < 30:
        trend_score += 1

    if trend_score >= 1:
        view = "bullish"
        view_cn = "偏多"
    elif trend_score <= -1:
        view = "bearish"
        view_cn = "偏空"
    else:
        view = "neutral"
        view_cn = "中性"

    iv_rv_spread = atm_iv - rv20
    if iv_rv_spread > 0.04:
        volatility_view = "IV高于近期RV，权利金偏贵"
    elif iv_rv_spread < -0.04:
        volatility_view = "IV低于近期RV，权利金偏便宜"
    else:
        volatility_view = "IV与近期RV接近，波动率定价中性"

    return {
        "ticker": TICKER,
        "data_source": source,
        "as_of": str(pd.Timestamp(hist["Date"].iloc[-1]).date()),
        "expiry": expiry,
        "dte": int(dte),
        "spot": spot,
        "ma20": ma20,
        "ma60": ma60,
        "ret20": ret20,
        "rv20": rv20,
        "rv60": rv60,
        "rsi14": rsi14,
        "atm_iv": atm_iv,
        "iv_minus_rv20": iv_rv_spread,
        "trend_score": int(trend_score),
        "directional_view": view,
        "directional_view_cn": view_cn,
        "volatility_view": volatility_view,
    }


def black_scholes_price(
    spot: float,
    strike: float,
    t: float,
    rate: float,
    sigma: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float:
    if t <= 0:
        return max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    sigma = max(float(sigma), 1e-6)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if option_type == "call":
        return spot * math.exp(-dividend_yield * t) * norm.cdf(d1) - strike * math.exp(-rate * t) * norm.cdf(d2)
    return strike * math.exp(-rate * t) * norm.cdf(-d2) - spot * math.exp(-dividend_yield * t) * norm.cdf(-d1)


def black_scholes_greeks(
    spot: float,
    strike: float,
    t: float,
    rate: float,
    sigma: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> dict[str, float]:
    sigma = max(float(sigma), 1e-6)
    t = max(float(t), 1e-6)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    nd1 = norm.pdf(d1)
    df_q = math.exp(-dividend_yield * t)
    df_r = math.exp(-rate * t)

    if option_type == "call":
        delta = df_q * norm.cdf(d1)
        theta = (
            -spot * df_q * nd1 * sigma / (2 * math.sqrt(t))
            - rate * strike * df_r * norm.cdf(d2)
            + dividend_yield * spot * df_q * norm.cdf(d1)
        ) / 365
        rho = strike * t * df_r * norm.cdf(d2) * 0.01
    else:
        delta = -df_q * norm.cdf(-d1)
        theta = (
            -spot * df_q * nd1 * sigma / (2 * math.sqrt(t))
            + rate * strike * df_r * norm.cdf(-d2)
            - dividend_yield * spot * df_q * norm.cdf(-d1)
        ) / 365
        rho = -strike * t * df_r * norm.cdf(-d2) * 0.01

    gamma = df_q * nd1 / (spot * sigma * math.sqrt(t))
    vega = spot * df_q * nd1 * math.sqrt(t) * 0.01
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def select_option(chain: pd.DataFrame, option_type: str, target_strike: float) -> pd.Series:
    sub = chain[(chain["option_type"] == option_type) & (chain["mid"] > 0)].copy()
    if sub.empty:
        raise ValueError(f"No {option_type} options available.")
    sub["distance"] = (sub["strike"] - target_strike).abs()
    liquidity = sub.get("openInterest", pd.Series(0, index=sub.index)).fillna(0) + sub.get(
        "volume", pd.Series(0, index=sub.index)
    ).fillna(0)
    sub["liquidity_rank"] = liquidity.rank(ascending=False, method="first")
    return sub.sort_values(["distance", "liquidity_rank"]).iloc[0]


def build_strategy(chain: pd.DataFrame, view: dict[str, object]) -> tuple[str, list[dict[str, object]]]:
    spot = float(view["spot"])
    direction = str(view["directional_view"])
    iv_minus_rv = float(view["iv_minus_rv20"])

    if direction == "bullish":
        strategy_name = "牛市看涨价差"
        specs = [
            ("call", spot * 1.00, 1),
            ("call", spot * 1.04, -1),
        ]
    elif direction == "bearish":
        strategy_name = "熊市看跌价差"
        specs = [
            ("put", spot * 1.00, 1),
            ("put", spot * 0.96, -1),
        ]
    elif iv_minus_rv > 0.04:
        strategy_name = "铁鹰式价差"
        specs = [
            ("put", spot * 0.94, 1),
            ("put", spot * 0.97, -1),
            ("call", spot * 1.03, -1),
            ("call", spot * 1.06, 1),
        ]
    else:
        strategy_name = "买入跨式"
        specs = [
            ("call", spot, 1),
            ("put", spot, 1),
        ]

    legs = []
    used = set()
    for option_type, target, qty in specs:
        row = select_option(chain[~chain["contractSymbol"].isin(used)], option_type, target)
        used.add(str(row["contractSymbol"]))
        legs.append(
            {
                "contract_symbol": str(row["contractSymbol"]),
                "option_type": option_type,
                "strike": float(row["strike"]),
                "expiry": str(row["expiry"]),
                "quantity": int(qty),
                "mid": float(row["mid"]),
                "implied_volatility": float(row["impliedVolatility"]),
                "volume": float(row.get("volume", np.nan)),
                "openInterest": float(row.get("openInterest", np.nan)),
                "relative_spread": float(row.get("relative_spread", np.nan)),
            }
        )
    return strategy_name, legs


def add_greeks_to_legs(legs: list[dict[str, object]], view: dict[str, object]) -> list[OptionLeg]:
    spot = float(view["spot"])
    expiry = pd.Timestamp(str(view["expiry"]))
    as_of = pd.Timestamp(str(view["as_of"]))
    t = max((expiry - as_of).days, 1) / 365.0
    out = []
    for leg in legs:
        greeks = black_scholes_greeks(
            spot=spot,
            strike=float(leg["strike"]),
            t=t,
            rate=RISK_FREE_RATE,
            sigma=float(leg["implied_volatility"]),
            option_type=str(leg["option_type"]),
            dividend_yield=DIVIDEND_YIELD,
        )
        out.append(
            OptionLeg(
                contract_symbol=str(leg["contract_symbol"]),
                option_type=str(leg["option_type"]),
                strike=float(leg["strike"]),
                expiry=str(leg["expiry"]),
                quantity=int(leg["quantity"]),
                mid=float(leg["mid"]),
                implied_volatility=float(leg["implied_volatility"]),
                delta=greeks["delta"],
                gamma=greeks["gamma"],
                vega=greeks["vega"],
                theta=greeks["theta"],
                rho=greeks["rho"],
            )
        )
    return out


def portfolio_greeks(legs: list[OptionLeg]) -> pd.DataFrame:
    rows = []
    totals = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0, "market_value": 0.0}
    for leg in legs:
        row = asdict(leg)
        row["market_value"] = leg.quantity * leg.mid * CONTRACT_MULTIPLIER
        for greek in ["delta", "gamma", "vega", "theta", "rho"]:
            row[f"portfolio_{greek}"] = leg.quantity * getattr(leg, greek) * CONTRACT_MULTIPLIER
            totals[greek] += row[f"portfolio_{greek}"]
        totals["market_value"] += row["market_value"]
        rows.append(row)
    rows.append(
        {
            "contract_symbol": "TOTAL",
            "option_type": "",
            "strike": np.nan,
            "expiry": "",
            "quantity": np.nan,
            "mid": np.nan,
            "implied_volatility": np.nan,
            "delta": np.nan,
            "gamma": np.nan,
            "vega": np.nan,
            "theta": np.nan,
            "rho": np.nan,
            "market_value": totals["market_value"],
            "portfolio_delta": totals["delta"],
            "portfolio_gamma": totals["gamma"],
            "portfolio_vega": totals["vega"],
            "portfolio_theta": totals["theta"],
            "portfolio_rho": totals["rho"],
        }
    )
    return pd.DataFrame(rows)


def expiry_payoff(legs: list[OptionLeg], spots: np.ndarray) -> pd.DataFrame:
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)
    rows = []
    for s in spots:
        intrinsic = 0.0
        for leg in legs:
            if leg.option_type == "call":
                payoff = max(s - leg.strike, 0.0)
            else:
                payoff = max(leg.strike - s, 0.0)
            intrinsic += leg.quantity * payoff * CONTRACT_MULTIPLIER
        rows.append({"underlying_price": s, "expiry_value": intrinsic, "pnl": intrinsic - initial_value})
    return pd.DataFrame(rows)


def scenario_pnl(legs: list[OptionLeg], view: dict[str, object]) -> pd.DataFrame:
    spot0 = float(view["spot"])
    expiry = pd.Timestamp(str(view["expiry"]))
    as_of = pd.Timestamp(str(view["as_of"]))
    current_t = max((expiry - as_of).days, 1) / 365.0
    future_t = max(current_t - 7 / 365.0, 1 / 365.0)
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)
    rows = []
    for spot_move in [-0.05, -0.02, 0.0, 0.02, 0.05]:
        for iv_shift in [-0.03, 0.0, 0.03]:
            spot = spot0 * (1 + spot_move)
            value = 0.0
            for leg in legs:
                sigma = max(0.01, leg.implied_volatility + iv_shift)
                price = black_scholes_price(spot, leg.strike, future_t, RISK_FREE_RATE, sigma, leg.option_type)
                value += leg.quantity * price * CONTRACT_MULTIPLIER
            rows.append(
                {
                    "spot_move": spot_move,
                    "iv_shift": iv_shift,
                    "strategy_value_after_7d": value,
                    "pnl_after_7d": value - initial_value,
                }
            )
    return pd.DataFrame(rows)


def build_pnl_summary(payoff: pd.DataFrame, scenario: pd.DataFrame, initial_value: float) -> dict[str, object]:
    max_profit = float(payoff["pnl"].max())
    max_loss = float(payoff["pnl"].min())
    best = payoff.loc[payoff["pnl"].idxmax()]
    worst = payoff.loc[payoff["pnl"].idxmin()]
    sign = np.sign(payoff["pnl"])
    breakevens = []
    for idx in range(1, len(payoff)):
        if sign.iloc[idx] == 0:
            breakevens.append(float(payoff["underlying_price"].iloc[idx]))
        elif sign.iloc[idx] != sign.iloc[idx - 1]:
            x0, y0 = payoff["underlying_price"].iloc[idx - 1], payoff["pnl"].iloc[idx - 1]
            x1, y1 = payoff["underlying_price"].iloc[idx], payoff["pnl"].iloc[idx]
            breakevens.append(float(x0 - y0 * (x1 - x0) / (y1 - y0)))
    return {
        "initial_value": float(initial_value),
        "max_profit_in_grid": max_profit,
        "max_loss_in_grid": max_loss,
        "best_expiry_price_in_grid": float(best["underlying_price"]),
        "worst_expiry_price_in_grid": float(worst["underlying_price"]),
        "breakevens_in_grid": breakevens,
        "scenario_best_pnl": float(scenario["pnl_after_7d"].max()),
        "scenario_worst_pnl": float(scenario["pnl_after_7d"].min()),
    }


def _simulate_terminal_spot(
    spot0: float, drift: float, sigma: float, t: float, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    z = rng.standard_normal(n_paths)
    return spot0 * np.exp((drift - 0.5 * sigma * sigma) * t + sigma * math.sqrt(t) * z)


def _strategy_pnl_at_expiry(legs: list[OptionLeg], spot_t: np.ndarray) -> np.ndarray:
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)
    payoffs = np.zeros_like(spot_t, dtype=float)
    for leg in legs:
        if leg.option_type == "call":
            leg_payoff = np.maximum(spot_t - leg.strike, 0.0)
        else:
            leg_payoff = np.maximum(leg.strike - spot_t, 0.0)
        payoffs += leg.quantity * leg_payoff * CONTRACT_MULTIPLIER
    return payoffs - initial_value


def _mc_stats_block(pnl: np.ndarray, initial_value: float, label: str, drift: float, sigma: float) -> dict[str, float]:
    sorted_pnl = np.sort(pnl)
    n = len(pnl)
    var_95 = float(-np.quantile(pnl, 0.05))
    var_99 = float(-np.quantile(pnl, 0.01))
    tail_5 = sorted_pnl[: max(int(0.05 * n), 1)]
    tail_1 = sorted_pnl[: max(int(0.01 * n), 1)]
    return {
        "scenario": label,
        "annual_drift_used": float(drift),
        "annual_sigma_used": float(sigma),
        "expected_pnl": float(pnl.mean()),
        "median_pnl": float(np.median(pnl)),
        "std_pnl": float(pnl.std(ddof=1)),
        "min_pnl": float(pnl.min()),
        "max_pnl": float(pnl.max()),
        "prob_of_profit": float((pnl > 0).mean()),
        "prob_loss_gt_half_premium": float((pnl < -0.5 * initial_value).mean()) if initial_value > 0 else float("nan"),
        "var_95": var_95,
        "var_99": var_99,
        "cvar_95": float(-tail_5.mean()),
        "cvar_99": float(-tail_1.mean()),
        "p05": float(np.quantile(pnl, 0.05)),
        "p25": float(np.quantile(pnl, 0.25)),
        "p50": float(np.quantile(pnl, 0.50)),
        "p75": float(np.quantile(pnl, 0.75)),
        "p95": float(np.quantile(pnl, 0.95)),
    }


def monte_carlo_pnl(
    legs: list[OptionLeg],
    view: dict[str, object],
    n_paths: int = 20000,
    seed: int = RANDOM_SEED,
) -> tuple[pd.DataFrame, dict[str, float], pd.DataFrame]:
    """Lognormal Monte Carlo of strategy P&L at expiry.

    We run two scenarios so the student can compare:
      1. risk-neutral: drift = r - q, sigma = ATM IV (Black-Scholes consistent)
      2. real-world:   drift = clipped historical 20-day annualized return,
                        sigma = realised volatility RV60 (more stable than RV20)
    The primary distribution returned is the risk-neutral one (academic default).
    """
    rng = np.random.default_rng(seed)
    spot0 = float(view["spot"])
    rv20 = float(view["rv20"])
    rv60 = float(view["rv60"])
    atm_iv = float(view["atm_iv"])
    expiry = pd.Timestamp(str(view["expiry"]))
    as_of = pd.Timestamp(str(view["as_of"]))
    horizon_days = max((expiry - as_of).days, 1)
    t = horizon_days / 365.0

    rn_drift = RISK_FREE_RATE - DIVIDEND_YIELD
    rn_sigma = max(atm_iv, 0.05)
    rw_drift = float(np.clip(float(view["ret20"]) * 252.0 / 20.0, -0.30, 0.30))
    rw_sigma = max(rv60, 0.05)

    spot_rn = _simulate_terminal_spot(spot0, rn_drift, rn_sigma, t, n_paths, rng)
    spot_rw = _simulate_terminal_spot(spot0, rw_drift, rw_sigma, t, n_paths, rng)
    pnl_rn = _strategy_pnl_at_expiry(legs, spot_rn)
    pnl_rw = _strategy_pnl_at_expiry(legs, spot_rw)
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)

    rn_block = _mc_stats_block(pnl_rn, initial_value, "risk_neutral", rn_drift, rn_sigma)
    rw_block = _mc_stats_block(pnl_rw, initial_value, "real_world", rw_drift, rw_sigma)

    paths_df = pd.DataFrame(
        {
            "spot_at_expiry_rn": spot_rn,
            "strategy_pnl_rn": pnl_rn,
            "spot_at_expiry_rw": spot_rw,
            "strategy_pnl_rw": pnl_rw,
        }
    )
    stats_df = pd.DataFrame([rn_block, rw_block])

    primary = {
        "n_paths": int(n_paths),
        "horizon_days": int(horizon_days),
        "rv20": rv20,
        "rv60": rv60,
        "atm_iv": atm_iv,
        **rn_block,
    }
    primary["scenario"] = "risk_neutral"
    return paths_df, primary, stats_df


def multi_horizon_scenarios(
    legs: list[OptionLeg],
    view: dict[str, object],
    horizons_days: tuple[int, ...] = (1, 7, 14, 21),
    spot_moves: tuple[float, ...] = (-0.05, -0.02, 0.0, 0.02, 0.05),
) -> pd.DataFrame:
    """Reprice the strategy across (horizon, spot move) keeping IV unchanged."""
    spot0 = float(view["spot"])
    expiry = pd.Timestamp(str(view["expiry"]))
    as_of = pd.Timestamp(str(view["as_of"]))
    full_t = max((expiry - as_of).days, 1) / 365.0
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)

    rows = []
    for h in horizons_days:
        t_remain = max(full_t - h / 365.0, 1 / 365.0)
        for move in spot_moves:
            spot = spot0 * (1 + move)
            value = 0.0
            for leg in legs:
                price = black_scholes_price(
                    spot, leg.strike, t_remain, RISK_FREE_RATE, leg.implied_volatility, leg.option_type
                )
                value += leg.quantity * price * CONTRACT_MULTIPLIER
            rows.append(
                {
                    "horizon_days": int(h),
                    "spot_move": move,
                    "spot": spot,
                    "strategy_value": value,
                    "pnl": value - initial_value,
                }
            )
    return pd.DataFrame(rows)


def save_plots(
    hist: pd.DataFrame,
    payoff: pd.DataFrame,
    greeks: pd.DataFrame,
    scenario: pd.DataFrame,
    mc_paths: pd.DataFrame | None = None,
    mc_stats: dict[str, float] | None = None,
    multi_horizon: pd.DataFrame | None = None,
) -> None:
    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")

    hist2 = hist.copy()
    hist2["MA20"] = hist2["Close"].rolling(20).mean()
    hist2["MA60"] = hist2["Close"].rolling(60).mean()
    plt.figure(figsize=(10.5, 4.8))
    plt.plot(hist2["Date"], hist2["Close"], label="Close", linewidth=1.4)
    plt.plot(hist2["Date"], hist2["MA20"], label="MA20", linewidth=1.1)
    plt.plot(hist2["Date"], hist2["MA60"], label="MA60", linewidth=1.1)
    plt.title(f"{TICKER} price and trend indicators")
    plt.ylabel("Price")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "underlying_view.png", dpi=160)
    plt.close()

    plt.figure(figsize=(10.5, 4.8))
    plt.plot(payoff["underlying_price"], payoff["pnl"], color="#1f77b4", linewidth=1.8)
    plt.axhline(0, color="#666666", linewidth=0.9)
    plt.title("Strategy expiry P&L")
    plt.xlabel("Underlying price at expiry")
    plt.ylabel("P&L")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "strategy_payoff.png", dpi=160)
    plt.close()

    total = greeks[greeks["contract_symbol"] == "TOTAL"].iloc[0]
    labels = ["Delta", "Gamma", "Vega", "Theta", "Rho"]
    values = [
        total["portfolio_delta"],
        total["portfolio_gamma"],
        total["portfolio_vega"],
        total["portfolio_theta"],
        total["portfolio_rho"],
    ]
    plt.figure(figsize=(8.5, 4.5))
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in values]
    plt.bar(labels, values, color=colors)
    plt.axhline(0, color="#666666", linewidth=0.9)
    plt.title("Portfolio Greeks")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "portfolio_greeks.png", dpi=160)
    plt.close()

    pivot = scenario.pivot(index="iv_shift", columns="spot_move", values="pnl_after_7d").sort_index(ascending=False)
    plt.figure(figsize=(8.5, 4.8))
    im = plt.imshow(pivot.values, cmap="RdYlGn", aspect="auto")
    plt.colorbar(im, label="P&L after 7 days")
    plt.xticks(range(len(pivot.columns)), [f"{x:.0%}" for x in pivot.columns])
    plt.yticks(range(len(pivot.index)), [f"{x:+.0%}" for x in pivot.index])
    plt.xlabel("Spot move")
    plt.ylabel("IV shift")
    plt.title("Scenario P&L heatmap")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            plt.text(j, i, f"{pivot.values[i, j]:.0f}", ha="center", va="center", fontsize=8)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "scenario_pnl_heatmap.png", dpi=160)
    plt.close()

    if mc_paths is not None and mc_stats is not None:
        pnl_col = "strategy_pnl_rn" if "strategy_pnl_rn" in mc_paths.columns else "strategy_pnl"
        plt.figure(figsize=(10.0, 4.8))
        ax = plt.gca()
        ax.hist(mc_paths[pnl_col], bins=60, color="#4c78a8", alpha=0.85, edgecolor="white")
        ax.axvline(0, color="#666666", linewidth=1.0, linestyle="--", label="Breakeven")
        ax.axvline(-mc_stats["var_95"], color="#d62728", linewidth=1.2, label=f"VaR95={-mc_stats['var_95']:.0f}")
        ax.axvline(-mc_stats["var_99"], color="#8c564b", linewidth=1.2, label=f"VaR99={-mc_stats['var_99']:.0f}")
        ax.axvline(mc_stats["expected_pnl"], color="#2ca02c", linewidth=1.2, label=f"E[PnL]={mc_stats['expected_pnl']:.0f}")
        ax.set_title(
            f"Monte Carlo P&L distribution at expiry (risk-neutral, POP={mc_stats['prob_of_profit']:.1%}, n={mc_stats['n_paths']})"
        )
        ax.set_xlabel("Strategy P&L (USD)")
        ax.set_ylabel("Frequency")
        ax.legend(loc="upper right", fontsize=9)
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / "monte_carlo_pnl.png", dpi=160)
        plt.close()

    if multi_horizon is not None and not multi_horizon.empty:
        plt.figure(figsize=(10.0, 4.8))
        for h, sub in multi_horizon.groupby("horizon_days"):
            sub_sorted = sub.sort_values("spot_move")
            plt.plot(
                [m * 100 for m in sub_sorted["spot_move"]],
                sub_sorted["pnl"],
                marker="o",
                linewidth=1.6,
                label=f"+{int(h)}d",
            )
        plt.axhline(0, color="#666666", linewidth=0.9)
        plt.title("Multi-horizon P&L curves (IV unchanged)")
        plt.xlabel("Spot move (%)")
        plt.ylabel("Strategy P&L (USD)")
        plt.legend(title="Horizon", loc="best")
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / "multi_horizon_pnl.png", dpi=160)
        plt.close()


def main() -> None:
    ensure_dirs()
    hist, chain, expiry, source = get_market_data(TICKER)
    view = form_view(hist, chain, expiry, source)
    strategy_name, raw_legs = build_strategy(chain, view)
    legs = add_greeks_to_legs(raw_legs, view)
    greeks_df = portfolio_greeks(legs)

    spot = float(view["spot"])
    spots = np.linspace(spot * 0.80, spot * 1.20, 161)
    payoff_df = expiry_payoff(legs, spots)
    scenario_df = scenario_pnl(legs, view)
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)
    pnl_summary = build_pnl_summary(payoff_df, scenario_df, initial_value)

    mc_paths_df, mc_primary, mc_stats_df = monte_carlo_pnl(legs, view)
    multi_horizon_df = multi_horizon_scenarios(legs, view)

    legs_df = pd.DataFrame([asdict(leg) for leg in legs])
    legs_df.to_csv(OUTPUT_DIR / "strategy_legs.csv", index=False, encoding="utf-8-sig")
    greeks_df.to_csv(OUTPUT_DIR / "portfolio_greeks.csv", index=False, encoding="utf-8-sig")
    payoff_df.to_csv(OUTPUT_DIR / "strategy_payoff.csv", index=False, encoding="utf-8-sig")
    scenario_df.to_csv(OUTPUT_DIR / "scenario_pnl.csv", index=False, encoding="utf-8-sig")
    mc_paths_df.to_csv(OUTPUT_DIR / "monte_carlo_paths.csv", index=False, encoding="utf-8-sig")
    mc_stats_df.to_csv(OUTPUT_DIR / "monte_carlo_stats.csv", index=False, encoding="utf-8-sig")
    multi_horizon_df.to_csv(OUTPUT_DIR / "multi_horizon_pnl.csv", index=False, encoding="utf-8-sig")

    view["strategy_name"] = strategy_name
    view["pnl_summary"] = pnl_summary
    view["mc_primary"] = mc_primary
    view["mc_real_world"] = mc_stats_df.iloc[1].to_dict()
    view["contract_multiplier"] = CONTRACT_MULTIPLIER
    (OUTPUT_DIR / "view_summary.json").write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([view | {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in view.items()}]).to_csv(
        OUTPUT_DIR / "view_summary.csv", index=False, encoding="utf-8-sig"
    )

    save_plots(hist, payoff_df, greeks_df, scenario_df, mc_paths_df, mc_primary, multi_horizon_df)
    print(json.dumps(view, ensure_ascii=False, indent=2))
    print("Outputs:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
