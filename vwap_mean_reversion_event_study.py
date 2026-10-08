"""vwap_mean_reversion_event_study.py - Step 1+2 of the VWAP mean-reversion
research (feature/vwap-mean-reversion, 2026-08-21): causal session VWAP +-2
std bands, then a pure event study (no trading rules) of whether price
reverts to VWAP after first touching a band, following the first hour of
the session. Reads data/vwap_m5_universe.csv (produced by
vwap_fetch_history.py) - no network access here.

    python vwap_mean_reversion_event_study.py [--history data/vwap_m5_universe.csv]

HYPOTHESIS (per the task): price that deviates >2 std from the session VWAP
has an elevated chance of reverting to VWAP before session end, because
institutional TWAP/VWAP execution algos are benchmarked against VWAP and
create a structural pull back toward it after a sharp deviation (stop-hunt,
impulsive order).

SESSION DEFINITIONS (proposed and used once, not tuned):
  - FOREX: London session, 08:00-16:00 UTC, weekdays only - the consultant's
    own example. Literal fixed UTC clock hours, not "London local time" -
    deliberately ignores BST/GMT daylight-saving shift to keep the window a
    single, simple, non-tuned constant year-round (matches the task's own
    "не оптимізуй... стандартні наперед обґрунтовані значення" instruction).
  - CRYPTO: UTC calendar day (00:00-24:00), every day including weekends -
    crypto has no institutional "session" in the traditional sense, so this
    is a documented pragmatic stand-in (the closest crypto analogue of "one
    trading day"), not a claim that crypto has session opens/closes.
  Only Step 1 for this pass - no Asian/NY sessions yet, per the task's own
  "можна почати з [London], розширити пізніше".

CAUSALITY: VWAP_t and std_t at bar t are computed ONLY from bars in
[session_start, t] via cumulative sums (Σpv, Σv, Σp²v up to t) - a bar
LATER in the session can never affect an EARLIER bar's VWAP/band value. See
_compute_session_vwap_bands. Same paranoia level as every prior experiment
in this repo.

EVENT DEFINITION: per session, per direction (upper/lower), the FIRST bar
(by High>=upper_band or Low<=lower_band) strictly after the first
WARMUP_BARS=12 bars (=60 minutes on M5 - "після першої години сесії", the
task's own instruction) is one event. A single session can contribute 0, 1,
or 2 events (an upper-touch event and a lower-touch event are tracked
independently). OUTCOME: does any LATER bar in the same session have
Low <= VWAP_at_that_bar <= High (i.e. price crosses the EVOLVING VWAP line,
not a frozen snapshot from the event moment - this is the economically
correct benchmark, since a live VWAP execution algo is always compared
against the CURRENT running VWAP, not its value at some past moment)?

SPREAD-COST BREAKEVEN: reuses config.BACKTEST_DEFAULT_SPREAD_ATR_FRACTION
(the project's own established cost convention from backtest.py, not a
freshly-invented number) - spread_cost = fraction * ATR(14) on the
symbol's continuous M5 series, applied ONCE (same single-sided convention
backtest.py uses). cost_fraction = spread_cost / deviation_size (the
"prize" being bet on - how far price has to travel back to VWAP). For a
simple symmetric +-1-unit payout bet, breakeven_win_rate = 50% +
50%*cost_fraction. This is an approximation stated explicitly, not a full
strategy P&L model - the task explicitly forbids building one at this
stage.

TRIANGULATION-ARTIFACT CHECK (explicit, standalone step - the SAME pitfall
already found in feature/h1h4-mean-reversion, checked BEFORE trusting any
cross-pair result this time, not after): for every forex cross pair (both
legs non-USD), synthesizes it from its two USD legs (e.g. EURCHF ~
EURUSD/USDCHF, generalized via _usd_value_series for both currency-quoting
conventions) and reports correlation + residual half-life against the
actual quoted price - exactly the diagnostic that caught the artifact last
time.

READ-ONLY: no trading, no P&L, no DB writes. Writes only to
data/vwap_*.csv.
"""
import argparse

import numpy as np
import pandas as pd
import statsmodels.api as sm

import config

Z_BAND = 2.0
WARMUP_BARS = 12  # first hour on M5 (60min / 5min)
MIN_EVENTS_FOR_CI = 20
BOOTSTRAP_ITERS = 5000
BOOTSTRAP_SEED = 42
ATR_LENGTH = 14

BASE_QUOTED_CURRENCIES = {"EUR", "GBP", "AUD", "NZD"}   # quoted as CURUSD
QUOTE_QUOTED_CURRENCIES = {"JPY", "CHF", "CAD", "MXN", "SGD"}  # quoted as USDCUR

