import json, hashlib
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.urls import reverse
from django.utils import timezone
from django.db.models import Sum, Q
from django.conf import settings

from accounts.utils.paystack import PaystackManager
from .models import (
    Product, ProductImage, Order, OrderItem, PaymentTransaction,
    RefundRequest, Shipment, ProductInsight, SellerPayout,
    PromoCode, MarketplaceSetting
)
from delivery.models import DeliveryOrder  # 🚚 Link to Delivery App
from services.notifications import Notifier  # 📧 Notification Service
from services.payment import PaymentService
from services.inventory import InventoryService
from services.invoice import InvoiceService
from .forms import (
    ProductForm, ProductImageForm, CheckoutForm,
    RefundRequestForm, ShipmentForm, PromoCodeForm
)
from accounts.models import SellerProfile


# ===========================================================
# 🔒 Access Control
# ===========================================================
def is_verified_seller(user):
    return hasattr(user, "seller_profile") and user.seller_profile.is_verified


def forbidden(request):
    return HttpResponseForbidden("You are not authorized to access this resource.")


# ===========================================================
# 🏠 HOME + SEARCH
# ===========================================================
from .models import Category, Product


def home(request):
    featured = Product.objects.filter(is_active=True, is_featured=True)[:10]
    latest = Product.objects.filter(is_active=True).order_by('-created_at')[:12]
    categories = Category.objects.filter(is_active=True)[:8]
    return render(request, 'store/home.html', {
        'featured': featured,
        'latest': latest,
        'categories': categories,
    })


def search_products(request):
    query = request.GET.get("q", "")
    min_price = request.GET.get("min")
    max_price = request.GET.get("max")

    products = Product.objects.filter(is_active=True)
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)

    return render(request, "store/search_results.html", {"products": products, "query": query})


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk, is_active=True)
    # Record view logic here if needed (e.g. ProductInsight)
    return render(request, "store/product_detail.html", {"product": product})


# ===========================================================
# 🛒 CART MANAGEMENT
# ===========================================================
@login_required
def view_cart(request):
    order, _ = Order.objects.get_or_create(buyer=request.user, status="pending")
    items = order.items.select_related("product", "seller")
    subtotal = sum(i.subtotal for i in items)
    vat_rate = MarketplaceSetting.current().vat_rate
    vat = (subtotal * vat_rate) / 100
    return render(request, "store/cart.html", {
        "order": order, "items": items, "subtotal": subtotal, "vat": vat
    })


@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    if product.stock <= 0:
        messages.warning(request, "This product is out of stock.")
        return redirect("store_home")

    order, _ = Order.objects.get_or_create(buyer=request.user, status="pending")
    item, created = OrderItem.objects.get_or_create(order=order, product=product, seller=product.seller)
    if not created:
        item.quantity += 1
    item.unit_price = product.price
    item.subtotal = item.unit_price * item.quantity
    item.save()
    messages.success(request, f"{product.name} added to your cart.")
    return redirect("view_cart")


@login_required
def remove_from_cart(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order__buyer=request.user, order__status="pending")
    item.delete()
    messages.info(request, "Item removed from cart.")
    return redirect("view_cart")


