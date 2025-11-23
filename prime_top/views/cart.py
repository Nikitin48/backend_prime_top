from __future__ import annotations

from django.db import transaction
from django.db.models import F, FloatField, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Cart, CartItem, Orders, OrdersItems, Products, Series, Stocks, Users
from .utils import (
    _parse_json_body,
    _serialize_client,
    _serialize_product,
    _serialize_series,
    require_client_auth,
)


def _get_or_create_cart(user: Users) -> Cart:
    cart, created = Cart.objects.get_or_create(
        user=user,
        defaults={
            "cart_created_at": timezone.now(),
            "cart_updated_at": timezone.now(),
        },
    )
    if not created:
        cart.cart_updated_at = timezone.now()
        cart.save(update_fields=["cart_updated_at"])
    return cart


def _serialize_cart_item(cart_item: CartItem) -> dict:
    result = {
        "id": cart_item.cart_item_id,
        "quantity": cart_item.cart_item_quantity,
        "product": _serialize_product(cart_item.product),
        "series": _serialize_series(cart_item.series) if cart_item.series else None,
    }
    return result


def _serialize_cart(cart: Cart, include_items: bool = True) -> dict:
    payload = {
        "id": cart.cart_id,
        "user": {
            "id": cart.user.user_id,
            "email": cart.user.user_email,
            "first_name": getattr(cart.user, "user_name", None),
            "last_name": getattr(cart.user, "user_surname", None),
        },
        "client": _serialize_client(cart.user.client),
        "created_at": cart.cart_created_at.isoformat() if cart.cart_created_at else None,
        "updated_at": cart.cart_updated_at.isoformat() if cart.cart_updated_at else None,
    }

    if include_items:
        items = []
        cart_items_qs = CartItem.objects.filter(cart=cart).select_related(
            "product",
            "product__coating_types",
            "series",
            "series__product",
            "series__product__coating_types",
        )
        for item in cart_items_qs:
            items.append(_serialize_cart_item(item))

        payload["items"] = items
        payload["items_count"] = len(items)
        payload["total_quantity"] = float(
            sum(item["quantity"] for item in items)
        )

        total_price = sum(
            item["product"]["price"] * item["quantity"] for item in items
        )
        payload["total_price"] = total_price
    else:
        items_count = CartItem.objects.filter(cart=cart).count()
        total_quantity = (
            CartItem.objects.filter(cart=cart).aggregate(
                total=Coalesce(Sum("cart_item_quantity"), 0)
            )["total"]
            or 0
        )
        payload["items_count"] = items_count
        payload["total_quantity"] = float(total_quantity)

    return payload


@require_client_auth
@csrf_exempt
@require_http_methods(["GET"])
def cart_view(request):
    user = request.authenticated_user
    cart = _get_or_create_cart(user)
    return JsonResponse(_serialize_cart(cart, include_items=True))


@require_client_auth
@csrf_exempt
@require_http_methods(["POST"])
def cart_item_add_view(request):
    user = request.authenticated_user

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    product_id = payload.get("product_id")
    series_id = payload.get("series_id")
    quantity = payload.get("quantity", 1)

    if not product_id:
        return JsonResponse({"error": "Field 'product_id' is required."}, status=400)

    try:
        product_id = int(product_id)
        if series_id is not None:
            series_id = int(series_id)
        quantity = int(quantity)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Fields 'product_id' and 'quantity' must be integers. 'series_id' must be integer or null."},
            status=400,
        )

    if quantity <= 0:
        return JsonResponse({"error": "Field 'quantity' must be greater than zero."}, status=400)

    product = get_object_or_404(Products, pk=product_id)
    series = None

    if series_id is not None:
        series = get_object_or_404(Series, pk=series_id)

        if series.product_id != product.product_id:
            return JsonResponse(
                {"error": f"Series '{series_id}' does not belong to product '{product_id}'."},
                status=400,
            )

        stocks_queryset = Stocks.objects.filter(series=series)
        stocks_count = stocks_queryset.aggregate(
            total=Coalesce(Sum("stocks_count", output_field=FloatField()), 0.0)
        )["total"] or 0.0

        if stocks_count <= 0:
            return JsonResponse(
                {
                    "error": f"Series '{series_id}' is not available in stocks or quantity is zero.",
                    "detail": f"Available quantity: {stocks_count}"
                },
                status=400,
            )

    cart = _get_or_create_cart(user)

    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        series=series,
        defaults={"cart_item_quantity": quantity},
    )

    if not created:
        cart_item.cart_item_quantity += quantity
        cart_item.save(update_fields=["cart_item_quantity"])

    cart.cart_updated_at = timezone.now()
    cart.save(update_fields=["cart_updated_at"])

    return JsonResponse(_serialize_cart_item(cart_item), status=201 if created else 200)


@require_client_auth
@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def cart_item_detail_view(request, cart_item_id: int):
    user = request.authenticated_user
    cart = _get_or_create_cart(user)

    cart_item = get_object_or_404(
        CartItem.objects.select_related("cart", "product", "series"),
        pk=cart_item_id,
        cart=cart,
    )

    if request.method == "DELETE":
        cart_item.delete()
        cart.cart_updated_at = timezone.now()
        cart.save(update_fields=["cart_updated_at"])
        return JsonResponse({"message": "Cart item deleted successfully."}, status=200)

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    quantity = payload.get("quantity")
    if quantity is None:
        return JsonResponse({"error": "Field 'quantity' is required."}, status=400)

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Field 'quantity' must be an integer."}, status=400)

    if quantity <= 0:
        return JsonResponse({"error": "Field 'quantity' must be greater than zero."}, status=400)

    cart_item.cart_item_quantity = quantity
    cart_item.save(update_fields=["cart_item_quantity"])

    cart.cart_updated_at = timezone.now()
    cart.save(update_fields=["cart_updated_at"])

    return JsonResponse(_serialize_cart_item(cart_item))


