from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from django.db import connection, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import (
    Analyses,
    Clients,
    CoatingTypes,
    Orders,
    OrdersItems,
    Products,
    Series,
    Stocks,
    Users,
)
from .utils import (
    _clip,
    _parse_iso_date,
    _parse_json_body,
    _serialize_client,
    _serialize_order,
    _serialize_product,
    _serialize_series,
    require_admin_auth,
)

# ============================================================================
# Управление продуктами (Products)
# ============================================================================


@csrf_exempt
@require_http_methods(["POST"])
@require_admin_auth
def admin_products_create(request):
    """Создание нового продукта"""
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    coating_type_id = payload.get("coating_type_id")
    product_name = payload.get("name")
    color = payload.get("color_code")
    price = payload.get("price")

    if not coating_type_id or not product_name or color is None or price is None:
        return JsonResponse(
            {"error": "Fields 'coating_type_id', 'name', 'color_code', and 'price' are required."},
            status=400,
        )

    try:
        coating_type = get_object_or_404(CoatingTypes, pk=int(coating_type_id))
        color_int = int(color)
        price_int = int(price)
        product_name_clipped = _clip(str(product_name), length=40)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid data types for required fields."}, status=400)

    if not product_name_clipped:
        return JsonResponse({"error": "Product name cannot be empty."}, status=400)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO products (coating_types_id, color, product_name, product_price)
                VALUES (%s, %s, %s, %s)
                RETURNING product_id
                """,
                [coating_type.coating_types_id, color_int, product_name_clipped, price_int],
            )
            product_id = cursor.fetchone()[0]

    product = Products.objects.select_related("coating_types").get(pk=product_id)
    return JsonResponse(_serialize_product(product), status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
@require_admin_auth
def admin_products_update(request, product_id: int):
    """Обновление или удаление продукта"""
    product = get_object_or_404(Products.objects.select_related("coating_types"), pk=product_id)

    if request.method == "DELETE":
        # Проверяем, нет ли связанных заказов или остатков
        from ..models import OrdersItems, Stocks

        has_orders = OrdersItems.objects.filter(product=product).exists()
        has_stocks = Stocks.objects.filter(series__product=product).exists()

        if has_orders or has_stocks:
            return JsonResponse(
                {
                    "error": "Cannot delete product. It has associated orders or stocks. "
                    "Consider deactivating it instead."
                },
                status=400,
            )

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM products WHERE product_id = %s", [product_id])

        return JsonResponse({"message": "Product deleted successfully."}, status=200)

    # PATCH - обновление
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    update_fields = []
    update_values = []

    if "coating_type_id" in payload:
        try:
            coating_type = get_object_or_404(CoatingTypes, pk=int(payload["coating_type_id"]))
            update_fields.append("coating_types_id = %s")
            update_values.append(coating_type.coating_types_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid 'coating_type_id'."}, status=400)

    if "name" in payload:
        product_name_clipped = _clip(str(payload["name"]), length=40)
        if not product_name_clipped:
            return JsonResponse({"error": "Product name cannot be empty."}, status=400)
        update_fields.append("product_name = %s")
        update_values.append(product_name_clipped)

    if "color_code" in payload:
        try:
            color_int = int(payload["color_code"])
            update_fields.append("color = %s")
            update_values.append(color_int)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid 'color_code'."}, status=400)

    if "price" in payload:
        try:
            price_int = int(payload["price"])
            if price_int < 0:
                return JsonResponse({"error": "Price cannot be negative."}, status=400)
            update_fields.append("product_price = %s")
            update_values.append(price_int)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid 'price'."}, status=400)

    if not update_fields:
        return JsonResponse({"error": "No fields to update."}, status=400)

    update_values.append(product_id)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE products SET {', '.join(update_fields)} WHERE product_id = %s",
                update_values,
            )

    product.refresh_from_db()
    return JsonResponse(_serialize_product(product))


# ============================================================================
# Управление сериями (Series)
# ============================================================================


@csrf_exempt
@require_http_methods(["POST"])
@require_admin_auth
def admin_series_create(request):
    """Создание новой серии"""
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    product_id = payload.get("product_id")
    series_name = payload.get("name")
    production_date = payload.get("production_date")
    expire_date = payload.get("expire_date")

    if not product_id:
        return JsonResponse({"error": "Field 'product_id' is required."}, status=400)

    try:
        product = get_object_or_404(Products, pk=int(product_id))
        series_name_clipped = _clip(str(series_name) if series_name else None, length=20)
        production_date_parsed = _parse_iso_date(production_date, field="production_date") if production_date else None
        expire_date_parsed = _parse_iso_date(expire_date, field="expire_date") if expire_date else None
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO series (product_id, series_name, series_production_date, series_expire_date)
                VALUES (%s, %s, %s, %s)
                RETURNING series_id
                """,
                [product.product_id, series_name_clipped, production_date_parsed, expire_date_parsed],
            )
            series_id = cursor.fetchone()[0]

    series = Series.objects.select_related("product", "product__coating_types").get(pk=series_id)
    return JsonResponse(_serialize_series(series), status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
@require_admin_auth
def admin_series_update(request, series_id: int):
    """Обновление или удаление серии"""
    series = get_object_or_404(Series.objects.select_related("product"), pk=series_id)

    if request.method == "DELETE":
        # Проверяем, нет ли связанных остатков или заказов
        from ..models import OrdersItems, Stocks

        has_orders = OrdersItems.objects.filter(series=series).exists()
        has_stocks = Stocks.objects.filter(series=series).exists()

        if has_orders or has_stocks:
            return JsonResponse(
                {
                    "error": "Cannot delete series. It has associated orders or stocks. "
                    "Consider deactivating it instead."
                },
                status=400,
            )

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM series WHERE series_id = %s", [series_id])

        return JsonResponse({"message": "Series deleted successfully."}, status=200)

    # PATCH - обновление
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    update_fields = []
    update_values = []

    if "product_id" in payload:
        try:
            product = get_object_or_404(Products, pk=int(payload["product_id"]))
            update_fields.append("product_id = %s")
            update_values.append(product.product_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid 'product_id'."}, status=400)

    if "name" in payload:
        series_name_clipped = _clip(str(payload["name"]) if payload["name"] else None, length=20)
        update_fields.append("series_name = %s")
        update_values.append(series_name_clipped)

    if "production_date" in payload:
        try:
            production_date_parsed = (
                _parse_iso_date(payload["production_date"], field="production_date")
                if payload["production_date"]
                else None
            )
            update_fields.append("series_production_date = %s")
            update_values.append(production_date_parsed)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if "expire_date" in payload:
        try:
            expire_date_parsed = (
                _parse_iso_date(payload["expire_date"], field="expire_date") if payload["expire_date"] else None
            )
            update_fields.append("series_expire_date = %s")
            update_values.append(expire_date_parsed)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if not update_fields:
        return JsonResponse({"error": "No fields to update."}, status=400)

    update_values.append(series_id)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE series SET {', '.join(update_fields)} WHERE series_id = %s",
                update_values,
            )

    series.refresh_from_db()
    return JsonResponse(_serialize_series(series))


# ============================================================================
# Управление остатками (Stocks)
# ============================================================================


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_admin_auth
def admin_stocks_list(request):
    """Список всех остатков с фильтрацией (GET) или создание остатка (POST)"""
    if request.method == "GET":
        from django.db.models import F, Q

        stocks_qs = Stocks.objects.select_related(
            "client",
            "series",
            "series__product",
            "series__product__coating_types",
        )

        # Фильтры
        client_id = request.GET.get("client_id")
        if client_id:
            try:
                client = get_object_or_404(Clients, pk=int(client_id))
                stocks_qs = stocks_qs.filter(client=client)
            except ValueError:
                return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

        # Фильтр по наличию клиента (null = общедоступные)
        only_public = request.GET.get("only_public", "false").lower() in ("true", "1", "yes")
        if only_public:
            stocks_qs = stocks_qs.filter(client__isnull=True)

        only_reserved = request.GET.get("only_reserved", "false").lower() in ("true", "1", "yes")
        if only_reserved:
            stocks_qs = stocks_qs.filter(stocks_is_reserved_for_client=True)

        series_id = request.GET.get("series_id")
        if series_id:
            try:
                stocks_qs = stocks_qs.filter(series_id=int(series_id))
            except ValueError:
                return JsonResponse({"error": "Invalid 'series_id'."}, status=400)

        min_quantity = request.GET.get("min_quantity")
        if min_quantity:
            try:
                stocks_qs = stocks_qs.filter(stocks_count__gte=float(min_quantity))
            except ValueError:
                return JsonResponse({"error": "Invalid 'min_quantity'."}, status=400)

        max_quantity = request.GET.get("max_quantity")
        if max_quantity:
            try:
                stocks_qs = stocks_qs.filter(stocks_count__lte=float(max_quantity))
            except ValueError:
                return JsonResponse({"error": "Invalid 'max_quantity'."}, status=400)

        # Сортировка
        stocks_qs = stocks_qs.order_by(
            F("client__client_name").asc(nulls_last=True),
            "series__product__coating_types__coating_type_nomenclatura",
            "series__series_id",
        )

        # Пагинация
        total_count = stocks_qs.count()
        offset = request.GET.get("offset")
        if offset:
            try:
                offset_value = int(offset)
                if offset_value < 0:
                    return JsonResponse({"error": "Invalid 'offset'."}, status=400)
                stocks_qs = stocks_qs[offset_value:]
            except ValueError:
                return JsonResponse({"error": "Invalid 'offset'."}, status=400)

        limit = request.GET.get("limit")
        if limit:
            try:
                limit_value = int(limit)
                if limit_value <= 0:
                    return JsonResponse({"error": "Invalid 'limit'."}, status=400)
                stocks_qs = stocks_qs[:limit_value]
            except ValueError:
                return JsonResponse({"error": "Invalid 'limit'."}, status=400)

        results = []
        for stock in stocks_qs:
            results.append(
                {
                    "id": stock.stocks_id,
                    "series": _serialize_series(stock.series) if stock.series else None,
                    "client": _serialize_client(stock.client) if stock.client else None,
                    "quantity": float(stock.stocks_count),
                    "is_reserved": bool(stock.stocks_is_reserved_for_client),
                    "updated_at": stock.stocks_update_at,
                }
            )

        return JsonResponse({"count": total_count, "results": results})
    
    # POST - создание остатка
    return admin_stocks_create_or_update(request, stocks_id=None)


@csrf_exempt
@require_http_methods(["PATCH"])
@require_admin_auth
def admin_stocks_update(request, stocks_id: int):
    """Обновление остатка"""
    return admin_stocks_create_or_update(request, stocks_id=stocks_id)


def admin_stocks_create_or_update(request, stocks_id: Optional[int] = None):
    """Создание или обновление остатка"""
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    series_id = payload.get("series_id")
    client_id = payload.get("client_id")  # None для общедоступных остатков
    stocks_count = payload.get("quantity")
    is_reserved = payload.get("is_reserved", False)

    if not series_id or stocks_count is None:
        return JsonResponse({"error": "Fields 'series_id' and 'quantity' are required."}, status=400)

    try:
        series = get_object_or_404(Series, pk=int(series_id))
        quantity_float = float(stocks_count)
        if quantity_float < 0:
            return JsonResponse({"error": "Quantity cannot be negative."}, status=400)

        client = None
        if client_id:
            client = get_object_or_404(Clients, pk=int(client_id))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": f"Invalid data: {str(exc)}"}, status=400)

    update_date = date.today()

    if stocks_id:
        # Обновление существующего остатка
        stock = get_object_or_404(Stocks, pk=stocks_id)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE stocks
                    SET series_id = %s, client_id = %s, stocks_count = %s,
                        stocks_is_reserved_for_client = %s, stocks_update_at = %s
                    WHERE stocks_id = %s
                    """,
                    [
                        series.series_id,
                        client.client_id if client else None,
                        quantity_float,
                        bool(is_reserved),
                        update_date,
                        stocks_id,
                    ],
                )
        stock.refresh_from_db()
        stocks_id_result = stocks_id
    else:
        # Создание нового остатка
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO stocks (series_id, client_id, stocks_count, stocks_is_reserved_for_client, stocks_update_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING stocks_id
                    """,
                    [
                        series.series_id,
                        client.client_id if client else None,
                        quantity_float,
                        bool(is_reserved),
                        update_date,
                    ],
                )
                stocks_id_result = cursor.fetchone()[0]

    stock = Stocks.objects.select_related("client", "series", "series__product", "series__product__coating_types").get(
        pk=stocks_id_result
    )

    return JsonResponse(
        {
            "id": stock.stocks_id,
            "series": _serialize_series(stock.series) if stock.series else None,
            "client": _serialize_client(stock.client) if stock.client else None,
            "quantity": float(stock.stocks_count),
            "is_reserved": bool(stock.stocks_is_reserved_for_client),
            "updated_at": stock.stocks_update_at,
        },
        status=201 if not stocks_id else 200,
    )


