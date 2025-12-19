# app.py

import streamlit as st
import sqlite3
import re
from difflib import get_close_matches

from core.bot_detector import is_bot
from core.sql_detector import needs_sql
from core.text_to_sql import generate_sql
from core.fast_result import fast_answer
from business.business_by_phone import get_businesses_by_phone
from business.business_health import get_update_suggestions
from business.business_update import update_business
from business.business_add import add_business
from business.business_utils import normalize_phone
from online.serpapi_search import search_online, rank_online_results
from db.config import DB_PATH

# ---------------- PAGE CONFIG ---------------- #

st.set_page_config(
    page_title="HBD Local Business AI",
    layout="wide"
)

st.title("HBD Local Business AI")
st.caption("Search local businesses, manage and update your business profile")

# ---------------- SESSION STATE ---------------- #

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "phone" not in st.session_state:
    st.session_state.phone = None

if "businesses" not in st.session_state:
    st.session_state.businesses = []

if "messages" not in st.session_state:
    st.session_state.messages = []

if "show_update" not in st.session_state:
    st.session_state.show_update = False

# Chatbot conversation state
if "chat_mode" not in st.session_state:
    st.session_state.chat_mode = None  # None, "show", "update", "add"

if "chat_step" not in st.session_state:
    st.session_state.chat_step = 0

if "chat_data" not in st.session_state:
    st.session_state.chat_data = {}

if "current_business" not in st.session_state:
    st.session_state.current_business = None

# ---------------- CHATBOT HELPER FUNCTIONS ---------------- #

def is_greeting(text: str) -> bool:
    """Check if user input is a greeting."""
    greetings = [
        "hi", "hello", "hey", "good morning", "good afternoon", 
        "good evening", "howdy", "hola", "greetings", "sup",
        "what's up", "yo", "namaste"
    ]
    text_lower = text.lower().strip()
    for greet in greetings:
        if greet in text_lower:
            return True
    return False

def detect_intent(text: str) -> str:
    """
    Detect user intent from their message.
    Returns: 'show', 'update', 'add', 'search', 'greeting', or 'general'
    """
    text_lower = text.lower().strip()
    
    # Check greeting first
    if is_greeting(text_lower):
        return "greeting"
    
    # Search for business intent (prioritize before show)
    search_keywords = [
        "search for", "find a", "looking for", "need a", "want a",
        "search", "find", "looking", "recommend", "suggest",
        "near me", "best", "top", "where can i find"
    ]
    for kw in search_keywords:
        if kw in text_lower:
            return "search"
    
    # Show business intent
    show_keywords = [
        "show my business", "view my business", "display business",
        "get my business", "my business details", "business info"
    ]
    for kw in show_keywords:
        if kw in text_lower:
            return "show"
    
    # Update business intent
    update_keywords = [
        "update my business", "edit details", "change my business",
        "modify business", "update business", "edit business",
        "change details", "update details", "edit my business",
        "modify my business", "fix my business", "correct details"
    ]
    for kw in update_keywords:
        if kw in text_lower:
            return "update"
    
    # Add business intent
    add_keywords = [
        "add business", "register my business", "create business",
        "new business", "add my business", "register business",
        "list my business", "add a business", "register a business",
        "add new business", "create new business"
    ]
    for kw in add_keywords:
        if kw in text_lower:
            return "add"
    
    return "general"

def format_business_details(biz: dict) -> str:
    """Format business details for display in chat."""
    return f"""
### 🏢 {biz.get('name', 'N/A')}
- 📍 **Address:** {biz.get('address') or 'N/A'}
- 📞 **Phone:** {biz.get('phone_number') or 'N/A'}
- 🌐 **Website:** {biz.get('website') or 'Not set'}
- 🏷️ **Category:** {biz.get('category') or 'N/A'}
- 📍 **City:** {biz.get('city') or 'N/A'}
- 📍 **State:** {biz.get('state') or 'N/A'}
"""

def get_greeting_response() -> str:
    """Return greeting response with suggestions."""
    return """Hi 👋 I can help you manage your business.

What would you like to do next?
- 🔍 **Search for a business** - Find restaurants, salons, stores, etc.
- 📋 **Show my business** - View your business details
- ✏️ **Update my business** - Edit your business information
- ➕ **Add a new business** - Register a new business

Just type what you're looking for! For example: "Find a restaurant near me" or "Search for salons"""

def get_suggestions_after_show() -> str:
    """Get follow-up suggestions after showing business."""
    return """
---
**What would you like to do next?**
- ✏️ Type "**update my business**" to make changes
- ➕ Type "**add a new business**" to register another business
- 🔍 Type "**search for**" + what you need"""

def get_suggestions_after_search() -> str:
    """Get follow-up suggestions after searching."""
    return """
---
**What would you like to do next?**
- 🔍 Search for something else
- 📋 Type "**show my business**" to view your business
- ✏️ Type "**update my business**" to make changes"""

