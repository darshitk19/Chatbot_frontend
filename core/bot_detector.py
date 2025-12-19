import re

def is_bot(text: str) -> bool:
    if not text:
        return True
    
    text_lower = text.lower().strip()
    
    # Allow common greetings (single word or short phrases)
    greetings = ["hello", "hi", "hey", "greetings", "good morning", "good afternoon", 
                 "good evening", "hi there", "hello there", "hey there"]
    
    if text_lower in greetings or any(text_lower.startswith(g) for g in greetings):
        return False
    
    # Allow short valid queries (at least 2 characters)
    if len(text.strip()) < 2:
        return True
    
    # Check for suspicious patterns (repeated characters)
    if re.search(r"(.)\1{6,}", text):
        return True
    
    return False
