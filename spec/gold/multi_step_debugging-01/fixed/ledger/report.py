"""Plain-text ledger report."""
from .money import parse_amount
from .tax import tax_cents


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"


def build_report(lines, rate_percent: int = 0) -> str:
    """lines: iterable of (label, amount_text). Refunds are negative amounts."""
    out = []
    subtotal = 0
    for label, amount_text in lines:
        cents = parse_amount(amount_text)
        subtotal += cents
        out.append(f"{label:<12}{format_cents(cents):>10}")
    tax = tax_cents(subtotal, rate_percent)
    out.append(f"{'subtotal':<12}{format_cents(subtotal):>10}")
    out.append(f"{'tax':<12}{format_cents(tax):>10}")
    out.append(f"{'total':<12}{format_cents(subtotal + tax):>10}")
    return "\n".join(out)
