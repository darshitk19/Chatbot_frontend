from core.llm_router import route_user_input

def fast_answer(user_input: str) -> str:
    """
    Get a fast answer from the LLM for general questions.
    Returns a string response.
    """
    result = route_user_input(user_input)
    return result.get("response", "I'm sorry, I couldn't generate a response.")
