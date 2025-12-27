from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, SellerProfile

# -----------------------------------------------------
#  CUSTOM USER ADMIN
# -----------------------------------------------------
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("email", "first_name", "last_name", "is_seller", "is_approved_seller", "is_staff")
    list_filter = ("is_seller", "is_approved_seller", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "phone", "country", "state", "city")}),
        ("Roles", {"fields": ("is_seller", "is_approved_seller", "is_staff", "is_superuser")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "password1", "password2"),
        }),
    )

    actions = ["approve_sellers", "revoke_sellers"]

    @admin.action(description="✅ Approve selected sellers")
    def approve_sellers(self, request, queryset):
        updated = 0
        for user in queryset.filter(is_seller=True):
            user.is_approved_seller = True
            user.save()
            SellerProfile.objects.filter(user=user).update(is_verified=True)
            updated += 1
        self.message_user(request, f"{updated} seller(s) approved successfully.")

    @admin.action(description="❌ Revoke seller approval")
    def revoke_sellers(self, request, queryset):
        updated = 0
        for user in queryset.filter(is_seller=True):
            user.is_approved_seller = False
            user.save()
            SellerProfile.objects.filter(user=user).update(is_verified=False)
            updated += 1
        self.message_user(request, f"{updated} seller(s) approval revoked.")



# -----------------------------------------------------
#  SELLER PROFILE ADMIN
# -----------------------------------------------------
@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("store_name", "user", "commission_rate", "is_verified", "wallet_balance", "date_joined")
    list_filter = ("is_verified", "is_active", "date_joined")
    search_fields = ("store_name", "user__email", "user__first_name")
    readonly_fields = ("store_slug", "date_joined", "wallet_balance")
    ordering = ("-date_joined",)
    actions = ["approve_profiles", "reject_profiles"]

    @admin.action(description="✅ Approve selected seller profiles")
    def approve_profiles(self, request, queryset):
        updated = 0
        for seller in queryset:
            seller.is_verified = True
            seller.save()
            seller.user.is_approved_seller = True
            seller.user.save()
            updated += 1
        self.message_user(request, f"{updated} seller profile(s) approved successfully.")

    @admin.action(description="❌ Reject selected seller profiles")
    def reject_profiles(self, request, queryset):
        updated = 0
        for seller in queryset:
            seller.is_verified = False
            seller.save()
            seller.user.is_approved_seller = False
            seller.user.save()
            updated += 1
        self.message_user(request, f"{updated} seller profile(s) rejected.")




