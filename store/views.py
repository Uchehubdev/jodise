# store/views.py
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.utils import paystack as paystack_api

from .forms import ProductForm, ProductImageForm, PromoCodeForm, RefundRequestForm, ShipmentForm
from .models import (
    Category,
    MarketplaceSetting,
    Order,
    OrderItem,
    PaymentTransaction,
    Product,
    ProductInsight,
    RefundRequest,
    SellerPayout,
    Shipment,
    PayoutRequest,
)

try:
    from .forms import DeliveryAddressForm  # type: ignore
except Exception:
    DeliveryAddressForm = None  # type: ignore

logger = logging.getLogger(__name__)

# Optional services (keep store app usable even if these apps/modules are absent)
try:
    from delivery.models import DeliveryOrder  # type: ignore
except Exception:
    DeliveryOrder = None  # type: ignore

try:
    from services.notifications import Notifier  # type: ignore
except Exception:
    Notifier = None  # type: ignore

try:
    from services.inventory import InventoryService  # type: ignore
except Exception:
    InventoryService = None  # type: ignore

try:
    from services.invoice import InvoiceService  # type: ignore
except Exception:
    InvoiceService = None  # type: ignore


# ===========================================================
# Utilities / Helpers
# ===========================================================
def _config():
    """
    Safe config accessor. Returns MarketplaceSetting.current() if available,
    otherwise a dummy object with sane defaults.
    """
    try:
        return MarketplaceSetting.current()
    except Exception:
        class _Dummy:
            currency_symbol = "₦"
            active_gateway = "paystack"
            commission_rate = Decimal("0")
            vat_rate = Decimal("0")
            paystack_public_key = ""
            stripe_publishable_key = ""
            currency = "NGN"

        return _Dummy()


def _money(v) -> Decimal:
    try:
        d = Decimal(str(v))
        if d.is_nan() or d.is_infinite():
            return Decimal("0.00")
        return d
    except Exception:
        return Decimal("0.00")


def _to_kobo(amount: Decimal) -> int:
    try:
        return int((Decimal(str(amount)) * 100).quantize(Decimal("1")))
    except Exception:
        return 0


