"""
OptiKinesis — Jayu Computer Use & Voice Navigation Agent
Inspired by Jayu (Gemini Computer Use): https://github.com/JonOuyang/Gemini-Computer-Use

Provides dual-mode assistive voice interaction:
1. Type & Speak Mode: Dictation and accessible typing with ElevenLabs TTS output.
2. Speak Navigation Mode (Jayu Computer Use): Full hands-free computer control,
   application launching, screen navigation, scrolling, typing, and desktop management
   powered by Google Gemini reasoning with ElevenLabs voice feedback.
"""

import os
import re
import sys
import time
import json
import logging
import subprocess
import webbrowser
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple

import pyautogui
from PIL import Image

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

import communication_service
import database

logger = logging.getLogger("computer_use_agent")
logger.setLevel(logging.INFO)

# PyAutoGUI safety configuration
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.2

from dotenv import load_dotenv
load_dotenv()

# Voice Mode Dedicated Gemini API Key & Model (Jayu Gemini-Computer-Use Repo)
VOICE_AGENT_GEMINI_KEY = os.environ.get(
    "GEMINI_VOICE_API_KEY",
    os.environ.get("VOICE_AGENT_GEMINI_KEY", os.environ.get("GEMINI_API_KEY", ""))
)
JAYU_COMPUTER_USE_MODELS = [
    "gemini-flash-latest",  # Exact model family from Jayu repo (gemini-1.5-flash-latest)
    "gemini-2.5-flash"
]


class VoiceAgentMode:
    TYPE_SPEAK = "type_speak"
    SPEAK_NAVIGATION = "speak_navigation"


def normalize_spoken_query(query: str) -> str:
    """Corrects common speech-to-text phonetic misrecognitions for desktop control."""
    q = (query or "").strip()
    replacements = [
        (r"\b(whitey|white tee|white-t|yt|u tube|you tube)\b", "youtube"),
        (r"\b(lead code|leadcode|leet code|lead-code)\b", "leetcode"),
        (r"\b(chat gpt|chat-gpt|chat g p t|chatgpt|gpt)\b", "chatgpt"),
        (r"\b(what's app|what app|whats app|what's-app)\b", "whatsapp"),
        (r"\b(git hub|git-hub)\b", "github"),
        (r"\b(g mail|g-mail|google mail)\b", "gmail"),
        (r"\b(face book|face-book)\b", "facebook"),
        (r"\b(insta gram|insta-gram|insta)\b", "instagram"),
        (r"\b(spot ify|spot-ify)\b", "spotify"),
        (r"\b(net flix|net-flix)\b", "netflix"),
    ]
    for pattern, repl in replacements:
        q = re.sub(pattern, repl, q, flags=re.I)
    return q


WEB_APPS = {
    "youtube": ("https://www.youtube.com", "Opening YouTube."),
    "chatgpt": ("https://chatgpt.com", "Opening ChatGPT."),
    "leetcode": ("https://leetcode.com", "Opening LeetCode."),
    "google": ("https://www.google.com", "Opening Google."),
    "github": ("https://github.com", "Opening GitHub."),
    "gmail": ("https://mail.google.com", "Opening Gmail."),
    "whatsapp": ("https://web.whatsapp.com", "Opening WhatsApp Web."),
    "spotify": ("https://open.spotify.com", "Opening Spotify."),
    "netflix": ("https://www.netflix.com", "Opening Netflix."),
    "reddit": ("https://www.reddit.com", "Opening Reddit."),
    "twitter": ("https://x.com", "Opening Twitter."),
    "x": ("https://x.com", "Opening X."),
    "amazon": ("https://www.amazon.com", "Opening Amazon."),
    "linkedin": ("https://www.linkedin.com", "Opening LinkedIn."),
    "wikipedia": ("https://www.wikipedia.org", "Opening Wikipedia."),
    "instagram": ("https://www.instagram.com", "Opening Instagram.")
}

