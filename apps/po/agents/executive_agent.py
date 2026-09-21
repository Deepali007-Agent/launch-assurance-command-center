def analyze_executive_decision(fin, vendor_sc, div_sc, sla, actions, decisions):
    """
    Executive Agent
    Creates a leadership-level decision summary from all analytics layers.
    No LLM call here, so it stays fast.
    """

    failed_decisions = [d for d in decisions if d["recommendation"] in ["HOLD", "REVIEW"]]

    top_vendor = vendor_sc[0] if vendor_sc else None
    top_division = max(div_sc,key=lambda d: ({"HIGH":3,"MEDIUM":2,"LOW":1,"CLEAR":0}.get(d.get("risk"),0),d.get("error_rate",0),d.get("margin_gaps",0))) if div_sc else None
    top_action = actions[0] if actions else None

    if failed_decisions or fin["po_pass_rate"] < 70:
        decision = "HOLD / REVIEW BEFORE SUBMISSION"
        decision_level = "CRITICAL"
        decision_reason = "PO submission quality is below leadership threshold."
    elif sla["sla_rate"] < 80:
        decision = "PROCESS WITH SLA CONTROL"
        decision_level = "WARNING"
        decision_reason = "POs can proceed, but SLA compliance requires leadership monitoring."
    elif fin["margin_gap"] > 0:
        decision = "PROCESS WITH MARGIN REVIEW"
        decision_level = "WARNING"
        decision_reason = "POs can proceed, but margin gaps need business review."
    else:
        decision = "PROCEED"
        decision_level = "CLEAR"
        decision_reason = "No major PO, vendor, SLA, or margin risks detected."

    return {
        "decision": decision,
        "decision_level": decision_level,
        "decision_reason": decision_reason,
        "po_pass_rate": fin["po_pass_rate"],
        "at_risk_revenue": fin["at_risk_rev"],
        "margin_gap": fin["margin_gap"],
        "sla_rate": sla["sla_rate"],
        "top_vendor": top_vendor["vendor"] if top_vendor else "N/A",
        "top_vendor_risk": top_vendor["risk_score"] if top_vendor else 0,
        "top_division": top_division["division"] if top_division else "N/A",
        "top_division_risk": top_division["risk"] if top_division else "N/A",
        "top_action": top_action["title"] if top_action else "No immediate action required",
        "executive_summary": (
            f"{decision}. {decision_reason} "
            f"PO pass rate is {fin['po_pass_rate']:.0f}%, SLA compliance is {sla['sla_rate']:.0f}%, "
            f"at-risk revenue is INR {fin['at_risk_rev']:,.0f}, and margin gap is INR {fin['margin_gap']:,.0f}."
        )
    }