from datetime import datetime, timedelta, timezone

import pytest

from orchestration.contracts import AgentAssessment
from orchestration.runtime import OrchestrationLedger


def assessment(agent_id: str, *, blocked: int = 0, generated_at: str | None = None):
    return AgentAssessment(
        agent_id=agent_id,
        label=agent_id,
        score=50 if blocked else 95,
        status="BLOCKED" if blocked else "READY",
        total_records=10,
        ready_records=10 - blocked,
        warning_records=0,
        blocked_records=blocked,
        source_run_id=f"SOURCE-{agent_id}",
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        business_cycle_id="RETAIL-CYCLE-TEST",
    )


def complete_assessments(**overrides):
    values = {
        agent_id: assessment(agent_id)
        for agent_id in ("onboarding_intelligence", "catalog_iq", "po_intelligence")
    }
    values.update(overrides)
    return values


def test_run_waits_for_all_three_agents(tmp_path):
    ledger = OrchestrationLedger(str(tmp_path / "runtime.db"))
    run = ledger.synchronize({"catalog_iq": assessment("catalog_iq")})
    assert run["status"] == "AWAITING_AGENTS"
    assert set(run["missing_agents"]) == {"onboarding_intelligence", "po_intelligence"}
    assert {row["status"] for row in run["executions"]} == {"COMPLETED", "MISSING"}


def test_stale_agent_blocks_human_gate(tmp_path):
    ledger = OrchestrationLedger(str(tmp_path / "runtime.db"))
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    run = ledger.synchronize(complete_assessments(po_intelligence=assessment("po_intelligence", generated_at=old)))
    assert run["status"] == "STALE"
    assert run["stale_agents"] == ["po_intelligence"]
    with pytest.raises(ValueError, match="fresh agent outputs"):
        ledger.decide_human_gate(run["orchestration_run_id"], True, "Buyer", "Approve")


def test_complete_fresh_run_requires_and_records_human_approval(tmp_path):
    ledger = OrchestrationLedger(str(tmp_path / "runtime.db"))
    run = ledger.synchronize(complete_assessments())
    assert run["status"] == "AWAITING_HUMAN_APPROVAL"
    approved = ledger.decide_human_gate(run["orchestration_run_id"], True, "Director", "Release approved")
    assert approved["status"] == "COMPLETED"
    assert approved["human_gate_status"] == "APPROVED"
    assert approved["events"][-1]["actor"] == "Director"


def test_blocked_decision_cannot_be_human_approved(tmp_path):
    ledger = OrchestrationLedger(str(tmp_path / "runtime.db"))
    values = complete_assessments(catalog_iq=assessment("catalog_iq", blocked=1))
    run = ledger.synchronize(values)
    with pytest.raises(ValueError, match="cannot be approved"):
        ledger.decide_human_gate(run["orchestration_run_id"], True, "Director", "Override")
    held = ledger.decide_human_gate(run["orchestration_run_id"], False, "Director", "Catalog remediation")
    assert held["status"] == "REJECTED"
