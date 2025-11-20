from __future__ import annotations

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..models import Series
from .utils import _color_filter, _serialize_series


@require_GET
def series_view(request):
    qs = Series.objects.select_related("product", "product__coating_types").annotate(
        available_quantity=Coalesce(Sum("stocks__stocks_count"), 0.0)
    )

    product_id = request.GET.get("product_id")
    if product_id:
        qs = qs.filter(product__product_id=product_id)

    series_query = request.GET.get("series")
    if series_query:
        try:
            series_id = int(series_query)
            qs = qs.filter(series_id=series_id)
        except ValueError:
            qs = qs.filter(series_name__icontains=series_query)

    color_query = request.GET.get("color")
    if color_query:
        qs = qs.filter(_color_filter(color_query))

    only_available = request.GET.get("in_stock", "false").lower() in {"1", "true", "yes"}
    if only_available:
        qs = qs.filter(available_quantity__gt=0)

    qs = qs.order_by("-available_quantity", "series_id")

    series_payload = [
        _serialize_series(series, available_quantity=getattr(series, "available_quantity", 0.0))
        for series in qs
    ]
    return JsonResponse({"count": len(series_payload), "results": series_payload})

