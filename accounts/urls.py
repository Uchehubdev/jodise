from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('verify-phone/', views.verify_phone_view, name='verify_phone'),

    # ✅ AJAX OTP endpoints
    path('send-otp-ajax/', views.send_otp_ajax, name='send_otp_ajax'),
    path('verify-otp-ajax/', views.verify_otp_ajax, name='verify_otp_ajax'),

    # Seller
    path('become-seller/', views.become_seller_view, name='become_seller'),
]
