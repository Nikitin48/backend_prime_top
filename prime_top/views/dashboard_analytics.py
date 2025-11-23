from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from django.db import models
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth, TruncQuarter, TruncWeek, TruncYear
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Clients, CoatingTypes, OrderStatusHistory, Orders, OrdersItems, Products, Series, Stocks
from .utils import _parse_iso_date, _serialize_client, _serialize_product, _serialize_series, require_admin_auth


# ============================================================================
# 1. Динамика потребления / Продаж
# ============================================================================


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def analytics_sales_volume(request):
    """
    1.1. Объем продаж по периодам
    Показывает общее количество проданных единиц, общую стоимость и количество заказов
    """
    # Парсинг фильтров
    period_from = request.GET.get("period_from") or request.GET.get("created_from")
    period_to = request.GET.get("period_to") or request.GET.get("created_to")
    
    try:
        date_from = _parse_iso_date(period_from, field="period_from") if period_from else None
        date_to = _parse_iso_date(period_to, field="period_to") if period_to else None
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    client_id = request.GET.get("client_id")
    coating_type_id = request.GET.get("coating_type_id")
    product_id = request.GET.get("product_id")
    series_id = request.GET.get("series_id")
    status = request.GET.get("status")
    group_by = request.GET.get("group_by", "month").lower()  # day/week/month/quarter/year

    # Базовый queryset
    orders_qs = Orders.objects.select_related("client").prefetch_related("ordersitems_set")

    # Применение фильтров
    if date_from:
        orders_qs = orders_qs.filter(orders_created_at__gte=date_from)
    if date_to:
        orders_qs = orders_qs.filter(orders_created_at__lte=date_to)
    if client_id:
        try:
            orders_qs = orders_qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)
    if status:
        orders_qs = orders_qs.filter(orders_status__iexact=status)

    # Фильтры по позициям заказов
    items_qs = OrdersItems.objects.select_related("product", "product__coating_types", "series", "orders")
    items_qs = items_qs.filter(orders__in=orders_qs)

    if coating_type_id:
        try:
            items_qs = items_qs.filter(product__coating_types_id=int(coating_type_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'coating_type_id'."}, status=400)
    if product_id:
        try:
            items_qs = items_qs.filter(product_id=int(product_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'product_id'."}, status=400)
    if series_id:
        try:
            items_qs = items_qs.filter(series_id=int(series_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'series_id'."}, status=400)

    # Выбор функции группировки
    trunc_func_map = {
        "day": TruncDate("orders__orders_created_at"),
        "week": TruncWeek("orders__orders_created_at"),
        "month": TruncMonth("orders__orders_created_at"),
        "quarter": TruncQuarter("orders__orders_created_at"),
        "year": TruncYear("orders__orders_created_at"),
    }

    if group_by not in trunc_func_map:
        return JsonResponse({"error": "Invalid 'group_by'. Must be one of: day, week, month, quarter, year."}, status=400)

    trunc_func = trunc_func_map[group_by]

    # Группировка и агрегация
    timeline_data = (
        items_qs.annotate(period=trunc_func)
        .values("period")
        .annotate(
            quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
            revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
            orders_count=Count("orders__orders_id", distinct=True),
        )
        .order_by("period")
    )

    # Общая сводка
    summary = items_qs.aggregate(
        total_quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
        total_revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
        orders_count=Count("orders__orders_id", distinct=True),
    )

    # Форматирование периода для ответа
    def format_period(period_date):
        if period_date is None:
            return None
        if group_by == "day":
            return period_date.strftime("%Y-%m-%d")
        elif group_by == "week":
            # Неделя: YYYY-WW
            year, week, _ = period_date.isocalendar()
            return f"{year}-W{week:02d}"
        elif group_by == "month":
            return period_date.strftime("%Y-%m")
        elif group_by == "quarter":
            quarter = (period_date.month - 1) // 3 + 1
            return f"{period_date.year}-Q{quarter}"
        elif group_by == "year":
            return str(period_date.year)
        return str(period_date)

    timeline = [
        {
            "period": format_period(item["period"]),
            "quantity": float(item["quantity"] or 0),
            "revenue": int(item["revenue"] or 0),
            "orders_count": item["orders_count"],
        }
        for item in timeline_data
    ]

    response = {
        "period": {
            "from": period_from,
            "to": period_to,
            "group_by": group_by,
        },
        "summary": {
            "total_quantity": float(summary["total_quantity"] or 0),
            "total_revenue": int(summary["total_revenue"] or 0),
            "orders_count": summary["orders_count"],
        },
        "timeline": timeline,
    }

    return JsonResponse(response)


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def analytics_order_status_dynamics(request):
    """
    1.2. Динамика по статусам заказов
    Показывает количество заказов в каждом статусе по времени и среднее время в статусах
    """
    period_from = request.GET.get("period_from") or request.GET.get("created_from")
    period_to = request.GET.get("period_to") or request.GET.get("created_to")
    
    try:
        date_from = _parse_iso_date(period_from, field="period_from") if period_from else None
        date_to = _parse_iso_date(period_to, field="period_to") if period_to else None
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    client_id = request.GET.get("client_id")
    group_by = request.GET.get("group_by", "month").lower()

    orders_qs = Orders.objects.all()

    if date_from:
        orders_qs = orders_qs.filter(orders_created_at__gte=date_from)
    if date_to:
        orders_qs = orders_qs.filter(orders_created_at__lte=date_to)
    if client_id:
        try:
            orders_qs = orders_qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    # Выбор функции группировки
    trunc_func_map = {
        "day": TruncDate("orders_created_at"),
        "week": TruncWeek("orders_created_at"),
        "month": TruncMonth("orders_created_at"),
        "quarter": TruncQuarter("orders_created_at"),
        "year": TruncYear("orders_created_at"),
    }

    if group_by not in trunc_func_map:
        return JsonResponse({"error": "Invalid 'group_by'. Must be one of: day, week, month, quarter, year."}, status=400)

    trunc_func = trunc_func_map[group_by]

    # Группировка по периоду и статусу
    status_timeline_data = (
        orders_qs.annotate(period=trunc_func)
        .values("period", "orders_status")
        .annotate(count=Count("orders_id"))
        .order_by("period", "orders_status")
    )

    # Форматирование периода
    def format_period(period_date):
        if period_date is None:
            return None
        if group_by == "day":
            return period_date.strftime("%Y-%m-%d")
        elif group_by == "week":
            year, week, _ = period_date.isocalendar()
            return f"{year}-W{week:02d}"
        elif group_by == "month":
            return period_date.strftime("%Y-%m")
        elif group_by == "quarter":
            quarter = (period_date.month - 1) // 3 + 1
            return f"{period_date.year}-Q{quarter}"
        elif group_by == "year":
            return str(period_date.year)
        return str(period_date)

    # Группировка по периодам
    timeline_dict: Dict[str, Dict[str, int]] = {}
    for item in status_timeline_data:
        period_str = format_period(item["period"])
        if period_str not in timeline_dict:
            timeline_dict[period_str] = {}
        timeline_dict[period_str][item["orders_status"]] = item["count"]

    status_timeline = [
        {"period": period, **statuses} for period, statuses in sorted(timeline_dict.items())
    ]

    # Расчет среднего времени в статусах (на основе истории статусов)
    history_qs = OrderStatusHistory.objects.filter(orders__in=orders_qs).select_related("orders")

    # Простая оценка: считаем количество переходов и среднее время между ними
    # Для более точного расчета нужны временные метки в правильном формате
    transitions = {}
    for hist in history_qs:
        transition_key = f"{hist.order_status_history_from_stat}_to_{hist.order_status_history_to_status}"
        if transition_key not in transitions:
            transitions[transition_key] = []
        # Парсим дату из строки (формат может быть разным)
        try:
            # Пытаемся распарсить дату из строки
            change_at_str = hist.order_status_history_chang_at
            if change_at_str:
                # Пробуем разные форматы
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S"]:
                    try:
                        change_date = datetime.strptime(change_at_str, fmt)
                        transitions[transition_key].append(change_date)
                        break
                    except ValueError:
                        continue
        except Exception:
            pass

    # Упрощенный расчет средних длительностей (если есть данные)
    average_durations = {}
    # В реальности нужен более сложный алгоритм для расчета времени между статусами

    response = {
        "status_timeline": status_timeline,
        "average_durations": average_durations,  # Пока пустой, требует доработки логики
    }

    return JsonResponse(response)


# ============================================================================
# 2. Популярные позиции
# ============================================================================


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def analytics_top_products(request):
    """
    2.1. Топ продуктов по объему продаж
    Показывает топ N продуктов по количеству, стоимости и количеству заказов
    """
    period_from = request.GET.get("period_from") or request.GET.get("created_from")
    period_to = request.GET.get("period_to") or request.GET.get("created_to")
    
    try:
        date_from = _parse_iso_date(period_from, field="period_from") if period_from else None
        date_to = _parse_iso_date(period_to, field="period_to") if period_to else None
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    client_id = request.GET.get("client_id")
    coating_type_id = request.GET.get("coating_type_id")
    limit = request.GET.get("limit", "10")

    try:
        limit_value = int(limit)
        if limit_value <= 0:
            return JsonResponse({"error": "Invalid 'limit'. Must be positive."}, status=400)
    except ValueError:
        return JsonResponse({"error": "Invalid 'limit'."}, status=400)

    # Базовый queryset заказов
    orders_qs = Orders.objects.all()

    if date_from:
        orders_qs = orders_qs.filter(orders_created_at__gte=date_from)
    if date_to:
        orders_qs = orders_qs.filter(orders_created_at__lte=date_to)
    if client_id:
        try:
            orders_qs = orders_qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    # Queryset позиций заказов
    items_qs = OrdersItems.objects.filter(orders__in=orders_qs).select_related(
        "product", "product__coating_types"
    )

    if coating_type_id:
        try:
            items_qs = items_qs.filter(product__coating_types_id=int(coating_type_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'coating_type_id'."}, status=400)

    # Топ по количеству
    top_by_quantity = (
        items_qs.values("product_id")
        .annotate(
            total_quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
            orders_count=Count("orders__orders_id", distinct=True),
            total_revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
        )
        .order_by("-total_quantity")[:limit_value]
    )

    # Топ по выручке
    top_by_revenue = (
        items_qs.values("product_id")
        .annotate(
            total_quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
            orders_count=Count("orders__orders_id", distinct=True),
            total_revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
        )
        .order_by("-total_revenue")[:limit_value]
    )

    # Топ по количеству заказов
    top_by_orders = (
        items_qs.values("product_id")
        .annotate(
            total_quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
            orders_count=Count("orders__orders_id", distinct=True),
            total_revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
        )
        .order_by("-orders_count")[:limit_value]
    )

    # Получение данных продуктов
    def get_product_data(product_id):
        try:
            product = Products.objects.select_related("coating_types").get(pk=product_id)
            return {
                "product_id": product.product_id,
                "product_name": product.product_name,
                "coating_type": {
                    "id": product.coating_types.coating_types_id,
                    "name": product.coating_types.coating_type_name,
                    "nomenclature": product.coating_types.coating_type_nomenclatura,
                },
            }
        except Products.DoesNotExist:
            return None

    def format_top_item(item):
        product_data = get_product_data(item["product_id"])
        if not product_data:
            return None
        return {
            **product_data,
            "total_quantity": float(item["total_quantity"] or 0),
            "orders_count": item["orders_count"],
            "total_revenue": int(item["total_revenue"] or 0),
        }

    response = {
        "period": {
            "from": period_from,
            "to": period_to,
        },
        "top_by_quantity": [item for item in [format_top_item(x) for x in top_by_quantity] if item],
        "top_by_revenue": [item for item in [format_top_item(x) for x in top_by_revenue] if item],
        "top_by_orders": [item for item in [format_top_item(x) for x in top_by_orders] if item],
    }

    return JsonResponse(response)


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def analytics_top_series(request):
    """
    2.2. Топ серий по потреблению
    Показывает наиболее востребованные серии
    """
    period_from = request.GET.get("period_from") or request.GET.get("created_from")
    period_to = request.GET.get("period_to") or request.GET.get("created_to")
    
    try:
        date_from = _parse_iso_date(period_from, field="period_from") if period_from else None
        date_to = _parse_iso_date(period_to, field="period_to") if period_to else None
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    client_id = request.GET.get("client_id")
    limit = request.GET.get("limit", "10")

    try:
        limit_value = int(limit)
        if limit_value <= 0:
            return JsonResponse({"error": "Invalid 'limit'. Must be positive."}, status=400)
    except ValueError:
        return JsonResponse({"error": "Invalid 'limit'."}, status=400)

    # Базовый queryset заказов
    orders_qs = Orders.objects.all()

    if date_from:
        orders_qs = orders_qs.filter(orders_created_at__gte=date_from)
    if date_to:
        orders_qs = orders_qs.filter(orders_created_at__lte=date_to)
    if client_id:
        try:
            orders_qs = orders_qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    # Queryset позиций заказов с сериями
    items_qs = OrdersItems.objects.filter(
        orders__in=orders_qs, series__isnull=False
    ).select_related("series", "series__product", "series__product__coating_types")

    # Топ серий
    top_series_data = (
        items_qs.values("series_id")
        .annotate(
            total_sold=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
            orders_count=Count("orders__orders_id", distinct=True),
        )
        .order_by("-total_sold")[:limit_value]
    )

    # Получение данных серий и остатков
    def get_series_data(series_id):
        try:
            series = Series.objects.select_related("product", "product__coating_types").get(pk=series_id)
            # Получаем текущие остатки
            current_stock = (
                Stocks.objects.filter(series=series)
                .aggregate(total=Coalesce(Sum("stocks_count"), 0.0))["total"]
                or 0.0
            )
            return {
                "series_id": series.series_id,
                "series_name": series.series_name,
                "production_date": series.series_production_date,
                "expire_date": series.series_expire_date,
                "product": {
                    "id": series.product.product_id,
                    "name": series.product.product_name,
                },
                "current_stock": float(current_stock),
            }
        except Series.DoesNotExist:
            return None

    top_series = []
    for item in top_series_data:
        series_data = get_series_data(item["series_id"])
        if series_data:
            top_series.append(
                {
                    **series_data,
                    "total_sold": float(item["total_sold"] or 0),
                    "orders_count": item["orders_count"],
                }
            )

    response = {
        "top_series": top_series,
    }

    return JsonResponse(response)


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def analytics_top_coating_types(request):
    """
    2.3. Топ номенклатуры / Типов покрытий
    Показывает распределение продаж по типам покрытий
    """
    period_from = request.GET.get("period_from") or request.GET.get("created_from")
    period_to = request.GET.get("period_to") or request.GET.get("created_to")
    
    try:
        date_from = _parse_iso_date(period_from, field="period_from") if period_from else None
        date_to = _parse_iso_date(period_to, field="period_to") if period_to else None
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    client_id = request.GET.get("client_id")

    # Базовый queryset заказов
    orders_qs = Orders.objects.all()

    if date_from:
        orders_qs = orders_qs.filter(orders_created_at__gte=date_from)
    if date_to:
        orders_qs = orders_qs.filter(orders_created_at__lte=date_to)
    if client_id:
        try:
            orders_qs = orders_qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    # Queryset позиций заказов
    items_qs = OrdersItems.objects.filter(orders__in=orders_qs).select_related(
        "product", "product__coating_types"
    )

    # Группировка по типам покрытий
    coating_types_data = (
        items_qs.values("product__coating_types_id")
        .annotate(
            total_quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
            total_revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
            orders_count=Count("orders__orders_id", distinct=True),
        )
        .order_by("-total_quantity")
    )

    # Общий итог
    total_summary = items_qs.aggregate(
        total_quantity=Coalesce(Sum("order_items_count", output_field=models.FloatField()), 0.0),
        total_revenue=Coalesce(Sum(F("order_items_count") * F("product__product_price"), output_field=models.IntegerField()), 0),
        orders_count=Count("orders__orders_id", distinct=True),
    )

    total_quantity = float(total_summary["total_quantity"] or 0)

    # Получение данных типов покрытий
    coating_types_breakdown = []
    for item in coating_types_data:
        try:
            coating_type = CoatingTypes.objects.get(pk=item["product__coating_types_id"])
            item_quantity = float(item["total_quantity"] or 0)
            percentage = (item_quantity / total_quantity * 100) if total_quantity > 0 else 0.0

            coating_types_breakdown.append(
                {
                    "coating_type_id": coating_type.coating_types_id,
                    "coating_type_name": coating_type.coating_type_name,
                    "nomenclature": coating_type.coating_type_nomenclatura,
                    "total_quantity": item_quantity,
                    "total_revenue": int(item["total_revenue"] or 0),
                    "orders_count": item["orders_count"],
                    "percentage_of_total": round(percentage, 2),
                }
            )
        except CoatingTypes.DoesNotExist:
            continue

    response = {
        "coating_types_breakdown": coating_types_breakdown,
        "total": {
            "quantity": total_quantity,
            "revenue": int(total_summary["total_revenue"] or 0),
            "orders_count": total_summary["orders_count"],
        },
    }

    return JsonResponse(response)

