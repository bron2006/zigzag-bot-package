"""Offline cross-asset predictive screening; never an execution/account engine."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import gzip
import hashlib
import json
import math
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
START, END = 1704067200, 1791417600
PHASES = (("2024", START, 1735689600), ("2025", 1735689600, 1767225600),
          ("2026H1", 1767225600, 1782864000), ("2026H2", 1782864000, END))


def load(asset):
    folder = ROOT / "research_new_methods_20261007" / "inverse_price_cache"
    manifest = json.loads((folder / f"{asset}_spot_complete.json").read_text("utf-8"))
    if not manifest["complete"]:
        raise ValueError("Incomplete manifest")
    rows, hashes = [], {}
    for page in manifest["pages"]:
        name = page["file"] if isinstance(page, dict) else page
        path = folder / name
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if isinstance(page, dict) and hashes[name] != page["sha256"]:
            raise ValueError("Changed input")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for raw in json.load(stream):
                ts = int(raw[0]) // 1000
                if START <= ts < END:
                    o, h, l, c = map(float, raw[1:5])
                    if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)) or not l <= min(o, c) <= max(o, c) <= h:
                        raise ValueError("Invalid OHLC")
                    rows.append(dict(ts=ts, Open=o, Close=c))
    rows.sort(key=lambda b: b["ts"])
    if [r["ts"] for r in rows] != list(range(START, END, 3600)):
        raise ValueError("Missing/duplicate hourly inputs")
    return rows, hashes


def signals(btc, eth, arm):
    if len(btc) != len(eth) or any(a["ts"] != b["ts"] for a, b in zip(btc, eth)):
        raise ValueError("Unsynchronized inputs")
    if arm not in ("ratio_reversion", "leader_lag"):
        raise ValueError("Unknown arm")
    ratios = np.log([a["Close"] / b["Close"] for a, b in zip(btc, eth)])
    result, blocked = [], -1
    horizon = 24 if arm == "ratio_reversion" else 6
    for i in range(len(btc)):
        entry = i + 2  # signal bar closes at i+1; wait that entire next hour
        if entry < blocked:
            continue
        side = 0
        if arm == "ratio_reversion" and i >= 168:
            prior = ratios[i - 168:i]
            sd = float(prior.std())
            z = (ratios[i] - float(prior.mean())) / sd if sd > 1e-12 else 0
            if abs(z) >= 2:
                side = -1 if z > 0 else 1
        elif arm == "leader_lag":
            rb = btc[i]["Close"] / btc[i]["Open"] - 1
            re = eth[i]["Close"] / eth[i]["Open"] - 1
            if abs(rb) >= .01 and abs(re) < .5 * abs(rb):
                side = 1 if rb > 0 else -1
        if side:
            result.append(dict(signal_index=i, entry_index=entry, exit_index=entry + horizon,
                               side=side, ts=btc[i]["ts"] + 7200, horizon=horizon))
            blocked = entry + horizon
    return result


def outcome(intent, btc, eth, arm, side, cost):
    i, j = intent["entry_index"], intent["exit_index"]
    if j >= len(btc):
        return dict(status="pending")
    if arm == "ratio_reversion":
        rb = btc[j]["Open"] / btc[i]["Open"] - 1
        re = eth[j]["Open"] / eth[i]["Open"] - 1
        gross = .5 * side * (rb - re)
        long_weight = .5
    else:
        gross = side * (eth[j]["Open"] / eth[i]["Open"] - 1)
        long_weight = float(side > 0)
    carry = .20 * intent["horizon"] / (365 * 24) * long_weight if cost else 0
    return dict(status="closed", gross=gross, net=gross-cost-carry, carry=carry)


def ci(values, day_indices, n_days):
    if not len(values):
        return None
    sums = np.bincount(day_indices, weights=values, minlength=n_days)
    counts = np.bincount(day_indices, minlength=n_days)
    rng = np.random.default_rng(20261015)
    starts = rng.integers(0, n_days, (10000, (n_days + 9)//10))
    idx = ((starts[:, :, None] + np.arange(10)) % n_days).reshape(10000, -1)[:, :n_days]
    ns = counts[idx].sum(axis=1)
    means = sums[idx].sum(axis=1)[ns > 0] / ns[ns > 0]
    return (np.quantile(means, [.025/64, 1-.025/64])*10000).tolist()


def main():
    btc, bh = load("BTC")
    eth, eh = load("ETH")
    report = dict(protocol_sha256=hashlib.sha256((HERE/"PROTOCOL.md").read_bytes()).hexdigest(),
                  input_hashes=dict(BTC=bh, ETH=eh), observations_only=True, real_orders=False,
                  phases=[], gates={})
    for arm in ("ratio_reversion", "leader_lag"):
        intents = signals(btc, eth, arm)
        stress_checks, total_2026 = [], 0
        for label, begin, end in PHASES:
            selected = [r for r in intents if begin <= r["ts"] < end]
            for scenario, cost in (("gross", 0), ("base", .002), ("stress", .003)):
                rows = [(r, outcome(r, btc, eth, arm, r["side"], cost)) for r in selected]
                closed = [(r, o) for r, o in rows if o["status"] == "closed"]
                vals = np.array([o["net"] for r, o in closed])
                days = np.array([(r["ts"]-begin)//86400 for r, o in closed], dtype=int)
                n_days = (end-begin+86399)//86400
                controls = {}
                for control in ("opposite", "always_positive", "always_negative"):
                    differences = np.array([o["net"] - outcome(r, btc, eth, arm,
                        -r["side"] if control == "opposite" else 1 if control == "always_positive" else -1,
                        cost)["net"] for r, o in closed])
                    controls[control] = dict(mean_improvement_bp=float(differences.mean()*10000) if len(vals) else None,
                                             adjusted_ci_bp=ci(differences, days, n_days))
                gain = vals[vals > 0].sum()
                loss = -vals[vals < 0].sum()
                summary = dict(arm=arm, phase=label, scenario=scenario, selected=len(rows),
                    statuses=dict(Counter(o["status"] for r, o in rows)), closed=len(vals),
                    mean_bp=float(vals.mean()*10000) if len(vals) else None,
                    median_bp=float(np.median(vals)*10000) if len(vals) else None,
                    sum_independent_bp=float(vals.sum()*10000),
                    wins=int((vals>0).sum()), worst_observation_bp=float(vals.min()*10000) if len(vals) else None,
                    profit_factor=float(gain/loss) if loss else None,
                    adjusted_ci_bp=ci(vals, days, n_days), controls=controls)
                report["phases"].append(summary)
                print(json.dumps({k:v for k,v in summary.items() if k != "controls"}), flush=True)
                if scenario == "stress":
                    stress_checks.append(summary)
                    if label.startswith("2026"):
                        total_2026 += len(vals)
        late = stress_checks[-1]
        report["gates"][arm] = bool(all(r["mean_bp"] is not None and r["mean_bp"]>0 for r in stress_checks)
            and total_2026 >= 100 and late["closed"]>=30 and late["adjusted_ci_bp"][0]>0
            and all(c["adjusted_ci_bp"][0]>0 for c in late["controls"].values()))
    (HERE/"result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(dict(gates=report["gates"])), flush=True)


if __name__ == "__main__":
    main()
