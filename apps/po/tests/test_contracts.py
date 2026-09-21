import unittest

from domain.contracts import (
    AssessmentStatus,
    CrossDomainContext,
    RunMetadata,
)


class ContractTests(unittest.TestCase):
    def test_run_metadata_has_traceable_id(self):
        metadata = RunMetadata.create("sample.csv", 12)

        self.assertTrue(metadata.run_id.startswith("PO-"))
        self.assertEqual(metadata.domain, "purchase_order")
        self.assertEqual(metadata.source_file, "sample.csv")
        self.assertEqual(metadata.row_count, 12)

    def test_cross_domain_context_defaults_to_not_evaluated(self):
        context = CrossDomainContext()

        self.assertEqual(
            context.onboarding_status,
            AssessmentStatus.NOT_EVALUATED,
        )
        self.assertEqual(
            context.catalog_status,
            AssessmentStatus.NOT_EVALUATED,
        )
        self.assertFalse(context.is_complete)

    def test_cross_domain_context_is_complete_after_both_assessments(self):
        context = CrossDomainContext(
            onboarding_status=AssessmentStatus.CLEAR,
            catalog_status=AssessmentStatus.WARNING,
        )

        self.assertTrue(context.is_complete)


if __name__ == "__main__":
    unittest.main()

