import unittest
from pathlib import Path
from uuid import uuid4

from domain.assessment_mapper import results_to_assessments
from domain.contracts import AssessmentStatus, RunMetadata
from domain.po_engine import validate_row
from domain.repository import AssessmentRepository
from tests.test_po_engine import valid_row


class RepositoryTests(unittest.TestCase):
    def test_run_assessment_and_decision_round_trip(self):
        database_path = Path(__file__).parent / f"repository_{uuid4().hex}.db"
        try:
            repository = AssessmentRepository(database_path)
            metadata = RunMetadata.create("sample.csv", 1)
            result = validate_row(valid_row(), 0)
            assessments, identifiers = results_to_assessments([result])

            repository.save_run(metadata)
            repository.save_assessments(
                metadata,
                assessments,
                identifiers,
            )
            repository.save_decisions(
                metadata,
                [
                    {
                        "po_id": "PO-1",
                        "recommendation": "PROCEED",
                        "reason": "All checks passed.",
                    }
                ],
            )

            latest = repository.latest_assessment(
                "purchase_order",
                "po_line",
                "STYLE-1",
            )
            counts = repository.run_counts()

            self.assertIsNotNone(latest)
            self.assertEqual(latest["status"], AssessmentStatus.CLEAR.value)
            self.assertEqual(latest["vendor_id"], "V-100")
            self.assertEqual(latest["po_id"], "PO-1")
            self.assertEqual(counts, {"runs": 1, "assessments": 1, "decisions": 1})
        finally:
            if database_path.exists():
                database_path.unlink()


if __name__ == "__main__":
    unittest.main()