def _safe_compare_digest(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return False


def _is_verified_seller(user) -> bool:
    sp = getattr(user, "seller_profile", None)
    return bool(sp and getattr(sp, "is_verified", False))


def seller_required(view_func):
    # Keeps your existing login_url behaviour.
    return login_required(user_passes_test(_is_verified_seller, login_url="login")(view_func))


def _get_pending_order(user) -> Order:
    # One pending cart per buyer.
    order, _ = Order.objects.get_or_create(buyer=user, status="pending")
    return order


def _public_order_number(order: Order) -> str:
    """
    Short, stable, non-ugly order number for users (email/UI).
    Example: JOD-7D777EF2
    - Deterministic per order
    - Does not expose raw UUID
    """
    try:
        key = (getattr(settings, "SECRET_KEY", "") or "JODISE").encode("utf-8")
        msg = f"{order.id}:{getattr(order, 'reference', '')}".encode("utf-8")
        token = hmac.new(key, msg, hashlib.sha256).hexdigest().upper()[:8]
        return f"JOD-{token}"
    except Exception:
        ref = str(getattr(order, "reference", "") or "").replace("-", "").upper()
        return f"JOD-{ref[:8] if ref else uuid.uuid4().hex[:8].upper()}"


def _canonical_product_url(product: Product) -> str:
    if hasattr(product, "public_id") and getattr(product, "public_id", None):
        return reverse("product_detail", kwargs={"slug": product.slug, "public_id": product.public_id})
    return reverse("product_detail_legacy", kwargs={"pk": product.pk})


def _ensure_product_insight(product: Product) -> Optional[ProductInsight]:
    try:
        insight, _ = ProductInsight.objects.get_or_create(product=product)
        return insight
    except Exception:
        return None


def _recalc_order_amounts(order: Order) -> Order:
    """
    Recalculate cart line items (unit_price/subtotal) and order totals.
    """
    subtotal = Decimal("0.00")
    items = order.items.select_related("product", "seller").all()

    for item in items:
        if item.product:
            item.unit_price = item.product.price
        item.quantity = int(item.quantity or 1)
        item.subtotal = (item.unit_price or Decimal("0.00")) * item.quantity
        item.save(update_fields=["unit_price", "quantity", "subtotal"])
        subtotal += item.subtotal

    order.subtotal = subtotal
    order.save(update_fields=["subtotal"])
    try:
        order.calculate_totals()
    except Exception:
        logger.exception("order.calculate_totals failed (non-fatal).")
    return order


def _create_or_update_seller_payouts(order: Order) -> None:
    cfg = _config()
    global_comm = getattr(cfg, "commission_rate", Decimal("0")) or Decimal("0")

    for item in order.items.select_related("seller", "product", "seller__user").all():
        if not item.product or not item.seller:
            continue

        seller_profile = item.seller
        seller_user = getattr(seller_profile, "user", None)
        if not seller_user:
            continue

        commission_rate = getattr(seller_profile, "commission_rate", None)
        if commission_rate is None:
            commission_rate = global_comm

        item.unit_price = item.product.price
        item.subtotal = item.unit_price * int(item.quantity or 1)

        try:
            item.calculate_line(commission_rate=commission_rate)
        except Exception:
            logger.exception("OrderItem.calculate_line failed (non-fatal).")

        item.save(update_fields=["unit_price", "subtotal", "commission", "vat", "seller_earnings"])

        payout, _ = SellerPayout.objects.get_or_create(
            order=order,
            seller=seller_user,
            defaults={
                "total_earned": Decimal("0.00"),
                "vat_deducted": Decimal("0.00"),
                "commission_deducted": Decimal("0.00"),
                "payable_amount": Decimal("0.00"),
            },
        )

        payout.total_earned = (payout.total_earned or Decimal("0.00")) + (item.subtotal or Decimal("0.00"))
        payout.vat_deducted = (payout.vat_deducted or Decimal("0.00")) + (item.vat or Decimal("0.00"))
        payout.commission_deducted = (payout.commission_deducted or Decimal("0.00")) + (item.commission or Decimal("0.00"))
        payout.payable_amount = (payout.payable_amount or Decimal("0.00")) + (item.seller_earnings or Decimal("0.00"))
        payout.save(update_fields=["total_earned", "vat_deducted", "commission_deducted", "payable_amount"])


def _reserve_stock_or_fail(order: Order) -> None:
    items = order.items.select_related("product").all()

    if InventoryService and hasattr(InventoryService, "reserve_stock"):
        payload = [{"product": i.product, "quantity": int(i.quantity or 1)} for i in items if i.product]
        InventoryService.reserve_stock(payload)
        return

    for item in items:
        if not item.product:
            continue
        qty = int(item.quantity or 1)
        updated = Product.objects.filter(pk=item.product.pk, stock__gte=qty).update(stock=F("stock") - qty)
        if updated == 0:
            raise ValueError(f"Insufficient stock for {item.product.name}")


def _create_delivery_order(order: Order) -> None:
    if not DeliveryOrder:
        return

    try:
        new_code = str(order.id)
        legacy_code = str(getattr(order, "reference", ""))

        existing = (
            DeliveryOrder.objects.filter(order_code=new_code).first()
            or DeliveryOrder.objects.filter(tracking_number=new_code).first()
            or DeliveryOrder.objects.filter(order_code=legacy_code).first()
            or DeliveryOrder.objects.filter(tracking_number=legacy_code).first()
        )

        payload = {
            "buyer": order.buyer,
            "pickup_address": "Seller Location / Warehouse",
            "delivery_address": getattr(order, "delivery_address", "") or getattr(order.buyer, "full_address", "") or "",
            "delivery_country": getattr(order, "country", "") or getattr(order.buyer, "country", "") or "",
            "contact_phone": getattr(order.buyer, "phone", "") or "",
            "status": getattr(existing, "status", None) or "pending",
        }

        if existing:
            existing.order_code = new_code
            existing.tracking_number = new_code
            for k, v in payload.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.save()
            return

        DeliveryOrder.objects.create(order_code=new_code, tracking_number=new_code, **payload)

    except Exception:
        logger.exception("DeliveryOrder create/update failed (non-fatal).")


def _notify_order_paid(order: Order) -> None:
    if Notifier and hasattr(Notifier, "notify_order_placed"):
        try:
            Notifier.notify_order_placed(order)
        except Exception:
            logger.exception("Notifier failed (non-fatal).")


def _paystack_public_key() -> str:
    cfg = _config()
    key = (getattr(cfg, "paystack_public_key", "") or "").strip()
    return key or (getattr(settings, "PAYSTACK_PUBLIC_KEY", "") or "").strip()


def _paystack_secret_key() -> str:
    return (getattr(settings, "PAYSTACK_SECRET_KEY", "") or "").strip()


def _new_paystack_reference(order_id: int) -> str:
    return f"JOD-{order_id}-{uuid.uuid4().hex[:12]}"


def _get_or_create_pending_payment(order: Order, amount: Decimal) -> PaymentTransaction:
    recent_cutoff = timezone.now() - timedelta(minutes=30)
    payment = (
        PaymentTransaction.objects.filter(order=order, status="pending", created_at__gte=recent_cutoff)
        .order_by("-created_at")
        .first()
    )

    if payment:
        stored_access = (payment.gateway_response or {}).get("access_code")
        if stored_access and (payment.amount == amount):
            return payment
        try:
            payment.status = "failed"
            payment.save(update_fields=["status"])
        except Exception:
            pass

    return PaymentTransaction.objects.create(
        order=order,
        buyer=order.buyer,
        amount=amount,
        status="pending",
        reference=_new_paystack_reference(order.id),
    )


def _extract_paystack_status_and_amount_kobo(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    try:
        if "data" in data and isinstance(data["data"], dict):
            d = data["data"]
        else:
            d = data
        status = d.get("status")
        amount = d.get("amount")
        currency = d.get("currency")
        try:
            amount_int = int(amount) if amount is not None else None
        except Exception:
            amount_int = None
        return status, amount_int, currency
    except Exception:
        return None, None, None


def _fulfill_paid_order(order: Order, gateway: str, provider_reference: str, raw: Optional[Dict[str, Any]] = None) -> None:
    if order.status in ("paid", "processing", "shipped", "completed"):
        return

    _recalc_order_amounts(order)
    _reserve_stock_or_fail(order)

    order.status = "paid"
    order.save(update_fields=["status"])

    _create_or_update_seller_payouts(order)
    _create_delivery_order(order)
    _notify_order_paid(order)


# ===========================================================
# HOME + SEARCH
# ===========================================================
def home(request):
    cfg = _config()
    featured = (
        Product.objects.filter(is_active=True, is_featured=True)
        .select_related("category", "seller")
        .prefetch_related("images")[:12]
    )
    latest = (
        Product.objects.filter(is_active=True)
        .select_related("category", "seller")
        .prefetch_related("images")
        .order_by("-created_at")[:24]
    )
    categories = Category.objects.filter(is_active=True).order_by("name")[:20]

    return render(
        request,
        "store/home.html",
        {
            "featured": featured,
            "latest": latest,
            "categories": categories,
            "currency_symbol": getattr(cfg, "currency_symbol", "₦"),
        },
    )


def search_products(request):
    cfg = _config()
    query = (request.GET.get("q") or "").strip()
    category_id = (request.GET.get("category") or "").strip()
    min_price = request.GET.get("min")
    max_price = request.GET.get("max")

    products = Product.objects.filter(is_active=True).select_related("category", "seller").prefetch_related("images")

    if category_id:
        products = products.filter(category_id=category_id)

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
            | Q(seller__store_name__icontains=query)
        )

    if min_price:
        products = products.filter(price__gte=_money(min_price))
    if max_price:
        products = products.filter(price__lte=_money(max_price))

    products = products.order_by("-created_at")
    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "store/search_results.html",
        {"products": page_obj, "query": query, "currency_symbol": getattr(cfg, "currency_symbol", "₦")},
    )


