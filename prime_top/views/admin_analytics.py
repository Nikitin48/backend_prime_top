from __future__ import annotations

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from ..models import Clients, CoatingTypes, OrdersItems, Products, Series, Stocks
from .utils import (
    _parse_iso_date,
    require_admin_auth,
)


@csrf_exempt
@require_GET
@require_admin_auth
def admin_analytics_top_products(request):
    created_from = request.GET.get("created_from")
    created_to = request.GET.get("created_to")
    client_id = request.GET.get("client_id")
    coating_type_id = request.GET.get("coating_type_id")
    limit = int(request.GET.get("limit", 10))

    items_qs = OrdersItems.objects.select_related(
        "orders",
        "product",
        "product__coating_types",
    ).filter(orders__orders_created_at__isnull=False)

    if created_from:
        try:
            from_date = _parse_iso_date(created_from, field="created_from")
            items_qs = items_qs.filter(orders__orders_created_at__gte=from_date)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if created_to:
        try:
            to_date = _parse_iso_date(created_to, field="created_to")
            items_qs = items_qs.filter(orders__orders_created_at__lte=to_date)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if client_id:
        try:
            items_qs = items_qs.filter(orders__client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    if coating_type_id:
        try:
            items_qs = items_qs.filter(product__coating_types_id=int(coating_type_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'coating_type_id'."}, status=400)

    top_by_quantity_data = (
        items_qs.values("product_id")
        .annotate(
            total_quantity=Coalesce(Sum("order_items_count"), 0),
            orders_count=Count("orders__orders_id", distinct=True),
        )
        .order_by("-total_quantity")[:limit]
    )

    top_by_quantity = []
    for item in top_by_quantity_data:
        product = Products.objects.select_related("coating_types").get(pk=item["product_id"])
        product_items = items_qs.filter(product_id=product.product_id)
        total_revenue = sum(float(oi.order_items_count) * float(oi.product.product_price) for oi in product_items)

        top_by_quantity.append(
            {
                "product_id": product.product_id,
                "product_name": product.product_name,
                "coating_type": {
                    "id": product.coating_types.coating_types_id,
                    "name": product.coating_types.coating_type_name,
                    "nomenclature": product.coating_types.coating_type_nomenclatura,
                },
                "total_quantity": float(item["total_quantity"]),
                "orders_count": item["orders_count"],
                "total_revenue": total_revenue,
            }
        )

    product_revenues = {}
    for item in items_qs.select_related("product"):
        product_id = item.product_id
        revenue = float(item.order_items_count) * float(item.product.product_price)
        if product_id not in product_revenues:
            product_revenues[product_id] = {"revenue": 0, "orders": set()}
        product_revenues[product_id]["revenue"] += revenue
        product_revenues[product_id]["orders"].add(item.orders_id)

    top_by_revenue_data = sorted(product_revenues.items(), key=lambda x: x[1]["revenue"], reverse=True)[:limit]

    top_by_revenue = []
    for product_id, data in top_by_revenue_data:
        product = Products.objects.select_related("coating_types").get(pk=product_id)
        product_items = items_qs.filter(product_id=product_id)
        total_quantity = sum(float(oi.order_items_count) for oi in product_items)

        top_by_revenue.append(
            {
                "product_id": product.product_id,
                "product_name": product.product_name,
                "coating_type": {
                    "id": product.coating_types.coating_types_id,
                    "name": product.coating_types.coating_type_name,
                    "nomenclature": product.coating_types.coating_type_nomenclatura,
                },
                "total_quantity": total_quantity,
                "orders_count": len(data["orders"]),
                "total_revenue": data["revenue"],
            }
        )

    top_by_orders_data = (
        items_qs.values("product_id")
        .annotate(orders_count=Count("orders__orders_id", distinct=True))
        .order_by("-orders_count")[:limit]
    )

    top_by_orders = []
    for item in top_by_orders_data:
        product = Products.objects.select_related("coating_types").get(pk=item["product_id"])
        product_items = items_qs.filter(product_id=product.product_id)
        total_quantity = sum(float(oi.order_items_count) for oi in product_items)
        total_revenue = sum(float(oi.order_items_count) * float(oi.product.product_price) for oi in product_items)

        top_by_orders.append(
            {
                "product_id": product.product_id,
                "product_name": product.product_name,
                "coating_type": {
                    "id": product.coating_types.coating_types_id,
                    "name": product.coating_types.coating_type_name,
                    "nomenclature": product.coating_types.coating_type_nomenclatura,
                },
                "total_quantity": total_quantity,
                "orders_count": item["orders_count"],
                "total_revenue": total_revenue,
            }
        )

    response = {
        "period": {
            "from": created_from,
            "to": created_to,
        },
        "top_by_quantity": top_by_quantity,
        "top_by_revenue": top_by_revenue,
        "top_by_orders": top_by_orders,
    }

    return JsonResponse(response)


@csrf_exempt
@require_GET
@require_admin_auth
def admin_analytics_top_series(request):
    created_from = request.GET.get("created_from")
    created_to = request.GET.get("created_to")
    client_id = request.GET.get("client_id")
    limit = int(request.GET.get("limit", 10))

    items_qs = OrdersItems.objects.select_related(
        "orders",
        "series",
        "series__product",
        "product",
    ).filter(orders__orders_created_at__isnull=False, series__isnull=False)

    if created_from:
        try:
            from_date = _parse_iso_date(created_from, field="created_from")
            items_qs = items_qs.filter(orders__orders_created_at__gte=from_date)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if created_to:
        try:
            to_date = _parse_iso_date(created_to, field="created_to")
            items_qs = items_qs.filter(orders__orders_created_at__lte=to_date)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if client_id:
        try:
            items_qs = items_qs.filter(orders__client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    top_series_data = (
        items_qs.values("series_id")
        .annotate(
            total_sold=Coalesce(Sum("order_items_count"), 0),
            orders_count=Count("orders__orders_id", distinct=True),
        )
        .order_by("-total_sold")[:limit]
    )

    top_series = []
    for item in top_series_data:
        series = Series.objects.select_related("product").get(pk=item["series_id"])

        stocks_qs = Stocks.objects.filter(series_id=series.series_id)
        current_stock = sum(float(s.stocks_count) for s in stocks_qs)

        top_series.append(
            {
                "series_id": series.series_id,
                "series_name": series.series_name,
                "product": {
                    "id": series.product.product_id,
                    "name": series.product.product_name,
                },
                "production_date": series.series_production_date,
                "total_sold": float(item["total_sold"]),
                "orders_count": item["orders_count"],
                "current_stock": current_stock,
            }
        )

    response = {"top_series": top_series}

    return JsonResponse(response)


@csrf_exempt
@require_GET
@require_admin_auth
def admin_analytics_top_coating_types(request):
    created_from = request.GET.get("created_from")
    created_to = request.GET.get("created_to")
    client_id = request.GET.get("client_id")

    items_qs = OrdersItems.objects.select_related(
        "orders",
        "product",
        "product__coating_types",
    ).filter(orders__orders_created_at__isnull=False)

    if created_from:
        try:
            from_date = _parse_iso_date(created_from, field="created_from")
            items_qs = items_qs.filter(orders__orders_created_at__gte=from_date)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if created_to:
        try:
            to_date = _parse_iso_date(created_to, field="created_to")
            items_qs = items_qs.filter(orders__orders_created_at__lte=to_date)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if client_id:
        try:
            items_qs = items_qs.filter(orders__client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    coating_types_data = (
        items_qs.values("product__coating_types_id")
        .annotate(
            total_quantity=Coalesce(Sum("order_items_count"), 0),
            orders_count=Count("orders__orders_id", distinct=True),
        )
        .order_by("-total_quantity")
    )

    total_quantity_all = sum(float(item["total_quantity"]) for item in coating_types_data)
    total_revenue_all = 0
    total_orders_all = set()

    for item in items_qs:
        total_revenue_all += float(item.order_items_count) * float(item.product.product_price)
        total_orders_all.add(item.orders_id)

    coating_types_breakdown = []
    for item in coating_types_data:
        coating_type = CoatingTypes.objects.get(pk=item["product__coating_types_id"])

        type_items = items_qs.filter(product__coating_types_id=coating_type.coating_types_id)
        total_revenue = sum(float(oi.order_items_count) * float(oi.product.product_price) for oi in type_items)

        percentage = (float(item["total_quantity"]) / total_quantity_all * 100) if total_quantity_all > 0 else 0

        coating_types_breakdown.append(
            {
                "coating_type_id": coating_type.coating_types_id,
                "coating_type_name": coating_type.coating_type_name,
                "nomenclature": coating_type.coating_type_nomenclatura,
                "total_quantity": float(item["total_quantity"]),
                "total_revenue": total_revenue,
                "orders_count": item["orders_count"],
                "percentage_of_total": round(percentage, 2),
            }
        )

    response = {
        "coating_types_breakdown": coating_types_breakdown,
        "total": {
            "quantity": total_quantity_all,
            "revenue": total_revenue_all,
            "orders_count": len(total_orders_all),
        },
    }

    return JsonResponse(response)

