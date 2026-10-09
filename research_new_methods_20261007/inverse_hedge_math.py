"""Pure inverse-contract accounting checks, not an order/executable risk model."""
import math


def positive(*values):
    if not all(math.isfinite(v) and v>0 for v in values):raise ValueError('Positive finite prices/notional required')


def short_pnl_coin(face_usd,entry_future,mark_future):
    positive(face_usd,entry_future,mark_future)
    return face_usd*(1/mark_future-1/entry_future)


def equity_usd(collateral_coin,face_usd,entry_future,mark_future,spot_price,cash_usd=0):
    positive(collateral_coin,face_usd,entry_future,mark_future,spot_price)
    if not math.isfinite(cash_usd):raise ValueError('Invalid cash')
    margin_coin=collateral_coin+short_pnl_coin(face_usd,entry_future,mark_future)
    return {'margin_coin':margin_coin,'equity_usd':margin_coin*spot_price+cash_usd}


def funding_usd_if_immediately_converted(face_usd,rate,mark_future,spot_price):
    positive(face_usd,mark_future,spot_price)
    if not math.isfinite(rate):raise ValueError('Invalid funding')
    # A positive rate pays the short, negative rate costs it. Assumed frictionless
    # same-time coin conversion, NOT actual observed execution or account cashflow.
    return face_usd*rate/mark_future*spot_price