# ===========================================================
# PRODUCT DETAIL
# ===========================================================
def product_detail(request, slug, public_id):
    product = get_object_or_404(
        Product.objects.select_related("category", "seller").prefetch_related("images"),
        is_active=True,
        slug=slug,
        public_id=public_id,
    )

    canonical = _canonical_product_url(product)
    if request.path != canonical:
        return redirect(canonical)

    insight = _ensure_product_insight(product)
    if insight:
        try:
            insight.record_view()
        except Exception:
            pass

    cfg = _config()
    return render(request, "store/product_detail.html", {"product": product, "currency_symbol": getattr(cfg, "currency_symbol", "₦")})


def product_detail_legacy(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("category", "seller").prefetch_related("images"),
        pk=pk,
        is_active=True,
    )
    return redirect(_canonical_product_url(product))


# ===========================================================
# CART
# ===========================================================
@login_required
def view_cart(request):
    cfg = _config()
    order = _get_pending_order(request.user)
    items = order.items.select_related("product", "seller").all()

    try:
        _recalc_order_amounts(order)
    except Exception:
        logger.exception("Cart recalculation failed (non-fatal).")

    cart_count = items.aggregate(total=Sum("quantity"))["total"] or 0

    return render(
        request,
        "store/cart.html",
        {"order": order, "items": items, "cart_count": cart_count, "currency_symbol": getattr(cfg, "currency_symbol", "₦")},
    )


