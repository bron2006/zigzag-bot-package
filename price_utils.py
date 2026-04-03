"""Utilities for price scaling across cTrader payloads."""

def resolve_price_divisor(symbol_details, fallback_digits: int = 5) -> int:
    if symbol_details is None:
        return 10 ** fallback_digits
    digits = getattr(symbol_details, "digits", fallback_digits)
    if not isinstance(digits, int) or digits < 0:
        digits = fallback_digits
    return 10 ** digits