def get_suggested_categories() -> list:
    """Get unique categories from database for suggestions."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM google_maps_listings WHERE category IS NOT NULL AND category != '' LIMIT 15")
        categories = [row[0] for row in cur.fetchall() if row[0]]
        conn.close()
        return categories
    except:
        return []

def get_all_searchable_terms() -> list:
    """Get all searchable terms (categories, business names, cities) from database for spell checking."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # Get unique categories
        cur.execute("SELECT DISTINCT category FROM google_maps_listings WHERE category IS NOT NULL AND category != ''")
        categories = [row[0].lower() for row in cur.fetchall() if row[0]]
        
        # Get unique cities
        cur.execute("SELECT DISTINCT city FROM google_maps_listings WHERE city IS NOT NULL AND city != ''")
        cities = [row[0].lower() for row in cur.fetchall() if row[0]]
        
        # Get business names (first word or short names)
        cur.execute("SELECT DISTINCT name FROM google_maps_listings WHERE name IS NOT NULL AND name != ''")
        names = []
        for row in cur.fetchall():
            if row[0]:
                # Add full name and first word for matching
                name = row[0].lower()
                names.append(name)
                first_word = name.split()[0] if name.split() else name
                if len(first_word) > 2:
                    names.append(first_word)
        
        conn.close()
        
        # Combine all terms and remove duplicates
        all_terms = list(set(categories + cities + names))
        return all_terms
    except:
        return []

def correct_spelling(query: str, threshold: float = 0.6) -> tuple:
    """
    Correct spelling of a search query by finding closest matches.
    Only corrects when spelling is actually incorrect (no match in database).
    Returns: (corrected_query, was_corrected, suggestions)
    """
    query_lower = query.lower().strip()
    
    # Get all searchable terms from database
    all_terms = get_all_searchable_terms()
    
    if not all_terms:
        return query, False, []
    
    # Check if query exactly matches any term - no correction needed
    if query_lower in all_terms:
        return query, False, []
    
    # Check if query is a partial match of any term (substring match)
    # If so, don't correct - the query is valid
    for term in all_terms:
        if query_lower in term or term in query_lower:
            return query, False, []
    
    # Check if any word in the query matches a term exactly
    query_words = query_lower.split()
    for word in query_words:
        if len(word) >= 3 and word in all_terms:
            return query, False, []  # At least one word is correct, don't auto-correct
    
    # Only now try to find corrections - the query seems to be misspelled
    # Find close matches for the whole query
    matches = get_close_matches(query_lower, all_terms, n=3, cutoff=threshold)
    
    if matches:
        # Only correct if the match is significantly close (higher threshold for single word)
        corrected = matches[0]
        # Preserve original case style if possible
        if query and query[0].isupper():
            corrected = corrected.title()
        return corrected, True, matches
    
    # Try matching individual words for multi-word queries
    words = query_lower.split()
    if len(words) > 1:
        corrected_words = []
        any_corrected = False
        
        for word in words:
            if len(word) < 3:  # Skip short words
                corrected_words.append(word)
                continue
            
            # Check if word exists in any term
            word_exists = any(word in term for term in all_terms)
            if word_exists:
                corrected_words.append(word)
                continue
            
            # Word doesn't exist, try to find correction
            word_matches = get_close_matches(word, all_terms, n=1, cutoff=threshold)
            if word_matches:
                corrected_words.append(word_matches[0])
                any_corrected = True
            else:
                corrected_words.append(word)
        
        if any_corrected:
            corrected = ' '.join(corrected_words)
            if query and query[0].isupper():
                corrected = corrected.title()
            return corrected, True, [corrected]
    
    return query, False, []

def parse_search_query(user_query: str) -> tuple:
    """
    Parse natural language search query to extract keyword and location.
    Example: "best ice cream shop in mumbai" -> ("ice cream shop", "mumbai")
    """
    q = user_query.lower().strip()
    
    # Stop words to remove (used for ranking intent, not filtering)
    stop_words = ["best", "top", "near", "me", "in", "the", "a", "an", "find", "search", "for", "looking", "need", "want", "good", "great"]
    for word in stop_words:
        q = q.replace(f" {word} ", " ")
        if q.startswith(f"{word} "):
            q = q[len(word)+1:]
        if q.endswith(f" {word}"):
            q = q[:-len(word)-1]
    
    # Clean up extra spaces
    q = " ".join(q.split())
    
    words = q.split()
    
    if not words:
        return "", ""
    
    if len(words) == 1:
        # Single word - could be keyword or location
        return words[0], ""
    
    # Last word is typically the location
    location = words[-1]
    keyword = " ".join(words[:-1])
    
    return keyword.strip(), location.strip()