@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)

    if int(product.stock or 0) <= 0:
        messages.warning(request, "This product is out of stock.")
        return redirect("store_home")

    raw_qty = (request.POST.get("qty") if request.method == "POST" else request.GET.get("qty")) or "1"
    try:
        qty = int(raw_qty)
    except Exception:
        qty = 1

    qty = max(1, qty)
    qty = min(qty, int(product.stock or 0))

    order = _get_pending_order(request.user)

    with transaction.atomic():
        item, created = OrderItem.objects.select_for_update().get_or_create(
            order=order,
            product=product,
            defaults={"seller": product.seller, "quantity": qty, "unit_price": product.price, "subtotal": product.price * qty},
        )

        if not created:
            new_qty = int(item.quantity or 0) + qty
            new_qty = min(new_qty, int(product.stock or 0))
            item.quantity = max(1, new_qty)

        item.seller = product.seller
        item.unit_price = product.price
        item.subtotal = item.unit_price * int(item.quantity or 1)
        item.save(update_fields=["seller", "quantity", "unit_price", "subtotal"])

    _recalc_order_amounts(order)

    next_url = (request.POST.get("next") if request.method == "POST" else request.GET.get("next")) or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)

    messages.success(request, f"{product.name} added to your cart.")
    return redirect("view_cart")


@login_required
def remove_from_cart(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order__buyer=request.user, order__status="pending")
    order = item.order
    item.delete()

    try:
        _recalc_order_amounts(order)
    except Exception:
        pass

    messages.info(request, "Item removed from cart.")
    return redirect("view_cart")


@login_required
@require_POST
def update_cart_quantity(request, item_id):
    try:
        qty = int(request.POST.get("qty", 1))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid quantity"}, status=400)

    item = get_object_or_404(OrderItem, id=item_id, order__buyer=request.user, order__status="pending")
    product = item.product

    if qty < 1:
        order = item.order
        item.delete()
        _recalc_order_amounts(order)
        cart_count = order.items.aggregate(total=Sum("quantity"))["total"] or 0
        return JsonResponse(
            {
                "ok": True,
                "deleted": True,
                "cart_count": int(cart_count),
                "order_subtotal": float(order.subtotal),
                "order_vat": float(getattr(order, "vat", 0) or 0),
                "delivery_fee": float(getattr(order, "delivery_fee", 0) or 0),
                "order_total": float(getattr(order, "total", 0) or 0),
            }
        )

    if product and qty > int(product.stock or 0):
        return JsonResponse({"ok": False, "error": "Quantity exceeds stock"}, status=400)

    item.quantity = qty
    item.unit_price = product.price if product else (item.unit_price or Decimal("0.00"))
    item.subtotal = item.unit_price * qty
    item.save(update_fields=["quantity", "unit_price", "subtotal"])

    order = item.order
    _recalc_order_amounts(order)

    cart_count = order.items.aggregate(total=Sum("quantity"))["total"] or 0

    return JsonResponse(
        {
            "ok": True,
            "success": True,
            "quantity": int(item.quantity),
            "cart_count": int(cart_count),
            "item_subtotal": float(item.subtotal),
            "order_subtotal": float(order.subtotal),
            "order_vat": float(getattr(order, "vat", 0) or 0),
            "delivery_fee": float(getattr(order, "delivery_fee", 0) or 0),
            "order_total": float(getattr(order, "total", 0) or 0),
        }
    )


# ===========================================================
# WISHLIST
# ===========================================================
@login_required
def toggle_wishlist(request, product_id):
    wishlist = request.session.get("wishlist", [])
    pid = str(product_id)

    if pid in wishlist:
        wishlist.remove(pid)
        messages.info(request, "Removed from wishlist.")
    else:
        wishlist.append(pid)
        messages.success(request, "Added to wishlist.")

    request.session["wishlist"] = wishlist
    request.session.modified = True
    return redirect("view_wishlist")


@login_required
def view_wishlist(request):
    cfg = _config()
    ids = request.session.get("wishlist", [])
    products = Product.objects.filter(id__in=ids, is_active=True).select_related("category", "seller").prefetch_related("images")
    return render(request, "store/wishlist.html", {"products": products, "currency_symbol": getattr(cfg, "currency_symbol", "₦")})


