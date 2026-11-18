import unittest
from ledger.tax import tax_cents


class TaxTests(unittest.TestCase):
    def test_round_half_up(self):
        self.assertEqual(tax_cents(1999, 8), 160)

    def test_zero_rate(self):
        self.assertEqual(tax_cents(1999, 0), 0)


if __name__ == "__main__":
    unittest.main()
