# store/models.py
from __future__ import annotations

import os
import uuid
import random
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image

from accounts.models import CustomUser, SellerProfile
from accounts.utils import paystack


# ===========================================================
# FILE VALIDATION
# ===========================================================
def validate_image_file(value):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise ValidationError("Allowed formats: JPG, JPEG, PNG, WEBP only.")
    if value.size > 5 * 1024 * 1024:
        raise ValidationError("Maximum file size is 5MB.")


# ===========================================================
# ABSTRACT BASE
# ===========================================================
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ===========================================================
# WAREHOUSE (CONSOLIDATION HUB)
# ===========================================================
class Warehouse(TimeStampedModel):
    """
    Your consolidation hub: all sellers send their packages here first.
    Then you pack them together and ship ONE consolidated package to buyer.
    """
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, unique=True, db_index=True)  # e.g. LAG-01
    address = models.TextField()
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, blank=True, default="Nigeria")

    contact_phone = models.CharField(max_length=40, blank=True)
    contact_email = models.EmailField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


# ===========================================================
# ADMIN-CONTROLLED MARKET SETTINGS
# ===========================================================
class MarketplaceSetting(models.Model):
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("7.5"))
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.0"))

    # 💰 CURRENCY CONFIG
    currency_symbol = models.CharField(max_length=10, default="₦", help_text="Symbol to display (e.g. ₦, $, €)")
    currency_code = models.CharField(max_length=10, default="NGN", help_text="ISO Code (e.g. NGN, USD, EUR)")

    # 💳 PAYMENT CONFIG
    PAYMENT_GATEWAYS = [
        ("paystack", "Paystack"),
        ("stripe", "Stripe (Global)"),
        ("paypal", "PayPal (Global - Coming Soon)"),
    ]
    active_gateway = models.CharField(max_length=20, choices=PAYMENT_GATEWAYS, default="paystack")

    # Paystack
    paystack_public_key = models.CharField(max_length=255, blank=True, null=True)
    paystack_secret_key = models.CharField(max_length=255, blank=True, null=True)

    # Stripe
    stripe_publishable_key = models.CharField(max_length=255, blank=True, null=True)
    stripe_secret_key = models.CharField(max_length=255, blank=True, null=True)

    # 📧 EMAIL CONFIG (SMTP)
    email_host = models.CharField(max_length=255, default="smtp.gmail.com", blank=True)
    email_port = models.IntegerField(default=587)
    email_host_user = models.CharField(max_length=255, blank=True)
    email_host_password = models.CharField(max_length=255, blank=True)
    email_use_tls = models.BooleanField(default=True)

    # 📱 SMS CONFIG (Twilio)
    twilio_sid = models.CharField(max_length=255, blank=True)
    twilio_auth_token = models.CharField(max_length=255, blank=True)
    twilio_from_number = models.CharField(max_length=50, blank=True)

    # ✅ Warehouse consolidation default hub
    default_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name="default_for_settings"
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"VAT {self.vat_rate}% | Commission {self.commission_rate}%"

    @classmethod
    def current(cls):
        return cls.objects.first() or cls.objects.create()


# ===========================================================
# CATEGORY / PRODUCT TYPE
# ===========================================================
class Category(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=150, unique=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    image = models.ImageField(upload_to="categories/", blank=True, null=True, validators=[validate_image_file])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.parent} > {self.name}" if self.parent else self.name


class ProductType(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    has_variants = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ===========================================================
# PRODUCT
# ===========================================================
class Product(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    # ✅ Jumia-style numeric id for URL
    public_id = models.BigIntegerField(unique=True, editable=False, null=True, blank=True, db_index=True)

    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name="products")
    product_type = models.ForeignKey(ProductType, on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    sku = models.CharField(max_length=40, unique=True, blank=True)  # auto-generate
    description = models.TextField()
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["public_id"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["seller", "is_active"]),
            models.Index(fields=["category", "is_active"]),
        ]

    def _generate_unique_public_id(self):
        for _ in range(20):
            pid = random.randint(100000000, 9999999999)
            if not type(self).objects.filter(public_id=pid).exists():
                return pid
        return int(str(uuid4().int)[:10])

    def _generate_unique_slug(self):
        base = slugify(self.name)[:200] or "product"
        s = base
        n = 1
        while type(self).objects.filter(slug=s).exclude(pk=self.pk).exists():
            n += 1
            s = f"{base}-{n}"
        return s

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = self._generate_unique_public_id()

        if not self.slug:
            self.slug = self._generate_unique_slug()

        if not self.sku:
            seller_ref = str(self.seller.id).replace("-", "")[:4].upper()
            rand_ref = uuid4().hex[:6].upper()
            self.sku = f"JOD-{seller_ref}-{rand_ref}"

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("product_detail", kwargs={"slug": self.slug, "public_id": self.public_id})

    def __str__(self):
        return self.name


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/", validators=[validate_image_file])
    alt_text = models.CharField(max_length=120, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "-created_at"]

    def save(self, *args, **kwargs):
        if self.image:
            self.compress_image()
        super().save(*args, **kwargs)

    def compress_image(self):
        img = Image.open(self.image)

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        max_size = (1024, 1024)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=80, optimize=True)
        buffer.seek(0)

        new_filename = f"{self.product.slug}-{uuid4().hex[:4]}.jpg"
        self.image.save(new_filename, ContentFile(buffer.read()), save=False)

    def __str__(self):
        return f"Image for {self.product.name}"


