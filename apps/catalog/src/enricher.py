"""
catalog_enricher.py
--------------------
Commerce Intelligence Engine

What this file does:
  1. Reads each product row from the CSV
  2. Evaluates catalog quality and completeness
  3. Sends weak/incomplete products to Gemini AI
  4. Generates enriched commerce intelligence outputs
  5. Returns structured results for Streamlit display
"""

import streamlit as st
import pandas as pd
import json
import math


# ─────────────────────────────────────────────
# GEMINI CONFIGURATION
# Shared AI backbone for future agents
# ─────────────────────────────────────────────

_model = None


def _get_model():
    """Create the Gemini client only when enrichment is actually requested."""
    global _model
    if _model is None:
        try:
            import google.generativeai as genai
        except (ImportError, OSError) as exc:
            raise RuntimeError(
                "Optional Gemini enrichment is unavailable in this environment. "
                "Catalog Operations validation and workflow features remain available."
            ) from exc
        api_key = st.secrets.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not configured. Add it to .streamlit/secrets.toml."
            )
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel("gemini-1.5-flash")
    return _model


def _is_missing(value) -> bool:
    """Treat None, NaN, blank strings, and common null strings as missing."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "null"}


def _safe_number(value, default=0.0) -> float:
    """Return a finite number, falling back for blanks, NaN, and bad input."""
    if _is_missing(value):
        return default
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────
# STEP 1: QUALITY SCORER
# Pure business logic — no AI needed
# ─────────────────────────────────────────────

FIELD_WEIGHTS = {
    "product_name": 20,
    "category": 15,
    "description": 20,
    "color": 10,
    "material": 10,
    "size": 5,
    "tags": 10,
    "price": 10,
}


def score_product(row: dict) -> dict:
    """
    Evaluates product catalog quality.

    Returns:
      - score (0–100)
      - tier
      - missing_fields
      - issues
    """

    score = 0
    missing = []
    issues = []

    for field, weight in FIELD_WEIGHTS.items():

        value = row.get(field, "")

        if not _is_missing(value):
            score += weight
        else:
            missing.append(field)

    # Description quality validation
    desc_value = row.get("description", "")
    desc = "" if _is_missing(desc_value) else str(desc_value).strip()

    if desc and len(desc.split()) < 6:
        score -= 10
        issues.append(
            "Description is too short for customer decision-making"
        )

    # Tag validation
    tags_value = row.get("tags", "")
    tags = "" if _is_missing(tags_value) else str(tags_value).strip()

    if not tags or tags.lower() in ["nan", "none", ""]:
        issues.append("Missing tags — hurts search discoverability")

    # Missing fields summary
    if missing:
        issues.append(f"Missing fields: {', '.join(missing)}")

    # Clamp score
    score = max(0, min(100, score))

    # Tier assignment
    if score >= 75:
        tier = "🟢 Good"
    elif score >= 45:
        tier = "🟡 Needs Work"
    else:
        tier = "🔴 Poor"

    return {
        "score": score,
        "tier": tier,
        "missing_fields": missing,
        "issues": issues
    }

# ====================================================
# AGENT 1 : CATALOG HEALTH AGENT
# ====================================================

def catalog_health_agent(df):
    if df is None or df.empty:
        return {
            "catalog_health": 0,
            "total_products": 0,
            "critical_products": 0,
            "missing_descriptions": 0,
            "missing_tags": 0,
            "missing_color": 0,
            "missing_description_by_subcategory": {},
            "missing_tags_by_brand": {},
            "root_causes": [],
            "most_common_issues": [],
            "critical_product_list": []
        }

    total_products = len(df)

    def safe_col(col):
        if col in df.columns:
            return df[col].fillna("").astype(str).str.strip()
        return pd.Series([""] * total_products, index=df.index)

    def missing_count(col):
        return safe_col(col).eq("").sum()

    missing_descriptions = int(missing_count("description"))
    missing_tags = int(missing_count("tags"))
    missing_color = int(missing_count("color"))

    scores = []
    issue_counter = {}
    critical_product_list = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        q = score_product(row_dict)
        scores.append(q["score"])

        if q["score"] < 45:
            critical_product_list.append({
                "product_id": row_dict.get("product_id", ""),
                "product_name": row_dict.get("product_name", ""),
                "brand": row_dict.get("brand", "Unknown"),
                "subcategory": row_dict.get("subcategory", "Unknown"),
                "vendor_name": row_dict.get("vendor_name", "Unknown"),
                "score": q["score"],
                "issues": q["issues"]
            })

        for issue in q.get("issues", []):
            issue_counter[issue] = issue_counter.get(issue, 0) + 1

    catalog_health = round(sum(scores) / max(len(scores), 1), 0)

    most_common_issues = [
        {"issue": issue, "count": count}
        for issue, count in sorted(
            issue_counter.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
    ]

    # Missing description by subcategory
    if "subcategory" in df.columns:
        missing_desc_df = df[safe_col("description").eq("")]
        missing_description_by_subcategory = (
            missing_desc_df.groupby("subcategory")
            .size()
            .sort_values(ascending=False)
            .head(5)
            .to_dict()
        )
    else:
        missing_description_by_subcategory = {}

    # Missing tags by brand
    if "brand" in df.columns:
        missing_tags_df = df[safe_col("tags").eq("")]
        missing_tags_by_brand = (
            missing_tags_df.groupby("brand")
            .size()
            .sort_values(ascending=False)
            .head(5)
            .to_dict()
        )
    else:
        missing_tags_by_brand = {}

    # Root cause detection
    root_causes = []

    if missing_descriptions / total_products > 0.25:
        root_causes.append(
            "High missing descriptions indicate weak content readiness before catalog go-live."
        )

    if missing_tags / total_products > 0.25:
        root_causes.append(
            "High missing tags indicate discoverability and search taxonomy gaps."
        )

    if missing_color / total_products > 0.20:
        root_causes.append(
            "Missing color data may impact filtering, customer decisioning, and product findability."
        )

    if len(critical_product_list) / total_products > 0.15:
        root_causes.append(
            "Critical product concentration suggests systemic catalog governance issues."
        )

    return {
        "catalog_health": catalog_health,
        "total_products": total_products,
        "critical_products": len(critical_product_list),
        "missing_descriptions": missing_descriptions,
        "missing_tags": missing_tags,
        "missing_color": missing_color,
        "missing_description_by_subcategory": missing_description_by_subcategory,
        "missing_tags_by_brand": missing_tags_by_brand,
        "root_causes": root_causes,
        "most_common_issues": most_common_issues,
        "critical_product_list": critical_product_list[:10]
    }

def revenue_impact_agent(df):
    if df is None or df.empty:
        return {
            "revenue_at_risk": 0,
            "revenue_recovery_opportunity": 0,
            "top_categories": [],
            "top_brands": [],
            "top_vendors": [],
            "top_products": [],
            "risk_logic": "No data available."
        }

    revenue_at_risk = 0
    category_risk = {}
    brand_risk = {}
    vendor_risk = {}
    risky_products = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()

        monthly_sales = _safe_number(row_dict.get("monthly_sales"))
        if monthly_sales == 0:
            monthly_sales = _safe_number(row_dict.get("price"))

        q = score_product(row_dict)
        score = q["score"]

        description = row_dict.get("description", "")
        tags = row_dict.get("tags", "")
        color = row_dict.get("color", "")

        risk_pct = 0

        if score < 45:
            risk_pct += 0.20
        elif score < 75:
            risk_pct += 0.10

        if _is_missing(description):
            risk_pct += 0.15

        if _is_missing(tags):
            risk_pct += 0.10

        if _is_missing(color):
            risk_pct += 0.05

        return_rate = _safe_number(row_dict.get("return_rate"))
        if return_rate > 0.20:
            risk_pct += 0.10

        rating = _safe_number(row_dict.get("rating"))
        if 0 < rating < 3.5:
            risk_pct += 0.10

        risk_pct = min(risk_pct, 0.50)

        risk_value = monthly_sales * risk_pct
        revenue_at_risk += risk_value

        category = row_dict.get("subcategory", "Unknown")
        brand = row_dict.get("brand", "Unknown")
        vendor = row_dict.get("vendor_name", "Unknown")

        category_risk[category] = category_risk.get(category, 0) + risk_value
        brand_risk[brand] = brand_risk.get(brand, 0) + risk_value
        vendor_risk[vendor] = vendor_risk.get(vendor, 0) + risk_value

        if risk_value > 0:
            risky_products.append({
                "product_id": row_dict.get("product_id", ""),
                "product_name": row_dict.get("product_name", ""),
                "brand": brand,
                "subcategory": category,
                "vendor_name": vendor,
                "quality_score": score,
                "risk_pct": round(risk_pct * 100, 1),
                "risk_value": round(risk_value, 2),
                "issues": q["issues"]
            })

    top_categories = sorted(category_risk.items(), key=lambda x: x[1], reverse=True)[:5]
    top_brands = sorted(brand_risk.items(), key=lambda x: x[1], reverse=True)[:5]
    top_vendors = sorted(vendor_risk.items(), key=lambda x: x[1], reverse=True)[:5]
    top_products = sorted(risky_products, key=lambda x: x["risk_value"], reverse=True)[:10]

    revenue_recovery_opportunity = revenue_at_risk * 0.60

    return {
        "revenue_at_risk": round(revenue_at_risk, 0),
        "revenue_recovery_opportunity": round(revenue_recovery_opportunity, 0),
        "top_categories": top_categories,
        "top_brands": top_brands,
        "top_vendors": top_vendors,
        "top_products": top_products,
        "risk_logic": (
            "Revenue risk is estimated using catalog quality score, missing descriptions, "
            "missing tags, missing color, return risk, rating risk, and sales exposure. "
            "When monthly sales is unavailable, product price is used as a conservative proxy."
        )
    }

# ====================================================
# AGENT 3 : OPPORTUNITY PRIORITIZATION AGENT
# Decision Layer Agent
# ====================================================

def opportunity_prioritization_agent(df, health, revenue):
    opportunities = []

    top_products = revenue.get("top_products", [])
    top_vendors = revenue.get("top_vendors", [])
    top_categories = revenue.get("top_categories", [])
    top_brands = revenue.get("top_brands", [])

    recovery_rate = 0.60

    if top_products:
        total_top_product_risk = sum(p.get("risk_value", 0) for p in top_products)
        opportunities.append({
            "Priority": "P1",
            "Opportunity": "Fix top revenue-risk SKUs",
            "Why it matters": "A small set of SKUs is driving measurable revenue exposure.",
            "Owner": "Catalog Ops",
            "Timeline": "24-48 hrs",
            "Estimated Recovery": round(total_top_product_risk * recovery_rate, 0),
            "Decision": "Start immediate SKU-level remediation."
        })

    if top_categories:
        category, value = top_categories[0]
        opportunities.append({
            "Priority": "P2",
            "Opportunity": f"Stabilize high-risk category: {category}",
            "Why it matters": "Category-level defects indicate a pattern, not isolated SKU issues.",
            "Owner": "Category + Catalog Team",
            "Timeline": "3-5 days",
            "Estimated Recovery": round(value * recovery_rate, 0),
            "Decision": "Run category defect cleanup and readiness review."
        })

    if top_brands:
        brand, value = top_brands[0]
        opportunities.append({
            "Priority": "P3",
            "Opportunity": f"Review brand-level catalog exposure: {brand}",
            "Why it matters": "Brand concentration can impact customer trust and conversion.",
            "Owner": "Brand / Merch Ops",
            "Timeline": "This week",
            "Estimated Recovery": round(value * recovery_rate, 0),
            "Decision": "Prioritize brand-level content correction."
        })

    if top_vendors:
        vendor, value = top_vendors[0]
        opportunities.append({
            "Priority": "P4",
            "Opportunity": f"Vendor governance action: {vendor}",
            "Why it matters": "Recurring vendor defects need ownership and SLA governance.",
            "Owner": "Vendor Governance",
            "Timeline": "Weekly cadence",
            "Estimated Recovery": round(value * recovery_rate, 0),
            "Decision": "Add vendor to weekly defect review."
        })

    if health.get("missing_descriptions", 0) > 0:
        opportunities.append({
            "Priority": "P5",
            "Opportunity": "Create pre-go-live catalog readiness gate",
            "Why it matters": "Prevents future revenue leakage before products go live.",
            "Owner": "Catalog Ops + Tech",
            "Timeline": "Process change",
            "Estimated Recovery": round(revenue.get("revenue_at_risk", 0) * 0.15, 0),
            "Decision": "Introduce automated readiness validation."
        })

    return opportunities

# ─────────────────────────────────────────────
# STEP 2: AI ENRICHMENT PROMPT
# Executive-grade commerce intelligence prompt
# ─────────────────────────────────────────────

ENRICHMENT_PROMPT = """
You are an expert e-commerce catalog strategist working for enterprise retail organizations.

