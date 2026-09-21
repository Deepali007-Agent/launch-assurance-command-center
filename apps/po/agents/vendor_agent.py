from services.llm_service import ask_llm


def analyze_vendor(vendor_data):
    """
    Strategic Vendor Intelligence Agent
    """

    prompt = f"""
    You are a senior procurement strategy consultant.

    Analyze this vendor performance data.

    Provide:

    1. Vendor Risk Level
    2. Core Business Problem
    3. Future Risk Prediction
    4. Financial Exposure
    5. Operational Impact
    6. Recommended Leadership Action
    7. Negotiation Strategy
    8. Executive Summary

    VENDOR DATA:
    {vendor_data}

    Keep the response concise, strategic, and executive-friendly.
    """

    return ask_llm(prompt)