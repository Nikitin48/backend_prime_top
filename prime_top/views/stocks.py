from __future__ import annotations

from typing import Dict, List

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ..models import Clients, Stocks
from .utils import (
    ANALYSIS_NUMERIC_FIELDS,
    _analysis_range_filters_from_request,
    _color_filter,
)


@require_GET
def stocks_view(request):
    client_id = request.GET.get("client_id")
    include_public = request.GET.get("include_public", "false").lower() in {"1", "true", "yes"}
    personal_only = request.GET.get("personal_only", "true").lower() in {"1", "true", "yes"}

    stocks_qs = Stocks.objects.select_related(
        "client",
        "series",
        "series__product",
        "series__product__coating_types",
        "series__analyses",
    )

    client = None
    if client_id:
        client = get_object_or_404(Clients, pk=client_id)
        if personal_only:
            stocks_qs = stocks_qs.filter(client=client)
        elif include_public:
            stocks_qs = stocks_qs.filter(Q(client=client) | Q(client__isnull=True))
        else:
            stocks_qs = stocks_qs.filter(client=client)
    elif not include_public:
        stocks_qs = stocks_qs.filter(client__isnull=True)

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
        try:
            series_id = int(series_filter)
            stocks_qs = stocks_qs.filter(series__series_id=series_id)
        except ValueError:
            stocks_qs = stocks_qs.filter(series__series_name__icontains=series_filter)

    analysis_filters = _analysis_range_filters_from_request(request, prefix="series__analyses__")
    if analysis_filters:
        stocks_qs = stocks_qs.filter(**analysis_filters)

    stocks_qs = stocks_qs.order_by(
        F("client__client_name").asc(nulls_last=True),
        "series__product__coating_types__coating_type_nomenclatura",
        "series__series_id",
    )

    series_entries: List[Dict[str, object]] = []
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

        series_entries.append(
            {
                "stocks_id": stock.stocks_id,
                "series_id": series.series_id if series else None,
                "series_name": series.series_name if series else None,
                "production_date": series.series_production_date if series else None,
                "expire_date": series.series_expire_date if series else None,
                "quantity": float(stock.stocks_count or 0),
                "reserved_for_client": bool(stock.client_id),
                "client": {
                    "id": stock.client.client_id,
                    "name": stock.client.client_name,
                }
                if stock.client
                else None,
                "product": {
                    "id": product.product_id if product else None,
                    "name": product.product_name if product else None,
                    "color_code": product.color if product else None,
                }
                if product
                else None,
                "coating_type": {
                    "id": coating.coating_types_id if coating else None,
                    "name": coating.coating_type_name if coating else None,
                    "nomenclature": coating.coating_type_nomenclatura if coating else None,
                }
                if coating
                else None,
                "updated_at": stock.stocks_update_at,
                "analyses": analyses_payload,
            }
        )

    aggregation = (
        stocks_qs.values(
            "series__product__product_name",
            "series__product__coating_types__coating_type_nomenclatura",
            "series__product__coating_types__coating_type_name",
        )
        .annotate(
            total_quantity=Coalesce(Sum("stocks_count"), 0),
            series_count=Count("series", distinct=True),
        )
        .order_by("series__product__coating_types__coating_type_nomenclatura", "series__product__product_name")
    )

    summary = [
        {
            "product_name": entry["series__product__product_name"],
            "coating_type_name": entry["series__product__coating_types__coating_type_name"],
            "nomenclature": entry["series__product__coating_types__coating_type_nomenclatura"],
            "series_count": entry["series_count"],
            "total_quantity": float(entry["total_quantity"] or 0),
        }
        for entry in aggregation
    ]

    response = {
        "client": {
            "id": client.client_id,
            "name": client.client_name,
        }
        if client
        else None,
        "summary_by_nomenclature": summary,
        "series": series_entries,
    }
    return JsonResponse(response)


