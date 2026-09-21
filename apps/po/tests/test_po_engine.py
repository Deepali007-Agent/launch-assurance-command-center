import unittest

import pandas as pd

from domain.po_engine import (
    build_decision_support,
    build_financial,
    build_sla,
    validate_row,
)


def valid_row(**overrides):
    row = {
        "Vendor ID": "V-100",
        "Vendor Name": "Northstar",
        "Division": "Menswear",
        "Class": "Apparel",
        "Sub-Class": "Shirts",
        "Vendor Style": "STYLE-1",
        "Description": "Oxford shirt",
        "Color": "Blue",
        "Case-pack": 2,
        "Cost": 10,
        "Reg Retail": 20,
        "Original Retail": 20,
        "Total Quantity": 30,
        "Location": "NJ",
        "Ship Dates": "2026-08-01",
        "Cancel Dates": "2026-08-20",
        "PO_ID": "PO-1",
    }
    row.update(overrides)
    return pd.Series(row)


class PoEngineTests(unittest.TestCase):
    def test_clean_row_passes(self):
        result = validate_row(valid_row(), 0)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["readiness"], 100)
        self.assertEqual(result["window_days"], 19)
        self.assertEqual(result["revenue"], 600)

    def test_low_margin_is_warning_and_gap_is_positive(self):
        result = validate_row(valid_row(Cost=13), 0)

        self.assertEqual(result["status"], "WARN")
        self.assertIn("Low Margin", result["error_types"])
        self.assertAlmostEqual(result["margin_pct"], 35)
        self.assertGreater(result["margin_gap"], 0)

    def test_cancel_before_ship_is_blocking(self):
        result = validate_row(
            valid_row(**{"Cancel Dates": "2026-07-31"}),
            0,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("Cancel Before Ship", result["error_types"])
        self.assertEqual(result["window_days"], -1)

    def test_financial_summary_uses_po_level_pass_rate(self):
        clean = validate_row(valid_row(), 0)
        warning = validate_row(
            valid_row(**{"PO_ID": "PO-2", "Cost": 13}),
            1,
        )

        financial = build_financial([clean, warning])

        self.assertEqual(financial["total_pos"], 2)
        self.assertEqual(financial["unique_pos_at_risk"], 1)
        self.assertEqual(financial["po_pass_rate"], 50)
        self.assertEqual(financial["at_risk_rev"], warning["revenue"])

    def test_sla_uses_fourteen_day_threshold(self):
        compliant = validate_row(valid_row(), 0)
        tight = validate_row(
            valid_row(
                **{
                    "PO_ID": "PO-2",
                    "Cancel Dates": "2026-08-10",
                }
            ),
            1,
        )

        sla = build_sla([compliant, tight])

        self.assertEqual(sla["meets_14"], 1)
        self.assertEqual(sla["tight"], 1)
        self.assertEqual(sla["sla_rate"], 50)

    def test_decision_engine_holds_critical_po(self):
        critical = validate_row(
            valid_row(**{"Cancel Dates": "2026-07-31"}),
            0,
        )

        decisions = build_decision_support([critical])

        self.assertEqual(decisions[0]["recommendation"], "HOLD")


if __name__ == "__main__":
    unittest.main()