# ===========================================================
# CHECKOUT (INLINE PAY - NO REDIRECT)
# ===========================================================
@login_required
def checkout_view(request):
    cfg = _config()
    order = _get_pending_order(request.user)
    items = order.items.select_related("product", "seller", "seller__user").all()

    if not items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect("store_home")

    _recalc_order_amounts(order)

    promo_form = PromoCodeForm(request.POST or None)
    address_form = DeliveryAddressForm(request.POST or None) if DeliveryAddressForm else None

    if request.method == "POST" and "apply_promo" in request.POST:
        if promo_form.is_valid():
            promo = promo_form.cleaned_data["code"]
            discount = (order.subtotal * (promo.discount_percent or 0)) / Decimal("100")
            order.subtotal = max(Decimal("0.00"), (order.subtotal or Decimal("0.00")) - discount)
            order.save(update_fields=["subtotal"])
            try:
                order.calculate_totals()
            except Exception:
                logger.exception("order.calculate_totals failed (non-fatal).")
            try:
                promo.use()
            except Exception:
                logger.exception("Promo use() failed (non-fatal).")
            messages.success(request, f"Promo applied: {promo.discount_percent}% off")
        else:
            messages.error(request, "Invalid or expired promo code.")
        return redirect("checkout_view")

    return render(
        request,
        "store/checkout.html",
        {
            "promo_form": promo_form,
            "address_form": address_form,
            "order": order,
            "items": items,
            "active_gateway": getattr(cfg, "active_gateway", "paystack"),
            "paystack_key": getattr(cfg, "paystack_public_key", "") or "",
            "currency_symbol": getattr(cfg, "currency_symbol", "₦"),
        },
    )


# ===========================================================
# PAYSTACK INLINE INIT + VERIFY (AJAX)
# ===========================================================
@require_POST
@login_required
def paystack_inline_init(request):
    cfg = _config()
    if getattr(cfg, "active_gateway", "paystack") != "paystack":
        return JsonResponse({"ok": False, "error": "Paystack is not the active gateway."}, status=400)

    order = _get_pending_order(request.user)
    if not order.items.exists():
        return JsonResponse({"ok": False, "error": "Your cart is empty."}, status=400)

    if not DeliveryAddressForm:
        return JsonResponse({"ok": False, "error": "DeliveryAddressForm not configured."}, status=500)

    form = DeliveryAddressForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": "Invalid address.", "fields": form.errors}, status=400)

    cd = form.cleaned_data
    for field, val in {
        "address_line1": cd.get("address_line1", ""),
        "address_line2": cd.get("address_line2", ""),
        "city": cd.get("city", ""),
        "state": cd.get("state", ""),
        "country": cd.get("country", ""),
        "postal_code": cd.get("postal_code", ""),
    }.items():
        if hasattr(order, field):
            setattr(order, field, val)

    if hasattr(order, "delivery_address") and not getattr(order, "delivery_address", ""):
        order.delivery_address = f"{cd.get('address_line1','')} {cd.get('address_line2','')}".strip()

    order.save()
    _recalc_order_amounts(order)

    email = (request.user.email or "").strip()
    if not email:
        return JsonResponse({"ok": False, "error": "User email is missing."}, status=400)

    amount = getattr(order, "total", None)
    if not amount or Decimal(str(amount)) <= 0:
        return JsonResponse({"ok": False, "error": "Order total is invalid."}, status=400)

    public_key = _paystack_public_key()
    if not public_key:
        return JsonResponse({"ok": False, "error": "PAYSTACK_PUBLIC_KEY missing."}, status=500)

    payment = _get_or_create_pending_payment(order, Decimal(str(amount)))

    existing_access = (payment.gateway_response or {}).get("access_code")
    if existing_access and payment.amount == Decimal(str(amount)):
        return JsonResponse(
            {
                "ok": True,
                "public_key": public_key,
                "email": email,
                "amount_kobo": _to_kobo(Decimal(str(amount))),
                "reference": payment.reference,
                "access_code": existing_access,
            }
        )

    metadata = {
        "order_ref": str(getattr(order, "reference", order.id)),
        "order_public": _public_order_number(order),
        "buyer_email": email,
        "buyer_id": str(request.user.id),
    }

    auth_url, ref, access_code, raw = paystack_api.initialize_payment(
        email=email,
        amount=Decimal(str(amount)),
        metadata=metadata,
        callback_url=None,
        currency=getattr(cfg, "currency", "NGN") or "NGN",
        reference=payment.reference,
    )

    if not access_code:
        msg = (raw or {}).get("message") or (raw or {}).get("error") or "Paystack init failed."
        try:
            payment.status = "failed"
            payment.gateway_response = raw or {}
            payment.save(update_fields=["status", "gateway_response"])
        except Exception:
            pass
        return JsonResponse({"ok": False, "error": msg, "raw": raw}, status=400)

    payment.gateway_response = {"access_code": access_code, "raw": raw or {}}
    payment.save(update_fields=["gateway_response"])

    return JsonResponse(
        {
            "ok": True,
            "public_key": public_key,
            "email": email,
            "amount_kobo": _to_kobo(Decimal(str(amount))),
            "reference": payment.reference,
            "access_code": access_code,
        }
    )


