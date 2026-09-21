from __future__ import annotations

from uuid import uuid4

from .agents import CatalogQualityAgent, ItemIntakeAgent, ItemReworkAgent, PolicyValidationAgent
from .contracts import AgentAssessment, CatalogItem, DomainDecision, DomainEvent
from .enums import DomainDecisionType, LifecycleStatus, ReworkReason, ReworkSource, Severity
from .persistence.repository import CatalogRepository


class CatalogOperationsOrchestrator:
    def __init__(self, repository: CatalogRepository):
        self.repository = repository
        self.intake = ItemIntakeAgent()
        self.quality = CatalogQualityAgent()
        self.policy = PolicyValidationAgent()
        self.rework = ItemReworkAgent()

    def _event(self, item: CatalogItem, event_type: str, previous: LifecycleStatus, new: LifecycleStatus, reason: str, source: str = "SYSTEM") -> DomainEvent:
        return DomainEvent(str(uuid4()), event_type, "CATALOG_OPERATIONS", "SKU", item.sku,
            item.workflow_run_id, previous.value, new.value, reason, source)

    @staticmethod
    def decide(item: CatalogItem, assessments: list[AgentAssessment]) -> DomainDecision:
        weights = {"ITEM_INTAKE_AGENT": .25, "CATALOG_QUALITY_AGENT": .35, "POLICY_VALIDATION_AGENT": .30, "ITEM_REWORK_AGENT": .10}
        composite = round(sum(a.readiness_score * weights[a.agent_name] for a in assessments), 1)
        unique: dict[tuple[str, str], dict] = {}
        for a in assessments:
            for value in a.findings:
                unique[(value.get("code", ""), value.get("field", ""))] = value
        blockers = [v for v in unique.values() if v.get("severity") == Severity.CRITICAL.value]
        warnings = [v for v in unique.values() if v.get("severity") == Severity.WARNING.value]
        actions = list(dict.fromkeys(action for a in assessments for action in a.recommended_actions))
        if blockers:
            decision = DomainDecisionType.REWORK_REQUIRED
        elif composite >= 80:
            decision = DomainDecisionType.APPROVE
        else:
            decision = DomainDecisionType.CONDITIONAL_APPROVAL
        return DomainDecision(item.sku, item.workflow_run_id, decision, composite, blockers, warnings, actions)

    def evaluate(self, item: CatalogItem, source: str = ReworkSource.VENDOR.value, reason_code: str = ReworkReason.VENDOR_REQUESTED_AMENDMENT.value) -> tuple[list[AgentAssessment], DomainDecision]:
        previous = self.repository.get_current_item(item.sku)
        item.revision_number = previous.revision_number + 1 if previous else 1
        item.lifecycle_status = LifecycleStatus.VALIDATING
        rework_assessment, rework_events = self.rework.compare(previous, item, source, reason_code)
        assessments = [self.intake.evaluate(item), self.quality.evaluate(item), self.policy.evaluate(item), rework_assessment]
        decision = self.decide(item, assessments)
        final_status = LifecycleStatus.REWORK_REQUIRED if decision.critical_blockers else LifecycleStatus.PENDING_HUMAN_APPROVAL
        item.lifecycle_status = final_status
        initial = previous.lifecycle_status if previous else LifecycleStatus.RECEIVED
        events = [self._event(item, "VALIDATION_STARTED", initial, LifecycleStatus.VALIDATING, "WORKFLOW_EVALUATION")]
        events.append(self._event(item, "VALIDATION_COMPLETED", LifecycleStatus.VALIDATING, final_status, decision.decision.value))
        self.repository.save_item_version(item)
        self.repository.save_assessments(assessments)
        self.repository.save_decision(decision)
        self.repository.save_rework_events(rework_events)
        self.repository.save_events(events)
        return assessments, decision

    def transition(self, sku: str, action: str, reason_code: str, source: str = "HUMAN") -> LifecycleStatus:
        item = self.repository.get_current_item(sku)
        if not item:
            raise KeyError(f"Unknown SKU: {sku}")
        if action == "RELEASE_HOLD":
            if item.lifecycle_status != LifecycleStatus.ON_HOLD:
                raise ValueError(f"RELEASE_HOLD is not allowed from {item.lifecycle_status.value}.")
            latest = self.repository.list_decisions(sku)
            has_blockers = bool(latest and latest[-1].get("critical_blockers"))
            target = LifecycleStatus.REWORK_REQUIRED if has_blockers else LifecycleStatus.PENDING_HUMAN_APPROVAL
            previous = item.lifecycle_status
            self.repository.update_status(sku, target)
            self.repository.save_events([self._event(item, action, previous, target, reason_code, source)])
            return target
        transitions = {
            "APPROVE": ({LifecycleStatus.PENDING_HUMAN_APPROVAL, LifecycleStatus.READY_FOR_APPROVAL}, LifecycleStatus.APPROVED),
            "PREPARE_ERP_HANDOFF": ({LifecycleStatus.APPROVED}, LifecycleStatus.ERP_HANDOFF_READY),
            "RETURN_FOR_REWORK": ({LifecycleStatus.PENDING_HUMAN_APPROVAL, LifecycleStatus.APPROVED}, LifecycleStatus.REWORK_REQUIRED),
            "PLACE_ON_HOLD": ({LifecycleStatus.PENDING_HUMAN_APPROVAL, LifecycleStatus.REWORK_REQUIRED, LifecycleStatus.APPROVED}, LifecycleStatus.ON_HOLD),
            "MARK_CREATED_IN_ERP_SIMULATION": ({LifecycleStatus.ERP_HANDOFF_READY}, LifecycleStatus.CREATED_IN_ERP_SIMULATED),
        }
        if action not in transitions:
            raise ValueError(f"Unsupported workflow action: {action}")
        allowed, target = transitions[action]
        if item.lifecycle_status not in allowed:
            raise ValueError(f"{action} is not allowed from {item.lifecycle_status.value}.")
        if action in {"APPROVE", "PREPARE_ERP_HANDOFF"}:
            latest = self.repository.list_decisions(sku)
            if not latest or latest[-1].get("critical_blockers"):
                raise ValueError("Critical blockers prevent approval and ERP-ready handoff.")
        previous = item.lifecycle_status
        self.repository.update_status(sku, target)
        self.repository.save_events([self._event(item, action, previous, target, reason_code, source)])
        return target
