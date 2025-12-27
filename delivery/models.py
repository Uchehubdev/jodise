from django.db import models
from django.utils import timezone
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from accounts.models import CustomUser


class DeliveryPartner(models.Model):
    """Registered delivery personnel or companies."""

    VEHICLE_CHOICES = [
        ('bike', 'Bike'),
        ('car', 'Car'),
        ('van', 'Van'),
        ('truck', 'Truck'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='delivery_profile')
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_CHOICES, default='bike')
    license_number = models.CharField(max_length=100, blank=True, null=True)
    profile_photo = models.ImageField(upload_to='delivery_profiles/', blank=True, null=True)
    id_document = models.FileField(upload_to='delivery_docs/', blank=True, null=True)

    # GPS and availability
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    is_available = models.BooleanField(default=True)

    # Verification & status
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    joined_on = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.first_name} ({self.vehicle_type})"

    def mark_unavailable(self):
        self.is_available = False
        self.save(update_fields=['is_available'])

    def mark_available(self):
        self.is_available = True
        self.save(update_fields=['is_available'])


class DeliveryOrder(models.Model):
    """System-managed delivery task automatically assigned to a driver."""

    STATUS_CHOICES = [
        ('pending', 'Pending Assignment'),
        ('assigned', 'Assigned'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed Delivery'),
        ('cancelled', 'Cancelled'),
    ]

    order_code = models.CharField(max_length=20, unique=True)
    buyer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='delivery_orders')
    delivery_partner = models.ForeignKey(
        DeliveryPartner, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders'
    )

    # Delivery route
    pickup_address = models.CharField(max_length=255)
    pickup_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    pickup_longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    delivery_address = models.CharField(max_length=255)
    delivery_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    delivery_longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    delivery_country = CountryField(blank=True, null=True)
    contact_phone = PhoneNumberField(blank=True, null=True)

    # Tracking
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    tracking_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    delivered_photo = models.ImageField(upload_to='delivery_proofs/', blank=True, null=True)

    assigned_at = models.DateTimeField(blank=True, null=True)
    estimated_delivery = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.estimated_delivery:
            # Simple algo: Created + 2 days
            self.estimated_delivery = timezone.now() + timezone.timedelta(days=2)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Delivery {self.order_code} - {self.status}"

    def assign_available_driver(self):
        """Automatically assigns the first verified, available delivery partner."""
        available_driver = DeliveryPartner.objects.filter(
            is_available=True, is_verified=True, is_active=True
        ).first()

        if available_driver:
            self.delivery_partner = available_driver
            self.status = 'assigned'
            self.assigned_at = timezone.now()
            available_driver.is_available = False
            available_driver.save()
            self.save()

            DeliveryTrackingHistory.objects.create(
                delivery=self,
                status='assigned',
                note=f"Driver {available_driver.user.first_name} assigned automatically."
            )
            return available_driver
        else:
            DeliveryTrackingHistory.objects.create(
                delivery=self,
                status='pending',
                note='No available delivery partner found at the moment.'
            )
            return None


class DeliveryTrackingHistory(models.Model):
    """Logs every location or status update for a delivery."""
    delivery = models.ForeignKey(DeliveryOrder, on_delete=models.CASCADE, related_name='tracking_history')
    status = models.CharField(max_length=50)
    note = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.delivery.order_code} → {self.status} at {self.timestamp:%Y-%m-%d %H:%M}"