@require_POST
@login_required
def paystack_inline_verify(request):
    reference = (request.POST.get("reference") or "").strip()
    if not reference:
        return JsonResponse({"ok": False, "error": "Missing reference."}, status=400)

    payment = PaymentTransaction.objects.select_related("order").filter(reference=reference).first()
    if not payment or not payment.order:
        return JsonResponse({"ok": False, "error": "Payment/order not found."}, status=404)

    order = payment.order
    if order.buyer_id != request.user.id:
        return JsonResponse({"ok": False, "error": "Unauthorized."}, status=403)

    if payment.status == "success" or order.status in ("paid", "processing", "shipped", "completed"):
        return JsonResponse({"ok": True, "redirect_url": reverse("order_success", kwargs={"reference": order.reference})})

    ok, data = paystack_api.verify_payment(reference)
    if not ok:
        payment.status = "failed"
        payment.gateway_response = data or {}
        payment.save(update_fields=["status", "gateway_response"])
        return JsonResponse({"ok": False, "error": "Payment verification failed.", "raw": data}, status=400)

    status, amount_kobo, currency = _extract_paystack_status_and_amount_kobo(data or {})
    expected_kobo = _to_kobo(Decimal(str(getattr(order, "total", 0) or 0)))
    if amount_kobo is not None and expected_kobo and amount_kobo != expected_kobo:
        payment.status = "failed"
        payment.gateway_response = data or {}
        payment.save(update_fields=["status", "gateway_response"])
        return JsonResponse({"ok": False, "error": "Payment amount mismatch."}, status=400)

    try:
        with transaction.atomic():
            payment.status = "success"
            payment.gateway_response = data or {}
            payment.save(update_fields=["status", "gateway_response"])
            _fulfill_paid_order(order, gateway="paystack", provider_reference=reference, raw=data or {})
    except Exception as e:
        logger.exception("Fulfilment failed after inline verification.")
        return JsonResponse({"ok": False, "error": f"Payment verified but fulfilment failed: {e}."}, status=500)

    return JsonResponse({"ok": True, "redirect_url": reverse("order_success", kwargs={"reference": order.reference})})


# ===========================================================
# FALLBACK VERIFY ENDPOINT
# ===========================================================
@login_required
def verify_payment(request):
    reference = (request.GET.get("reference") or request.POST.get("reference") or "").strip()
    if not reference:
        return HttpResponseForbidden("Missing payment reference")

    payment = PaymentTransaction.objects.select_related("order").filter(reference=reference).first()
    if not payment or not payment.order:
        return HttpResponseBadRequest("Could not resolve payment/order.")

    order = payment.order

    if payment.status == "success" or order.status in ("paid", "processing", "shipped", "completed"):
        messages.success(request, "✅ Payment already verified.")
        return redirect("order_success", reference=order.reference)

    ok, data = paystack_api.verify_payment(reference)
    if not ok:
        payment.status = "failed"
        payment.gateway_response = data or {}
        payment.save(update_fields=["status", "gateway_response"])
        messages.error(request, "Payment verification failed.")
        return redirect("checkout_view")

    status, amount_kobo, currency = _extract_paystack_status_and_amount_kobo(data or {})
    expected_kobo = _to_kobo(Decimal(str(getattr(order, "total", 0) or 0)))
    if amount_kobo is not None and expected_kobo and amount_kobo != expected_kobo:
        payment.status = "failed"
        payment.gateway_response = data or {}
        payment.save(update_fields=["status", "gateway_response"])
        messages.error(request, "Payment amount mismatch.")
        return redirect("checkout_view")

    try:
        with transaction.atomic():
            payment.status = "success"
            payment.gateway_response = data or {}
            payment.save(update_fields=["status", "gateway_response"])
            _fulfill_paid_order(order, gateway="paystack", provider_reference=reference, raw=data or {})
    except Exception as e:
        logger.exception("Fulfilment failed after verification.")
        messages.warning(request, f"Payment verified, but fulfilment had an issue: {e}. Contact support.")
        return redirect("order_success", reference=order.reference)

    messages.success(request, "✅ Payment verified successfully.")
    return redirect("order_success", reference=order.reference)


# ===========================================================
# SUCCESS + INVOICE
# ===========================================================
@login_required
def order_success(request, reference):
    order = get_object_or_404(Order, reference=reference, buyer=request.user)

    tracking_no = (getattr(order, "tracking_no", None) or "").strip()
    if not tracking_no:
        tracking_no = _public_order_number(order)

    track_url = reverse("track_order") + f"?tracking_number={tracking_no}"

    return render(
        request,
        "store/order_success.html",
        {
            "order": order,
            "order_number": tracking_no,
            "public_order_number": _public_order_number(order),
            "track_url": track_url,
            "currency_symbol": getattr(_config(), "currency_symbol", "₦"),
        },
    )


