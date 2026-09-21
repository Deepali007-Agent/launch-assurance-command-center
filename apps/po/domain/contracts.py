"""Shared contracts used by PO Intelligence and future retail agents."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class AssessmentStatus(str, Enum):
    CLEAR = "CLEAR"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NOT_EVALUATED = "NOT_EVALUATED"
    STALE = "STALE"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    domain: str
    source_file: str
    row_count: int
    validated_at: str

    @classmethod
    def create(cls, source_file: str, row_count: int) -> "RunMetadata":
        return cls(
            run_id=f"PO-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
            domain="purchase_order",
            source_file=source_file,
            row_count=row_count,
            validated_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass
class AgentFinding:
    agent: str
    entity_type: str
    entity_id: str
    status: AssessmentStatus
    score: float
    severity: Severity
    issues: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CrossDomainContext:
    onboarding_status: AssessmentStatus = AssessmentStatus.NOT_EVALUATED
    catalog_status: AssessmentStatus = AssessmentStatus.NOT_EVALUATED
    onboarding_run_id: str | None = None
    catalog_run_id: str | None = None

    @property
    def is_complete(self) -> bool:
        evaluated = {
            AssessmentStatus.CLEAR,
            AssessmentStatus.WARNING,
            AssessmentStatus.BLOCKED,
        }
        return (
            self.onboarding_status in evaluated
            and self.catalog_status in evaluated
        )