def smart_search_business(user_query: str, use_spelling_correction: bool = True) -> tuple:
    """
    Smart natural-language search for businesses.
    Extracts keyword/category and location from query.
    Returns: (results_list, keyword, location, was_corrected)
    """
    original_query = user_query
    
    # Parse query to extract keyword and location
    keyword, location = parse_search_query(user_query)
    
    # Apply spelling correction to keyword and location separately
    corrected_keyword = keyword
    corrected_location = location
    was_corrected = False
    
    if use_spelling_correction and keyword:
        corrected_kw, kw_corrected, _ = correct_spelling(keyword)
        if kw_corrected:
            corrected_keyword = corrected_kw
            was_corrected = True
    
    if use_spelling_correction and location:
        corrected_loc, loc_corrected, _ = correct_spelling(location)
        if loc_corrected:
            corrected_location = corrected_loc
            was_corrected = True
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        results = []
        
        # If we have both keyword and location
        if corrected_keyword and corrected_location:
            search_term = f"%{corrected_keyword}%"
            location_term = f"%{corrected_location}%"
            
            cur.execute("""
                SELECT * FROM google_maps_listings
                WHERE (
                    LOWER(name) LIKE LOWER(?)
                    OR LOWER(category) LIKE LOWER(?)
                    OR LOWER(subcategory) LIKE LOWER(?)
                )
                AND (
                    LOWER(city) LIKE LOWER(?)
                    OR LOWER(address) LIKE LOWER(?)
                )
                ORDER BY reviews_average DESC, reviews_count DESC
                LIMIT 5
            """, (search_term, search_term, search_term, location_term, location_term))
            
            rows = cur.fetchall()
            results = [dict(row) for row in rows]
        
        # If only keyword (no location match found), search by keyword only
        if not results and corrected_keyword:
            search_term = f"%{corrected_keyword}%"
            
            cur.execute("""
                SELECT * FROM google_maps_listings
                WHERE LOWER(name) LIKE LOWER(?)
                   OR LOWER(category) LIKE LOWER(?)
                   OR LOWER(subcategory) LIKE LOWER(?)
                ORDER BY reviews_average DESC, reviews_count DESC
                LIMIT 5
            """, (search_term, search_term, search_term))
            
            rows = cur.fetchall()
            results = [dict(row) for row in rows]
        
        # If still no results, try location only (maybe user typed just a city)
        if not results and corrected_location:
            location_term = f"%{corrected_location}%"
            
            cur.execute("""
                SELECT * FROM google_maps_listings
                WHERE LOWER(city) LIKE LOWER(?)
                   OR LOWER(address) LIKE LOWER(?)
                ORDER BY reviews_average DESC, reviews_count DESC
                LIMIT 5
            """, (location_term, location_term))
            
            rows = cur.fetchall()
            results = [dict(row) for row in rows]
        
        # Fallback: search full original query
        if not results:
            full_term = f"%{user_query}%"
            
            cur.execute("""
                SELECT * FROM google_maps_listings
                WHERE LOWER(name) LIKE LOWER(?)
                   OR LOWER(category) LIKE LOWER(?)
                   OR LOWER(city) LIKE LOWER(?)
                ORDER BY reviews_average DESC, reviews_count DESC
                LIMIT 5
            """, (full_term, full_term, full_term))
            
            rows = cur.fetchall()
            results = [dict(row) for row in rows]
        
        conn.close()
        
        return results, corrected_keyword, corrected_location, was_corrected
        
    except Exception as e:
        return [], keyword, location, False

# Keep old function for backward compatibility
def search_business_in_db(query: str, use_spelling_correction: bool = True) -> tuple:
    """
    Search for businesses in database (backward compatible wrapper).
    Returns: (results_list, corrected_query, was_corrected)
    """
    results, keyword, location, was_corrected = smart_search_business(query, use_spelling_correction)
    corrected_query = f"{keyword} {location}".strip() if keyword or location else query
    return results, corrected_query, was_corrected

def format_search_result(biz: dict, is_online: bool = False) -> str:
    """Format a single search result for display."""
    source = "🌐 Online" if is_online else "📁 Database"
    rating = biz.get('rating') or biz.get('reviews_average') or 'N/A'
    reviews = biz.get('reviews') or biz.get('reviews_count') or 0
    phone = biz.get('phone') or biz.get('phone_number') or 'N/A'
    
    return f"""
### {biz.get('title') or biz.get('name')}
- 📍 {biz.get('address') or 'N/A'}
- 📞 {phone}
- ⭐ {rating} ({reviews} reviews)
- 🏷️ {biz.get('type') or biz.get('category') or 'N/A'}
- {source}
---"""

def get_suggestions_after_update() -> str:
    """Get follow-up suggestions after updating business."""
    return """
---
**What would you like to do next?**
- 🔍 Type "**show my business**" to view the updated details
- ✏️ Type "**update my business**" to make more changes
- ➕ Type "**add a new business**" to register another business"""

def get_suggestions_after_add() -> str:
    """Get follow-up suggestions after adding business."""
    return """
---
**What would you like to do next?**
- 🔍 Type "**show my business**" to view your new business
- ✏️ Type "**update my business**" to make changes to it
- ➕ Type "**add a new business**" to register another business"""

def reset_chat_flow():
    """Reset the chat flow state."""
    st.session_state.chat_mode = None
    st.session_state.chat_step = 0
    st.session_state.chat_data = {}
    st.session_state.current_business = None

