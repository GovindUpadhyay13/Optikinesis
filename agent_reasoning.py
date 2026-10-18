"""
Agent Reasoning Layer (Gemma / AI Systems Coordinator)
Prepares dignified, empathetic, and truthful communications between
the patient, caregivers, and assistive automation modules.
Strictly disallows fabricated medical conclusions or unrestricted execution.
"""

import os
import json
import logging
from typing import Dict, Any, List

import database
import communication_service

logger = logging.getLogger("agent_reasoning")
logger.setLevel(logging.INFO)

GEMMA_API_KEY = os.getenv("GEMMA_API_KEY", "")


# Explicitly Permitted Tools
def tool_get_patient_profile() -> Dict[str, Any]:
    """Retrieve patient's profile and communication preferences."""
    profile = database.get_patient_profile()
    if not profile:
        return {"name": "Patient", "preferred_name": "Friend", "preferences": {}}
    return {
        "preferred_name": profile["preferred_name"],
        "can_speak": bool(profile["can_speak"]),
        "mobility": profile["mobility_limitations"],
        "preferences": profile["accessibility_settings"]
    }


def tool_list_caregivers() -> List[Dict[str, Any]]:
    """List authorized caregivers and trusted relatives."""
    caregivers = database.get_all_caregivers()
    return [{
        "id": c["id"],
        "name": c["name"],
        "relationship": c["relationship"],
        "phone": c["phone_number"],
        "is_primary": bool(c["is_primary"])
    } for c in caregivers]


def tool_create_help_request(category: str, note: str = "", caregiver_id: int = None) -> Dict[str, Any]:
    """Create and dispatch an everyday assistance request."""
    return database.create_help_request(category=category, note=note, caregiver_id=caregiver_id)


def compose_caregiver_alert(rule_name: str, metric: str, value: float, severity: str) -> str:
    """
    Format a clear, calm, and truthful spoken/SMS alert for the caregiver.
    Strictly reports verified measurements without clinical speculation.
    """
    profile = database.get_patient_profile()
    patient_name = profile["preferred_name"] if profile else "Alex"

    metric_readable = "breathing rate" if "breath" in metric.lower() else "pulse rate"
    unit = "breaths per minute" if "breath" in metric.lower() else "beats per minute"

    message = (
        f"OptiKinesis BreathGuard has detected an alert: {rule_name}. "
        f"The current measured {metric_readable} is {value:.1f} {unit}. "
        f"Please check in with {patient_name} directly to ensure comfort and safety."
    )
    return message


def compose_assistance_message(category: str, note: str = "") -> str:
    """Compose everyday assistance request text for caregivers."""
    profile = database.get_patient_profile()
    patient_name = profile["preferred_name"] if profile else "Alex"

    category_phrases = {
        "water": f"{patient_name} requests water or a beverage.",
        "food": f"{patient_name} is requesting assistance with a meal.",
        "physical": f"{patient_name} needs physical assistance.",
        "position": f"{patient_name} would like help adjusting seating or posture.",
        "personal_care": f"{patient_name} needs help with personal care.",
        "talk": f"{patient_name} would like to talk with you.",
        "general": f"{patient_name} is requesting assistance."
    }

    base = category_phrases.get(category.lower(), f"{patient_name} needs help with: {category}.")
    if note and len(note.strip()) > 0:
        base += f" Note: \"{note.strip()}\""
    return base


def process_agent_query(user_query: str) -> Dict[str, Any]:
    """
    Process patient query or voice request through Gemma reasoning layer,
    or through deterministic structured fallback.
    """
    query = user_query.lower()
    
    # 1. Direct tool routing
    if "help" in query or "assist" in query or "water" in query or "food" in query:
        cat = "general"
        if "water" in query or "drink" in query:
            cat = "water"
        elif "food" in query or "eat" in query or "meal" in query:
            cat = "food"
        elif "position" in query or "move" in query:
            cat = "position"
        elif "talk" in query:
            cat = "talk"
        
        req = tool_create_help_request(category=cat, note=user_query)
        msg = compose_assistance_message(cat, note=user_query)
        
        return {
            "status": "success",
            "action": "help_request",
            "category": cat,
            "message": msg,
            "request_id": req["id"]
        }

    elif "call" in query or "dial" in query:
        primary = database.get_primary_caregiver()
        cg_name = primary["name"] if primary else "Caregiver"
        return {
            "status": "confirmation_required",
            "action": "call_caregiver",
            "caregiver": primary,
            "message": f"Would you like me to place a call to {cg_name}?"
        }

    return {
        "status": "info",
        "action": "general",
        "message": f"OptiKinesis ready: {user_query}"
    }
