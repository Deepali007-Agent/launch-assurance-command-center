"""Map deterministic PO results into shared retail assessment contracts."""

from typing import Any

from domain.contracts import AgentFinding, AssessmentStatus, Severity


STATUS_MAP = {
    "PASS": AssessmentStatus.CLEAR,
    "WARN": AssessmentStatus.WARNING,
    "FAIL": AssessmentStatus.BLOCKED,
}

RISK_MAP = {
    "CLEAR": Severity.INFO,
    "LOW": Severity.LOW,
    "MEDIUM": Severity.MEDIUM,
    "HIGH": Severity.HIGH,
}


def results_to_assessments(
    results: list[dict[str, Any]],
) -> tuple[list[AgentFinding], list[dict[str, str]]]:
    assessments: list[AgentFinding] = []
    identifiers: list[dict[str, str]] = []

    for result in results:
        entity_id = (
            result.get("sku")
            or result.get("style_id")
            or f"{result.get('po_id', 'UNKNOWN')}:{result.get('row_index', 0)}"
        )
        issues = [
            issue.replace("<b>", "").replace("</b>", "")
            for issue in result.get("errors", []) + result.get("warnings", [])
        ]
        if result.get("status") == "FAIL":
            actions = ["Correct blocking PO fields before submission."]
        elif result.get("status") == "WARN":
            actions = ["Review warnings before final PO release."]
        else:
            actions = ["No corrective action required."]

        assessments.append(
            AgentFinding(
                agent="po_validation_agent",
                entity_type="po_line",
                entity_id=str(entity_id),
                status=STATUS_MAP.get(
                    result.get("status"),
                    AssessmentStatus.NOT_EVALUATED,
                ),
                score=float(result.get("readiness", 0)),
                severity=RISK_MAP.get(
                    result.get("risk"),
                    Severity.MEDIUM,
                ),
                issues=issues,
                actions=actions,
                evidence=list(result.get("error_types", [])),
                metrics={
                    "revenue": result.get("revenue", 0),
                    "margin_pct": result.get("margin_pct"),
                    "margin_gap": result.get("margin_gap", 0),
                    "sla_window_days": result.get("window_days"),
                },
                confidence=1.0,
            )
        )
        identifiers.append(
            {
                "vendor_id": str(result.get("vendor_id", "")),
                "sku": str(result.get("sku", "")),
                "po_id": str(result.get("po_id", "")),
            }
        )

    return assessments, identifiers