def process_chatbot_response(user_input: str) -> str:
    """
    Main chatbot logic processor.
    Handles all conversation flows: show, update, add, and general queries.
    """
    # If we're in the middle of a flow, continue it
    if st.session_state.chat_mode:
        return handle_active_flow(user_input)
    
    # Detect intent from user input
    intent = detect_intent(user_input)
    
    if intent == "greeting":
        return get_greeting_response()
    
    elif intent == "show":
        st.session_state.chat_mode = "show"
        st.session_state.chat_step = 1
        return """🔍 Let's find your business!

Please enter the **phone number** associated with your business:
_(Example: 9873312399 or 98733 12399)_"""
    
    elif intent == "update":
        st.session_state.chat_mode = "update"
        st.session_state.chat_step = 1
        return """✏️ Let's update your business details!

Please enter the **phone number** associated with your business:
_(Example: 9873312399 or 98733 12399)_"""
    
    elif intent == "add":
        st.session_state.chat_mode = "add"
        st.session_state.chat_step = 1
        return """➕ Great! Let's add a new business.

I'll ask you a few questions to register your business. Let's start!

**What is the name of your business?**"""
    
    elif intent == "search":
        # Direct search - perform search immediately with user's query
        # Extract the actual search query by removing intent keywords
        search_query = user_input.lower().strip()
        
        # Remove common search intent words to get the actual query
        remove_words = ["search for", "find a", "looking for", "need a", "want a", 
                        "search", "find", "looking", "recommend", "suggest", 
                        "where can i find", "best", "top", "near me"]
        for word in remove_words:
            search_query = search_query.replace(word, "")
        search_query = " ".join(search_query.split()).strip()
        
        # If we have a valid search query, search directly
        if search_query and len(search_query) >= 2:
            # Use smart search with keyword/location extraction
            db_results, keyword, location, was_corrected = smart_search_business(search_query)
            
            if db_results:
                # Found in database - show results directly
                search_info = ""
                if keyword and location:
                    search_info = f'🔍 Searching for **"{keyword}"** in **{location}**\n\n'
                elif keyword:
                    search_info = f'🔍 Searching for **"{keyword}"**\n\n'
                
                if was_corrected:
                    search_info += '💡 _(Auto-corrected your search)_\n\n'
                
                response = search_info + f"✅ **Found {len(db_results)} top-rated business(es):**\n"
                
                for biz in db_results[:5]:
                    response += format_search_result(biz, is_online=False)
                
                response += get_suggestions_after_search()
                return response
            else:
                # Not found in database - try online search
                try:
                    if keyword and location:
                        online_query = f"{keyword} in {location}"
                    elif keyword:
                        online_query = keyword
                    else:
                        online_query = search_query
                    
                    online_results = search_online(online_query)
                    
                    if online_results:
                        ranked_results = rank_online_results(online_results)
                        
                        response = f"""🔍 No local results found for "{search_query}".\n"""
                        
                        if keyword and location:
                            response += f"""_(Searched: "{keyword}" in {location})_\n"""
                        
                        response += """\n🌐 **Here are results from online search:**\n"""
                        
                        for biz in ranked_results[:5]:
                            response += format_search_result(biz, is_online=True)
                        
                        response += """

💡 **Tip:** Would you like to add any of these businesses to our database?
Type "**add a new business**" to register one!"""
                        response += get_suggestions_after_search()
                        return response
                    else:
                        return f"""❌ No results found for "{search_query}" in our database or online.

**Try searching for:**
- A different business name
- A category (e.g., "Restaurant", "Salon")
- A location (e.g., city name)

Or type "**add a new business**" to register one!
{get_suggestions_after_search()}"""
                        
                except Exception as e:
                    return f"""❌ No local results found for "{search_query}".

Online search failed: {str(e)}

**What would you like to do?**
- 🔍 Try searching for something else
- ➕ Type "**add a new business**" to register one
{get_suggestions_after_search()}"""
        else:
            # No valid search query, ask what to find
            categories = get_suggested_categories()
            category_text = ""
            if categories:
                category_text = "\n\n**Popular categories in our database:**\n" + ", ".join([f"🏷️ {c}" for c in categories[:8]])
            
            return f"""🔍 What would you like to search for?

You can search by:
- Business name
- Category (e.g., Restaurant, Salon, Store)
- Location/City{category_text}"""
    
    else:
        # General query - use existing logic
        return None  # Signal to use existing SQL/fast_answer logic

def handle_active_flow(user_input: str) -> str:
    """Handle ongoing conversation flows."""
    mode = st.session_state.chat_mode
    step = st.session_state.chat_step
    
    # Check if user wants to cancel
    if user_input.lower().strip() in ["cancel", "exit", "quit", "stop", "nevermind"]:
        reset_chat_flow()
        return """No problem! I've cancelled the current operation.

What would you like to do next?
- 🔍 **Show my business**
- ✏️ **Update my business**
- ➕ **Add a new business**"""
    
    if mode == "show":
        return handle_show_flow(user_input)
    elif mode == "update":
        return handle_update_flow(user_input)
    elif mode == "add":
        return handle_add_flow(user_input)
    elif mode == "search":
        return handle_search_flow(user_input)
    
    return None

