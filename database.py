"""
OptiKinesis Database & Storage Layer
Stores Patient Profiles, Caregivers, Everyday Help Requests,
BreathGuard Vitals & Consent, and Communication Logs.
"""

import sqlite3
import json
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "optikinesis.db")


def get_db_connection():
    """Create a thread-safe connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables with schema migrations and defaults."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Patient Profile Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            preferred_name TEXT NOT NULL,
            condition_disclosed TEXT,
            mobility_limitations TEXT, -- JSON array
            can_speak INTEGER DEFAULT 1,
            preferred_communication TEXT DEFAULT 'eye_control',
            accessibility_settings TEXT, -- JSON object
            updated_at REAL
        )
    """)

    # Schema migrations for patient_profile & caregivers
    migrations = [
        "ALTER TABLE patient_profile ADD COLUMN onboarding_completed INTEGER DEFAULT 0",
        "ALTER TABLE patient_profile ADD COLUMN condition_categories TEXT DEFAULT '[]'",
        "ALTER TABLE patient_profile ADD COLUMN floating_keyboard INTEGER DEFAULT 0",
        "ALTER TABLE caregivers ADD COLUMN contact_type TEXT DEFAULT 'caregiver'",
    ]
    for m in migrations:
        try:
            cursor.execute(m)
        except sqlite3.OperationalError:
            pass

    # 2. Caregivers & Trusted Relatives Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS caregivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            relationship TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            email TEXT,
            is_primary INTEGER DEFAULT 0,
            is_verified INTEGER DEFAULT 0,
            preferred_channel TEXT DEFAULT 'voice', -- 'voice', 'sms', 'video'
            created_at REAL
        )
    """)

    # 3. Everyday Help Requests Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS help_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            note TEXT,
            caregiver_id INTEGER,
            caregiver_name TEXT,
            caregiver_phone TEXT,
            status TEXT DEFAULT 'pending', -- 'pending', 'acknowledged', 'completed', 'cancelled'
            created_at REAL,
            acknowledged_at REAL
        )
    """)

    # 4. BreathGuard Consent & Safeguards Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS breathguard_consent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            permission_granted INTEGER DEFAULT 0,
            granted_at REAL,
            revoked_at REAL
        )
    """)

    # 5. BreathGuard Alert Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS breathguard_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            threshold REAL NOT NULL,
            rule_name TEXT NOT NULL,
            severity TEXT DEFAULT 'warning', -- 'warning', 'critical'
            caregiver_contacted TEXT,
            status TEXT DEFAULT 'triggered', -- 'triggered', 'notified', 'acknowledged'
            created_at REAL
        )
    """)

    # 6. Communication & Call History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_type TEXT NOT NULL, -- 'voice_alert', 'video', 'routine_help'
            caregiver_name TEXT,
            phone_number TEXT,
            status TEXT,
            duration_secs INTEGER DEFAULT 0,
            notes TEXT,
            created_at REAL
        )
    """)

    # Check if default patient profile exists; if not, create initial profile
    cursor.execute("SELECT COUNT(*) as cnt FROM patient_profile")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT INTO patient_profile 
            (full_name, preferred_name, condition_disclosed, mobility_limitations, can_speak, preferred_communication, accessibility_settings, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Alex Mercer",
            "Alex",
            "ALS / Motor Neuron Limitation",
            json.dumps(["Limited arm mobility", "Non-verbal communication preferred"]),
            0,
            "eye_control",
            json.dumps({
                "cursor_speed": 0.5,
                "blink_sensitivity": 0.22,
                "cursor_scope": 1.0,
                "dwell_click_enabled": False,
                "high_contrast": True
            }),
            time.time()
        ))

    # Check if default caregiver exists; if not, create one
    cursor.execute("SELECT COUNT(*) as cnt FROM caregivers")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT INTO caregivers 
            (name, relationship, phone_number, email, is_primary, is_verified, preferred_channel, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Sarah Mercer",
            "Sister / Primary Caregiver",
            os.getenv("EMERGENCY_CONTACT", "+1234567890"),
            "sarah.mercer@example.com",
            1,
            1,
            "voice",
            time.time()
        ))

    # Ensure initial consent record exists (defaulting to False for safeguard)
    cursor.execute("SELECT COUNT(*) as cnt FROM breathguard_consent")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT INTO breathguard_consent (permission_granted, granted_at, revoked_at)
            VALUES (0, NULL, NULL)
        """)

    conn.commit()
    conn.close()


