"""Platform-owned contracts for orchestrating immutable external agents."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import math
from uuid import uuid4


REQUIRED_AGENT_IDS = (
    "onboarding_intelligence",
    "catalog_iq",
    "po_intelligence",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentAssessment:
    agent_id: str
    label: str
    score: float
    status: str
    total_records: int
    ready_records: int
    warning_records: int
    blocked_records: int
    financial_exposure: float = 0.0
    findings: list[dict[str, Any]] = field(default_factory=list)
    identifiers: set[str] = field(default_factory=set)
    source_file: str = ""
    source_run_id: str = ""
    contract_version: str = "agent-assessment-1.0"
    generated_at: str = field(default_factory=utc_now)
    business_cycle_id: str = ""
    release_blockers: list[str] = field(default_factory=list)
    rule_version: str = "retail-cycle-controls-2.0"

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError(
                f"AgentAssessment score must be between 0 and 100; "
                f"received {self.score}."
            )

        counts = (self.total_records, self.ready_records, self.warning_records, self.blocked_records)
        if any(type(n) is not int or n < 0 for n in counts) or sum(counts[1:]) != counts[0]:
            raise ValueError('Assessment counts must be nonnegative integers and reconcile to total records.')
        if not math.isfinite(self.financial_exposure) or self.financial_exposure < 0:
            raise ValueError('Financial exposure must be finite and nonnegative.')

    @property
    def completion_rate(self) -> float:
        if not self.total_records:
            return 0.0
        return round(self.ready_records / self.total_records * 100, 1)


@dataclass
class ExecutiveDecision:
    score: float
    decision: str
    status: str
    modules_completed: int
    modules_required: int
    total_records: int
    total_exposure: float | None
    common_identifiers: set[str]
    priorities: list[str]
    rationale: str


@dataclass
class AgentExecution:
    """Platform evidence for one external-agent result; agents remain unchanged."""

    execution_id: str
    orchestration_run_id: str
    agent_id: str
    status: str
    attempt: int = 1
    started_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    source_run_id: str = ""
    error: str | None = None

    @classmethod
    def pending(cls, orchestration_run_id: str, agent_id: str) -> "AgentExecution":
        return cls(
            execution_id=f"EXEC-{uuid4().hex[:16].upper()}",
            orchestration_run_id=orchestration_run_id,
            agent_id=agent_id,
            status="PENDING",
        )


@dataclass
class OrchestrationRun:
    orchestration_run_id: str
    status: str
    required_agents: tuple[str, ...] = REQUIRED_AGENT_IDS
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    decision: str = "NOT EVALUATED"
    human_gate_status: str = "NOT REQUIRED"
