from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .contracts import CatalogDomainSnapshot
from .enums import LifecycleStatus
from .persistence.repository import CatalogRepository

INTAKE_SLA_HOURS = 24.0
APPROVAL_SLA_HOURS = 24.0


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def get_catalog_agent_assessments(repository: CatalogRepository, sku: str | None = None) -> list[dict[str, Any]]:
    return repository.list_assessments(sku)


def get_catalog_domain_events(repository: CatalogRepository, sku: str | None = None) -> list[dict[str, Any]]:
    return repository.list_events(sku)


def get_catalog_rework_metrics(repository: CatalogRepository) -> dict[str, Any]:
    items, events, versions = repository.list_current_items(), repository.list_rework_events(), repository.list_item_versions()
    total = len(items)
    reworked = {e["sku"] for e in events}
    revisions = Counter(v["sku"] for v in versions)
    resolution = [e["resolution_hours"] for e in events if e.get("resolution_hours") is not None]
    by = lambda key: [{key: name, "count": count} for name, count in Counter(e.get(key) or "Unknown" for e in events).most_common()]
    category_by_sku = {item["sku"]: item.get("category") or "Unknown" for item in items}
    category_counts = Counter(category_by_sku.get(e["sku"], "Unknown") for e in events)
    return {
        "first_time_right_rate": round((total - len(reworked)) / total * 100, 1) if total else 0.0,
        "rework_rate": round(len(reworked) / total * 100, 1) if total else 0.0,
        "average_revisions_per_sku": round(sum(revisions.values()) / total, 2) if total else 0.0,
        "average_resolution_hours": round(sum(resolution) / len(resolution), 2) if resolution else 0.0,
        "rework_by_vendor": by("vendor_id"),
        "rework_by_category": [{"category": name, "count": count} for name, count in category_counts.most_common()],
        "rework_by_stage": by("workflow_stage"),
        "rework_by_attribute": by("attribute_name"), "rework_by_source": by("source"),
        "repeated_failure_reasons": by("reason_code"),
        "highest_approval_loops": [{"sku": sku, "revisions": count} for sku, count in revisions.most_common(10) if count > 1],
        "downstream_delay_hours": round(sum(resolution), 2),
    }


def get_catalog_priority_actions(repository: CatalogRepository) -> list[dict[str, Any]]:
    decisions = repository.list_decisions()
    latest = {}
    for d in decisions: latest[d["sku"]] = d
    actions = []
    for sku, decision in latest.items():
        if decision["critical_blockers"]:
            actions.append({"sku": sku, "priority": "P1", "action": decision["recommended_actions"][0] if decision["recommended_actions"] else "Resolve critical blockers", "blocker_count": len(decision["critical_blockers"])})
        elif decision["warnings"]:
            actions.append({"sku": sku, "priority": "P2", "action": decision["recommended_actions"][0] if decision["recommended_actions"] else "Review warnings", "blocker_count": 0})
    return sorted(actions, key=lambda x: (x["priority"], -x["blocker_count"]))


def get_catalog_actionable_summary(repository: CatalogRepository) -> list[dict[str, Any]]:
    """Aggregate latest governed findings into manager-ready remediation queues."""
    assessments = repository.list_assessments()
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for value in assessments:
        latest[(value["entity_id"], value["agent_name"])] = value
    # Consolidate every finding for the same business attribute. A SKU is
    # counted once per attribute even when multiple agents or rules flag it.
    affected: dict[str, set[str]] = {}
    severities: dict[str, str] = {}
    for (sku, _), value in latest.items():
        for finding in value.get("findings", []):
            field = finding.get("field") or "general"
            affected.setdefault(field, set()).add(sku)
            if finding.get("severity") == "CRITICAL":
                severities[field] = "Critical"
            else:
                severities.setdefault(field, "Warning")
    total = len(repository.list_current_items())
    field_labels = {
        "image_url": "Product image URL", "description": "Description", "product_name": "Product title",
        "brand": "Brand", "colour": "Colour", "size": "Size", "material": "Material",
        "category": "Category", "price": "Price", "gtin": "GTIN", "vendor_id": "Vendor approval",
    }
    action_labels = {
        "image_url": "Add or correct product images", "description": "Improve customer-facing descriptions",
        "product_name": "Improve product titles", "brand": "Complete brand information",
        "colour": "Complete colour attributes", "size": "Complete size attributes",
        "material": "Complete material attributes", "category": "Correct category mapping",
        "price": "Correct price data", "gtin": "Correct product identifiers", "vendor_id": "Resolve vendor approval",
    }
    rows = []
    for field, skus in affected.items():
        count = len(skus)
        rows.append({
            "actionable": field_labels.get(field, field.replace("_", " ").title()),
            "affected_skus": count,
            "composition_pct": round(count / total * 100, 1) if total else 0.0,
            "severity": severities[field],
            "recommended_action": action_labels.get(field, "Review and correct affected records"),
        })
    return sorted(rows, key=lambda row: (row["severity"] != "Critical", -row["affected_skus"], row["actionable"]))


