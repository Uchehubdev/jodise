from django import forms
from django.contrib.auth import get_user_model
from .models import DeliveryPartner

User = get_user_model()

class DeliverySignupForm(forms.ModelForm):
    # User fields
    first_name = forms.CharField(max_length=100, required=True)
    last_name = forms.CharField(max_length=100, required=True)
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    phone = forms.CharField(max_length=20, required=True)

    class Meta:
        model = DeliveryPartner
        fields = ['vehicle_type', 'license_number', 'id_document', 'profile_photo']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

    def save(self, commit=True):
        # 1. Create User
        user = User.objects.create_user(
            email=self.cleaned_data['email'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name'],
            password=self.cleaned_data['password'],
            phone=self.cleaned_data['phone']
        )
        # 2. Create DeliveryPartner profile linked to User
        partner = super().save(commit=False)
        partner.user = user
        if commit:
            partner.save()
        return partner
