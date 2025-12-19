"""
Utility functions for business operations.
"""


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number by removing spaces and symbols, keeping only digits.
    
    Rules:
    - Remove spaces
    - Remove symbols
    - Keep digits only
    
    Examples:
        "98733 12399" -> "9873312399"
        "9873312399" -> "9873312399"
        "+1 (987) 331-2399" -> "19873312399"
    """
    if not phone:
        return ""
    # Use filter to keep only digits
    return "".join(filter(str.isdigit, phone))