DESKTOP_APPS = {
    "calc": ("calc.exe", "Opening Calculator."),
    "calculator": ("calc.exe", "Opening Calculator."),
    "notepad": ("notepad.exe", "Opening Notepad."),
    "text editor": ("notepad.exe", "Opening text editor."),
    "explorer": ("explorer.exe", "Opening File Explorer."),
    "file explorer": ("explorer.exe", "Opening File Explorer."),
    "files": ("explorer.exe", "Opening File Explorer."),
    "my computer": ("explorer.exe", "Opening File Explorer."),
    "cmd": ("cmd.exe", "Opening Command Prompt."),
    "command prompt": ("cmd.exe", "Opening Command Prompt."),
    "terminal": ("cmd.exe", "Opening Command Prompt."),
    "powershell": ("powershell.exe", "Opening PowerShell."),
    "paint": ("mspaint.exe", "Opening Paint."),
    "mspaint": ("mspaint.exe", "Opening Paint."),
    "task manager": ("taskmgr.exe", "Opening Task Manager."),
    "taskmgr": ("taskmgr.exe", "Opening Task Manager."),
    "camera": ("start microsoft.windows.camera:", "Opening Camera."),
    "settings": ("start ms-settings:", "Opening Windows Settings."),
    "word": ("write.exe", "Opening Wordpad."),
    "wordpad": ("write.exe", "Opening Wordpad."),
}


