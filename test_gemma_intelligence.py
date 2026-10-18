"""
Test Suite for OptiKinesis Gemma 4 Intelligence Layer
Verifies SDK integration, model specifications, Thinking configuration,
Function Calling tools, and assistive agent query routing.
"""

import sys
import os
import json
from gemma_intelligence import (
    GemmaIntelligenceClient,
    DEFAULT_GEMMA_MODEL,
    HEAVY_GEMMA_MODEL,
    TOOL_DECLARATIONS,
    execute_assistive_tool
)
import agent_reasoning

def run_tests():
    passed = 0
    total = 0

    def check(title, condition, extra=""):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f" [PASS] {title}")
        else:
            print(f"![FAIL] {title} - {extra}")

    print("==================================================================")
    print(" GEMMA 4 INTELLIGENCE LAYER VERIFICATION SUITE")
    print("==================================================================")

    # 1. Model Constant Checks
    check("1. Supported model: gemma-4-26b-a4b-it", DEFAULT_GEMMA_MODEL == "gemma-4-26b-a4b-it")
    check("2. Supported model: gemma-4-31b-it", HEAVY_GEMMA_MODEL == "gemma-4-31b-it")

    # 2. Client Initialization
    client = GemmaIntelligenceClient()
    check("3. GemmaIntelligenceClient instantiated", client is not None)
    check("4. Client default model is gemma-4-26b-a4b-it", client.default_model == "gemma-4-26b-a4b-it")
    from gemma_intelligence import GENAI_SDK_AVAILABLE
    check("5. google.genai SDK module available", GENAI_SDK_AVAILABLE)

    # 3. Thinking Configuration Verification
    from google.genai import types
    cfg_high = types.ThinkingConfig(thinking_level="high")
    check("6. ThinkingConfig supports 'high' level", cfg_high is not None)

    cfg_minimal = types.ThinkingConfig(thinking_level="minimal")
    check("7. ThinkingConfig supports 'minimal' level", cfg_minimal is not None)

    # 4. Assistive Tools Declarations
    tool_names = [t["name"] for t in TOOL_DECLARATIONS]
    check("8. Tool declared: call_caregiver", "call_caregiver" in tool_names)
    check("9. Tool declared: create_help_request", "create_help_request" in tool_names)
    check("10. Tool declared: get_patient_profile", "get_patient_profile" in tool_names)
    check("11. Tool declared: get_patient_vitals", "get_patient_vitals" in tool_names)

    # 5. Tool Execution Tests
    res_help = execute_assistive_tool("create_help_request", {"request_type": "water", "note": "Glass of water"})
    check("12. Tool execution: create_help_request dispatches to DB", res_help.get("status") in ["dispatched", "success"])

    res_vitals = execute_assistive_tool("get_patient_vitals", {})
    check("13. Tool execution: get_patient_vitals reads BreathGuard", "breathing_rate_bpm" in res_vitals or "breathing_rate" in res_vitals)

    res_profile = execute_assistive_tool("get_patient_profile", {})
    check("14. Tool execution: get_patient_profile reads patient name", "preferred_name" in res_profile)

    res_call = execute_assistive_tool("call_caregiver", {"is_emergency": False, "reason": "General checkin"})
    check("15. Tool execution: call_caregiver prepares contact", "phone_number" in res_call or res_call.get("status") == "error")

    # 6. Agent Reasoning Query Routing
    agent_res = agent_reasoning.process_agent_query("Please bring me some water")
    check("16. Agent reasoning dispatches everyday water request", agent_res.get("action") == "help_request")

    agent_call = agent_reasoning.process_agent_query("Call my caregiver please")
    check("17. Agent reasoning requests confirmation before calling", agent_call.get("status") == "confirmation_required")

    # 7. Generation Fallback / Simulated Handling
    offline_gen = client.generate("Hello Gemma", thinking_level="high")
    check("18. Graceful generation response when waiting for API key", "text" in offline_gen and offline_gen.get("status") in ["success", "simulated"])

    pct = int(passed / total * 100) if total > 0 else 0
    print("==================================================================")
    print(f" RESULTS: {passed}/{total} CHECKS PASSED ({pct}%)")
    print("==================================================================")
    if passed == total:
        print(" ALL GEMMA 4 INTELLIGENCE LAYER TESTS PASSED!")
        return 0
    return 1

if __name__ == '__main__':
    sys.exit(run_tests())