Your role is NOT just rewriting descriptions.

You improve:
- discoverability
- search ranking
- conversion readiness
- customer clarity
- merchandising quality
- catalog completeness

You will receive weak or incomplete catalog data.

PRODUCT DATA:
{product_json}

QUALITY ISSUES DETECTED:
{issues}

TASK:
Return ONLY a valid JSON object with EXACTLY these fields:

{{
  "enriched_description": "A compelling SEO-friendly product description. 2-3 sentences. Minimum 20 words.",

  "suggested_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],

  "inferred_color": "Best inferred or validated color",

  "inferred_material": "Best inferred or validated material",

  "seo_title": "Search-optimized product title under 60 characters",

  "quality_explanation": "Biggest catalog issue and why it impacts sales or discoverability"
}}

RULES:
- Return ONLY valid JSON
- No markdown
- No explanation outside JSON
- Make intelligent inferences from category and title
- Tags should reflect e-commerce search behavior
- Tone should sound premium and natural
"""


# ─────────────────────────────────────────────
# STEP 3: CALL GEMINI AI
# Sends catalog intelligence request to Gemini
# ─────────────────────────────────────────────

def enrich_product(row: dict, quality: dict) -> dict:
    """
    Sends product catalog data to Gemini AI for enrichment.

    Returns:
        Structured enrichment response
    """

    # Only send customer-facing catalog fields to Gemini
    ENRICHMENT_FIELDS = [
        "product_id",
        "product_name",
        "category",
        "subcategory",
        "description",
        "color",
        "material",
        "size",
        "tags",
        "price"
    ]

    clean_row = {
        k: (None if _is_missing(v) else v) for k, v in row.items()
        if k in ENRICHMENT_FIELDS
    }

    # Build prompt
    prompt = ENRICHMENT_PROMPT.format(
        product_json=json.dumps(clean_row, indent=2),
        issues="\n".join(
            f"- {i}" for i in quality["issues"]
        ) or "- No major issues detected"
    )

    try:

        # Generate AI response
        response = _get_model().generate_content(prompt)

        raw = response.text.strip()

        # Clean markdown wrappers if Gemini returns them
        if raw.startswith("```"):

            raw = raw.split("```")[1]

            if raw.startswith("json"):
                raw = raw[4:]

        raw = raw.strip()

        # Parse JSON safely
        enriched = json.loads(raw)

        return {
            "success": True,
            "data": enriched
        }

    except json.JSONDecodeError:

        return {
            "success": False,
            "error": "Gemini returned invalid JSON",
            "raw": raw
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }

def process_catalog(df: pd.DataFrame) -> list:
    results = []

    ENRICHMENT_FIELDS = [
        "product_id",
        "product_name",
        "category",
        "subcategory",
        "description",
        "color",
        "material",
        "size",
        "tags",
        "price"
    ]

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        quality = score_product(row_dict)

        if quality["score"] < 75:
            clean_row = {
                k: v for k, v in row_dict.items()
                if k in ENRICHMENT_FIELDS
            }

            enrichment = enrich_product(clean_row, quality)

        else:
            enrichment = {
                "success": True,
                "data": {
                    "quality_explanation": "Product data already meets quality standards."
                }
            }

        results.append({
            "product_id": row_dict.get("product_id", ""),
            "product_name": row_dict.get("product_name", ""),
            "original": row_dict,
            "quality": quality,
            "enrichment": enrichment
        })

    return results

# ====================================================
# SUBMISSION READINESS AGENT
# ====================================================

def submission_readiness_agent(df):
    """
    Evaluates whether submitted items are ready
    to enter the onboarding workflow.
    """

    if df is None or df.empty:
        return {
            "submission_readiness": 0,
            "ready_items": 0,
            "needs_attention": 0,
            "critical_items": 0,
            "results": []
        }

    results = []

    ready = 0
    attention = 0
    critical = 0

    total_score = 0

    for _, row in df.iterrows():

        quality = score_product(row.to_dict())

        score = quality["score"]

        total_score += score

        if score >= 85:
            status = "🟢 Ready for Submission"
            ready += 1

        elif score >= 60:
            status = "🟡 Needs Minor Corrections"
            attention += 1

        else:
            status = "🔴 Needs Major Corrections"
            critical += 1

        recommendations = []

        for field in quality["missing_fields"]:
            recommendations.append(f"Complete {field}")

        results.append({
            "product_id": row.get("product_id", ""),
            "product_name": row.get("product_name", ""),
            "score": score,
            "status": status,
            "missing_fields": quality["missing_fields"],
            "recommendations": recommendations
        })

    submission_score = round(total_score / len(df), 0)

    return {
        "submission_readiness": submission_score,
        "ready_items": ready,
        "needs_attention": attention,
        "critical_items": critical,
        "results": results
    }
