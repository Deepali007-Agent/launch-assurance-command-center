from src.enricher import score_product


def test_existing_catalog_scoring_still_works(valid_row):
    legacy = dict(valid_row)
    legacy.update(product_id=legacy.pop("sku"), color=legacy.pop("colour"), tags="kurti,cotton")
    result = score_product(legacy)
    assert 0 <= result["score"] <= 100
    assert {"score", "tier", "missing_fields", "issues"} <= result.keys()