@require_client_auth
@csrf_exempt
@require_http_methods(["POST"])
def cart_checkout_view(request):
    user = request.authenticated_user
    client = user.client

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    cart = _get_or_create_cart(user)

    cart_items = CartItem.objects.filter(cart=cart).select_related(
        "product",
        "series",
    )

    if not cart_items.exists():
        return JsonResponse({"error": "Cart is empty. Cannot create order."}, status=400)

    status_value = str(payload.get("status", "pending")).strip()[:30] or "pending"
    note_value = payload.get("status_note")

    from django.utils.dateparse import parse_date
    from datetime import date

    created_at = timezone.now().date()
    if payload.get("created_at"):
        try:
            created_at = parse_date(payload["created_at"])
            if not created_at:
                raise ValueError
        except (ValueError, TypeError):
            return JsonResponse(
                {"error": "Field 'created_at' must be a valid ISO date (YYYY-MM-DD)."},
                status=400,
            )

    shipped_at = None
    if payload.get("shipped_at"):
        try:
            shipped_at = parse_date(payload["shipped_at"])
            if not shipped_at:
                raise ValueError
        except (ValueError, TypeError):
            return JsonResponse(
                {"error": "Field 'shipped_at' must be a valid ISO date (YYYY-MM-DD)."},
                status=400,
            )

    delivered_at = None
    if payload.get("delivered_at"):
        try:
            delivered_at = parse_date(payload["delivered_at"])
            if not delivered_at:
                raise ValueError
        except (ValueError, TypeError):
            return JsonResponse(
                {"error": "Field 'delivered_at' must be a valid ISO date (YYYY-MM-DD)."},
                status=400,
            )

    cancel_reason = str(payload.get("cancel_reason", ""))[:100] or None

    with transaction.atomic():
        order = Orders.objects.create(
            client=client,
            orders_status=status_value,
            orders_created_at=created_at,
            orders_shipped_at=shipped_at,
            orders_delivered_at=delivered_at,
            orders_cancel_reason=cancel_reason,
        )

        for cart_item in cart_items:
            order_item = OrdersItems.objects.create(
                orders=order,
                product=cart_item.product,
                series=cart_item.series,
                order_items_count=cart_item.cart_item_quantity,
            )

            if cart_item.series is not None:
                remaining_quantity = float(cart_item.cart_item_quantity)
                
                client_stocks = Stocks.objects.filter(
                    series=cart_item.series,
                    client=client,
                    stocks_count__gt=0
                )
                
                public_stocks = Stocks.objects.filter(
                    series=cart_item.series,
                    client__isnull=True,
                    stocks_count__gt=0
                )
                
                client_total = client_stocks.aggregate(
                    total=Coalesce(Sum("stocks_count", output_field=FloatField()), 0.0)
                )["total"] or 0.0
                
                public_total = public_stocks.aggregate(
                    total=Coalesce(Sum("stocks_count", output_field=FloatField()), 0.0)
                )["total"] or 0.0
                
                total_available = client_total + public_total
                
                if total_available < remaining_quantity:
                    transaction.set_rollback(True)
                    return JsonResponse(
                        {
                            "error": f"Insufficient stock for series '{cart_item.series.series_id}'. "
                                    f"Requested: {remaining_quantity}, Available: {total_available}"
                        },
                        status=400,
                    )
                
                stocks_records = list(client_stocks) + list(public_stocks)
                
                for stock_record in stocks_records:
                    if remaining_quantity <= 0:
                        break
                    
                    available_in_record = float(stock_record.stocks_count)
                    if available_in_record <= 0:
                        continue
                    
                    quantity_to_deduct = min(remaining_quantity, available_in_record)
                    stock_record.stocks_count = available_in_record - quantity_to_deduct
                    stock_record.stocks_update_at = timezone.now().date()
                    stock_record.save(update_fields=["stocks_count", "stocks_update_at"])
                    
                    remaining_quantity -= quantity_to_deduct

        from ..models import OrderStatusHistory

        OrderStatusHistory.objects.create(
            orders=order,
            order_status_history_from_stat="created",
            order_status_history_to_status=status_value,
            order_status_history_chang_at=timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_status_history_note=str(note_value)[:30] if note_value else "Created from cart",
        )

        cart_items.delete()

        cart.cart_updated_at = timezone.now()
        cart.save(update_fields=["cart_updated_at"])

    from .utils import _serialize_order

    order = Orders.objects.select_related("client").prefetch_related(
        "ordersitems_set__product",
        "ordersitems_set__product__coating_types",
        "ordersitems_set__series",
        "ordersitems_set__series__product",
        "ordersitems_set__series__product__coating_types",
    ).get(pk=order.orders_id)
    response_payload = _serialize_order(order, include_items=True)

    return JsonResponse(response_payload, status=201)


@require_client_auth
@csrf_exempt
@require_http_methods(["DELETE"])
def cart_clear_view(request):
    user = request.authenticated_user
    cart = _get_or_create_cart(user)

    CartItem.objects.filter(cart=cart).delete()

    cart.cart_updated_at = timezone.now()
    cart.save(update_fields=["cart_updated_at"])

    return JsonResponse({"message": "Cart cleared successfully."}, status=200)

