"""Public price-only retrieval and research simulation, no credentials/orders."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT")
START = "2019-01-01"
END = "2026-10-01"
ENDPOINT = "https://data-api.binance.vision/api/v3/klines"


def fetch(output):
    output.mkdir(parents=True, exist_ok=True)
    end_ms = int(pd.Timestamp(END, tz="UTC").timestamp()*1000)
    for symbol in SYMBOLS:
        cursor = int(pd.Timestamp(START, tz="UTC").timestamp()*1000)
        rows = []
        while cursor < end_ms:
            query = urlencode(dict(symbol=symbol, interval="1d", startTime=cursor,
                                   endTime=end_ms-1, limit=1000))
            with urlopen(ENDPOINT+"?"+query, timeout=15) as response:
                batch = json.load(response)
            if not isinstance(batch, list) or not batch:
                raise ValueError("Incomplete public price history")
            rows.extend(batch)
            next_cursor = int(batch[-1][0])+86400000
            if next_cursor <= cursor:
                raise ValueError("Non-advancing API cursor")
            cursor = next_cursor
        # Preserve raw API fields and provenance separately from computed data.
        record = dict(endpoint=ENDPOINT, symbol=symbol, interval="1d",
                      fetched_utc=pd.Timestamp.now(tz="UTC").isoformat(),
                      start=START, end_exclusive=END, rows=rows)
        path = output/f"{symbol}_1d.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        print(json.dumps(dict(symbol=symbol, rows=len(rows), stored=str(path))), flush=True)


def load_history(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw["rows"]
    df = pd.DataFrame([dict(ts=int(r[0]), Open=float(r[1]), High=float(r[2]),
                            Low=float(r[3]), Close=float(r[4])) for r in rows])
    expected = pd.date_range(START, END, freq="D", inclusive="left", tz="UTC")
    expected_ms = expected.as_unit("ms").asi8
    if not np.array_equal(df.ts.to_numpy(), expected_ms):
        raise ValueError("Daily timestamps missing, duplicated or out of requested range")
    prices = df[["Open", "High", "Low", "Close"]]
    if not np.isfinite(prices).all().all() or (prices <= 0).any().any():
        raise ValueError("Invalid price")
    if ((df.High < prices.max(axis=1)) | (df.Low > prices.min(axis=1))).any():
        raise ValueError("Impossible OHLC")
    df["date"] = expected
    df["desired"] = (df.Close > df.Close.rolling(200, min_periods=200).mean()).astype(int)
    df["position"] = df.desired.shift(2).fillna(0).astype(int)
    return df


def simulate(df, fee, hold=False):
    equity, cash, units, active = [], 1.0, 0.0, 0
    changes, entries, completed = 0, 0, 0
    for i, bar in enumerate(df.itertuples(index=False)):
        desired = 1 if hold else int(bar.position)
        if desired != active:
            changes += 1
            if desired:
                units, cash = cash*(1-fee)/bar.Open, 0.0
                entries += 1
            else:
                cash, units = units*bar.Open*(1-fee), 0.0
                completed += 1
            active = desired
        equity.append(cash+units*bar.Close)
    if active:
        equity[-1] *= 1-fee
        changes += 1
        completed += 1
    curve = np.asarray(equity)
    running_peak = np.maximum.accumulate(np.r_[1.0, curve])[1:]
    years = len(df)/365.25
    return dict(total_return=float(curve[-1]-1), annualized_return=float(curve[-1]**(1/years)-1),
                max_drawdown=float((curve/running_peak-1).min()),
                exposure=float(1 if hold else df.position.mean()), changes=changes,
                entries=entries, completed_trades=completed, days=len(df)), curve


def analyze(directory):
    records, curves = [], []
    for symbol in SYMBOLS:
        path = directory/f"{symbol}_1d.json"
        history = load_history(path)
        blocks = {"early": ("2020-01-01", "2024-01-01"), "late": ("2024-01-01", END)}
        result = dict(symbol=symbol, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), blocks={})
        for label, (start, end) in blocks.items():
            df = history[(history.date >= start) & (history.date < end)].copy()
            measured = {}
            for name, fee, hold in [("trend", .001, False), ("trend_stress", .003, False),
                                     ("buy_hold", .001, True), ("buy_hold_stress", .003, True)]:
                measured[name], curve = simulate(df, fee, hold)
                curves.extend(dict(symbol=symbol, block=label, model=name, date=str(day.date()),
                                   equity=float(value)) for day, value in zip(df.date, curve))
            result["blocks"][label] = measured
        late = result["blocks"]["late"]
        result["risk_screen_pass"] = (late["trend_stress"]["total_return"] > 0
                                       and late["trend_stress"]["max_drawdown"] > late["buy_hold_stress"]["max_drawdown"])
        records.append(result)
    summary = dict(protocol_sha256=hashlib.sha256(Path(__file__).with_name("DAILY_TREND_PROTOCOL.md").read_bytes()).hexdigest(),
                   selected_parameters_before_results=True, retrospective_not_proven_edge=True,
                   both_assets_pass=all(r["risk_screen_pass"] for r in records), results=records)
    (directory/"daily_trend_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(curves).to_csv(directory/"daily_trend_equity.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["fetch", "analyze", "fetch-worker"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "fetch-worker":
        fetch(args.directory)
    elif args.mode == "fetch":
        # urllib timeout does not reliably bound OS DNS, so bound the whole child.
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "fetch-worker",
                                     "--directory", str(args.directory)], timeout=90)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print("Public data retrieval exceeded 90 seconds; child killed; no analysis run.")
            sys.exit(1)
    else:
        analyze(args.directory)
