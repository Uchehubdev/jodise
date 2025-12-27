from django.core.mail import get_connection, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from decouple import config
import logging
from store.models import MarketplaceSetting

# Setup Logging
logger = logging.getLogger(__name__)

# Basic Try-Import for Twilio
try:
    from twilio.rest import Client
except ImportError:
    Client = None


class Notifier:
    """
    Centralized service for sending Emails and SMS.
    Uses Dynamic DB Configuration from MarketplaceSetting.
    """

    @staticmethod
    def _get_email_connection():
        """
        Returns a Django EmailBackend connection object based on DB settings.
        Falls back to settings.py values if DB is empty.
        """
        config = MarketplaceSetting.objects.first()
        if not config:
            return get_connection() # Use default settings.py

        # If DB config is incomplete, fallback to settings
        if not config.email_host_user:
             return get_connection()

        return get_connection(
            host=config.email_host or settings.EMAIL_HOST,
            port=config.email_port or settings.EMAIL_PORT,
            username=config.email_host_user,
            password=config.email_host_password,
            use_tls=config.email_use_tls
        )

    @staticmethod
    def _get_twilio_client():
        """
        Returns (client, from_number) tuple.
        """
        config = MarketplaceSetting.objects.first()
        
        # 1. DB Config
        if config and config.twilio_sid and config.twilio_auth_token:
            if Client:
                return Client(config.twilio_sid, config.twilio_auth_token), config.twilio_from_number
        
        # 2. Fallback to Env/Settings
        sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        number = getattr(settings, 'TWILIO_PHONE_NUMBER', None)
        
        if sid and token and Client:
            return Client(sid, token), number
            
        return None, None

    @classmethod
    def send_email(cls, subject, recipient_email, template_name, context):
        """Send HTML email with dynamic connection."""
        try:
            html_message = render_to_string(template_name, context)
            plain_message = strip_tags(html_message)
            from_email = settings.DEFAULT_FROM_EMAIL
            
            connection = cls._get_email_connection()

            msg = EmailMultiAlternatives(
                subject, plain_message, from_email, [recipient_email], connection=connection
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send()
            
            logger.info(f"📧 Email sent to {recipient_email}: {subject}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send email to {recipient_email}: {e}")
            return False

    @classmethod
    def send_sms(cls, phone_number, message_body):
        """Send SMS via Twilio (Dynamic)."""
        client, from_number = cls._get_twilio_client()
        
        if not client or not from_number:
            logger.warning("⚠️ SMS skipped: Twilio not configured in DB or Settings.")
            return False

        try:
            # Format phone number if needed
            phone = str(phone_number)
            if not phone.startswith('+'):
                phone = f"+234{phone.lstrip('0')}" if len(phone) < 14 else phone

            client.messages.create(
                body=message_body,
                from_=from_number,
                to=phone
            )
            logger.info(f"📱 SMS sent to {phone}: {message_body[:20]}...")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send SMS to {phone_number}: {e}")
            return False

    # --- Business Event Methods ---
    
    @classmethod
    def notify_order_placed(cls, order):
        cls.send_email(
            subject=f"Order Confirmed: #{order.reference}",
            recipient_email=order.buyer.email,
            template_name="emails/order_confirmation.html",
            context={"order": order}
        )
        
        sellers = set(item.seller for item in order.items.all())
        for seller in sellers:
             cls.send_sms(
                 seller.support_phone or seller.user.phone,
                 f"Jodise New Order: #{order.reference}. Check dashboard!"
             )

    @classmethod
    def notify_order_shipped(cls, delivery_order):
        cls.send_sms(
            delivery_order.contact_phone,
            f"Shipped! Your order #{delivery_order.order_code} is on the way. Track: jodise.com/track/{delivery_order.tracking_number}"
        )

    @classmethod
    def notify_order_delivered(cls, delivery_order):
        cls.send_sms(
            delivery_order.contact_phone,
            f"Delivered! Order #{delivery_order.order_code} has arrived. Thanks for choosing Jodise!"
        )
