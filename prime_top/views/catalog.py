from __future__ import annotations

from typing import Dict, List

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ..models import Analyses, Clients, CoatingTypes, Products, Series, Stocks
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from .utils import (
    ANALYSIS_NUMERIC_FIELDS,
    _analysis_range_filters_from_request,
    _color_filter,
    _normalized_color,
    _serialize_product,
    _serialize_series,
)


@require_GET
def products_view(request):
    qs = Products.objects.select_related("coating_types").all()

    coating_type_id = request.GET.get("coating_type_id")
    if coating_type_id:
        try:
            qs = qs.filter(coating_types__coating_types_id=int(coating_type_id))
        except ValueError:
            raise Http404("Query parameter 'coating_type_id' must be an integer.")

    name_query = request.GET.get("name")
    if name_query:
        qs = qs.filter(product_name__icontains=name_query)

    nomenclature_query = request.GET.get("nomenclature")
    if nomenclature_query:
        qs = qs.filter(coating_types__coating_type_nomenclatura__icontains=nomenclature_query)

    color_query = request.GET.get("color")
    if color_query:
        color_filter = (
            Q(product_name__icontains=color_query)
            | Q(coating_types__coating_type_name__icontains=color_query)
            | Q(coating_types__coating_type_nomenclatura__icontains=color_query)
        )
        normalized = _normalized_color(color_query)
        if normalized:
            try:
                color_filter |= Q(color=int(normalized))
            except ValueError:
                pass
            color_filter |= Q(product_name__icontains=normalized)
            color_filter |= Q(coating_types__coating_type_nomenclatura__icontains=normalized)
        qs = qs.filter(color_filter)

    min_price = request.GET.get("min_price")
    if min_price:
        try:
            qs = qs.filter(product_price__gte=int(min_price))
        except ValueError:
            raise Http404("Query parameter 'min_price' must be an integer.")

    max_price = request.GET.get("max_price")
    if max_price:
        try:
            qs = qs.filter(product_price__lte=int(max_price))
        except ValueError:
            raise Http404("Query parameter 'max_price' must be an integer.")

    qs = qs.order_by("coating_types__coating_type_nomenclatura", "product_name")
    
    total_count = qs.count()
    
    offset = request.GET.get("offset")
    if offset:
        try:
            offset_value = int(offset)
            if offset_value < 0:
                raise Http404("Query parameter 'offset' must be a non-negative integer.")
            qs = qs[offset_value:]
        except ValueError:
            raise Http404("Query parameter 'offset' must be an integer.")
    
    limit = request.GET.get("limit")
    if limit:
        try:
            limit_value = int(limit)
            if limit_value <= 0:
                raise Http404("Query parameter 'limit' must be a positive integer.")
            qs = qs[:limit_value]
        except ValueError:
            raise Http404("Query parameter 'limit' must be an integer.")
    
    products = [_serialize_product(product) for product in qs]
    return JsonResponse({"count": total_count, "results": products})


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
            # Try to filter by series_id if it's a number
            series_id = int(series_query)
            qs = qs.filter(series_id=series_id)
        except ValueError:
            # Otherwise filter by series_name
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
            # Try to filter by series_id if it's a number
            series_id = int(series_filter)
            stocks_qs = stocks_qs.filter(series__series_id=series_id)
        except ValueError:
            # Otherwise filter by series_name
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


@require_GET
def coating_types_view(request):
    """
    Получить список всех категорий типов покрытий (coating types).
    
    Возвращает все доступные категории типов покрытий, отсортированные
    по номенклатуре. В будущем количество категорий может увеличиваться.
    
    Query параметры:
        - sort: порядок сортировки (по умолчанию: nomenclature)
                 Возможные значения: 'id', 'name', 'nomenclature', '-id', '-name', '-nomenclature'
    
    Returns:
        JSON response с полем 'count' (количество категорий) и 'results' (список категорий)
    """
    qs = CoatingTypes.objects.all()
    
    # Поддержка сортировки
    sort = request.GET.get("sort", "nomenclature")
    valid_sort_fields = {
        "id", "-id",
        "name", "-name",
        "nomenclature", "-nomenclature",
    }
    
    sort_mapping = {
        "id": "coating_types_id",
        "-id": "-coating_types_id",
        "name": "coating_type_name",
        "-name": "-coating_type_name",
        "nomenclature": "coating_type_nomenclatura",
        "-nomenclature": "-coating_type_nomenclatura",
    }
    
    if sort in valid_sort_fields:
        qs = qs.order_by(sort_mapping[sort])
    else:
        qs = qs.order_by("coating_type_nomenclatura")
    
    results = [
        {
            "id": coating_type.coating_types_id,
            "name": coating_type.coating_type_name,
            "nomenclature": coating_type.coating_type_nomenclatura,
        }
        for coating_type in qs
    ]
    
    return JsonResponse({
        "count": len(results),
        "results": results,
    })


