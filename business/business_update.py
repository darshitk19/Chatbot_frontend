import sqlite3
from db.config import DB_PATH
from business.business_utils import normalize_phone

ALLOWED_FIELDS = [
    "name",
    "address",
    "phone_number",
    "website",
    "category",
    "subcategory",
    "area",
    "city",
    "state",
]

def update_business(business_id: int = None, updates: dict = None, phone_number: str = None):
    """
    Update business details directly in the existing record.
    Can update by business_id or by phone_number if id is not available.
    Updates all provided fields (including empty strings to clear fields).
    Only updates fields that are in ALLOWED_FIELDS.
    Phone numbers are normalized before matching and updating.
    Returns True if update was successful, False otherwise.
    """
    if updates is None or not updates:
        return False
    
    # Filter to allowed fields only, preserve all values (including empty strings)
    filtered_updates = {}
    for k, v in updates.items():
        if k in ALLOWED_FIELDS:
            if v is None:
                filtered_updates[k] = ""
            elif isinstance(v, str):
                if k == "phone_number":
                    filtered_updates[k] = normalize_phone(v.strip())
                else:
                    filtered_updates[k] = v.strip()
            else:
                filtered_updates[k] = v

    if not filtered_updates:
        return False

    fields = [f"{k} = ?" for k in filtered_updates]
    values = list(filtered_updates.values())

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        matching_rowids = []
        
        # Find matching records by ID or phone
        if business_id is not None:
            # Check if this ID exists
            cur.execute("SELECT rowid FROM google_maps_listings WHERE id = ?", (business_id,))
            row = cur.fetchone()
            if row:
                matching_rowids.append(row[0])
            else:
                # ID might be the rowid itself
                cur.execute("SELECT rowid FROM google_maps_listings WHERE rowid = ?", (business_id,))
                row = cur.fetchone()
                if row:
                    matching_rowids.append(row[0])
        
        # If no match by ID, try phone number
        if not matching_rowids and phone_number:
            normalized_phone = normalize_phone(phone_number)
            if normalized_phone:
                cur.execute("SELECT rowid, phone_number FROM google_maps_listings")
                all_rows = cur.fetchall()
                for row in all_rows:
                    db_phone = row[1] or ""
                    if normalize_phone(db_phone) == normalized_phone:
                        matching_rowids.append(row[0])
        
        if not matching_rowids:
            return False
        
        # Update matching records using rowid
        placeholders = ','.join(['?'] * len(matching_rowids))
        query = f"""
            UPDATE google_maps_listings
            SET {', '.join(fields)}
            WHERE rowid IN ({placeholders})
        """
        values.extend(matching_rowids)
        cur.execute(query, values)
        
        rows_affected = cur.rowcount
        conn.commit()
        return rows_affected > 0
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Update business error: {e}")
        return False
    finally:
        if conn:
            conn.close()

