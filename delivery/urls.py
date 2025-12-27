from django.urls import path
from . import views

urlpatterns = [
    # 🚚 AUTH
    path('register/', views.delivery_signup, name='delivery_signup'),
    path('login/', views.delivery_login, name='delivery_login'),

    # 📋 DASHBOARD
    path('dashboard/', views.delivery_dashboard, name='delivery_dashboard'),

    # 📦 ORDERS
    path('available/', views.available_orders, name='available_orders'),
    path('order/<int:pk>/accept/', views.accept_order, name='accept_order'),
    path('order/<int:pk>/update/', views.update_delivery_status, name='update_delivery_status'),
]