# ===========================================================
# DELIVERY / SHIPPING METHOD
# ===========================================================
class DeliveryMethod(models.Model):
    name = models.CharField(max_length=100)
    flat_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    estimated_days = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (₦{self.flat_fee})"


# ===========================================================
# ORDER (MULTI-VENDOR)
# ===========================================================
class Order(TimeStampedModel):
    STATUS = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("processing", "Processing"),
        ("shipped", "Shipped"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    reference = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    buyer = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="orders")
    delivery_method = models.ForeignKey(DeliveryMethod, on_delete=models.SET_NULL, null=True)

    status = models.CharField(max_length=20, choices=STATUS, default="pending")

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    tracking_no = models.CharField(max_length=6, unique=True, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tracking_no"]),
            models.Index(fields=["status", "created_at"]),
        ]

    @staticmethod
    def generate_tracking_no():
        while True:
            code = "{:06X}".format(random.randint(0, 0xFFFFFF))
            if not Order.objects.filter(tracking_no=code).exists():
                return code

    def save(self, *args, **kwargs):
        if not self.tracking_no:
            self.tracking_no = self.generate_tracking_no()
        super().save(*args, **kwargs)

    def calculate_totals(self):
        config = MarketplaceSetting.current()
        items = self.items.all()

        self.subtotal = sum((i.subtotal for i in items), Decimal("0"))
        self.vat = (self.subtotal * config.vat_rate) / 100
        self.delivery_fee = self.delivery_method.flat_fee if self.delivery_method else Decimal("0")
        self.total = self.subtotal + self.vat + self.delivery_fee

        self.save(update_fields=["subtotal", "vat", "delivery_fee", "total"])

    def __str__(self):
        return f"Order {self.reference}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    seller = models.ForeignKey(SellerProfile, on_delete=models.SET_NULL, null=True)

    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    seller_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["seller"]),
        ]

    def calculate_line(self, commission_rate=None):
        config = MarketplaceSetting.current()
        rate = commission_rate if commission_rate is not None else config.commission_rate

        self.subtotal = self.unit_price * self.quantity
        self.vat = (self.subtotal * config.vat_rate) / 100
        self.commission = (self.subtotal * rate) / 100
        self.seller_earnings = self.subtotal - self.vat - self.commission
        self.save()

    def __str__(self):
        return f"{self.quantity} × {self.product.name if self.product else 'Unknown'}"


# ===========================================================
# PAYMENT (PAYSTACK)
# ===========================================================
class PaymentTransaction(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    buyer = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("success", "Success"),
            ("failed", "Failed"),
            ("refunded", "Refunded"),
        ],
        default="pending",
    )
    gateway_response = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["reference"]), models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.reference} - {self.status}"

    def initialize_paystack(self, callback_url):
        meta = {"order_ref": str(self.order.reference), "buyer": self.buyer.email if self.buyer else ""}
        return paystack.initialize_payment(self.buyer.email, self.amount, meta, callback_url)

    def verify_paystack(self):
        verified = paystack.verify_payment(self.reference)
        if verified:
            self.status = "success"
            self.save(update_fields=["status"])
        return verified


# ===========================================================
# PROMO CODES
# ===========================================================
class PromoCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2)
    active = models.BooleanField(default=True)
    usage_limit = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-valid_from"]

    def is_valid(self):
        now = timezone.now()
        return self.active and self.valid_from <= now and (not self.valid_to or now <= self.valid_to)

    def use(self):
        if self.usage_limit and self.used_count >= self.usage_limit:
            self.active = False
        self.used_count += 1
        self.save(update_fields=["active", "used_count"])

    def __str__(self):
        return f"{self.code} ({self.discount_percent}%)"


# ===========================================================
# REFUND
# ===========================================================
class RefundRequest(TimeStampedModel):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="refunds")
    reason = models.TextField()
    amount_requested = models.DecimalField(max_digits=12, decimal_places=2)
    approved = models.BooleanField(default=False)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def approve(self):
        self.approved = True
        self.processed_at = timezone.now()
        self.save(update_fields=["approved", "processed_at"])