@login_required
def download_invoice(request, reference):
    order = get_object_or_404(Order, reference=reference, buyer=request.user)
    if not InvoiceService or not hasattr(InvoiceService, "generate_invoice_pdf"):
        return HttpResponseBadRequest("Invoice service not configured.")
    return InvoiceService.generate_invoice_pdf(order)


# ===========================================================
# TRACK ORDER (PUBLIC)
# ===========================================================
def track_order(request):
    tracking_number = (request.GET.get("tracking_number") or "").strip()
    delivery = None
    order = None

    if tracking_number:
        # 1) tracking_no
        order = Order.objects.filter(tracking_no=tracking_number).first()

        # 2) digits -> try id
        if not order and tracking_number.isdigit():
            order = Order.objects.filter(id=int(tracking_number)).first()

        # 3) legacy reference
        if not order:
            order = Order.objects.filter(reference=tracking_number).first()

        if DeliveryOrder:
            try:
                delivery = (
                    DeliveryOrder.objects.filter(Q(tracking_number=tracking_number) | Q(order_code=tracking_number))
                    .prefetch_related("tracking_history")
                    .first()
                )

                if not delivery and order:
                    legacy = str(getattr(order, "reference", "") or "")
                    oid = str(getattr(order, "id", "") or "")
                    delivery = (
                        DeliveryOrder.objects.filter(
                            Q(tracking_number=legacy) | Q(order_code=legacy) | Q(tracking_number=oid) | Q(order_code=oid)
                        )
                        .prefetch_related("tracking_history")
                        .first()
                    )
            except Exception:
                delivery = None

    return render(request, "store/tracking.html", {"tracking_number": tracking_number, "delivery": delivery, "order": order})


# ===========================================================
# PAYSTACK WEBHOOK
# ===========================================================
@csrf_exempt
@require_POST
def paystack_webhook(request):
    secret = _paystack_secret_key()
    signature = request.headers.get("x-paystack-signature") or request.META.get("HTTP_X_PAYSTACK_SIGNATURE")

    if not secret or not signature:
        return HttpResponseForbidden("Unauthorized")

    computed = hmac.new(secret.encode("utf-8"), msg=request.body, digestmod=hashlib.sha512).hexdigest()
    if not _safe_compare_digest(computed, signature):
        return HttpResponseForbidden("Invalid signature")

    try:
        event = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    event_type = event.get("event")
    data = event.get("data") or {}

    if event_type in ("charge.success", "transaction.success"):
        pay_ref = (data.get("reference") or "").strip()
        if pay_ref:
            payment = PaymentTransaction.objects.select_related("order").filter(reference=pay_ref).first()
            if payment and payment.order and payment.status != "success":
                try:
                    with transaction.atomic():
                        payment.status = "success"
                        payment.gateway_response = data
                        payment.save(update_fields=["status", "gateway_response"])
                        _fulfill_paid_order(payment.order, gateway="paystack", provider_reference=pay_ref, raw=data)
                except Exception:
                    logger.exception("Webhook fulfilment failed (non-fatal).")

    return JsonResponse({"status": "ok"})


# ===========================================================
# SELLER: PRODUCT CRUD
# ===========================================================
@seller_required
def add_product(request):
    seller = request.user.seller_profile
    form = ProductForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.seller = seller
        product.save()
        form.save_m2m()
        messages.success(request, "✅ Product added successfully.")
        return redirect("seller_dashboard")

    return render(request, "store/product_form.html", {"form": form})


@seller_required
def edit_product(request, pk):
    seller = request.user.seller_profile
    product = get_object_or_404(Product, pk=pk, seller=seller)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "✅ Product updated successfully.")
        return redirect("seller_dashboard")

    return render(request, "store/product_form.html", {"form": form, "edit_mode": True, "product": product})


@seller_required
def delete_product(request, pk):
    seller = request.user.seller_profile
    product = get_object_or_404(Product, pk=pk, seller=seller)

    if request.method == "POST":
        product.delete()
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": True})
        messages.warning(request, "🗑️ Product deleted.")
        return redirect("seller_dashboard")

    return render(request, "store/confirm_delete.html", {"product": product})


@seller_required
def upload_product_image(request, product_id):
    seller = request.user.seller_profile
    product = get_object_or_404(Product, pk=product_id, seller=seller)

    try:
        existing_count = product.images.count()  # type: ignore
    except Exception:
        existing_count = None

    form = ProductImageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        if existing_count is not None and existing_count >= 5:
            messages.error(request, "You can upload a maximum of 5 images for a product.")
            return redirect("edit_product", pk=product.pk)

        img = form.save(commit=False)
        img.product = product
        img.save()
        messages.success(request, "✅ Image uploaded successfully.")
        return redirect("edit_product", pk=product.pk)

    return render(request, "store/product_image_form.html", {"form": form, "product": product})


