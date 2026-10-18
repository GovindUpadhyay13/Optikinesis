import os
from dotenv import load_dotenv
load_dotenv()

# Test WhatsApp automation using configured emergency contact from .env
if __name__ == "__main__":
    from main import auto_send_whatsapp
    phone = os.getenv("EMERGENCY_CONTACT", "+1234567890")
    print(f"Testing WhatsApp automation to target: {phone}")
    # auto_send_whatsapp(phone, "OptiKinesis System Test")