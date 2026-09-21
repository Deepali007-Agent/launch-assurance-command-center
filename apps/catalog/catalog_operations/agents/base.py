from __future__ import annotations

from ..contracts import AgentAssessment, CatalogItem
from ..enums import AssessmentStatus, Severity
from ..rules import RULE_VERSION


def assessment(item: CatalogItem, agent_name: str, findings: list[dict], score: float, actions: list[str]) -> AgentAssessment:
    critical = any(f["severity"] == Severity.CRITICAL.value for f in findings)
    warnings = any(f["severity"] == Severity.WARNING.value for f in findings)
    status = AssessmentStatus.FAIL if critical else AssessmentStatus.PASS_WITH_WARNINGS if warnings else AssessmentStatus.PASS
    severity = Severity.CRITICAL if critical else Severity.WARNING if warnings else Severity.NONE
    return AgentAssessment(
        agent_name=agent_name, domain="CATALOG_OPERATIONS", entity_type="SKU",
        entity_id=item.sku, workflow_run_id=item.workflow_run_id, status=status,
        readiness_score=max(0.0, min(100.0, round(score, 1))), severity=severity,
        findings=findings, recommended_actions=list(dict.fromkeys(actions)), rule_version=RULE_VERSION,
    )