USD_DIRECT_MAJORS = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "USDMXN", "USDSGD"}


def _classify(symbol: str, crypto_syms: set[str]) -> str:
    if symbol in crypto_syms:
        return "crypto"
    if symbol in USD_DIRECT_MAJORS:
        return "forex_major"
    return "forex_cross"


def _usd_value_series(currency: str, price_by_symbol: dict[str, pd.Series]) -> pd.Series | None:
    if currency in BASE_QUOTED_CURRENCIES:
        return price_by_symbol.get(currency + "USD")
    if currency in QUOTE_QUOTED_CURRENCIES:
        s = price_by_symbol.get("USD" + currency)
        return None if s is None else 1.0 / s
    return None


def _triangulation_check(raw: pd.DataFrame, crypto_syms: set[str]) -> pd.DataFrame:
    price_by_symbol = {}
    for symbol, group in raw.groupby("symbol"):
        if symbol in crypto_syms:
            continue
        price_by_symbol[symbol] = group.set_index("Timestamp")["Close"].sort_index()

    rows = []
    for symbol in price_by_symbol:
        if symbol in USD_DIRECT_MAJORS:
            continue
        base, quote = symbol[:3], symbol[3:]
        if base == "USD" or quote == "USD" or len(symbol) != 6:
            continue
        leg_base = _usd_value_series(base, price_by_symbol)
        leg_quote = _usd_value_series(quote, price_by_symbol)
        if leg_base is None or leg_quote is None:
            continue

        actual = price_by_symbol[symbol]
        merged = pd.concat([actual.rename("actual"), leg_base.rename("lb"), leg_quote.rename("lq")], axis=1, join="inner").dropna()
        if len(merged) < 500:
            continue

        synthetic = merged["lb"] / merged["lq"]
        resid = (merged["actual"] - synthetic).to_numpy()
        corr = float(np.corrcoef(merged["actual"], synthetic)[0, 1])

        lagged = resid[:-1]
        delta = resid[1:] - resid[:-1]
        theta = sm.OLS(delta, sm.add_constant(lagged)).fit().params[1]
        half_life_bars = -np.log(2) / theta if theta < 0 else float("inf")

        rows.append({
            "symbol": symbol, "base_leg": base + "USD-equiv", "quote_leg": quote + "USD-equiv",
            "corr_actual_vs_synthetic": corr, "resid_half_life_m5_bars": half_life_bars,
            "resid_half_life_hours": half_life_bars * 5.0 / 60.0 if np.isfinite(half_life_bars) else float("inf"),
            "n_bars": len(merged),
            "likely_synthetic_cross": bool(corr > 0.999 and np.isfinite(half_life_bars) and half_life_bars * 5.0 / 60.0 < 2.0),
        })
    return pd.DataFrame(rows).sort_values("corr_actual_vs_synthetic", ascending=False).reset_index(drop=True)


def _assign_sessions(df: pd.DataFrame, asset_class: str) -> pd.DataFrame:
    df = df.copy()
    ts = pd.to_datetime(df["Timestamp"], unit="s", utc=True)
    df["_hour"] = ts.dt.hour
    df["_weekday"] = ts.dt.weekday
    df["_date"] = ts.dt.date

    if asset_class == "crypto":
        df["session_id"] = df["_date"].astype(str)
    else:
        in_session = (df["_hour"] >= 8) & (df["_hour"] < 16) & (df["_weekday"] < 5)
        df = df[in_session].copy()
        df["session_id"] = df["_date"].astype(str)

    return df.drop(columns=["_hour", "_weekday", "_date"])


