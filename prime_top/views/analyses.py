from __future__ import annotations

from typing import Dict

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ..models import Analyses, Clients, Series
from .utils import ANALYSIS_NUMERIC_FIELDS, _analysis_range_filters_from_request


@require_GET
def analyses_view(request):
    accessible_only = request.GET.get("accessible_only", "true").lower() in {"1", "true", "yes"}
    client_id = request.GET.get("client_id")
    client = None
    if client_id:
        client = get_object_or_404(Clients, pk=client_id)

    analyses_qs = Analyses.objects.select_related(
        "series",
        "series__product",
        "series__product__coating_types",
    ).annotate(
        available_quantity=Coalesce(Sum("series__stocks__stocks_count"), 0.0),
        reserved_clients=Count("series__stocks__client", distinct=True),
    )

    if client:
        if accessible_only:
            analyses_qs = analyses_qs.filter(
                Q(series__stocks__client=client) | Q(series__stocks__client__isnull=True)
            )
        else:
            analyses_qs = analyses_qs.filter(series__stocks__client=client)

    analyses_qs = analyses_qs.filter(series__stocks__stocks_count__gt=0).distinct()

    range_filters = _analysis_range_filters_from_request(request)
    if range_filters:
        analyses_qs = analyses_qs.filter(**range_filters)

    sort = request.GET.get("sort")
    if sort:
        sort_field = sort.lstrip("-")
        if sort_field not in ANALYSIS_NUMERIC_FIELDS and sort_field != "available_quantity":
            raise Http404(f"Unsupported sort field '{sort_field}'.")
        analyses_qs = analyses_qs.order_by(sort)
    else:
        analyses_qs = analyses_qs.order_by("-available_quantity", "series__series_id")

    limit = request.GET.get("limit")
    if limit:
        try:
            limit_value = int(limit)
            if limit_value > 0:
                analyses_qs = analyses_qs[:limit_value]
        except ValueError:
            raise Http404("Query parameter 'limit' must be a positive integer.")

    def serialize_analysis(analysis: Analyses) -> Dict[str, object]:
        series_obj: Series = analysis.series
        product = series_obj.product
        coating = product.coating_types if product else None

        payload = {
            "series_id": series_obj.series_id,
            "series_name": series_obj.series_name,
            "production_date": series_obj.series_production_date,
            "expire_date": series_obj.series_expire_date,
            "available_quantity": float(getattr(analysis, "available_quantity", 0.0) or 0.0),
            "reserved_for_clients": bool(getattr(analysis, "reserved_clients", 0)),
            "metrics": {},
            "product": {
                "id": product.product_id if product else None,
                "name": product.product_name if product else None,
                "color_code": product.color if product else None,
            },
            "coating_type": {
                "id": coating.coating_types_id if coating else None,
                "name": coating.coating_type_name if coating else None,
                "nomenclature": coating.coating_type_nomenclatura if coating else None,
            }
            if coating
            else None,
        }

        for field in ANALYSIS_NUMERIC_FIELDS:
            payload["metrics"][field] = getattr(analysis, field)

        return payload

    results = [serialize_analysis(analysis) for analysis in analyses_qs]

    response = {
        "client": {
            "id": client.client_id,
            "name": client.client_name,
        }
        if client
        else None,
        "count": len(results),
        "results": results,
    }
    return JsonResponse(response)

