from services.llm_service import ask_llm


def analyze_po_risk(row_data):

    prompt = f"""
    You are an enterprise procurement risk analyst.

    Analyze this PO and provide:

    - Risk Level
    - Business Risk
    - Financial Impact
    - Operational Impact
    - Recommended Action
    - Executive Summary

    PURCHASE ORDER:
    {row_data}

    Keep it concise and executive-friendly.
    """

    return ask_llm(prompt)