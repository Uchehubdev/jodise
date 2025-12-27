import random
from django.core.cache import cache

def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp(phone):
    otp = generate_otp()
    cache.set(f"otp_{phone}", otp, timeout=300)  # 5 minutes
    print(f"[DEBUG] OTP sent to {phone}: {otp}")  # Replace with SMS logic
    return otp

def verify_otp_code(phone, entered_otp):
    cached_otp = cache.get(f"otp_{phone}")
    return cached_otp == entered_otp
