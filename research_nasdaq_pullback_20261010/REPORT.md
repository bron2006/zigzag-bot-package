# Research result, 2026-10-10

Decision: fixed USTEC expansion + M5 pullback v1 DOES NOT pass the cheap gate.
Do not deploy, start a forward executor, raise risk to force orders, or claim
a validated profitable strategy. VWAP and production settings unchanged.

195988 M5 and 758 D1 bars obtained by isolated demo-only allowlisted read.
688/688 scheduled full regular US sessions usable; holidays/early closes
excluded explicitly. Total 237 trades (92 in 2024, 88 in 2025, 57 in 2026).
Original acquisition SHA retained; pre-result UTC weekday clarification is
documented in PRE_RESULT_AMENDMENT.md. No PnL existed before clarification.

Conditional five-index-point RT friction: point PF 1.270 / 1.400 / 1.062
in 2024/2025/2026. Net points 1080.54 / 1813.78 / 210.60. Five-session circular
block bootstrap 2026 mean points/session 95% CI [-13.04, +17.13]; no statistical
confirmation. 2026 has only 57 trades, below frozen minimum 100. Removing
three best trades leaves stress net negative in EACH year, especially 2026
(-1154 points); concentration diagnostic, not a recommendation to remove wins.

Ideal fractional $1000 accounts, reset each year, 1% risk, friction reserved:
base (2 points) +$105.95 / +$40.90 / +$14.21;
stress (5 points) +$85.09 / +$28.38 / +$8.02.
These are NOT executable account profits. At current broker 0.1-unit minimum,
all 237 trades are skipped at $10 initial risk budget. Minimum-contract stop
budget with stress friction ranges $10.535-$121.23, median $22.228. Do not
convert this into a proposal to risk 12% per trade. One USD/point/unit and 5x
notional cap are illustrative assumptions; actual margin remains unverified.
Broker max 250 units is not binding in any fractional projection.

Current commission metadata is zero, NOT a historical commission guarantee.
Historical bid/ask spreads, slippage, tick path and real-account margin were
not verified. No prospective OOS claim: the whole sample is retrospective.
Bar-close and adverse-range drawdowns are sampled diagnostics, not tick DD.

Verification: 11 synthetic screen tests + 6 existing read-only probe safety
tests passed. Second state-machine implementation replayed all 688 sessions,
matched all entry/ATR/stop/gap/end exits and trade paths for 237 trades, plus
all yearly cost totals and fractional balances. Shared source/calendar, not
an external independent audit. Raw cache hashes checked on every replay.

Next research must be a genuinely different predefined hypothesis, not
post-result threshold optimization of this Nasdaq candidate. Production
execution, GitHub push, cloud deploy and broker order authority were not used.
