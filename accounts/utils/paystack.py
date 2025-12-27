import requests
import logging
from django.conf import settings
from decimal import Decimal

# ============================================================
# 🔐 PAYSTACK CONFIG
# ============================================================
# ============================================================
# 🔐 PAYSTACK CONFIG
# ============================================================
def get_paystack_secret():
    from store.models import MarketplaceSetting
    config = MarketplaceSetting.objects.first()
    if config and config.paystack_secret_key:
        return config.paystack_secret_key
    return getattr(settings, "PAYSTACK_SECRET_KEY", None)

PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify/"
PAYSTACK_REFUND_URL = "https://api.paystack.co/refund"

logger = logging.getLogger(__name__)


# ============================================================
# 🧾 INITIALIZE PAYMENT
# ============================================================
def initialize_payment(email: str, amount: Decimal, metadata: dict, callback_url: str):
    """
    Initialize a Paystack transaction securely.
    Returns the redirect (authorization) URL if successful.
    """
    if not PAYSTACK_SECRET_KEY:
        raise ValueError("Paystack secret key is missing in settings.")

    if not email or not amount or amount <= 0:
        raise ValueError("Invalid payment initialization parameters.")

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": int(amount * 100),  # convert to kobo
        "metadata": metadata or {},
        "callback_url": callback_url,
    }

    try:
        response = requests.post(PAYSTACK_INITIALIZE_URL, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        if data.get("status") is True and data.get("data", {}).get("authorization_url"):
            return data["data"]["authorization_url"]
        logger.warning(f"Paystack init failed: {data.get('message')}")
        return None
    except requests.RequestException as e:
        logger.error(f"Paystack initialization error: {e}")
        return None


# ============================================================
# 🔍 VERIFY PAYMENT
# ============================================================
def verify_payment(reference: str):
    """
    Verifies a Paystack transaction by reference.
    Returns (True, response_data) if successful.
    """
    if not PAYSTACK_SECRET_KEY:
        raise ValueError("Paystack secret key is missing in settings.")

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(f"{PAYSTACK_VERIFY_URL}{reference}", headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        status = data.get("data", {}).get("status") == "success"
        return status, data
    except requests.RequestException as e:
        logger.error(f"Paystack verification error: {e}")
        return False, None


# ============================================================
# 💸 PROCESS REFUND
# ============================================================
def process_refund(transaction_reference: str, amount: Decimal):
    """
    Creates a refund for a given transaction reference.
    Returns True if the refund was successful.
    """
    if not PAYSTACK_SECRET_KEY:
        raise ValueError("Paystack secret key is missing in settings.")
    if not transaction_reference or amount <= 0:
        raise ValueError("Invalid refund parameters.")

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "transaction": transaction_reference,
        "amount": int(amount * 100),  # kobo
    }

    try:
        response = requests.post(PAYSTACK_REFUND_URL, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        if data.get("status") is True:
            logger.info(f"✅ Paystack refund success for {transaction_reference}")
            return True
        logger.warning(f"Refund failed: {data.get('message')}")
        return False
    except requests.RequestException as e:
        logger.error(f"Paystack refund error: {e}")
        return False


# ============================================================
# 🧠 SAFE WRAPPER (RESILIENT CALLS)
# ============================================================
class PaystackManager:
    """
    Centralized wrapper for safer Paystack operations.
    Use: PaystackManager().charge(...) or .refund(...)
    """

    def __init__(self, email=None):
        self.email = email

    def charge(self, amount, metadata, callback_url):
        """Initialize and return redirect URL."""
        try:
            return initialize_payment(self.email, amount, metadata, callback_url)
        except Exception as e:
            logger.error(f"Charge error: {e}")
            return None

    def confirm(self, reference):
        """Verify and return (status, response_json)."""
        try:
            return verify_payment(reference)
        except Exception as e:
            logger.error(f"Confirm error: {e}")
            return False, None

    def refund(self, reference, amount):
        """Process refund for successful transaction."""
        try:
            return process_refund(reference, amount)
        except Exception as e:
            logger.error(f"Refund error: {e}")
            return False
