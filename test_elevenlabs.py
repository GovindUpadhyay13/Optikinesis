import sys
import communication_service

def test_elevenlabs_synthesis():
    print("Testing ElevenLabs text-to-speech synthesis...")
    test_phrase = "OptiKinesis speech output test using ElevenLabs voice synthesis."
    result = communication_service.synthesize_speech(test_phrase)
    
    print("ElevenLabs API result:")
    print(f"Status: {result.get('status')}")
    print(f"Source: {result.get('source')}")
    print(f"Voice ID: {result.get('voice_id')}")
    print(f"Model ID: {result.get('model_id')}")
    print(f"Byte length: {result.get('byte_length')}")
    
    if result.get("status") == "success" and result.get("audio_base64"):
        print(" SUCCESS: Audio successfully synthesized and base64 encoded!")
        return 0
    else:
        print(f" FAILED: {result.get('error')}")
        return 1

if __name__ == "__main__":
    sys.exit(test_elevenlabs_synthesis())
