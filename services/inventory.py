from django.db import transaction
from django.core.exceptions import ValidationError
from store.models import Product, OrderItem

class InventoryService:
    """
    Handles atomic stock updates and reservations.
    """

    @classmethod
    @transaction.atomic
    def reserve_stock(cls, items_data):
        """
        Atomically checks and decrements stock for a list of items.
        items_data: List of dicts {'product': Product, 'quantity': int}
        Raises ValidationError if any item is out of stock.
        """
        # Lock and refresh all products involved
        product_ids = [item['product'].id for item in items_data]
        # select_for_update locks rows until transaction ends
        products = Product.objects.select_for_update().filter(id__in=product_ids)
        product_map = {p.id: p for p in products}

        for item in items_data:
            product = product_map.get(item['product'].id)
            quantity = item['quantity']

            if not product:
                raise ValidationError(f"Product {item['product'].name} no longer exists.")
            
            if product.stock < quantity:
                raise ValidationError(f"Insufficient stock for {product.name}. Available: {product.stock}, Requested: {quantity}")

            # Decrement stock
            product.stock -= quantity
            product.save()

    @classmethod
    @transaction.atomic
    def release_stock(cls, order):
        """
        Restores stock if an order is cancelled or payment fails (optional usage).
        """
        items = order.items.select_related('product').all()
        for item in items:
            # We use F expressions for atomic increment without locking if we don't strict-need it
            # But locking is safer for consistency
            Product.objects.filter(id=item.product.id).update(stock=models.F('stock') + item.quantity)
