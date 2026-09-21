import pandas as pd
import pytest

from catalog_operations.adapters import get_catalog_domain_snapshot, get_catalog_rework_metrics
from catalog_operations.enums import DomainDecisionType, LifecycleStatus
from catalog_operations.ingestion import ingest_dataframe
from catalog_operations.orchestrator import CatalogOperationsOrchestrator
from catalog_operations.services import process_upload


def test_agent_assessment_contract_and_sequence(valid_df, repository):
    item = ingest_dataframe(valid_df).items[0]
    assessments, decision = CatalogOperationsOrchestrator(repository).evaluate(item)
    assert [a.agent_name for a in assessments] == ["ITEM_INTAKE_AGENT", "CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT", "ITEM_REWORK_AGENT"]
    assert all(a.entity_id == item.sku and 0 <= a.readiness_score <= 100 for a in assessments)
    assert decision.sku == item.sku


def test_critical_blocker_enforcement(valid_row, repository):
    valid_row["vendor_approved"] = False
    item = ingest_dataframe(pd.DataFrame([valid_row])).items[0]
    _, decision = CatalogOperationsOrchestrator(repository).evaluate(item)
    assert decision.decision == DomainDecisionType.REWORK_REQUIRED
    assert decision.critical_blockers
    assert repository.get_current_item(item.sku).lifecycle_status == LifecycleStatus.REWORK_REQUIRED
    with pytest.raises(ValueError, match="not allowed|Critical blockers"):
        CatalogOperationsOrchestrator(repository).transition(item.sku, "APPROVE", "TEST")


def test_decision_requires_human_approval(valid_df, repository):
    result = process_upload(valid_df, "test.csv", repository)
    decision = result.evaluations[0][1]
    assert decision.decision in {DomainDecisionType.APPROVE, DomainDecisionType.CONDITIONAL_APPROVAL}
    assert repository.get_current_item("SKU-1001").lifecycle_status == LifecycleStatus.PENDING_HUMAN_APPROVAL
    target = CatalogOperationsOrchestrator(repository).transition("SKU-1001", "APPROVE", "HUMAN_APPROVED")
    assert target == LifecycleStatus.APPROVED


def test_hold_can_be_released_to_human_approval(valid_df, repository):
    process_upload(valid_df, "test.csv", repository)
    orchestrator = CatalogOperationsOrchestrator(repository)
    assert orchestrator.transition("SKU-1001", "PLACE_ON_HOLD", "WAITING") == LifecycleStatus.ON_HOLD
    assert orchestrator.transition("SKU-1001", "RELEASE_HOLD", "RESUMED") == LifecycleStatus.PENDING_HUMAN_APPROVAL


def test_post_live_vendor_amendment_generates_rework(valid_df, repository):
    process_upload(valid_df, "first.csv", repository)
    orchestrator = CatalogOperationsOrchestrator(repository)
    orchestrator.transition("SKU-1001", "APPROVE", "HUMAN_APPROVED")
    orchestrator.transition("SKU-1001", "PREPARE_ERP_HANDOFF", "HANDOFF_PREPARED")
    orchestrator.transition("SKU-1001", "MARK_CREATED_IN_ERP_SIMULATION", "SIMULATED_GO_LIVE")
    corrected = valid_df.copy()
    corrected.loc[0, "description"] = "Updated customer description with additional product care and fit details."
    process_upload(corrected, "second.csv", repository)
    versions = repository.list_item_versions("SKU-1001")
    rework = repository.list_rework_events("SKU-1001")
    assert [v["revision_number"] for v in versions] == [1, 2]
    assert any(e["attribute_name"] == "description" for e in rework)


def test_revalidation_after_correction(valid_row, repository):
    valid_row["material"] = ""
    first = process_upload(pd.DataFrame([valid_row]), "first.csv", repository)
    assert first.evaluations[0][1].critical_blockers
    valid_row["material"] = "Cotton"
    second = process_upload(pd.DataFrame([valid_row]), "second.csv", repository)
    assert not second.evaluations[0][1].critical_blockers
    assert repository.get_current_item("SKU-1001").revision_number == 2
    assert repository.list_rework_events("SKU-1001") == []


def test_first_time_right_calculation(valid_df, repository):
    process_upload(valid_df, "first.csv", repository)
    metrics = get_catalog_rework_metrics(repository)
    assert metrics["first_time_right_rate"] == 100.0
    orchestrator = CatalogOperationsOrchestrator(repository)
    orchestrator.transition("SKU-1001", "APPROVE", "HUMAN_APPROVED")
    orchestrator.transition("SKU-1001", "PREPARE_ERP_HANDOFF", "HANDOFF_PREPARED")
    orchestrator.transition("SKU-1001", "MARK_CREATED_IN_ERP_SIMULATION", "SIMULATED_GO_LIVE")
    updated = valid_df.copy(); updated.loc[0, "colour"] = "Navy"
    process_upload(updated, "second.csv", repository)
    metrics = get_catalog_rework_metrics(repository)
    assert metrics["first_time_right_rate"] == 0.0
    assert metrics["rework_rate"] == 100.0


def test_empty_state_adapter(repository):
    snapshot = get_catalog_domain_snapshot(repository)
    assert snapshot["evaluated_skus"] == 0
    assert snapshot["priority_actions"] == []


def test_database_persistence_survives_repository_restart(valid_df, tmp_path):
    from catalog_operations.persistence.repository import CatalogRepository
    url = f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}"
    process_upload(valid_df, "test.csv", CatalogRepository(url))
    reopened = CatalogRepository(url)
    assert reopened.get_current_item("SKU-1001") is not None
    assert len(reopened.list_assessments("SKU-1001")) == 4
