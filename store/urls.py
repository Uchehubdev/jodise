# store/urls.py
from __future__ import annotations

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
    path("paystack/inline/init/", views.paystack_inline_init, name="paystack_inline_init"),
    path("paystack/inline/verify/", views.paystack_inline_verify, name="paystack_inline_verify"),
    path("verify-payment/", views.verify_payment, name="verify_payment"),

    path("order/success/<str:reference>/", views.order_success, name="order_success"),
    path("order/<str:reference>/invoice/", views.download_invoice, name="download_invoice"),

    path("webhooks/paystack/", views.paystack_webhook, name="paystack_webhook"),

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

    path("seller/product/<uuid:pk>/toggle-status/", views.toggle_product_status, name="toggle_product_status"),
    path("seller/products/bulk-action/", views.seller_products_bulk_action, name="seller_products_bulk_action"),

    path("seller/settings/", views.seller_settings, name="seller_settings"),
    path("seller/payouts/", views.request_payout, name="request_payout"),
    path("seller/insights/", views.product_insights, name="product_insights"),

    path("seller/orders/", views.seller_orders, name="seller_orders"),
    # path("seller/orders/<uuid:order_id>/", views.seller_order_detail, name="seller_order_detail"),
    # path("seller/orders/<uuid:order_id>/update-fulfillment/", views.seller_update_fulfillment, name="seller_update_fulfillment"),

    path("seller/orders/<int:order_id>/", views.seller_order_detail, name="seller_order_detail"),
    path(
        "seller/orders/<int:order_id>/update-fulfillment/",
        views.seller_update_fulfillment,
        name="seller_update_fulfillment",
        ),

    # (Legacy shipment view) - keep ONE route only
    path("seller/shipment/<int:order_id>/", views.manage_shipment, name="manage_shipment"),

    # ==========================================================
    # 🏭 Warehouse (Staff)
    # ==========================================================
    path("warehouse/", views.warehouse_dashboard, name="warehouse_dashboard"),
    path("warehouse/orders/<str:tracking_no>/", views.warehouse_order_detail, name="warehouse_order_detail"),
    path("warehouse/orders/<str:tracking_no>/receive/<int:fulfillment_id>/", views.warehouse_receive_seller_package, name="warehouse_receive_seller_package"),
    path("warehouse/orders/<str:tracking_no>/shipment/update/", views.warehouse_update_shipment, name="warehouse_update_shipment"),
]
