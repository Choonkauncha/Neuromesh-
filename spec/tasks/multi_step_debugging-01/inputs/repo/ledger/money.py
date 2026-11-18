"""Money parsing. All amounts are carried as integer cents."""


def parse_amount(text: str) -> int:
    """Parse a decimal string such as '1,234.50' or '-3.10' into integer cents."""
    cleaned = text.strip().replace(",", "")
    return int(float(cleaned) * 100)
