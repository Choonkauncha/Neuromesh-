import unittest
from ledger.money import parse_amount


class ParseAmountTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_amount("5.00"), 500)

    def test_thousands_separator(self):
        self.assertEqual(parse_amount("1,234.50"), 123450)

    def test_cents_precision(self):
        self.assertEqual(parse_amount("19.99"), 1999)


if __name__ == "__main__":
    unittest.main()
