"""Sales tax. Recently refactored; behaviour is covered by tests/test_tax.py."""


def tax_cents(subtotal_cents: int, rate_percent: int) -> int:
    """Tax in cents, rounded half up. Uses integer math only."""
    return (subtotal_cents * rate_percent + 50) // 100