# --- PATIENT PROFILE REPOSITORY ---
def get_patient_profile():
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM patient_profile ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["mobility_limitations"] = json.loads(data.get("mobility_limitations") or "[]")
    data["accessibility_settings"] = json.loads(data.get("accessibility_settings") or "{}")
    data["condition_categories"] = json.loads(data.get("condition_categories") or "[]")
    data["onboarding_completed"] = int(data.get("onboarding_completed") or 0)
    data["floating_keyboard"] = int(data.get("floating_keyboard") or 0)
    return data


def update_patient_profile(profile_data):
    conn = get_db_connection()
    existing = get_patient_profile() or {}
    
    full_name = profile_data.get("full_name", existing.get("full_name", "User"))
    preferred_name = profile_data.get("preferred_name", existing.get("preferred_name", full_name))
    condition_disclosed = profile_data.get("condition_disclosed", existing.get("condition_disclosed", ""))
    mobility = profile_data.get("mobility_limitations", existing.get("mobility_limitations", []))
    can_speak = int(profile_data.get("can_speak", existing.get("can_speak", 1)))
    preferred_comms = profile_data.get("preferred_communication", existing.get("preferred_communication", "eye_control"))
    access_settings = profile_data.get("accessibility_settings", existing.get("accessibility_settings", {}))
    
    onboarding_completed = int(profile_data.get("onboarding_completed", existing.get("onboarding_completed", 0)))
    condition_cats = profile_data.get("condition_categories", existing.get("condition_categories", []))
    floating_kb = int(profile_data.get("floating_keyboard", existing.get("floating_keyboard", 0)))

    conn.execute("""
        UPDATE patient_profile SET
            full_name = ?,
            preferred_name = ?,
            condition_disclosed = ?,
            mobility_limitations = ?,
            can_speak = ?,
            preferred_communication = ?,
            accessibility_settings = ?,
            onboarding_completed = ?,
            condition_categories = ?,
            floating_keyboard = ?,
            updated_at = ?
        WHERE id = (SELECT id FROM patient_profile ORDER BY id DESC LIMIT 1)
    """, (
        full_name,
        preferred_name,
        condition_disclosed,
        json.dumps(mobility),
        can_speak,
        preferred_comms,
        json.dumps(access_settings),
        onboarding_completed,
        json.dumps(condition_cats),
        floating_kb,
        time.time()
    ))
    conn.commit()
    conn.close()
    return get_patient_profile()


