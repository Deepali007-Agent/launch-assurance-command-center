import tempfile
import unittest
from pathlib import Path

from orchestration.intake import (PublicationStore, catalog_publication_to_assessment,
                                  onboarding_publications_to_assessment, validate_publication,
                                  vendor_publication_to_assessment, po_publication_to_assessment)


def payload(**overrides):
    value = {
        "schema": "retail-intelligence.catalog.v1", "schema_version": "1.0",
        "source": "CATALOG_IQ_PRO", "orchestration_run_id": "ORCH-1001",
        "business_cycle_id": "RETAIL-CYCLE-TEST",
        "dataset_run_ids": ["RUN-1001"], "policy_version": "retail-ops-policy-1.0",
        "synchronization_status": "VERIFIED",
        "executive_decision": {"decision": "HOLD", "reason": "Critical defects"},
        "catalog": {"total_skus": 10, "clean_skus": 7, "warning_skus": 1,
                    "critical_skus": 2, "health_score": 82.5},
        "item_onboarding": {"submitted_items": 10, "validation_cleared": 7, "approval_ready": 7,
                            "warning_items": 1, "correction_required": 2, "erp_ready": 0,
                            "readiness_score": 82.5, "decision": "BLOCKED"},
        "revenue_impact": {"revenue_at_risk": 100000, "currency": "INR"},
        "sku_health": [
            {"sku": "SKU-1", "readiness": 60, "severity": "CRITICAL", "affected_fields": ["description"]},
            {"sku": "SKU-2", "readiness": 100, "severity": "NONE", "affected_fields": []},
        ],
        "provenance": {"source_agents": ["CATALOG_QUALITY_AGENT"]},
    }
    value.update(overrides)
    return value


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PublicationStore(str(Path(self.temp.name) / "platform.db"))

    def tearDown(self):
        self.temp.cleanup()

    def test_receive_persists_and_acknowledges(self):
        acknowledgement = self.store.receive("PUB-1001", payload())
        self.assertTrue(acknowledgement["accepted"])
        stored = self.store.get("PUB-1001")
        self.assertEqual(stored["status"], "ACCEPTED")
        self.assertEqual(stored["payload"]["dataset_run_ids"], ["RUN-1001"])

    def test_duplicate_is_idempotent(self):
        first = self.store.receive("PUB-1001", payload())
        second = self.store.receive("PUB-1001", payload())
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_publications()), 1)

    def test_unsynchronized_package_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "synchronized"):
            validate_publication(payload(synchronization_status="BLOCKED"))

    def test_catalog_contract_maps_to_parent_agent(self):
        self.store.receive("PUB-1001", payload())
        assessment = catalog_publication_to_assessment(self.store.latest("CATALOG_IQ_PRO"))
        self.assertEqual(assessment.agent_id, "catalog_iq")
        self.assertEqual(assessment.total_records, 10)
        self.assertEqual(assessment.blocked_records, 2)
        self.assertEqual(assessment.financial_exposure, 100000)
        self.assertEqual(assessment.identifiers, {"SKU-1", "SKU-2"})

    def test_vendor_contract_maps_to_parent_agent(self):
        vendor_payload = {
            "schema": "retail-intelligence.vendor.v1", "schema_version": "1.0",
            "source": "VENDOR_IQ_PRO", "orchestration_run_id": "VENDOR-ORCH-1",
            "business_cycle_id": "RETAIL-CYCLE-TEST",
            "dataset_run_ids": ["VENDOR-DATA-1"], "policy_version": "vendor-policy-1.0",
            "synchronization_status": "VERIFIED", "executive_decision": {"decision": "HOLD"},
            "vendor_intelligence": {"total_vendors": 2, "ready_vendors": 1, "warning_vendors": 0,
                                    "critical_vendors": 1, "health_score": 50, "business_value_at_risk": 250000},
            "vendor_onboarding": {"submitted_vendors": 2, "validation_cleared": 1, "approval_ready": 1,
                                  "correction_required": 1, "on_hold": 0, "handoff_ready": 0, "created": 0,
                                  "critical_vendors": 1, "warning_vendors": 0, "readiness_score": 50,
                                  "decision": "BLOCKED"},
            "vendor_health": [{"vendor_id": "V-1", "score": 0, "severity": "CRITICAL", "issues": ["Compliance"]},
                              {"vendor_id": "V-2", "score": 100, "severity": "NONE", "issues": []}],
            "provenance": {"source_agents": ["Compliance Agent"]},
        }
        self.store.receive("PUB-VENDOR-1", vendor_payload)
        assessment = vendor_publication_to_assessment(self.store.latest("VENDOR_IQ_PRO"))
        self.assertEqual(assessment.agent_id, "vendor_intelligence")
        self.assertEqual(assessment.blocked_records, 1)
        self.assertEqual(assessment.financial_exposure, 250000)

    def test_combined_onboarding_uses_both_contracts_and_weighting(self):
        self.store.receive("PUB-CATALOG", payload(orchestration_run_id="ORCH-CATALOG"))
        vendor_payload = {
            "schema": "retail-intelligence.vendor.v1", "schema_version": "1.0", "source": "VENDOR_IQ_PRO",
            "orchestration_run_id": "ORCH-VENDOR", "dataset_run_ids": ["RUN-VENDOR"],
            "business_cycle_id": "RETAIL-CYCLE-TEST",
            "policy_version": "vendor-policy-1", "synchronization_status": "VERIFIED",
            "executive_decision": {"decision": "READY"},
            "vendor_intelligence": {"total_vendors": 5, "ready_vendors": 5, "warning_vendors": 0,
                                    "critical_vendors": 0, "health_score": 100, "business_value_at_risk": 0},
            "vendor_onboarding": {"submitted_vendors": 5, "validation_cleared": 5, "approval_ready": 5,
                                  "correction_required": 0, "on_hold": 0, "handoff_ready": 0, "created": 0,
                                  "critical_vendors": 0, "warning_vendors": 0, "readiness_score": 100,
                                  "decision": "READY"},
            "vendor_health": [{"vendor_id": "V-1", "severity": "NONE", "score": 100, "issues": []}],
            "provenance": {"source_agents": ["Vendor"]},
        }
        self.store.receive("PUB-VENDOR", vendor_payload)
        combined = onboarding_publications_to_assessment(
            self.store.latest("VENDOR_IQ_PRO"), self.store.latest("CATALOG_IQ_PRO")
        )
        self.assertEqual(combined.agent_id, "onboarding_intelligence")
        self.assertAlmostEqual(combined.score, 89.5)
        self.assertEqual(combined.status, "BLOCKED")

    def test_po_contract_is_accepted_and_mapped(self):
        po_payload = {
            "schema": "retail-intelligence.po.v1", "schema_version": "1.0",
            "source": "PO_INTELLIGENCE", "orchestration_run_id": "PO-ORCH-1",
            "business_cycle_id": "RETAIL-CYCLE-TEST",
            "dataset_run_ids": ["PO-RUN-1"], "policy_version": "po-policy-1.0",
            "synchronization_status": "VERIFIED",
            "executive_decision": {"decision": "HOLD", "reason": "One blocked line"},
            "po_intelligence": {"total_lines": 2, "ready_lines": 1, "warning_lines": 0,
                                "blocked_lines": 1, "readiness_score": 75,
                                "financial_exposure": 50000, "currency": "INR"},
            "po_health": [{"po_id": "PO-1", "sku": "SKU-1", "vendor_id": "V-1",
                           "readiness": 50, "severity": "CRITICAL", "issues": ["Invalid cost"]},
                          {"po_id": "PO-2", "sku": "SKU-2", "vendor_id": "V-2",
                           "readiness": 100, "severity": "NONE", "issues": []}],
            "financial_impact": {"at_risk_rev": 50000},
            "provenance": {"source_agent": "PO_INTELLIGENCE"},
        }
        self.store.receive("PUB-PO-1", po_payload)
        assessment = po_publication_to_assessment(self.store.latest("PO_INTELLIGENCE"))
        self.assertEqual(assessment.agent_id, "po_intelligence")
        self.assertEqual(assessment.blocked_records, 1)
        self.assertEqual(assessment.financial_exposure, 50000)
        self.assertEqual(assessment.identifiers, {"SKU-1", "SKU-2"})

    def test_health_reports_missing_and_current_sources(self):
        empty = self.store.health_summary()
        self.assertFalse(empty["integration_ready"])
        self.assertEqual(empty["domains"]["po_intelligence"]["status"], "MISSING")

        self.store.receive("PUB-CATALOG-HEALTH", payload(orchestration_run_id="ORCH-HEALTH"))
        partial = self.store.health_summary()
        self.assertEqual(partial["receiver"], "UP")
        self.assertEqual(partial["domains"]["catalog_iq"]["status"], "CURRENT")
        self.assertEqual(partial["domains"]["onboarding_intelligence"]["status"], "MISSING")
        self.assertFalse(partial["integration_ready"])


if __name__ == "__main__":
    unittest.main()
