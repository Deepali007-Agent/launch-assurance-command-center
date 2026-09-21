from datetime import datetime, timezone

import pytest

from orchestration.intake import catalog_publication_to_assessment, validate_publication
from orchestration.runtime import OrchestrationLedger
from tests.test_intake import payload
from tests.test_runtime import complete_assessments


def test_legacy_catalog_can_display_but_cannot_authorize_release(tmp_path):
    legacy = payload()
    del legacy["business_cycle_id"]
    publication = {
        "payload": legacy, "publication_id": "LEGACY",
        "orchestration_run_id": "LEGACY-RUN",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    assessment = catalog_publication_to_assessment(publication)
    assert assessment.business_cycle_id == ""
    assert assessment.total_records == 10
    ledger = OrchestrationLedger(str(tmp_path / "legacy.db"))
    run = ledger.synchronize(complete_assessments(catalog_iq=assessment))
    assert run["status"] == "CYCLE_MISMATCH"
    assert run["decision"] == "NOT EVALUATED"
    with pytest.raises(ValueError):
        ledger.decide_human_gate(run["orchestration_run_id"], True, "Buyer", "Approve")
    with pytest.raises(ValueError, match="business_cycle_id"):
        validate_publication(legacy)