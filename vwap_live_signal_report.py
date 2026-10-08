"""vwap_live_signal_report.py - one-off report script (local, not committed):
takes the deduplicated live read-only VWAP signals (data/vwap_live_signals.csv)
and the freshly fetched real M5 history (data/vwap_week_report.csv), and runs
EXACTLY the same bar-by-bar simulation as vwap_long_only_backtest.py's
_simulate_event (SL-first same-bar tie-break, 2.2x stressed spread cost,
2.0-sigma stop) against each live signal's actual subsequent price action.
"""
import numpy as np
import pandas as pd

from vwap_mean_reversion_event_study import _assign_sessions, compute_causal_vwap_bands, _compute_atr

SPREAD_STRESS_MULTIPLIER = 2.2
SPREAD_ATR_FRACTION = 0.1
STOP_MULT = 2.0
Z_BAND = 2.0


def _bootstrap_mean_ci(values, n_iter=5000, seed=42):
    n = len(values)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_iter, n))
    boot_means = values[idx].mean(axis=1)
    return float(values.mean()), float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))


def main():
    signals = pd.read_csv("data/vwap_live_signals.csv", parse_dates=["first_ts"])
    raw = pd.read_csv("data/vwap_week_report.csv")

    results = []
    skipped = []

    for symbol, sym_raw in raw.groupby("symbol"):
        sym_raw = sym_raw.sort_values("Timestamp").reset_index(drop=True)
        atr = _compute_atr(sym_raw)
        sessioned = _assign_sessions(sym_raw, "forex_cross")

        sym_signals = signals[signals["symbol"] == symbol]
        for _, sig in sym_signals.iterrows():
            # Log timestamps are LOCAL wall-clock (this machine, UTC+3, no DST
            # change within the analyzed week) - pandas' naive Timestamp.timestamp()
            # treats a naive value as already-UTC (unlike stdlib datetime, which
            # assumes local), so it must be corrected by the fixed offset here or
            # every event lands 3h later than real UTC, silently pushing evening
            # (real UTC ~14-16h) signals outside the 08-16 UTC session window.
            LOCAL_UTC_OFFSET_SECONDS = 3 * 3600
            event_ts_s = int(sig["first_ts"].timestamp()) - LOCAL_UTC_OFFSET_SECONDS

            # anchor bar: last completed bar at/before the poll timestamp
            candidates = sym_raw[sym_raw["Timestamp"] <= event_ts_s]
            if candidates.empty:
                skipped.append((symbol, sig["first_ts"], "no bar at/before signal time"))
                continue
            raw_idx = candidates.index[-1]

            session_id = sessioned.loc[sessioned["Timestamp"] == sym_raw.loc[raw_idx, "Timestamp"], "session_id"]
            if session_id.empty:
                skipped.append((symbol, sig["first_ts"], "signal time outside London session window"))
                continue
            session_id = session_id.iloc[0]

            g = sessioned[sessioned["session_id"] == session_id].sort_values("Timestamp").reset_index(drop=True)
            ts_arr = g["Timestamp"].to_numpy()
            match = np.where(ts_arr == sym_raw.loc[raw_idx, "Timestamp"])[0]
            if len(match) == 0:
                skipped.append((symbol, sig["first_ts"], "event bar not found in session frame"))
                continue
            anchor_idx = int(match[0])

            close = g["Close"].to_numpy(dtype=float)
            high = g["High"].to_numpy(dtype=float)
            low = g["Low"].to_numpy(dtype=float)
            v = g["Volume"].clip(lower=0).to_numpy(dtype=float)
            vwap, upper, lower = compute_causal_vwap_bands(close, v, z_band=Z_BAND)

            # The live poll timestamp lands on whichever M5 bar happens to be
            # forming/just-closed at that moment - it can be 0-1 bars AFTER the
            # bar that actually satisfied Low<=lower_band (a real band touch a
            # few seconds before a bar boundary shows up as "already the next
            # bar" by the time the log line is written). Search a small window
            # of completed bars around the anchor for the true first touching
            # bar, matching the actual event definition (Low<=lower), instead
            # of trusting bar-time proximity alone - using the anchor itself
            # when nothing in the window touches understates deviation and
            # inflates R, exactly the bug this replaces.
            WINDOW_BEFORE, WINDOW_AFTER = 4, 1
            lo_search = max(0, anchor_idx - WINDOW_BEFORE)
            hi_search = min(len(g) - 1, anchor_idx + WINDOW_AFTER)
            event_idx = None
            for i in range(lo_search, hi_search + 1):
                if not np.isnan(vwap[i]) and low[i] <= lower[i]:
                    event_idx = i
                    break
            if event_idx is None:
                skipped.append((symbol, sig["first_ts"], "no true band-touch bar found near signal time"))
                continue

            atr_at_event = atr.iloc[raw_idx - (anchor_idx - event_idx)] if (raw_idx - (anchor_idx - event_idx)) >= 0 else atr.iloc[raw_idx]
            if pd.isna(atr_at_event):
                skipped.append((symbol, sig["first_ts"], "ATR not warmed up yet"))
                continue

            price_at_event = low[event_idx]
            vwap_at_event = vwap[event_idx]
            deviation = abs(price_at_event - vwap_at_event)
            if deviation <= 0:
                skipped.append((symbol, sig["first_ts"], "zero deviation at event bar"))
                continue
            sigma_at_event = deviation / Z_BAND

            spread_cost = atr_at_event * SPREAD_ATR_FRACTION
            spread_cost_stressed = spread_cost * SPREAD_STRESS_MULTIPLIER

            effective_entry = price_at_event + spread_cost_stressed
            risk = STOP_MULT * sigma_at_event
            stop_price = effective_entry - risk

            outcome, exit_bar, r_multiple = "SESSION_END", len(g) - 1, None
            for j in range(event_idx + 1, len(g)):
                stop_hit = low[j] <= stop_price
                target_hit = (not np.isnan(vwap[j])) and (low[j] <= vwap[j] <= high[j])
                if stop_hit:
                    outcome, exit_bar, r_multiple = "STOP", j, -1.0
                    break
                if target_hit:
                    outcome, exit_bar, r_multiple = "TARGET", j, (vwap[j] - effective_entry) / risk
                    break
            if r_multiple is None:
                r_multiple = (close[-1] - effective_entry) / risk

            bars_to_exit = exit_bar - event_idx
            minutes_to_exit = bars_to_exit * 5

            results.append({
                "symbol": symbol,
                "signal_first_ts": sig["first_ts"],
                "n_polls_live": sig["n_polls"],
                "logged_limit_price": sig["limit_price"],
                "logged_stop_price": sig["stop_price"],
                "real_price_at_event_bar": price_at_event,
                "real_vwap_at_event": vwap_at_event,
                "sigma_at_event": sigma_at_event,
                "effective_entry": effective_entry,
                "stop_price_2sigma": stop_price,
                "outcome": outcome,
                "bars_to_exit": bars_to_exit,
                "minutes_to_exit": minutes_to_exit,
                "r_multiple": r_multiple,
            })

    results_df = pd.DataFrame(results)
    results_df.to_csv("data/vwap_live_signal_results.csv", index=False)

    print(f"Оброблено сигналів: {len(results_df)}  |  Пропущено (немає даних): {len(skipped)}")
    if skipped:
        print("Причини пропуску:")
        from collections import Counter
        for reason, cnt in Counter(r for _, _, r in skipped).items():
            print(f"  {reason}: {cnt}")
    print()

    if len(results_df) == 0:
        return

    n_total = len(results_df)
    n_target = int((results_df["outcome"] == "TARGET").sum())
    n_stop = int((results_df["outcome"] == "STOP").sum())
    n_flat = int((results_df["outcome"] == "SESSION_END").sum())

    r_values = results_df["r_multiple"].to_numpy(dtype=float)
    mean_r, lo_r, hi_r = _bootstrap_mean_ci(r_values)

    gains = r_values[r_values > 0].sum()
    losses = -r_values[r_values < 0].sum()
    profit_factor = gains / losses if losses > 0 else float("inf")
    total_r = r_values.sum()
    win_rate = float((r_values > 0).mean())

    print(f"n={n_total}  TARGET(win)={n_target} ({n_target/n_total*100:.0f}%)  "
          f"STOP(loss)={n_stop} ({n_stop/n_total*100:.0f}%)  "
          f"SESSION_END(flat/mixed)={n_flat} ({n_flat/n_total*100:.0f}%)")
    print(f"% угод з R>0: {win_rate*100:.1f}%")
    print(f"Сумарний R: {total_r:+.2f}  |  Profit factor: {profit_factor:.2f}")
    print(f"Середній R/угоду: {mean_r:+.4f}  95% bootstrap CI=[{lo_r:+.4f}, {hi_r:+.4f}]")
    print(f"Медіана часу до виходу: {results_df['minutes_to_exit'].median():.0f} хв "
          f"(середнє: {results_df['minutes_to_exit'].mean():.0f} хв)")
    print()
    print("--- По парах ---")
    by_symbol = results_df.groupby("symbol").agg(
        n=("r_multiple", "count"),
        mean_r=("r_multiple", "mean"),
        target=("outcome", lambda s: (s == "TARGET").sum()),
        stop=("outcome", lambda s: (s == "STOP").sum()),
        flat=("outcome", lambda s: (s == "SESSION_END").sum()),
    ).sort_values("n", ascending=False)
    print(by_symbol.to_string())


if __name__ == "__main__":
    main()
