"""
week10_project_backtest.py
==========================

Daily-bar historical option simulation backtest for the Week-10 Project.

The notebook follows three steps:

  1. **Historical option-chain reconstruction.** Free historical option tick
     data is not generally available, so we *reproduce* historical option
     prices from the underlying's daily history.  At each historical trading
     day t we synthesise an option chain at multiple DTEs and strikes using
     Black-Scholes with an IV surface fitted from realised volatility:

         IV(t, K, T) = max(0.05, RV_20(t) * IV_RV_ratio
                                  + skew * ln(K/F_t) / sqrt(T))

     RV_20 is the 20-day annualised realised vol; IV_RV_ratio (default 1.10)
     captures the historically observed IV-RV premium; skew gives put-side
     premium consistent with the equity-index volatility smile.

  2. **Strategy: rolling short strangle with profit-take / stop-loss.**
     - Every Friday, if flat, open a 0.20-delta short strangle 30 days out,
       sized so cash collateral = $50,000.
     - Close the position when:
         (a) it reaches 50 percent of max profit (take profit), or
         (b) it loses 200 percent of initial credit (stop loss), or
         (c) we reach DTE = 2 (managed expiry).
     - Mark-to-market daily.

  3. **Risk and performance analysis.**
     - Equity curve & drawdown
     - Trade-level P&L distribution
     - Daily Greek exposure
     - Comparison vs underlying buy-and-hold
     - Stats: total return, CAGR, Sharpe, Sortino, max drawdown, win rate,
       average trade P&L, expectancy, profit factor.

Target ticker is SPY by default (academic, comparable to CBOE VIX setting).
Edit TICKER below to USO/QQQ etc.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/week10"
OUTPUT_DIR = ROOT / "research/outputs/week10/project"
TICKER = "SPY"
LOOKBACK_DAYS = 504  # ~2 trading years
INITIAL_CAPITAL = 100_000.0
COLLATERAL_PER_TRADE = 50_000.0
RISK_FREE_RATE = 0.04
DIVIDEND_YIELD = 0.0
CONTRACT_MULTIPLIER = 100
IV_RV_RATIO = 1.10  # observed historical premium
PUT_SKEW = 0.06  # additional put IV per unit of sqrt(T)*ln(K/F)
ENTRY_DELTA = 0.20
ROLL_DTE_TARGET = 30
TAKE_PROFIT = 0.50
STOP_LOSS = 2.00
MANAGED_DTE = 2
BIDASK_HAIRCUT = 0.01  # 1% of mid lost to spread per execution
COMMISSION_PER_LEG = 0.65  # per contract, per execution
RANDOM_SEED = 23300180062


# ---------------------------------------------------------------------------
# Black-Scholes helpers
# ---------------------------------------------------------------------------


def bs_price(spot: float, k: float, t: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    if t <= 0:
        return max(spot - k, 0.0) if kind == "call" else max(k - spot, 0.0)
    sigma = max(sigma, 1e-6)
    d1 = (math.log(spot / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if kind == "call":
        return spot * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    return k * math.exp(-r * t) * norm.cdf(-d2) - spot * math.exp(-q * t) * norm.cdf(-d1)


def bs_delta(spot: float, k: float, t: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    sigma = max(sigma, 1e-6)
    t = max(t, 1e-6)
    d1 = (math.log(spot / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    if kind == "call":
        return math.exp(-q * t) * norm.cdf(d1)
    return -math.exp(-q * t) * norm.cdf(-d1)


def bs_greeks(spot: float, k: float, t: float, r: float, sigma: float, kind: str, q: float = 0.0) -> dict:
    sigma = max(sigma, 1e-6)
    t = max(t, 1e-6)
    d1 = (math.log(spot / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    nd1 = norm.pdf(d1)
    dfq, dfr = math.exp(-q * t), math.exp(-r * t)
    if kind == "call":
        delta = dfq * norm.cdf(d1)
        theta = (
            -spot * dfq * nd1 * sigma / (2 * math.sqrt(t))
            - r * k * dfr * norm.cdf(d2)
            + q * spot * dfq * norm.cdf(d1)
        ) / 365
    else:
        delta = -dfq * norm.cdf(-d1)
        theta = (
            -spot * dfq * nd1 * sigma / (2 * math.sqrt(t))
            + r * k * dfr * norm.cdf(-d2)
            - q * spot * dfq * norm.cdf(-d1)
        ) / 365
    return {
        "delta": delta,
        "gamma": dfq * nd1 / (spot * sigma * math.sqrt(t)),
        "vega": spot * dfq * nd1 * math.sqrt(t) * 0.01,
        "theta": theta,
    }


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


def load_underlying(ticker: str = TICKER) -> tuple[pd.DataFrame, str]:
    cache = DATA_DIR / f"{ticker.lower()}_history_backtest.csv"
    source = "cached"
    try:
        import yfinance as yf

        h = yf.Ticker(ticker).history(period="3y", interval="1d", auto_adjust=False)
        if h.empty:
            raise RuntimeError("empty history")
        h = h.reset_index()
        if "Date" not in h.columns:
            h = h.rename(columns={h.columns[0]: "Date"})
        h["Date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None)
        h.to_csv(cache, index=False, encoding="utf-8-sig")
        source = "yfinance"
        return h, source
    except Exception as exc:
        if cache.exists():
            return pd.read_csv(cache, parse_dates=["Date"]), "cached"
        # last-resort GBM
        rng = np.random.default_rng(RANDOM_SEED)
        dates = pd.bdate_range(end=pd.Timestamp.today(), periods=LOOKBACK_DAYS + 100)
        log_r = rng.normal(0.0003, 0.011, size=len(dates))
        close = 480.0 * np.exp(np.cumsum(log_r))
        h = pd.DataFrame(
            {
                "Date": dates,
                "Open": close * (1 + rng.normal(0, 0.002, size=len(dates))),
                "High": close * (1 + rng.uniform(0.001, 0.01, size=len(dates))),
                "Low": close * (1 - rng.uniform(0.001, 0.01, size=len(dates))),
                "Close": close,
                "Volume": rng.integers(50_000_000, 110_000_000, size=len(dates)),
            }
        )
        h.to_csv(cache, index=False, encoding="utf-8-sig")
        return h, "synthetic_gbm"


def add_realised_vol(h: pd.DataFrame) -> pd.DataFrame:
    out = h.copy().sort_values("Date").reset_index(drop=True)
    log_r = np.log(out["Close"] / out["Close"].shift(1))
    out["log_return"] = log_r
    out["rv20"] = log_r.rolling(20).std() * math.sqrt(252)
    out["rv60"] = log_r.rolling(60).std() * math.sqrt(252)
    out["rv120"] = log_r.rolling(120).std() * math.sqrt(252)
    out["ma20"] = out["Close"].rolling(20).mean()
    out["ma60"] = out["Close"].rolling(60).mean()
    return out


def iv_surface(spot: float, k: float, t: float, rv20: float, rv60: float) -> float:
    """Simple IV surface: vol level from RV (with IV-RV premium), plus put skew."""
    base = max((rv20 if not np.isnan(rv20) else rv60), 0.08)
    base *= IV_RV_RATIO
    # log-moneyness term:  positive => ITM call / OTM put. We want OTM puts to
    # carry a *higher* IV ⇒ negative log-moneyness needs positive premium ⇒
    # subtract PUT_SKEW * ln(K/F) / sqrt(T).
    skew_term = -PUT_SKEW * math.log(k / spot) / math.sqrt(max(t, 1e-3))
    return float(max(0.05, base + skew_term))


# ---------------------------------------------------------------------------
# Synthetic option chain at one historical date
# ---------------------------------------------------------------------------


def synth_chain(spot: float, rv20: float, rv60: float, ref_date: pd.Timestamp, dte_list=(7, 14, 30, 45, 60)) -> pd.DataFrame:
    rows = []
    for dte in dte_list:
        t = dte / 365.0
        expiry = ref_date + pd.Timedelta(days=int(dte))
        # build a grid of strikes spaced ~0.5σ apart
        sigma_T = max((rv20 if not np.isnan(rv20) else 0.20), 0.08) * math.sqrt(t)
        step = max(spot * sigma_T * 0.25, 1.0)
        n_each = 12
        strikes = sorted(set(round(spot + i * step, 2) for i in range(-n_each, n_each + 1)))
        for k in strikes:
            for kind in ["call", "put"]:
                iv = iv_surface(spot, k, t, rv20, rv60)
                price = bs_price(spot, k, t, RISK_FREE_RATE, iv, kind, DIVIDEND_YIELD)
                if price <= 0.01:
                    continue
                rows.append(
                    {
                        "ref_date": str(ref_date.date()),
                        "expiry": str(expiry.date()),
                        "dte": int(dte),
                        "strike": float(k),
                        "option_type": kind,
                        "mid": float(price),
                        "iv": float(iv),
                        "delta": float(bs_delta(spot, k, t, RISK_FREE_RATE, iv, kind, DIVIDEND_YIELD)),
                    }
                )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Strategy and backtest engine
# ---------------------------------------------------------------------------


@dataclass
class OptionPosition:
    open_date: pd.Timestamp
    expiry: pd.Timestamp
    call_strike: float
    put_strike: float
    contracts: int
    call_open_iv: float
    put_open_iv: float
    call_open_mid: float
    put_open_mid: float
    initial_credit_per_share: float  # positive number: credit per share
    initial_credit_total: float  # USD


@dataclass
class TradeRecord:
    open_date: str
    close_date: str
    days_held: int
    expiry: str
    call_strike: float
    put_strike: float
    contracts: int
    open_credit: float
    close_cost: float
    commissions: float
    pnl: float
    pnl_pct_of_credit: float
    exit_reason: str
    underlying_at_open: float
    underlying_at_close: float


@dataclass
class BacktestState:
    history: pd.DataFrame
    daily: list[dict] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)


def pick_short_strangle(chain: pd.DataFrame, target_delta: float, target_dte: int) -> tuple[pd.Series, pd.Series]:
    """Pick the call and put closest to ±target_delta within the closest DTE."""
    if chain.empty:
        raise ValueError("empty chain")
    available_dtes = chain["dte"].unique()
    chosen_dte = min(available_dtes, key=lambda d: abs(d - target_dte))
    sub = chain[chain["dte"] == chosen_dte]
    calls = sub[sub["option_type"] == "call"]
    puts = sub[sub["option_type"] == "put"]
    call_row = calls.iloc[(calls["delta"] - target_delta).abs().argsort()[:1]].iloc[0]
    put_row = puts.iloc[(puts["delta"] + target_delta).abs().argsort()[:1]].iloc[0]
    return call_row, put_row


def open_position(date: pd.Timestamp, spot: float, chain: pd.DataFrame, position_count: int, capital: float) -> OptionPosition:
    call_row, put_row = pick_short_strangle(chain, ENTRY_DELTA, ROLL_DTE_TARGET)
    credit = float(call_row["mid"] + put_row["mid"])
    contracts = max(1, int(COLLATERAL_PER_TRADE // (float(call_row["strike"]) * CONTRACT_MULTIPLIER)))
    return OptionPosition(
        open_date=date,
        expiry=pd.Timestamp(call_row["expiry"]),
        call_strike=float(call_row["strike"]),
        put_strike=float(put_row["strike"]),
        contracts=contracts,
        call_open_iv=float(call_row["iv"]),
        put_open_iv=float(put_row["iv"]),
        call_open_mid=float(call_row["mid"]),
        put_open_mid=float(put_row["mid"]),
        initial_credit_per_share=credit,
        initial_credit_total=credit * CONTRACT_MULTIPLIER * contracts,
    )


def reprice_position(
    pos: OptionPosition, date: pd.Timestamp, spot: float, rv20: float, rv60: float
) -> dict:
    t = max((pos.expiry - date).days, 0) / 365.0
    if t <= 0:
        call_val = max(spot - pos.call_strike, 0.0)
        put_val = max(pos.put_strike - spot, 0.0)
        call_iv = pos.call_open_iv
        put_iv = pos.put_open_iv
        call_delta = 1.0 if spot > pos.call_strike else 0.0
        put_delta = -1.0 if spot < pos.put_strike else 0.0
        call_gamma = put_gamma = call_vega = put_vega = call_theta = put_theta = 0.0
    else:
        call_iv = iv_surface(spot, pos.call_strike, t, rv20, rv60)
        put_iv = iv_surface(spot, pos.put_strike, t, rv20, rv60)
        call_val = bs_price(spot, pos.call_strike, t, RISK_FREE_RATE, call_iv, "call", DIVIDEND_YIELD)
        put_val = bs_price(spot, pos.put_strike, t, RISK_FREE_RATE, put_iv, "put", DIVIDEND_YIELD)
        call_g = bs_greeks(spot, pos.call_strike, t, RISK_FREE_RATE, call_iv, "call", DIVIDEND_YIELD)
        put_g = bs_greeks(spot, pos.put_strike, t, RISK_FREE_RATE, put_iv, "put", DIVIDEND_YIELD)
        call_delta, put_delta = call_g["delta"], put_g["delta"]
        call_gamma, put_gamma = call_g["gamma"], put_g["gamma"]
        call_vega, put_vega = call_g["vega"], put_g["vega"]
        call_theta, put_theta = call_g["theta"], put_g["theta"]
    cost_per_share = call_val + put_val  # cost to buy back
    mark = pos.initial_credit_per_share - cost_per_share  # positive => profit
    mark_total = mark * CONTRACT_MULTIPLIER * pos.contracts
    # short positions: portfolio greeks = -1 * leg_greek per contract
    pf_delta = -(call_delta + put_delta) * CONTRACT_MULTIPLIER * pos.contracts
    pf_gamma = -(call_gamma + put_gamma) * CONTRACT_MULTIPLIER * pos.contracts
    pf_vega = -(call_vega + put_vega) * CONTRACT_MULTIPLIER * pos.contracts
    pf_theta = -(call_theta + put_theta) * CONTRACT_MULTIPLIER * pos.contracts
    return {
        "cost_per_share": cost_per_share,
        "mark_per_share": mark,
        "mark_total": mark_total,
        "delta": pf_delta,
        "gamma": pf_gamma,
        "vega": pf_vega,
        "theta": pf_theta,
        "call_val": call_val,
        "put_val": put_val,
    }


def close_position(pos: OptionPosition, date: pd.Timestamp, spot: float, rv20: float, rv60: float, reason: str) -> tuple[TradeRecord, float, float]:
    mark = reprice_position(pos, date, spot, rv20, rv60)
    cost_per_share = mark["cost_per_share"]
    # apply bid-ask haircut (we pay slightly more to close)
    cost_per_share *= (1 + BIDASK_HAIRCUT)
    close_cost_total = cost_per_share * CONTRACT_MULTIPLIER * pos.contracts
    # commissions: 2 legs open + 2 legs close
    commissions = COMMISSION_PER_LEG * pos.contracts * 4 if reason != "expiry" else COMMISSION_PER_LEG * pos.contracts * 2
    # P&L
    pnl = pos.initial_credit_total - close_cost_total - commissions
    days_held = (date.date() - pos.open_date.date()).days
    trade = TradeRecord(
        open_date=str(pos.open_date.date()),
        close_date=str(date.date()),
        days_held=days_held,
        expiry=str(pos.expiry.date()),
        call_strike=pos.call_strike,
        put_strike=pos.put_strike,
        contracts=pos.contracts,
        open_credit=float(pos.initial_credit_total),
        close_cost=float(close_cost_total),
        commissions=float(commissions),
        pnl=float(pnl),
        pnl_pct_of_credit=float(pnl / pos.initial_credit_total) if pos.initial_credit_total else 0.0,
        exit_reason=reason,
        underlying_at_open=float("nan"),  # filled later
        underlying_at_close=float(spot),
    )
    return trade, close_cost_total, commissions


def run_backtest(hist: pd.DataFrame) -> dict:
    h = hist.copy()
    h = add_realised_vol(h)
    h = h.dropna(subset=["rv20"]).reset_index(drop=True)

    cash = INITIAL_CAPITAL
    equity_records: list[dict] = []
    trades: list[TradeRecord] = []
    open_pos: OptionPosition | None = None
    sample_chains: list[pd.DataFrame] = []

    for i, row in h.iterrows():
        date = pd.Timestamp(row["Date"])
        spot = float(row["Close"])
        rv20 = float(row["rv20"])
        rv60 = float(row["rv60"]) if not np.isnan(row["rv60"]) else rv20

        # synth chain for entry signal / pricing
        chain = synth_chain(spot, rv20, rv60, date)

        # cache a few snapshots for the report
        if len(sample_chains) < 4 and date.weekday() == 4 and i % 60 == 0:
            sample = chain.copy()
            sample["snapshot_underlying"] = spot
            sample_chains.append(sample)

        if open_pos is not None:
            mark = reprice_position(open_pos, date, spot, rv20, rv60)
            mtm = mark["mark_total"]
            equity = cash + mtm
            close_now = False
            reason = ""
            # take profit at 50% of initial credit
            if mtm >= TAKE_PROFIT * open_pos.initial_credit_total:
                close_now, reason = True, "take_profit_50pct"
            elif mtm <= -STOP_LOSS * open_pos.initial_credit_total:
                close_now, reason = True, "stop_loss_-200pct"
            elif (open_pos.expiry - date).days <= MANAGED_DTE:
                close_now, reason = True, "managed_dte"
            if close_now:
                trade, close_cost, commissions = close_position(open_pos, date, spot, rv20, rv60, reason)
                trade.underlying_at_open = float(h.loc[h["Date"] == open_pos.open_date, "Close"].iloc[0])
                trades.append(trade)
                cash += trade.pnl  # credit was already collected at open; reinvest pnl
                open_pos = None
                # record post-close
                equity = cash
            equity_records.append(
                {
                    "Date": date,
                    "spot": spot,
                    "position_open": open_pos is not None,
                    "mtm": float(mtm) if open_pos is not None else 0.0,
                    "cash": float(cash),
                    "equity": float(equity),
                    "rv20": rv20,
                    "delta_exposure": float(mark["delta"]) if open_pos is not None else 0.0,
                    "gamma_exposure": float(mark["gamma"]) if open_pos is not None else 0.0,
                    "vega_exposure": float(mark["vega"]) if open_pos is not None else 0.0,
                    "theta_exposure": float(mark["theta"]) if open_pos is not None else 0.0,
                }
            )
            continue

        # No position open — check entry signal (Friday rolls)
        if date.weekday() == 4:
            open_pos = open_position(date, spot, chain, len(trades), cash)
            equity_records.append(
                {
                    "Date": date,
                    "spot": spot,
                    "position_open": True,
                    "mtm": 0.0,
                    "cash": float(cash),
                    "equity": float(cash),
                    "rv20": rv20,
                    "delta_exposure": 0.0,
                    "gamma_exposure": 0.0,
                    "vega_exposure": 0.0,
                    "theta_exposure": 0.0,
                }
            )
        else:
            equity_records.append(
                {
                    "Date": date,
                    "spot": spot,
                    "position_open": False,
                    "mtm": 0.0,
                    "cash": float(cash),
                    "equity": float(cash),
                    "rv20": rv20,
                    "delta_exposure": 0.0,
                    "gamma_exposure": 0.0,
                    "vega_exposure": 0.0,
                    "theta_exposure": 0.0,
                }
            )

    # Force-close any open at the end
    if open_pos is not None:
        last = h.iloc[-1]
        date = pd.Timestamp(last["Date"])
        spot = float(last["Close"])
        rv20 = float(last["rv20"])
        rv60 = float(last["rv60"]) if not np.isnan(last["rv60"]) else rv20
        trade, _, _ = close_position(open_pos, date, spot, rv20, rv60, "end_of_backtest")
        trade.underlying_at_open = float(h.loc[h["Date"] == open_pos.open_date, "Close"].iloc[0])
        trades.append(trade)
        cash += trade.pnl
        equity_records[-1]["cash"] = float(cash)
        equity_records[-1]["equity"] = float(cash)
        equity_records[-1]["mtm"] = 0.0

    eq_df = pd.DataFrame(equity_records)
    eq_df["Date"] = pd.to_datetime(eq_df["Date"])
    return {"equity": eq_df, "trades": trades, "sample_chains": sample_chains}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def compute_stats(equity: pd.DataFrame, trades: list[TradeRecord], hist: pd.DataFrame) -> dict:
    df = equity.copy().sort_values("Date").reset_index(drop=True)
    df["ret"] = df["equity"].pct_change().fillna(0.0)
    n_days = max(len(df), 2)
    total_return = float(df["equity"].iloc[-1] / df["equity"].iloc[0] - 1)
    n_years = n_days / 252.0
    cagr = float((df["equity"].iloc[-1] / df["equity"].iloc[0]) ** (1 / max(n_years, 1e-6)) - 1)
    sharpe = float(df["ret"].mean() / df["ret"].std() * math.sqrt(252)) if df["ret"].std() > 0 else float("nan")
    downside = df["ret"].clip(upper=0)
    sortino = float(df["ret"].mean() / downside.std() * math.sqrt(252)) if downside.std() > 0 else float("nan")

    cum = df["equity"].cummax()
    dd = (df["equity"] - cum) / cum
    max_dd = float(dd.min())

    # underlying buy-hold from first to last day, normalised to same start capital
    hist = hist.sort_values("Date").reset_index(drop=True)
    bh_start = float(hist["Close"].iloc[0])
    bh_end = float(hist["Close"].iloc[-1])
    bh_total = bh_end / bh_start - 1
    bh_cagr = (1 + bh_total) ** (1 / max(n_years, 1e-6)) - 1

    if trades:
        pnls = np.array([t.pnl for t in trades])
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = float(len(wins) / len(pnls))
        avg_win = float(wins.mean()) if len(wins) else 0.0
        avg_loss = float(losses.mean()) if len(losses) else 0.0
        expectancy = float(pnls.mean())
        profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else float("inf")
        max_trade = float(pnls.max())
        min_trade = float(pnls.min())
    else:
        win_rate = avg_win = avg_loss = expectancy = max_trade = min_trade = float("nan")
        profit_factor = float("nan")

    return {
        "start_equity": float(df["equity"].iloc[0]),
        "end_equity": float(df["equity"].iloc[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_dd,
        "n_days": int(n_days),
        "n_years": float(n_years),
        "n_trades": int(len(trades)),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_trade_pnl": max_trade,
        "min_trade_pnl": min_trade,
        "buyhold_total_return": float(bh_total),
        "buyhold_cagr": float(bh_cagr),
    }


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------


def plot_equity(equity: pd.DataFrame, hist: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    plt.style.use("seaborn-v0_8-whitegrid")
    eq = equity.copy().sort_values("Date").reset_index(drop=True)
    bh = hist.copy().sort_values("Date").reset_index(drop=True)
    norm_bh = bh["Close"] / bh["Close"].iloc[0] * eq["equity"].iloc[0]
    fig, ax = plt.subplots(figsize=(11.5, 5.0))
    ax.plot(eq["Date"], eq["equity"], label="Short Strangle (rolling)", color="#1f77b4", linewidth=1.6)
    ax.plot(bh["Date"], norm_bh, label="Buy & Hold underlying", color="#ff7f0e", linewidth=1.4, alpha=0.85)
    ax.set_title("Equity curve - strategy vs buy & hold")
    ax.set_ylabel("Equity (USD)")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "equity_curve.png", dpi=160)
    plt.close()


def plot_drawdown(equity: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    eq = equity.copy().sort_values("Date").reset_index(drop=True)
    cum = eq["equity"].cummax()
    dd = (eq["equity"] - cum) / cum
    fig, ax = plt.subplots(figsize=(11.5, 3.5))
    ax.fill_between(eq["Date"], dd * 100, 0, color="#d62728", alpha=0.55)
    ax.set_title("Strategy drawdown (%)")
    ax.set_ylabel("Drawdown (%)")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "drawdown.png", dpi=160)
    plt.close()


def plot_trade_pnl(trades: list[TradeRecord]) -> None:
    import matplotlib.pyplot as plt
    if not trades:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
    pnls = [t.pnl for t in trades]
    axes[0].hist(pnls, bins=25, color="#4c78a8", edgecolor="white")
    axes[0].axvline(0, color="#666", linewidth=0.8)
    axes[0].set_title(f"Trade P&L distribution (n={len(trades)})")
    axes[0].set_xlabel("P&L (USD)")
    cum_pnl = np.cumsum(pnls)
    axes[1].plot(range(1, len(pnls) + 1), cum_pnl, color="#1f77b4", linewidth=1.4)
    axes[1].axhline(0, color="#666", linewidth=0.7)
    axes[1].set_title("Cumulative trade P&L")
    axes[1].set_xlabel("Trade #")
    axes[1].set_ylabel("Cum. P&L (USD)")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "trade_pnl.png", dpi=160)
    plt.close()


def plot_greek_exposure(equity: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    eq = equity.copy().sort_values("Date").reset_index(drop=True)
    fig, axes = plt.subplots(4, 1, figsize=(11.5, 8.0), sharex=True)
    for ax, col, title, color in [
        (axes[0], "delta_exposure", "Delta exposure", "#1f77b4"),
        (axes[1], "gamma_exposure", "Gamma exposure", "#ff7f0e"),
        (axes[2], "vega_exposure", "Vega exposure", "#2ca02c"),
        (axes[3], "theta_exposure", "Theta exposure (per day)", "#d62728"),
    ]:
        ax.plot(eq["Date"], eq[col], color=color, linewidth=1.2)
        ax.axhline(0, color="#666", linewidth=0.6)
        ax.set_ylabel(title)
    axes[-1].set_xlabel("Date")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "greek_exposure.png", dpi=160)
    plt.close()


def plot_iv_rv_history(hist_with_rv: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    df = hist_with_rv.dropna(subset=["rv20"]).copy()
    fig, ax = plt.subplots(figsize=(11.5, 4.0))
    ax.plot(df["Date"], df["rv20"] * 100, label="RV20", color="#1f77b4", linewidth=1.2)
    ax.plot(df["Date"], (df["rv20"] * IV_RV_RATIO) * 100, label=f"IV (RV20 x {IV_RV_RATIO:.2f})", color="#ff7f0e", linewidth=1.2, alpha=0.8)
    ax.set_title("Realised vs implied volatility used by the simulator")
    ax.set_ylabel("Annualised volatility (%)")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "iv_rv_history.png", dpi=160)
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hist, source = load_underlying(TICKER)
    hist = hist.sort_values("Date").reset_index(drop=True)
    # restrict to lookback window
    hist = hist.tail(LOOKBACK_DAYS).reset_index(drop=True)

    enriched = add_realised_vol(hist)
    enriched.to_csv(DATA_DIR / f"{TICKER.lower()}_history_with_rv.csv", index=False, encoding="utf-8-sig")

    backtest = run_backtest(enriched)
    eq_df: pd.DataFrame = backtest["equity"]
    trades: list[TradeRecord] = backtest["trades"]
    sample_chains: list[pd.DataFrame] = backtest["sample_chains"]

    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([asdict(t) for t in trades]).to_csv(
        OUTPUT_DIR / "trades.csv", index=False, encoding="utf-8-sig"
    )

    stats = compute_stats(eq_df, trades, enriched)
    stats["ticker"] = TICKER
    stats["data_source"] = source
    stats["iv_rv_ratio"] = IV_RV_RATIO
    stats["entry_delta"] = ENTRY_DELTA
    stats["take_profit"] = TAKE_PROFIT
    stats["stop_loss"] = STOP_LOSS
    stats["roll_dte_target"] = ROLL_DTE_TARGET
    stats["managed_dte"] = MANAGED_DTE
    stats["start_date"] = str(eq_df["Date"].iloc[0].date())
    stats["end_date"] = str(eq_df["Date"].iloc[-1].date())
    (OUTPUT_DIR / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pd.DataFrame([stats]).to_csv(OUTPUT_DIR / "stats.csv", index=False, encoding="utf-8-sig")

    for i, df in enumerate(sample_chains):
        df.to_csv(OUTPUT_DIR / f"sample_chain_{i + 1}.csv", index=False, encoding="utf-8-sig")

    plot_equity(eq_df, hist)
    plot_drawdown(eq_df)
    plot_trade_pnl(trades)
    plot_greek_exposure(eq_df)
    plot_iv_rv_history(enriched)

    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    print("Outputs:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
