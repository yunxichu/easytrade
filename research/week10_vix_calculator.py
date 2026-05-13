"""
week10_vix_calculator.py
========================

CBOE VIX-style 30-day implied volatility index calculation, applied to:

  1. SPY (proxy for SPX, comparable to the published CBOE VIX ^VIX index)
  2. USO (proxy for WTI crude oil, comparable to CBOE OVX index ^OVX)

The implementation follows the CBOE VIX White Paper (2019 revision):

  σ²(T) = (2/T) · Σ_i [ΔK_i / K_i²] · e^{R·T} · Q(K_i)  −  (1/T) · (F/K_0 − 1)²

  VIX = 100 · sqrt[ (T_1·σ_1² · w_1 + T_2·σ_2² · w_2) · (N_365 / N_30) ]

where  w_1 = (N_T2 − N_30)/(N_T2 − N_T1),  w_2 = (N_30 − N_T1)/(N_T2 − N_T1).

Key implementation notes:
  - We use trading-minute time (CBOE convention).
  - We use bid/ask midpoint as Q(K_i), and skip strikes once we hit two
    consecutive zero-bid contracts (CBOE stopping rule).
  - Forward F is derived from the put-call parity strike K* with smallest
    |C-P|: F = K* + e^{R·T} (C(K*) - P(K*)).
  - K_0 = largest strike strictly less than F.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/week10"
OUTPUT_DIR = ROOT / "research/outputs/week10/homework"
RISK_FREE_RATE = 0.04
MINUTES_IN_YEAR = 525600  # 365 * 1440
MINUTES_IN_30_DAYS = 43200
RANDOM_SEED = 23300180062


@dataclass
class VIXResult:
    ticker: str
    as_of: str
    near_expiry: str
    next_expiry: str
    near_dte: float
    next_dte: float
    near_sigma2: float
    next_sigma2: float
    near_forward: float
    next_forward: float
    near_k0: float
    next_k0: float
    near_num_strikes: int
    next_num_strikes: int
    vix: float


def _minutes_to_settlement(now: datetime, settlement_day: pd.Timestamp) -> float:
    """Minutes between *now* and SPX-style settlement (8:30am ET on settlement day).

    For our purposes we approximate with the day boundary at 09:30 NY time on
    the settlement date.  The exact minute count does not materially affect the
    VIX magnitude for educational purposes.
    """
    settle_dt = datetime.combine(settlement_day.date(), time(9, 30))
    delta = settle_dt - now
    return max(delta.total_seconds() / 60.0, 1.0)


def _build_quote_chain(chain_df: pd.DataFrame) -> pd.DataFrame:
    """Convert long-format option chain into wide [strike, call_mid, put_mid].

    When bid/ask are unavailable (e.g. market closed in Yahoo data), fall back
    to lastPrice.  We carry a *quote* column that mirrors the price used for
    the stopping-rule check.
    """
    chain = chain_df.copy()
    chain["mid"] = np.where(
        (chain["bid"] > 0) & (chain["ask"] > 0) & (chain["ask"] >= chain["bid"]),
        (chain["bid"] + chain["ask"]) / 2.0,
        chain["lastPrice"],
    )
    # If everything is still zero (Yahoo glitch), fall back to lastPrice.
    chain["mid"] = chain["mid"].where(chain["mid"] > 0, chain["lastPrice"])
    chain["quote"] = chain["bid"].where(chain["bid"] > 0, chain["lastPrice"])

    def pivot(col: str, side: str, alias: str) -> pd.Series:
        return chain[chain["option_type"] == side].set_index("strike")[col].rename(alias)

    df = pd.concat(
        [
            pivot("mid", "call", "call_mid"),
            pivot("mid", "put", "put_mid"),
            pivot("quote", "call", "call_quote"),
            pivot("quote", "put", "put_quote"),
        ],
        axis=1,
    ).dropna(subset=["call_mid", "put_mid"])
    return df.sort_index().reset_index().rename(columns={"index": "strike"})


def _select_otm_strikes(wide: pd.DataFrame, forward: float, k0: float) -> pd.DataFrame:
    """Apply CBOE OTM selection + two-consecutive-zero-quote stopping rule.

    Yahoo's snapshot occasionally reports zero bid/ask while last-traded prices
    are non-zero; we therefore use *quote = bid OR lastPrice* as the stopping
    signal so the rule still meaningfully truncates the far wings.
    """
    selected_rows = []

    # Puts: strikes < K0, walk downward
    puts = wide[wide["strike"] < k0].sort_values("strike", ascending=False)
    consec_zero = 0
    for _, row in puts.iterrows():
        q = row.get("put_quote", row.get("put_mid", 0.0))
        if q is None or pd.isna(q) or q <= 0:
            consec_zero += 1
            if consec_zero >= 2:
                break
            continue
        consec_zero = 0
        selected_rows.append({"strike": row["strike"], "Q": row["put_mid"], "side": "put"})

    # K0 row: average of call and put mids
    k0_row = wide[wide["strike"] == k0]
    if not k0_row.empty:
        r = k0_row.iloc[0]
        selected_rows.append({"strike": k0, "Q": (r["call_mid"] + r["put_mid"]) / 2.0, "side": "atm"})

    # Calls: strikes > K0, walk upward
    calls = wide[wide["strike"] > k0].sort_values("strike", ascending=True)
    consec_zero = 0
    for _, row in calls.iterrows():
        q = row.get("call_quote", row.get("call_mid", 0.0))
        if q is None or pd.isna(q) or q <= 0:
            consec_zero += 1
            if consec_zero >= 2:
                break
            continue
        consec_zero = 0
        selected_rows.append({"strike": row["strike"], "Q": row["call_mid"], "side": "call"})

    sub = pd.DataFrame(selected_rows).sort_values("strike").reset_index(drop=True)
    # Compute ΔK
    strikes = sub["strike"].values
    dk = np.zeros_like(strikes, dtype=float)
    for i in range(len(strikes)):
        if i == 0:
            dk[i] = strikes[i + 1] - strikes[i] if len(strikes) > 1 else 1.0
        elif i == len(strikes) - 1:
            dk[i] = strikes[i] - strikes[i - 1]
        else:
            dk[i] = (strikes[i + 1] - strikes[i - 1]) / 2.0
    sub["delta_K"] = dk
    return sub


def compute_single_expiry_sigma2(
    chain_df: pd.DataFrame, expiry: pd.Timestamp, as_of: datetime, rate: float
) -> tuple[float, dict]:
    """Compute σ² for a single expiry using CBOE methodology."""
    wide = _build_quote_chain(chain_df)
    if wide.empty:
        raise ValueError("Empty option chain after cleaning.")

    minutes = _minutes_to_settlement(as_of, expiry)
    t_years = minutes / MINUTES_IN_YEAR

    # Forward via put-call parity at minimum |C-P|
    diff = (wide["call_mid"] - wide["put_mid"]).abs()
    k_star_idx = diff.idxmin()
    k_star = float(wide.loc[k_star_idx, "strike"])
    c_minus_p = float(wide.loc[k_star_idx, "call_mid"] - wide.loc[k_star_idx, "put_mid"])
    forward = k_star + math.exp(rate * t_years) * c_minus_p

    # K0 = largest strike < forward
    less = wide[wide["strike"] < forward]
    if less.empty:
        k0 = float(wide["strike"].iloc[0])
    else:
        k0 = float(less["strike"].iloc[-1])

    selected = _select_otm_strikes(wide, forward, k0)
    if selected.empty:
        raise ValueError("No OTM strikes survived CBOE selection.")

    er = math.exp(rate * t_years)
    contrib = (selected["delta_K"] / (selected["strike"] ** 2)) * er * selected["Q"]
    sigma2 = (2.0 / t_years) * contrib.sum() - (1.0 / t_years) * (forward / k0 - 1.0) ** 2

    detail = {
        "minutes": minutes,
        "t_years": t_years,
        "forward": forward,
        "k_star": k_star,
        "k0": k0,
        "num_strikes": int(len(selected)),
        "selected": selected,
        "contrib_sum": float(contrib.sum()),
    }
    return float(sigma2), detail


def compute_vix(
    chain_df: pd.DataFrame,
    expiries: list[pd.Timestamp],
    as_of: datetime,
    rate: float = RISK_FREE_RATE,
) -> tuple[float, dict]:
    """Compute the 30-day VIX from two nearest expirations bracketing 30 days."""
    today = pd.Timestamp(as_of.date())
    dte_pairs = [(exp, (pd.Timestamp(exp) - today).days) for exp in expiries]
    near_pool = [pair for pair in dte_pairs if pair[1] >= 7 and pair[1] <= 30]
    next_pool = [pair for pair in dte_pairs if pair[1] > 30 and pair[1] <= 60]
    if not near_pool:
        near_pool = [pair for pair in dte_pairs if pair[1] >= 7]
        near_pool.sort(key=lambda x: x[1])
        near_pool = near_pool[:1]
    if not next_pool:
        next_pool = [pair for pair in dte_pairs if pair[1] > (near_pool[0][1] if near_pool else 0)]
        next_pool.sort(key=lambda x: x[1])
        next_pool = next_pool[:1]
    if not near_pool or not next_pool:
        raise ValueError("Not enough expirations to compute VIX.")
    near_exp = near_pool[-1][0]
    next_exp = next_pool[0][0]

    near_chain = chain_df[chain_df["expiry"] == str(pd.Timestamp(near_exp).date())]
    next_chain = chain_df[chain_df["expiry"] == str(pd.Timestamp(next_exp).date())]
    if near_chain.empty or next_chain.empty:
        raise ValueError("Selected expiries have empty chains.")

    s1, d1 = compute_single_expiry_sigma2(near_chain, pd.Timestamp(near_exp), as_of, rate)
    s2, d2 = compute_single_expiry_sigma2(next_chain, pd.Timestamp(next_exp), as_of, rate)

    nt1, nt2 = d1["minutes"], d2["minutes"]
    n30, n365 = float(MINUTES_IN_30_DAYS), float(MINUTES_IN_YEAR)
    w1 = (nt2 - n30) / (nt2 - nt1) if nt2 != nt1 else 0.5
    w2 = (n30 - nt1) / (nt2 - nt1) if nt2 != nt1 else 0.5
    inner = d1["t_years"] * s1 * w1 + d2["t_years"] * s2 * w2
    vix = 100.0 * math.sqrt(max(inner, 0.0) * (n365 / n30))

    detail = {
        "near": {"expiry": str(pd.Timestamp(near_exp).date()), **{k: v for k, v in d1.items() if k != "selected"}, "sigma2": s1},
        "next": {"expiry": str(pd.Timestamp(next_exp).date()), **{k: v for k, v in d2.items() if k != "selected"}, "sigma2": s2},
        "w_near": w1,
        "w_next": w2,
        "vix": vix,
        "near_selected": d1["selected"],
        "next_selected": d2["selected"],
    }
    return vix, detail


def _synth_chain(ticker: str, spot: float, vol_level: float, expiry_dtes: list[int], seed: int) -> tuple[pd.DataFrame, str]:
    """Deterministic synthetic chain when yfinance is unavailable."""
    from scipy.stats import norm
    rng = np.random.default_rng(seed)
    rows = []
    today = pd.Timestamp(datetime.now().date())
    for dte in expiry_dtes:
        exp_date = (today + pd.Timedelta(days=dte)).date()
        t = dte / 365.0
        strikes = np.arange(
            round(spot * 0.70 / 1) * 1, round(spot * 1.31 / 1) * 1 + 1, max(0.5, round(spot * 0.01, 1))
        )
        for opt_type in ["call", "put"]:
            for k in strikes:
                # IV smile: parabolic in log-moneyness
                m = math.log(k / spot)
                iv = vol_level * (1 + 4.0 * m * m) + 0.02 * (1 if opt_type == "put" else -1) * m
                iv = max(0.05, iv)
                d1 = (math.log(spot / k) + (RISK_FREE_RATE + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
                d2 = d1 - iv * math.sqrt(t)
                if opt_type == "call":
                    price = spot * norm.cdf(d1) - k * math.exp(-RISK_FREE_RATE * t) * norm.cdf(d2)
                else:
                    price = k * math.exp(-RISK_FREE_RATE * t) * norm.cdf(-d2) - spot * norm.cdf(-d1)
                price = max(price, 0.02)
                spread = max(0.02, price * 0.02)
                rows.append(
                    {
                        "contractSymbol": f"SYN{ticker}{str(exp_date).replace('-', '')}{opt_type[0].upper()}{int(k * 1000)}",
                        "strike": float(k),
                        "lastPrice": price,
                        "bid": max(0.01, price - spread / 2),
                        "ask": price + spread / 2,
                        "volume": int(rng.integers(50, 5000)),
                        "openInterest": int(rng.integers(500, 30000)),
                        "impliedVolatility": iv,
                        "option_type": opt_type,
                        "expiry": str(exp_date),
                    }
                )
    return pd.DataFrame(rows), "synthetic_fallback"


def download_option_chain(ticker: str) -> tuple[pd.DataFrame, float, str, datetime]:
    """Return (chain_df, spot, source, as_of_dt)."""
    try:
        import yfinance as yf
        tkr = yf.Ticker(ticker)
        hist = tkr.history(period="5d", interval="1d", auto_adjust=False)
        if hist.empty:
            raise RuntimeError("empty history")
        spot = float(hist["Close"].iloc[-1])
        expiries = list(tkr.options)
        today = pd.Timestamp.utcnow().tz_localize(None).normalize()
        keep = [e for e in expiries if 14 <= (pd.Timestamp(e) - today).days <= 90]
        if len(keep) < 2:
            keep = expiries[:8]
        frames = []
        for exp in keep[:8]:
            ch = tkr.option_chain(exp)
            for kind, df in [("call", ch.calls), ("put", ch.puts)]:
                d = df.copy()
                d["option_type"] = kind
                d["expiry"] = exp
                frames.append(d)
        chain = pd.concat(frames, ignore_index=True)
        for col in ["strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"]:
            if col in chain.columns:
                chain[col] = pd.to_numeric(chain[col], errors="coerce")
        chain = chain.dropna(subset=["strike", "lastPrice"]).reset_index(drop=True)
        as_of = datetime.utcnow().replace(microsecond=0)
        return chain, spot, "yfinance", as_of
    except Exception as exc:
        print(f"[{ticker}] yfinance failed ({exc}), using synthetic chain")
        defaults = {"SPY": (530.0, 0.16), "USO": (75.0, 0.32), "QQQ": (470.0, 0.20)}
        spot, vol = defaults.get(ticker, (100.0, 0.30))
        chain, source = _synth_chain(ticker, spot, vol, [14, 21, 28, 35, 49, 63], RANDOM_SEED + hash(ticker) % 1000)
        return chain, spot, source, datetime.utcnow().replace(microsecond=0)


def fetch_reference_vix(symbol: str = "^VIX") -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        if h.empty:
            return None
        return float(h["Close"].iloc[-1])
    except Exception:
        return None


def run_vix_for_ticker(ticker: str, out_prefix: str) -> dict:
    chain, spot, source, as_of = download_option_chain(ticker)
    expiries = sorted(chain["expiry"].unique().tolist())
    vix, detail = compute_vix(chain, expiries, as_of)
    chain.to_csv(DATA_DIR / f"{ticker.lower()}_chain.csv", index=False, encoding="utf-8-sig")
    detail["near_selected"].to_csv(OUTPUT_DIR / f"{out_prefix}_vix_near_strikes.csv", index=False, encoding="utf-8-sig")
    detail["next_selected"].to_csv(OUTPUT_DIR / f"{out_prefix}_vix_next_strikes.csv", index=False, encoding="utf-8-sig")
    summary = {
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "spot": spot,
        "data_source": source,
        "computed_vix": vix,
        "near_expiry": detail["near"]["expiry"],
        "near_dte_minutes": detail["near"]["minutes"],
        "near_t_years": detail["near"]["t_years"],
        "near_forward": detail["near"]["forward"],
        "near_k0": detail["near"]["k0"],
        "near_sigma2": detail["near"]["sigma2"],
        "near_num_strikes": detail["near"]["num_strikes"],
        "next_expiry": detail["next"]["expiry"],
        "next_dte_minutes": detail["next"]["minutes"],
        "next_t_years": detail["next"]["t_years"],
        "next_forward": detail["next"]["forward"],
        "next_k0": detail["next"]["k0"],
        "next_sigma2": detail["next"]["sigma2"],
        "next_num_strikes": detail["next"]["num_strikes"],
        "w_near": detail["w_near"],
        "w_next": detail["w_next"],
    }
    return summary


def make_comparison_plot(rows: list[dict]) -> None:
    import matplotlib.pyplot as plt
    plt.style.use("seaborn-v0_8-whitegrid")
    labels = [r["label"] for r in rows]
    computed = [r["computed_vix"] for r in rows]
    reference = [r.get("reference") for r in rows]
    x = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.bar(x - width / 2, computed, width, label="Our replication", color="#4c78a8")
    ref_y = [r if r is not None else 0 for r in reference]
    ax.bar(x + width / 2, ref_y, width, label="CBOE official", color="#f28e2b")
    for i, v in enumerate(computed):
        ax.text(i - width / 2, v + 0.4, f"{v:.2f}", ha="center", fontsize=9)
    for i, v in enumerate(reference):
        if v is not None:
            ax.text(i + width / 2, v + 0.4, f"{v:.2f}", ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("VIX (%)")
    ax.set_title("CBOE VIX methodology - replicated vs reference index")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "vix_compare.png", dpi=160)
    plt.close()


def make_strike_contribution_plot(summary: dict, ticker: str) -> None:
    import matplotlib.pyplot as plt
    near = pd.read_csv(OUTPUT_DIR / f"{ticker.lower()}_vix_near_strikes.csv")
    nxt = pd.read_csv(OUTPUT_DIR / f"{ticker.lower()}_vix_next_strikes.csv")
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.4))
    for axis, df, title in [
        (ax[0], near, f"{ticker} near-term  K0={summary['near_k0']:.0f}  F={summary['near_forward']:.0f}"),
        (ax[1], nxt, f"{ticker} next-term  K0={summary['next_k0']:.0f}  F={summary['next_forward']:.0f}"),
    ]:
        contrib = df["delta_K"] * df["Q"] / (df["strike"] ** 2)
        axis.bar(df["strike"], contrib, color="#4c78a8", width=(df["strike"].diff().median() or 1.0) * 0.7)
        axis.set_title(title)
        axis.set_xlabel("Strike")
        axis.set_ylabel("contribution to σ²")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / f"{ticker.lower()}_vix_contrib.png", dpi=160)
    plt.close()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    spy_summary = run_vix_for_ticker("SPY", "spy")
    uso_summary = run_vix_for_ticker("USO", "uso")
    spy_summary["reference_label"] = "^VIX (CBOE 30-day SPX IV)"
    uso_summary["reference_label"] = "^OVX (CBOE 30-day crude IV)"
    spy_summary["reference_vix"] = fetch_reference_vix("^VIX")
    uso_summary["reference_vix"] = fetch_reference_vix("^OVX")

    summary_rows = []
    for s in [spy_summary, uso_summary]:
        summary_rows.append(
            {
                "ticker": s["ticker"],
                "as_of": s["as_of"],
                "spot": s["spot"],
                "computed_vix": s["computed_vix"],
                "reference_index": s["reference_label"],
                "reference_value": s["reference_vix"],
                "near_expiry": s["near_expiry"],
                "next_expiry": s["next_expiry"],
                "near_sigma2": s["near_sigma2"],
                "next_sigma2": s["next_sigma2"],
                "near_forward": s["near_forward"],
                "near_k0": s["near_k0"],
                "next_forward": s["next_forward"],
                "next_k0": s["next_k0"],
                "near_num_strikes": s["near_num_strikes"],
                "next_num_strikes": s["next_num_strikes"],
            }
        )
    pd.DataFrame(summary_rows).to_csv(OUTPUT_DIR / "vix_summary.csv", index=False, encoding="utf-8-sig")
    (OUTPUT_DIR / "vix_summary.json").write_text(
        json.dumps(summary_rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    make_comparison_plot(
        [
            {"label": "SPY → VIX", "computed_vix": spy_summary["computed_vix"], "reference": spy_summary["reference_vix"]},
            {"label": "USO → OVX", "computed_vix": uso_summary["computed_vix"], "reference": uso_summary["reference_vix"]},
        ]
    )
    make_strike_contribution_plot(spy_summary, "SPY")
    make_strike_contribution_plot(uso_summary, "USO")

    print(json.dumps(summary_rows, ensure_ascii=False, indent=2, default=str))
    print("Outputs:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
