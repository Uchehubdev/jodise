import random
from datetime import timedelta
from decouple import config
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.utils import timezone
from django.urls import reverse
from django.conf import settings

from .forms import CustomRegistrationForm, CustomLoginForm
from .models import CustomUser, OtpCode

# ----------------------------
# Twilio OTP Setup
# ----------------------------
try:
    from twilio.rest import Client
    TWILIO_SID = config("TWILIO_ACCOUNT_SID", default=None)
    TWILIO_TOKEN = config("TWILIO_AUTH_TOKEN", default=None)
    TWILIO_PHONE = config("TWILIO_PHONE_NUMBER", default=None)
    twilio_client = Client(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID and TWILIO_TOKEN else None
except Exception:
    twilio_client = None


def generate_otp():
    """Generate a random 6-digit OTP"""
    return str(random.randint(100000, 999999))

def send_otp_code(phone):
    """
    Send OTP via Twilio or fallback print.
    Saves OTP to Database for reliability.
    """
    otp = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=5)

    # ✅ Save to Database (replaces in-memory store)
    OtpCode.objects.update_or_create(
        phone=str(phone),
        defaults={"otp_code": otp, "expires_at": expires_at}
    )

    if twilio_client and TWILIO_PHONE:
        try:
            twilio_client.messages.create(
                body=f"Your Jodise verification code is {otp}",
                from_=TWILIO_PHONE,
                to=str(phone)
            )
        except Exception as e:
            print("Twilio error:", e)
    
    # Always print for DEV/Debug regardless of Twilio status
    print("\n" + "="*50)
    print(f"🔑 JODISE OTP: {otp}")
    print(f"📱 Phone: {phone}")
    print("="*50 + "\n")
    
    return otp

def verify_otp_code(phone, otp):
    """Check OTP validity against Database"""
    try:
        record = OtpCode.objects.get(phone=str(phone))
        if record.is_valid(otp):
            record.delete()  # Consumed
            return True
    except OtpCode.DoesNotExist:
        pass
    
    return False


# ==============================================================
# USER AUTH VIEWS
# ==============================================================

@csrf_exempt
def send_otp_ajax(request):
    """AJAX endpoint to send OTP"""
    if request.method == "POST":
        phone = request.POST.get("phone")
        if not phone:
            return JsonResponse({"status": "error", "message": "Phone required."})
        send_otp_code(phone)
        return JsonResponse({"status": "ok", "message": f"OTP sent to {phone}"})
    return JsonResponse({"status": "error", "message": "Invalid request method."})


@csrf_exempt
@require_POST
def verify_otp_ajax(request):
    """AJAX endpoint to verify OTP"""
    phone = request.POST.get("phone")
    otp = request.POST.get("otp")

    if not phone or not otp:
        return JsonResponse({"status": "error", "message": "Missing phone or OTP"})

    if verify_otp_code(phone, otp):
        request.session["otp_verified_phone"] = phone
        return JsonResponse({"status": "verified"})
    return JsonResponse({"status": "invalid"})


# ------------------------------------------------------------
# REGISTER VIEW
# ------------------------------------------------------------
from django.contrib.auth import get_backends

def register_view(request):
    """Register a new user — requires verified phone via OTP"""
    if request.user.is_authenticated:
        print("🟢 [DEBUG] User already authenticated → redirecting to dashboard")
        return redirect("dashboard")

    form = CustomRegistrationForm(request.POST or None)
    phone = request.POST.get("phone")

    if request.method == "POST":
        print("🟡 [DEBUG] Received POST data:", request.POST.dict())

        # ✅ Step 1: Ensure OTP verification
        verified_phone = request.session.get("otp_verified_phone")
        print("🟢 [DEBUG] Session verified phone:", verified_phone)

        # Allow skipping check ONLY if verified_phone matches submitted phone
        # (This prevents user from verifying one number and registering another)
        if not verified_phone or str(verified_phone) != str(phone):
            print("❌ [DEBUG] OTP verification failed:", verified_phone, "!=", phone)
            messages.error(request, "Please verify your phone number before completing registration.")
            return render(request, "accounts/register.html", {"form": form})

        # ✅ Step 2: Validate registration form
        if form.is_valid():
            print("✅ [DEBUG] Form is valid.")
            user = form.save(commit=False)
            user.phone = verified_phone
            user.phone_verified = True
            user.is_active = True
            user.save()
            print(f"🟢 [DEBUG] User {user.email} created successfully.")

            # ✅ Step 3: Handle multiple authentication backends cleanly
            try:
                backend = get_backends()[0]  # gets first backend in AUTHENTICATION_BACKENDS
                backend_path = f"{backend.__module__}.{backend.__class__.__name__}"
                print(f"🟣 [DEBUG] Using backend: {backend_path}")
                login(request, user, backend=backend_path)
            except IndexError:
                 login(request, user) # Fallback if standard backend

            # ✅ Step 4: Clear session and confirm success
            request.session.pop("otp_verified_phone", None)
            print("🧹 [DEBUG] Session OTP cleared.")

            messages.success(request, f"🎉 Welcome, {user.first_name or 'User'}! Your account has been created successfully.")
            print("✅ [DEBUG] Redirecting to dashboard...")
            return redirect("dashboard")

        # Invalid form case
        print("❌ [DEBUG] Form invalid! Errors below:")
        print(form.errors.as_json())  # <-- shows full error detail in console
        messages.error(request, "Please correct the errors below.")

    else:
        print("ℹ️ [DEBUG] GET request — rendering blank registration form.")

    return render(request, "accounts/register.html", {"form": form})



