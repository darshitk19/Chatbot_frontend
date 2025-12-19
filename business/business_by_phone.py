import sqlite3
from db.config import DB_PATH
from business.business_utils import normalize_phone

def get_businesses_by_phone(phone: str):
    """
    Get businesses by phone number using exact normalized matching.
    
    Rules:
    - Uses exact match only (no LIKE, no partial match)
    - Normalizes phone numbers before comparison
    - Returns all businesses with matching phone_number
    - Ordered by created_at DESC
    """
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all businesses and normalize phone numbers for exact match
    cur.execute("SELECT * FROM google_maps_listings")
    rows = cur.fetchall()
    conn.close()

    # Filter by exact normalized phone number match
    matching_businesses = []
    for row in rows:
        # Convert Row to dict for easier access
        row_dict = dict(row)
        db_phone = row_dict.get('phone_number', '') or ''
        db_normalized = normalize_phone(db_phone)
        # Exact match only
        if normalized_phone == db_normalized:
            matching_businesses.append(row_dict)
    
    # Sort by created_at DESC (most recent first)
    # If created_at is not available, keep original order
    try:
        matching_businesses.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    except:
        pass
    
    return matching_businesses


def get_business_by_id(business_id: int):
    """Fetch a single business by its primary key."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM google_maps_listings
        WHERE id = ?
        LIMIT 1
        """,
        (business_id,),
    )

    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    cols = [d[0] for d in cur.description]
    conn.close()

    return dict(zip(cols, row))


def get_latest_business():
    """Fetch the most recently created business (highest id)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM google_maps_listings
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    cols = [d[0] for d in cur.description]
    conn.close()

    return dict(zip(cols, row))