# ===========================================================
# SELLER SETTINGS + INSIGHTS
# ===========================================================
@seller_required
def seller_settings(request):
    seller = request.user.seller_profile
    try:
        from .forms import SellerSettingsForm
    except Exception:
        return HttpResponseBadRequest("SellerSettingsForm not configured.")

    form = SellerSettingsForm(request.POST or None, request.FILES or None, instance=seller)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "✅ Store settings updated successfully.")
        return redirect("seller_settings")

    return render(request, "store/seller_settings.html", {"form": form, "seller": seller})


@seller_required
def product_insights(request):
    seller = request.user.seller_profile
    insights = ProductInsight.objects.filter(product__seller=seller).select_related("product")
    return render(request, "store/insights.html", {"insights": insights})


# ===========================================================
# SHIPMENT + REFUND
# ===========================================================
@seller_required
def manage_shipment(request, order_id):
    seller = request.user.seller_profile
    order = get_object_or_404(Order.objects.filter(items__seller=seller).distinct(), id=order_id)

    shipment, _ = Shipment.objects.get_or_create(order=order)
    form = ShipmentForm(request.POST or None, instance=shipment)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "✅ Shipment details updated.")
        return redirect("seller_dashboard")

    return render(request, "store/shipment_form.html", {"form": form, "order": order})


@login_required
def request_refund(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order__buyer=request.user)
    form = RefundRequestForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        refund: RefundRequest = form.save(commit=False)
        refund.order_item = item
        refund.amount_requested = item.subtotal
        refund.save()
        messages.info(request, "Refund request submitted successfully.")
        return redirect("order_success", reference=item.order.reference)

    return render(request, "store/refund_form.html", {"form": form, "item": item})


# ===========================================================
# SELLER DASHBOARD + PAYOUTS
# ===========================================================
@seller_required
def seller_dashboard(request):
    cfg = _config()
    seller = request.user.seller_profile

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "all").strip()

    products = Product.objects.filter(seller=seller).order_by("-created_at")
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if status == "active":
        products = products.filter(is_active=True)
    elif status == "inactive":
        products = products.filter(is_active=False)

    paginator = Paginator(products, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    payouts = SellerPayout.objects.filter(seller=request.user)
    total_earnings = payouts.aggregate(Sum("payable_amount"))["payable_amount__sum"] or 0
    total_orders = payouts.count()

    last_month = timezone.now() - timedelta(days=30)
    month_earnings = payouts.filter(created_at__gte=last_month).aggregate(Sum("payable_amount"))["payable_amount__sum"] or 0

    pending_shipments = Order.objects.filter(status="paid", items__seller=seller).exclude(shipments__isnull=False).distinct().count()
    low_stock_count = Product.objects.filter(seller=seller, stock__lt=5).count()

    recent_payouts = payouts.order_by("-created_at")[:5]
    recent_products = Product.objects.filter(seller=seller).order_by("-created_at")[:5]

    return render(
        request,
        "store/seller_dashboard.html",
        {
            "seller": seller,
            "products": page_obj,
            "q": q,
            "status": status,
            "total_earnings": total_earnings,
            "month_earnings": month_earnings,
            "total_orders": total_orders,
            "pending_shipments": pending_shipments,
            "low_stock_count": low_stock_count,
            "recent_payouts": recent_payouts,
            "recent_products": recent_products,
            "products_count": Product.objects.filter(seller=seller).count(),
            "currency_symbol": getattr(cfg, "currency_symbol", "₦"),
        },
    )


@seller_required
def request_payout(request):
    seller = request.user.seller_profile
    cfg = _config()

    balance = getattr(seller, "wallet_balance", Decimal("0.00")) or Decimal("0.00")

    if request.method == "POST":
        amount = _money(request.POST.get("amount", "0"))
        if amount <= 0:
            messages.error(request, "Invalid amount.")
        elif amount > balance:
            messages.error(request, "Insufficient wallet balance.")
        else:
            bank_info = f"{getattr(seller,'bank_name','')} - {getattr(seller,'bank_account_number','')} ({getattr(seller,'bank_account_name','')})"
            PayoutRequest.objects.create(seller=seller, amount=amount, bank_details=bank_info)
            messages.success(request, "Withdrawal request submitted! 💸")
            return redirect("request_payout")

    history = PayoutRequest.objects.filter(seller=seller).order_by("-created_at")
    return render(
        request,
        "store/payout_history.html",
        {"balance": balance, "history": history, "seller": seller, "currency_symbol": getattr(cfg, "currency_symbol", "₦")},
    )