@require_GET
def available_stocks_view(request):
    """
    Получить доступные остатки для покупки.
    
    Возвращает:
    - public_stocks: все остатки, где client IS NULL (общедоступные остатки)
    - client_stocks: остатки для конкретного клиента (если передан client_id)
    
    Query параметры:
        - client_id: ID клиента для получения его персональных остатков
        - color: фильтр по цвету продукта
        - coating_type: фильтр по типу покрытия
        - series: фильтр по серии (ID или название)
        - min_quantity: минимальное количество в остатке
        - limit: ограничение количества результатов
        - offset: смещение для пагинации
    """
    # Получаем общедоступные остатки (client IS NULL)
    public_stocks_qs = Stocks.objects.select_related(
        "series",
        "series__product",
        "series__product__coating_types",
        "series__analyses",
    ).filter(
        client__isnull=True,
        stocks_count__gt=0
    )
    
    # Получаем клиентские остатки (если передан client_id)
    client_id = request.GET.get("client_id")
    client = None
    client_stocks_qs = Stocks.objects.none()
    
    if client_id:
        try:
            client = get_object_or_404(Clients, pk=int(client_id))
            client_stocks_qs = Stocks.objects.select_related(
                "client",
                "series",
                "series__product",
                "series__product__coating_types",
                "series__analyses",
            ).filter(
                client=client,
                stocks_count__gt=0
            )
        except ValueError:
            raise Http404("Query parameter 'client_id' must be an integer.")
    
    # Применяем фильтры к общедоступным остаткам
    color = request.GET.get("color")
    if color:
        public_stocks_qs = public_stocks_qs.filter(_color_filter(color, prefix="series__"))
        if client_id:
            client_stocks_qs = client_stocks_qs.filter(_color_filter(color, prefix="series__"))
    
    coating_type = request.GET.get("coating_type")
    if coating_type:
        coating_filter = (
            Q(series__product__coating_types__coating_type_name__icontains=coating_type)
            | Q(series__product__coating_types__coating_type_nomenclatura__icontains=coating_type)
        )
        public_stocks_qs = public_stocks_qs.filter(coating_filter)
        if client_id:
            client_stocks_qs = client_stocks_qs.filter(coating_filter)
    
    series_filter = request.GET.get("series")
    if series_filter:
        try:
            series_id = int(series_filter)
            public_stocks_qs = public_stocks_qs.filter(series__series_id=series_id)
            if client_id:
                client_stocks_qs = client_stocks_qs.filter(series__series_id=series_id)
        except ValueError:
            public_stocks_qs = public_stocks_qs.filter(series__series_name__icontains=series_filter)
            if client_id:
                client_stocks_qs = client_stocks_qs.filter(series__series_name__icontains=series_filter)
    
    min_quantity = request.GET.get("min_quantity")
    if min_quantity:
        try:
            min_qty = float(min_quantity)
            public_stocks_qs = public_stocks_qs.filter(stocks_count__gte=min_qty)
            if client_id:
                client_stocks_qs = client_stocks_qs.filter(stocks_count__gte=min_qty)
        except ValueError:
            raise Http404("Query parameter 'min_quantity' must be a number.")
    
    # Сортируем (используем F() для безопасной сортировки с null значениями)
    public_stocks_qs = public_stocks_qs.order_by(
        F("series__product__coating_types__coating_type_nomenclatura").asc(nulls_last=True),
        F("series__series_id").asc(nulls_last=True),
    )
    
    if client_id:
        client_stocks_qs = client_stocks_qs.order_by(
            F("series__product__coating_types__coating_type_nomenclatura").asc(nulls_last=True),
            F("series__series_id").asc(nulls_last=True),
        )
    
    # Применяем пагинацию к общедоступным остаткам
    public_total_count = public_stocks_qs.count()
    
    offset = request.GET.get("offset")
    if offset:
        try:
            offset_value = int(offset)
            if offset_value < 0:
                raise Http404("Query parameter 'offset' must be a non-negative integer.")
            public_stocks_qs = public_stocks_qs[offset_value:]
        except ValueError:
            raise Http404("Query parameter 'offset' must be an integer.")
    
    limit = request.GET.get("limit")
    if limit:
        try:
            limit_value = int(limit)
            if limit_value <= 0:
                raise Http404("Query parameter 'limit' must be a positive integer.")
            public_stocks_qs = public_stocks_qs[:limit_value]
        except ValueError:
            raise Http404("Query parameter 'limit' must be an integer.")
    
    # Сериализуем общедоступные остатки
    public_entries: List[Dict[str, object]] = []
    for stock in public_stocks_qs:
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
        
        public_entries.append({
            "stocks_id": stock.stocks_id,
            "series_id": series.series_id if series else None,
            "series_name": series.series_name if series else None,
            "production_date": series.series_production_date if series else None,
            "expire_date": series.series_expire_date if series else None,
            "quantity": float(stock.stocks_count or 0),
            "updated_at": stock.stocks_update_at,
            "color": product.color if product else None,
            "product": {
                "id": product.product_id if product else None,
                "name": product.product_name if product else None,
                "color_code": product.color if product else None,
                "price": product.product_price if product else None,
            } if product else None,
            "coating_type": {
                "id": coating.coating_types_id if coating else None,
                "name": coating.coating_type_name if coating else None,
                "nomenclature": coating.coating_type_nomenclatura if coating else None,
            } if coating else None,
            "analyses": analyses_payload,
        })
    
    # Сериализуем клиентские остатки
    client_entries: List[Dict[str, object]] = []
    if client_id:
        for stock in client_stocks_qs:
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
            
            client_entries.append({
                "stocks_id": stock.stocks_id,
                "series_id": series.series_id if series else None,
                "series_name": series.series_name if series else None,
                "production_date": series.series_production_date if series else None,
                "expire_date": series.series_expire_date if series else None,
                "quantity": float(stock.stocks_count or 0),
                "reserved_for_client": bool(stock.stocks_is_reserved_for_client),
                "updated_at": stock.stocks_update_at,
                "color": product.color if product else None,
                "product": {
                    "id": product.product_id if product else None,
                    "name": product.product_name if product else None,
                    "color_code": product.color if product else None,
                    "price": product.product_price if product else None,
                } if product else None,
                "coating_type": {
                    "id": coating.coating_types_id if coating else None,
                    "name": coating.coating_type_name if coating else None,
                    "nomenclature": coating.coating_type_nomenclatura if coating else None,
                } if coating else None,
                "analyses": analyses_payload,
            })
    
    response = {
        "public_stocks": {
            "count": len(public_entries),
            "total_count": public_total_count,
            "total_quantity": float(sum(item["quantity"] for item in public_entries)),
            "results": public_entries,
        },
    }
    
    if client_id:
        response["client"] = {
            "id": client.client_id,
            "name": client.client_name,
        }
        response["client_stocks"] = {
            "count": len(client_entries),
            "total_quantity": float(sum(item["quantity"] for item in client_entries)),
            "results": client_entries,
        }
    
    return JsonResponse(response)