def handle_show_flow(user_input: str) -> str:
    """Handle the show business flow."""
    step = st.session_state.chat_step
    
    if step == 1:
        # User provided phone number
        phone = user_input.strip()
        normalized = normalize_phone(phone)
        
        if not normalized or len(normalized) < 6:
            return """⚠️ That doesn't look like a valid phone number.

Please enter a valid phone number (at least 6 digits):
_(Example: 9873312399 or 98733 12399)_"""
        
        # Fetch business from database
        businesses = get_businesses_by_phone(phone)
        
        if not businesses:
            reset_chat_flow()
            return f"""❌ No business found with phone number **{phone}**

The number doesn't match any registered business in our database.

**Would you like to register this business?**
- ➕ Type "**add a new business**" to register it
- 🔍 Type "**show my business**" to try another number"""
        
        # Business found - display details
        reset_chat_flow()
        st.session_state.current_business = businesses[0]
        
        response = f"""✅ **Business Found!**
{format_business_details(businesses[0])}"""
        
        # Add smart suggestions
        if not businesses[0].get('website'):
            response += """
💡 **Tip:** Adding a website can increase visibility and trust!
"""
        
        response += get_suggestions_after_show()
        return response
    
    return None

def handle_update_flow(user_input: str) -> str:
    """Handle the update business flow."""
    step = st.session_state.chat_step
    
    if step == 1:
        # User provided phone number
        phone = user_input.strip()
        normalized = normalize_phone(phone)
        
        if not normalized or len(normalized) < 6:
            return """⚠️ That doesn't look like a valid phone number.

Please enter a valid phone number (at least 6 digits):
_(Example: 9873312399 or 98733 12399)_"""
        
        # Fetch business from database
        businesses = get_businesses_by_phone(phone)
        
        if not businesses:
            reset_chat_flow()
            return f"""❌ No business found with phone number **{phone}**

The number doesn't match any registered business in our database.

**Would you like to register this business instead?**
- ➕ Type "**add a new business**" to register it
- 🔍 Type "**show my business**" to try another number"""
        
        # Business found - store it and ask which field to update
        st.session_state.current_business = businesses[0]
        st.session_state.chat_data["phone"] = phone
        st.session_state.chat_step = 2
        
        biz = businesses[0]
        response = f"""✅ **Business Found!**
{format_business_details(biz)}

**Which field would you like to update?**
1️⃣ **Name** - Current: {biz.get('name') or 'Not set'}
2️⃣ **Address** - Current: {biz.get('address') or 'Not set'}
3️⃣ **Phone** - Current: {biz.get('phone_number') or 'Not set'}
4️⃣ **Website** - Current: {biz.get('website') or 'Not set'}
5️⃣ **Category** - Current: {biz.get('category') or 'Not set'}
6️⃣ **City** - Current: {biz.get('city') or 'Not set'}
7️⃣ **State** - Current: {biz.get('state') or 'Not set'}

Just type the field name or number (e.g., "name" or "1"):"""

        # Smart suggestion for missing website
        if not biz.get('website'):
            response += """

💡 **Suggestion:** Adding a website can increase visibility and trust!"""
        
        return response
    
    elif step == 2:
        # User selected which field to update
        field_input = user_input.strip().lower()
        
        # Check if user is done updating
        if field_input in ["done", "finish", "exit", "no", "cancel"]:
            reset_chat_flow()
            biz = st.session_state.current_business
            return f"""✅ **Update complete!**

{format_business_details(biz) if biz else ''}

{get_suggestions_after_update()}"""
        
        field_mapping = {
            "1": "name", "name": "name",
            "2": "address", "address": "address",
            "3": "phone", "phone": "phone_number", "phone number": "phone_number",
            "4": "website", "website": "website",
            "5": "category", "category": "category",
            "6": "city", "city": "city",
            "7": "state", "state": "state",
        }
        
        if field_input not in field_mapping:
            return """⚠️ I didn't understand that. Please choose from:
1️⃣ **Name**
2️⃣ **Address**
3️⃣ **Phone**
4️⃣ **Website**
5️⃣ **Category**
6️⃣ **City**
7️⃣ **State**

Type the number (1-7) or field name, or "**done**" to finish:"""
        
        field_key = field_mapping[field_input]
        st.session_state.chat_data["update_field"] = field_key
        st.session_state.chat_step = 3
        
        current_value = st.session_state.current_business.get(field_key) or "Not set"
        
        return f"""✏️ Updating **{field_key.replace('_', ' ').title()}**

Current value: **{current_value}**

Please enter the new value:"""
    
    elif step == 3:
        # User provided new value - update database
        new_value = user_input.strip()
        field_key = st.session_state.chat_data.get("update_field")
        biz = st.session_state.current_business
        
        if not new_value:
            return """⚠️ Please enter a value. Type the new value for the field:"""
        
        if not field_key:
            reset_chat_flow()
            return """⚠️ Something went wrong. Please start again.

Type "**update my business**" to try again."""
        
        # Prepare update
        updates = {field_key: new_value}
        
        try:
            # Get business ID and phone
            business_id = biz.get("id") if biz else None
            phone_for_update = st.session_state.chat_data.get("phone")
            
            success = False
            
            # Try update by ID first
            if business_id is not None:
                success = update_business(business_id=int(business_id), updates=updates)
            
            # Fallback to phone number update if ID update failed
            if not success and phone_for_update:
                success = update_business(phone_number=phone_for_update, updates=updates)
            
            if success:
                # Refresh business data
                updated_businesses = get_businesses_by_phone(phone_for_update) if phone_for_update else []
                if updated_businesses:
                    # Find the same business by ID or take first one
                    for b in updated_businesses:
                        if b.get("id") == business_id:
                            biz = b
                            break
                    else:
                        biz = updated_businesses[0]
                    st.session_state.current_business = biz
                
                # Ask if user wants to update more fields
                st.session_state.chat_step = 2  # Go back to field selection
                
                response = f"""✅ **Successfully Updated!**

**{field_key.replace('_', ' ').title()}** has been updated to: **{new_value}**

{format_business_details(biz)}

**Would you like to update another field?**
1️⃣ **Name** - Current: {biz.get('name') or 'Not set'}
2️⃣ **Address** - Current: {biz.get('address') or 'Not set'}
3️⃣ **Phone** - Current: {biz.get('phone_number') or 'Not set'}
4️⃣ **Website** - Current: {biz.get('website') or 'Not set'}
5️⃣ **Category** - Current: {biz.get('category') or 'Not set'}
6️⃣ **City** - Current: {biz.get('city') or 'Not set'}
7️⃣ **State** - Current: {biz.get('state') or 'Not set'}

Type a number (1-7) to update another field, or type "**done**" to finish."""
                return response
            else:
                # Update failed - stay in update mode, let user try again
                return f"""⚠️ Could not update **{field_key.replace('_', ' ').title()}**. 

Please try entering a different value, or type "**done**" to exit:"""
                
        except Exception as e:
            reset_chat_flow()
            return f"""❌ Error updating business: {str(e)}

What would you like to do?
- ✏️ Type "**update my business**" to try again
- 🔍 Type "**show my business**" to view details"""
    
    return None

