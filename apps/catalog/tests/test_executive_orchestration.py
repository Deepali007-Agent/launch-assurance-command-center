import pandas as pd

from catalog_operations.executive_orchestrator import ExecutiveOrchestrator
from catalog_operations.intelligence import build_intelligence
from catalog_operations.services import process_upload


def test_current_repository_outputs_are_synchronized(valid_df, repository):
    process_upload(valid_df, "current.csv", repository)
    output = build_intelligence(repository)

    assert output["orchestration"]["contract_version"] == "executive-orchestration-1.0"
    assert output["orchestration"]["synchronization"]["status"] == "VERIFIED"
    assert output["executive"]["provenance"]["source_sku_count"] == 1
    assert output["orchestration"]["domain_contracts"]["revenue"]["authority"] == "REVENUE_IMPACT"


def test_stale_agent_output_blocks_executive_decision():
    payload = {
        "catalog": {"decision": "GO", "decision_reason": "Clear"},
        "vendor": [], "division": [],
        "revenue": {"confidence": "High"}, "customer": {"risk_level": "Low"},
        "executive": {"top_actions": []},
    }
    items = [{"sku": "SKU-1", "workflow_run_id": "RUN-2"}]
    assessments = [
        {"entity_id": "SKU-1", "agent_name": "CATALOG_QUALITY_AGENT", "workflow_run_id": "RUN-1"},
        {"entity_id": "SKU-1", "agent_name": "POLICY_VALIDATION_AGENT", "workflow_run_id": "RUN-1"},
    ]
    decisions = [{"sku": "SKU-1", "workflow_run_id": "RUN-1"}]

    output = ExecutiveOrchestrator().compose(payload, items, assessments, decisions)

    assert output["synchronization"]["status"] == "BLOCKED"
    assert output["decision"] == "NOT AVAILABLE"
    assert output["synchronization"]["missing_inputs"]


def test_revalidation_closes_resolved_executive_actions(valid_row, repository):
    defective = dict(valid_row); defective["material"] = ""
    process_upload(pd.DataFrame([defective]), "defective.csv", repository)
    first = build_intelligence(repository)
    assert first["executive"]["governed_actions"]
    assert all(value["status"] == "OPEN" for value in first["executive"]["governed_actions"])

    corrected = dict(valid_row); corrected["material"] = "Cotton"
    process_upload(pd.DataFrame([corrected]), "corrected.csv", repository)
    second = build_intelligence(repository)

    assert second["executive"]["governed_actions"] == []
    history = repository.list_executive_actions()
    assert history and all(value["status"] == "CLOSED" for value in history)
    assert all(value["closure_reason"] == "Resolved by revalidation" for value in history)


def test_action_lifecycle_preserves_assignment(valid_row, repository):
    defective = dict(valid_row); defective["description"] = ""
    process_upload(pd.DataFrame([defective]), "defective.csv", repository)
    action = build_intelligence(repository)["executive"]["governed_actions"][0]
    repository.update_executive_action(action["action_id"], "IN_PROGRESS", "Content Operations")

    refreshed = build_intelligence(repository)["executive"]["governed_actions"]
    current = next(value for value in refreshed if value["action_id"] == action["action_id"])
    assert current["status"] == "IN_PROGRESS"
    assert current["owner"] == "Content Operations"


def test_complete_defect_to_recovery_journey(valid_row, repository):
    defective = dict(valid_row)
    defective.update(material="", monthly_sales=100000, gross_margin_pct=40)
    first_run = process_upload(pd.DataFrame([defective]), "defective.csv", repository)
    before = build_intelligence(repository)

    assert first_run.evaluations[0][1].critical_blockers
    assert before["executive"]["decision"] in {"HOLD", "PARTIAL HOLD"}
    assert before["revenue"]["revenue_at_risk"] > 0
    assert before["executive"]["governed_actions"]
    assert len(repository.list_item_versions(valid_row["sku"])) == 1

    corrected = dict(valid_row)
    corrected.update(material="Cotton", monthly_sales=100000, gross_margin_pct=40)
    second_run = process_upload(pd.DataFrame([corrected]), "corrected.csv", repository)
    after = build_intelligence(repository)

    assert not second_run.evaluations[0][1].critical_blockers
    assert after["executive"]["decision"] == "GO"
    assert after["revenue"]["revenue_at_risk"] == 0
    assert after["executive"]["governed_actions"] == []
    assert len(repository.list_item_versions(valid_row["sku"])) == 2
    assert any(value["event_type"] == "VALIDATION_COMPLETED" for value in repository.list_events(valid_row["sku"]))
    assert repository.list_executive_actions()
    assert all(value["status"] == "CLOSED" for value in repository.list_executive_actions())
