from django.shortcuts import redirect
from django.urls import reverse

class PhoneVerificationMiddleware:
    pass
    # """Redirect users without verified phone to verification page."""

    # def __init__(self, get_response):
    #     self.get_response = get_response

    # def __call__(self, request):
    #     if request.user.is_authenticated:
    #         if not request.user.phone_verified:
    #             allowed_paths = [
    #                 reverse('verify_phone'),
    #                 reverse('send_otp'),
    #                 reverse('logout'),
    #             ]
    #             # allow media/static/admin access
    #             if not any(request.path.startswith(p) for p in allowed_paths) and not request.path.startswith('/admin'):
    #                 return redirect('verify_phone')
    #     return self.get_response(request)
