"""Deterministic cross-domain orchestration and release decision engine."""

from orchestration.contracts import AgentAssessment, ExecutiveDecision


WEIGHTS = {
    "onboarding_intelligence": 0.30,
    "catalog_iq": 0.30,
    "po_intelligence": 0.40,
}

if abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:
    raise ValueError("Executive orchestration weights must total 1.0.")


def orchestrate(
    assessments: dict[str, AgentAssessment],
) -> ExecutiveDecision:
    available = [
        assessment
        for agent_id, assessment in assessments.items()
        if agent_id in WEIGHTS
    ]
    if not available:
        return ExecutiveDecision(
            score=0,
            decision="UPLOAD DATA",
            status="NOT EVALUATED",
            modules_completed=0,
            modules_required=3,
            total_records=0,
            total_exposure=0,
            common_identifiers=set(),
            priorities=["Upload at least one agent-specific file to begin."],
            rationale="No agent assessment has run.",
        )

    total_records = sum(item.total_records for item in available)
    if total_records == 0:
        return ExecutiveDecision(
            score=0,
            decision="NO DATA TO ASSESS",
            status="NOT EVALUATED",
            modules_completed=len(available),
            modules_required=3,
            total_records=0,
            total_exposure=0,
            common_identifiers=set(),
            priorities=["Upload files containing at least one data row."],
            rationale="Agent runs exist, but no retail records were assessed.",
        )

    active_weight = sum(WEIGHTS[item.agent_id] for item in available)
    score = sum(
        item.score * WEIGHTS[item.agent_id] for item in available
    ) / active_weight
    complete = len(available) == 3 and all(item.total_records > 0 for item in available)
    has_blocker = any(item.blocked_records or item.status == "BLOCKED" or item.release_blockers for item in available)
    has_warning = any(item.warning_records for item in available)

    identifier_sets = [{identifier.removeprefix('ITEM:') for identifier in item.identifiers
                        if not identifier.startswith('VENDOR:')} for item in available if item.identifiers]
    common = (
        set.intersection(*identifier_sets)
        if len(identifier_sets) >= 2
        else set()
    )
    priorities = [reason for item in available for reason in item.release_blockers]
    for item in sorted(
        available,
        key=lambda assessment: (
            assessment.blocked_records,
            assessment.financial_exposure,
            100 - assessment.score,
        ),
        reverse=True,
    ):
        if item.blocked_records:
            priorities.append(
                f"{item.label}: remediate {item.blocked_records} blocked records."
            )
        elif item.warning_records:
            priorities.append(
                f"{item.label}: review {item.warning_records} warning records."
            )
    if not priorities:
        priorities.append("All evaluated records meet their domain thresholds.")
    if not complete:
        missing = [
            label
            for agent_id, label in (
                ("onboarding_intelligence", "Onboarding Intelligence"),
                ("catalog_iq", "Catalog IQ Pro"),
                ("po_intelligence", "PO Intelligence"),
            )
            if agent_id not in assessments
        ]
        priorities.append(f"Complete remaining assessment: {', '.join(missing)}.")

    if not complete:
        decision, status = "PARTIAL ASSESSMENT", "NOT EVALUATED"
    elif has_blocker:
        decision, status = "HOLD RELEASE", "BLOCKED"
    elif has_warning:
        decision, status = "CONDITIONAL RELEASE", "WARNING"
    else:
        decision, status = "APPROVE RELEASE", "READY"

    linkage = (
        f"{len(common)} identifiers overlap across evaluated domains."
        if common
        else "No shared identifiers were found; portfolio-level aggregation is used."
    )
    rationale = (
        f"{len(available)} of 3 domain controls completed. "
        f"{sum(item.blocked_records for item in available)} blocked control records; "
        "populations overlap and must not be added as unique entities. "
        f"{linkage}"
    )
    return ExecutiveDecision(
        score=round(score, 1),
        decision=decision,
        status=status,
        modules_completed=len(available),
        modules_required=3,
        total_records=total_records,
        total_exposure=None,
        common_identifiers=common,
        priorities=priorities,
        rationale=rationale,
    )
