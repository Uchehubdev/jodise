from django.urls import path
from . import views

urlpatterns = [
    # 🌍 HOME & SEARCH
    path("", views.home, name="store_home"),
    path("track/", views.track_order, name="track_order"),  # 🚚 Public Tracking
    path("item/<int:pk>/", views.product_detail, name="product_detail"),  # ✅ Added detail view
    path("search/", views.search_products, name="search_products"),

    # 🛒 CART
    path("cart/", views.view_cart, name="view_cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/remove/<int:item_id>/", views.remove_from_cart, name="remove_from_cart"),
    path("cart/update/<int:item_id>/", views.update_cart_quantity, name="update_cart_quantity"),

    # ❤️ WISHLIST
    path("wishlist/", views.view_wishlist, name="view_wishlist"),
    path("wishlist/toggle/<int:product_id>/", views.toggle_wishlist, name="toggle_wishlist"),

    # 🧾 CHECKOUT + PAYMENT
    path("checkout/", views.checkout_view, name="checkout_view"),
    path("verify-payment/", views.verify_payment, name="verify_payment"),
    path("order/success/<uuid:reference>/", views.order_success, name="order_success"),
    path("order/<uuid:reference>/invoice/", views.download_invoice, name="download_invoice"), # 📄 Invoice
    path("paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),

    # 💰 REFUNDS
    path("refund/<int:item_id>/", views.request_refund, name="request_refund"),

    # 🧑‍🌾 SELLER DASHBOARD + CRUD
    path("seller/dashboard/", views.seller_dashboard, name="seller_dashboard"),
    path("seller/product/add/", views.add_product, name="add_product"),
    path("seller/product/<int:pk>/edit/", views.edit_product, name="edit_product"),
    path("seller/product/<int:pk>/delete/", views.delete_product, name="delete_product"),
    path("seller/product/<int:product_id>/upload-image/", views.upload_product_image, name="upload_product_image"),
    path("seller/settings/", views.seller_settings, name="seller_settings"),

    # 🚚 SHIPMENT MANAGEMENT
    path("seller/shipment/<int:order_id>/", views.manage_shipment, name="manage_shipment"),

    # 💸 PAYOUTS
    # 💸 PAYOUTS
    path("seller/payouts/", views.request_payout, name="request_payout"),

    # 📈 INSIGHTS
    path("seller/insights/", views.product_insights, name="product_insights"),
]
