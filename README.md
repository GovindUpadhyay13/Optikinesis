# OptiKinesis 👁️🎙️

> **Enabling Movement. Empowering Lives.**  
> An advanced multimodal assistive ecosystem delivering hands-free desktop control, contactless vitals monitoring, and AI-powered care coordination through gaze tracking, voice automation, and intelligent reasoning.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0%2B-lightgrey.svg)](https://flask.palletsprojects.com/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-0.10.9-green.svg)](https://developers.google.com/mediapipe)
[![Gemini / Gemma](https://img.shields.io/badge/AI-Gemini%20%26%20Gemma%204-purple.svg)](https://ai.google.dev/)
[![ElevenLabs](https://img.shields.io/badge/Voice-ElevenLabs%20TTS-orange.svg)](https://elevenlabs.io/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📌 Overview

**OptiKinesis** is designed for individuals living with Amyotrophic Lateral Sclerosis (ALS), quadriplegia, cerebral palsy, and severe motor impairments. It unifies computer vision, edge AI, and desktop automation into an accessible, dignified communication and control hub.

Patients can control their entire PC using **eye gaze**, **natural voice commands**, or a **cohesive dual-mode**, while continuous contactless vitals monitoring guarantees caregiver peace of mind.

---

## 🖼️ Product Screenshots

The screenshot attachments referenced in this task are not available as local files in this repository workspace, so no image links are embedded yet (to avoid broken paths).  
When the files are available, place them in `docs/screenshots/` and reference them with concise captions for:

- Onboarding condition preferences, floating virtual keyboard, and trusted-contact setup
- Onboarding preferred name + primary control mode (Jayu, eye tracking/gaze, dual mode)
- Accessible virtual keyboard with eye/cursor interaction
- Dashboard with live eye-control camera preview and caregiver/help/type-and-speak/BreathGuard cards

Apply the same `docs/screenshots/` convention for the prior four screenshots as well if those files are provided.

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        OptiKinesis Web Client                          │
│  (Modern Glassmorphism UI • High-Contrast Light/Dark • Audio Feedback)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST / Server-Sent Events
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Flask Core Server (main.py)                     │
└─────┬──────────────┬──────────────┬──────────────┬──────────────┬──────┘
      │              │              │              │              │
      ▼              ▼              ▼              ▼              ▼
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│ MediaPipe │  │   Jayu    │  │BreathGuard│  │  Gemma 4  │  │ElevenLabs │
│ Eye/Gaze  │  │ Computer  │  │Contactless│  │ Reasoning │  │ & Twilio  │
│  Blinks   │  │ Use Agent │  │  Vitals   │  │   Agent   │  │ Outbound  │
└─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
      │              │              │              │              │
      ▼              ▼              ▼              ▼              ▼
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│  Desktop  │  │ PyAutoGUI │  │ Chest ROI │  │ Tool Call │  │ Voice AAC │
│ Navigation│  │ Automation│  │  Analysis │  │ Dispatch  │  │ & Alerts  │
└───────────┘  └───────────┘  └───────────┘  └───────────┘  └───────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ Local SQLite (WAL Mode) │
                       │ Profiles, Contacts, Logs│
                       └─────────────────────────┘
```

---

## 🖥️ Frontend Structure & Application Tabs

The web frontend is engineered with responsive, high-accessibility UI components featuring dwell-click indicators, large touch/gaze targets, and auditory confirmation:

| Tab / Section | Route / Trigger | Capabilities |
| :--- | :--- | :--- |
| **🚀 Onboarding Flow** | `#view-onboarding` | Welcomes first-time patients, sets profile credentials, performs interactive camera checks, and provides control mode selection (**Voice Only**, **Eye Only**, or **Dual Mode**). |
| **🏠 Home Dashboard** | `#view-home` | Real-time overview displaying primary caregiver status, live vitals summary, and 1-click / gaze access to essential services. |
| **🆘 Need Help** | `#view-help` | High-priority assistive requests (Water, Food, Position adjustment, Restroom, Medication). Immediately logs and dispatches alerts to caregivers. |
| **🫁 BreathGuard AI** | `#view-breathguard` | Contactless respiratory rate monitoring using facial and upper torso landmark motion tracking. Detects hypoventilation, hyperventilation, and tachypnea. |
| **📞 Call a Friend** | `#view-friends` | Accessible communication directory. Synthesizes voice calls and emergency messages via ElevenLabs neural TTS and Twilio voice channels. |
| **⌨️ Type & Speak** | `#view-keyboard` | Accessible virtual on-screen keyboard with dwell-time typing, voice dictation, phrase banks, and **Type External** to write into any desktop app. |
| **⚙️ Settings** | `#view-settings` | Caregiver directory management, eye-tracking sensitivity adjustment, blink threshold tuning, and system diagnostics. |
| **🚨 Emergency Rail** | Global Footer | Instant one-action emergency alert button accessible at all times across any view. |

---

## ⚙️ Backend Subsystems

- **`main.py`**: Central Flask orchestrator managing webcam frames, eye-blink detection, background threads, and REST endpoints.
- **`computer_use_agent.py`**: Jayu Computer-Use Agent. Translates natural voice commands (*"open chrome"*, *"open notepad"*, *"scroll down"*, *"stop hearing"*) into desktop actions via PyAutoGUI and Google Gemini.
- **`breathguard.py`**: Contactless respiratory vital sign estimation using MediaPipe landmarks and frequency domain signal processing.
- **`communication_service.py`**: Connects ElevenLabs multi-lingual speech synthesis and Twilio telephony for high-fidelity voice output and emergency calling.
- **`gemma_intelligence.py` & `agent_reasoning.py`**: Gemma 4 reasoning layer with Thinking configurations (`minimal`, `high`) and autonomous assistive function calling.
- **`database.py`**: Thread-safe SQLite database managing patient records, caregiver directories, friend contacts, vitals history, and audit logs.
- **`fatigue_monitor.py` & `eye_blink.py`**: PERCLOS (Percentage of Eye Closure) analysis for blink validation and cognitive fatigue prevention.

---

## 🔒 Security & Privacy (Zero Credential Exposure)

OptiKinesis enforces enterprise-grade privacy and zero hardcoded secret policies:
- **No API keys or sensitive credentials** are committed to version control.
- Configuration is loaded exclusively from a local `.env` file (see `.env.example`).
- Video frames and biometric gaze calculations are processed **100% locally on device**; raw webcam streams never leave the host machine.
- Automated tests verify secret isolation prior to execution.

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python**: 3.10 or higher
- **Webcam**: Standard 720p or 1080p camera
- **Microphone**: Any built-in or external mic
- **OS**: Windows 10/11, macOS, or Linux

### 2. Clone the Repository
```bash
git clone https://github.com/GovindUpadhyay13/Optikinesis.git
cd Optikinesis
```

### 3. Create a Virtual Environment & Install Dependencies
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the template and provide your API keys:
```bash
cp .env.example .env
```
Edit `.env` with your preferred credentials:
```env
# Gemini API Keys (Jayu Voice Computer Control & Gemma AI)
GEMINI_VOICE_API_KEY=your_gemini_api_key
GEMINI_API_KEY=your_gemini_api_key

# ElevenLabs Speech Synthesis
ELEVENLABS_API_KEY=your_elevenlabs_api_key

# Twilio Emergency Telephony (Optional)
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_PHONE=+1234567890

# Default Emergency Caregiver Contact
EMERGENCY_CONTACT=+1234567890
```

### 5. Launch the Application
```bash
python main.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5001
```

---

## 🎙️ Voice & Computer Control Commands

When Voice Mode is activated, OptiKinesis responds directly to intuitive spoken directives:

| Command | Action Performed |
| :--- | :--- |
| `"Open Chrome"` | Launches Google Chrome or brings it into focus. |
| `"Open Notepad"` | Launches Notepad editor. |
| `"Open Calculator"` | Launches system calculator. |
| `"Scroll Down"` / `"Scroll Up"` | Scrolls the active application window smoothly. |
| `"Close Window"` | Sends Alt+F4 to gracefully close the active window. |
| `"Stop Hearing"` / `"Mute"` | Suspends active command execution until woken. |
| `"Hey Opti"` / `"Resume Listening"` | Wakes the voice agent from suspended listening. |
| `"Switch to Type Mode"` | Toggles mode to Type & Speak text dictation. |
| `"Switch to Navigation Mode"` | Activates Jayu desktop navigation mode. |

---

## 🧪 Testing & Verification

Run the built-in test suites to verify subsystem readiness:
```bash
# Test Gemma 4 Intelligence & Function Calling
python test_gemma_intelligence.py

# Test ElevenLabs Text-to-Speech Synthesis
python test_elevenlabs.py

# Test Voice Mode & Wake-Word Execution
python test_jayu_modes.py
```

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
