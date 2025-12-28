# accounts/utils/paystack.py
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify/"


def _get_secret_key() -> str:
    key = (getattr(settings, "PAYSTACK_SECRET_KEY", "") or "").strip()
    if not key:
        raise ValueError("PAYSTACK_SECRET_KEY is missing in settings.")
    return key


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_secret_key()}",
        "Content-Type": "application/json",
    }


def _to_smallest_unit(amount: Any, decimals: int = 2) -> int:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid amount: {amount}")

    if value <= 0:
        raise ValueError("Amount must be greater than 0.")

    multiplier = Decimal(10) ** int(decimals)
    # quantize to whole number, then int
    return int((value * multiplier).quantize(Decimal("1")))


def initialize_payment(
    email: str,
    amount: Any,
    metadata: Optional[Dict[str, Any]] = None,
    callback_url: Optional[str] = None,
    currency: str = "NGN",
    decimals: int = 2,
    reference: Optional[str] = None,
    timeout: int = 25,
) -> Tuple[Optional[str], Optional[str], Optional[str], Dict[str, Any]]:
    """
    Returns:
      (authorization_url, reference, access_code, raw_response_json)

    IMPORTANT:
    - If your Paystack account is NGN-only, you can omit currency completely.
    """
    if not email:
        raise ValueError("Email is required.")

    payload: Dict[str, Any] = {
        "email": email,
        "amount": _to_smallest_unit(amount, decimals=decimals),
        "metadata": metadata or {},
    }

    # ✅ Only send currency if you truly need it (to avoid 400 on some setups)
    if currency:
        payload["currency"] = (currency or "NGN").upper()

    # ✅ callback_url can cause 400 if malformed; only send if it’s a clean absolute URL
    if callback_url:
        payload["callback_url"] = callback_url

    if reference:
        payload["reference"] = reference

    try:
        resp = requests.post(
            PAYSTACK_INITIALIZE_URL,
            headers=_headers(),
            json=payload,
            timeout=timeout,
        )

        # ✅ Always try to parse Paystack message (even when status != 200)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": (resp.text or "").strip()}

        if not resp.ok:
            # This is what you NEED to see to fix 400
            logger.error(
                "Paystack init rejected (%s). payload=%s response=%s",
                resp.status_code, payload, data
            )
            return None, None, None, data

        if data.get("status") is True:
            d = data.get("data") or {}
            return d.get("authorization_url"), d.get("reference"), d.get("access_code"), data

        logger.warning("Paystack init failed: %s | %s", data.get("message"), data)
        return None, None, None, data

    except requests.RequestException as e:
        logger.exception("Paystack initialization error: %s", str(e))
        return None, None, None, {"error": str(e)}


def verify_payment(reference: str, timeout: int = 25) -> Tuple[bool, Dict[str, Any]]:
    if not reference:
        return False, {"error": "Missing reference"}

    try:
        resp = requests.get(
            f"{PAYSTACK_VERIFY_URL}{reference}",
            headers=_headers(),
            timeout=timeout,
        )

        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": (resp.text or "").strip()}

        if not resp.ok:
            logger.error("Paystack verify rejected (%s): %s", resp.status_code, data)
            return False, data

        status = data.get("data", {}).get("status")
        return status == "success", data

    except requests.RequestException as e:
        logger.exception("Paystack verification error: %s", str(e))
        return False, {"error": str(e)}