# --- CAREGIVERS & CONTACTS REPOSITORY ---
def get_all_caregivers(contact_type=None):
    conn = get_db_connection()
    if contact_type:
        rows = conn.execute("SELECT * FROM caregivers WHERE contact_type = ? ORDER BY is_primary DESC, id ASC", (contact_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM caregivers ORDER BY is_primary DESC, id ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_caregivers_only():
    return get_all_caregivers(contact_type="caregiver")


def get_friends():
    return get_all_caregivers(contact_type="friend")


def get_primary_caregiver():
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM caregivers WHERE is_primary = 1 AND (contact_type = 'caregiver' OR contact_type IS NULL) LIMIT 1").fetchone()
    if not row:
        row = conn.execute("SELECT * FROM caregivers WHERE (contact_type = 'caregiver' OR contact_type IS NULL) ORDER BY id ASC LIMIT 1").fetchone()
    if not row:
        row = conn.execute("SELECT * FROM caregivers ORDER BY id ASC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def add_caregiver(name, relationship, phone_number, email="", is_primary=0, preferred_channel="voice", contact_type="caregiver"):
    conn = get_db_connection()
    if is_primary:
        conn.execute("UPDATE caregivers SET is_primary = 0 WHERE contact_type = 'caregiver'")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO caregivers (name, relationship, phone_number, email, is_primary, is_verified, preferred_channel, contact_type, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
    """, (name, relationship, phone_number, email, int(is_primary), preferred_channel, contact_type, time.time()))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def add_friend(name, phone_number, relationship="Friend"):
    return add_caregiver(
        name=name,
        relationship=relationship or "Friend",
        phone_number=phone_number,
        is_primary=0,
        contact_type="friend"
    )


def delete_caregiver(caregiver_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM caregivers WHERE id = ?", (caregiver_id,))
    conn.commit()
    conn.close()


def delete_friend(friend_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM caregivers WHERE id = ? AND contact_type = 'friend'", (friend_id,))
    conn.commit()
    conn.close()


def update_caregiver(caregiver_id, name, relationship, phone_number, is_primary=0, preferred_channel="voice"):
    conn = get_db_connection()
    if is_primary:
        conn.execute("UPDATE caregivers SET is_primary = 0")
    conn.execute("""
        UPDATE caregivers SET
            name = ?,
            relationship = ?,
            phone_number = ?,
            is_primary = ?,
            preferred_channel = ?
        WHERE id = ?
    """, (name, relationship, phone_number, int(is_primary), preferred_channel, caregiver_id))
    conn.commit()
    conn.close()


# --- EVERYDAY HELP REQUESTS REPOSITORY ---
def create_help_request(category, note="", caregiver_id=None):
    conn = get_db_connection()
    caregiver = None
    if caregiver_id:
        c_row = conn.execute("SELECT * FROM caregivers WHERE id = ?", (caregiver_id,)).fetchone()
        if c_row:
            caregiver = dict(c_row)
    if not caregiver:
        caregiver = get_primary_caregiver()

    cg_id = caregiver["id"] if caregiver else None
    cg_name = caregiver["name"] if caregiver else "Primary Caregiver"
    cg_phone = caregiver["phone_number"] if caregiver else ""

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO help_requests (category, note, caregiver_id, caregiver_name, caregiver_phone, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (category, note, cg_id, cg_name, cg_phone, time.time()))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "id": req_id,
        "category": category,
        "note": note,
        "caregiver_name": cg_name,
        "caregiver_phone": cg_phone,
        "status": "pending",
        "created_at": time.time()
    }


def get_help_requests(limit=20):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM help_requests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_help_request_status(request_id, status):
    conn = get_db_connection()
    ack_time = time.time() if status in ['acknowledged', 'completed'] else None
    conn.execute("""
        UPDATE help_requests SET status = ?, acknowledged_at = COALESCE(acknowledged_at, ?) WHERE id = ?
    """, (status, ack_time, request_id))
    conn.commit()
    conn.close()


# --- BREATHGUARD CONSENT SAFEGUARD ---
def get_breathguard_consent():
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM breathguard_consent ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return bool(row["permission_granted"]) if row else False


def set_breathguard_consent(granted: bool):
    conn = get_db_connection()
    now = time.time()
    if granted:
        conn.execute("UPDATE breathguard_consent SET permission_granted = 1, granted_at = ?, revoked_at = NULL", (now,))
    else:
        conn.execute("UPDATE breathguard_consent SET permission_granted = 0, revoked_at = ?", (now,))
    conn.commit()
    conn.close()
    return granted


# --- BREATHGUARD ALERTS ---
def log_breathguard_alert(metric, value, threshold, rule_name, severity="critical", caregiver_contacted=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO breathguard_alerts (metric, value, threshold, rule_name, severity, caregiver_contacted, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'notified', ?)
    """, (metric, value, threshold, rule_name, severity, caregiver_contacted, time.time()))
    alert_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return alert_id


def get_breathguard_alerts(limit=20):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM breathguard_alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- CALL LOGS ---
def log_call_attempt(call_type, caregiver_name, phone_number, status, duration_secs=0, notes=""):
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO call_logs (call_type, caregiver_name, phone_number, status, duration_secs, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (call_type, caregiver_name, phone_number, status, duration_secs, notes, time.time()))
    conn.commit()
    conn.close()


# Initialize database automatically on import
init_db()