# ===========================================================
# WAREHOUSE CONSOLIDATION TIMELINE (BUYER-FRIENDLY)
# ===========================================================
class OrderEvent(TimeStampedModel):
    """
    Order timeline events for buyer tracking + internal auditing.
    Examples:
      - ORDER_PAID
      - SELLER_SENT_TO_WAREHOUSE
      - WAREHOUSE_RECEIVED_SELLER
      - WAREHOUSE_ALL_RECEIVED
      - WAREHOUSE_PACKED
      - DISPATCHED
      - DELIVERED
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    code = models.CharField(max_length=50, db_index=True)
    message = models.CharField(max_length=255)
    actor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    meta = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["order", "created_at"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return f"{self.order.tracking_no} | {self.code}"


# ===========================================================
# SELLER -> WAREHOUSE FULFILLMENT (PER SELLER, SAME GLOBAL ORDER NUMBER)
# ===========================================================
class SellerFulfillment(TimeStampedModel):
    """
    One row per (order, seller).
    Sellers ONLY update up to "sent_to_warehouse".
    Warehouse updates "received_at_warehouse".
    """
    STATUS = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("packing", "Packing"),
        ("sent_to_warehouse", "Sent to Warehouse"),
        ("received_at_warehouse", "Received at Warehouse"),
        ("issue", "Issue"),
        ("cancelled", "Cancelled"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="seller_fulfillments")
    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name="fulfillments")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True)

    status = models.CharField(max_length=30, choices=STATUS, default="pending")
    note = models.TextField(blank=True)

    # Optional inbound tracking to warehouse (seller -> warehouse)
    inbound_carrier = models.CharField(max_length=100, blank=True)
    inbound_tracking = models.CharField(max_length=120, blank=True)

    accepted_at = models.DateTimeField(null=True, blank=True)
    packed_at = models.DateTimeField(null=True, blank=True)
    sent_to_warehouse_at = models.DateTimeField(null=True, blank=True)

    received_at_warehouse_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_fulfillments"
    )

    class Meta:
        unique_together = ("order", "seller")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["seller", "status"]),
            models.Index(fields=["order", "status"]),
            models.Index(fields=["warehouse", "status"]),
        ]

    def __str__(self):
        return f"{self.order.tracking_no} | {self.seller.store_name} | {self.status}"


# ===========================================================
# SHIPMENT (WAREHOUSE -> BUYER)  [ONE CONSOLIDATED SHIPMENT]
# ===========================================================
class Shipment(TimeStampedModel):
    """
    Single outbound shipment per order in warehouse consolidation mode.
    (You can keep multiple shipments later if you support split shipments.)
    """
    STATUS = [
        ("awaiting_sellers", "Awaiting Sellers"),
        ("packing", "Packing at Warehouse"),
        ("pending", "Pending Pickup"),
        ("in_transit", "In Transit"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True)

    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    carrier = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS, default="awaiting_sellers")

    packed_at = models.DateTimeField(blank=True, null=True)
    dispatched_at = models.DateTimeField(blank=True, null=True)

    estimated_delivery = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["tracking_number"]),
        ]

    def __str__(self):
        return f"{self.order.tracking_no} - {self.status}"


# ===========================================================
# INSIGHTS / ANALYTICS
# ===========================================================
class ProductInsight(TimeStampedModel):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="insight")
    views = models.PositiveIntegerField(default=0)
    purchases = models.PositiveIntegerField(default=0)
    refunds = models.PositiveIntegerField(default=0)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)

    def record_view(self):
        self.views += 1
        self.save(update_fields=["views"])

    def record_purchase(self):
        self.purchases += 1
        self.save(update_fields=["purchases"])

    def record_refund(self):
        self.refunds += 1
        self.save(update_fields=["refunds"])


# ===========================================================
# SELLER PAYOUTS
# ===========================================================
class SellerPayout(models.Model):
    seller = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="payouts")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payouts")

    total_earned = models.DecimalField(max_digits=10, decimal_places=2)
    vat_deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payable_amount = models.DecimalField(max_digits=10, decimal_places=2)

    paid = models.BooleanField(default=False)
    paid_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def mark_paid(self):
        self.paid = True
        self.paid_date = timezone.now()
        self.save(update_fields=["paid", "paid_date"])

    def __str__(self):
        return f"Payout for {self.seller} on {self.order.reference}"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Seller Payout"
        verbose_name_plural = "Seller Payouts"


# ===========================================================
# 💸 PAYOUT REQUEST (Withdrawal)
# ===========================================================
class PayoutRequest(TimeStampedModel):
    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name="payout_requests")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    bank_details = models.TextField(help_text="Snapshot of bank details at time of request")
    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pending"), ("paid", "Paid"), ("rejected", "Rejected")],
        default="pending",
    )
    admin_note = models.TextField(blank=True, null=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Request ₦{self.amount} by {self.seller.store_name} ({self.status})"