@login_required
def update_cart_quantity(request, item_id):
    """AJAX secure cart quantity update."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    qty = int(request.POST.get("qty", 1))
    item = get_object_or_404(OrderItem, id=item_id, order__buyer=request.user, order__status="pending")
    if qty < 1:
        item.delete()
    else:
        item.quantity = qty
        item.subtotal = item.unit_price * qty
        item.save()
    return JsonResponse({"success": True, "subtotal": float(item.subtotal)})


# ===========================================================
# ❤️ WISHLIST
# ===========================================================
@login_required
def toggle_wishlist(request, product_id):
    wishlist = request.session.get("wishlist", [])
    if product_id in wishlist:
        wishlist.remove(product_id)
        messages.info(request, "Removed from wishlist.")
    else:
        wishlist.append(product_id)
        messages.success(request, "Added to wishlist.")
    request.session["wishlist"] = wishlist
    return redirect("view_wishlist")


@login_required
def view_wishlist(request):
    ids = request.session.get("wishlist", [])
    products = Product.objects.filter(id__in=ids, is_active=True)
    return render(request, "store/wishlist.html", {"products": products})


# ===========================================================
# 🧑‍🌾 SELLER PRODUCT CRUD
# ===========================================================
@login_required
@user_passes_test(is_verified_seller)
def add_product(request):
    """Create a new product."""
    seller = request.user.seller_profile
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.seller = seller
        product.save()
        messages.success(request, "✅ Product added successfully.")
        return redirect("seller_dashboard")
    return render(request, "store/product_form.html", {"form": form})


@login_required
@user_passes_test(is_verified_seller)
def edit_product(request, pk):
    """Edit product (only owner can)."""
    product = get_object_or_404(Product, pk=pk, seller=request.user.seller_profile)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "✅ Product updated successfully.")
        return redirect("seller_dashboard")
    return render(request, "store/product_form.html", {"form": form, "edit_mode": True})


@login_required
@user_passes_test(is_verified_seller)
def delete_product(request, pk):
    """Secure delete (only product owner)."""
    product = get_object_or_404(Product, pk=pk, seller=request.user.seller_profile)
    if request.method == "POST":
        product.delete()
        messages.warning(request, "🗑️ Product deleted successfully.")
        return redirect("seller_dashboard")
    return render(request, "store/confirm_delete.html", {"product": product})


@login_required
@user_passes_test(is_verified_seller)
def upload_product_image(request, product_id):
    """Upload product image."""
    product = get_object_or_404(Product, id=product_id, seller=request.user.seller_profile)
    form = ProductImageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        img = form.save(commit=False)
        img.product = product
        img.save()
        messages.success(request, "Image uploaded successfully.")
        return redirect("seller_dashboard")
    return render(request, "store/product_image_form.html", {"form": form, "product": product})


# ===========================================================
# 💳 CHECKOUT + PAYSTACK
# ===========================================================
@login_required
@transaction.atomic
def checkout_view(request):
    order = get_object_or_404(Order, buyer=request.user, status="pending")
    items = order.items.select_related("product", "seller")

    if not items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect("store_home")

    checkout_form = CheckoutForm(request.POST or None)
    promo_form = PromoCodeForm(request.POST or None)

    if request.method == "POST":
        if promo_form.is_valid():
            promo = promo_form.cleaned_data["code"]
            discount = (order.subtotal * promo.discount_percent) / 100
            order.subtotal -= discount
            promo.use()
            messages.success(request, f"Promo code applied: {promo.discount_percent}% off")

        if checkout_form.is_valid():
            order.delivery_method = checkout_form.cleaned_data["delivery_method"]
            order.calculate_totals()

            # Determine Gateway
            config = MarketplaceSetting.objects.first()
            gateway = config.active_gateway if config else 'paystack'
            
            payment = PaymentTransaction.objects.create(
                order=order,
                buyer=request.user,
                reference=str(order.reference),
                amount=order.total,
                status="pending",
                provider=gateway
            )

            if gateway == 'paystack':
                paystack = PaystackManager(request.user.email)
                callback_url = request.build_absolute_uri(reverse("verify_payment"))
                redirect_url = paystack.charge(
                    amount=order.total,
                    metadata={"order_ref": order.reference, "buyer": request.user.email},
                    callback_url=callback_url,
                )
                if redirect_url:
                    return redirect(redirect_url)
            
            elif gateway == 'stripe':
                success_url = request.build_absolute_uri(reverse("verify_payment"))
                cancel_url = request.build_absolute_uri(reverse("checkout_view"))
                redirect_url = PaymentService.create_stripe_session(order, success_url, cancel_url)
                if redirect_url:
                    return redirect(redirect_url)

            messages.error(request, "Payment initialization failed.")

    # Get Config for Template
    config = MarketplaceSetting.objects.first()
    context = {
        "form": checkout_form, "promo_form": promo_form,
        "order": order, "items": items,
        "active_gateway": config.active_gateway if config else 'paystack',
        "paystack_key": config.paystack_public_key if config else '',
        "stripe_key": config.stripe_publishable_key if config else ''
    }
    return render(request, "store/checkout.html", context)


# ===========================================================
# 🔁 PAYMENT VERIFICATION
# ===========================================================
@login_required
@csrf_exempt
def verify_payment(request):
    # Support both 'reference' (Paystack) and 'session_id' (Stripe)
    reference = request.GET.get("reference") or request.POST.get("reference")
    session_id = request.GET.get("session_id")

    if not reference and not session_id:
        return HttpResponseForbidden("Missing payment reference or session ID")

    # If Stripe, the reference is currently the session_ID, but we passed order ref in metadata
    # But wait, we need to verify first to get the Order Ref back if we didn't store session_id in DB yet.
    # Actually, verify_payment(reference) in Service handles the dispatch.
    
    verify_ref = reference or session_id
    success, amount, data = PaymentService.verify_payment(verify_ref)
    
    if success:
        # If Stripe, object is Session, locate order via metadata
        if session_id:
             order_ref = data.get('client_reference_id') or data.get('metadata', {}).get('order_ref')
             # We might need to find the payment transaction or create one
             payment, _ = PaymentTransaction.objects.get_or_create(
                 ref=verify_ref, # Store session ID as ref for Stripe
                 defaults={'amount': amount, 'status': 'success', 'provider': 'stripe'}
             )
             # Link order if not linked (e.g. if we just created it)
             if not payment.order_id:
                  payment.order = get_object_or_404(Order, reference=order_ref)
                  payment.buyer = payment.order.buyer
                  payment.save()
        else:
             payment = get_object_or_404(PaymentTransaction, reference=reference)

        try:
            with transaction.atomic():
                # 2. Idempotent Transaction Record
                PaymentService.record_transaction(payment.order, reference, amount)
                
                # 3. Reserve Stock (Atomic)
                items_data = [{'product': item.product, 'quantity': item.quantity} for item in payment.order.items.all()]
                InventoryService.reserve_stock(items_data)

                order = payment.order
                order.status = "paid"
                order.save()

                # 4. Seller Payouts
                for item in order.items.all():
                    # Calculate Commission (Seller Override > Global)
                    global_comm = MarketplaceSetting.objects.first().commission_rate
                    seller_comm = item.seller.commission_rate if item.seller.commission_rate is not None else global_comm
                    
                    item.calculate_line(commission_rate=seller_comm)
                    
                    SellerPayout.objects.create(
                        seller=item.seller, order=order,
                        total_earned=item.subtotal,
                        vat_deducted=item.vat,
                        commission_deducted=item.commission,
                        payable_amount=item.seller_earnings,
                    )

                # 5. Delivery Order
                DeliveryOrder.objects.get_or_create(
                    order_code=order.reference,
                    defaults={
                        'buyer': order.buyer,
                        'pickup_address': "Jodise Warehouse / Seller Location",
                        'delivery_address': order.buyer.full_address,
                        'delivery_country': order.buyer.country,
                        'contact_phone': order.buyer.phone,
                        'tracking_number': order.reference,
                        'status': 'pending'
                    }
                )

                # 6. Notify
                Notifier.notify_order_placed(order)

            messages.success(request, "✅ Payment verified successfully.")
            return redirect("order_success", reference=order.reference)
        
        except Exception as e:
            messages.warning(request, f"Payment verified but stock issue: {e}. Contact support.")
            return redirect("order_success", reference=payment.order.reference)
            
    else:
        payment.status = "failed"


@login_required
def order_success(request, reference):
    order = get_object_or_404(Order, reference=reference, buyer=request.user)
    return render(request, "store/order_success.html", {"order": order})


@login_required
def download_invoice(request, reference):
    order = get_object_or_404(Order, reference=reference, buyer=request.user)
    return InvoiceService.generate_invoice_pdf(order)


def track_order(request):
    """Public tracking page."""
    tracking_number = request.GET.get('tracking_number')
    delivery = None
    if tracking_number:
        # Import inside to avoid circular deps if needed, or best at top
        from delivery.models import DeliveryOrder
        delivery = DeliveryOrder.objects.filter(tracking_number=tracking_number).prefetch_related('tracking_history').first()
    
    return render(request, 'store/tracking.html', {
        'tracking_number': tracking_number,
        'delivery': delivery
    })


# ===========================================================
# 🌐 PAYSTACK WEBHOOK
# ===========================================================
@csrf_exempt
@require_POST
def paystack_webhook(request):
    secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    signature = request.headers.get("x-paystack-signature")
    if not secret or not signature:
        return HttpResponseForbidden("Unauthorized")

    computed = hashlib.sha512(request.body + secret.encode()).hexdigest()
    if signature != computed:
        return HttpResponseForbidden("Invalid signature")

    event = json.loads(request.body.decode("utf-8"))
    event_type = event.get("event")
    data = event.get("data", {})

    if event_type == "charge.success":
        reference = data.get("reference")
        payment = PaymentTransaction.objects.filter(reference=reference).first()
        if payment and payment.status != "success":
            with transaction.atomic():
                payment.status = "success"
                payment.gateway_response = data
                payment.save()
                order = payment.order
                order.status = "paid"
                order.save()
                # 4. Seller Payouts
                for item in order.items.all():
                    # Calculate Commission (Seller Override > Global)
                    global_comm = MarketplaceSetting.objects.first().commission_rate
                    seller_comm = item.seller.commission_rate if item.seller.commission_rate is not None else global_comm

                    item.calculate_line(commission_rate=seller_comm)
                    
                    SellerPayout.objects.create(
                        seller=item.seller, order=order,
                        total_earned=item.subtotal,
                        vat_deducted=item.vat,
                        commission_deducted=item.commission,
                        payable_amount=item.seller_earnings,
                    )
                
                # 🚚 AUTOMATIC DELIVERY ORDER CREATION (Webhook)
                if not DeliveryOrder.objects.filter(order_code=order.reference).exists():
                    DeliveryOrder.objects.create(
                        order_code=order.reference,
                        buyer=order.buyer,
                        pickup_address="Jodise Warehouse / Seller Location",
                        delivery_address=order.buyer.full_address,
                        delivery_country=order.buyer.country,
                        contact_phone=order.buyer.phone,
                        tracking_number=order.reference,
                        status='pending'
                    )
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '') 
    # In production, fetching from DB if configurable would be nice, 
    # but webhooks often need defined secrets in code/env for security.
    
    # Actually, let's try to get it from settings or we can't verify.
    if not endpoint_secret:
         # If not set, maybe skip verification or log warning (Insecure for production)
         return HttpResponseForbidden("Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        return HttpResponseForbidden("Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        return HttpResponseForbidden("Invalid signature")

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        # Fulfill the order...
        # We can reuse similar logic to verify_payment or just trust the event?
        # Ideally, we call a service method to 'fulfill_order(reference)'
        pass 
        # For now, since verify_payment is called on success_url, 
        # we might just use this for strictly background updates if user closes tab.
        
    return JsonResponse({'status': 'success'})


# ===========================================================
# 🚚 SHIPMENT & REFUND
# ===========================================================
@login_required
@user_passes_test(is_verified_seller)
def manage_shipment(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    shipment, _ = Shipment.objects.get_or_create(order=order)
    form = ShipmentForm(request.POST or None, instance=shipment)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Shipment details updated.")
        return redirect("seller_dashboard")
    return render(request, "store/shipment_form.html", {"form": form, "order": order})


@login_required
def request_refund(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order__buyer=request.user)
    form = RefundRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        refund = form.save(commit=False)
        refund.order_item = item
        refund.save()
        messages.info(request, "Refund request submitted successfully.")
        return redirect("my_orders")
    return render(request, "store/refund_form.html", {"form": form, "item": item})


# ===========================================================
# 📊 SELLER DASHBOARD & INSIGHTS
# ===========================================================
@login_required
@user_passes_test(is_verified_seller)
def seller_dashboard(request):
    seller = request.user.seller_profile
    products = seller.products.all()
    
    # 📊 KPI: Total Sales & Earnings
    payouts = seller.payouts.all()
    total_earnings = payouts.aggregate(Sum("payable_amount"))["payable_amount__sum"] or 0
    total_orders = payouts.count()
    
    # 📉 KPI: Recent Performance (Last 30 Days)
    last_month = timezone.now() - timezone.timedelta(days=30)
    month_earnings = payouts.filter(created_at__gte=last_month).aggregate(Sum("payable_amount"))["payable_amount__sum"] or 0
    
    # 📦 KPI: Order Status
    pending_orders = OrderItem.objects.filter(seller=seller, order__status='paid', shipment__isnull=True).count()
    
    # ⚠️ KPI: Low Stock (Less than 5)
    low_stock_count = products.filter(stock__lt=5).count()

    # Recent Data for Table
    recent_payouts = payouts.order_by("-created_at")[:5]
    recent_products = products.order_by("-created_at")[:5]

    return render(request, "store/seller_dashboard.html", {
        "seller": seller,
        "total_earnings": total_earnings,
        "month_earnings": month_earnings,
        "total_orders": total_orders,
        "pending_shipments": pending_orders,
        "low_stock_count": low_stock_count,
        "recent_payouts": recent_payouts,
        "recent_products": recent_products,
        "products_count": products.count()
    })


@login_required
@user_passes_test(is_verified_seller)
def product_insights(request):
    seller = request.user.seller_profile
    insights = ProductInsight.objects.filter(product__seller=seller).select_related("product")
    return render(request, "store/insights.html", {"insights": insights})


@login_required
@user_passes_test(is_verified_seller)
def seller_settings(request):
    """Allow seller to update profile and bank details."""
    seller = request.user.seller_profile
    # Import form inside to avoid circular deps if needed, or check top-level
    from .forms import SellerSettingsForm 
    
    form = SellerSettingsForm(request.POST or None, request.FILES or None, instance=seller)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "✅ Store settings updated successfully.")
        return redirect("seller_settings")
        
    return render(request, "store/seller_settings.html", {"form": form, "seller": seller})


@login_required
@user_passes_test(is_verified_seller)
def request_payout(request):
    seller = request.user.seller_profile
    balance = seller.wallet_balance
    
    if request.method == "POST":
        amount = Decimal(request.POST.get("amount", 0))
        if amount <= 0:
            messages.error(request, "Invalid amount.")
        elif amount > balance:
            messages.error(request, "Insufficient wallet balance.")
        else:
            # Create Request
            bank_info = f"{seller.bank_name} - {seller.bank_account_number} ({seller.bank_account_name})"
            PayoutRequest.objects.create(
                seller=seller,
                amount=amount,
                bank_details=bank_info
            )
            messages.success(request, "Withdrawal request submitted! 💸")
            return redirect("request_payout")

    # History
    payout_history = PayoutRequest.objects.filter(seller=seller).order_by("-created_at")
    
    return render(request, "store/payout_history.html", {
        "balance": balance,
        "history": payout_history,
        "seller": seller
    })