def handle_add_flow(user_input: str) -> str:
    """Handle the add business flow."""
    step = st.session_state.chat_step
    
    if step == 1:
        # User provided business name
        name = user_input.strip()
        if not name or len(name) < 2:
            return """⚠️ Please enter a valid business name (at least 2 characters):"""
        
        st.session_state.chat_data["name"] = name
        st.session_state.chat_step = 2
        return f"""Great! Your business is: **{name}**

📞 **What is your business phone number?**
_(Example: 9873312399 or 98733 12399)_"""
    
    elif step == 2:
        # User provided phone number
        phone = user_input.strip()
        normalized = normalize_phone(phone)
        
        if not normalized or len(normalized) < 6:
            return """⚠️ Please enter a valid phone number (at least 6 digits):
_(Example: 9873312399 or 98733 12399)_"""
        
        st.session_state.chat_data["phone_number"] = normalized
        st.session_state.chat_step = 3
        return f"""📞 Phone: **{normalized}**

📍 **What is your business address?**"""
    
    elif step == 3:
        # User provided address
        address = user_input.strip()
        if not address or len(address) < 5:
            return """⚠️ Please enter a valid address (at least 5 characters):"""
        
        st.session_state.chat_data["address"] = address
        st.session_state.chat_step = 4
        return f"""📍 Address: **{address}**

🌐 **What is your business website?** _(optional - type "skip" to skip)_"""
    
    elif step == 4:
        # User provided website (optional)
        website = user_input.strip()
        if website.lower() in ["skip", "none", "n/a", "-", ""]:
            st.session_state.chat_data["website"] = ""
        else:
            st.session_state.chat_data["website"] = website
        
        st.session_state.chat_step = 5
        return f"""🏷️ **What category is your business?**
_(Example: Restaurant, Salon, Retail Store, Healthcare, etc.)_"""
    
    elif step == 5:
        # User provided category
        category = user_input.strip()
        if not category or len(category) < 2:
            return """⚠️ Please enter a business category:
_(Example: Restaurant, Salon, Retail Store, Healthcare, etc.)_"""
        
        st.session_state.chat_data["category"] = category
        st.session_state.chat_step = 6
        return f"""🏷️ Category: **{category}**

📍 **What city is your business located in?**"""
    
    elif step == 6:
        # User provided city
        city = user_input.strip()
        st.session_state.chat_data["city"] = city if city and city.lower() not in ["skip", "none"] else ""
        st.session_state.chat_step = 7
        return f"""📍 **What state is your business located in?**"""
    
    elif step == 7:
        # User provided state - now add to database
        state = user_input.strip()
        st.session_state.chat_data["state"] = state if state and state.lower() not in ["skip", "none"] else ""
        
        data = st.session_state.chat_data
        
        try:
            # Add business to database
            new_id = add_business(
                name=data.get("name", ""),
                address=data.get("address", ""),
                phone_number=data.get("phone_number", ""),
                website=data.get("website", ""),
                category=data.get("category", ""),
                city=data.get("city", ""),
                state=data.get("state", ""),
            )
            
            if new_id:
                # Fetch the newly added business
                new_businesses = get_businesses_by_phone(data.get("phone_number", ""))
                st.session_state.current_business = new_businesses[0] if new_businesses else None
                
                reset_chat_flow()
                
                response = f"""✅ **Business Added Successfully!**

Your business has been registered with ID: **{new_id}**

**Summary:**
- 🏢 **Name:** {data.get('name')}
- 📞 **Phone:** {data.get('phone_number')}
- 📍 **Address:** {data.get('address')}
- 🌐 **Website:** {data.get('website') or 'Not set'}
- 🏷️ **Category:** {data.get('category')}
- 📍 **City:** {data.get('city') or 'Not set'}
- 📍 **State:** {data.get('state') or 'Not set'}
{get_suggestions_after_add()}"""
                return response
            else:
                reset_chat_flow()
                return """❌ Failed to add the business. Please try again.

What would you like to do?
- ➕ Type "**add a new business**" to try again"""
        
        except Exception as e:
            reset_chat_flow()
            return f"""❌ An error occurred: {str(e)}

What would you like to do?
- ➕ Type "**add a new business**" to try again"""
    
    return None