def get_catalog_bottleneck_summary(repository: CatalogRepository) -> list[dict[str, Any]]:
    """Translate validation findings into accountable team-level launch bottlenecks."""
    items = repository.list_current_items()
    total = len(items)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for assessment in repository.list_assessments():
        latest[(assessment["entity_id"], assessment["agent_name"])] = assessment

    validation_completed: dict[str, datetime] = {}
    for event in repository.list_events():
        if event.get("event_type") == "VALIDATION_COMPLETED":
            occurred = _as_datetime(event.get("occurred_at"))
            if occurred:
                validation_completed[event["entity_id"]] = occurred

    field_owners = {
        "image_url": ("Content Operations", "Add or correct product imagery"),
        "description": ("Content Operations", "Improve customer-facing descriptions"),
        "product_name": ("Content Operations", "Correct product titles"),
        "brand": ("Category / Vendor Team", "Complete brand information"),
        "colour": ("Category / Vendor Team", "Complete colour attributes"),
        "size": ("Category / Vendor Team", "Complete size attributes"),
        "material": ("Category / Vendor Team", "Complete material attributes"),
        "category": ("Catalog Governance", "Correct category mapping"),
        "vendor_id": ("Vendor Operations", "Resolve vendor authorization"),
        "vendor_approved": ("Vendor Operations", "Resolve vendor authorization"),
        "gtin": ("Master Data", "Correct product identifiers"),
        "price": ("Commercial / Merchandising", "Correct commercial data"),
    }
    now = datetime.now(timezone.utc)
    teams: dict[str, dict[str, Any]] = {}
    for (sku, agent), assessment in latest.items():
        if agent not in {"CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT"}:
            continue
        for finding in assessment.get("findings", []):
            field = finding.get("field") or "general"
            team, action = field_owners.get(field, ("Catalog Operations", "Review governed exception"))
            record = teams.setdefault(team, {
                "team": team, "skus": set(), "fields": set(), "actions": set(),
                "ages": [], "breached_skus": set(), "critical_skus": set(),
            })
            record["skus"].add(sku)
            record["fields"].add(field.replace("_", " ").title())
            record["actions"].add(action)
            completed = validation_completed.get(sku)
            if completed:
                age_days = max(0.0, (now - completed).total_seconds() / 86400)
                record["ages"].append(age_days)
                if age_days > 1:
                    record["breached_skus"].add(sku)
            if finding.get("severity") == "CRITICAL":
                record["critical_skus"].add(sku)

    rows = []
    for record in teams.values():
        count = len(record["skus"])
        average_age = sum(record["ages"]) / len(record["ages"]) if record["ages"] else 0.0
        oldest_age = max(record["ages"], default=0.0)
        rows.append({
            "team": record["team"],
            "affected_skus": count,
            "pipeline_pct": round(count / total * 100, 1) if total else 0.0,
            "average_age_days": round(average_age, 2),
            "oldest_age_days": round(oldest_age, 2),
            "sla_breaches": len(record["breached_skus"]),
            "critical_skus": len(record["critical_skus"]),
            "estimated_delay_days": round(max(0.0, oldest_age - 1), 2),
            "top_attributes": ", ".join(sorted(record["fields"])[:4]),
            "recommended_action": "; ".join(sorted(record["actions"])[:2]),
        })
    return sorted(rows, key=lambda row: (-row["sla_breaches"], -row["affected_skus"], row["team"]))