@csrf_exempt
@require_http_methods(["DELETE"])
@require_admin_auth
def admin_stocks_delete(request, stocks_id: int):
    """Удаление остатка"""
    stock = get_object_or_404(Stocks, pk=stocks_id)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM stocks WHERE stocks_id = %s", [stocks_id])

    return JsonResponse({"message": "Stock deleted successfully."}, status=200)


# ============================================================================
# Управление анализами (Analyses)
# ============================================================================


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
@require_admin_auth
def admin_analyses_create_or_update(request, series_id: int):
    """Создание или обновление анализа для серии"""
    series = get_object_or_404(Series, pk=series_id)

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    from .utils import ANALYSIS_NUMERIC_FIELDS

    # Подготавливаем поля для вставки/обновления
    analysis_fields = []
    analysis_values = []

    # Обрабатываем числовые поля
    for field in ANALYSIS_NUMERIC_FIELDS:
        if field in payload:
            value = payload[field]
            if value is not None:
                try:
                    analysis_fields.append(f"{field} = %s")
                    analysis_values.append(float(value))
                except (ValueError, TypeError):
                    return JsonResponse({"error": f"Invalid value for field '{field}'."}, status=400)

    # Обрабатываем строковые поля
    string_fields = [
        "analyses_viz_kontrol_poverh",
        "analyses_vneshnii_vid",
        "analyses_grunt",
        "analyses_tverdost_po_karandashu",
    ]
    for field in string_fields:
        if field in payload:
            value = payload[field]
            if value is not None:
                max_length = 15 if field == "analyses_viz_kontrol_poverh" else 31 if field == "analyses_vneshnii_vid" else 30 if field == "analyses_grunt" else 2
                value_clipped = _clip(str(value), length=max_length)
                analysis_fields.append(f"{field} = %s")
                analysis_values.append(value_clipped)

    if not analysis_fields:
        return JsonResponse({"error": "No analysis fields provided."}, status=400)

    # Проверяем, существует ли уже анализ
    analysis_exists = Analyses.objects.filter(series=series).exists()

    if analysis_exists:
        # Обновление
        analysis_values.append(series_id)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE analyses SET {', '.join(analysis_fields)} WHERE series_id = %s",
                    analysis_values,
                )
    else:
        # Создание
        analysis_values.insert(0, series_id)
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Сначала создаем запись с series_id
                placeholders = ["%s"] + ["%s"] * (len(analysis_fields))
                field_names = ["series_id"] + [f.split(" = ")[0] for f in analysis_fields]
                cursor.execute(
                    f"INSERT INTO analyses ({', '.join(field_names)}) VALUES ({', '.join(placeholders)})",
                    analysis_values,
                )

    # Получаем обновленный анализ
    try:
        analysis = Analyses.objects.select_related("series").get(series=series)
    except Analyses.DoesNotExist:
        return JsonResponse({"error": "Failed to create/update analysis."}, status=500)

    # Формируем ответ
    response_data = {"series_id": series_id}
    for field in ANALYSIS_NUMERIC_FIELDS + string_fields:
        value = getattr(analysis, field, None)
        if value is not None:
            response_data[field] = value

    return JsonResponse(response_data, status=201 if not analysis_exists else 200)