def compute_causal_vwap_bands(close: np.ndarray, volume: np.ndarray, z_band: float = Z_BAND) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The ONE place this repo computes session VWAP + Z-band bands - every
    other script (backtest event detection, the live shadow logger, the
    LONG-only executor) imports this instead of re-deriving the formula, so
    "does the live code compute the same VWAP as the backtest" can never
    silently drift into two different implementations.

    Causal by construction: bar i's vwap[i]/upper[i]/lower[i] depend only on
    close[0..i] and volume[0..i] (numpy cumsum never looks ahead). Population
    (ddof=0) variance via Sum(v*p^2)/Sum(v) - VWAP^2 - the standard volume-
    weighted variance identity, same convention as this repo's log-price
    Bollinger bands elsewhere (mean_reversion_stage1_screen.py).

    volume.sum()==0 up to some bar (no trades yet this session) yields NaN
    vwap/bands at that bar via the cum_v<=0 guard - callers must handle NaN,
    not treat it as zero."""
    v = np.clip(volume, 0, None).astype(float)
    p = np.asarray(close, dtype=float)

    cum_v = np.cumsum(v)
    cum_v_safe = np.where(cum_v <= 0, np.nan, cum_v)
    cum_pv = np.cumsum(p * v)
    cum_p2v = np.cumsum(p * p * v)
    vwap = cum_pv / cum_v_safe
    variance = np.clip(cum_p2v / cum_v_safe - vwap ** 2, 0, None)
    std = np.sqrt(variance)
    upper = vwap + z_band * std
    lower = vwap - z_band * std
    return vwap, upper, lower


def _process_session(g: pd.DataFrame) -> list[dict]:
    g = g.sort_values("Timestamp").reset_index(drop=True)
    n = len(g)
    if n <= WARMUP_BARS + 1:
        return []

    v = g["Volume"].clip(lower=0).to_numpy(dtype=float)
    if v.sum() <= 0:
        return []
    high = g["High"].to_numpy(dtype=float)
    low = g["Low"].to_numpy(dtype=float)
    ts = g["Timestamp"].to_numpy()

    vwap, upper, lower = compute_causal_vwap_bands(g["Close"].to_numpy(dtype=float), v)

    events = []
    for direction, touched in (("upper", high >= upper), ("lower", low <= lower)):
        touched = touched.copy()
        touched[:WARMUP_BARS] = False
        touched[np.isnan(vwap)] = False
        candidates = np.where(touched)[0]
        if len(candidates) == 0:
            continue
        event_idx = int(candidates[0])

        reverted = False
        bars_to_revert = None
        for j in range(event_idx + 1, n):
            if not np.isnan(vwap[j]) and low[j] <= vwap[j] <= high[j]:
                reverted = True
                bars_to_revert = j - event_idx
                break

        price_at_event = high[event_idx] if direction == "upper" else low[event_idx]
        vwap_at_event = vwap[event_idx]
        deviation = abs(price_at_event - vwap_at_event)

        events.append({
            "event_ts": int(ts[event_idx]), "direction": direction,
            "vwap_at_event": vwap_at_event, "price_at_event": price_at_event,
            "deviation_size": deviation, "bars_remaining_in_session": n - 1 - event_idx,
            "reverted": reverted, "bars_to_revert": bars_to_revert,
        })
    return events


def _bootstrap_ci(outcomes: np.ndarray, n_iter: int = BOOTSTRAP_ITERS, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    n = len(outcomes)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_iter, n))
    boot_means = outcomes[idx].mean(axis=1)
    return float(outcomes.mean()), float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))


def _compute_atr(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(ATR_LENGTH).mean()


def main() -> None:
    parser = argparse.ArgumentParser(description="VWAP mean-reversion: causal session VWAP bands + pure event study.")
    parser.add_argument("--history", type=str, default="data/vwap_m5_universe.csv")
    args = parser.parse_args()

    print(f"Завантажую історію з {args.history}...")
    raw = pd.read_csv(args.history)
    print(f"Символів у файлі: {raw['symbol'].nunique()}\n")

    crypto_syms = {p.replace("/", "").upper() for p in config.CRYPTO_PAIRS}

    print("=== Крок 0: перевірка на triangulation-артефакт (окремо, наперед) ===\n")
    triangulation = _triangulation_check(raw, crypto_syms)
    triangulation.to_csv("data/vwap_triangulation_check.csv", index=False)
    n_suspect = int(triangulation["likely_synthetic_cross"].sum())
    print(f"Крос-пар перевірено: {len(triangulation)}")
    print(f"Підозрілих на синтетичну тріангуляцію (corr>0.999 AND half-life<2h): {n_suspect}\n")
    if n_suspect > 0:
        suspects = triangulation[triangulation["likely_synthetic_cross"]]
        print("Підозрілі пари (їхні результати нижче трактувати з застереженням):")
        for _, row in suspects.iterrows():
            print(f"  {row['symbol']:>8}  corr={row['corr_actual_vs_synthetic']:.6f}  "
                  f"half-life={row['resid_half_life_hours']:.2f}год  n={row['n_bars']:.0f}")
    suspect_symbols = set(triangulation.loc[triangulation["likely_synthetic_cross"], "symbol"]) if n_suspect > 0 else set()

    print(f"\n=== Крок 1-2: сесійний VWAP + подієвий аналіз ===\n")
    atr_by_symbol: dict[str, pd.Series] = {}
    all_events = []
    for symbol, group in raw.groupby("symbol"):
        asset_class = _classify(symbol, crypto_syms)
        group = group.sort_values("Timestamp").reset_index(drop=True)
        atr_by_symbol[symbol] = pd.Series(_compute_atr(group).to_numpy(), index=group["Timestamp"].to_numpy())

        sessioned = _assign_sessions(group, asset_class)
        if sessioned.empty:
            continue

        for session_id, g in sessioned.groupby("session_id"):
            events = _process_session(g)
            for e in events:
                e["symbol"] = symbol
                e["asset_class"] = asset_class
                e["session_id"] = session_id
                e["is_suspect_synthetic"] = symbol in suspect_symbols
                all_events.append(e)

    if not all_events:
        print("Жодної події не знайдено.")
        return

    events_df = pd.DataFrame(all_events)

    atr_lookup = []
    for _, row in events_df.iterrows():
        atr_series = atr_by_symbol.get(row["symbol"])
        atr_val = np.nan
        if atr_series is not None:
            pos = atr_series.index.searchsorted(row["event_ts"])
            if 0 <= pos < len(atr_series):
                atr_val = atr_series.iloc[pos]
        atr_lookup.append(atr_val)
    events_df["atr_at_event"] = atr_lookup

    spread_fraction = config.BACKTEST_DEFAULT_SPREAD_ATR_FRACTION
    events_df["spread_cost"] = spread_fraction * events_df["atr_at_event"]
    events_df["cost_fraction"] = events_df["spread_cost"] / events_df["deviation_size"].replace(0, np.nan)

    events_df.to_csv("data/vwap_mean_reversion_events.csv", index=False)
    print(f"Подій знайдено всього: {len(events_df)}  (symbol x session x напрямок)")
    print(f"Символів з подіями: {events_df['symbol'].nunique()}\n")

    print(f"=== Результати по класах активів (окремо, як вимагалось) ===\n")
    print(f"Витрати на спред: config.BACKTEST_DEFAULT_SPREAD_ATR_FRACTION={spread_fraction} "
          f"x ATR(14) M5, застосовано один раз (та сама конвенція, що й у backtest.py)\n")

    summary_rows = []
    for asset_class, grp in events_df.groupby("asset_class"):
        outcomes = grp["reverted"].to_numpy(dtype=float)
        n = len(outcomes)
        if n < MIN_EVENTS_FOR_CI:
            print(f"  {asset_class}: лише {n} подій - замало для довірчого інтервалу, пропущено\n")
            continue

        point, lo, hi = _bootstrap_ci(outcomes)
        median_cost_fraction = float(grp["cost_fraction"].median())
        breakeven = 0.5 + 0.5 * median_cost_fraction
        passes = lo > breakeven

        print(f"--- {asset_class} ---")
        print(f"  n подій={n}  символів={grp['symbol'].nunique()}")
        print(f"  Ймовірність повернення до VWAP: {point*100:.1f}%  "
              f"95% bootstrap CI=[{lo*100:.1f}%, {hi*100:.1f}%]")
        print(f"  Медіанна spread-cost-фракція від розміру відхилення: {median_cost_fraction*100:.1f}%")
        print(f"  Беззбитковий winrate (50%+50%*cost_fraction): {breakeven*100:.1f}%")
        print(f"  ВЕРДИКТ: {'ГІПОТЕЗА ВАРТА ПОДАЛЬШОЇ РОЗРОБКИ' if passes else 'негативний результат'} "
              f"(нижня межа CI {'>' if passes else '<='} беззбитковості)\n")

        summary_rows.append({
            "asset_class": asset_class, "n_events": n, "n_symbols": grp["symbol"].nunique(),
            "reversion_rate": point, "ci_low": lo, "ci_high": hi,
            "median_cost_fraction": median_cost_fraction, "breakeven_win_rate": breakeven,
            "passes_criterion": passes,
        })

        if asset_class == "forex_cross":
            print("  --- розбивка по окремих крос-парах (перевірка на артефакт постфактум) ---")
            for symbol, sg in grp.groupby("symbol"):
                so = sg["reverted"].to_numpy(dtype=float)
                if len(so) < MIN_EVENTS_FOR_CI:
                    continue
                sp, slo, shi = _bootstrap_ci(so)
                flag = " [ПІДОЗРА НА СИНТЕТИЧНУ ТРІАНГУЛЯЦІЮ]" if sg["is_suspect_synthetic"].iloc[0] else ""
                print(f"    {symbol:>8}  n={len(so)}  reversion={sp*100:.1f}%  CI=[{slo*100:.1f}%,{shi*100:.1f}%]{flag}")
            print()

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv("data/vwap_mean_reversion_summary.csv", index=False)

    print("=== Підсумок ===")
    if summary_df.empty:
        print("Недостатньо подій у жодній групі для висновку.")
    else:
        n_pass = int(summary_df["passes_criterion"].sum())
        print(f"Груп активів протестовано: {len(summary_df)}  |  пройшли критерій: {n_pass}")
        if n_pass == 0:
            print("Жодна група не пройшла критерій (нижня межа CI > беззбитковості) - негативний результат.")


if __name__ == "__main__":
    main()
