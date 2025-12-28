from __future__ import annotations

from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Product,
    ProductImage,
    DeliveryMethod,
    Order,
    OrderItem,
    PaymentTransaction,
    RefundRequest,
    Shipment,
    PromoCode,
)

from accounts.models import CustomUser, SellerProfile

# Optional: Only used if you still do Paystack init via forms (fallback).
# Prefer doing initialization in views/services.
try:
    from accounts.utils import paystack
except Exception:
    paystack = None


# ============================================================
# 🎨 Tailwind helpers (consistent, reusable)
# ============================================================
TW_INPUT = (
    "w-full px-3 py-3 rounded-xl border border-gray-200 bg-white text-gray-900 "
    "placeholder:text-gray-400 outline-none "
    "focus:ring-2 focus:ring-orange-300 focus:border-orange-300"
)

TW_SELECT = TW_INPUT
TW_TEXTAREA = (
    "w-full px-3 py-3 rounded-xl border border-gray-200 bg-white text-gray-900 "
    "placeholder:text-gray-400 outline-none resize-y "
    "focus:ring-2 focus:ring-orange-300 focus:border-orange-300"
)

TW_CHECKBOX = "h-4 w-4 rounded border-gray-300 text-orange-600 focus:ring-orange-300"

TW_FILE = (
    "block w-full text-sm text-gray-700 "
    "file:mr-4 file:py-2 file:px-4 "
    "file:rounded-full file:border-0 file:font-semibold "
    "file:bg-orange-50 file:text-orange-700 hover:file:bg-orange-100"
)


# ============================================================
# 🌟 Base Secure Form
# ============================================================
class SecureForm(forms.ModelForm):
    """
    Common base form to enforce security and consistency.
    """

    def add_tailwind(self, field_name: str, kind: str = "input"):
        field = self.fields.get(field_name)
        if not field:
            return

        if kind == "textarea":
            field.widget.attrs.update({"class": TW_TEXTAREA})
        elif kind == "select":
            field.widget.attrs.update({"class": TW_SELECT})
        elif kind == "checkbox":
            field.widget.attrs.update({"class": TW_CHECKBOX})
        elif kind == "file":
            field.widget.attrs.update({"class": TW_FILE})
        else:
            field.widget.attrs.update({"class": TW_INPUT})


# ============================================================
# 🛍️ PRODUCT FORM (for Sellers)
# ============================================================
class ProductForm(SecureForm):
    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "description",
            "price",
            "stock",
            "is_active",
            "is_featured",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5, "placeholder": "Describe your product..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for f in self.fields:
            if f == "description":
                self.add_tailwind(f, "textarea")
            elif f == "category":
                self.add_tailwind(f, "select")
            elif f in ("is_active", "is_featured"):
                self.add_tailwind(f, "checkbox")
            else:
                self.add_tailwind(f, "input")

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None or Decimal(price) <= 0:
            raise ValidationError("Price must be greater than zero.")
        return price

    def clean_stock(self):
        stock = self.cleaned_data.get("stock")
        if stock is None:
            return 0
        if int(stock) < 0:
            raise ValidationError("Stock cannot be negative.")
        return stock


