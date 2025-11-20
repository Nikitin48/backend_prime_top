from __future__ import annotations

from typing import List

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from ..models import Clients, Orders, OrdersItems, Users
from .utils import (
    _clip,
    _color_filter,
    _orders_summary_payload,
    _parse_json_body,
    require_client_auth,
    _serialize_client,
)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def clients_view(request):
    if request.method == "GET":
        search = request.GET.get("search")
        qs = Clients.objects.all()
        if search:
            qs = qs.filter(
                Q(client_name__icontains=search)
                | Q(client_email__icontains=search)
            )
        qs = qs.order_by("client_name")
        clients = [_serialize_client(client) for client in qs]
        return JsonResponse({"count": len(clients), "results": clients})

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    name = payload.get("name")
    email = payload.get("email")
    if not name or not email:
        return JsonResponse(
            {"error": "Fields 'name' and 'email' are required."},
            status=400,
        )

    client = Clients.objects.create(
        client_name=str(name).strip(),
        client_email=str(email).strip(),
    )
    return JsonResponse(_serialize_client(client), status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def client_detail_view(request, client_id: int):
    client = get_object_or_404(Clients, pk=client_id)

    if request.method == "GET":
        return JsonResponse(_serialize_client(client))

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    updated_fields: List[str] = []
    if "name" in payload and payload["name"] is not None:
        client.client_name = str(payload["name"]).strip()
        updated_fields.append("client_name")
    if "email" in payload and payload["email"] is not None:
        client.client_email = str(payload["email"]).strip()
        updated_fields.append("client_email")

    if updated_fields:
        client.save(update_fields=updated_fields)

    return JsonResponse(_serialize_client(client))


@require_GET
def client_orders_summary(request, client_id: int):
    client = get_object_or_404(Clients, pk=client_id)

    orders_qs = Orders.objects.filter(client=client)
    summary = _orders_summary_payload(orders_qs)

    cancel_details = list(
        orders_qs.filter(orders_status__iexact="cancelled")
        .exclude(Q(orders_cancel_reason__isnull=True) | Q(orders_cancel_reason__exact=""))
        .values("orders_cancel_reason")
        .annotate(
            cancelled_orders=Count("orders_id", distinct=True),
            cancelled_series=Count("ordersitems__series", distinct=True),
            cancelled_quantity=Coalesce(Sum("ordersitems__order_items_count"), 0),
        )
        .order_by("-cancelled_orders")
    )

    data = {
        "client": {
            "id": client.client_id,
            "name": client.client_name,
            "email": client.client_email,
        },
        "summary": summary,
        "cancel_details": [
            {
                "reason": entry["orders_cancel_reason"],
                "orders_count": entry["cancelled_orders"],
                "series_count": entry["cancelled_series"],
                "total_quantity": float(entry["cancelled_quantity"] or 0),
            }
            for entry in cancel_details
        ],
        "period": {
            "first_order": orders_qs.order_by("orders_created_at").values_list("orders_created_at", flat=True).first(),
            "last_order": orders_qs.order_by("-orders_created_at").values_list("orders_created_at", flat=True).first(),
        },
    }

    return JsonResponse(data)


@require_GET
def client_orders_detail(request, client_id: int):
    client = get_object_or_404(Clients, pk=client_id)

    item_qs = (
        OrdersItems.objects.select_related(
            "orders",
            "product",
            "product__coating_types",
            "series",
        )
        .filter(orders__client=client)
        .order_by("-orders__orders_created_at", "orders__orders_id")
    )

    status = request.GET.get("status")
    if status:
        item_qs = item_qs.filter(orders__orders_status__iexact=status)

    series_query = request.GET.get("series")
    if series_query:
        try:
            # Try to filter by series_id if it's a number
            series_id = int(series_query)
            item_qs = item_qs.filter(series__series_id=series_id)
        except ValueError:
            # Otherwise filter by series_name
            item_qs = item_qs.filter(series__series_name__icontains=series_query)

    color = request.GET.get("color")
    if color:
        item_qs = item_qs.filter(_color_filter(color))

    items = []
    for item in item_qs:
        product = item.product
        coating = product.coating_types
        order = item.orders
        items.append(
            {
                "order_id": order.orders_id,
                "series_id": item.series.series_id if item.series else None,
                "status": order.orders_status,
                "created_at": order.orders_created_at,
                "shipped_at": order.orders_shipped_at,
                "delivered_at": order.orders_delivered_at,
                "cancel_reason": order.orders_cancel_reason,
                "quantity": item.order_items_count,
                "product": {
                    "id": product.product_id,
                    "name": product.product_name,
                    "color_code": product.color,
                },
                "coating_type": {
                    "id": coating.coating_types_id if coating else None,
                    "name": coating.coating_type_name if coating else None,
                    "nomenclature": coating.coating_type_nomenclatura if coating else None,
                },
            }
        )

    data = {
        "client": {
            "id": client.client_id,
            "name": client.client_name,
        },
        "count": len(items),
        "orders": items,
    }
    return JsonResponse(data)


@require_client_auth
@require_GET
def client_users_view(request, client_id: int):
    client = get_object_or_404(Clients, pk=client_id)

    # Only allow fetching users of own organization
    if request.authenticated_client.client_id != client.client_id:
        return JsonResponse({"error": "Forbidden"}, status=403)

    users = Users.objects.filter(client=client).order_by("user_email")
    payload = [
        {
          "id": user.user_id,
          "email": user.user_email,
          "first_name": getattr(user, "user_name", None),
          "last_name": getattr(user, "user_surname", None),
          "created_at": user.user_created_at,
        }
        for user in users
    ]
    return JsonResponse(
        {
            "client": {
                "id": client.client_id,
                "name": client.client_name,
                "email": client.client_email,
            },
            "count": len(payload),
            "users": payload,
        }
    )

