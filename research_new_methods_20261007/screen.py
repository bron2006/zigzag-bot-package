"""Offline, fixed-rule screening. No bot imports, credentials or network."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

METHODS = ("hour_momentum", "opening_breakout", "failed_breakout")
SEED = 20261007


def prepare(raw):
    required = ["symbol", "Timestamp", "Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(raw):
        raise ValueError("Missing required history columns")
    df = raw[required].copy()
    if df.duplicated(["symbol", "Timestamp"]).any():
        raise ValueError("Duplicate symbol/timestamp")
    if df.isna().any().any():
        raise ValueError("Missing history values")
    values = df[["Open", "High", "Low", "Close"]]
    if not np.isfinite(values).all().all() or (values <= 0).any().any():
        raise ValueError("Invalid prices")
    if ((df.High < values.max(axis=1)) | (df.Low > values.min(axis=1))).any():
        raise ValueError("Impossible OHLC")
    if (df.Timestamp % 300 != 0).any():
        raise ValueError("Non-M5 timestamp")
    df = df.sort_values(["symbol", "Timestamp"])
    previous = df.groupby("symbol").Close.shift(1)
    tr = pd.concat([df.High-df.Low, (df.High-previous).abs(), (df.Low-previous).abs()], axis=1).max(axis=1)
    df["atr"] = tr.groupby(df.symbol).transform(lambda s: s.rolling(14, min_periods=14).mean())
    df["utc"] = pd.to_datetime(df.Timestamp, unit="s", utc=True)
    df["day"] = df.utc.dt.strftime("%Y-%m-%d")
    return df


def first_signal(session, method):
    close = session.Close.to_numpy()
    atr = session.atr.to_numpy()
    high, low = session.High.iloc[:12].max(), session.Low.iloc[:12].min()
    # signal+2 entry must be <=15:00 (index84). Last signal index82.
    for i in range(12, min(83, len(session)-2)):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        side = 0
        if method == "hour_momentum":
            change = close[i] - close[i-12]
            side = 1 if change > atr[i] else -1 if change < -atr[i] else 0
        elif method == "opening_breakout":
            side = 1 if close[i] > high else -1 if close[i] < low else 0
        elif method == "failed_breakout":
            if i >= 13 and low <= close[i] <= high:
                side = -1 if close[i-1] > high else 1 if close[i-1] < low else 0
        else:
            raise ValueError("Unknown strategy")
        if side:
            return i, side
    return None


def outcome(session, signal_index, side):
    entry_index = signal_index + 2
    entry = float(session.Open.iloc[entry_index])
    atr = float(session.atr.iloc[signal_index])
    risk = 2*atr
    stop, target = entry-side*risk, entry+side*2*risk
    last = min(entry_index+11, len(session)-1)
    exit_index, exit_price, reason = last, float(session.Close.iloc[last]), "time"
    for j in range(entry_index, last+1):
        bar = session.iloc[j]
        stopped = bar.Low <= stop if side == 1 else bar.High >= stop
        target_hit = bar.High >= target if side == 1 else bar.Low <= target
        if stopped:
            exit_index = j
            exit_price = min(stop, bar.Open) if side == 1 else max(stop, bar.Open)
            reason = "stop"
            break
        if target_hit:
            exit_index, exit_price, reason = j, target, "target"
            break
    gross = side*(exit_price-entry)/risk
    return dict(entry_index=entry_index, exit_index=exit_index, entry_price=entry,
                stop=stop, target=target, atr=atr, gross_r=gross,
                net_r=gross-0.11, stress_r=gross-0.22, exit_reason=reason)


def trade_rows(df):
    trades, exclusions, calendar = [], [], set()
    eligible = df[(df.utc.dt.dayofweek < 5) & (df.utc.dt.hour >= 8) & (df.utc.dt.hour < 16)
                  & (df.day >= "2026-08-24") & (df.day <= "2026-10-01")]
    for (symbol, day), session in eligible.groupby(["symbol", "day"]):
        session = session.reset_index(drop=True)
        expected_start = int(pd.Timestamp(day, tz="UTC").timestamp())+8*3600
        timestamps = session.Timestamp.to_numpy()
        if len(session) != 96 or not np.array_equal(timestamps, expected_start+np.arange(96)*300):
            exclusions.append(dict(symbol=symbol, day=day, reason="incomplete_session", bars=len(session)))
            continue
        if not np.isfinite(session.atr.iloc[12:83]).all():
            exclusions.append(dict(symbol=symbol, day=day, reason="missing_atr_warmup", bars=len(session)))
            continue
        calendar.add(day)
        for method in METHODS:
            signal = first_signal(session, method)
            if signal is None:
                continue
            i, side = signal
            primary, control = outcome(session, i, side), outcome(session, i, -side)
            trades.append(dict(strategy=method, symbol=symbol, day=day, side=side,
                               signal_closed_ts=int(session.Timestamp.iloc[i])+300,
                               entry_ts=int(session.Timestamp.iloc[i+2]),
                               exit_bar_ts=int(session.Timestamp.iloc[primary["exit_index"]]),
                               **primary, opposite_r=control["net_r"],
                               paired_difference_r=primary["net_r"]-control["net_r"]))
    return pd.DataFrame(trades), pd.DataFrame(exclusions), sorted(calendar)


def bootstrap(group, calendar, column, draws=10000):
    daily = group.groupby("day")[column].agg(["sum", "count"]).reindex(calendar, fill_value=0)
    values = daily["sum"].to_numpy()
    counts = daily["count"].to_numpy()
    rng = np.random.default_rng(SEED)
    sampled = rng.integers(0, len(calendar), size=(draws, len(calendar)))
    denom = counts[sampled].sum(axis=1)
    valid = denom > 0
    means = values[sampled].sum(axis=1)[valid]/denom[valid]
    tail = 0.05/(2*len(METHODS))
    return [float(x) for x in np.quantile(means, [tail, 1-tail])]


def metrics(group, calendar):
    if group.empty:
        return {"n": 0, "dates": 0, "mean_r": None, "pf": None}
    def pf(column):
        r = group[column]
        loss = -r[r < 0].sum()
        return float(r[r > 0].sum()/loss) if loss else None
    return dict(n=len(group), dates=int(group.day.nunique()),
                mean_r=float(group.net_r.mean()), total_r=float(group.net_r.sum()),
                pf=pf("net_r"), stress_mean_r=float(group.stress_r.mean()),
                stress_pf=pf("stress_r"), opposite_mean_r=float(group.opposite_r.mean()),
                mean_ci_9833=bootstrap(group, calendar, "net_r"),
                stress_ci_9833=bootstrap(group, calendar, "stress_r"),
                paired_ci_9833=bootstrap(group, calendar, "paired_difference_r"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    df = prepare(pd.read_csv(args.history))
    trades, excluded, calendar = trade_rows(df)
    records = []
    for method in METHODS:
        group = trades[trades.strategy == method]
        early_days = [d for d in calendar if d <= "2026-09-11"]
        late_days = [d for d in calendar if d >= "2026-09-14"]
        early = metrics(group[group.day <= "2026-09-11"], early_days)
        late = metrics(group[group.day >= "2026-09-14"], late_days)
        passed = (late["n"] >= 100 and late["dates"] >= 10 and early["n"] > 0
                  and early["mean_r"] > 0 and late["mean_r"] > 0
                  and late["pf"] is not None and late["pf"] > 1.1
                  and late["stress_pf"] is not None and late["stress_pf"] > 1.0
                  and late["stress_ci_9833"][0] > 0 and late["paired_ci_9833"][0] > 0)
        records.append(dict(strategy=method, early=early, late=late,
                            advances_to_further_research=bool(passed)))
    summary = dict(protocol_sha256=hashlib.sha256(Path(__file__).with_name("PROTOCOL.md").read_bytes()).hexdigest(),
                   source_sha256=hashlib.sha256(args.history.read_bytes()).hexdigest(),
                   source_rows=len(df), symbols=int(df.symbol.nunique()),
                   calendar=calendar, excluded_sessions=len(excluded), seed=SEED,
                   retrospective_not_blind=True, results=records)
    args.output.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.output/"trades.csv", index=False)
    excluded.to_csv(args.output/"excluded_sessions.csv", index=False)
    trades.groupby(["strategy", "day"]).agg(
        trades=("net_r", "size"), net_total_r=("net_r", "sum"),
        stress_total_r=("stress_r", "sum"), opposite_total_r=("opposite_r", "sum")
    ).reset_index().to_csv(args.output/"daily.csv", index=False)
    (args.output/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
