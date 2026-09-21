"""Auditable deterministic validation agents."""
from __future__ import annotations

from datetime import datetime, timezone
import re
import math

from dates import parse_business_date

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def finding(field, issue, fix, severity="Warning", owner="Vendor Onboarding"):
    return {"field": field, "issue": issue, "how_to_fix": fix, "severity": severity, "owner": owner}


def result(agent, findings):
    severities = [x["severity"] for x in findings]
    severity = "Critical" if "Critical" in severities else "Warning" if findings else "None"
    outcome = "Fail" if severity == "Critical" else "Pass with warnings" if findings else "Pass"
    return {"agent": agent, "outcome": outcome, "severity": severity, "findings": findings}


def master_data_agent(v):
    issues = []
    required = {
        "legal_name": "Provide the registered legal entity name.",
        "tax_id": "Provide the applicable tax identifier.",
        "registration_id": "Provide the company registration identifier.",
        "country": "Provide the country of registration.",
        "currency": "Provide the settlement currency.",
        "payment_terms": "Agree and record payment terms.",
    }
    for field, fix in required.items():
        if not str(v.get(field, "")).strip():
            issues.append(finding(field, "Required vendor master data is missing", fix, "Critical", "Vendor Master Data"))
    if not EMAIL.match(str(v.get("contact_email", ""))):
        issues.append(finding("contact_email", "Contact email is missing or invalid", "Provide a valid business email.", "Warning"))
    if str(v.get("bank_information_status", "")).lower() not in {"verified", "complete"}:
        issues.append(finding("bank_information_status", "Bank-information verification is incomplete", "Complete secure verification outside this dashboard.", "Critical", "Finance"))
    return result("Vendor Master Data Agent", issues)


def compliance_agent(v):
    issues = []
    status = str(v.get("document_status", "")).lower()
    expiry = str(v.get("document_expiry_date", "")).strip()
    if status in {"missing", "expired", "rejected"}:
        issues.append(finding("document_status", f"Required document is {status}", "Upload a current approved document.", "Critical", "Compliance"))
    if expiry:
        parsed_expiry = parse_business_date(expiry)
        if parsed_expiry:
            days = (parsed_expiry - datetime.now(timezone.utc).date()).days
            if days < 0:
                issues.append(finding("document_expiry_date", "Document has expired", "Obtain and upload the renewed document.", "Critical", "Compliance"))
            elif days <= 30:
                issues.append(finding("document_expiry_date", f"Document expires in {days} days", "Start renewal immediately.", "Warning", "Compliance"))
            elif days <= 90:
                issues.append(finding("document_expiry_date", f"Document expires in {days} days", "Schedule renewal before expiry.", "Warning", "Compliance"))
        else:
            issues.append(finding("document_expiry_date", "Expiry date is invalid", "Use an ISO date such as 2027-05-31.", "Critical", "Compliance"))
    for field in ("insurance_status", "ethical_trade_status", "vendor_authorization"):
        if str(v.get(field, "")).lower() not in {"approved", "valid", "current", "yes"}:
            issues.append(finding(field, "Compliance evidence is not approved", "Provide current approved evidence.", "Critical", "Compliance"))
    return result("Compliance & Documentation Agent", issues)


def commercial_agent(v):
    issues = []
    for field, owner in (("incoterms", "Commercial"), ("return_terms", "Commercial"), ("lead_time_days", "Buying")):
        if not str(v.get(field, "")).strip():
            issues.append(finding(field, "Commercial term is incomplete", "Agree and record the commercial term.", "Critical", owner))
    try:
        if not math.isfinite(float(v.get("minimum_order_quantity", 0) or 0)) or float(v.get("minimum_order_quantity", 0) or 0) <= 0:
            issues.append(finding("minimum_order_quantity", "Minimum order quantity is not valid", "Enter an agreed quantity above zero.", "Warning", "Buying"))
    except (TypeError, ValueError):
        issues.append(finding("minimum_order_quantity", "Minimum order quantity is not numeric", "Enter a numeric agreed quantity.", "Warning", "Buying"))
    return result("Commercial Readiness Agent", issues)


def risk_agent(v, prior):
    issues = []
    critical = sum(a["severity"] == "Critical" for a in prior)
    warnings = sum(a["severity"] == "Warning" for a in prior)
    revisions = int(v.get("revision", v.get("revision_number", 1)) or 1)
    if critical:
        issues.append(finding("validation_risk", f"{critical} specialist assessment(s) contain critical blockers", "Resolve all explained blockers before approval.", "Critical", "Vendor Operations"))
    if warnings >= 2:
        issues.append(finding("warning_concentration", "Multiple unresolved warnings increase operational risk", "Review and accept or remediate each warning.", "Warning", "Vendor Operations"))
    if revisions >= 3:
        issues.append(finding("revision_number", f"Vendor has required {revisions} submission revisions", "Review recurring correction causes with the vendor.", "Warning", "Vendor Onboarding"))
    return result("Vendor Risk Agent", issues)


def assess_vendor(v):
    specialist = [master_data_agent(v), compliance_agent(v), commercial_agent(v)]
    specialist.append(risk_agent(v, specialist))
    return specialist