def get_catalog_workflow_metrics(repository: CatalogRepository, approval_eligible_skus: set[str] | None = None) -> dict[str, Any]:
    """Calculate intake TAT, approval queue age, and SLA compliance."""
    items = repository.list_current_items()
    events = repository.list_events()
    completed_by_sku: dict[str, datetime] = {}
    for event in events:
        if event.get("event_type") == "VALIDATION_COMPLETED":
            occurred = _as_datetime(event.get("occurred_at"))
            if occurred:
                completed_by_sku[event["entity_id"]] = occurred
    validation_tats, approval_ages = [], []
    approval_breaches = 0
    now = datetime.now(timezone.utc)
    for item in items:
        submitted = _as_datetime(item.get("submitted_at"))
        completed = completed_by_sku.get(item["sku"])
        if submitted and completed:
            validation_tats.append(max(0.0, (completed - submitted).total_seconds() / 3600))
        is_eligible = approval_eligible_skus is None or item["sku"] in approval_eligible_skus
        if item.get("lifecycle_status") == LifecycleStatus.PENDING_HUMAN_APPROVAL.value and completed and is_eligible:
            age = max(0.0, (now - completed).total_seconds() / 3600)
            approval_ages.append(age)
            if age > APPROVAL_SLA_HOURS:
                approval_breaches += 1
    intake_met = sum(value <= INTAKE_SLA_HOURS for value in validation_tats)
    approval_met = sum(value <= APPROVAL_SLA_HOURS for value in approval_ages)
    return {
        "average_intake_tat_hours": round(sum(validation_tats) / len(validation_tats), 1) if validation_tats else 0.0,
        "average_intake_tat_days": round(sum(validation_tats) / len(validation_tats) / 24, 2) if validation_tats else 0.0,
        "intake_sla_hours": INTAKE_SLA_HOURS,
        "intake_sla_days": INTAKE_SLA_HOURS / 24,
        "intake_sla_compliance_pct": round(intake_met / len(validation_tats) * 100, 1) if validation_tats else 0.0,
        "average_approval_queue_age_hours": round(sum(approval_ages) / len(approval_ages), 1) if approval_ages else 0.0,
        "average_approval_queue_age_days": round(sum(approval_ages) / len(approval_ages) / 24, 2) if approval_ages else 0.0,
        "approval_sla_hours": APPROVAL_SLA_HOURS,
        "approval_sla_days": APPROVAL_SLA_HOURS / 24,
        "approval_sla_compliance_pct": round(approval_met / len(approval_ages) * 100, 1) if approval_ages else 0.0,
        "approval_sla_breaches": approval_breaches,
        "approval_queue_size": len(approval_ages),
    }


def get_catalog_domain_snapshot(repository: CatalogRepository) -> dict[str, Any]:
    items, decisions = repository.list_current_items(), repository.list_decisions()
    if not items:
        return CatalogDomainSnapshot().to_dict()
    statuses = Counter(i["lifecycle_status"] for i in items)
    latest = {}
    for d in decisions: latest[d["sku"]] = d
    readiness = [d["composite_readiness"] for d in latest.values()]
    blockers = sum(len(d["critical_blockers"]) for d in latest.values())
    metrics = get_catalog_rework_metrics(repository)
    bottlenecks = metrics["rework_by_attribute"][:5]
    return CatalogDomainSnapshot(
        evaluated_skus=len(items), ready_skus=statuses[LifecycleStatus.ERP_HANDOFF_READY.value],
        rework_skus=statuses[LifecycleStatus.REWORK_REQUIRED.value], held_skus=statuses[LifecycleStatus.ON_HOLD.value],
        pending_approval_skus=statuses[LifecycleStatus.PENDING_HUMAN_APPROVAL.value],
        average_readiness=round(sum(readiness) / len(readiness), 1) if readiness else 0,
        first_time_right_rate=metrics["first_time_right_rate"], rework_rate=metrics["rework_rate"],
        critical_blocker_count=blockers, modeled_revenue_exposure=0.0,
        top_bottlenecks=bottlenecks, priority_actions=get_catalog_priority_actions(repository),
        last_updated_at=datetime.now(timezone.utc),
    ).to_dict()
