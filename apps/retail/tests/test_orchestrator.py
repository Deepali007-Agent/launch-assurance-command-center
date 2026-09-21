import unittest

from orchestration.contracts import AgentAssessment
from orchestration.executive import orchestrate


def assessment(agent_id, score=90, blocked=0, warning=0, identifiers=None):
    total = 10
    return AgentAssessment(
        agent_id=agent_id,
        label=agent_id,
        score=score,
        status="BLOCKED" if blocked else ("WARNING" if warning else "READY"),
        total_records=total,
        ready_records=total - blocked - warning,
        warning_records=warning,
        blocked_records=blocked,
        identifiers=set(identifiers or []),
    )


class OrchestratorTests(unittest.TestCase):
    def test_no_upload_is_not_evaluated(self):
        decision = orchestrate({})
        self.assertEqual(decision.status, "NOT EVALUATED")
        self.assertEqual(decision.modules_completed, 0)

    def test_partial_assessment_is_not_final(self):
        decision = orchestrate(
            {"onboarding_intelligence": assessment("onboarding_intelligence")}
        )
        self.assertEqual(decision.decision, "PARTIAL ASSESSMENT")

    def test_blocker_holds_release(self):
        decision = orchestrate(
            {
                "onboarding_intelligence": assessment("onboarding_intelligence"),
                "catalog_iq": assessment("catalog_iq", blocked=1),
                "po_intelligence": assessment("po_intelligence"),
            }
        )
        self.assertEqual(decision.decision, "HOLD RELEASE")
        self.assertEqual(decision.status, "BLOCKED")

    def test_shared_identifier_is_linked(self):
        decision = orchestrate(
            {
                "onboarding_intelligence": assessment(
                    "onboarding_intelligence", identifiers={"SKU-1", "SKU-2"}
                ),
                "catalog_iq": assessment(
                    "catalog_iq", identifiers={"SKU-1", "SKU-3"}
                ),
                "po_intelligence": assessment(
                    "po_intelligence", identifiers={"SKU-1", "SKU-4"}
                ),
            }
        )
        self.assertEqual(decision.common_identifiers, {"SKU-1"})
        self.assertEqual(decision.decision, "APPROVE RELEASE")

    def test_warnings_create_conditional_release(self):
        decision = orchestrate(
            {
                "onboarding_intelligence": assessment("onboarding_intelligence"),
                "catalog_iq": assessment("catalog_iq", warning=1),
                "po_intelligence": assessment("po_intelligence"),
            }
        )
        self.assertEqual(decision.decision, "CONDITIONAL RELEASE")
        self.assertEqual(decision.status, "WARNING")

    def test_zero_record_assessments_are_safe(self):
        empty_assessments = {}
        for agent_id in (
            "onboarding_intelligence",
            "catalog_iq",
            "po_intelligence",
        ):
            empty_assessments[agent_id] = AgentAssessment(
                agent_id=agent_id,
                label=agent_id,
                score=0,
                status="NOT EVALUATED",
                total_records=0,
                ready_records=0,
                warning_records=0,
                blocked_records=0,
            )
        decision = orchestrate(empty_assessments)
        self.assertEqual(decision.total_records, 0)
        self.assertEqual(decision.score, 0)
        self.assertEqual(decision.decision, "NO DATA TO ASSESS")
        self.assertEqual(decision.status, "NOT EVALUATED")


if __name__ == "__main__":
    unittest.main()
