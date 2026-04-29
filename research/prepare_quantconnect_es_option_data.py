"""
prepare_quantconnect_es_option_data.py
=====================================
Download and convert cleaner public minute data from QuantConnect/LEAN.

This dataset uses E-mini S&P 500 futures (ES) and ES futures options from
2020-01-06. The sample is much cleaner than the tiny COMEX gold option sample:
selected option contracts have more than 1,200 one-minute quote rows and tight
median bid-ask spreads.

Source repository:
https://github.com/QuantConnect/Lean

Run:
    python research/prepare_quantconnect_es_option_data.py
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd


RAW_DIR = Path("data/quantconnect_raw/es")
PROCESSED_DIR = Path("data/processed")
RAW_BASE = "https://raw.githubusercontent.com/QuantConnect/Lean/master/"

FILES = {
    "es_future_quote": "Data/future/cme/minute/es/20200106_quote.zip",
    "es_option_quote": "Data/futureoption/cme/minute/es/202003/20200106_quote_american.zip",
}

SELECTED_OPTIONS = {
    ("call", 3200.0),
    ("call", 3250.0),
    ("put", 3200.0),
    ("put", 3250.0),
}


def download_file(relative_path: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return
    with urllib.request.urlopen(RAW_BASE + relative_path, timeout=60) as response:
        output_path.write_bytes(response.read())


def ensure_raw_files() -> dict[str, Path]:
    paths = {}
    for key, relative in FILES.items():
        prefix = "future" if "/future/" in relative else "option"
        output_path = RAW_DIR / f"{prefix}_{Path(relative).name}"
        download_file(relative, output_path)
        paths[key] = output_path
    return paths


def milliseconds_to_timestamp(trading_date: str, value: int | float | str) -> pd.Timestamp:
    return pd.Timestamp(trading_date) + pd.to_timedelta(int(value), unit="ms")


def read_entry(zip_path: Path, entry_name: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        content = zf.read(entry_name).decode("utf-8")
    return pd.read_csv(io.StringIO(content), header=None)


def standard_quote_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [
        "ms",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "bid_size",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
        "ask_size",
    ]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def parse_future_quote(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        entries = [name for name in zf.namelist() if name.endswith("_202003.csv")]
        entry = entries[0]
    match = re.match(r"(?P<date>\d{8})_es_minute_quote_(?P<expiry>\d{6})\.csv", entry)
    if not match:
        raise ValueError(f"Unexpected futures quote entry: {entry}")
    df = standard_quote_columns(read_entry(zip_path, entry))
    df["timestamp"] = df["ms"].map(lambda x: milliseconds_to_timestamp(match.group("date"), x))
    df["futures_price"] = (df["bid_close"] + df["ask_close"]) / 2.0
    df["futures_symbol"] = "ES" + match.group("expiry")
    return df[["timestamp", "futures_symbol", "futures_price"]].dropna()


def parse_option_quotes(zip_path: Path) -> pd.DataFrame:
    pattern = re.compile(
        r"(?P<date>\d{8})_es_minute_quote_american_"
        r"(?P<right>call|put)_(?P<strike>\d+)_(?P<expiry>\d{8})\.csv"
    )
    frames = []
    with zipfile.ZipFile(zip_path) as zf:
        for entry in zf.namelist():
            match = pattern.match(entry)
            if not match:
                continue
            right = match.group("right")
            strike = int(match.group("strike")) / 10000.0
            if (right, strike) not in SELECTED_OPTIONS:
                continue
            df = standard_quote_columns(read_entry(zip_path, entry))
            expiry = pd.Timestamp(match.group("expiry"))
            df["timestamp"] = df["ms"].map(lambda x: milliseconds_to_timestamp(match.group("date"), x))
            df["option_type"] = right
            df["strike"] = strike
            df["expiry"] = expiry
            df["option_symbol"] = f"ES-{right.upper()}-{strike:g}-{expiry:%Y%m%d}"
            df["bid"] = df["bid_close"]
            df["ask"] = df["ask_close"]
            df["option_price"] = (df["bid"] + df["ask"]) / 2.0
            frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["timestamp", "bid", "ask", "option_price"])
    out = out[(out["bid"] > 0) & (out["ask"] > 0) & (out["ask"] >= out["bid"])]
    out["relative_spread"] = (out["ask"] - out["bid"]) / out["option_price"]
    out = out[out["relative_spread"] <= 0.05]
    return out[
        [
            "timestamp",
            "option_symbol",
            "option_type",
            "strike",
            "expiry",
            "bid",
            "ask",
            "option_price",
            "relative_spread",
        ]
    ]


def build_dataset() -> Path:
    paths = ensure_raw_files()
    futures = parse_future_quote(paths["es_future_quote"]).sort_values("timestamp")
    options = parse_option_quotes(paths["es_option_quote"]).sort_values("timestamp")
    merged = pd.merge_asof(
        options,
        futures,
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("60s"),
    )
    merged = merged.dropna(subset=["futures_price"]).copy()
    merged["rate"] = 0.015
    merged = merged[
        [
            "timestamp",
            "futures_symbol",
            "option_symbol",
            "option_type",
            "strike",
            "expiry",
            "futures_price",
            "option_price",
            "bid",
            "ask",
            "relative_spread",
            "rate",
        ]
    ].sort_values(["option_symbol", "timestamp"])
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output = PROCESSED_DIR / "quantconnect_es_future_option_minute.csv"
    merged.to_csv(output, index=False, encoding="utf-8-sig")
    return output


def main() -> None:
    output = build_dataset()
    df = pd.read_csv(output)
    print(f"Wrote {output.resolve()}")
    print(f"Rows: {len(df)}")
    print(df.groupby("option_symbol").size().to_string())
    print("Median relative spread:")
    print(df.groupby("option_symbol")["relative_spread"].median().to_string())


if __name__ == "__main__":
    main()
