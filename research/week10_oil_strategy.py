"""
week10_oil_strategy.py
======================

Today's crude-oil-option (USO) trading strategy lab.

We construct and analyse four classical short-volatility / spread strategies
on the same expiry chain and compare them side by side:

  1. Short Straddle  - sell ATM call + sell ATM put
  2. Short Strangle  - sell OTM call + sell OTM put
  3. Iron Condor     - short OTM strangle + long further-OTM wings
  4. Calendar Spread - sell near-month ATM call + buy next-month same-strike call

For each strategy we report: legs, portfolio Greeks, expiry P&L curve,
risk metrics (max profit, max loss, breakevens), Monte Carlo POP and VaR.

The chain is loaded from data/week10/uso_chain.csv (produced by
week10_vix_calculator.py).  If unavailable, a synthetic chain is generated.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/week10"
OUTPUT_DIR = ROOT / "research/outputs/week10/homework"
RISK_FREE_RATE = 0.04
DIVIDEND_YIELD = 0.0
CONTRACT_MULTIPLIER = 100
RANDOM_SEED = 23300180062


@dataclass
class StrategyLeg:
    strategy: str
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


def bs_price(spot: float, k: float, t: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    if t <= 0:
        return max(spot - k, 0.0) if kind == "call" else max(k - spot, 0.0)
    sigma = max(sigma, 1e-6)
    d1 = (math.log(spot / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if kind == "call":
        return spot * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    return k * math.exp(-r * t) * norm.cdf(-d2) - spot * math.exp(-q * t) * norm.cdf(-d1)


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
        rho = k * t * dfr * norm.cdf(d2) * 0.01
    else:
        delta = -dfq * norm.cdf(-d1)
        theta = (
            -spot * dfq * nd1 * sigma / (2 * math.sqrt(t))
            + r * k * dfr * norm.cdf(-d2)
            - q * spot * dfq * norm.cdf(-d1)
        ) / 365
        rho = -k * t * dfr * norm.cdf(-d2) * 0.01
    return {
        "delta": delta,
        "gamma": dfq * nd1 / (spot * sigma * math.sqrt(t)),
        "vega": spot * dfq * nd1 * math.sqrt(t) * 0.01,
        "theta": theta,
        "rho": rho,
    }


def implied_vol_brent(price: float, spot: float, k: float, t: float, r: float, kind: str, q: float = 0.0) -> float | None:
    """Back-solve BS implied volatility for a given option price via Brent."""
    if price <= 0 or t <= 0:
        return None
    intrinsic = max(spot - k, 0.0) if kind == "call" else max(k - spot, 0.0)
    if price < intrinsic * 0.999:
        return None
    lo, hi = 1e-3, 5.0

    def diff(sigma: float) -> float:
        return bs_price(spot, k, t, r, sigma, kind, q) - price

    f_lo, f_hi = diff(lo), diff(hi)
    if f_lo * f_hi > 0:
        return None
    try:
        from scipy.optimize import brentq
        return float(brentq(diff, lo, hi, maxiter=80, xtol=1e-5))
    except Exception:
        return None


def _clean(chain: pd.DataFrame, spot: float | None = None) -> pd.DataFrame:
    df = chain.copy()
    for col in ["strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["mid"] = np.where(
        (df["bid"] > 0) & (df["ask"] > 0) & (df["ask"] >= df["bid"]),
        (df["bid"] + df["ask"]) / 2.0,
        df["lastPrice"],
    )
    df["mid"] = df["mid"].where(df["mid"] > 0, df["lastPrice"])
    df = df.dropna(subset=["strike", "mid"])
    df = df[df["mid"] > 0].copy()

    # Yahoo's per-strike IV is often badly stale (e.g. 6.25% for an OTM USO
    # call in a 75% OVX environment).  Always re-solve IV from mid price.
    if spot is None and not df.empty:
        spot = float(df.loc[df["strike"].sub(df["strike"].median()).abs().idxmin(), "strike"])
    today = pd.Timestamp(datetime.now().date())
    fixed_iv = []
    for _, row in df.iterrows():
        exp = pd.Timestamp(row["expiry"])
        t = max((exp - today).days, 1) / 365.0
        iv = implied_vol_brent(
            float(row["mid"]), float(spot), float(row["strike"]), t, RISK_FREE_RATE, str(row["option_type"])
        )
        if iv is None:
            # fallback to the Yahoo value if our solver fails, but only if it's
            # at least a plausible vol (≥10%)
            yh = float(row.get("impliedVolatility", 0.0) or 0.0)
            iv = yh if yh >= 0.10 else np.nan
        fixed_iv.append(iv)
    df["impliedVolatility"] = fixed_iv
    df = df.dropna(subset=["impliedVolatility"])
    df = df[df["impliedVolatility"] > 0]
    return df


def _spot_from_yfinance() -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker("USO").history(period="5d", interval="1d", auto_adjust=False)
        if not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


def load_chain() -> tuple[pd.DataFrame, float, str]:
    path = DATA_DIR / "uso_chain.csv"
    if path.exists():
        raw = pd.read_csv(path)
        spot = _spot_from_yfinance()
        chain = _clean(raw, spot)
        if not chain.empty:
            if spot is None:
                atm = chain.loc[chain["strike"].sub(chain["strike"].median()).abs().idxmin()]
                spot = float(atm["strike"])
            return chain, spot, "cached"
    # rebuild via VIX module
    from week10_vix_calculator import download_option_chain  # type: ignore
    raw, spot, source, _ = download_option_chain("USO")
    chain = _clean(raw, spot)
    chain.to_csv(path, index=False, encoding="utf-8-sig")
    return chain, spot, source


def pick_strike(chain: pd.DataFrame, target: float, kind: str, expiry: str, excluded: set) -> pd.Series:
    sub = chain[(chain["option_type"] == kind) & (chain["expiry"] == expiry) & (~chain["contractSymbol"].isin(excluded))].copy()
    if sub.empty:
        raise ValueError(f"no {kind} found for expiry {expiry}")
    sub["dist"] = (sub["strike"] - target).abs()
    liq = sub.get("openInterest", pd.Series(0, index=sub.index)).fillna(0) + sub.get(
        "volume", pd.Series(0, index=sub.index)
    ).fillna(0)
    sub["liq_rank"] = liq.rank(ascending=False, method="first")
    return sub.sort_values(["dist", "liq_rank"]).iloc[0]


def build_legs(chain: pd.DataFrame, spot: float, near_expiry: str, far_expiry: str, as_of: pd.Timestamp) -> dict:
    """Return dict[strategy_name] -> list[leg-dict].

    Strikes for strangle / iron condor are spaced by *sigma√T* so the structure
    scales sensibly across calm and turbulent IV regimes (e.g. SPX vs USO).
    """
    used: set = set()

    def leg(strategy: str, kind: str, target: float, qty: int, expiry: str) -> dict:
        row = pick_strike(chain, target, kind, expiry, used)
        used.add(str(row["contractSymbol"]))
        return {
            "strategy": strategy,
            "contract_symbol": str(row["contractSymbol"]),
            "option_type": kind,
            "strike": float(row["strike"]),
            "expiry": expiry,
            "quantity": int(qty),
            "mid": float(row["mid"]),
            "implied_volatility": float(row["impliedVolatility"]),
        }

    # Estimate ATM IV at the near expiry for sigma-scaled strike spacing
    near_chain = chain[chain["expiry"] == near_expiry]
    near_chain = near_chain.iloc[(near_chain["strike"] - spot).abs().argsort()[:10]]
    atm_iv = float(near_chain["impliedVolatility"].median())
    near_T_years = max((pd.Timestamp(near_expiry) - as_of).days, 1) / 365.0
    sigma_T = atm_iv * math.sqrt(near_T_years)
    # spacing multipliers
    strangle_w = 0.5 * sigma_T   # ~0.5σ OTM
    body_w = 1.0 * sigma_T       # body of condor at ~1σ
    wing_w = 1.6 * sigma_T       # wings of condor at ~1.6σ

    strategies: dict[str, list[dict]] = {}
    strategies["Short Straddle"] = [
        leg("Short Straddle", "call", spot, -1, near_expiry),
        leg("Short Straddle", "put", spot, -1, near_expiry),
    ]
    used.clear()
    strategies["Short Strangle"] = [
        leg("Short Strangle", "call", spot * (1 + strangle_w), -1, near_expiry),
        leg("Short Strangle", "put", spot * (1 - strangle_w), -1, near_expiry),
    ]
    used.clear()
    strategies["Iron Condor"] = [
        leg("Iron Condor", "put", spot * (1 - wing_w), 1, near_expiry),
        leg("Iron Condor", "put", spot * (1 - body_w), -1, near_expiry),
        leg("Iron Condor", "call", spot * (1 + body_w), -1, near_expiry),
        leg("Iron Condor", "call", spot * (1 + wing_w), 1, near_expiry),
    ]
    used.clear()
    strategies["Calendar Spread"] = [
        leg("Calendar Spread", "call", spot, -1, near_expiry),
        leg("Calendar Spread", "call", spot, 1, far_expiry),
    ]
    return strategies


def attach_greeks(legs: list[dict], spot: float, as_of: pd.Timestamp) -> list[StrategyLeg]:
    out = []
    for leg in legs:
        expiry = pd.Timestamp(leg["expiry"])
        t = max((expiry - as_of).days, 1) / 365.0
        greeks = bs_greeks(
            spot=spot,
            k=float(leg["strike"]),
            t=t,
            r=RISK_FREE_RATE,
            sigma=float(leg["implied_volatility"]),
            kind=str(leg["option_type"]),
            q=DIVIDEND_YIELD,
        )
        out.append(
            StrategyLeg(
                strategy=str(leg["strategy"]),
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


def portfolio_summary(legs: list[StrategyLeg]) -> dict:
    out = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0, "net_premium": 0.0}
    for leg in legs:
        out["delta"] += leg.quantity * leg.delta * CONTRACT_MULTIPLIER
        out["gamma"] += leg.quantity * leg.gamma * CONTRACT_MULTIPLIER
        out["vega"] += leg.quantity * leg.vega * CONTRACT_MULTIPLIER
        out["theta"] += leg.quantity * leg.theta * CONTRACT_MULTIPLIER
        out["rho"] += leg.quantity * leg.rho * CONTRACT_MULTIPLIER
        out["net_premium"] += leg.quantity * leg.mid * CONTRACT_MULTIPLIER
    return out


def expiry_payoff(legs: list[StrategyLeg], spots: np.ndarray, as_of: pd.Timestamp) -> pd.DataFrame:
    """For calendar spread we must use BS to price the far-leg at near-expiry."""
    near_expiries = sorted(set(pd.Timestamp(l.expiry) for l in legs))
    near_T = min(near_expiries)
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)
    rows = []
    for s in spots:
        value = 0.0
        for leg in legs:
            expiry_dt = pd.Timestamp(leg.expiry)
            if expiry_dt == near_T:
                if leg.option_type == "call":
                    payoff = max(s - leg.strike, 0.0)
                else:
                    payoff = max(leg.strike - s, 0.0)
                value += leg.quantity * payoff * CONTRACT_MULTIPLIER
            else:
                t_remain = max((expiry_dt - near_T).days, 1) / 365.0
                price = bs_price(s, leg.strike, t_remain, RISK_FREE_RATE, leg.implied_volatility, leg.option_type)
                value += leg.quantity * price * CONTRACT_MULTIPLIER
        rows.append({"spot_at_near_expiry": s, "strategy_value": value, "pnl": value - initial_value})
    return pd.DataFrame(rows)


def find_breakevens(payoff: pd.DataFrame) -> list[float]:
    sign = np.sign(payoff["pnl"])
    out = []
    for i in range(1, len(payoff)):
        if sign.iloc[i] == 0:
            out.append(float(payoff["spot_at_near_expiry"].iloc[i]))
        elif sign.iloc[i] != sign.iloc[i - 1]:
            x0, y0 = payoff["spot_at_near_expiry"].iloc[i - 1], payoff["pnl"].iloc[i - 1]
            x1, y1 = payoff["spot_at_near_expiry"].iloc[i], payoff["pnl"].iloc[i]
            out.append(float(x0 - y0 * (x1 - x0) / (y1 - y0)))
    return out


def monte_carlo(
    legs: list[StrategyLeg], spot: float, as_of: pd.Timestamp, n_paths: int = 20000, seed: int = RANDOM_SEED
) -> dict:
    """Risk-neutral GBM Monte Carlo to near expiry."""
    rng = np.random.default_rng(seed)
    near_T_date = min(pd.Timestamp(l.expiry) for l in legs)
    t = max((near_T_date - as_of).days, 1) / 365.0
    sigma = max(np.mean([l.implied_volatility for l in legs]), 0.05)
    drift = RISK_FREE_RATE - DIVIDEND_YIELD
    z = rng.standard_normal(n_paths)
    spot_t = spot * np.exp((drift - 0.5 * sigma * sigma) * t + sigma * math.sqrt(t) * z)
    initial_value = sum(leg.quantity * leg.mid * CONTRACT_MULTIPLIER for leg in legs)
    pnl = np.zeros(n_paths)
    for leg in legs:
        expiry_dt = pd.Timestamp(leg.expiry)
        if expiry_dt == near_T_date:
            if leg.option_type == "call":
                p = np.maximum(spot_t - leg.strike, 0.0)
            else:
                p = np.maximum(leg.strike - spot_t, 0.0)
            pnl += leg.quantity * p * CONTRACT_MULTIPLIER
        else:
            t_rem = max((expiry_dt - near_T_date).days, 1) / 365.0
            prices = np.array(
                [bs_price(float(s), leg.strike, t_rem, RISK_FREE_RATE, leg.implied_volatility, leg.option_type) for s in spot_t]
            )
            pnl += leg.quantity * prices * CONTRACT_MULTIPLIER
    pnl = pnl - initial_value
    sorted_pnl = np.sort(pnl)
    n = len(pnl)
    return {
        "n_paths": int(n_paths),
        "sigma_used": float(sigma),
        "drift_used": float(drift),
        "horizon_years": float(t),
        "prob_of_profit": float((pnl > 0).mean()),
        "expected_pnl": float(pnl.mean()),
        "median_pnl": float(np.median(pnl)),
        "std_pnl": float(pnl.std(ddof=1)),
        "min_pnl": float(pnl.min()),
        "max_pnl": float(pnl.max()),
        "var_95": float(-np.quantile(pnl, 0.05)),
        "var_99": float(-np.quantile(pnl, 0.01)),
        "cvar_95": float(-sorted_pnl[: max(int(0.05 * n), 1)].mean()),
        "cvar_99": float(-sorted_pnl[: max(int(0.01 * n), 1)].mean()),
    }


def make_strategy_panel(payoffs: dict[str, pd.DataFrame], spot: float) -> None:
    import matplotlib.pyplot as plt
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.5))
    for ax, (name, df) in zip(axes.flat, payoffs.items()):
        ax.plot(df["spot_at_near_expiry"], df["pnl"], color="#1f77b4", linewidth=1.7)
        ax.axhline(0, color="#666", linewidth=0.8)
        ax.axvline(spot, color="#d62728", linewidth=0.8, linestyle="--", label=f"spot={spot:.1f}")
        ax.set_title(name)
        ax.set_xlabel("USO at near-expiry")
        ax.set_ylabel("P&L (USD)")
        ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "oil_strategy_payoffs.png", dpi=160)
    plt.close()


def make_greeks_bar(summary_rows: list[dict]) -> None:
    import matplotlib.pyplot as plt
    plt.style.use("seaborn-v0_8-whitegrid")
    df = pd.DataFrame(summary_rows)
    metrics = ["delta", "gamma", "vega", "theta"]
    fig, axes = plt.subplots(1, 4, figsize=(13.5, 4.3))
    for ax, m in zip(axes, metrics):
        ax.bar(df["strategy"], df[m], color=["#4c78a8", "#f28e2b", "#54a24b", "#e45756"])
        ax.axhline(0, color="#666", linewidth=0.7)
        ax.set_title(f"Portfolio {m.title()}")
        ax.tick_params(axis="x", rotation=30)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "oil_strategy_greeks.png", dpi=160)
    plt.close()


def make_mc_bar(rows: list[dict]) -> None:
    import matplotlib.pyplot as plt
    df = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.3))
    colors = ["#4c78a8", "#f28e2b", "#54a24b", "#e45756"]
    for ax, col, title in zip(axes, ["prob_of_profit", "expected_pnl", "var_95"], ["POP", "Expected P&L", "VaR 95%"]):
        ax.bar(df["strategy"], df[col], color=colors)
        ax.axhline(0, color="#666", linewidth=0.7)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=25)
        if col == "prob_of_profit":
            ax.set_ylim(0, 1.0)
            ax.set_ylabel("Probability")
        else:
            ax.set_ylabel("USD")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "oil_strategy_mc.png", dpi=160)
    plt.close()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    chain, spot, source = load_chain()
    as_of = pd.Timestamp(datetime.now().date())
    expiries = sorted(chain["expiry"].unique().tolist())
    # near = closest to 30 DTE, far = closest to 60 DTE
    dte = {e: (pd.Timestamp(e) - as_of).days for e in expiries}
    valid = [e for e, d in dte.items() if d >= 14]
    if len(valid) < 2:
        valid = expiries
    near = min(valid, key=lambda e: abs(dte[e] - 30))
    far_candidates = [e for e in valid if dte[e] > dte[near] + 14]
    far = min(far_candidates, key=lambda e: abs(dte[e] - 60)) if far_candidates else valid[-1]
    print(f"Near expiry: {near} (DTE={dte[near]}), Far expiry: {far} (DTE={dte[far]})")

    raw = build_legs(chain, spot, near, far, as_of)

    all_legs: list[StrategyLeg] = []
    strategy_summary_rows = []
    payoffs: dict[str, pd.DataFrame] = {}
    mc_rows: list[dict] = []
    s_grid = np.linspace(spot * 0.55, spot * 1.45, 361)
    for name, leg_list in raw.items():
        legs = attach_greeks(leg_list, spot, as_of)
        all_legs.extend(legs)
        port = portfolio_summary(legs)
        payoff = expiry_payoff(legs, s_grid, as_of)
        payoffs[name] = payoff
        mc = monte_carlo(legs, spot, as_of)
        mc_rows.append({"strategy": name, **mc})
        breakevens = find_breakevens(payoff)
        max_profit = float(payoff["pnl"].max())
        max_loss = float(payoff["pnl"].min())
        strategy_summary_rows.append(
            {
                "strategy": name,
                "net_premium": port["net_premium"],
                "delta": port["delta"],
                "gamma": port["gamma"],
                "vega": port["vega"],
                "theta": port["theta"],
                "rho": port["rho"],
                "max_profit": max_profit,
                "max_loss": max_loss,
                "breakevens": json.dumps([round(x, 2) for x in breakevens]),
                "prob_of_profit": mc["prob_of_profit"],
                "expected_pnl": mc["expected_pnl"],
                "var_95": mc["var_95"],
                "cvar_95": mc["cvar_95"],
                "near_expiry": near,
                "far_expiry": far if name == "Calendar Spread" else "",
            }
        )

    pd.DataFrame([asdict(l) for l in all_legs]).to_csv(
        OUTPUT_DIR / "oil_strategy_legs.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(strategy_summary_rows).to_csv(
        OUTPUT_DIR / "oil_strategy_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(mc_rows).to_csv(OUTPUT_DIR / "oil_strategy_mc.csv", index=False, encoding="utf-8-sig")
    for name, df in payoffs.items():
        slug = name.lower().replace(" ", "_")
        df.to_csv(OUTPUT_DIR / f"oil_payoff_{slug}.csv", index=False, encoding="utf-8-sig")

    make_strategy_panel(payoffs, spot)
    make_greeks_bar(strategy_summary_rows)
    make_mc_bar(mc_rows)

    meta = {
        "ticker": "USO",
        "data_source": source,
        "spot": spot,
        "as_of": str(as_of.date()),
        "near_expiry": near,
        "near_dte": dte[near],
        "far_expiry": far,
        "far_dte": dte[far],
    }
    (OUTPUT_DIR / "oil_strategy_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(pd.DataFrame(strategy_summary_rows).to_string(index=False))
    print("Outputs:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