def handle_search_flow(user_input: str) -> str:
    """Handle the search business flow - database first, then online."""
    step = st.session_state.chat_step
    
    if step == 1:
        # User provided search query
        query = user_input.strip()
        if not query or len(query) < 2:
            return """⚠️ Please enter what you're looking for (at least 2 characters):"""
        
        st.session_state.chat_data["search_query"] = query
        
        # Use smart search with keyword/location extraction
        db_results, keyword, location, was_corrected = smart_search_business(query)
        
        if db_results:
            # Found in database
            reset_chat_flow()
            
            # Build search info message
            search_info = ""
            if keyword and location:
                search_info = f'🔍 Searching for **"{keyword}"** in **{location}**\n\n'
            elif keyword:
                search_info = f'🔍 Searching for **"{keyword}"**\n\n'
            
            # Show spelling correction if applied
            if was_corrected:
                search_info += f'💡 _(Auto-corrected your search)_\n\n'
            
            response = search_info + f"""✅ **Found {len(db_results)} top-rated business(es):**\n"""
            
            for biz in db_results[:5]:  # Show top 5
                response += format_search_result(biz, is_online=False)
            
            response += get_suggestions_after_search()
            return response
        else:
            # Not found in database - search online
            st.session_state.chat_step = 2
            
            try:
                # Build online search query
                if keyword and location:
                    online_query = f"{keyword} in {location}"
                elif keyword:
                    online_query = keyword
                else:
                    online_query = query
                
                online_results = search_online(online_query)
                
                if online_results:
                    ranked_results = rank_online_results(online_results)
                    reset_chat_flow()
                    
                    response = f"""🔍 No local results found for "{query}".\n"""
                    
                    if keyword and location:
                        response += f"""_(Searched: "{keyword}" in {location})_\n"""
                    
                    response += """\n🌐 **Here are results from online search:**\n"""
                    
                    for biz in ranked_results[:5]:  # Show top 5
                        response += format_search_result(biz, is_online=True)
                    
                    response += """

💡 **Tip:** Would you like to add any of these businesses to our database?
Type "**add a new business**" to register one!"""
                    response += get_suggestions_after_search()
                    return response
                else:
                    reset_chat_flow()
                    
                    # Suggest possible corrections
                    _, _, suggestions = correct_spelling(query)
                    suggestion_text = ""
                    if suggestions:
                        suggestion_text = f"\n\n💡 **Did you mean:** {', '.join(suggestions[:3])}?"
                    
                    return f"""❌ No results found for "{query}" in our database or online.{suggestion_text}

**Try searching for:**
- A different business name
- A category (e.g., "Restaurant", "Salon")
- A location (e.g., city name)

Or type "**add a new business**" to register one!
{get_suggestions_after_search()}"""
                    
            except Exception as e:
                reset_chat_flow()
                return f"""❌ Could not search online: {str(e)}

No local results found for "{query}".

**What would you like to do?**
- 🔍 Try a different search term
- ➕ Type "**add a new business**" to register one
{get_suggestions_after_search()}"""
    
    return None


# ---------------- PHONE LOGIN ---------------- #

if not st.session_state.authenticated:
    st.subheader("📞 Enter your phone number to continue")

    phone = st.text_input(
        "Phone Number",
        placeholder="e.g. 093466 93525"
    )

    if st.button("Continue"):
        phone = phone.strip()

        if len(phone) < 6:
            st.error("Please enter a valid phone number")
        else:
            businesses = get_businesses_by_phone(phone)

            if not businesses:
                st.error("No businesses found for this phone number")
            else:
                st.session_state.authenticated = True
                st.session_state.phone = phone
                st.session_state.businesses = businesses
                st.success("Phone number verified")
                st.rerun()

    st.stop()

# ---------------- SIDEBAR ---------------- #


# ---------------- BUSINESS DASHBOARD ---------------- #

st.subheader("🏢 Your Business")

for biz in st.session_state.businesses:
    st.markdown(f"""
### {biz.get('name')}
- 📍 **Address:** {biz.get('address')}
- 📞 **Phone:** {biz.get('phone_number')}
- ⭐ **Rating:** {biz.get('reviews_average')} ({biz.get('reviews_count')} reviews)
- 🏷️ **Category:** {biz.get('category')}
- 🌐 **Website:** {biz.get('website') or 'N/A'}
""")

st.divider()

# ---------------- UPDATE PANEL ---------------- #

