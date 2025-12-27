from django import forms
from django.contrib.auth.forms import AuthenticationForm
from phonenumber_field.formfields import PhoneNumberField
from .models import CustomUser


# -------------------------------------------------------------------
# USER REGISTRATION FORM
# -------------------------------------------------------------------
class CustomRegistrationForm(forms.ModelForm):
    """
    Handles new user registration with full international phone number format.
    Works seamlessly with OTP verification flow.
    """

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter password",
                "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm password",
                "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
            }
        ),
    )

    phone = PhoneNumberField(
        label="Phone (International Format)",
        region=None,
        widget=forms.TextInput(
            attrs={
                "placeholder": "+2348012345678",
                "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
            }
        ),
        error_messages={"invalid": "Enter a valid international phone number."},
    )

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "country",
            "state",
            "city",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "placeholder": "First Name",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "placeholder": "Last Name",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "Email Address",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "country": forms.Select(
                attrs={
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "state": forms.TextInput(
                attrs={
                    "placeholder": "State",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "city": forms.TextInput(
                attrs={
                    "placeholder": "City",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get("phone")
        if CustomUser.objects.filter(phone=phone).exists():
            raise forms.ValidationError("This phone number is already registered.")
        return phone

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        """Saves user securely with phone unverified (for OTP flow)."""
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.phone_verified = False
        if commit:
            user.save()
        return user


# -------------------------------------------------------------------
# LOGIN FORM
# -------------------------------------------------------------------
class CustomLoginForm(AuthenticationForm):
    """
    Login form using email and password.
    Used in login_view for authentication.
    """

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "Enter your email",
                "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
            }
        ),
    )

    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your password",
                "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
            }
        ),
    )




# -------------------------------------------------------------------
# SELLER APPLICATION FORM (KYC)
# -------------------------------------------------------------------
from .models import SellerProfile

class SellerApplicationForm(forms.ModelForm):
    """
    Handles seller KYC and storefront setup.
    Requires admin approval before activation.
    """

    class Meta:
        model = SellerProfile
        fields = [
            "store_name",
            "description",
            "store_logo",
            "store_banner",
            "support_email",
            "support_phone",
            "business_license",
            "id_document",
            "bank_account_name",
            "bank_account_number",
            "bank_name",
        ]

        widgets = {
            "store_name": forms.TextInput(
                attrs={
                    "placeholder": "Your Store Name",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "placeholder": "Describe your store and what you sell...",
                    "rows": 4,
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "support_email": forms.EmailInput(
                attrs={
                    "placeholder": "Customer support email (optional)",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "support_phone": forms.TextInput(
                attrs={
                    "placeholder": "+2348012345678",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "bank_account_name": forms.TextInput(
                attrs={
                    "placeholder": "Account Name",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "bank_account_number": forms.TextInput(
                attrs={
                    "placeholder": "Account Number",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
            "bank_name": forms.TextInput(
                attrs={
                    "placeholder": "Bank Name",
                    "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
                }
            ),
      
        }

    def clean(self):
        cleaned_data = super().clean()
        required_fields = [
            "store_logo",
            "store_banner",
            "support_phone",
            "id_document",
            "bank_account_name",
            "bank_account_number",
            "bank_name",
        ]
        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, "This field is required for KYC verification.")
        return cleaned_data
