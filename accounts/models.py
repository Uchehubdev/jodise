from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.utils.text import slugify
import os


# -------------------------------------------------
#  USER MANAGER
# -------------------------------------------------
class CustomUserManager(BaseUserManager):
    """Manager handling secure user & superuser creation."""

    def create_user(self, email, first_name, last_name, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)

        user = self.model(
            email=email,
            first_name=first_name.strip().title(),
            last_name=last_name.strip().title(),
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, first_name, last_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, first_name, last_name, password, **extra_fields)


# -------------------------------------------------
#  USER MODEL
# -------------------------------------------------
class CustomUser(AbstractBaseUser, PermissionsMixin):
    """Clean, secure, and international-ready user model for Jodise."""

    # --- Identity ---
    email = models.EmailField(unique=True)
    first_name = models.CharField(
        max_length=100,
        validators=[RegexValidator(r"^[A-Za-zÀ-ÿ' -]+$", "First name must contain only letters.")]
    )
    last_name = models.CharField(
        max_length=100,
        validators=[RegexValidator(r"^[A-Za-zÀ-ÿ' -]+$", "Last name must contain only letters.")]
    )

    # --- Contact ---
    phone = PhoneNumberField(unique=True, blank=True, null=True)
    phone_verified = models.BooleanField(default=False)

    # --- Location / Shipping ---
    country = CountryField(blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)

    # --- Profile Info ---
    profile_image = models.ImageField(upload_to="profiles/", blank=True, null=True)
    gender = models.CharField(
        max_length=10,
        choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")],
        blank=True,
        null=True,
    )
    date_of_birth = models.DateField(blank=True, null=True)

    # --- Roles / Referrals ---
    is_seller = models.BooleanField(default=False)
    is_approved_seller = models.BooleanField(default=False)
    referral_code = models.CharField(max_length=20, blank=True, null=True)
    referred_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="referrals"
    )

    # --- Permissions ---
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # --- Security / Monitoring ---
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    account_locked_until = models.DateTimeField(blank=True, null=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    # --- Security helpers ---
    def lock_account(self, minutes=15):
        """Temporarily lock user after too many failed logins."""
        from datetime import timedelta
        self.account_locked_until = timezone.now() + timedelta(minutes=minutes)
        self.save()

    def is_locked(self):
        """Check if account is currently locked."""
        return self.account_locked_until and self.account_locked_until > timezone.now()

    @property
    def full_address(self):
        """Return formatted shipping address."""
        parts = [
            self.address_line1, self.address_line2, self.city,
            self.state, self.country.name if self.country else None, self.postal_code
        ]
        return ", ".join([p for p in parts if p])


    def request_seller_status(self):
        """User applies to become a seller (awaiting admin approval)."""
        self.is_seller = True
        self.is_approved_seller = False
        self.save()

    def approve_seller(self):
        """Admin approves seller account."""
        self.is_approved_seller = True
        self.save()

    def revoke_seller(self):
        """Admin revokes seller rights."""
        self.is_approved_seller = False
        self.save()

# -------------------------------------------------
#  OTP CODE MODEL (NEW)
# -------------------------------------------------
class OtpCode(models.Model):
    """Reliable DB storage for OTP codes."""
    phone = PhoneNumberField(unique=True)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def is_valid(self, code):
        return self.otp_code == code and timezone.now() < self.expires_at

    def __str__(self):
        return f"{self.phone}: {self.otp_code}"

# -------------------------------------------------
#  FILE VALIDATORS
# -------------------------------------------------
def validate_file_extension(value):
    """Allow only safe file types (PDF, JPG, JPEG, PNG)."""
    valid_extensions = [".pdf", ".jpg", ".jpeg", ".png"]
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in valid_extensions:
        raise ValidationError("Unsupported file type. Allowed: PDF, JPG, JPEG, PNG.")


def validate_file_size(value):
    """Restrict uploads to 5 MB maximum."""
    filesize = value.size
    if filesize > 5 * 1024 * 1024:
        raise ValidationError("File too large. Maximum allowed size is 5 MB.")


# -------------------------------------------------
#  SELLER PROFILE (SECURE + VERIFIED KYC)
# -------------------------------------------------
class SellerProfile(models.Model):
    """Verified seller profile with full KYC and store configuration."""

    user = models.OneToOneField(
        'CustomUser',
        on_delete=models.CASCADE,
        related_name='seller_profile'
    )

    # --- Store Identity ---
    store_name = models.CharField(max_length=150, unique=True)
    store_slug = models.SlugField(max_length=160, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)

    store_logo = models.ImageField(
        upload_to="store_logos/",
        validators=[validate_file_extension, validate_file_size],
        help_text="Upload store logo (JPG, JPEG, or PNG only, max 5MB)."
    )
    store_banner = models.ImageField(
        upload_to="store_banners/",
        validators=[validate_file_extension, validate_file_size],
        help_text="Upload store banner (JPG, JPEG, or PNG only, max 5MB)."
    )

    # --- Contact / Support ---
    support_email = models.EmailField(blank=True, null=True)
    support_phone = PhoneNumberField(
        help_text="Business contact number in international format (e.g. +2348012345678)."
    )

    # --- KYC & Documents ---
    business_license = models.FileField(
        upload_to="seller_docs/",
        validators=[validate_file_extension, validate_file_size],
        blank=True,
        null=True,
        help_text="Optional business registration certificate (PDF, JPG, PNG, ≤5MB)."
    )
    id_document = models.FileField(
        upload_to="seller_docs/",
        validators=[validate_file_extension, validate_file_size],
        help_text="Government-issued ID (PDF, JPG, PNG, ≤5MB)."
    )

    # --- Bank Details ---
    bank_account_name = models.CharField(
        max_length=150,
        help_text="Exact name registered with your bank."
    )
    bank_account_number = models.CharField(
        max_length=50,
        validators=[RegexValidator(r"^\d{6,20}$", "Enter a valid account number (6–20 digits).")],
        help_text="Your bank account number (digits only)."
    )
    bank_name = models.CharField(
        max_length=150,
        help_text="Name of your bank (e.g., GTBank, Access Bank)."
    )

    # --- Status & Verification ---
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True,
        help_text="Override global commission rate for this seller (e.g. 5.0 for 5%). Leave empty to use global default."
    )
    is_verified = models.BooleanField(default=False)   # ✅ Admin approval flag
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Seller Profile"
        verbose_name_plural = "Seller Profiles"
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.store_name} ({self.user.email})"

    def save(self, *args, **kwargs):
        """Auto-generate slug safely."""
        if not self.store_slug:
            self.store_slug = slugify(f"{self.store_name}-{self.user.id}")
        super().save(*args, **kwargs)

    @property
    def owner_email(self):
        return self.user.email

    @property
    def is_fully_verified(self):
        """
        A seller is 'fully verified' only when:
        - Admin has approved (is_verified=True)
        - All mandatory KYC and bank fields are filled.
        """
        required = [
            self.store_logo,
            self.store_banner,
            self.support_phone,
            self.id_document,
            self.bank_account_name,
            self.bank_account_number,
            self.bank_name,
        ]
        return self.is_verified and all(required)

    @property
    def wallet_balance(self):
        """
        Calculates available funds:
        (Total Earnings from SellerPayout) - (Total Paid/Pending PayoutRequests)
        Using late import to avoid circular dependency.
        """
        from store.models import SellerPayout, PayoutRequest
        from django.db.models import Sum

        total_earned = SellerPayout.objects.filter(seller=self).aggregate(Sum("payable_amount"))["payable_amount__sum"] or 0
        total_withdrawn = PayoutRequest.objects.filter(seller=self, status__in=['pending', 'paid']).aggregate(Sum("amount"))["amount__sum"] or 0
        
        return total_earned - total_withdrawn



# -----------------------------------------------------
#  AUTO-SYNC SIGNALS
# -----------------------------------------------------
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=SellerProfile)
def sync_user_on_seller_update(sender, instance, **kwargs):
    """Auto-sync CustomUser status when SellerProfile changes."""
    user = instance.user
    if instance.is_verified and not user.is_approved_seller:
        user.is_approved_seller = True
        user.is_seller = True
        user.save()
    elif not instance.is_verified and user.is_approved_seller:
        user.is_approved_seller = False
        user.save()
