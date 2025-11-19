import math
from datetime import timedelta

from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone

from prime_top.models import Clients, Orders, OrdersItems, Products, Series, Stocks


def landing_stats_view(request):
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)

    orders_last_30 = Orders.objects.filter(orders_created_at__gte=last_30_days).count()
    orders_per_day = math.ceil(orders_last_30 / 30) if orders_last_30 else 0

    data = {
        "projects": Orders.objects.count(),
        "series": Series.objects.count(),
        "orders_per_day": orders_per_day,
        "logistics_hubs": Stocks.objects.filter(client__isnull=True).count(),
        "clients": Clients.objects.count(),
    }
    return JsonResponse(data)


def landing_popular_products_view(request):
    try:
        limit = int(request.GET.get("limit", 6))
    except (TypeError, ValueError):
        limit = 6

    top_items = (
        OrdersItems.objects.values("product_id")
        .annotate(total_quantity=Sum("order_items_count"))
        .order_by("-total_quantity")[:limit]
    )

    product_ids = [item["product_id"] for item in top_items]
    products = {
        product.product_id: product
        for product in Products.objects.filter(product_id__in=product_ids).select_related("coating_types")
    }

    results = []
    for item in top_items:
        product = products.get(item["product_id"])
        if product is None:
            continue
        results.append(
            {
                "id": product.product_id,
                "name": product.product_name,
                "color_code": product.color,
                "price": product.product_price,
                "coating_type": {
                    "id": product.coating_types.coating_types_id,
                    "name": product.coating_types.coating_type_name,
                    "nomenclature": product.coating_types.coating_type_nomenclatura,
                },
                "orders_count": item["total_quantity"] or 0,
            }
        )

    return JsonResponse({"results": results})
