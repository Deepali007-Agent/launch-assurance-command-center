from catalog_operations.intelligence import build_intelligence_from_records


def _item(sku, vendor, category, monthly_sales, **overrides):
    item = {
        "sku": sku, "vendor_id": vendor, "vendor_name": vendor, "product_name": f"Product {sku}",
        "brand": "Demo", "category": category, "description": "Complete customer-facing description",
        "price": 100, "image_url": "https://example.com/image.jpg", "colour": "Blue",
        "size": "M", "material": "Cotton", "source_record": {"monthly_sales": monthly_sales},
    }
    item.update(overrides)
    return item


def _assessment(sku, status, severity, field):
    findings = [] if severity == "NONE" else [{"severity": severity, "field": field, "message": "Test finding"}]
    return {
        "entity_id": sku, "agent_name": "CATALOG_QUALITY_AGENT", "status": status,
        "readiness_score": 100 if severity == "NONE" else 70, "findings": findings,
    }


def test_standardized_intelligence_contract_and_financial_formula():
    items = [
        _item("SKU-1", "Vendor A", "Fashion", 1000, size=""),
        _item("SKU-2", "Vendor B", "Home", 2000, image_url="bad-url"),
        _item("SKU-3", "Vendor B", "Home", 500),
    ]
    assessments = [
        _assessment("SKU-1", "FAIL", "CRITICAL", "size"),
        _assessment("SKU-2", "PASS_WITH_WARNINGS", "WARNING", "image_url"),
        _assessment("SKU-3", "PASS", "NONE", "general"),
    ]
    decisions = [
        {"sku": "SKU-1", "composite_readiness": 70},
        {"sku": "SKU-2", "composite_readiness": 85},
        {"sku": "SKU-3", "composite_readiness": 100},
    ]

    output = build_intelligence_from_records(items, assessments, decisions)

    assert output["contract_version"] == "catalog-intelligence-2.0"
    assert output["catalog"]["critical_skus"] == 1
    assert output["catalog"]["warning_skus"] == 1
    assert output["catalog"]["clean_skus"] == 1
    assert output["catalog"]["decision"] == "HOLD"
    assert output["revenue"]["revenue_at_risk"] == 590.0
    assert output["revenue"]["expected_recovery"] == 360.5
    assert output["revenue"]["actual_input_coverage"] == 100.0
    assert output["revenue"]["confidence"] == "High"
    assert output["revenue"]["currency"] == "INR"
    assert output["executive"]["top_actions"]


def test_missing_commercial_inputs_are_labeled_modeled():
    item = _item("SKU-1", "Vendor A", "Fashion", None)
    item["source_record"] = {}
    output = build_intelligence_from_records(
        [item], [_assessment("SKU-1", "PASS_WITH_WARNINGS", "WARNING", "description")],
        [{"sku": "SKU-1", "composite_readiness": 90}],
    )

    assert output["revenue"]["confidence"] == "Modeled"
    assert output["revenue"]["actual_input_coverage"] == 0.0
    assert output["revenue"]["revenue_at_risk"] == 120.0


def test_vendor_and_division_risk_uses_uploaded_operating_signals():
    items = [
        _item("SKU-1", "Vendor A", "Fashion", 1000,
              source_record={"monthly_sales": 1000, "vendor_sla": 70, "return_rate": 15, "division": "Apparel"}),
        _item("SKU-2", "Vendor B", "Home", 1000,
              source_record={"monthly_sales": 1000, "vendor_sla": 99, "return_rate": 3, "division": "Homeware"}),
    ]
    assessments = [
        _assessment("SKU-1", "FAIL", "CRITICAL", "description"),
        _assessment("SKU-2", "PASS", "NONE", "general"),
    ]
    decisions = [
        {"sku": "SKU-1", "composite_readiness": 70},
        {"sku": "SKU-2", "composite_readiness": 100},
    ]

    output = build_intelligence_from_records(items, assessments, decisions)

    assert output["vendor"][0]["vendor"] == "Vendor A"
    assert output["vendor"][0]["risk_score"] > output["vendor"][1]["risk_score"]
    assert output["division"][0]["division"] == "Apparel"
    assert output["division"][0]["sla_compliance"] == 70.0
    assert output["sku"][0]["currency"] == "INR"


def test_multiple_distinct_defects_increase_exposure_with_a_governed_cap():
    items = [_item("SKU-1", "Vendor A", "Fashion", 1000, size="", material="")]
    assessments = [{
        "entity_id": "SKU-1", "agent_name": "CATALOG_QUALITY_AGENT", "status": "FAIL",
        "readiness_score": 50,
        "findings": [
            {"severity": "CRITICAL", "field": "size", "message": "Missing size"},
            {"severity": "CRITICAL", "field": "material", "message": "Missing material"},
            {"severity": "WARNING", "field": "image_url", "message": "Missing image"},
        ],
    }]
    output = build_intelligence_from_records(
        items, assessments, [{"sku": "SKU-1", "composite_readiness": 50}],
    )

    assert output["sku"][0]["distinct_defects"] == 3
    assert output["sku"][0]["severity_factor"] == 45.0
    assert output["revenue"]["revenue_at_risk"] == 450.0


def test_small_critical_cohort_creates_partial_hold_not_portfolio_hold():
    items = [_item(f"SKU-{index}", "Vendor A", "Fashion", 1000) for index in range(10)]
    assessments = [_assessment("SKU-0", "FAIL", "CRITICAL", "description")]
    assessments.extend(_assessment(f"SKU-{index}", "PASS", "NONE", "general") for index in range(1, 10))
    decisions = [{"sku": f"SKU-{index}", "composite_readiness": 70 if index == 0 else 100} for index in range(10)]

    output = build_intelligence_from_records(items, assessments, decisions)

    assert output["catalog"]["decision"] == "PARTIAL HOLD"
    assert output["catalog"]["decision_scope"] == "Affected SKUs and scopes"
