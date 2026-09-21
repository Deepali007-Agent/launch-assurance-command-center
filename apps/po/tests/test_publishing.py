import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domain.contracts import RunMetadata
from domain import publishing


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({"accepted": True, "acknowledgement_id": "ACK-PO-1"}).encode()


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_outbox = publishing.OUTBOX
        publishing.OUTBOX = Path(self.temp.name) / "po-outbox.json"
        self.metadata = RunMetadata(
            run_id="PO-RUN-1", domain="purchase_order", source_file="buy.csv",
            row_count=1, validated_at="2026-09-04T10:00:00+00:00",
        )
        self.result = {
            "po_id": "PO-1", "sku": "SKU-1", "vendor_id": "V-1",
            "status": "FAIL", "readiness": 50, "errors": ["Invalid cost"], "warnings": [],
        }

    def tearDown(self):
        publishing.OUTBOX = self.original_outbox
        self.temp.cleanup()

    def payload(self):
        return publishing.build_publication(
            self.metadata, [self.result], {"at_risk_rev": 1200}, [], [], {}, [], []
        )

    def test_contract_contains_governed_po_evidence(self):
        with patch.dict(os.environ, {"RETAIL_BUSINESS_CYCLE_ID": "RETAIL-CYCLE-TEST"}):
            payload = self.payload()
        self.assertEqual(payload["schema"], "retail-intelligence.po.v1")
        self.assertEqual(payload["source"], "PO_INTELLIGENCE")
        self.assertEqual(payload["po_intelligence"]["blocked_lines"], 1)
        self.assertEqual(payload["po_intelligence"]["financial_exposure"], 1200)
        self.assertEqual(payload["dataset_run_ids"], ["PO-RUN-1"])
        self.assertEqual(payload["business_cycle_id"], "RETAIL-CYCLE-TEST")

    def test_unconfigured_destination_keeps_result_ready(self):
        with patch.dict(os.environ, {}, clear=True):
            state = publishing.publish(self.payload())
        self.assertEqual(state["status"], "READY_TO_PUBLISH")

    @patch("domain.publishing.urllib.request.urlopen", return_value=_Response())
    def test_publish_is_acknowledged_and_idempotent(self, post):
        environment = {
            "RETAIL_INTELLIGENCE_API_URL": "http://127.0.0.1:8511/v1/publications",
            "RETAIL_INTELLIGENCE_API_TOKEN": "test-token",
        }
        with patch.dict(os.environ, environment, clear=True):
            first = publishing.publish(self.payload())
            second = publishing.publish(self.payload())
        self.assertEqual(first["status"], "PUBLISHED")
        self.assertEqual(second["publication_id"], first["publication_id"])
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
