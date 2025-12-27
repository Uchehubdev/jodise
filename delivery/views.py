from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from .models import DeliveryPartner, DeliveryOrder, DeliveryTrackingHistory
from .models import DeliveryPartner, DeliveryOrder, DeliveryTrackingHistory
from .forms import DeliverySignupForm  # We will create this form next
from services.notifications import Notifier  # 📧 Notification Service

# ==========================================
# 🔒 Permissions
# ==========================================
def is_delivery_partner(user):
    return user.is_authenticated and hasattr(user, 'delivery_profile')

# ==========================================
# 🚚 AUTH
# ==========================================
def delivery_signup(request):
    if request.user.is_authenticated:
        return redirect('delivery_dashboard')
    
    if request.method == 'POST':
        form = DeliverySignupForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            # Log the user in or redirect to login
            messages.success(request, "Delivery partner account created! Please log in.")
            return redirect('delivery_login')
    else:
        form = DeliverySignupForm()
    
    return render(request, 'delivery/signup.html', {'form': form})

def delivery_login(request):
    # Reuse accounts login or have a specific one? 
    # For now, redirect to main login with a next param
    return redirect('/accounts/login/?next=/delivery/dashboard/')

# ==========================================
# 📋 DASHBOARD
# ==========================================
@login_required
@user_passes_test(is_delivery_partner)
def delivery_dashboard(request):
    partner = request.user.delivery_profile
    active_orders = DeliveryOrder.objects.filter(delivery_partner=partner, status__in=['assigned', 'in_transit'])
    completed_orders = DeliveryOrder.objects.filter(delivery_partner=partner, status='delivered').count()
    
    return render(request, 'delivery/dashboard.html', {
        'partner': partner,
        'active_orders': active_orders,
        'completed_count': completed_orders
    })

# ==========================================
# 📦 ORDERS
# ==========================================
@login_required
@user_passes_test(is_delivery_partner)
def available_orders(request):
    """View orders that are paid but not assigned to any driver."""
    orders = DeliveryOrder.objects.filter(status='pending', delivery_partner__isnull=True)
    return render(request, 'delivery/available_orders.html', {'orders': orders})

@login_required
@user_passes_test(is_delivery_partner)
def accept_order(request, pk):
    order = get_object_or_404(DeliveryOrder, pk=pk, status='pending', delivery_partner__isnull=True)
    partner = request.user.delivery_profile
    
    if not partner.is_verified or not partner.is_available:
        messages.error(request, "You must be verified and available to accept orders.")
        return redirect('delivery_dashboard')
    
    order.delivery_partner = partner
    order.status = 'assigned'
    order.assigned_at = timezone.now()
    order.save()
    
    # Log history
    DeliveryTrackingHistory.objects.create(
        delivery=order,
        status='assigned',
        note=f"Order accepted by {partner.user.first_name}"
    )
    
    # Mark driver as busy? Optional, depends on logic.
    # partner.is_available = False
    # partner.save()

    messages.success(request, f"Order {order.order_code} accepted!")
    return redirect('delivery_dashboard')

@login_required
@user_passes_test(is_delivery_partner)
def update_delivery_status(request, pk):
    order = get_object_or_404(DeliveryOrder, pk=pk, delivery_partner=request.user.delivery_profile)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        note = request.POST.get('note', '')
        
        if new_status in ['in_transit', 'delivered', 'failed']:
            order.status = new_status
            order.save()
            
            DeliveryTrackingHistory.objects.create(
                delivery=order,
                status=new_status,
                note=note
            )
            
            # 📧 NOTIFICATIONS
            if new_status == 'in_transit':
                Notifier.notify_order_shipped(order)
            elif new_status == 'delivered':
                Notifier.notify_order_delivered(order)
            
            if new_status == 'delivered':
                # Link back to main store Order if necessary or trigger payout logic
                pass
                
            messages.success(request, f"Status updated to {new_status}")
            
    return redirect('delivery_dashboard')
