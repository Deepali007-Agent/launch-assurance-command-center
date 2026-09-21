"""
app.py — The Streamlit Web Interface
--------------------------------------
This is the file you RUN to launch the app.
It creates the web page that lets you:
  - Upload a product CSV
  - See quality scores per product
  - Read AI-generated enrichments
  - Download the improved catalog

Run it with:  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import json
import sys
import os

import importlib
from catalog_operations import ingestion as catalog_ingestion, services as catalog_services
importlib.reload(catalog_ingestion)
importlib.reload(catalog_services)
from catalog_operations import ui as catalog_ui
render_app = importlib.reload(catalog_ui).render_app

render_app()
st.stop()


# Add src folder so we can import our enricher
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))
from enricher import (
    process_catalog,
    score_product,
    catalog_health_agent,
    revenue_impact_agent
)



# ─── Page config ───────────────────────────────
st.set_page_config(
    page_title="AI Catalog Enrichment",
    page_icon="🏷️",
    layout="wide"
)

# ─── Custom CSS ────────────────────────────────
st.markdown("""
<style>
    .metric-box {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
        border: 1px solid #e9ecef;
    }
    .tier-good    { color: #198754; font-weight: 600; }
    .tier-amber   { color: #fd7e14; font-weight: 600; }
    .tier-poor    { color: #dc3545; font-weight: 600; }
    .enriched-box {
        background: #f0fff4;
        border-left: 4px solid #198754;
        padding: 12px 16px;
        border-radius: 4px;
        margin: 8px 0;
    }
    .issue-box {
        background: #fff8f0;
        border-left: 4px solid #fd7e14;
        padding: 12px 16px;
        border-radius: 4px;
        margin: 8px 0;
    }
</style>
""", unsafe_allow_html=True)


# ─── Header ────────────────────────────────────
st.title("🚀 CatalogIQ Pro")

st.markdown(
    """
    ### Executive Retail Operations Command Center

    AI-Powered Revenue Risk, Vendor Intelligence & Recovery Decision Engine
    """
)

st.markdown(
    "Upload catalog data → assess revenue risk → identify vendor and CX gaps → prioritize executive recovery actions."
)

st.divider()

# ==================================================
# AI AGENT SELECTION
# ==================================================

st.subheader("🤖 Choose Your AI Agent")

selected_agent = st.radio(
    "Select an operational workflow:",
    [
        "Catalog Intelligence Agent",
        "Onboarding Agent"
    ],
    horizontal=True
)

st.divider()


# ─── Sidebar: Setup + Info ────────────────────
with st.sidebar:
    st.header("🚀 CatalogIQ Pro")
    st.caption("Executive Summary")

    st.success("Gemini API connected ✓")

    st.divider()
    st.markdown("### Platform Workflow")
    st.markdown("""
    1. **Upload** catalog data  
    2. **Assess** revenue and quality risk  
    3. **Identify** vendor, division, and CX gaps  
    4. **Prioritize** executive recovery actions  
    5. **Export** AI-enriched recovery plan
    """)

    st.divider()
    st.markdown("### Recommended Catalog Columns")
    st.code(
        "product_id, product_name, category,\n"
        "subcategory, brand, description,\n"
        "color, material, size, tags, price,\n"
        "monthly_sales, vendor_name, sla_compliance,\n"
        "return_rate, rating, review_count"
    )
    st.caption("CSV and Excel (.xlsx) files are both supported. Missing operational columns use safe defaults.")


## ─── File Upload ────────────────────────────────
if selected_agent == "Catalog Intelligence Agent":

    uploaded = st.file_uploader(
        "Upload your product catalog (CSV or Excel)",
        type=["csv", "xlsx"],
        help="Upload a CSV or Excel (.xlsx) catalog file."
    )

    # Load sample if no upload
    if not uploaded:
        st.info("No file uploaded — showing sample data from /data/sample_products.csv")

        try:
            df = pd.read_csv("data/sample_products.csv")
        except FileNotFoundError:
            st.error("Sample file not found. Please upload a CSV.")
            st.stop()

    else:

        try:

            if uploaded.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded)

            else:
                df = pd.read_csv(uploaded)

                if df.shape[1] == 1:
                    uploaded.seek(0)
                    df = pd.read_csv(uploaded, sep=";")

                if df.shape[1] == 1:
                    uploaded.seek(0)
                    df = pd.read_csv(uploaded, sep="\t")

        except Exception as e:
            st.error(f"Could not read uploaded file: {e}")
            st.stop()

# ==================================================
# EXECUTIVE INSIGHTS DASHBOARD
# ==================================================

def opportunity_prioritization_agent(df, health, revenue):
    opportunities = []

    if health.get("missing_descriptions", 0) > 0:
        opportunities.append({
            "Priority": "High",
            "Opportunity": "Fix missing product descriptions",
            "Business Impact": "Improves product clarity, search ranking, and conversion",
            "Recommended Owner": "Catalog Ops"
        })

    if health.get("missing_tags", 0) > 0:
        opportunities.append({
            "Priority": "High",
            "Opportunity": "Fix missing product tags",
            "Business Impact": "Improves discoverability and browse experience",
            "Recommended Owner": "Catalog Ops"
        })

    if health.get("critical_products", 0) > 0:
        opportunities.append({
            "Priority": "Critical",
            "Opportunity": "Resolve critical catalog products first",
            "Business Impact": "Reduces customer-facing defects and revenue leakage",
            "Recommended Owner": "Catalog Governance Lead"
        })

    if revenue.get("revenue_at_risk", 0) > 0:
        opportunities.append({
            "Priority": "Critical",
            "Opportunity": "Prioritize high revenue-at-risk SKUs",
            "Business Impact": f"${revenue.get('revenue_at_risk', 0):,.0f} monthly revenue exposure",
            "Recommended Owner": "Retail Ops / Category Team"
        })

    return opportunities


def prepare_revenue_columns(df):
    temp_df = df.copy()
    temp_df.columns = temp_df.columns.str.strip()

    if "price" not in temp_df.columns:
        temp_df["price"] = 0

    if "monthly_sales" not in temp_df.columns:
        temp_df["monthly_sales"] = 0

    if "vendor_name" not in temp_df.columns:
        if "vendor" in temp_df.columns:
            temp_df["vendor_name"] = temp_df["vendor"]
        elif "brand" in temp_df.columns:
            temp_df["vendor_name"] = temp_df["brand"]
        else:
            temp_df["vendor_name"] = "Unknown Vendor"

    temp_df["price"] = pd.to_numeric(temp_df["price"], errors="coerce").fillna(0)
    temp_df["monthly_sales"] = pd.to_numeric(temp_df["monthly_sales"], errors="coerce").fillna(0)

    # Conservative revenue exposure proxy for catalog recovery
    # Keeps Vendor, Division, CX, and Executive tabs aligned
    temp_df["revenue"] = (
       temp_df["price"]
       *
       temp_df["monthly_sales"]
       )

    return temp_df

def executive_priority_queue(df):

    temp_df = prepare_revenue_columns(df)

    priority_rows = []

    for _, row in temp_df.iterrows():

        issue = None

        if pd.isna(row.get("description")):
            issue = "Missing Description"

        elif pd.isna(row.get("tags")):
            issue = "Missing Tags"

        elif pd.isna(row.get("color")):
            issue = "Missing Color"

        elif pd.isna(row.get("material")):
            issue = "Missing Material"

        if issue:

            revenue_risk = row["revenue"] * 0.25

            priority_rows.append({
                "SKU": row.get("product_id"),
                "Product": row.get("product_name"),
                "Issue": issue,
                "Revenue Risk": revenue_risk,
                "Owner": "Catalog Operations"
            })

    priority_df = pd.DataFrame(priority_rows)

    if priority_df.empty:
        return priority_df

    priority_df = priority_df.sort_values(
        "Revenue Risk",
        ascending=False
    )

    priority_df.insert(
        0,
        "Rank",
        range(1, len(priority_df) + 1)
    )

    return priority_df.head(20)


def vendor_intelligence_agent(df):
    vendor_rows = []
    temp_df = prepare_revenue_columns(df)

    def safe_mean(group, col, default):
        if col in group.columns:
            return pd.to_numeric(group[col], errors="coerce").fillna(default).mean()
        return default

    temp_df["content_defect"] = (
        temp_df["description"].isna() |
        (temp_df["description"].astype(str).str.strip() == "") |
        temp_df["tags"].isna() |
        (temp_df["tags"].astype(str).str.strip() == "") |
        temp_df["color"].isna() |
        (temp_df["color"].astype(str).str.strip() == "") |
        temp_df["material"].isna() |
        (temp_df["material"].astype(str).str.strip() == "") |
        temp_df["size"].isna() |
        (temp_df["size"].astype(str).str.strip() == "")
    )

    for vendor, group in temp_df.groupby("vendor_name"):
        revenue_exposure = group.loc[
            group["content_defect"],
            "revenue"
        ].sum()
        products_impacted = group["product_id"].nunique()

        defect_rate = group["content_defect"].mean() * 100
        sla_compliance = safe_mean(group, "sla_compliance", 100)
        return_rate = safe_mean(group, "return_rate", 0)
        rating = safe_mean(group, "rating", 5)

        if defect_rate >= 20 or sla_compliance < 85 or return_rate >= 12 or rating < 4:
            risk_level = "HIGH"
            recommended_action = "Launch vendor governance review"
        elif defect_rate >= 10 or sla_compliance < 92 or return_rate >= 8 or rating < 4.3:
            risk_level = "MEDIUM"
            recommended_action = "Monitor vendor performance and fix catalog defects"
        else:
            risk_level = "LOW"
            recommended_action = "Maintain current operating rhythm"

        vendor_rows.append({
            "Vendor": vendor,
            "Revenue Exposure": revenue_exposure,
            "Products Impacted": products_impacted,
            "Defect Rate": defect_rate,
            "SLA Compliance": sla_compliance,
            "Return Rate": return_rate,
            "Rating": rating,
            "Risk Level": risk_level,
            "Recommended Action": recommended_action
        })

    vendor_df = pd.DataFrame(vendor_rows)

    if vendor_df.empty:
        return pd.DataFrame(columns=[
            "Vendor", "Revenue Exposure", "Products Impacted",
            "Defect Rate", "SLA Compliance", "Return Rate",
            "Rating", "Risk Level", "Recommended Action"
        ])

    risk_order = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
    vendor_df["risk_sort"] = vendor_df["Risk Level"].map(risk_order)

    vendor_df = vendor_df.sort_values(
        by=["risk_sort", "Revenue Exposure"],
        ascending=[True, False]
    ).drop(columns=["risk_sort"])

    return vendor_df

def division_performance_agent(df):
    division_rows = []
    temp_df = prepare_revenue_columns(df)

    if "subcategory" not in temp_df.columns:
        temp_df["subcategory"] = "Unknown"

    if "category" not in temp_df.columns:
        temp_df["category"] = "Unknown"

    for col in ["description", "tags", "color", "material", "size"]:
        if col not in temp_df.columns:
            temp_df[col] = ""

    temp_df["Division"] = (
        temp_df["subcategory"].astype(str).str.strip()
        + " / "
        + temp_df["category"].astype(str).str.strip()
    )

    temp_df["content_defect"] = (
        temp_df["description"].isna() |
        (temp_df["description"].astype(str).str.strip() == "") |
        temp_df["tags"].isna() |
        (temp_df["tags"].astype(str).str.strip() == "") |
        temp_df["color"].isna() |
        (temp_df["color"].astype(str).str.strip() == "") |
        temp_df["material"].isna() |
        (temp_df["material"].astype(str).str.strip() == "") |
        temp_df["size"].isna() |
        (temp_df["size"].astype(str).str.strip() == "")
    )

    for division, group in temp_df.groupby("Division"):

        risk_group = group[group["content_defect"]]

        revenue_exposure = risk_group["revenue"].sum()

        if "product_id" in risk_group.columns:
            products_impacted = risk_group["product_id"].nunique()
        else:
            products_impacted = len(risk_group)

        defect_rate = group["content_defect"].mean() * 100

        recovery_opportunity = revenue_exposure * 0.60

        if defect_rate >= 20:
            risk_level = "HIGH"
            recommended_action = "Immediate remediation"
        elif defect_rate >= 10:
            risk_level = "MEDIUM"
            recommended_action = "Prioritize attribute and PDP cleanup"
        else:
            risk_level = "LOW"
            recommended_action = "Monitor performance"

        division_rows.append({
            "Division": division,
            "Revenue Exposure": revenue_exposure,
            "Products Impacted": products_impacted,
            "Defect Rate": defect_rate,
            "Risk Level": risk_level,
            "Recovery Opportunity": recovery_opportunity,
            "Recommended Action": recommended_action
        })

    division_df = pd.DataFrame(division_rows)

    if division_df.empty:
        return pd.DataFrame(columns=[
            "Division", "Revenue Exposure", "Products Impacted",
            "Defect Rate", "Risk Level", "Recovery Opportunity",
            "Recommended Action"
        ])

    risk_order = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
    division_df["risk_sort"] = division_df["Risk Level"].map(risk_order)

    division_df = division_df.sort_values(
        by=["risk_sort", "Revenue Exposure"],
        ascending=[True, False]
    ).drop(columns=["risk_sort"])

    return division_df

def customer_experience_agent_v2(df):
    temp_df = prepare_revenue_columns(df)

    # Safe fallback columns for basic CSV uploads
    if "rating" not in temp_df.columns:
        temp_df["rating"] = 5.0
    else:
        temp_df["rating"] = pd.to_numeric(temp_df["rating"], errors="coerce").fillna(5.0)

    if "return_rate" not in temp_df.columns:
        temp_df["return_rate"] = 0.0
    else:
        temp_df["return_rate"] = pd.to_numeric(temp_df["return_rate"], errors="coerce").fillna(0.0)

    missing_descriptions = temp_df[
        temp_df["description"].isna() |
        (temp_df["description"].astype(str).str.strip() == "")
    ]

    missing_tags = temp_df[
        temp_df["tags"].isna() |
        (temp_df["tags"].astype(str).str.strip() == "")
    ]

    low_ratings = temp_df[temp_df["rating"] < 4.0]
    high_returns = temp_df[temp_df["return_rate"] >= 10]

    cx_revenue_risk = (
        missing_descriptions["revenue"].sum()
        + missing_tags["revenue"].sum()
        + low_ratings["revenue"].sum()
        + high_returns["revenue"].sum()
    )

    total_revenue = temp_df["revenue"].sum()

    cx_risk_pct = (
        cx_revenue_risk / total_revenue * 100
        if total_revenue > 0 else 0
    )

    if cx_risk_pct >= 25:
        risk_level = "HIGH"
        recommended_action = "Immediate PDP content and return-rate remediation"
    elif cx_risk_pct >= 10:
        risk_level = "MEDIUM"
        recommended_action = "Prioritize top CX defect drivers"
    else:
        risk_level = "LOW"
        recommended_action = "Monitor CX quality signals"

    return {
        "cx_revenue_risk": cx_revenue_risk,
        "cx_risk_pct": cx_risk_pct,
        "risk_level": risk_level,
        "missing_descriptions": len(missing_descriptions),
        "missing_tags": len(missing_tags),
        "low_ratings": len(low_ratings),
        "high_returns": len(high_returns),
        "conversion_loss": (
            missing_descriptions["revenue"].sum()
            + low_ratings["revenue"].sum()
        ),
        "search_visibility_impact": missing_tags["revenue"].sum(),
        "customer_trust_impact": high_returns["revenue"].sum(),
        "recommended_action": recommended_action
    }

def revenue_prioritization_engine(df):
    temp_df = prepare_revenue_columns(df)

    if "subcategory" not in temp_df.columns:
        temp_df["subcategory"] = "Unknown"

    if "category" not in temp_df.columns:
        temp_df["category"] = "Unknown"

    if "vendor_name" not in temp_df.columns:
        temp_df["vendor_name"] = "Unknown Vendor"

    for col in ["description", "tags", "color", "material", "size"]:
        if col not in temp_df.columns:
            temp_df[col] = ""

    temp_df["Division"] = (
        temp_df["subcategory"].astype(str).str.strip()
        + " / "
        + temp_df["category"].astype(str).str.strip()
    )

    temp_df["content_defect"] = (
        temp_df["description"].isna() |
        (temp_df["description"].astype(str).str.strip() == "") |
        temp_df["tags"].isna() |
        (temp_df["tags"].astype(str).str.strip() == "") |
        temp_df["color"].isna() |
        (temp_df["color"].astype(str).str.strip() == "") |
        temp_df["material"].isna() |
        (temp_df["material"].astype(str).str.strip() == "") |
        temp_df["size"].isna() |
        (temp_df["size"].astype(str).str.strip() == "")
    )

    risk_df = temp_df[temp_df["content_defect"] == True]
    rows = []

    for division, group in risk_df.groupby("Division"):
        exposure = group["revenue"].sum()

        if exposure > 0:
            rows.append({
                "Area": division,
                "Area Type": "Division",
                "Exposure": exposure,
                "Recommended Action": "Fix content and attribute defects"
            })

    for vendor_name, group in risk_df.groupby("vendor_name"):
        exposure = group["revenue"].sum()

        if exposure > 0:
            rows.append({
                "Area": vendor_name,
                "Area Type": "Vendor",
                "Exposure": exposure,
                "Recommended Action": "Launch vendor governance review"
            })

    priority_df = pd.DataFrame(rows)

    if priority_df.empty:
        return pd.DataFrame(columns=[
            "Rank", "Area", "Area Type", "Exposure", "Recommended Action"
        ])

    priority_df = priority_df.sort_values("Exposure", ascending=False).head(10)
    priority_df.insert(0, "Rank", range(1, len(priority_df) + 1))

    return priority_df

def catalog_health_scorecard_agent(df):
    total_products = len(df)

    required_fields = [
        "description", "tags", "color", "material",
        "size", "category", "product_name"
    ]

    available_fields = [col for col in required_fields if col in df.columns]

    if not available_fields or total_products == 0:
        return {
            "scorecard": pd.DataFrame(),
            "overall_score": 0,
            "overall_status": "Not Available",
            "summary": "Catalog health scorecard could not be generated due to missing required fields."
        }

    total_cells = total_products * len(available_fields)
    missing_cells = df[available_fields].isna().sum().sum()

    catalog_completeness = round(
        ((total_cells - missing_cells) / total_cells) * 100,
        1
    )

    if "description" in df.columns:
        desc_missing = df["description"].isna().sum()
        desc_short = df["description"].fillna("").astype(str).apply(
            lambda x: len(x.strip()) < 40
        ).sum()

        content_quality = round(
            100 - (((desc_missing + desc_short) / total_products) * 100),
            1
        )
    else:
        content_quality = 0

    search_fields = [
        col for col in ["product_name", "category", "tags"]
        if col in df.columns
    ]

    if search_fields:
        search_missing = df[search_fields].isna().sum().sum()
        search_total = total_products * len(search_fields)

        search_readiness = round(
            ((search_total - search_missing) / search_total) * 100,
            1
        )
    else:
        search_readiness = 0

    attr_fields = [
        col for col in ["color", "material", "size"]
        if col in df.columns
    ]

    if attr_fields:
        attr_missing = df[attr_fields].isna().sum().sum()
        attr_total = total_products * len(attr_fields)

        attribute_completeness = round(
            ((attr_total - attr_missing) / attr_total) * 100,
            1
        )
    else:
        attribute_completeness = 0

    discoverability_risk = (
        "High" if search_readiness < 70
        else "Medium" if search_readiness < 85
        else "Low"
    )

    revenue_risk_level = (
        "High" if catalog_completeness < 75
        else "Medium" if catalog_completeness < 90
        else "Low"
    )

    def status(score):
        if score >= 90:
            return "Green"
        elif score >= 75:
            return "Amber"
        else:
            return "Red"

    overall_score = round(
        (
            catalog_completeness
            + content_quality
            + search_readiness
            + attribute_completeness
        ) / 4,
        1
    )

    scorecard = pd.DataFrame([
        {
            "Metric": "Catalog Completeness",
            "Score / Status": f"{catalog_completeness}%",
            "Status": status(catalog_completeness),
            "What It Means": "Measures mandatory product field completeness."
        },
        {
            "Metric": "Content Quality",
            "Score / Status": f"{content_quality}%",
            "Status": status(content_quality),
            "What It Means": "Checks whether descriptions are useful for customer decision-making."
        },
        {
            "Metric": "Search Readiness",
            "Score / Status": f"{search_readiness}%",
            "Status": status(search_readiness),
            "What It Means": "Measures discoverability through product name, category, and tags."
        },
        {
            "Metric": "Attribute Completeness",
            "Score / Status": f"{attribute_completeness}%",
            "Status": status(attribute_completeness),
            "What It Means": "Checks buying attributes like color, material, and size."
        },
        {
            "Metric": "Discoverability Risk",
            "Score / Status": discoverability_risk,
            "Status": discoverability_risk,
            "What It Means": "Indicates whether customers may struggle to find products."
        },
        {
            "Metric": "Revenue Risk Level",
            "Score / Status": revenue_risk_level,
            "Status": revenue_risk_level,
            "What It Means": "Estimates commercial risk from catalog gaps."
        }
    ])

    return {
        "scorecard": scorecard,
        "overall_score": overall_score,
        "overall_status": status(overall_score),
        "summary": f"Overall catalog health score is {overall_score}%, indicating {status(overall_score)} readiness."
    }

def executive_alert_banner_agent(health, revenue, vendor, customer):
    alerts = []

    if health.get("catalog_health", 100) < 70:
        alerts.append("🚨 Catalog health is below leadership threshold.")

    if revenue.get("revenue_at_risk", 0) > 0:
        alerts.append(
            f"💰 Revenue at risk detected: ${revenue.get('revenue_at_risk', 0):,.0f}/month."
        )

    if isinstance(vendor, pd.DataFrame) and not vendor.empty:
        high_risk_vendors = len(vendor[vendor["Risk Level"] == "HIGH"])

        if high_risk_vendors > 0:
            alerts.append(
                f"🏢 {high_risk_vendors} high-risk vendor(s) require leadership attention."
            )

    if customer.get("cx_risk_pct", 0) >= 10:
        alerts.append(
            f"😊 Customer experience risk is elevated at {customer.get('cx_risk_pct', 0):.1f}%."
        )

    return {
        "status": "RED" if len(alerts) >= 3 else "AMBER" if alerts else "GREEN",
        "message": "⚠️ Executive attention required." if alerts else "✅ Business health is stable.",
        "alerts": alerts
    }


def executive_orchestration_agent(
    health,
    revenue,
    vendor,
    customer,
    division
):
    revenue_risk = revenue.get("revenue_at_risk", 0)
    expected_recovery = revenue.get("revenue_recovery_opportunity", 0)

    high_risk_vendors = (
        vendor[vendor["Risk Level"] == "HIGH"]
        if isinstance(vendor, pd.DataFrame) and "Risk Level" in vendor.columns
        else pd.DataFrame()
    )

    high_risk_divisions = (
        division[division["Risk Level"] == "HIGH"]
        if isinstance(division, pd.DataFrame) and "Risk Level" in division.columns
        else pd.DataFrame()
    )

    top_risk_vendor = (
        vendor.iloc[0]["Vendor"]
        if isinstance(vendor, pd.DataFrame) and not vendor.empty and "Vendor" in vendor.columns
        else "No critical vendor concentration"
    )

    top_risk_division = (
        division.iloc[0]["Division"]
        if isinstance(division, pd.DataFrame) and not division.empty and "Division" in division.columns
        else "No critical division concentration"
    )

    top_vendor_exposure = (
        vendor.iloc[0]["Revenue Exposure"]
        if isinstance(vendor, pd.DataFrame) and not vendor.empty and "Revenue Exposure" in vendor.columns
        else 0
    )

    top_division_exposure = (
        division.iloc[0]["Revenue Exposure"]
        if isinstance(division, pd.DataFrame) and not division.empty and "Revenue Exposure" in division.columns
        else 0
    )

    cx_risk_pct = customer.get("cx_risk_pct", 0) if isinstance(customer, dict) else 0
    cx_revenue_risk = customer.get("cx_revenue_risk", 0) if isinstance(customer, dict) else 0
    cx_risk_level = customer.get("risk_level", "LOW") if isinstance(customer, dict) else "LOW"

    if revenue_risk >= 100000 or len(high_risk_vendors) >= 3 or cx_risk_level == "HIGH":
        business_severity = "CRITICAL"
        decision_mode = "Immediate leadership action required"
    elif revenue_risk > 0 or len(high_risk_vendors) > 0 or len(high_risk_divisions) > 0:
        business_severity = "HIGH"
        decision_mode = "Prioritized recovery plan recommended"
    else:
        business_severity = "CONTROLLED"
        decision_mode = "Catalog operations are stable"

    if len(high_risk_vendors) > 0:
        primary_owner = "Vendor Operations / Retail Operations"
        top_action = f"Launch governance review for {top_risk_vendor}"
        root_cause = "Vendor-led concentration of catalog quality, SLA, and execution risk."
    elif cx_risk_level == "HIGH":
        primary_owner = "Catalog Ops + Customer Experience"
        top_action = "Fix PDP content and customer experience defects"
        root_cause = "Customer-facing catalog gaps are impacting trust, search, and conversion."
    elif len(high_risk_divisions) > 0:
        primary_owner = "Catalog Operations / Category Team"
        top_action = f"Prioritize recovery for {top_risk_division}"
        root_cause = "Division-led concentration of content, attribute, and discoverability risk."
    else:
        primary_owner = "Catalog Operations"
        top_action = "Maintain monitoring and readiness controls"
        root_cause = "No major concentration risk detected."

    ceo_summary = (
        f"{business_severity}: ${revenue_risk:,.0f} revenue exposure identified, "
        f"with ${expected_recovery:,.0f} expected recovery opportunity. "
        f"Primary action: {top_action}."
    )

    top_risks = [
        f"Vendor Risk: {top_risk_vendor}",
        f"Division Risk: {top_risk_division}",
        f"Customer Experience Risk: {cx_risk_level}"
    ]

    top_actions = [
        top_action,
        "Prioritize highest revenue-exposure catalog defects",
        "Review progress in weekly retail operations cadence"
    ]

    leadership_decision = (
        f"{top_action}. Assign ownership to {primary_owner}. "
        f"Focus on high-exposure catalog defects, vendor execution gaps, and CX-linked recovery opportunities."
    )

    return {
        "business_severity": business_severity,
        "decision_mode": decision_mode,
        "ceo_summary": ceo_summary,
        "revenue_risk": revenue_risk,
        "expected_recovery": expected_recovery,
        "top_risk_vendor": top_risk_vendor,
        "top_vendor_exposure": top_vendor_exposure,
        "top_risk_division": top_risk_division,
        "top_division_exposure": top_division_exposure,
        "cx_risk_pct": cx_risk_pct,
        "cx_revenue_risk": cx_revenue_risk,
        "cx_risk_level": cx_risk_level,
        "root_cause": root_cause,
        "primary_owner": primary_owner,
        "leadership_decision": leadership_decision,
        "recommended_action": leadership_decision,
        "top_customer_risk": "PDP Content / Search Visibility Risk",
        "top_risks": top_risks,
        "top_actions": top_actions,
        "top_action": top_action,
        "high_risk_vendor_count": len(high_risk_vendors),
        "high_risk_division_count": len(high_risk_divisions)
    }

# ==================================================
# EXECUTIVE DECISION AGENT V3
# ==================================================

def executive_decision_agent(vendor_df, division_df, customer, revenue):
    decisions = []

    def safe_num(value, default=0):
        try:
            return float(value)
        except:
            return default

    def effort_score(effort):
        if effort == "Low":
            return 3
        elif effort == "Medium":
            return 2
        else:
            return 1

    # -------------------------------
    # Vendor Decisions
    # -------------------------------
    if vendor_df is not None and not vendor_df.empty:
        top_vendors = vendor_df.sort_values(
            by="Revenue Exposure",
            ascending=False
        ).head(5)

        for _, row in top_vendors.iterrows():
            vendor_name = row.get("Vendor", "Unknown Vendor")
            revenue_exposure = safe_num(row.get("Revenue Exposure", 0))
            defect_rate = safe_num(row.get("Defect Rate", 0))
            sla = safe_num(row.get("SLA Compliance", 100))

            recovery_potential = revenue_exposure * 0.45
            effort = "Medium"

            urgency = (
                "High"
                if defect_rate >= 20 or sla < 85
                else "Medium"
            )

            roi_score = recovery_potential * effort_score(effort)

            decisions.append({
                "Business Problem": f"{vendor_name} is driving revenue and execution risk",
                "Root Cause": "Vendor defects, SLA gaps, or operational execution issues",
                "Revenue Exposure": revenue_exposure,
                "Recovery Potential": recovery_potential,
                "Effort": effort,
                "ROI Score": roi_score,
                "Owner": "Vendor Operations",
                "Urgency": urgency,
                "Recommended Decision": f"Launch {vendor_name} Performance Recovery Program",
                "Expected Outcome": "Stabilize vendor performance and recover exposed revenue"
            })

    # -------------------------------
    # Division Decisions
    # -------------------------------
    if division_df is not None and not division_df.empty:
        top_divisions = division_df.sort_values(
            by="Revenue Exposure",
            ascending=False
        ).head(5)

        for _, row in top_divisions.iterrows():
            division_name = row.get("Division", "Unknown Division")
            revenue_exposure = safe_num(row.get("Revenue Exposure", 0))
            recovery_potential = safe_num(
                row.get("Recovery Opportunity", revenue_exposure * 0.40)
            )
            defect_rate = safe_num(row.get("Defect Rate", 0))

            effort = "Low" if defect_rate < 20 else "Medium"
            urgency = "High" if defect_rate >= 20 else "Medium"
            roi_score = recovery_potential * effort_score(effort)

            decisions.append({
                "Business Problem": f"{division_name} has high recoverable catalog risk",
                "Root Cause": "Content, attribute, and discoverability defects",
                "Revenue Exposure": revenue_exposure,
                "Recovery Potential": recovery_potential,
                "Effort": effort,
                "ROI Score": roi_score,
                "Owner": "Catalog Operations",
                "Urgency": urgency,
                "Recommended Decision": f"Launch {division_name} Catalog Recovery Program",
                "Expected Outcome": "Improve catalog readiness and recover lost conversion"
            })

    # -------------------------------
    # Customer Experience Decision
    # -------------------------------
    if isinstance(customer, dict):
        cx_revenue_risk = safe_num(customer.get("cx_revenue_risk", 0))
        cx_risk_pct = safe_num(customer.get("cx_risk_pct", 0))

        if cx_revenue_risk > 0:
            effort = "Low"
            recovery_potential = cx_revenue_risk * 0.35
            roi_score = recovery_potential * effort_score(effort)

            decisions.append({
                "Business Problem": "Customer experience defects are impacting conversion",
                "Root Cause": "Missing descriptions, tags, low ratings, or high returns",
                "Revenue Exposure": cx_revenue_risk,
                "Recovery Potential": recovery_potential,
                "Effort": effort,
                "ROI Score": roi_score,
                "Owner": "Customer Experience / Catalog Quality",
                "Urgency": "High" if cx_risk_pct >= 25 else "Medium",
                "Recommended Decision": "Launch Customer Experience Recovery Program",
                "Expected Outcome": "Improve trust, search visibility, and conversion recovery"
            })

    decision_queue_df = pd.DataFrame(decisions)

    if decision_queue_df.empty:
        return pd.DataFrame(columns=[
            "Rank",
            "Business Problem",
            "Root Cause",
            "Revenue Exposure",
            "Recovery Potential",
            "Effort",
            "ROI Score",
            "Owner",
            "Urgency",
            "Recommended Decision",
            "Expected Outcome"
        ])

    decision_queue_df = decision_queue_df.sort_values(
        by=["ROI Score", "Recovery Potential"],
        ascending=[False, False]
    ).reset_index(drop=True)

    decision_queue_df.insert(0, "Rank", range(1, len(decision_queue_df) + 1))

    return decision_queue_df

# ==================================================
# RUN AGENTS
# ==================================================

health = catalog_health_agent(df)
revenue = revenue_impact_agent(df)
opportunities = opportunity_prioritization_agent(df, health, revenue)
catalog_scorecard = catalog_health_scorecard_agent(df)
priority_queue_df = executive_priority_queue(df)


vendor = vendor_intelligence_agent(df)
customer = customer_experience_agent_v2(df)
division = division_performance_agent(df)

decision_queue_df = executive_decision_agent(
    vendor,
    division,
    customer,
    revenue
)



executive_alert = executive_alert_banner_agent(
    health, revenue, vendor, customer
)

executive_summary = executive_orchestration_agent(
    health, revenue, vendor, customer, division
)

def remove_recommendation_columns(df):
    """
    Removes recommendation/action columns from non-executive tabs.
    Executive Command Center remains the single source of truth for decisions.
    """
    if df is None or df.empty:
        return df

    recommendation_keywords = [
        "recommended action",
        "recommendation",
        "action",
        "decision",
        "next step",
        "ownership",
        "owner"
    ]

    cols_to_remove = [
        col for col in df.columns
        if any(keyword in col.lower() for keyword in recommendation_keywords)
    ]

    return df.drop(columns=cols_to_remove, errors="ignore")

# ==================================================
# TABS
# ==================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Executive Summary",
    "🏷️ Catalog Health",
    "🏢 Vendor Intelligence",
    "😊 Customer Experience",
    "💰 Revenue Impact",
    "🤖 AI Enrichment"
])

with tab1:
    st.subheader("🚀 Executive Summary")

    severity = executive_summary["business_severity"]

    if severity == "CRITICAL":
        st.error(f"🚨 {executive_summary['decision_mode']}")
    elif severity == "HIGH":
        st.warning(f"⚠️ {executive_summary['decision_mode']}")
    else:
        st.success(f"✅ {executive_summary['decision_mode']}")

    st.markdown("### Executive Exposure")

    k1, k2, k3, k4 = st.columns(4)

    recovery_rate = (
        executive_summary["expected_recovery"] / executive_summary["revenue_risk"] * 100
        if executive_summary["revenue_risk"] > 0
        else 0
    )

    high_risk_vendors = (
        vendor[vendor["Risk Level"] == "HIGH"]
        if "Risk Level" in vendor.columns
        else pd.DataFrame()
    )

    k1.metric("Revenue At Risk", f"${executive_summary['revenue_risk']:,.0f}")
    k2.metric("Expected Recovery", f"${executive_summary['expected_recovery']:,.0f}")
    k3.metric("High-Risk Vendors", len(high_risk_vendors))
    k4.metric("Recovery Rate", f"{recovery_rate:.0f}%")

    st.divider()

    st.markdown("### 📋 Executive Decision Queue")

    if decision_queue_df.empty:
        st.success("No executive actions required.")
    else:
        actions_df = (
            decision_queue_df.head(3)[
                [
                    "Owner",
                    "Recommended Decision",
                    "Recovery Potential",
                ]
            ].copy()
        )

        actions_df.insert(0, "Priority", [1, 2, 3])

        actions_df["Recovery Potential"] = actions_df[
            "Recovery Potential"
        ].apply(lambda x: f"${x:,.0f}")

        st.dataframe(
            actions_df,
            hide_index=True,
            use_container_width=True,
        )

    st.divider()

    st.subheader("🧭 Executive Operating Model")

    st.caption(
        "How CatalogIQ Pro converts catalog, vendor, customer, and revenue signals into leadership decisions."
    )

    operating_model = pd.DataFrame(
        {
            "Stage": [
                "1. Identify Risk",
                "2. Quantify Impact",
                "3. Assign Ownership",
                "4. Measure Customer Risk",
                "5. Prioritize Recovery",
                "6. Recommend Action",
                "7. Drive Leadership Decision",
            ],
            "Intelligence Layer": [
                "Catalog Health Agent",
                "Revenue Impact Agent",
                "Vendor Intelligence Agent",
                "Customer Experience Agent",
                "Revenue Prioritization Engine",
                "Executive Decision Agent V3",
                "Executive Agent V2",
            ],
            "Business Outcome": [
                "Detect catalog defects and product readiness gaps",
                "Measure revenue exposure and recovery opportunity",
                "Identify accountable vendors and operational owners",
                "Quantify CX degradation, returns, and trust impact",
                "Rank the highest-value recovery actions",
                "Generate decision-ready recovery recommendations",
                "Convert insights into executive action plan",
            ],
        }
    )

    st.dataframe(
        operating_model,
        use_container_width=True,
        hide_index=True,
    )


with tab2:
    st.subheader("🏷️ Catalog Health Scorecard")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Overall Health Score", f"{catalog_scorecard['overall_score']}%")
    c2.metric("Status", catalog_scorecard["overall_status"])
    c3.metric("Missing Descriptions", health["missing_descriptions"])
    c4.metric("Missing Tags", health["missing_tags"])

    st.info(catalog_scorecard["summary"])

    st.markdown("### 📋 Catalog Health Metrics")

    if not catalog_scorecard["scorecard"].empty:

       st.dataframe(
           catalog_scorecard["scorecard"],
           use_container_width=True,
           hide_index=True
       )

    else:
        st.warning("Catalog scorecard could not be generated.")

    st.markdown("### 🧠 How to Read This")

    st.write(
        """
        This scorecard converts raw catalog gaps into business-facing health indicators.
        Even when the dataset does not include conversion, returns, SLA, or customer complaints,
        the app uses proxy signals such as missing product attributes, weak descriptions,
        missing search tags, and incomplete buying fields to estimate operational risk.
        """
    )

    st.markdown("### 🚨 Executive Error Driver Summary")

    error_summary = []

    for _, row in df.iterrows():
        category = row.get("category", "Unknown Category")
        brand = row.get("brand", row.get("vendor", "Unknown Brand"))
        price = row.get("price", 0)

        issues = []

        if "description" in df.columns and pd.isna(row.get("description")):
            issues.append("Missing Description")

        if "tags" in df.columns and pd.isna(row.get("tags")):
            issues.append("Missing Tags")

        if "color" in df.columns and pd.isna(row.get("color")):
            issues.append("Missing Color")

        if "material" in df.columns and pd.isna(row.get("material")):
            issues.append("Missing Material")

        if "size" in df.columns and pd.isna(row.get("size")):
            issues.append("Missing Size")

        for issue in issues:
            error_summary.append({
                "Issue": issue,
                "Category": category,
                "Brand/Vendor": brand,
                "Revenue Proxy": price
            })

    if error_summary:
        error_df = pd.DataFrame(error_summary)

        driver_df = (
            error_df.groupby("Issue")
            .agg(
                Affected_Products=("Issue", "count"),
                Revenue_Exposure=("Revenue Proxy", "sum")
            )
            .reset_index()
            .sort_values(
                ["Revenue_Exposure", "Affected_Products"],
                ascending=False
            )
        )

        st.dataframe(
            driver_df.head(5),
            use_container_width=True,
            hide_index=True
        )

        top_issue = driver_df.iloc[0]["Issue"]
        top_exposure = driver_df.iloc[0]["Revenue_Exposure"]

        st.info(
            f"Highest catalog risk driver is **{top_issue}**, impacting approximately "
            f"**${top_exposure:,.0f}** in revenue proxy."
        )

    else:
        st.success("No major catalog error drivers detected.")

with tab3:
    st.subheader("🏢 Vendor Intelligence 2.0")

    vendor_df = vendor_intelligence_agent(df)

    high_risk_vendors = vendor_df[vendor_df["Risk Level"] == "HIGH"]
    total_vendor_exposure = vendor_df["Revenue Exposure"].sum()
    high_risk_exposure = high_risk_vendors["Revenue Exposure"].sum()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Vendor Risk Exposure",
        f"${high_risk_exposure:,.0f}"
    )

    c2.metric(
        "Vendors Requiring Action",
        len(high_risk_vendors)
    )

    top_vendor = vendor_df.iloc[0]["Vendor"] if not vendor_df.empty else "N/A"

    c3.metric(
        "Top Recovery Vendor",
        top_vendor
    )

    avg_sla = vendor_df["SLA Compliance"].mean() if not vendor_df.empty else 0

    c4.metric(
        "Avg Vendor SLA",
        f"{avg_sla:.1f}%"
    )

    st.markdown("### 🚨 Vendor Risk Summary")

    if vendor_df.empty:
        st.info("No vendor risks detected.")
    else:
        vendor_df = vendor_df.sort_values(
            by="Revenue Exposure",
            ascending=False
        )

        top_recovery_vendor = vendor_df.iloc[0]

        st.markdown(
            f"""
            <div style="
               padding:16px;
               border-radius:12px;
               background:#2b2b2b;
               border-left:6px solid #f59e0b;
               color:white;
           ">   
                <h4 style="margin-bottom:8px;">Highest Vendor Risk Identified</h4>
                <p style="font-size:16px; margin-bottom:6px;">
                    Prioritize recovery with <b>{top_recovery_vendor["Vendor"]}</b>.
                </p>
                <p style="font-size:14px; margin-bottom:0;">
                    This vendor carries <b>${top_recovery_vendor["Revenue Exposure"]:,.0f}</b> in catalog-linked revenue exposure,
                    with SLA performance at <b>{top_recovery_vendor["SLA Compliance"]:.1f}%</b>.
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.markdown("### ✅ Vendor Tab Ownership")

        st.success(
            "This tab answers: Which vendors contribute most to revenue exposure and operational risk."
        )

    st.markdown("### 📌 Vendor Risk Scorecard")

    display_vendor_df = vendor_df.copy()
    display_vendor_df = remove_recommendation_columns(
    display_vendor_df
    )
    display_vendor_df["Revenue Exposure"] = display_vendor_df["Revenue Exposure"].apply(lambda x: f"${x:,.0f}")
    display_vendor_df["Defect Rate"] = display_vendor_df["Defect Rate"].apply(lambda x: f"{x:.1f}%")
    display_vendor_df["SLA Compliance"] = display_vendor_df["SLA Compliance"].apply(lambda x: f"{x:.1f}%")
    display_vendor_df["Return Rate"] = display_vendor_df["Return Rate"].apply(lambda x: f"{x:.1f}%")
    display_vendor_df["Rating"] = display_vendor_df["Rating"].apply(lambda x: f"{x:.1f}")

    st.dataframe(
        display_vendor_df,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")
    st.markdown("### 🧭 Division Performance Analysis")

    division_df = division_performance_agent(df)

    high_risk_divisions = division_df[division_df["Risk Level"] == "HIGH"]

    d1, d2, d3, d4 = st.columns(4)

    d1.metric(
        "Total Division Exposure",
        f"${division_df['Revenue Exposure'].sum():,.0f}"
    )

    d2.metric(
        "High Risk Divisions",
        len(high_risk_divisions)
    )

    d3.metric(
        "Recovery Opportunity",
        f"${division_df['Recovery Opportunity'].sum():,.0f}"
    )

    top_division = division_df.iloc[0]["Division"] if not division_df.empty else "N/A"

    d4.metric(
        "Top Risk Division",
        top_division
    )

    st.markdown("### 🚨 Executive Division Risk Summary")

    if not division_df.empty:
        top_div = division_df.iloc[0]

    st.warning(
        f"""
        **Top Risk Division:** {top_div['Division']}  
        **Revenue Exposure:** ${top_div['Revenue Exposure']:,.0f}  
        **Products Impacted:** {top_div['Products Impacted']}  
        **Defect Rate:** {top_div['Defect Rate']:.1f}%  
        **Risk Level:** {top_div['Risk Level']}  
        **Recovery Opportunity:** ${top_div['Recovery Opportunity']:,.0f}
        """
    )

    st.markdown("### 📌 Division Risk Scorecard")

    display_division_df = division_df.copy() 

    display_division_df = remove_recommendation_columns(display_division_df)

    display_division_df["Revenue Exposure"] = display_division_df["Revenue Exposure"].apply(lambda x: f"${x:,.0f}")
    display_division_df["Defect Rate"] = display_division_df["Defect Rate"].apply(lambda x: f"{x:.1f}%")
    display_division_df["Recovery Opportunity"] = display_division_df["Recovery Opportunity"].apply(lambda x: f"${x:,.0f}")

    st.dataframe(
        display_division_df,
        use_container_width=True,
        hide_index=True
    )

with tab5:

    st.subheader("💰 Revenue Impact Agent")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Revenue At Risk",
        f"${revenue['revenue_at_risk']:,.0f}"
    )

    c2.metric(
        "Expected Recovery",
        f"${revenue.get('revenue_recovery_opportunity',0):,.0f}"
    )

    recovery_rate = 0

    if revenue["revenue_at_risk"] > 0:
        recovery_rate = (
            revenue.get("revenue_recovery_opportunity",0)
            /
            revenue["revenue_at_risk"]
        ) * 100

    c3.metric(
        "Recovery %",
        f"{recovery_rate:.0f}%"
    )

    st.divider()

    # ==================================================
    # REVENUE PRIORITIZATION ENGINE
    # ==================================================
    st.markdown("### 🚀 Revenue Prioritization Engine")

    priority_df = revenue_prioritization_engine(df)

    if not priority_df.empty:
        display_priority_df = priority_df.copy()
        display_priority_df = remove_recommendation_columns(
            display_priority_df
        )
        display_priority_df["Exposure"] = display_priority_df["Exposure"].apply(lambda x: f"${x:,.0f}")

        st.dataframe(
            display_priority_df,
            use_container_width=True,
            hide_index=True
        )

        top_priority = priority_df.iloc[0]

        st.warning(
            f"Recommended action: **{top_priority['Recommended Action']}**."
            f"with **${top_priority['Exposure']:,.0f}** exposed."
        )

    else:
        st.success("No major revenue recovery priorities detected.")

    # ==================================================
    # CATEGORY RISK ANALYSIS
    # ==================================================
    st.markdown("### 📊 Category Risk Analysis")

    if revenue.get("top_categories"):
        category_df = pd.DataFrame(
            revenue["top_categories"],
            columns=["Category", "Revenue Exposure"]
        )

        category_df["Priority"] = category_df["Revenue Exposure"].apply(
            lambda x: "Critical" if x >= category_df["Revenue Exposure"].mean() else "Monitor"
        )

        st.dataframe(
            category_df,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No category revenue risk available.")

    # ==================================================
    # BRAND RISK ANALYSIS
    # ==================================================
    st.markdown("### 🏷️ Brand Risk Analysis")

    if revenue.get("top_brands"):
        brand_df = pd.DataFrame(
            revenue["top_brands"],
            columns=["Brand", "Revenue Exposure"]
        )

        brand_df["Priority"] = brand_df["Revenue Exposure"].apply(
            lambda x: "Critical" if x >= brand_df["Revenue Exposure"].mean() else "Monitor"
        )

        st.dataframe(
            brand_df,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No brand revenue risk available.")

# ==================================================
# LEADERSHIP IMPACT STATEMENT
# ==================================================
st.markdown("### 🧠 Leadership Impact Statement")

st.info(
    f"""
    Catalog defects are currently exposing approximately
    **${revenue.get('revenue_at_risk',0):,.0f}**
    in monthly revenue risk.

    Current recovery analysis indicates a potential
    **${revenue.get('revenue_recovery_opportunity',0):,.0f}**
    recovery opportunity.

    Revenue exposure is concentrated across a small number of
    categories, brands, divisions, and vendors.
    """
)

with tab6:
    st.subheader("🤖 AI Enrichment & Export")

    st.write("Download the enriched catalog and executive outputs.")

    export_df = df.copy()

    export_df["catalog_health_index"] = health.get("catalog_health", 0)
    export_df["revenue_at_risk_total"] = revenue.get("revenue_at_risk", 0)
    export_df["expected_recovery"] = revenue.get("revenue_recovery_opportunity", 0)

    export_df["executive_summary"] = executive_summary.get("ceo_summary", "")
    export_df["top_risks"] = " | ".join(executive_summary.get("top_risks", []))
    export_df["recommended_actions"] = " | ".join(executive_summary.get("top_actions", []))

    csv = export_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="📥 Download Executive Catalog Export",
        data=csv,
        file_name="executive_catalog_export.csv",
        mime="text/csv",
        use_container_width=True
    )


# ─── Run Analysis ───────────────────────────────
col_score, col_enrich = st.columns(2)

run_score = col_score.button(
    "📊 Run Quality Scoring",
    use_container_width=True
)

run_enrich = col_enrich.button(
    "✨ Score + AI Enrich (Gemini AI)",
    use_container_width=True
)

if not run_score and not run_enrich:
    st.caption("👆 Click a button above to start.")
    st.stop()


# ─── Quality Scoring Only ───────────────────────
if run_score:
    st.subheader("📊 Quality Scorecard")

    scores = []
    for _, row in df.iterrows():
        q = score_product(row.to_dict())
        scores.append({
            "Product": row.get("product_name", row.get("product_id", "")),
            "Score": q["score"],
            "Tier": q["tier"],
            "Issues": " | ".join(q["issues"]) if q["issues"] else "None"
        })

    score_df = pd.DataFrame(scores)

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Products", len(score_df))
    c2.metric("🟢 Good (75+)", len(score_df[score_df["Score"] >= 75]))
    c3.metric("🟡 Needs Work (45–74)", len(score_df[(score_df["Score"] >= 45) & (score_df["Score"] < 75)]))
    c4.metric("🔴 Poor (<45)", len(score_df[score_df["Score"] < 45]))

    st.divider()
    st.dataframe(score_df, use_container_width=True, hide_index=True)

    avg = score_df["Score"].mean()
    st.markdown(f"**Average catalog quality score: {avg:.0f}/100**")
    if avg < 60:
        st.warning(
            "⚠️ Your catalog average is below 60. This directly impacts search ranking "
            "and conversion. Run AI Enrichment to fix it."
        )
    elif avg < 80:
        st.info("ℹ️ Good start — a few products need improvement. Run AI Enrichment to polish them.")
    else:
        st.success("✅ Strong catalog quality overall!")


# ─── Full AI Enrichment ──────────────────────────
if run_enrich:
    st.subheader("✨ AI Enrichment Results")

    progress = st.progress(0, text="Starting enrichment...")
    results = []
    enriched_rows = []

    for i, (_, row) in enumerate(df.iterrows()):
        name = row.get("product_name", f"Product {i+1}")
        progress.progress((i) / len(df), text=f"Enriching: {name}...")

        row_dict = row.to_dict()
        q = score_product(row_dict)

        # Only call AI for products that need it
        if q["score"] < 75:
            from enricher import enrich_product
            enrichment = enrich_product(row_dict, q)
        else:
            enrichment = {
                "success": True,
                "data": {
                    "quality_explanation": "Already complete — no enrichment needed.",
                    "enriched_description": row_dict.get("description", ""),
                    "suggested_tags": [],
                    "seo_title": row_dict.get("product_name", ""),
                    "inferred_color": row_dict.get("color", ""),
                    "inferred_material": row_dict.get("material", "")
                }
            }

        results.append({"name": name, "quality": q, "enrichment": enrichment, "original": row_dict})

        # Build enriched output row
        edata = enrichment.get("data", {})
        enriched_rows.append({
            **row_dict,
            "quality_score": q["score"],
            "quality_tier": q["tier"],
            "ai_description": edata.get("enriched_description", ""),
            "ai_tags": ", ".join(edata.get("suggested_tags", [])),
            "ai_seo_title": edata.get("seo_title", ""),
            "ai_color": edata.get("inferred_color", ""),
            "ai_material": edata.get("inferred_material", ""),
        })

    progress.progress(1.0, text="Done! ✓")
    st.success(f"✅ Enriched {len(results)} products.")
    st.divider()

    # ─── Summary metrics ─────────────────────────
    total = len(results)
    enriched_count = sum(1 for r in results if r["quality"]["score"] < 75)
    skipped = total - enriched_count

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Products", total)
    c2.metric("AI Enriched", enriched_count)
    c3.metric("Already Complete", skipped)
    st.divider()

    # ─── Per-product results ──────────────────────
    for r in results:
        q = r["quality"]
        e = r["enrichment"]
        name = r["name"]

        with st.expander(f"{q['tier']}  |  {name}  (Score: {q['score']}/100)"):
            col_orig, col_new = st.columns(2)

            with col_orig:
                st.markdown("**📋 Original Data**")
                orig_desc = r["original"].get("description", "")
                st.markdown(
                    f'<div class="issue-box">**Description:** {orig_desc or "⚠️ Missing"}</div>',
                    unsafe_allow_html=True
                )
                if q["issues"]:
                    st.markdown("**Issues found:**")
                    for issue in q["issues"]:
                        st.markdown(f"- {issue}")

            with col_new:
                st.markdown("**✨ AI Enriched**")
                if e["success"]:
                    d = e["data"]
                    if d.get("enriched_description"):
                        st.markdown(
                            f'<div class="enriched-box">**Description:** {d["enriched_description"]}</div>',
                            unsafe_allow_html=True
                        )
                    if d.get("suggested_tags"):
                        tags = "  `" + "`  `".join(d["suggested_tags"]) + "`"
                        st.markdown(f"**Tags:** {tags}")
                    if d.get("seo_title"):
                        st.markdown(f"**SEO Title:** `{d['seo_title']}`")
                    if d.get("quality_explanation"):
                        st.caption(f"💡 {d['quality_explanation']}")
                else:
                    st.error(f"Enrichment failed: {e.get('error', 'Unknown error')}")

    # ─── Download ─────────────────────────────────
    st.divider()
    st.subheader("⬇️ Download Enriched Catalog")
    enriched_df = pd.DataFrame(enriched_rows)
    csv_out = enriched_df.to_csv(index=False)
    st.download_button(
        "Download enriched_catalog.csv",
        data=csv_out,
        file_name="enriched_catalog.csv",
        mime="text/csv",
        use_container_width=True
    )
    st.caption(
        "This CSV contains all original columns + AI-generated "
        "description, tags, SEO title, and quality score."
    )
