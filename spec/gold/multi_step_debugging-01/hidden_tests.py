import unittest
from ledger.money import parse_amount
from ledger.report import build_report, format_cents


class HiddenTests(unittest.TestCase):
    def test_parse_matrix(self):
        for text, cents in [("0.29", 29), ("19.99", 1999), ("1,234.50", 123450),
                            ("-3.10", -310), ("0.07", 7), ("0.58", 58), ("4.35", 435),
                            ("-0.29", -29), ("100", 10000)]:
            self.assertEqual(parse_amount(text), cents, text)

    def test_format_matrix(self):
        for cents, text in [(0, "0.00"), (5, "0.05"), (-5, "-0.05"), (-310, "-3.10"),
                            (-100, "-1.00"), (123456, "1234.56"), (-123456, "-1234.56")]:
            self.assertEqual(format_cents(cents), text)

    def test_mixed_refund_report_total(self):
        report = build_report([("sale", "19.99"), ("refund", "-0.29")], rate_percent=0)
        self.assertTrue(report.splitlines()[-1].endswith("19.70"))
        self.assertIn("-0.29", report)

    def test_tax_untouched_behaviour(self):
        report = build_report([("sale", "19.99")], rate_percent=8)
        self.assertTrue(report.splitlines()[-1].endswith("21.59"))


if __name__ == "__main__":
    unittest.main()
