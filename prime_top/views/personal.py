from __future__ import annotations

from typing import Dict, List

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..models import Orders, Stocks
from .utils import (
    ANALYSIS_NUMERIC_FIELDS,
    _analysis_range_filters_from_request,
    _color_filter,
    _orders_summary_payload,
    _parse_iso_date,
    _serialize_client,
    _serialize_order,
    _serialize_product,
    _serialize_series,
    require_client_auth,
)


@require_client_auth
@require_GET
def my_orders_current_view(request):
    client = request.authenticated_client

    include_items = request.GET.get("include_items", "false").lower() in {"1", "true", "yes"}
    limit_param = request.GET.get("limit")

    statuses: List[str] = []
    for value in request.GET.getlist("status"):
        statuses.extend([item.strip() for item in value.split(",") if item.strip()])

    orders_qs = Orders.objects.filter(client=client).select_related("client")
    if statuses:
        status_filter = Q()
        for status in statuses:
            status_filter |= Q(orders_status__iexact=status)
        orders_qs = orders_qs.filter(status_filter)
    else:
        orders_qs = (
            orders_qs.filter(orders_delivered_at__isnull=True)
            .exclude(orders_status__icontains="cancel")
            .exclude(orders_status__icontains="отмен")
        )

    summary = _orders_summary_payload(orders_qs)
    total_count = orders_qs.count()

    orders_qs = orders_qs.order_by("-orders_created_at", "-orders_id")
    if limit_param:
        try:
            limit_value = int(limit_param)
            if limit_value > 0:
                orders_qs = orders_qs[:limit_value]
        except ValueError:
            return JsonResponse({"error": "Query parameter 'limit' must be a positive integer."}, status=400)

    orders_payload = [_serialize_order(order, include_items=include_items) for order in orders_qs]

    response = {
        "client": _serialize_client(client),
        "summary": summary,
        "total_count": total_count,
        "count": len(orders_payload),
        "orders": orders_payload,
    }
    return JsonResponse(response)