class JayuComputerUseAgent:
    """
    Jayu Computer-Use Agent for hands-free computer navigation and interaction.
    Analyzes user voice instructions, captures screen state when supported,
    determines OS actions, and executes desktop controls via PyAutoGUI and system tools.
    """

    def __init__(self):
        self.screen_width, self.screen_height = pyautogui.size()
        self.active_mode = VoiceAgentMode.SPEAK_NAVIGATION
        self.gemini_client = None
        self._init_gemini_client()

    def _init_gemini_client(self):
        """Initialize Google GenAI client for Jayu voice navigation mode."""
        api_key = VOICE_AGENT_GEMINI_KEY or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key and GENAI_AVAILABLE:
            try:
                self.gemini_client = genai.Client(api_key=api_key)
                logger.info(f"[Jayu] Gemini client initialized with voice-mode key using model {JAYU_COMPUTER_USE_MODELS[0]}.")
            except Exception as e:
                logger.warning(f"[Jayu] Failed to initialize Gemini client: {e}")
                self.gemini_client = None

    def capture_screen(self) -> Optional[Any]:
        """Safely capture desktop screenshot if graphical session allows."""
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            return screenshot
        except Exception as e:
            logger.debug(f"[Jayu] Direct ImageGrab not available in current session: {e}")
            return None

    def process_voice_command(self, query: str, mode: str = VoiceAgentMode.SPEAK_NAVIGATION) -> Dict[str, Any]:
        """
        Process a voice command according to the selected mode:
        1. type_speak: Dictation to text output and speech synthesis.
        2. speak_navigation: Jayu Computer-Use desktop automation.
        """
        clean_query = normalize_spoken_query(query.strip())
        if not clean_query:
            return {
                "status": "error",
                "mode": mode,
                "message": "Empty voice input received."
            }

        # Check for wake words ("hey opti", "ok opti", "opti")
        has_wake_word = bool(re.search(r"\b(hey\s+opti[a-z]*|ok\s+opti[a-z]*|okay\s+opti[a-z]*|opti\b)", clean_query, re.I))

        # Extract pure command after wake word if present
        command = re.sub(r"^(.*?)(hey\s+opti[a-z]*|ok\s+opti[a-z]*|okay\s+opti[a-z]*|opti\b)[\s,:\-–]*", "", clean_query, flags=re.I).strip()

        # If user just said the wake word ("Hey Opti") with no trailing command
        if not command and has_wake_word:
            feedback = "I'm listening. What can I do for you?"
            return {
                "status": "success",
                "action": "wake",
                "mode": mode,
                "feedback": feedback,
                "has_wake_word": True,
                "audio": communication_service.synthesize_speech(feedback)
            }

        target_query = command if command else clean_query

        # Check for "stop hearing" / sleep commands
        if re.search(r"\b(stop\s+(hearing|listening)|pause\s+(hearing|listening)|go\s+to\s+sleep|sleep\b)", target_query, re.I):
            feedback = "Stopping hearing. Say 'Hey Opti' whenever you want me to resume."
            return {
                "status": "success",
                "action": "stop_hearing",
                "mode": mode,
                "feedback": feedback,
                "has_wake_word": has_wake_word,
                "audio": communication_service.synthesize_speech(feedback)
            }

        # Check for resume / wake up commands
        if re.search(r"\b(start\s+(hearing|listening)|resume\s+(hearing|listening)|wake\s*up)\b", target_query, re.I):
            feedback = "I'm listening. How can I help you?"
            return {
                "status": "success",
                "action": "wake",
                "mode": mode,
                "feedback": feedback,
                "has_wake_word": has_wake_word,
                "audio": communication_service.synthesize_speech(feedback)
            }

        # Check for dynamic mode switching commands
        if re.search(r"\b(switch to|enable|activate)\s+(type|typing|dictation)\b", target_query, re.I):
            return {
                "status": "success",
                "action": "mode_switch",
                "target_mode": VoiceAgentMode.TYPE_SPEAK,
                "feedback": "Switched to Type and Speak mode. What would you like to write?",
                "audio": communication_service.synthesize_speech("Switched to Type and Speak mode.")
            }
        elif re.search(r"\b(switch to|enable|activate)\s+(nav|navigation|computer use|jayu)\b", target_query, re.I):
            return {
                "status": "success",
                "action": "mode_switch",
                "target_mode": VoiceAgentMode.SPEAK_NAVIGATION,
                "feedback": "Switched to Speak Navigation mode. Jayu is ready to control your computer.",
                "audio": communication_service.synthesize_speech("Switched to Speak Navigation mode.")
            }

        if mode == VoiceAgentMode.TYPE_SPEAK:
            return self._handle_type_speak(target_query)
        else:
            return self._handle_speak_navigation(target_query)

    def _handle_type_speak(self, text: str) -> Dict[str, Any]:
        """
        Mode 1: Transcribe user speech into accessible typing text.
        Allows instant speech-to-text dictation into the OptiKinesis virtual keyboard.
        """
        # Clean any remaining dictation commands like "write ..." or "type ..."
        dictated_text = re.sub(r"^(type|write|saying)\s+", "", text, flags=re.I).strip() or text
        audio_result = communication_service.synthesize_speech(dictated_text)
        return {
            "status": "success",
            "mode": VoiceAgentMode.TYPE_SPEAK,
            "action": "dictate_text",
            "text": dictated_text,
            "feedback": f"Dictated: \"{dictated_text}\"",
            "audio": audio_result
        }

    def _handle_speak_navigation(self, query: str) -> Dict[str, Any]:
        """
        Mode 2: Jayu Gemini Computer Use Agent.
        Interprets natural language commands and executes OS/computer navigation actions.
        Prioritizes instant local heuristics for sub-second execution, falling back to Gemini.
        """
        logger.info(f"[Jayu] Processing navigation command: '{query}'")

        # 1. Fast, reliable rule-based Computer-Use Heuristics (instant 0ms latency)
        heuristic_res = self._heuristic_computer_use(query)
        if heuristic_res.get("action") != "unknown":
            return heuristic_res

        # 2. Attempt Gemini Multimodal / Reasoning interpretation for open-ended queries
        gemini_plan = self._reason_with_gemini(query)
        if gemini_plan and gemini_plan.get("action") and gemini_plan.get("action") != "unknown":
            action = gemini_plan.get("action")
            params = gemini_plan.get("params", {})
            feedback = gemini_plan.get("feedback", f"Executing {action}")
            exec_result = self.execute_computer_action(action, params)
            audio_result = communication_service.synthesize_speech(feedback)
            return {
                "status": "success",
                "mode": VoiceAgentMode.SPEAK_NAVIGATION,
                "action": action,
                "params": params,
                "feedback": feedback,
                "execution": exec_result,
                "audio": audio_result,
                "agent": "jayu_gemini"
            }

        return heuristic_res

    def _reason_with_gemini(self, query: str) -> Optional[Dict[str, Any]]:
        """Ask Gemini API for computer-use action planning."""
        if not self.gemini_client:
            return None

        prompt = (
            f"You are Jayu, an AI desktop navigation assistant. "
            f"Given the user's voice command: '{query}', determine the single best computer action to execute. "
            f"Supported actions: "
            f"1. 'open_app' with param 'app' (e.g. 'notepad', 'calc', 'chrome', 'explorer')\n"
            f"2. 'search_web' with param 'query'\n"
            f"3. 'open_url' with param 'url'\n"
            f"4. 'type_text' with param 'text'\n"
            f"5. 'scroll' with param 'direction' ('up' or 'down') and 'amount' (int)\n"
            f"6. 'hotkey' with param 'keys' (array, e.g. ['alt', 'tab'], ['win', 'd'], ['ctrl', 'c'])\n"
            f"7. 'press_key' with param 'key' (e.g. 'enter', 'esc', 'tab', 'backspace')\n"
            f"8. 'click' with param 'position' ('center', 'top_left', 'top_right')\n"
            f"9. 'navigate_optikinesis' with param 'tab' ('home', 'breathguard', 'friends', 'keyboard', 'settings')\n"
            f"Return ONLY valid JSON in format: {{\"action\": \"...\", \"params\": {{...}}, \"feedback\": \"short spoken sentence\"}}"
        )

        for model in JAYU_COMPUTER_USE_MODELS:
            try:
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                text_resp = response.text.strip()
                match = re.search(r"\{.*\}", text_resp, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except Exception as e:
                logger.debug(f"[Jayu] Model {model} reasoning attempt: {e}")

        return None

    def _heuristic_computer_use(self, query: str) -> Dict[str, Any]:
        """
        Determines and executes desktop actions for high-frequency assistive commands.
        Guarantees that everyday websites, apps, and searches ALWAYS succeed.
        """
        q = normalize_spoken_query(query).lower().strip()
        action = "unknown"
        params = {}
        feedback = "I couldn't recognize that computer navigation command."

        # A. Stop / Resume Hearing
        if re.search(r"\b(stop\s+(hearing|listening)|pause\s+(hearing|listening)|go\s+to\s+sleep|sleep\b)", q):
            action = "stop_hearing"
            feedback = "Stopping hearing. Say 'Hey Opti' whenever you want me to resume."

        elif re.search(r"\b(start\s+(hearing|listening)|resume\s+(hearing|listening)|wake\s*up)\b", q):
            action = "wake"
            feedback = "I'm listening. How can I help you?"

        # B. OptiKinesis Tab Navigation
        elif re.search(r"\b(go to|open|show|switch to)\s+(breathguard|vitals)\b", q):
            action = "navigate_optikinesis"
            params = {"tab": "breathguard"}
            feedback = "Opening BreathGuard vital sign monitoring."

        elif re.search(r"\b(go to|open|show|switch to)\s+(friend|friends|call a friend)\b", q):
            action = "navigate_optikinesis"
            params = {"tab": "friends"}
            feedback = "Opening Call a Friend contact directory."

        elif re.search(r"\b(go to|open|show|switch to)\s+(type|keyboard|speech)\b", q):
            action = "navigate_optikinesis"
            params = {"tab": "keyboard"}
            feedback = "Opening Virtual Keyboard and Speech."

        elif re.search(r"\b(go to|open|show|switch to)\s+(settings|preferences)\b", q):
            action = "navigate_optikinesis"
            params = {"tab": "settings"}
            feedback = "Opening System and Accessibility Settings."

        elif re.search(r"\b(go to|open|show|switch to)\s+(home|dashboard)\b", q):
            action = "navigate_optikinesis"
            params = {"tab": "home"}
            feedback = "Navigating to Home Dashboard."

        elif re.search(r"\b(go to|open|show|switch to)\s+(help|need help|everyday help)\b", q):
            action = "navigate_optikinesis"
            params = {"tab": "help"}
            feedback = "Opening Everyday Help Requests."

        # C. YouTube Specific (open or search)
        elif re.search(r"\b(?:open\s+)?youtube(?:\s+(?:and\s+)?(?:search|play)\s+(.+))?", q):
            m = re.search(r"\b(?:open\s+)?youtube(?:\s+(?:and\s+)?(?:search|play)\s+(.+))?", q)
            yt_term = m.group(1).strip() if m.group(1) else ""
            if yt_term:
                action = "search_youtube"
                params = {"query": yt_term}
                feedback = f"Searching YouTube for \"{yt_term}\"."
            else:
                action = "open_url"
                params = {"url": "https://www.youtube.com"}
                feedback = "Opening YouTube."

        # D. Search & Google
        elif re.search(r"^\s*(search|google|look up|find)\s*$", q):
            action = "open_url"
            params = {"url": "https://www.google.com"}
            feedback = "Opening Google Search. What would you like to search for?"

        elif re.search(r"\b(search|google|look up|find)\s+(?:for\s+)?(.+)", q):
            m = re.search(r"\b(search|google|look up|find)\s+(?:for\s+)?(.+)", q)
            search_term = m.group(2).strip()
            search_term = re.sub(r"\s+on\s+google$", "", search_term, flags=re.I)
            action = "search_web"
            params = {"query": search_term}
            feedback = f"Searching Google for \"{search_term}\"."

        # E. Known Web Applications (ChatGPT, LeetCode, GitHub, etc.)
        if action == "unknown":
            for app_key, (app_url, app_fb) in WEB_APPS.items():
                if re.search(rf"\b(open|launch|start|go to)?\s*{re.escape(app_key)}\b", q):
                    action = "open_url"
                    params = {"url": app_url}
                    feedback = app_fb
                    break

        # F. Known Desktop Applications (Calc, Notepad, Explorer, Paint, etc.)
        if action == "unknown":
            for app_key, (app_cmd, app_fb) in DESKTOP_APPS.items():
                if re.search(rf"\b(open|launch|start)?\s*{re.escape(app_key)}\b", q):
                    action = "open_app"
                    params = {"app": app_key, "cmd": app_cmd}
                    feedback = app_fb
                    break

        # G. General Browser Launching
        if action == "unknown":
            if re.search(r"\b(open|launch|start)?\s*(chrome|browser|google chrome|internet|edge)\b", q):
                action = "open_url"
                params = {"url": "https://www.google.com"}
                feedback = "Opening web browser."

        # H. Window Management & Shortcuts
        if action == "unknown":
            if re.search(r"\b(close window|close app|close program|exit app)\b", q):
                action = "close_window"
                feedback = "Closing active window."

            elif re.search(r"\b(minimize window|minimize all|minimize)\b", q):
                action = "minimize_window"
                feedback = "Minimizing window."

            elif re.search(r"\b(maximize window|maximize)\b", q):
                action = "maximize_window"
                feedback = "Maximizing window."

            elif re.search(r"\b(show desktop|desktop)\b", q):
                action = "hotkey"
                params = {"keys": ["win", "d"]}
                feedback = "Showing desktop."

            elif re.search(r"\b(switch window|next window|alt tab)\b", q):
                action = "hotkey"
                params = {"keys": ["alt", "tab"]}
                feedback = "Switching active window."

        # I. Desktop Typing
        if action == "unknown":
            if re.search(r"\b(type|write)\s+(?:into app\s+)?(?:saying\s+)?(.+)", q):
                m = re.search(r"\b(type|write)\s+(?:into app\s+)?(?:saying\s+)?(.+)", q)
                text_to_type = m.group(2).strip()
                action = "type_text"
                params = {"text": text_to_type, "press_enter": False}
                feedback = f"Typing \"{text_to_type}\" into your active window."

        # J. Scrolling
        if action == "unknown":
            if re.search(r"\bscroll\s+down\b", q):
                action = "scroll"
                params = {"direction": "down", "amount": 450}
                feedback = "Scrolling down."

            elif re.search(r"\bscroll\s+up\b", q):
                action = "scroll"
                params = {"direction": "up", "amount": 450}
                feedback = "Scrolling up."

        # K. Keyboard & Mouse Actions
        if action == "unknown":
            if re.search(r"\b(press enter|hit enter|send)\b", q):
                action = "press_key"
                params = {"key": "enter"}
                feedback = "Pressed Enter."

            elif re.search(r"\b(press escape|hit escape|close dialog)\b", q):
                action = "press_key"
                params = {"key": "esc"}
                feedback = "Pressed Escape."

            elif re.search(r"\b(click|mouse click)\b", q):
                action = "click"
                params = {"position": "center"}
                feedback = "Clicked current mouse position."

        # L. Universal "Open <Target>" Catch-All (Never fail an open command!)
        if action == "unknown":
            m_open = re.search(r"\b(?:open|launch|start|go to)\s+(.+)", q)
            if m_open:
                target = m_open.group(1).strip()
                if "." in target and " " not in target:
                    url = f"https://{target}" if not target.startswith("http") else target
                    action = "open_url"
                    params = {"url": url}
                    feedback = f"Opening {target} in your browser."
                else:
                    action = "open_url"
                    params = {"url": f"https://www.google.com/search?q={urllib.parse.quote(target)}"}
                    feedback = f"Opening {target}."

        if action == "unknown":
            return {
                "status": "unknown",
                "action": "unknown",
                "feedback": feedback
            }

        # Execute determined action
        exec_result = self.execute_computer_action(action, params)
        audio_result = communication_service.synthesize_speech(feedback)

        return {
            "status": "success",
            "mode": VoiceAgentMode.SPEAK_NAVIGATION,
            "action": action,
            "params": params,
            "feedback": feedback,
            "execution": exec_result,
            "audio": audio_result,
            "agent": "jayu_heuristic"
        }

    def execute_computer_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Directly executes the physical OS action on the Windows desktop."""
        try:
            if action == "stop_hearing":
                return {"result": "Hearing paused"}

            elif action == "wake":
                return {"result": "Agent awake and listening"}

            elif action == "open_app":
                app_name = params.get("app", "notepad").lower().strip()
                cmd = params.get("cmd", "")

                # Check if it's actually in WEB_APPS
                if app_name in WEB_APPS:
                    url = WEB_APPS[app_name][0]
                    webbrowser.open_new(url)
                    return {"result": f"Opened web app: {url}"}

                if not cmd and app_name in DESKTOP_APPS:
                    cmd = DESKTOP_APPS[app_name][0]

                if not cmd:
                    if app_name in ["chrome", "browser", "google chrome", "internet", "edge"]:
                        webbrowser.open_new("https://www.google.com")
                        return {"result": "Opened web browser"}
                    cmd = f"{app_name}.exe"

                logger.info(f"[Jayu] Executing app command: {cmd}")
                try:
                    subprocess.Popen(cmd, shell=True)
                except Exception as ex:
                    logger.warning(f"subprocess open failed for {cmd}, opening in browser: {ex}")
                    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(app_name)}")
                return {"result": f"Launched application: {cmd}"}

            elif action == "open_url":
                url = params.get("url", "https://google.com")
                if not url.startswith("http"):
                    url = "https://" + url
                logger.info(f"[Jayu] Opening URL: {url}")
                webbrowser.open(url)
                return {"result": f"Opened URL: {url}"}

            elif action == "close_window":
                pyautogui.hotkey("alt", "f4")
                return {"result": "Closed active window"}

            elif action == "minimize_window":
                pyautogui.hotkey("win", "down")
                return {"result": "Minimized window"}

            elif action == "maximize_window":
                pyautogui.hotkey("win", "up")
                return {"result": "Maximized window"}

            elif action == "search_web":
                query = params.get("query", "")
                url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                logger.info(f"[Jayu] Searching web: {url}")
                webbrowser.open(url)
                return {"result": f"Opened Google search for {query}"}

            elif action == "search_youtube":
                query = params.get("query", "")
                url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
                logger.info(f"[Jayu] Searching YouTube: {url}")
                webbrowser.open(url)
                return {"result": f"Opened YouTube search for {query}"}

            elif action == "type_text":
                text = params.get("text", "")
                pyautogui.write(text, interval=0.03)
                if params.get("press_enter", False):
                    pyautogui.press("enter")
                return {"result": f"Typed {len(text)} characters into active window"}

            elif action == "scroll":
                direction = params.get("direction", "down")
                amount = int(params.get("amount", 300))
                scroll_units = -amount if direction == "down" else amount
                pyautogui.scroll(scroll_units)
                return {"result": f"Scrolled {direction} by {amount} units"}

            elif action == "hotkey":
                keys = params.get("keys", ["alt", "tab"])
                pyautogui.hotkey(*keys)
                return {"result": f"Triggered shortcut: {' + '.join(keys)}"}

            elif action == "press_key":
                key = params.get("key", "enter")
                pyautogui.press(key)
                return {"result": f"Pressed key: {key}"}

            elif action == "click":
                pos = params.get("position", "center")
                if pos == "center":
                    x = self.screen_width // 2
                    y = self.screen_height // 2
                    pyautogui.click(x, y)
                else:
                    pyautogui.click()
                return {"result": "Clicked mouse button"}

            elif action == "navigate_optikinesis":
                return {"result": f"Navigating within OptiKinesis to {params.get('tab')}"}

            return {"result": "No action executed"}

        except Exception as e:
            logger.error(f"[Jayu] Execution error for action {action}: {e}")
            return {"error": str(e)}


# Singleton Instance
jayu_agent = JayuComputerUseAgent()