# ============================================================================
# Управление пользователями (Users)
# ============================================================================


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def admin_users_list(request):
    """Список пользователей"""
    qs = Users.objects.select_related("client").all()

    # Фильтры
    client_id = request.GET.get("client_id")
    if client_id:
        try:
            qs = qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    is_active = request.GET.get("is_active")
    if is_active is not None:
        qs = qs.filter(user_is_active=is_active.lower() in ("true", "1", "yes"))

    is_admin = request.GET.get("is_admin")
    if is_admin is not None:
        qs = qs.filter(user_is_admin=is_admin.lower() in ("true", "1", "yes"))

    email_query = request.GET.get("email")
    if email_query:
        qs = qs.filter(user_email__icontains=email_query)

    # Пагинация
    total_count = qs.count()
    offset = request.GET.get("offset")
    if offset:
        try:
            offset_value = int(offset)
            if offset_value < 0:
                return JsonResponse({"error": "Invalid 'offset'."}, status=400)
            qs = qs[offset_value:]
        except ValueError:
            return JsonResponse({"error": "Invalid 'offset'."}, status=400)

    limit = request.GET.get("limit")
    if limit:
        try:
            limit_value = int(limit)
            if limit_value <= 0:
                return JsonResponse({"error": "Invalid 'limit'."}, status=400)
            qs = qs[:limit_value]
        except ValueError:
            return JsonResponse({"error": "Invalid 'limit'."}, status=400)

    users_list = []
    for user in qs:
        users_list.append(
            {
                "id": user.user_id,
                "email": user.user_email,
                "first_name": getattr(user, "user_name", None),
                "last_name": getattr(user, "user_surname", None),
                "is_active": user.user_is_active,
                "is_admin": getattr(user, "user_is_admin", False),
                "created_at": user.user_created_at,
                "client": _serialize_client(user.client),
            }
        )

    return JsonResponse({"count": total_count, "results": users_list})


