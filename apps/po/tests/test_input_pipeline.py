import unittest

import pandas as pd

from domain.input_pipeline import REQUIRED_COLUMNS, validate_upload


def valid_frame() -> pd.DataFrame:
    row = {column: "value" for column in REQUIRED_COLUMNS}
    row.update(
        {
            "Cost": 10,
            "Reg Retail": 20,
            "Original Retail": 20,
            "Total Quantity": 30,
            "Case-pack": 2,
        }
    )
    return pd.DataFrame([row])


class InputPipelineTests(unittest.TestCase):
    def test_valid_upload_creates_canonical_identifiers(self):
        result = validate_upload(valid_frame())

        self.assertTrue(result.valid)
        self.assertIn("vendor_id", result.dataframe.columns)
        self.assertIn("po_id", result.dataframe.columns)
        self.assertIn("style_id", result.dataframe.columns)

    def test_lowercase_aliases_are_normalized(self):
        frame = valid_frame().rename(
            columns={
                "Vendor ID": "vendor_id",
                "PO_ID": "po_id",
                "Sub-Class": "sub_class",
            }
        )

        result = validate_upload(frame)

        self.assertTrue(result.valid)
        self.assertIn("Vendor ID", result.dataframe.columns)
        self.assertIn("PO_ID", result.dataframe.columns)
        self.assertIn("Sub-Class", result.dataframe.columns)

    def test_missing_columns_are_rejected(self):
        result = validate_upload(pd.DataFrame([{"Vendor ID": "V-1"}]))

        self.assertFalse(result.valid)
        self.assertIn("Missing required columns", result.errors[0])

    def test_empty_upload_is_rejected(self):
        result = validate_upload(pd.DataFrame(columns=REQUIRED_COLUMNS))

        self.assertFalse(result.valid)
        self.assertIn(
            "The uploaded buysheet contains no data rows.",
            result.errors,
        )

    def test_missing_sku_is_explicitly_not_silently_mapped(self):
        result = validate_upload(valid_frame())

        self.assertEqual(result.identifiers["sku"], "")
        self.assertTrue(any("NOT_EVALUATED" in warning for warning in result.warnings))
        self.assertNotIn("sku", result.dataframe.columns)


if __name__ == "__main__":
    unittest.main()

