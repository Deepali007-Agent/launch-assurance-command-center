from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .enums import AssessmentStatus, DomainDecisionType, LifecycleStatus, Severity


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ValidationMessage:
    field: str
    code: str
    message: str
    severity: Severity = Severity.CRITICAL


@dataclass(slots=True)
class CatalogItem:
    sku: str
    vendor_id: str
    vendor_name: str
    product_name: str
    brand: str
    category: str
    description: str
    price: Decimal | None
    gtin: str
    image_url: str
    colour: str
    size: str
    material: str
    submitted_at: datetime
    workflow_run_id: str
    source_record: dict[str, Any] = field(default_factory=dict)
    revision_number: int = 1
    lifecycle_status: LifecycleStatus = LifecycleStatus.RECEIVED

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["price"] = float(self.price) if self.price is not None else None
        result["submitted_at"] = self.submitted_at.isoformat()
        result["lifecycle_status"] = self.lifecycle_status.value
        return result


@dataclass(slots=True)
class AgentAssessment:
    agent_name: str
    domain: str
    entity_type: str
    entity_id: str
    workflow_run_id: str
    status: AssessmentStatus
    readiness_score: float
    severity: Severity
    findings: list[dict[str, Any]]
    recommended_actions: list[str]
    evaluated_at: datetime = field(default_factory=utc_now)
    rule_version: str = "1.0"

    @property
    def critical_findings(self) -> list[dict[str, Any]]:
        return [f for f in self.findings if f.get("severity") == Severity.CRITICAL.value]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("status", "severity"):
            result[key] = getattr(self, key).value
        result["evaluated_at"] = self.evaluated_at.isoformat()
        return result


@dataclass(slots=True)
class DomainDecision:
    sku: str
    workflow_run_id: str
    decision: DomainDecisionType
    composite_readiness: float
    critical_blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommended_actions: list[str]
    decided_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["decision"] = self.decision.value
        result["decided_at"] = self.decided_at.isoformat()
        return result


@dataclass(slots=True)
class DomainEvent:
    event_id: str
    event_type: str
    domain: str
    entity_type: str
    entity_id: str
    workflow_run_id: str
    previous_status: str
    new_status: str
    reason_code: str
    source: str
    occurred_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["occurred_at"] = self.occurred_at.isoformat()
        return result


@dataclass(slots=True)
class ReworkEvent:
    rework_id: str
    sku: str
    vendor_id: str
    workflow_stage: str
    attribute_name: str
    previous_value: Any
    updated_value: Any
    reason_code: str
    source: str
    revision_number: int
    opened_at: datetime
    resolved_at: datetime | None
    resolution_hours: float | None
    downstream_impact: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("opened_at", "resolved_at"):
            value = result[key]
            result[key] = value.isoformat() if value else None
        return result


@dataclass(slots=True)
class CatalogDomainSnapshot:
    evaluated_skus: int = 0
    ready_skus: int = 0
    rework_skus: int = 0
    held_skus: int = 0
    pending_approval_skus: int = 0
    average_readiness: float = 0.0
    first_time_right_rate: float = 0.0
    rework_rate: float = 0.0
    critical_blocker_count: int = 0
    modeled_revenue_exposure: float = 0.0
    top_bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    priority_actions: list[dict[str, Any]] = field(default_factory=list)
    last_updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["last_updated_at"] = self.last_updated_at.isoformat() if self.last_updated_at else None
        return result


@dataclass(slots=True)
class IngestionResult:
    workflow_run_id: str
    items: list[CatalogItem]
    errors: list[ValidationMessage]
    warnings: list[ValidationMessage]
    original_records: list[dict[str, Any]]
