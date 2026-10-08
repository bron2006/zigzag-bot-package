"""vwap_long_only_backtest.py - LONG-only VWAP mean-reversion mini-backtest
with a real stop-loss (feature/vwap-mean-reversion, 2026-08-21), per user
instruction after the three robustness checks (vwap_robustness_checks.py)
found the SHORT side does not survive stress and MAE showed the "hold to
session end no matter what" methodology overcounts wins. This is the
narrowed, LONG-only (-2sigma events only) test: for each of several stop-
loss candidates, walk the actual bar-by-bar path from entry to see whether
the stop or the VWAP target is hit FIRST, exactly like backtest.py already
does for the production signal path - not just "did it eventually revert".

    python vwap_long_only_backtest.py

SCOPE: same base subset as before - asset_class=="forex_cross" AND
bars_remaining_in_session<=48 AND direction=="lower" (192 events, the LONG
side of the 403-event <=4h-remaining subset).

STOP CANDIDATES: 1.5sigma and 2.0sigma (user's own suggestion) plus the
LONG-only P90 MAE (4.59sigma, from vwap_mae_check.csv filtered to
direction=="lower" - LONG's own MAE distribution, not the pooled one, since
the user noted it may differ). LONG-only P75 (2.00sigma) is already
covered by the fixed 2.0sigma candidate, so not duplicated.

SIMULATION (per event, per stop candidate):
  - effective_entry = price_at_event + spread_cost_stressed (same single-
    sided convention as backtest.py: `effective_entry = entry_price +
    spread_cost` for a BUY). spread_cost_stressed = spread_cost(0.1xATR) *
    2.2 (the 2.0x widening-under-volatility proxy + ~0.02xATR commission
    approximation already established and used in vwap_robustness_checks.py
    - reused here unchanged, not re-derived).
  - stop_price = effective_entry - stop_mult * sigma_at_event
    (sigma_at_event = deviation_size/2.0, since entry sits at exactly
    Z_BAND=2 sigma from VWAP by construction).
  - Walks bars strictly after the event, in order, checking BOTH conditions
    every bar: Low_j <= stop_price (STOP hit) and Low_j <= vwap_j <= High_j
    (TARGET/VWAP hit, using the live evolving VWAP at bar j, same as the
    event study). SAME-BAR TIE-BREAK: if a bar's range spans both the stop
    and the target, SL is assumed to fire first - the exact policy
    backtest.py's own docstring documents and justifies ("resolve this
    conservatively... can only ever make the backtest's numbers
    pessimistic relative to reality, never optimistic").
  - If neither is hit before the session's last bar, the position is
    force-closed at the session's final Close (no overnight carry, matching
    this whole study's session-bounded framing) - a real third outcome
    (SESSION_END), not silently dropped or double-counted as a win.
  - R-multiple: loss = exactly -1R by construction (exit at the stop).
    Win = (vwap_at_exit_bar - effective_entry) / (stop_mult * sigma) - NOT
    a fixed 1R, since the target distance depends on how much VWAP itself
    has moved by the time it's touched, honestly variable like a real
    trade. Session-end close = (close - effective_entry) / (stop_mult *
    sigma), which can be positive, negative, or ~zero.

DECISION: mean R per trade with a 5000-iteration bootstrap 95% CI (same
method as every CI in this research line) is the primary "is there a real
edge net of stops and stressed costs" statistic - if its lower bound clears
0, that's the first result in this whole cycle to survive a real bar-by-bar
backtest, not just an event study.

READ-ONLY: reads only the local CSVs already on disk (events + raw M5
history), no network, no trading, no DB writes. Writes only to
data/vwap_long_only_backtest.csv.
"""
import numpy as np
import pandas as pd

from vwap_mean_reversion_event_study import _assign_sessions

STOP_CANDIDATES_SIGMA = [1.5, 2.0, 4.59]  # 4.59 = LONG-only P90 MAE, see docstring
SPREAD_STRESS_MULTIPLIER = 2.2  # matches vwap_robustness_checks.py exactly
BOOTSTRAP_ITERS = 5000
BOOTSTRAP_SEED = 42


def _bootstrap_mean_ci(values: np.ndarray, n_iter: int = BOOTSTRAP_ITERS, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    n = len(values)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_iter, n))
    boot_means = values[idx].mean(axis=1)
    return float(values.mean()), float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))


