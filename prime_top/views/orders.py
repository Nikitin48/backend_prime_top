from __future__ import annotations

from django.db import transaction
from django.db.models import Count, FloatField, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from ..models import Clients, Orders, OrdersItems, Products, Series, Stocks
from .utils import _clip, _parse_iso_date, _parse_json_body, _serialize_client, _serialize_order


@csrf_exempt
@require_http_methods(["GET", "POST"])
def orders_view(request):
    if request.method == "GET":
        qs = Orders.objects.select_related("client").annotate(
            total_quantity=Coalesce(Sum("ordersitems__order_items_count"), 0),
            series_count=Count("ordersitems__series", distinct=True),
            items_count=Count("ordersitems__order_items_id", distinct=True),
        )

        client_id = request.GET.get("client_id")
        if client_id:
            qs = qs.filter(client__client_id=client_id)

        status = request.GET.get("status")
        if status:
            qs = qs.filter(orders_status__iexact=status)

        created_from = request.GET.get("created_from")
        if created_from:
            try:
                qs = qs.filter(orders_created_at__gte=_parse_iso_date(created_from, field="created_from"))
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

        created_to = request.GET.get("created_to")
        if created_to:
            try:
                qs = qs.filter(orders_created_at__lte=_parse_iso_date(created_to, field="created_to"))
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

        qs = qs.order_by("-orders_created_at")

        results = [
            {
                "id": order.orders_id,
                "client": _serialize_client(order.client),
                "status": order.orders_status,
                "created_at": order.orders_created_at,
                "shipped_at": order.orders_shipped_at,
                "delivered_at": order.orders_delivered_at,
                "cancel_reason": order.orders_cancel_reason,
                "total_quantity": float(order.total_quantity or 0),
                "series_count": order.series_count,
                "items_count": order.items_count,
            }
            for order in qs
        ]
        return JsonResponse({"count": len(results), "results": results})

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    client_id = payload.get("client_id")
    if not client_id:
        return JsonResponse({"error": "Field 'client_id' is required."}, status=400)

    items_data = payload.get("items") or []
    if not isinstance(items_data, list) or not items_data:
        return JsonResponse({"error": "Field 'items' must be a non-empty list."}, status=400)

    status_value = _clip(str(payload.get("status", "В ожидании")).strip() or "В ожидании", length=30)
    note_value = payload.get("status_note")

    try:
        created_at = _parse_iso_date(payload.get("created_at"), field="created_at") or timezone.now().date()
        shipped_at = _parse_iso_date(payload.get("shipped_at"), field="shipped_at")
        delivered_at = _parse_iso_date(payload.get("delivered_at"), field="delivered_at")
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    cancel_reason = _clip(payload.get("cancel_reason"), length=100)

    client = get_object_or_404(Clients, pk=client_id)

    with transaction.atomic():
        order = Orders.objects.create(
            client=client,
            orders_status=status_value,
            orders_created_at=created_at,
            orders_shipped_at=shipped_at,
            orders_delivered_at=delivered_at,
            orders_cancel_reason=cancel_reason,
        )

        for item in items_data:
            try:
                product_id = int(item["product_id"])
                quantity = int(item.get("quantity", 0))
                series_id = item.get("series_id")
                if series_id is not None:
                    series_id = int(series_id)
            except (KeyError, TypeError, ValueError):
                transaction.set_rollback(True)
                return JsonResponse(
                    {"error": "Each item must contain 'product_id' and integer 'quantity'. 'series_id' is optional."},
                    status=400,
                )

            if quantity <= 0:
                transaction.set_rollback(True)
                return JsonResponse({"error": "Item 'quantity' must be greater than zero."}, status=400)

            product = get_object_or_404(Products, pk=product_id)
            series = None
            if series_id is not None:
                series = get_object_or_404(Series, pk=series_id)
                if series.product_id != product.product_id:
                    transaction.set_rollback(True)
                    return JsonResponse(
                        {"error": f"Series '{series.series_id}' does not belong to product '{product.product_id}'."},
                        status=400,
                    )

            order_item = OrdersItems.objects.create(
                orders=order,
                product=product,
                series=series,
                order_items_count=quantity,
            )

            if series is not None:
                remaining_quantity = float(quantity)
                
                client_stocks = Stocks.objects.filter(
                    series=series,
                    client=client,
                    stocks_count__gt=0
                )
                
                public_stocks = Stocks.objects.filter(
                    series=series,
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
                            "error": f"Insufficient stock for series '{series.series_id}'. "
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
            order_status_history_from_stat=_clip(payload.get("status_from") or "Создан", length=30),
            order_status_history_to_status=_clip(status_value, length=30),
            order_status_history_chang_at=timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_status_history_note=_clip(note_value or "Created via API", length=30),
        )

    order = Orders.objects.select_related("client").get(pk=order.orders_id)
    response_payload = _serialize_order(order)
    return JsonResponse(response_payload, status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def order_detail_view(request, order_id: int):
    order = get_object_or_404(
        Orders.objects.select_related("client"),
        pk=order_id,
    )

    if request.method == "GET":
        return JsonResponse(_serialize_order(order))

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    status_updated = False
    status_from = order.orders_status

    if "status" in payload and payload["status"] is not None:
        new_status = _clip(str(payload["status"]).strip(), length=30)
        if new_status and new_status != order.orders_status:
            order.orders_status = new_status
            status_updated = True

    try:
        if "shipped_at" in payload:
            order.orders_shipped_at = _parse_iso_date(payload.get("shipped_at"), field="shipped_at")
        if "delivered_at" in payload:
            order.orders_delivered_at = _parse_iso_date(payload.get("delivered_at"), field="delivered_at")
        if "cancel_reason" in payload:
            order.orders_cancel_reason = _clip(payload.get("cancel_reason"), length=100)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    update_fields = ["orders_shipped_at", "orders_delivered_at", "orders_cancel_reason"]
    if status_updated:
        update_fields.append("orders_status")

    order.save(update_fields=update_fields)

    if status_updated:
        from ..models import OrderStatusHistory

        OrderStatusHistory.objects.create(
            orders=order,
            order_status_history_from_stat=_clip(status_from, length=30),
            order_status_history_to_status=_clip(order.orders_status, length=30),
            order_status_history_chang_at=timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_status_history_note=_clip(payload.get("status_note"), length=30),
        )

    order.refresh_from_db()
    return JsonResponse(_serialize_order(order))

