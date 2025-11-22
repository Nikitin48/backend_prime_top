from __future__ import annotations

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ..models import OrdersItems, Products, Series
from .utils import _normalized_color, _serialize_product


@require_GET
def products_view(request):
    qs = Products.objects.select_related("coating_types").all()

    coating_type_ids = request.GET.getlist("coating_type_id")
    if coating_type_ids:
        try:
            # Поддержка нескольких coating_type_id: можно передать несколько параметров
            # или один параметр с запятыми (например: coating_type_id=1,2,3)
            ids_list = []
            for coating_type_id in coating_type_ids:
                # Если значение содержит запятые, разбиваем на отдельные ID
                if ',' in coating_type_id:
                    ids_list.extend([int(x.strip()) for x in coating_type_id.split(',')])
                else:
                    ids_list.append(int(coating_type_id))
            qs = qs.filter(coating_types__coating_types_id__in=ids_list)
        except ValueError:
            raise Http404("Query parameter 'coating_type_id' must be an integer or comma-separated integers.")

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
    
    series_list = Series.objects.filter(product=product).select_related("analyses").annotate(
        available_quantity=Coalesce(Sum("stocks__stocks_count"), 0.0)
    )
    
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
        
        analyses_data = {}
        analysis = getattr(series, "analyses", None)
        if analysis:
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


@require_GET
def top_products_view(request):
    """
    Получить ТОП 20 самых популярных товаров.
    
    Популярность определяется по общему количеству заказанных единиц товара (order_items_count)
    из всех заказов. Возвращается список из 20 самых популярных товаров, отсортированных
    по убыванию популярности.
    """
    top_products = (
        OrdersItems.objects
        .select_related("product", "product__coating_types")
        .values(
            "product__product_id",
            "product__product_name",
            "product__color",
            "product__product_price",
            "product__coating_types__coating_types_id",
            "product__coating_types__coating_type_name",
            "product__coating_types__coating_type_nomenclatura",
        )
        .annotate(
            total_ordered=Coalesce(Sum("order_items_count"), 0)
        )
        .order_by("-total_ordered", "product__product_id")
        [:20]
    )
    
    products_list = []
    for item in top_products:
        products_list.append({
            "id": item["product__product_id"],
            "name": item["product__product_name"],
            "color_code": item["product__color"],
            "price": item["product__product_price"],
            "total_ordered": float(item["total_ordered"] or 0),
            "coating_type": {
                "id": item["product__coating_types__coating_types_id"],
                "name": item["product__coating_types__coating_type_name"],
                "nomenclature": item["product__coating_types__coating_type_nomenclatura"],
            } if item["product__coating_types__coating_types_id"] else None,
        })
    
    return JsonResponse({
        "count": len(products_list),
        "results": products_list,
    })


@require_GET
def products_search_view(request):
    """
    Поиск продуктов по номенклатуре или цвету.
    
    Принимает строку поиска и ищет продукты по:
    - Номенклатуре (coating_type_nomenclatura)
    - Цвету (color code, включая RAL коды)
    """
    search_query = request.GET.get("q")
    
    if not search_query:
        return JsonResponse({
            "error": "Query parameter 'q' is required."
        }, status=400)
    
    qs = Products.objects.select_related("coating_types").all()
    
    # Поиск по номенклатуре
    search_filter = Q(coating_types__coating_type_nomenclatura__icontains=search_query)
    
    # Поиск по цвету (включая нормализацию RAL кодов)
    normalized_color = _normalized_color(search_query)
    if normalized_color:
        try:
            # Точное совпадение по коду цвета
            search_filter |= Q(color=int(normalized_color))
        except ValueError:
            pass
        # Также ищем нормализованный код в номенклатуре
        if normalized_color != search_query:
            search_filter |= Q(coating_types__coating_type_nomenclatura__icontains=normalized_color)
    
    qs = qs.filter(search_filter)
    qs = qs.order_by("coating_types__coating_type_nomenclatura", "product_name")
    
    total_count = qs.count()
    
    # Поддержка пагинации
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