@csrf_exempt
@require_http_methods(["PATCH"])
@require_admin_auth
def admin_users_update(request, user_id: int):
    """Обновление пользователя"""
    user = get_object_or_404(Users.objects.select_related("client"), pk=user_id)

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    update_fields = []
    update_values = []

    if "is_active" in payload:
        is_active = bool(payload["is_active"])
        update_fields.append("user_is_active = %s")
        update_values.append(is_active)

    if "is_admin" in payload:
        is_admin = bool(payload["is_admin"])
        update_fields.append("user_is_admin = %s")
        update_values.append(is_admin)

    if "first_name" in payload:
        first_name = _clip(str(payload["first_name"]) if payload["first_name"] else None, length=50)
        update_fields.append("user_name = %s")
        update_values.append(first_name)

    if "last_name" in payload:
        last_name = _clip(str(payload["last_name"]) if payload["last_name"] else None, length=50)
        update_fields.append("user_surname = %s")
        update_values.append(last_name)

    if not update_fields:
        return JsonResponse({"error": "No fields to update."}, status=400)

    update_values.append(user_id)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = %s",
                update_values,
            )

    user.refresh_from_db()
    return JsonResponse(
        {
            "id": user.user_id,
            "email": user.user_email,
            "first_name": getattr(user, "user_name", None),
            "last_name": getattr(user, "user_surname", None),
            "is_active": user.user_is_active,
            "is_admin": getattr(user, "user_is_admin", False),
            "created_at": user.user_created_at,
            "client": _serialize_client(user.client),
        }
    )


