# store/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # ==========================================================
    # 🏠 PUBLIC
    # ==========================================================
    path("", views.home, name="store_home"),
    path("search/", views.search_products, name="search_products"),

    # ==========================================================
    # 🧾 PRODUCT (Canonical Jumia-style URL)
    # /some-product-slug-12345.html
    # ==========================================================
    path("<slug:slug>-<int:public_id>.html", views.product_detail, name="product_detail"),

    # Legacy UUID URL -> redirect to canonical
    path("item/<uuid:pk>/", views.product_detail_legacy, name="product_detail_legacy"),

    # ==========================================================
    # 🛒 CART
    # ==========================================================
    path("cart/", views.view_cart, name="view_cart"),
    path("cart/add/<uuid:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/remove/<int:item_id>/", views.remove_from_cart, name="remove_from_cart"),
    path("cart/update/<int:item_id>/", views.update_cart_quantity, name="update_cart_quantity"),

    # ==========================================================
    # ❤️ WISHLIST
    # ==========================================================
    path("wishlist/", views.view_wishlist, name="view_wishlist"),
    path("wishlist/toggle/<uuid:product_id>/", views.toggle_wishlist, name="toggle_wishlist"),

    # ==========================================================
    # 💳 CHECKOUT + PAYMENTS
    # ==========================================================
    path("checkout/", views.checkout_view, name="checkout_view"),

    # ✅ Inline Paystack (AJAX)
    path("paystack/inline/init/", views.paystack_inline_init, name="paystack_inline_init"),
    path("paystack/inline/verify/", views.paystack_inline_verify, name="paystack_inline_verify"),

    # ✅ Fallback redirect verify (keeps old callback flow working)
    path("verify-payment/", views.verify_payment, name="verify_payment"),

    # Success + Invoice
    path("order/success/<slug:reference>/", views.order_success, name="order_success"),
    path("order/<slug:reference>/invoice/", views.download_invoice, name="download_invoice"),

    # Webhooks
    path("webhooks/paystack/", views.paystack_webhook, name="paystack_webhook"),
    # path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),

    # ==========================================================
    # 📦 TRACKING (PUBLIC)
    # ==========================================================
    path("track/", views.track_order, name="track_order"),

    # ==========================================================
    # 🔁 REFUNDS
    # ==========================================================
    path("refund/<int:item_id>/", views.request_refund, name="request_refund"),

    # ==========================================================
    # 🧑‍🌾 SELLER (Verified)
    # ==========================================================
    path("seller/", views.seller_dashboard, name="seller_dashboard"),
    path("seller/product/add/", views.add_product, name="add_product"),
    path("seller/product/<uuid:pk>/edit/", views.edit_product, name="edit_product"),
    path("seller/product/<uuid:pk>/delete/", views.delete_product, name="delete_product"),
    path("seller/product/<uuid:product_id>/upload-image/", views.upload_product_image, name="upload_product_image"),

    path("seller/settings/", views.seller_settings, name="seller_settings"),
    path("seller/shipment/<int:order_id>/", views.manage_shipment, name="manage_shipment"),
    path("seller/payouts/", views.request_payout, name="request_payout"),
    path("seller/insights/", views.product_insights, name="product_insights"),
]