# ------------------------------------------------------------
# LOGIN VIEW
# ------------------------------------------------------------
def login_view(request):
    """User login with verification enforcement"""
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = CustomLoginForm(request, data=request.POST)
        if form.is_valid():
            email = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(request, email=email, password=password)

            if user:
                # Security Check: Ensure phone is verified
                if not user.phone_verified:
                    request.session["pending_user"] = user.email
                    
                    if user.phone:
                        request.session["pending_phone"] = str(user.phone)
                        send_otp_code(user.phone)
                    else:
                        request.session["pending_phone"] = None
                        messages.warning(request, "Please add a phone number to verify your account.")

                    return redirect("verify_phone")
                
                login(request, user)
                user.last_login_ip = request.META.get("REMOTE_ADDR")
                user.save(update_fields=["last_login_ip"])
                messages.success(request, f"Welcome back, {user.first_name}!")
                return redirect("dashboard")
            else:
                messages.error(request, "Invalid email or password.")
        else:
            messages.error(request, "Invalid form submission.")
    else:
        form = CustomLoginForm()

    return render(request, "accounts/login.html", {"form": form})


# ------------------------------------------------------------
# LOGOUT VIEW
# ------------------------------------------------------------
@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect("login")


# ------------------------------------------------------------
# DASHBOARD VIEW
# ------------------------------------------------------------
@login_required
def dashboard_view(request):
    """User dashboard placeholder"""
    return render(request, "accounts/dashboard.html", {"user": request.user})


# ------------------------------------------------------------
# VERIFY PHONE PAGE (Non-AJAX fallback)
# ------------------------------------------------------------
@csrf_exempt
def verify_phone_view(request):
    """
    Manual verification page (fallback or login intercept).
    """
    phone = request.session.get("pending_phone")
    email = request.session.get("pending_user")

    if not phone or not email:
        # Check if we have email only (missing phone case)
        if email:
             pass 
        else:
            messages.error(request, "Verification session expired.")
            return redirect("login")

    if request.method == "POST":
        # Handle "Change Number"
        if request.POST.get("change_number"):
            new_phone = request.POST.get("new_phone")
            if new_phone:
                # Check if phone is already taken by another user
                if CustomUser.objects.filter(phone=new_phone).exclude(email=email).exists():
                     messages.error(request, "This phone number is already associated with another account.")
                     return redirect("verify_phone")

                try:
                    CustomUser.objects.filter(email=email).update(phone=new_phone, phone_verified=False)
                    request.session["pending_phone"] = new_phone
                    send_otp_code(new_phone)
                    messages.success(request, f"OTP sent to new number: {new_phone}")
                    return redirect("verify_phone")
                except Exception as e:
                     # Fallback if race condition occurs
                     messages.error(request, "Error updating phone number. It may be in use.")
                     return redirect("verify_phone")

        # Handle OTP Verification
        otp = request.POST.get("otp")
        if otp:
            if not phone:
                 # If trying to verify but session has no phone, they must add one first
                 messages.error(request, "Please add a phone number first.")
            elif verify_otp_code(phone, otp):
                CustomUser.objects.filter(email=email).update(phone=phone, phone_verified=True)
                request.session.pop("pending_user", None)
                request.session.pop("pending_phone", None)
                messages.success(request, "✅ Phone verified successfully! Please log in.")
                return redirect("login")
            else:
                messages.error(request, "❌ Invalid or expired OTP.")

    return render(request, "accounts/verify_phone.html", {"phone": phone})


# ------------------------------------------------------------
# BECOME A SELLER
# ------------------------------------------------------------
from .forms import SellerApplicationForm
from .models import SellerProfile

@login_required
def become_seller_view(request):
    """
    Allows a verified user to submit KYC and become a seller.
    Application stays pending until admin approval.
    """
    user = request.user

    # --- Security: Must verify phone before proceeding ---
    if not user.phone_verified:
        messages.error(request, "Please verify your phone number first.")
        return redirect("verify_phone")

    # --- Prevent re-application if seller profile exists ---
    existing_profile = getattr(user, "seller_profile", None)
    if existing_profile:
        if existing_profile.is_verified:
            messages.info(request, "✅ You are already an approved seller.")
        else:
            messages.info(request, "⏳ Your seller application is under review.")
        return redirect("dashboard")

    # --- Handle KYC Form Submission ---
    if request.method == "POST":
        form = SellerApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            seller_profile = form.save(commit=False)
            seller_profile.user = user
            seller_profile.is_verified = False  # wait for admin
            seller_profile.is_active = True
            seller_profile.save()

            # Update user flags
            user.is_seller = True
            user.is_approved_seller = False
            user.save()

            messages.success(
                request,
                "✅ Your seller application has been submitted successfully! "
                "Our team will review and approve it soon."
            )
            return redirect("dashboard")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = SellerApplicationForm()

    return render(request, "accounts/become_seller.html", {"form": form})