# ============================================================================
# Управление типами покрытий (CoatingTypes)
# ============================================================================


@csrf_exempt
@require_http_methods(["POST"])
@require_admin_auth
def admin_coating_types_create(request):
    """Создание нового типа покрытия"""
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    name = payload.get("name")
    nomenclature = payload.get("nomenclature")

    if not name or not nomenclature:
        return JsonResponse({"error": "Fields 'name' and 'nomenclature' are required."}, status=400)

    name_clipped = _clip(str(name), length=40)
    nomenclature_clipped = _clip(str(nomenclature), length=40)

    if not name_clipped or not nomenclature_clipped:
        return JsonResponse({"error": "Name and nomenclature cannot be empty."}, status=400)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO coating_types (coating_type_name, coating_type_nomenclatura)
                VALUES (%s, %s)
                RETURNING coating_types_id
                """,
                [name_clipped, nomenclature_clipped],
            )
            coating_type_id = cursor.fetchone()[0]

    coating_type = CoatingTypes.objects.get(pk=coating_type_id)
    return JsonResponse(
        {
            "id": coating_type.coating_types_id,
            "name": coating_type.coating_type_name,
            "nomenclature": coating_type.coating_type_nomenclatura,
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
@require_admin_auth
def admin_coating_types_update(request, coating_type_id: int):
    """Обновление или удаление типа покрытия"""
    coating_type = get_object_or_404(CoatingTypes, pk=coating_type_id)

    if request.method == "DELETE":
        # Проверяем, нет ли связанных продуктов
        has_products = Products.objects.filter(coating_types=coating_type).exists()
        if has_products:
            return JsonResponse(
                {"error": "Cannot delete coating type. It has associated products."},
                status=400,
            )

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM coating_types WHERE coating_types_id = %s", [coating_type_id])

        return JsonResponse({"message": "Coating type deleted successfully."}, status=200)

    # PATCH - обновление
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    update_fields = []
    update_values = []

    if "name" in payload:
        name_clipped = _clip(str(payload["name"]), length=40)
        if not name_clipped:
            return JsonResponse({"error": "Name cannot be empty."}, status=400)
        update_fields.append("coating_type_name = %s")
        update_values.append(name_clipped)

    if "nomenclature" in payload:
        nomenclature_clipped = _clip(str(payload["nomenclature"]), length=40)
        if not nomenclature_clipped:
            return JsonResponse({"error": "Nomenclature cannot be empty."}, status=400)
        update_fields.append("coating_type_nomenclatura = %s")
        update_values.append(nomenclature_clipped)

    if not update_fields:
        return JsonResponse({"error": "No fields to update."}, status=400)

    update_values.append(coating_type_id)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE coating_types SET {', '.join(update_fields)} WHERE coating_types_id = %s",
                update_values,
            )

    coating_type.refresh_from_db()
    return JsonResponse(
        {
            "id": coating_type.coating_types_id,
            "name": coating_type.coating_type_name,
            "nomenclature": coating_type.coating_type_nomenclatura,
        }
    )


# ============================================================================
# Управление заказами (Orders)
# ============================================================================


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def admin_orders_list(request):
    """Список всех заказов с фильтрацией"""
    from django.db.models import Count
    from django.db.models.functions import Coalesce
    from django.db.models import Sum

    qs = Orders.objects.select_related("client").annotate(
        total_quantity=Coalesce(Sum("ordersitems__order_items_count"), 0),
        series_count=Count("ordersitems__series", distinct=True),
        items_count=Count("ordersitems__order_items_id", distinct=True),
    )

    # Фильтры
    client_id = request.GET.get("client_id")
    if client_id:
        try:
            qs = qs.filter(client_id=int(client_id))
        except ValueError:
            return JsonResponse({"error": "Invalid 'client_id'."}, status=400)

    status = request.GET.get("status")
    if status:
        qs = qs.filter(orders_status__iexact=status)

    created_from = request.GET.get("created_from")
    if created_from:
        try:
            qs = qs.filter(orders_created_at__gte=_parse_iso_date(created_from, field="created_from"))
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    created_to = request.GET.get("created_to")
    if created_to:
        try:
            qs = qs.filter(orders_created_at__lte=_parse_iso_date(created_to, field="created_to"))
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    shipped_from = request.GET.get("shipped_from")
    if shipped_from:
        try:
            qs = qs.filter(orders_shipped_at__gte=_parse_iso_date(shipped_from, field="shipped_from"))
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    shipped_to = request.GET.get("shipped_to")
    if shipped_to:
        try:
            qs = qs.filter(orders_shipped_at__lte=_parse_iso_date(shipped_to, field="shipped_to"))
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    qs = qs.order_by("-orders_created_at", "-orders_id")

    # Пагинация
    total_count = qs.count()
    offset = request.GET.get("offset")
    if offset:
        try:
            offset_value = int(offset)
            if offset_value < 0:
                return JsonResponse({"error": "Invalid 'offset'."}, status=400)
            qs = qs[offset_value:]
        except ValueError:
            return JsonResponse({"error": "Invalid 'offset'."}, status=400)

    limit = request.GET.get("limit")
    if limit:
        try:
            limit_value = int(limit)
            if limit_value <= 0:
                return JsonResponse({"error": "Invalid 'limit'."}, status=400)
            qs = qs[:limit_value]
        except ValueError:
            return JsonResponse({"error": "Invalid 'limit'."}, status=400)

    results = []
    for order in qs:
        results.append(
            {
                "id": order.orders_id,
                "client": _serialize_client(order.client),
                "status": order.orders_status,
                "created_at": order.orders_created_at,
                "shipped_at": order.orders_shipped_at,
                "delivered_at": order.orders_delivered_at,
                "cancel_reason": order.orders_cancel_reason,
                "total_quantity": float(order.total_quantity or 0),
                "series_count": order.series_count,
                "items_count": order.items_count,
            }
        )

    return JsonResponse({"count": total_count, "results": results})


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@require_admin_auth
def admin_orders_detail(request, order_id: int):
    """Просмотр, обновление или удаление заказа"""
    order = get_object_or_404(Orders.objects.select_related("client"), pk=order_id)

    if request.method == "GET":
        return JsonResponse(_serialize_order(order))

    if request.method == "DELETE":
        # Проверяем, можно ли удалить заказ
        # В зависимости от бизнес-логики можно добавить дополнительные проверки
        with transaction.atomic():
            # Удаляем связанные записи
            OrdersItems.objects.filter(orders=order).delete()
            from ..models import OrderStatusHistory

            OrderStatusHistory.objects.filter(orders=order).delete()
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM orders WHERE orders_id = %s", [order_id])

        return JsonResponse({"message": "Order deleted successfully."}, status=200)

    # PATCH - обновление заказа
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    from django.utils import timezone
    from ..models import OrderStatusHistory

    status_updated = False
    status_from = order.orders_status

    update_fields = []
    update_values = []

    if "status" in payload and payload["status"] is not None:
        new_status = _clip(str(payload["status"]).strip(), length=30)
        if new_status and new_status != order.orders_status:
            update_fields.append("orders_status = %s")
            update_values.append(new_status)
            status_updated = True

    if "shipped_at" in payload:
        try:
            shipped_at_parsed = (
                _parse_iso_date(payload["shipped_at"], field="shipped_at") if payload["shipped_at"] else None
            )
            update_fields.append("orders_shipped_at = %s")
            update_values.append(shipped_at_parsed)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if "delivered_at" in payload:
        try:
            delivered_at_parsed = (
                _parse_iso_date(payload["delivered_at"], field="delivered_at") if payload["delivered_at"] else None
            )
            update_fields.append("orders_delivered_at = %s")
            update_values.append(delivered_at_parsed)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    if "cancel_reason" in payload:
        cancel_reason_clipped = _clip(payload.get("cancel_reason"), length=100)
        update_fields.append("orders_cancel_reason = %s")
        update_values.append(cancel_reason_clipped)

    if update_fields:
        update_values.append(order_id)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE orders SET {', '.join(update_fields)} WHERE orders_id = %s",
                    update_values,
                )

            if status_updated:
                OrderStatusHistory.objects.create(
                    orders=order,
                    order_status_history_from_stat=_clip(status_from, length=30),
                    order_status_history_to_status=_clip(payload.get("status", ""), length=30),
                    order_status_history_chang_at=timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                    order_status_history_note=_clip(payload.get("status_note"), length=30),
                )

    order.refresh_from_db()
    return JsonResponse(_serialize_order(order))

