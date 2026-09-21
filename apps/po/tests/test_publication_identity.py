import os
from unittest.mock import patch

from domain.contracts import RunMetadata
from domain.publishing import build_publication


def payload(run="RUN-1", amount=10):
    metadata=RunMetadata(run_id=run,domain="purchase_order",source_file="test.csv",row_count=1,validated_at="2026-09-19T00:00:00+00:00")
    return build_publication(metadata,[{"po_id":"PO-1","sku":"SKU-1","status":"PASS","readiness":100}],{"at_risk_rev":amount},[],[],{},[],[])


def test_changed_value_or_run_requires_new_acknowledgement():
    original=payload()["orchestration_run_id"]
    assert payload(amount=20)["orchestration_run_id"]!=original
    assert payload(run="RUN-2")["orchestration_run_id"]!=original
    assert payload()["orchestration_run_id"]==original


def test_new_cycle_does_not_reuse_old_acknowledgement():
    with patch.dict(os.environ,{"RETAIL_BUSINESS_CYCLE_ID":"CYCLE-A"}):
        first=payload()["orchestration_run_id"]
    with patch.dict(os.environ,{"RETAIL_BUSINESS_CYCLE_ID":"CYCLE-B"}):
        assert payload()["orchestration_run_id"]!=first
