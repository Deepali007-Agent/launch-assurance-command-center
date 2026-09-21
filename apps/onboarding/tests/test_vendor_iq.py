import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents import assess_vendor
from data_factory import make_dataset
from dates import parse_business_date
from kpis import REGISTRY, calculate_kpis
from service import VendorIQService


class VendorIQTests(unittest.TestCase):
    def setUp(self):
        self.db_path = ROOT / "tests" / "test_runtime.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.service = VendorIQService(self.db_path)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_structural_validation_rejects_duplicate_ids(self):
        frame = make_dataset(3, "clean")
        frame.loc[1, "vendor_id"] = frame.loc[0, "vendor_id"]
        accepted, rejected, errors = self.service.validate_frame(frame)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(errors)

    def test_clean_vendor_has_no_critical_findings(self):
        vendor = make_dataset(1, "clean").iloc[0].to_dict()
        assessments = assess_vendor(vendor)
        self.assertFalse(any(a["severity"] == "Critical" for a in assessments))

    def test_spreadsheet_day_first_dates_are_accepted(self):
        self.assertEqual(str(parse_business_date("'15-09-2027'")), "2027-09-15")
        self.assertEqual(str(parse_business_date("15/09/2027")), "2027-09-15")

    def test_ingest_persists_and_routes_ready_vendor(self):
        outcome = self.service.ingest(make_dataset(2, "clean"), replace=True)
        self.assertEqual(outcome["accepted"], 2)
        vendors = self.service.repo.vendors()
        self.assertEqual({v["status"] for v in vendors}, {"Approval Decision"})
        self.assertGreaterEqual(len(self.service.repo.audit()), 4)

    def test_material_action_requires_auditable_transition(self):
        self.service.ingest(make_dataset(1, "clean"), replace=True)
        vendor_id = self.service.repo.vendors()[0]["vendor_id"]
        self.service.decision(vendor_id, "Approve vendor", "Reviewed supporting evidence")
        self.assertEqual(self.service.repo.vendors()[0]["status"], "Handoff Ready")
        self.assertEqual(self.service.repo.audit(vendor_id)[0]["note"], "Reviewed supporting evidence")

    def test_critical_finding_cannot_be_overridden_by_approval(self):
        frame = make_dataset(1, "clean")
        frame.loc[0, "tax_id"] = ""
        self.service.ingest(frame, replace=True)
        vendor_id = self.service.repo.vendors()[0]["vendor_id"]
        with self.assertRaisesRegex(ValueError, "Approval blocked"):
            self.service.decision(vendor_id, "Approve vendor", "Attempted override")

    def test_unknown_columns_are_preserved(self):
        frame = make_dataset(1, "clean")
        frame["vendor_specific_note"] = "Preserve me"
        self.service.ingest(frame, replace=True)
        self.assertEqual(self.service.repo.vendors()[0]["vendor_specific_note"], "Preserve me")

    def test_kpi_registry_has_governance_definition_for_every_metric(self):
        self.assertGreaterEqual(len(REGISTRY), 15)
        for metric in REGISTRY:
            self.assertTrue(metric.purpose)
            self.assertTrue(metric.numerator)
            self.assertTrue(metric.denominator)
            self.assertTrue(metric.eligible_population)
            self.assertTrue(metric.exclusions)
            self.assertTrue(metric.required_fields)
            self.assertTrue(metric.owner)

    def test_empty_portfolio_is_explicitly_not_measurable(self):
        results = calculate_kpis(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        self.assertFalse(results["sla_attainment"].measurable)
        self.assertEqual(results["sla_attainment"].display, "Not measurable yet")

    def test_commercial_exposure_is_not_multiplied_by_findings(self):
        frame = make_dataset(1, "mixed")
        frame.loc[0, "planned_purchase_value"] = 250000
        frame.loc[0, "value_currency"] = "GBP"
        frame.loc[0, "bank_information_status"] = "Pending"
        frame.loc[0, "insurance_status"] = "Pending"
        self.service.ingest(frame, replace=True)
        vendors, assessments, audit = self.service.snapshot()
        results = calculate_kpis(vendors, assessments, audit)
        self.assertEqual(results["opportunity_at_risk"].value, 250000)

    def test_non_base_currency_value_is_not_fabricated(self):
        frame = make_dataset(1, "clean")
        frame.loc[0, "value_currency"] = "EUR"
        self.service.ingest(frame, replace=True)
        vendors, assessments, audit = self.service.snapshot()
        results = calculate_kpis(vendors, assessments, audit)
        self.assertFalse(results["opportunity_awaiting_activation"].measurable)

    def test_post_approval_reopening_is_measured(self):
        self.service.ingest(make_dataset(1, "clean"), replace=True)
        vendor_id = self.service.repo.vendors()[0]["vendor_id"]
        self.service.decision(vendor_id, "Approve vendor", "Evidence accepted")
        self.service.decision(vendor_id, "Request correction", "Post-approval evidence defect")
        vendors, assessments, audit = self.service.snapshot()
        results = calculate_kpis(vendors, assessments, audit)
        self.assertEqual(results["post_approval_defect_rate"].value, 1.0)

    def test_completed_journey_has_measurable_activation_time(self):
        frame = make_dataset(1, "clean")
        self.service.ingest(frame, replace=True)
        vendor_id = self.service.repo.vendors()[0]["vendor_id"]
        self.service.decision(vendor_id, "Approve vendor", "Approved")
        vendors, assessments, audit = self.service.snapshot()
        results = calculate_kpis(vendors, assessments, audit)
        self.assertTrue(results["median_safe_activation_days"].measurable)
        self.assertGreaterEqual(results["median_safe_activation_days"].value, 0)


if __name__ == "__main__":
    unittest.main()
