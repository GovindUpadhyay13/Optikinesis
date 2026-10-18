"""
OptiKinesis — Gemma 4 Intelligence Layer
Unified generative AI reasoning client for Gemma 4 models via Google GenAI SDK and REST API.

Supported Models:
- gemma-4-26b-a4b-it (Default: lightweight, low-latency, reasoning-enabled)
- gemma-4-31b-it (High-capacity multi-step reasoning)

Capabilities Implemented:
1. Basic Generation
2. Thinking Process ("high" or "minimal")
3. Image Understanding (Multimodal Vision)
4. System Instructions
5. Multi-turn Chat Conversations
6. Function Calling / Tools (Assistive Dispatch, Vitals, Profile)
7. Google Search Grounding with citations
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Union

from dotenv import load_dotenv
load_dotenv()

try:
    from google import genai
    from google.genai import types
    GENAI_SDK_AVAILABLE = True
except ImportError:
    GENAI_SDK_AVAILABLE = False

import database

logger = logging.getLogger("gemma_intelligence")
logger.setLevel(logging.INFO)

# Default Model Specifications
DEFAULT_GEMMA_MODEL = "gemma-4-26b-a4b-it"
HEAVY_GEMMA_MODEL = "gemma-4-31b-it"

# Assistive System Persona for OptiKinesis
DEFAULT_SYSTEM_INSTRUCTION = (
    "You are the OptiKinesis Assistive Intelligence Core. "
    "Your purpose is to empower individuals with ALS, quadriplegia, and motor limitations. "
    "Be respectful, calm, clear, and dignified. Never invent or hallucinate clinical medical facts. "
    "When a user needs assistance or caregiver contact, use the available function tools promptly."
)


# =========================================================================
# ASSISTIVE TOOL DECLARATIONS FOR FUNCTION CALLING
# =========================================================================

TOOL_DECLARATIONS = [
    {
        "name": "call_caregiver",
        "description": "Trigger an automated phone call or alert to the patient's caregiver.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for calling the caregiver (e.g., 'patient feels uncomfortable', 'urgent check-in').",
                },
                "is_emergency": {
                    "type": "boolean",
                    "description": "True if urgent assistance is required, False for routine request.",
                },
            },
            "required": ["reason"],
        },
    },
    {
        "name": "create_help_request",
        "description": "Dispatch an everyday assistance request for water, meals, posture adjustment, personal care, or companionship.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category of help: 'Water / Drink', 'Food / Meal', 'Physical Assistance', 'Adjust Position', 'Personal Care', or 'Just Want to Talk'.",
                },
                "note": {
                    "type": "string",
                    "description": "Specific optional note or context from patient.",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_patient_profile",
        "description": "Retrieve the patient's preferred name, condition, and communication preferences.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_patient_vitals",
        "description": "Retrieve the latest non-contact respiratory and pulse vitals from BreathGuard Presage monitor.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


def execute_assistive_tool(function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute local system functions invoked by Gemma model function calls."""
    try:
        if function_name == "call_caregiver":
            primary = database.get_primary_caregiver()
            cg_name = primary["name"] if primary else "Caregiver"
            return {
                "status": "initiated",
                "caregiver_name": cg_name,
                "phone_number": primary.get("phone_number") if primary else None,
                "reason": args.get("reason", "Patient requested contact"),
                "is_emergency": args.get("is_emergency", False)
            }
        
        elif function_name == "create_help_request":
            cat = args.get("category", "General Assistance")
            note = args.get("note", "")
            req = database.create_help_request(category=cat, note=note)
            return {
                "status": "dispatched",
                "request_id": req.get("id"),
                "caregiver_name": req.get("caregiver_name"),
                "category": cat
            }
        
        elif function_name == "get_patient_profile":
            prof = database.get_patient_profile()
            return {
                "status": "success",
                "preferred_name": prof.get("preferred_name", "Alex"),
                "condition": prof.get("condition_disclosed", "Motor limitation"),
                "can_speak": prof.get("can_speak", True)
            }
        
        elif function_name == "get_patient_vitals":
            import breathguard
            summary = breathguard.breathguard_engine.get_vitals_summary()
            return {
                "status": "success",
                "permission_granted": summary.get("permission_granted", False),
                "breathing_rate_bpm": summary.get("breathing_rate"),
                "pulse_rate_bpm": summary.get("pulse_rate"),
                "alert_status": summary.get("active_alert")
            }
        
        else:
            return {"status": "error", "message": f"Unknown tool: {function_name}"}

    except Exception as e:
        logger.error(f"[Gemma Tools] Error executing {function_name}: {e}")
        return {"status": "error", "error": str(e)}


