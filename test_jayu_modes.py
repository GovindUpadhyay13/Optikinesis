import json
import urllib.request
import time
import sys

BASE_URL = "http://127.0.0.1:5001"

def test_cmd(name, text, mode="speak_navigation"):
    print(f"\n--- Testing: {name} | Text: \"{text}\" ---")
    req = urllib.request.Request(
        f"{BASE_URL}/api/agent/voice",
        data=json.dumps({"text": text, "mode": mode}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print("Status:", data.get("status"))
            print("Action:", data.get("action"))
            print("Feedback:", data.get("feedback"))
            if "audio" in data and data["audio"]:
                print("ElevenLabs Audio Generated:", bool(data["audio"].get("audio_base64")))
            return data
    except Exception as e:
        print("ERROR:", e)
        return None

if __name__ == "__main__":
    print("Verifying Alexa-Style Wake Word ('Hey Opti') & 'Stop Hearing' Engine...")

    # 1. Hey Opti alone (Wake up)
    r1 = test_cmd("Wake Word Alone", "Hey Opti")
    assert r1 and r1.get("action") == "wake", f"Expected wake, got {r1}"

    # 2. Hey Opti with Open Notepad command
    r2 = test_cmd("Wake + Open Notepad", "Hey Opti open notepad")
    assert r2 and r2.get("action") == "open_app", f"Expected open_app, got {r2}"

    # 3. Hey Opti with Stop Hearing command
    r3 = test_cmd("Stop Hearing Command", "Hey Opti stop hearing")
    assert r3 and r3.get("action") == "stop_hearing", f"Expected stop_hearing, got {r3}"

    # 4. Resume Hearing / Wake Up
    r4 = test_cmd("Resume Hearing", "Hey Opti resume listening")
    assert r4 and r4.get("action") == "wake", f"Expected wake, got {r4}"

    # 5. Hey Opti with Scroll Down
    r5 = test_cmd("Scroll Down", "Hey Opti, scroll down")
    assert r5 and r5.get("action") == "scroll", f"Expected scroll, got {r5}"

    # 6. Hey Opti Close Window
    r6 = test_cmd("Close Window", "Hey Opti close window")
    assert r6 and r6.get("action") == "close_window", f"Expected close_window, got {r6}"

    # 7. Hey Opti Switch to Type Mode
    r7 = test_cmd("Switch to Type Mode", "Hey Opti switch to type mode")
    assert r7 and r7.get("action") == "mode_switch", f"Expected mode_switch, got {r7}"
    assert r7.get("target_mode") == "type_speak"

    # 8. Type & Speak Mode: Dictation with wake word stripped
    r8 = test_cmd("Type & Speak Dictation", "Hey Opti please turn on the light", mode="type_speak")
    assert r8 and r8.get("action") == "dictate_text", f"Expected dictate_text, got {r8}"
    assert "please turn on the light" in r8.get("text", "").lower(), f"Unexpected dictated text: {r8.get('text')}"

    print("\n[SUCCESS] ALL WAKE-WORD & VOICE COMMAND TESTS PASSED!")