# ============================================================
# 🖼️ PRODUCT IMAGE FORM
# ============================================================
class ProductImageForm(SecureForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "is_primary"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["image"].widget.attrs.update({"accept": "image/*"})
        self.add_tailwind("image", "file")
        self.add_tailwind("alt_text", "input")
        self.add_tailwind("is_primary", "checkbox")

        self.fields["alt_text"].widget.attrs.update({"placeholder": "Optional image description"})


# ============================================================
# 🚚 DELIVERY METHOD FORM (Admin/Internal)
# (Even if you don’t show delivery options on checkout UI,
#  you can still keep this for admin configuration.)
# ============================================================
class DeliveryMethodForm(SecureForm):
    class Meta:
        model = DeliveryMethod
        fields = ["name", "flat_fee", "estimated_days", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for f in self.fields:
            if f == "is_active":
                self.add_tailwind(f, "checkbox")
            else:
                self.add_tailwind(f, "input")

    def clean_flat_fee(self):
        fee = self.cleaned_data.get("flat_fee")
        if fee is None:
            return Decimal("0.00")
        if Decimal(fee) < 0:
            raise ValidationError("Delivery fee cannot be negative.")
        return fee


# ============================================================
# 🏠 CHECKOUT ADDRESS FORM (NEW ✅)
# This replaces delivery option selection on checkout.
# ============================================================
class CheckoutAddressForm(SecureForm):
    class Meta:
        model = CustomUser
        fields = ("address_line1", "address_line2", "city", "state", "country", "postal_code")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_tailwind("address_line1", "input")
        self.add_tailwind("address_line2", "input")
        self.add_tailwind("city", "input")
        self.add_tailwind("state", "input")
        self.add_tailwind("country", "select")
        self.add_tailwind("postal_code", "input")

        self.fields["address_line1"].widget.attrs.update({"placeholder": "Street address, house number"})
        self.fields["address_line2"].widget.attrs.update({"placeholder": "Apartment, suite, landmark (optional)"})
        self.fields["city"].widget.attrs.update({"placeholder": "City"})
        self.fields["state"].widget.attrs.update({"placeholder": "State"})
        self.fields["postal_code"].widget.attrs.update({"placeholder": "Postal code (optional)"})

    def clean(self):
        cleaned = super().clean()
        required = ["address_line1", "city", "state", "country"]
        for f in required:
            if not cleaned.get(f):
                self.add_error(f, "This field is required.")
        return cleaned


# ============================================================
# 💳 PAYMENT FORM (Optional/Fallback)
# Prefer payment init in views/services, but keep this safe.
# ============================================================
class PaymentForm(forms.ModelForm):
    class Meta:
        model = PaymentTransaction
        fields = ["amount"]

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or Decimal(amount) <= 0:
            raise ValidationError("Invalid payment amount.")
        return amount

    def initialize_transaction(self, buyer_email: str, order: Order, callback_url: str):
        """
        Optional Paystack initialization from form.
        Prefer PaymentService in views.
        """
        if paystack is None:
            raise ValidationError("Paystack module not available.")

        amount = self.cleaned_data.get("amount")
        metadata = {"order_ref": str(order.reference), "buyer_email": buyer_email}

        # Your paystack.initialize_payment signature must match this.
        return paystack.initialize_payment(
            buyer_email=buyer_email,
            amount=amount,
            metadata=metadata,
            callback_url=callback_url,
        )


# ============================================================
# 📦 ORDER ITEM FORM (Internal/Admin)
# ============================================================
class OrderItemForm(SecureForm):
    class Meta:
        model = OrderItem
        fields = ["product", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_tailwind("product", "select")
        self.add_tailwind("quantity", "input")

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        try:
            qty = int(qty)
        except Exception:
            raise ValidationError("Quantity must be a number.")
        if qty < 1:
            raise ValidationError("Quantity must be at least 1.")
        return qty


# ============================================================
# 💰 REFUND REQUEST FORM
# ============================================================
class RefundRequestForm(SecureForm):
    class Meta:
        model = RefundRequest
        fields = ["reason", "amount_requested"]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 4, "placeholder": "Briefly explain why you want a refund..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_tailwind("reason", "textarea")
        self.add_tailwind("amount_requested", "input")

    def clean_amount_requested(self):
        amount = self.cleaned_data.get("amount_requested")
        if amount is None or Decimal(amount) <= 0:
            raise ValidationError("Refund amount must be greater than zero.")
        return amount


# ============================================================
# 🚚 SHIPMENT / FULFILMENT FORM
# ============================================================
class ShipmentForm(SecureForm):
    class Meta:
        model = Shipment
        fields = ["tracking_number", "carrier", "status", "estimated_delivery"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for f in self.fields:
            if f == "estimated_delivery":
                self.fields[f].widget = forms.DateTimeInput(attrs={"type": "datetime-local"})
                self.add_tailwind(f, "input")
            else:
                self.add_tailwind(f, "input")

    def clean_estimated_delivery(self):
        eta = self.cleaned_data.get("estimated_delivery")
        if eta and eta < timezone.now():
            raise ValidationError("Estimated delivery cannot be in the past.")
        return eta


# ============================================================
# 🎟️ PROMO CODE FORM
# ============================================================
class PromoCodeForm(forms.Form):
    code = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={"placeholder": "Enter promo code", "class": TW_INPUT}),
    )

    def clean_code(self):
        raw = (self.cleaned_data.get("code") or "").strip().upper()
        if not raw:
            raise ValidationError("Enter a promo code.")

        promo = PromoCode.objects.filter(code__iexact=raw, active=True).first()
        if not promo or not promo.is_valid():
            raise ValidationError("Invalid or expired promo code.")

        # Return the string code (safer for callers) OR return the promo object if you prefer.
        return raw


# ============================================================
# ⚙️ SELLER SETTINGS FORM
# ============================================================
class SellerSettingsForm(SecureForm):
    class Meta:
        model = SellerProfile
        fields = [
            "store_name",
            "description",
            "support_phone",
            "support_email",
            "store_logo",
            "store_banner",
            "bank_account_name",
            "bank_account_number",
            "bank_name",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for f in self.fields:
            if f in ("store_logo", "store_banner"):
                self.add_tailwind(f, "file")
            elif f == "description":
                self.add_tailwind(f, "textarea")
            else:
                self.add_tailwind(f, "input")

        self.fields["store_name"].widget.attrs.update({"placeholder": "Your store name"})
        self.fields["support_email"].widget.attrs.update({"placeholder": "Support email (optional)"})
        self.fields["bank_account_name"].widget.attrs.update({"placeholder": "Account name"})
        self.fields["bank_account_number"].widget.attrs.update({"placeholder": "Account number"})
        self.fields["bank_name"].widget.attrs.update({"placeholder": "Bank name"})




# store/forms.py
from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class DeliveryAddressForm(forms.ModelForm):
    """
    Checkout delivery address.
    Saves into CustomUser fields:
      country, state, city, address_line1, address_line2, postal_code
    """
    class Meta:
        model = User
        fields = ["country", "state", "city", "address_line1", "address_line2", "postal_code"]
        widgets = {
            "state": forms.TextInput(attrs={"placeholder": "State"}),
            "city": forms.TextInput(attrs={"placeholder": "City"}),
            "address_line1": forms.TextInput(attrs={"placeholder": "Address line 1"}),
            "address_line2": forms.TextInput(attrs={"placeholder": "Address line 2 (optional)"}),
            "postal_code": forms.TextInput(attrs={"placeholder": "Postal code (optional)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        base = "w-full border border-gray-200 rounded-xl px-3 py-2 outline-none focus:ring-2 focus:ring-yellow-400"
        for f in self.fields.values():
            f.widget.attrs["class"] = base
