import pandas as pd

from catalog_operations.ingestion import ingest_dataframe


def test_csv_schema_validation(valid_df):
    result = ingest_dataframe(valid_df)
    assert len(result.items) == 1
    assert not result.errors
    assert result.workflow_run_id


def test_canonical_mapping_preserves_source_record(valid_row):
    valid_row["product_id"] = valid_row.pop("sku")
    valid_row["color"] = valid_row.pop("colour")
    valid_row["unexpected_source_value"] = "preserved"
    result = ingest_dataframe(pd.DataFrame([valid_row]))
    assert result.items[0].sku == "SKU-1001"
    assert result.items[0].colour == "Blue"
    assert result.items[0].source_record["unexpected_source_value"] == "preserved"
    assert any(w.code == "UNKNOWN_COLUMN" for w in result.warnings)


def test_duplicate_sku_is_rejected(valid_row):
    result = ingest_dataframe(pd.DataFrame([valid_row, valid_row]))
    assert len(result.items) == 1
    assert any(e.code == "DUPLICATE_SKU" for e in result.errors)


def test_missing_required_column_returns_clear_error(valid_df):
    result = ingest_dataframe(valid_df.drop(columns=["sku"]))
    assert not result.items
    assert any(e.code == "MISSING_COLUMN" and e.field == "sku" for e in result.errors)


def test_invalid_price_and_gtin_are_rejected(valid_row):
    valid_row.update(price="not-money", gtin="12345678")
    result = ingest_dataframe(pd.DataFrame([valid_row]))
    assert not result.items
    assert {e.code for e in result.errors} >= {"INVALID_PRICE", "INVALID_GTIN"}