# =========================================================================
# GEMMA 4 INTELLIGENCE CLIENT
# =========================================================================

class GemmaIntelligenceClient:
    """
    Client for interacting with Gemma 4 models (gemma-4-26b-a4b-it and gemma-4-31b-it)
    hosted on the Google Gemini API.
    """

    def __init__(self, api_key: Optional[str] = None, default_model: str = DEFAULT_GEMMA_MODEL):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.default_model = default_model
        self._sdk_client = None

        if self.api_key and GENAI_SDK_AVAILABLE:
            try:
                self._sdk_client = genai.Client(api_key=self.api_key)
                logger.info(f"[Gemma] Client initialized with model: {self.default_model}")
            except Exception as e:
                logger.warning(f"[Gemma] SDK initialization failed, will use REST: {e}")

    def is_configured(self) -> bool:
        """Check if an API key is active."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    # ---------------------------------------------------------------------
    # 1. Basic Generation with Optional Thinking Control & System Prompt
    # ---------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        thinking_level: Optional[str] = None,  # "high" or "minimal"
        system_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate content using Gemma 4 with optional thinking process control.
        thinking_level: "high" enables multi-step internal reasoning, "minimal" disables it.
        """
        target_model = model or self.default_model

        if not self.is_configured():
            return {
                "status": "simulated",
                "model": target_model,
                "text": f"[Gemma 4 ({target_model}) offline — Set GEMINI_API_KEY to activate]: Received: {prompt}",
                "thinking": "No API key configured."
            }

        if self._sdk_client:
            try:
                # Build configuration
                config_args = {}
                if system_instruction:
                    config_args["system_instruction"] = system_instruction
                
                if thinking_level in ["high", "minimal"]:
                    config_args["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

                config = types.GenerateContentConfig(**config_args) if config_args else None

                response = self._sdk_client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config
                )

                return {
                    "status": "success",
                    "model": target_model,
                    "text": response.text,
                    "raw_response": response
                }
            except Exception as e:
                logger.error(f"[Gemma SDK] Generation error: {e}")
                return self._generate_rest(prompt, target_model, thinking_level, system_instruction)

        return self._generate_rest(prompt, target_model, thinking_level, system_instruction)

    # ---------------------------------------------------------------------
    # 2. Multi-turn Chat Conversation
    # ---------------------------------------------------------------------
    def create_chat(self, model: Optional[str] = None, system_instruction: Optional[str] = None):
        """
        Create a multi-turn conversation session with history tracking.
        """
        target_model = model or self.default_model
        if self._sdk_client:
            config = None
            if system_instruction:
                config = types.GenerateContentConfig(system_instruction=system_instruction)
            return self._sdk_client.chats.create(model=target_model, config=config)
        return None

    # ---------------------------------------------------------------------
    # 3. Image Understanding (Multimodal)
    # ---------------------------------------------------------------------
    def analyze_image(
        self,
        image_path: str,
        prompt: str = "Analyze this image for patient comfort, posture, and safety.",
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gemma 4 multimodal vision analysis using image input.
        """
        target_model = model or self.default_model

        if not self.is_configured():
            return {
                "status": "simulated",
                "model": target_model,
                "text": f"[Gemma Vision offline] Image {image_path} received: {prompt}"
            }

        if self._sdk_client:
            try:
                uploaded_file = self._sdk_client.files.upload(file=image_path)
                response = self._sdk_client.models.generate_content(
                    model=target_model,
                    contents=[uploaded_file, prompt],
                )
                return {
                    "status": "success",
                    "model": target_model,
                    "text": response.text
                }
            except Exception as e:
                logger.error(f"[Gemma Vision] Error: {e}")
                return {"status": "error", "error": str(e)}

        return {"status": "error", "error": "SDK required for file upload analysis"}

    # ---------------------------------------------------------------------
    # 4. Function Calling (Agentic Reasoning with Tools)
    # ---------------------------------------------------------------------
    def reason_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        system_instruction: Optional[str] = DEFAULT_SYSTEM_INSTRUCTION,
    ) -> Dict[str, Any]:
        """
        Gemma 4 Tool / Function Calling.
        The model determines whether to call assistive actions or respond conversationally.
        """
        target_model = model or self.default_model
        tools_list = tools or TOOL_DECLARATIONS

        if not self.is_configured():
            # Fallback to local heuristic dispatch when key is absent
            import agent_reasoning
            return agent_reasoning.process_agent_query(prompt)

        if self._sdk_client:
            try:
                sdk_tools = types.Tool(function_declarations=tools_list)
                config = types.GenerateContentConfig(
                    tools=[sdk_tools],
                    system_instruction=system_instruction
                )

                response = self._sdk_client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config,
                )

                # Check if function was invoked
                if response.function_calls:
                    executed_results = []
                    for fc in response.function_calls:
                        res = execute_assistive_tool(fc.name, dict(fc.args))
                        executed_results.append({
                            "tool": fc.name,
                            "arguments": dict(fc.args),
                            "execution_result": res
                        })
                    
                    return {
                        "status": "function_called",
                        "model": target_model,
                        "actions": executed_results,
                        "text": f"Executed action: {executed_results[0]['tool']}"
                    }

                return {
                    "status": "conversational",
                    "model": target_model,
                    "text": response.text
                }

            except Exception as e:
                logger.error(f"[Gemma Function Calling] Error: {e}")
                import agent_reasoning
                return agent_reasoning.process_agent_query(prompt)

        return {"status": "unsupported", "message": "SDK required for advanced tool declarations"}

    # ---------------------------------------------------------------------
    # 5. Grounding with Google Search
    # ---------------------------------------------------------------------
    def search_grounded(self, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Ground Gemma 4 responses in real-time web data via Google Search.
        """
        target_model = model or self.default_model
        if not self.is_configured():
            return {"status": "simulated", "text": f"[Gemma Search Grounding offline]: {prompt}"}

        if self._sdk_client:
            try:
                config = types.GenerateContentConfig(tools=[{"google_search": {}}])
                response = self._sdk_client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config
                )

                citations = []
                if response.candidates and response.candidates[0].grounding_metadata:
                    chunks = getattr(response.candidates[0].grounding_metadata, "grounding_chunks", [])
                    for ch in chunks:
                        if hasattr(ch, "web") and ch.web:
                            citations.append({"title": ch.web.title, "uri": ch.web.uri})

                return {
                    "status": "success",
                    "text": response.text,
                    "citations": citations
                }
            except Exception as e:
                logger.error(f"[Gemma Search Grounding] Error: {e}")
                return {"status": "error", "error": str(e)}

        return {"status": "error", "error": "SDK required for Search grounding"}

    # ---------------------------------------------------------------------
    # REST API Fallback
    # ---------------------------------------------------------------------
    def _generate_rest(
        self,
        prompt: str,
        model: str,
        thinking_level: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Direct REST fallback to Generative Language API."""
        import requests

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        if thinking_level:
            payload["generationConfig"] = {
                "thinkingConfig": {
                    "thinkingLevel": thinking_level
                }
            }

        try:
            r = requests.post(url, json=payload, timeout=15)
            data = r.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return {"status": "success", "model": model, "text": text}
            else:
                return {"status": "error", "error": data.get("error", "No candidate returned")}
        except Exception as e:
            logger.error(f"[Gemma REST] Exception: {e}")
            return {"status": "error", "error": str(e)}


# Global Singleton Client
gemma_client = GemmaIntelligenceClient()
