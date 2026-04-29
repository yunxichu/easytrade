"""
prepare_historical_percentiles.py
=================================
Fetch longer Yahoo Finance history for historical percentile context.

The public minute futures-option sample only covers one trading day. That is
enough for IV, Greeks, and minute price attribution, but it is not enough for
a true historical percentile. This script adds a more defensible proxy:

- RV historical percentile: ES=F daily close returns from Yahoo Finance.
- IV historical percentile proxy: CBOE VIX daily close from Yahoo Finance.

The sample date is 2020-01-06, so the percentile is computed using data up to
that date only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/processed"
OUT_DIR = ROOT / "research/outputs/es_options"
START = "2015-01-01"
END = "2020-01-07"
SAMPLE_DATE = "2020-01-06"


def fetch_series(symbol: str) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(start=START, end=END, interval="1d")
    if df.empty:
        raise RuntimeError(f"Yahoo Finance returned no data for {symbol}")
    out = df.reset_index()
    out["symbol"] = symbol
    return out[["Date", "symbol", "Open", "High", "Low", "Close", "Volume"]]


def percentile(series: pd.Series, value: float) -> float:
    clean = series.dropna()
    return float((clean <= value).mean())


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    es = fetch_series("ES=F")
    vix = fetch_series("^VIX")
    history = pd.concat([es, vix], ignore_index=True)
    history.to_csv(DATA_DIR / "yahoo_es_vix_history_2015_2020.csv", index=False, encoding="utf-8-sig")

    es_close = es.set_index("Date")["Close"]
    ret = np.log(es_close).diff()
    rv20 = ret.rolling(20).std() * math.sqrt(252)
    rv60 = ret.rolling(60).std() * math.sqrt(252)
    rv20_latest = float(rv20.dropna().iloc[-1])
    rv60_latest = float(rv60.dropna().iloc[-1])

    vix_close = vix.set_index("Date")["Close"] / 100.0
    vix_latest = float(vix_close.dropna().iloc[-1])

    summary = {
        "sample_date": SAMPLE_DATE,
        "rv_source": "Yahoo Finance ES=F daily close, 2015-01-01 to 2020-01-06",
        "iv_proxy_source": "Yahoo Finance ^VIX daily close, 2015-01-01 to 2020-01-06",
        "rv20": rv20_latest,
        "rv20_percentile": percentile(rv20, rv20_latest),
        "rv60": rv60_latest,
        "rv60_percentile": percentile(rv60, rv60_latest),
        "vix_iv_proxy": vix_latest,
        "vix_iv_proxy_percentile": percentile(vix_close, vix_latest),
    }
    (OUT_DIR / "historical_percentiles.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame([summary]).to_csv(OUT_DIR / "historical_percentiles.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
