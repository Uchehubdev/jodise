from django.contrib import admin
from .models import (
    Category, ProductType, Product, ProductImage, DeliveryMethod,
    Order, OrderItem, PaymentTransaction, RefundRequest,
    Shipment, ProductInsight, SellerPayout, MarketplaceSetting, PromoCode,
    PayoutRequest
)


# ===========================================================
# INLINE ADMIN CONFIGS
# ===========================================================
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "quantity", "unit_price", "subtotal", "seller_earnings")


# ===========================================================
# PRODUCT ADMIN
# ===========================================================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "seller", "price", "stock", "is_active", "is_featured", "created_at")
    list_filter = ("is_active", "is_featured", "category")
    search_fields = ("name", "seller__store_name")
    inlines = [ProductImageInline]


# ===========================================================
# ORDER ADMIN
# ===========================================================
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "buyer", "status", "total", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("reference", "buyer__email")
    inlines = [OrderItemInline]


# ===========================================================
# REFUND ADMIN
# ===========================================================
@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    list_display = ("order_item", "amount_requested", "approved", "processed_at")
    list_filter = ("approved",)
    search_fields = ("order_item__product__name",)
    readonly_fields = ("order_item", "reason", "amount_requested", "approved", "processed_at")


# ===========================================================
# PAYOUT ADMIN
# ===========================================================
@admin.register(SellerPayout)
class SellerPayoutAdmin(admin.ModelAdmin):
    list_display = (
        "seller",
        "order",
        "payable_amount",
        "paid",
        "paid_date",
        "created_at",
    )
    list_filter = ("paid", "created_at")
    search_fields = ("seller__email", "order__reference")
    readonly_fields = ("seller", "order", "total_earned", "vat_deducted", "commission_deducted", "payable_amount", "paid", "paid_date", "created_at")


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display = ("seller", "amount", "status", "processed_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("seller__store_name", "seller__user__email")
    readonly_fields = ("seller", "amount", "bank_details", "created_at", "processed_at")
    actions = ["mark_as_paid", "reject_request"]

    @admin.action(description="✅ Mark selected as PAID")
    def mark_as_paid(self, request, queryset):
        rows = 0
        from django.utils import timezone
        for req in queryset.filter(status="pending"):
            req.status = "paid"
            req.processed_at = timezone.now()
            req.save()
            rows += 1
        self.message_user(request, f"{rows} payout(s) marked as PAID.")

    @admin.action(description="❌ Reject selected requests")
    def reject_request(self, request, queryset):
        rows = queryset.filter(status="pending").update(status="rejected", processed_at=timezone.now())
        self.message_user(request, f"{rows} payout(s) rejected.")


# ===========================================================
# MISC ADMIN
# ===========================================================
@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "order", "buyer", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "buyer__email", "order__reference")
    readonly_fields = ("reference", "order", "buyer", "amount", "status", "gateway_response", "created_at")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "has_variants", "is_active")


@admin.register(MarketplaceSetting)
class MarketplaceSettingAdmin(admin.ModelAdmin):
    list_display = ("vat_rate", "active_gateway", "updated_at")
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("General", {
            "fields": ("vat_rate", "commission_rate", "currency_symbol", "currency_code")
        }),
        ("💳 Payment Configuration", {
            "fields": (
                "active_gateway", 
                "paystack_public_key", "paystack_secret_key",
                "stripe_publishable_key", "stripe_secret_key"
            ),
            "description": "Configure keys for your chosen gateway. Ensure the active gateway has keys set.",
            "classes": ("collapse",),
        }),
        ("📧 Email Configuration (SMTP)", {
            "fields": ("email_host", "email_port", "email_host_user", "email_host_password", "email_use_tls"),
            "classes": ("collapse",),
        }),
        ("📱 SMS Configuration (Twilio)", {
            "fields": ("twilio_sid", "twilio_auth_token", "twilio_from_number"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        # Only allow one setting instance
        return not MarketplaceSetting.objects.exists()


@admin.register(DeliveryMethod)
class DeliveryMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "flat_fee", "estimated_days", "is_active")


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "tracking_number", "carrier", "status", "estimated_delivery", "delivered_at")
    list_filter = ("status",)
    search_fields = ("order__reference", "tracking_number")


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_percent", "active", "usage_limit", "used_count", "valid_from", "valid_to")
    search_fields = ("code",)
    list_filter = ("active", "valid_from", "valid_to")


@admin.register(ProductInsight)
class ProductInsightAdmin(admin.ModelAdmin):
    list_display = ("product", "views", "purchases", "refunds", "rating_avg")