def _simulate_event(g: pd.DataFrame, event_idx: int, price_at_event: float, sigma: float,
                     spread_cost_stressed: float, stop_mult: float) -> dict:
    high = g["High"].to_numpy(dtype=float)
    low = g["Low"].to_numpy(dtype=float)
    close = g["Close"].to_numpy(dtype=float)
    v = g["Volume"].clip(lower=0).to_numpy(dtype=float)
    p = g["Close"].to_numpy(dtype=float)
    cum_v = np.cumsum(v)
    cum_v_safe = np.where(cum_v <= 0, np.nan, cum_v)
    vwap = np.cumsum(p * v) / cum_v_safe

    effective_entry = price_at_event + spread_cost_stressed
    stop_price = effective_entry - stop_mult * sigma
    risk = stop_mult * sigma

    n = len(g)
    for j in range(event_idx + 1, n):
        stop_hit = low[j] <= stop_price
        target_hit = (not np.isnan(vwap[j])) and (low[j] <= vwap[j] <= high[j])
        if stop_hit:  # SL-first tie-break, matches backtest.py's own documented policy
            return {"outcome": "STOP", "exit_bar": j, "r_multiple": -1.0}
        if target_hit:
            r = (vwap[j] - effective_entry) / risk
            return {"outcome": "TARGET", "exit_bar": j, "r_multiple": r}

    r = (close[n - 1] - effective_entry) / risk
    return {"outcome": "SESSION_END", "exit_bar": n - 1, "r_multiple": r}


def main() -> None:
    events = pd.read_csv("data/vwap_mean_reversion_events.csv")
    long_events = events[
        (events["asset_class"] == "forex_cross")
        & (events["bars_remaining_in_session"] <= 48)
        & (events["direction"] == "lower")
    ].copy()
    print(f"LONG-only події (forex_cross, <=48 барів, -2sigma): n={len(long_events)}, "
          f"символів={long_events['symbol'].nunique()}\n")

    long_events["spread_cost_stressed"] = long_events["spread_cost"] * SPREAD_STRESS_MULTIPLIER
    long_events["sigma_at_event"] = long_events["deviation_size"] / 2.0

    raw = pd.read_csv("data/vwap_m5_universe.csv")
    sessioned_cache: dict[str, pd.DataFrame] = {}
    for symbol in long_events["symbol"].unique():
        group = raw[raw["symbol"] == symbol].sort_values("Timestamp").reset_index(drop=True)
        sessioned_cache[symbol] = _assign_sessions(group, "forex_cross")

    all_results = []
    for stop_mult in STOP_CANDIDATES_SIGMA:
        trades = []
        for _, ev in long_events.iterrows():
            sessioned = sessioned_cache.get(ev["symbol"])
            if sessioned is None:
                continue
            g = sessioned[sessioned["session_id"] == ev["session_id"]].sort_values("Timestamp").reset_index(drop=True)
            ts_arr = g["Timestamp"].to_numpy()
            matches = np.where(ts_arr == ev["event_ts"])[0]
            if len(matches) == 0:
                continue
            event_idx = int(matches[0])

            result = _simulate_event(g, event_idx, ev["price_at_event"], ev["sigma_at_event"],
                                      ev["spread_cost_stressed"], stop_mult)
            result.update({"symbol": ev["symbol"], "session_id": ev["session_id"], "stop_mult": stop_mult})
            trades.append(result)

        trades_df = pd.DataFrame(trades)
        all_results.append(trades_df)

        r_values = trades_df["r_multiple"].to_numpy(dtype=float)
        mean_r, lo_r, hi_r = _bootstrap_mean_ci(r_values)

        n_target = int((trades_df["outcome"] == "TARGET").sum())
        n_stop = int((trades_df["outcome"] == "STOP").sum())
        n_flat = int((trades_df["outcome"] == "SESSION_END").sum())
        n_total = len(trades_df)
        win_rate_positive_r = float((r_values > 0).mean())

        gains = r_values[r_values > 0].sum()
        losses = -r_values[r_values < 0].sum()
        profit_factor = gains / losses if losses > 0 else float("inf")
        total_r = r_values.sum()

        print(f"--- Стоп = {stop_mult}sigma ---")
        print(f"  n={n_total}  TARGET(win)={n_target} ({n_target/n_total*100:.0f}%)  "
              f"STOP(loss)={n_stop} ({n_stop/n_total*100:.0f}%)  "
              f"SESSION_END(flat/mixed)={n_flat} ({n_flat/n_total*100:.0f}%)")
        print(f"  % угод з R>0: {win_rate_positive_r*100:.1f}%")
        print(f"  Сумарний R: {total_r:+.2f}  |  Profit factor: {profit_factor:.2f}")
        print(f"  Середній R/угоду: {mean_r:+.4f}  95% bootstrap CI=[{lo_r:+.4f}, {hi_r:+.4f}]")
        verdict = "СТАТИСТИЧНО ПЕРЕКОНЛИВО ПРИБУТКОВО" if lo_r > 0 else "НЕ переконливо (CI перетинає 0)"
        print(f"  ВЕРДИКТ: {verdict}\n")

    pd.concat(all_results, ignore_index=True).to_csv("data/vwap_long_only_backtest.csv", index=False)
    print("Збережено: data/vwap_long_only_backtest.csv")


if __name__ == "__main__":
    main()
