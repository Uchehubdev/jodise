import requests
import stripe
from django.conf import settings
from decimal import Decimal
from store.models import PaymentTransaction, MarketplaceSetting
import logging

logger = logging.getLogger(__name__)

class PaymentService:
    """
    Handles interactions with Payment Gateways (Dynamic: Paystack, Stripe).
    """

    @staticmethod
    def get_config():
        return MarketplaceSetting.objects.first()

    @staticmethod
    def _get_paystack_key():
        config = PaymentService.get_config()
        if config and config.paystack_secret_key:
            return config.paystack_secret_key
        return getattr(settings, "PAYSTACK_SECRET_KEY", "")

    @staticmethod
    def _get_stripe_key():
        config = PaymentService.get_config()
        if config and config.stripe_secret_key:
            return config.stripe_secret_key
        return getattr(settings, "STRIPE_SECRET_KEY", "")

    @classmethod
    def create_stripe_session(cls, order, success_url, cancel_url):
        """
        Creates a Stripe Checkout Session for the order.
        """
        stripe.api_key = cls._get_stripe_key()
        if not stripe.api_key:
            return None

        try:
            # Build line items
            line_items = []
            for item in order.items.all():
                line_items.append({
                    'price_data': {
                        'currency': 'ngn', # Or dynamic based on user/store
                        'product_data': {
                            'name': item.product.name,
                        },
                        'unit_amount': int(item.unit_price * 100),
                    },
                    'quantity': item.quantity,
                })

            # Add Delivery Fee if any
            if order.delivery_fee > 0:
                line_items.append({
                    'price_data': {
                        'currency': 'ngn',
                        'product_data': {'name': 'Delivery Fee'},
                        'unit_amount': int(order.delivery_fee * 100),
                    },
                    'quantity': 1,
                })

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}", 
                cancel_url=cancel_url,
                client_reference_id=order.reference,
                metadata={'order_ref': order.reference}
            )
            return session.url
        except Exception as e:
            logger.error(f"Stripe session creation failed: {e}")
            return None

    @classmethod
    def verify_payment(cls, reference, gateway=None):
        """
        Verifies a payment based on the active gateway or specified one.
        reference: Can be Paystack Reference OR Stripe Session ID
        """
        config = cls.get_config()
        active_gateway = gateway or (config.active_gateway if config else 'paystack')

        if active_gateway == 'paystack':
            return cls.verify_paystack(reference)
        elif active_gateway == 'stripe':
            return cls.verify_stripe(reference)
        
        return False, 0, {}

    @classmethod
    def verify_paystack(cls, reference):
        secret_key = cls._get_paystack_key()
        verify_url = "https://api.paystack.co/transaction/verify/"
        
        if not secret_key: 
            return False, 0, {}

        headers = {"Authorization": f"Bearer {secret_key}"}
        try:
            resp = requests.get(f"{verify_url}{reference}", headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("status") and data["data"]["status"] == "success":
                amount = Decimal(data["data"]["amount"]) / 100
                return True, amount, data["data"]
        except Exception as e:
            logger.error(f"Paystack Verify Error: {e}")
        
        return False, 0, {}

    @classmethod
    def verify_stripe(cls, session_id):
        stripe.api_key = cls._get_stripe_key()
        if not stripe.api_key:
            return False, 0, {}

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid':
                amount = Decimal(session.amount_total) / 100
                return True, amount, session
        except Exception as e:
            logger.error(f"Stripe Verify Error: {e}")
        
        return False, 0, {}

    @classmethod
    def record_transaction(cls, order, reference, amount, provider):
        transaction, created = PaymentTransaction.objects.get_or_create(
            ref=reference,
            defaults={
                'order': order,
                'amount': amount,
                'status': 'success',
                'provider': provider
            }
        )
        if not created and transaction.status != 'success':
            transaction.status = 'success'
            transaction.amount = amount
            transaction.save()
        return transaction
