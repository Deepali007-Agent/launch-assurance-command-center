try:
    import ollama
except ImportError:  # The dashboard can run without local AI support.
    ollama = None


def ask_llm(prompt, model="llama3.2:1b"):
    """
    Centralized AI service layer.
    All agents communicate with LLM through this service.
    """

    if ollama is None:
        return (
            "AI Error: optional dependency 'ollama' is not installed. "
            "Install it and start Ollama to enable AI analysis."
        )

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an enterprise procurement intelligence AI. "
                        "You analyze purchase orders, vendor risks, financial exposure, "
                        "SLA violations, operational failures, and business impact."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response["message"]["content"]

    except Exception as e:
        return f"AI Error: {str(e)}"
