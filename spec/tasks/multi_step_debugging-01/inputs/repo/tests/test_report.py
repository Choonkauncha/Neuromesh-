import unittest
from ledger.report import build_report, format_cents


class ReportTests(unittest.TestCase):
    def test_format_positive(self):
        self.assertEqual(format_cents(1999), "19.99")

    def test_refund_line_is_displayed_as_negative_amount(self):
        report = build_report([("refund", "-3.10")])
        self.assertIn("-3.10", report)

    def test_total(self):
        report = build_report([("widget", "19.99"), ("gizmo", "0.29")], rate_percent=0)
        self.assertTrue(report.splitlines()[-1].endswith("20.28"))


if __name__ == "__main__":
    unittest.main()