if st.session_state.show_update:
    st.subheader("🛠️ Edit Business Details")

    # Currently assumes 1 business per phone
    business = st.session_state.businesses[0]
    business_id = business.get("id")

    if not business_id:
        st.error("Business ID not found.")
        st.stop()

    # ---- Optional Suggestions ----
    suggestions = get_update_suggestions(business)

    if suggestions:
        with st.expander("📌 Suggestions to improve your business (optional)"):
            for s in suggestions:
                st.markdown(f"- {s}")

    st.divider()

    # ---- Update Form (Always Editable) ----
    with st.form("update_business_form"):
        name = st.text_input("Business Name", value=business.get("name") or "")
        address = st.text_input("Address", value=business.get("address") or "")
        phone_number = st.text_input("Phone Number", value=business.get("phone_number") or "")
        website = st.text_input("Website", value=business.get("website") or "")
        category = st.text_input("Category", value=business.get("category") or "")
        subcategory = st.text_input("Subcategory", value=business.get("subcategory") or "")
        area = st.text_input("Area", value=business.get("area") or "")

        col1, col2 = st.columns(2)
        with col1:
            save = st.form_submit_button("💾 Save Changes")
        with col2:
            cancel = st.form_submit_button("❌ Cancel")

    if save:
        updates = {
            "name": name,
            "address": address,
            "phone_number": phone_number,
            "website": website,
            "category": category,
            "subcategory": subcategory,
            "area": area,
        }

        update_business(business_id, updates)

        st.success("✅ Business details updated successfully")

        # Refresh updated data
        st.session_state.businesses = get_businesses_by_phone(
            st.session_state.phone
        )
        st.session_state.show_update = False
        st.rerun()

    if cancel:
        st.session_state.show_update = False
        st.rerun()

st.divider()

# ---------------- CHAT / SEARCH (ChatGPT-style) ---------------- #

st.subheader("💬 Chat with Business Assistant")

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Show welcome message if chat is empty
if not st.session_state.messages:
    welcome_msg = get_greeting_response()
    st.session_state.messages.append({"role": "assistant", "content": welcome_msg})
    with st.chat_message("assistant"):
        st.markdown(welcome_msg)

user_input = st.chat_input("Type your message here...")

if user_input:
    # Add user message to history
    st.session_state.messages.append(
        {"role": "user", "content": user_input}
    )

    with st.chat_message("user"):
        st.markdown(user_input)

    # Check for bot/spam
    if is_bot(user_input):
        with st.chat_message("assistant"):
            st.error("Invalid or suspicious input detected")
        st.stop()

    try:
        # Process through chatbot logic
        chatbot_response = process_chatbot_response(user_input)
        
        if chatbot_response:
            # Chatbot handled it
            answer = chatbot_response
        else:
            # Fallback: Use smart search with online fallback
            db_results, keyword, location, was_corrected = smart_search_business(user_input)
            
            if db_results:
                # Found in database
                search_info = ""
                if keyword and location:
                    search_info = f'🔍 Searching for **"{keyword}"** in **{location}**\n\n'
                elif keyword:
                    search_info = f'🔍 Searching for **"{keyword}"**\n\n'
                
                if was_corrected:
                    search_info += '💡 _(Auto-corrected your search)_\n\n'
                
                answer = search_info + f"✅ **Found {len(db_results)} top-rated business(es):**\n"
                
                for biz in db_results[:5]:
                    answer += format_search_result(biz, is_online=False)
                
                answer += get_suggestions_after_search()
            else:
                # Not found in database - try online search
                try:
                    # Build online search query
                    if keyword and location:
                        online_query = f"{keyword} in {location}"
                    elif keyword:
                        online_query = keyword
                    else:
                        online_query = user_input
                    
                    online_results = search_online(online_query)
                    
                    if online_results:
                        ranked_results = rank_online_results(online_results)
                        
                        answer = f"""🔍 No local results found for "{user_input}".\n"""
                        
                        if keyword and location:
                            answer += f"""_(Searched: "{keyword}" in {location})_\n"""
                        
                        answer += """\n🌐 **Here are results from online search:**\n"""
                        
                        for biz in ranked_results[:5]:
                            answer += format_search_result(biz, is_online=True)
                        
                        answer += """

💡 **Tip:** Would you like to add any of these businesses to our database?
Type "**add a new business**" to register one!"""
                        answer += get_suggestions_after_search()
                    else:
                        # No online results either
                        answer = f"""❌ No results found for "{user_input}" in our database or online.

**Try searching for:**
- A different business name
- A category (e.g., "Restaurant", "Salon")
- A location (e.g., city name)

Or type "**add a new business**" to register one!
{get_suggestions_after_search()}"""
                        
                except Exception as online_err:
                    # Online search failed
                    answer = f"""❌ No local results found for "{user_input}".

Online search also failed: {str(online_err)}

**What would you like to do?**
- 🔍 Try a different search term
- ➕ Type "**add a new business**" to register one
{get_suggestions_after_search()}"""

        st.session_state.messages.append(
            {"role": "assistant", "content": answer}
        )

        with st.chat_message("assistant"):
            st.markdown(answer)

    except Exception as e:
        error_msg = f"""❌ An error occurred: {str(e)}

What would you like to do?
- 🔍 Type "**show my business**"
- ✏️ Type "**update my business**"
- ➕ Type "**add a new business**" """
        st.session_state.messages.append({"role": "assistant", "content": error_msg})
        with st.chat_message("assistant"):
            st.markdown(error_msg)