@require_client_auth
@require_GET
def my_orders_history_view(request):
    client = request.authenticated_client

    include_items = request.GET.get("include_items", "true").lower() in {"1", "true", "yes"}
    limit_param = request.GET.get("limit")

    orders_qs = Orders.objects.filter(client=client).select_related("client")

    statuses: List[str] = []
    for value in request.GET.getlist("status"):
        statuses.extend([item.strip() for item in value.split(",") if item.strip()])
    if statuses:
        status_filter = Q()
        for status in statuses:
            status_filter |= Q(orders_status__iexact=status)
        orders_qs = orders_qs.filter(status_filter)

    try:
        created_from = request.GET.get("created_from")
        if created_from:
            orders_qs = orders_qs.filter(orders_created_at__gte=_parse_iso_date(created_from, field="created_from"))

        created_to = request.GET.get("created_to")
        if created_to:
            orders_qs = orders_qs.filter(orders_created_at__lte=_parse_iso_date(created_to, field="created_to"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    summary = _orders_summary_payload(orders_qs)
    total_count = orders_qs.count()

    orders_qs = orders_qs.order_by("-orders_created_at", "-orders_id")
    if limit_param:
        try:
            limit_value = int(limit_param)
            if limit_value > 0:
                orders_qs = orders_qs[:limit_value]
        except ValueError:
            return JsonResponse({"error": "Query parameter 'limit' must be a positive integer."}, status=400)

    orders_payload = [_serialize_order(order, include_items=include_items) for order in orders_qs]

    return JsonResponse(
        {
            "client": _serialize_client(client),
            "summary": summary,
            "total_count": total_count,
            "count": len(orders_payload),
            "orders": orders_payload,
        }
    )


@require_client_auth
@require_GET
def my_stocks_view(request):
    client = request.authenticated_client

    include_public = request.GET.get("include_public", "true").lower() in {"1", "true", "yes"}
    personal_only = request.GET.get("personal_only", "false").lower() in {"1", "true", "yes"}

    stocks_qs = Stocks.objects.select_related(
        "client",
        "series",
        "series__product",
        "series__product__coating_types",
        "series__analyses",
    )

    if personal_only:
        stocks_qs = stocks_qs.filter(client=client)
    else:
        base_filter = Q(client=client)
        if include_public:
            base_filter |= Q(client__isnull=True)
        stocks_qs = stocks_qs.filter(base_filter)

    color = request.GET.get("color")
    if color:
        stocks_qs = stocks_qs.filter(_color_filter(color, prefix="series__"))

    coating_type = request.GET.get("coating_type")
    if coating_type:
        stocks_qs = stocks_qs.filter(
            Q(series__product__coating_types__coating_type_name__icontains=coating_type)
            | Q(series__product__coating_types__coating_type_nomenclatura__icontains=coating_type)
        )

    series_filter = request.GET.get("series")
    if series_filter:
        stocks_qs = stocks_qs.filter(series__series_id__icontains=series_filter)

    analysis_filters = _analysis_range_filters_from_request(request, prefix="series__analyses__")
    if analysis_filters:
        stocks_qs = stocks_qs.filter(**analysis_filters)

    stocks_qs = stocks_qs.order_by(
        F("client__client_name").asc(nulls_last=True),
        "series__product__coating_types__coating_type_nomenclatura",
        "series__series_id",
    )

    personal_entries: List[Dict[str, object]] = []
    public_entries: List[Dict[str, object]] = []

    for stock in stocks_qs:
        series = stock.series
        product = series.product if series else None
        coating = product.coating_types if product else None
        analysis_obj = getattr(series, "analyses", None) if series else None

        analyses_payload = None
        if analysis_obj:
            analyses_payload = {
                field: getattr(analysis_obj, field)
                for field in ANALYSIS_NUMERIC_FIELDS
                if getattr(analysis_obj, field) is not None
            }

        payload = {
            "stocks_id": stock.stocks_id,
            "scope": "personal" if stock.client_id else "public",
            "quantity": float(stock.stocks_count or 0),
            "updated_at": stock.stocks_update_at,
            "series": _serialize_series(series) if series else None,
            "product": _serialize_product(product) if product else None,
            "coating_type": {
                "id": coating.coating_types_id if coating else None,
                "name": coating.coating_type_name if coating else None,
                "nomenclature": coating.coating_type_nomenclatura if coating else None,
            }
            if coating
            else None,
            "analyses": analyses_payload,
        }

        if stock.client_id:
            personal_entries.append(payload)
        else:
            public_entries.append(payload)

    summary_rows = (
        stocks_qs.values(
            "client_id",
            "series__product__product_name",
            "series__product__coating_types__coating_type_name",
            "series__product__coating_types__coating_type_nomenclatura",
        )
        .annotate(
            total_quantity=Coalesce(Sum("stocks_count"), 0),
            series_count=Count("series", distinct=True),
        )
        .order_by("series__product__coating_types__coating_type_nomenclatura", "series__product__product_name")
    )

    summary = [
        {
            "scope": "personal" if entry["client_id"] else "public",
            "product_name": entry["series__product__product_name"],
            "coating_type_name": entry["series__product__coating_types__coating_type_name"],
            "nomenclature": entry["series__product__coating_types__coating_type_nomenclatura"],
            "series_count": entry["series_count"],
            "total_quantity": float(entry["total_quantity"] or 0),
        }
        for entry in summary_rows
    ]

    response = {
        "client": _serialize_client(client),
        "filters": {
            "include_public": include_public,
            "personal_only": personal_only,
        },
        "summary_by_nomenclature": summary,
        "personal_total_quantity": float(sum(item["quantity"] for item in personal_entries)),
        "public_total_quantity": float(sum(item["quantity"] for item in public_entries)),
        "personal_count": len(personal_entries),
        "public_count": len(public_entries),
        "personal": personal_entries,
        "public": public_entries,
    }
    return JsonResponse(response)

