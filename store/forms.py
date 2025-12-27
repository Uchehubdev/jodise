from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from .models import (
    Product, ProductImage, DeliveryMethod,
    Order, OrderItem, PaymentTransaction,
    RefundRequest, Shipment, PromoCode
)
from accounts.utils import paystack


# ============================================================
# 🌟 Base Secure Form
# ============================================================
class SecureForm(forms.ModelForm):
    """Common base form to enforce security and consistency."""
    def add_tailwind(self, field_name):
        """Helper for Tailwind-style input classes."""
        self.fields[field_name].widget.attrs.update({
            "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
        })


# ============================================================
# 🛍️ PRODUCT FORM (for Sellers)
# ============================================================
class ProductForm(SecureForm):
    class Meta:
        model = Product
        fields = [
            "name", "category", "description",
            "price", "stock", "is_active", "is_featured"
        ]
        widgets = {
            "description": forms.Textarea(attrs={
                "rows": 4, "placeholder": "Describe your product..."
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.add_tailwind(field)

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if not price or price <= 0:
            raise ValidationError("Price must be greater than zero.")
        return price

    def clean_stock(self):
        stock = self.cleaned_data.get("stock")
        if stock < 0:
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
        self.fields["image"].widget.attrs.update({
            "accept": "image/*",
            "class": "block w-full text-sm text-gray-700 file:mr-4 file:py-2 file:px-4 "
                     "file:rounded-full file:border-0 file:font-semibold file:bg-indigo-50 "
                     "file:text-indigo-700 hover:file:bg-indigo-100"
        })
        self.add_tailwind("alt_text")


# ============================================================
# 🚚 DELIVERY METHOD FORM
# ============================================================
class DeliveryMethodForm(SecureForm):
    class Meta:
        model = DeliveryMethod
        fields = ["name", "flat_fee", "estimated_days", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.add_tailwind(field)

    def clean_flat_fee(self):
        fee = self.cleaned_data.get("flat_fee", 0)
        if fee < 0:
            raise ValidationError("Delivery fee cannot be negative.")
        return fee


# ============================================================
# 💳 CHECKOUT / PAYMENT INITIALIZATION
# ============================================================
class CheckoutForm(SecureForm):
    """Handles order confirmation and Paystack initialization."""
    delivery_method = forms.ModelChoiceField(
        queryset=DeliveryMethod.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500"
        }),
        required=True,
        label="Select Delivery Method"
    )

    class Meta:
        model = Order
        fields = ["delivery_method"]

    def clean_delivery_method(self):
        method = self.cleaned_data.get("delivery_method")
        if not method:
            raise ValidationError("Please select a valid delivery method.")
        return method


class PaymentForm(forms.ModelForm):
    """Handles Paystack payment initialization securely."""
    class Meta:
        model = PaymentTransaction
        fields = ["amount"]

    def initialize_transaction(self, buyer_email, order, callback_url):
        """Creates a Paystack transaction securely."""
        amount = self.cleaned_data.get("amount")
        if not amount or amount <= 0:
            raise ValidationError("Invalid payment amount.")

        metadata = {"order_ref": order.reference, "buyer_email": buyer_email}
        return paystack.initialize_payment(buyer_email, amount, metadata, callback_url)


# ============================================================
# 📦 ORDER ITEM FORM (Internal/Admin)
# ============================================================
class OrderItemForm(SecureForm):
    class Meta:
        model = OrderItem
        fields = ["product", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.add_tailwind(f)

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
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
            "reason": forms.Textarea(attrs={
                "rows": 3, "placeholder": "Provide a brief reason for refund."
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.add_tailwind(f)

    def clean_amount_requested(self):
        amount = self.cleaned_data.get("amount_requested")
        if not amount or amount <= 0:
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
            self.add_tailwind(f)

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
        widget=forms.TextInput(attrs={
            "placeholder": "Enter promo code",
            "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-green-500"
        })
    )

    def clean_code(self):
        code = self.cleaned_data.get("code", "").strip().upper()
        from .models import PromoCode
        promo = PromoCode.objects.filter(code=code, active=True).first()
        if not promo or not promo.is_valid():
            raise ValidationError("Invalid or expired promo code.")
        return promo


# ============================================================
# ⚙️ SELLER SETTINGS FORM
# ============================================================
from accounts.models import SellerProfile
class SellerSettingsForm(SecureForm):
    class Meta:
        model = SellerProfile
        fields = [
            "store_name", "description", "support_phone", "support_email",
            "store_logo", "store_banner",
            "bank_account_name", "bank_account_number", "bank_name"
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.add_tailwind(f)
            
        # File inputs styling
        for field_name in ["store_logo", "store_banner"]:
            self.fields[field_name].widget.attrs.update({
                "class": "file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 text-sm text-gray-500"
            })