@require_GET
def product_detail_view(request, product_id):
    """
    Получить детальную информацию о продукте по его ID.
    
    Возвращает все поля продукта, все связанные серии и для каждой серии
    все поля из таблицы analyses.
    """
    product = get_object_or_404(
        Products.objects.select_related("coating_types"),
        pk=product_id
    )
    
    # Получаем все серии продукта с предзагрузкой analyses и информацией о stocks
    series_list = Series.objects.filter(product=product).select_related("analyses").annotate(
        available_quantity=Coalesce(Sum("stocks__stocks_count"), 0.0)
    )
    
    # Сериализуем продукт
    coating = product.coating_types
    product_data = {
        "id": product.product_id,
        "name": product.product_name,
        "color_code": product.color,
        "price": product.product_price,
        "coating_type": {
            "id": coating.coating_types_id if coating else None,
            "name": coating.coating_type_name if coating else None,
            "nomenclature": coating.coating_type_nomenclatura if coating else None,
        },
    }
    
    # Сериализуем серии с их analyses и информацией о stocks
    series_data = []
    for series in series_list:
        available_qty = float(getattr(series, "available_quantity", 0.0) or 0.0)
        series_item = {
            "id": series.series_id,
            "name": series.series_name,
            "production_date": series.series_production_date,
            "expire_date": series.series_expire_date,
            "available_quantity": available_qty,
            "in_stock": available_qty > 0,
        }
        
        # Добавляем все поля из analyses, если они есть
        analyses_data = {}
        analysis = getattr(series, "analyses", None)
        if analysis:
            # Получаем все поля из модели Analyses
            # Числовые поля (FloatField)
            float_fields = [
                "analyses_blesk_pri_60_grad",
                "analyses_uslovnaya_vyazkost",
                "analyses_delta_e",
                "analyses_delta_l",
                "analyses_delta_a",
                "analyses_color_diff_deltae_d8",
                "analyses_delta_b",
                "analyses_vremya_sushki",
                "analyses_pikovaya_temperatura",
                "analyses_tolschina_dlya_grunta",
                "analyses_adgeziya",
                "analyses_stoikost_k_rastvor",
                "analyses_kolvo_vykr_s_partii",
                "analyses_unnamed_16",
                "analyses_stepen_peretira",
                "analyses_tverd_vesches_po_v",
                "analyses_tolsch_plenki_zhidk",
                "analyses_tolsch_dly_em_lak_ch",
                "analyses_teoreticheskii_rashod",
                "analyses_prochnost_pri_izgibe",
                "analyses_stoikost_k_obrat_udaru",
                "analyses_prochn_rastyazh_po_er",
                "analyses_blesk",
                "analyses_plotnost",
                "analyses_mass_dolya_nelet_vesh",
            ]
            for field in float_fields:
                value = getattr(analysis, field, None)
                if value is not None:
                    analyses_data[field] = value
            
            # Строковые поля (CharField)
            string_fields = [
                "analyses_viz_kontrol_poverh",
                "analyses_vneshnii_vid",
                "analyses_grunt",
                "analyses_tverdost_po_karandashu",
            ]
            for field in string_fields:
                value = getattr(analysis, field, None)
                if value is not None:
                    analyses_data[field] = value
        
        series_item["analyses"] = analyses_data if analyses_data else None
        series_data.append(series_item)
    
    response = {
        "product": product_data,
        "series": series_data,
        "series_count": len(series_data),
    }
    
    return JsonResponse(response)

