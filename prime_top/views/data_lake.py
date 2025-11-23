from __future__ import annotations

import json
import traceback
from datetime import date, datetime
from typing import Any, Dict, List
from uuid import uuid4

from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import (
    Clients,
    CoatingTypes,
    Orders,
    OrdersItems,
    Products,
    Series,
    Stocks,
)
from .utils import _clip, _parse_iso_date, require_admin_auth


def _parse_json_file(file_content: bytes) -> List[Dict[str, Any]]:
    try:
        text_content = file_content.decode("utf-8")
        data = json.loads(text_content)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    return value
            return [data]
        else:
            raise ValueError("JSON должен содержать массив объектов или объект с массивом")
    except json.JSONDecodeError as e:
        raise ValueError(f"Ошибка парсинга JSON: {str(e)}")
    except Exception as e:
        raise ValueError(f"Ошибка обработки JSON: {str(e)}")


def _normalize_product_data(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    
    field_mapping = {
        "product_id": ["product_id", "id", "productId"],
        "product_name": ["product_name", "name", "productName", "product_name"],
        "color_code": ["color_code", "color", "colorCode", "color_code"],
        "price": ["price", "product_price", "productPrice"],
        "coating_type_id": ["coating_type_id", "coatingTypeId", "coating_type_id"],
        "coating_type_name": ["coating_type_name", "coatingTypeName"],
        "coating_type_nomenclature": ["coating_type_nomenclature", "nomenclature", "coatingTypeNomenclature"],
    }
    
    for target_field, source_fields in field_mapping.items():
        for source_field in source_fields:
            if source_field in row and row[source_field] is not None:
                value = row[source_field]
                if target_field in ["product_id", "color_code", "coating_type_id"]:
                    try:
                        normalized[target_field] = int(value)
                    except (ValueError, TypeError):
                        pass
                elif target_field == "price":
                    try:
                        normalized[target_field] = int(float(value))
                    except (ValueError, TypeError):
                        pass
                else:
                    normalized[target_field] = str(value).strip()
                break
    
    return normalized


def _normalize_series_data(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    
    field_mapping = {
        "series_id": ["series_id", "id", "seriesId"],
        "product_id": ["product_id", "productId"],
        "series_name": ["series_name", "name", "seriesName"],
        "production_date": ["production_date", "productionDate", "production_date"],
        "expire_date": ["expire_date", "expireDate", "expire_date"],
    }
    
    for target_field, source_fields in field_mapping.items():
        for source_field in source_fields:
            if source_field in row and row[source_field] is not None:
                value = row[source_field]
                if target_field in ["series_id", "product_id"]:
                    try:
                        normalized[target_field] = int(value)
                    except (ValueError, TypeError):
                        pass
                elif target_field in ["production_date", "expire_date"]:
                    try:
                        if isinstance(value, str):
                            normalized[target_field] = _parse_iso_date(value, field=target_field)
                        elif isinstance(value, (date, datetime)):
                            normalized[target_field] = value.date() if isinstance(value, datetime) else value
                    except ValueError:
                        pass
                else:
                    normalized[target_field] = str(value).strip() if value else None
                break
    
    return normalized


def _normalize_stock_data(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    
    field_mapping = {
        "series_id": ["series_id", "seriesId", "series_id"],
        "client_id": ["client_id", "clientId", "client_id"],
        "quantity": ["quantity", "stocks_count", "count", "stocksCount"],
        "is_reserved": ["is_reserved", "isReserved", "reserved"],
        "updated_at": ["updated_at", "updateAt", "stocks_update_at"],
    }
    
    for target_field, source_fields in field_mapping.items():
        for source_field in source_fields:
            if source_field in row and row[source_field] is not None:
                value = row[source_field]
                if target_field in ["series_id", "client_id"]:
                    try:
                        normalized[target_field] = int(value)
                    except (ValueError, TypeError):
                        pass
                elif target_field == "quantity":
                    try:
                        normalized[target_field] = float(value)
                    except (ValueError, TypeError):
                        pass
                elif target_field == "is_reserved":
                    normalized[target_field] = str(value).lower() in ("true", "1", "yes", "да")
                elif target_field == "updated_at":
                    try:
                        if isinstance(value, str):
                            normalized[target_field] = _parse_iso_date(value, field=target_field)
                        elif isinstance(value, (date, datetime)):
                            normalized[target_field] = value.date() if isinstance(value, datetime) else value
                    except ValueError:
                        normalized[target_field] = date.today()
                break
    
    if "updated_at" not in normalized:
        normalized["updated_at"] = date.today()
    
    return normalized


def _normalize_order_data(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    
    field_mapping = {
        "client_id": ["client_id", "clientId"],
        "status": ["status", "orders_status", "orderStatus"],
        "created_at": ["created_at", "createdAt", "orders_created_at"],
        "shipped_at": ["shipped_at", "shippedAt", "orders_shipped_at"],
        "delivered_at": ["delivered_at", "deliveredAt", "orders_delivered_at"],
        "cancel_reason": ["cancel_reason", "cancelReason", "orders_cancel_reason"],
        "items": ["items", "order_items", "orderItems"],
    }
    
    for target_field, source_fields in field_mapping.items():
        for source_field in source_fields:
            if source_field in row and row[source_field] is not None:
                value = row[source_field]
                if target_field == "client_id":
                    try:
                        normalized[target_field] = int(value)
                    except (ValueError, TypeError):
                        pass
                elif target_field in ["created_at", "shipped_at", "delivered_at"]:
                    try:
                        if isinstance(value, str):
                            normalized[target_field] = _parse_iso_date(value, field=target_field)
                        elif isinstance(value, (date, datetime)):
                            normalized[target_field] = value.date() if isinstance(value, datetime) else value
                    except ValueError:
                        pass
                elif target_field == "items":
                    if isinstance(value, (list, str)):
                        if isinstance(value, str):
                            try:
                                value = json.loads(value)
                            except json.JSONDecodeError:
                                pass
                        if isinstance(value, list):
                            normalized[target_field] = value
                else:
                    normalized[target_field] = str(value).strip() if value else None
                break
    
    return normalized


def _process_products_data(normalized_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    results = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "errors": [],
    }
    
    with transaction.atomic():
        for idx, row in enumerate(normalized_rows, 1):
            try:
                product_id = row.get("product_id")
                product_name = row.get("product_name")
                color_code = row.get("color_code")
                price = row.get("price")
                coating_type_id = row.get("coating_type_id")
                coating_type_name = row.get("coating_type_name")
                coating_type_nomenclature = row.get("coating_type_nomenclature")
                
                if not product_name:
                    results["errors"].append(f"Строка {idx}: отсутствует название продукта")
                    continue
                
                if price is None:
                    results["errors"].append(f"Строка {idx}: отсутствует цена")
                    continue
                
                coating_type = None
                if coating_type_id:
                    try:
                        coating_type = CoatingTypes.objects.get(pk=coating_type_id)
                    except CoatingTypes.DoesNotExist:
                        results["errors"].append(f"Строка {idx}: тип покрытия {coating_type_id} не найден")
                        continue
                elif coating_type_name or coating_type_nomenclature:
                    if not coating_type_nomenclature:
                        coating_type_nomenclature = coating_type_name or f"TYPE_{uuid4().hex[:8]}"
                    coating_type, created = CoatingTypes.objects.get_or_create(
                        coating_type_nomenclatura=_clip(coating_type_nomenclature, length=40),
                        defaults={"coating_type_name": _clip(coating_type_name or coating_type_nomenclature, length=40)},
                    )
                
                if not coating_type:
                    results["errors"].append(f"Строка {idx}: не указан тип покрытия")
                    continue
                
                product_name_clipped = _clip(product_name, length=40)
                color_code_int = int(color_code) if color_code is not None else 0
                price_int = int(price)
                
                if product_id:
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                UPDATE products 
                                SET coating_types_id = %s, color = %s, product_name = %s, product_price = %s
                                WHERE product_id = %s
                                """,
                                [coating_type.coating_types_id, color_code_int, product_name_clipped, price_int, product_id],
                            )
                            if cursor.rowcount > 0:
                                results["updated"] += 1
                            else:
                                results["errors"].append(f"Строка {idx}: продукт {product_id} не найден")
                                continue
                    except Exception as e:
                        results["errors"].append(f"Строка {idx}: ошибка обновления продукта: {str(e)}")
                        continue
                else:
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                INSERT INTO products (coating_types_id, color, product_name, product_price)
                                VALUES (%s, %s, %s, %s)
                                RETURNING product_id
                                """,
                                [coating_type.coating_types_id, color_code_int, product_name_clipped, price_int],
                            )
                            results["created"] += 1
                    except Exception as e:
                        results["errors"].append(f"Строка {idx}: ошибка создания продукта: {str(e)}")
                        continue
                
                results["processed"] += 1
            except Exception as e:
                results["errors"].append(f"Строка {idx}: неожиданная ошибка: {str(e)}")
                continue
    
    return results


def _process_series_data(normalized_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    results = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "errors": [],
    }
    
    with transaction.atomic():
        for idx, row in enumerate(normalized_rows, 1):
            try:
                series_id = row.get("series_id")
                product_id = row.get("product_id")
                series_name = row.get("series_name")
                production_date = row.get("production_date")
                expire_date = row.get("expire_date")
                
                if not product_id:
                    results["errors"].append(f"Строка {idx}: отсутствует product_id")
                    continue
                
                try:
                    product = Products.objects.get(pk=product_id)
                except Products.DoesNotExist:
                    results["errors"].append(f"Строка {idx}: продукт {product_id} не найден")
                    continue
                
                series_name_clipped = _clip(series_name, length=20) if series_name else None
                
                if series_id:
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                UPDATE series 
                                SET product_id = %s, series_name = %s, series_production_date = %s, series_expire_date = %s
                                WHERE series_id = %s
                                """,
                                [product.product_id, series_name_clipped, production_date, expire_date, series_id],
                            )
                            if cursor.rowcount > 0:
                                results["updated"] += 1
                            else:
                                results["errors"].append(f"Строка {idx}: серия {series_id} не найдена")
                                continue
                    except Exception as e:
                        results["errors"].append(f"Строка {idx}: ошибка обновления серии: {str(e)}")
                        continue
                else:
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                INSERT INTO series (product_id, series_name, series_production_date, series_expire_date)
                                VALUES (%s, %s, %s, %s)
                                RETURNING series_id
                                """,
                                [product.product_id, series_name_clipped, production_date, expire_date],
                            )
                            results["created"] += 1
                    except Exception as e:
                        results["errors"].append(f"Строка {idx}: ошибка создания серии: {str(e)}")
                        continue
                
                results["processed"] += 1
            except Exception as e:
                results["errors"].append(f"Строка {idx}: неожиданная ошибка: {str(e)}")
                continue
    
    return results


def _process_stocks_data(normalized_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    results = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "errors": [],
    }
    
    with transaction.atomic():
        for idx, row in enumerate(normalized_rows, 1):
            try:
                series_id = row.get("series_id")
                client_id = row.get("client_id")
                quantity = row.get("quantity")
                is_reserved = row.get("is_reserved", False)
                updated_at = row.get("updated_at", date.today())
                
                if not series_id:
                    results["errors"].append(f"Строка {idx}: отсутствует series_id")
                    continue
                
                if quantity is None:
                    results["errors"].append(f"Строка {idx}: отсутствует количество")
                    continue
                
                try:
                    series = Series.objects.get(pk=series_id)
                except Series.DoesNotExist:
                    results["errors"].append(f"Строка {idx}: серия {series_id} не найдена")
                    continue
                
                client = None
                if client_id:
                    try:
                        client = Clients.objects.get(pk=client_id)
                    except Clients.DoesNotExist:
                        results["errors"].append(f"Строка {idx}: клиент {client_id} не найден")
                        continue
                
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT stocks_id FROM stocks 
                            WHERE series_id = %s AND (client_id = %s OR (client_id IS NULL AND %s IS NULL))
                            """,
                            [series_id, client_id, client_id],
                        )
                        existing = cursor.fetchone()
                        
                        if existing:
                            cursor.execute(
                                """
                                UPDATE stocks 
                                SET stocks_count = %s, stocks_is_reserved_for_client = %s, stocks_update_at = %s
                                WHERE stocks_id = %s
                                """,
                                [quantity, is_reserved, updated_at, existing[0]],
                            )
                            results["updated"] += 1
                        else:
                            cursor.execute(
                                """
                                INSERT INTO stocks (series_id, client_id, stocks_count, stocks_is_reserved_for_client, stocks_update_at)
                                VALUES (%s, %s, %s, %s, %s)
                                RETURNING stocks_id
                                """,
                                [series_id, client.client_id if client else None, quantity, is_reserved, updated_at],
                            )
                            results["created"] += 1
                        
                        results["processed"] += 1
                except Exception as e:
                    results["errors"].append(f"Строка {idx}: ошибка обработки остатка: {str(e)}")
                    continue
            except Exception as e:
                results["errors"].append(f"Строка {idx}: неожиданная ошибка: {str(e)}")
                continue
    
    return results


def _process_orders_data(normalized_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    results = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "errors": [],
    }
    
    with transaction.atomic():
        for idx, row in enumerate(normalized_rows, 1):
            try:
                client_id = row.get("client_id")
                status = row.get("status", "В ожидании")
                created_at = row.get("created_at", date.today())
                shipped_at = row.get("shipped_at")
                delivered_at = row.get("delivered_at")
                cancel_reason = row.get("cancel_reason")
                items = row.get("items", [])
                
                if not client_id:
                    results["errors"].append(f"Строка {idx}: отсутствует client_id")
                    continue
                
                try:
                    client = Clients.objects.get(pk=client_id)
                except Clients.DoesNotExist:
                    results["errors"].append(f"Строка {idx}: клиент {client_id} не найден")
                    continue
                
                status_clipped = _clip(status, length=30)
                cancel_reason_clipped = _clip(cancel_reason, length=100) if cancel_reason else None
                
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO orders (client_id, orders_status, orders_created_at, orders_shipped_at, orders_delivered_at, orders_cancel_reason)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            RETURNING orders_id
                            """,
                            [client.client_id, status_clipped, created_at, shipped_at, delivered_at, cancel_reason_clipped],
                        )
                        order_id = cursor.fetchone()[0]
                        
                        for item_idx, item in enumerate(items, 1):
                            try:
                                product_id = int(item.get("product_id") or item.get("productId"))
                                quantity = int(item.get("quantity") or item.get("count", 0))
                                series_id = item.get("series_id") or item.get("seriesId")
                                
                                if quantity <= 0:
                                    results["errors"].append(f"Строка {idx}, элемент {item_idx}: количество должно быть больше 0")
                                    continue
                                
                                product = Products.objects.get(pk=product_id)
                                series = None
                                if series_id:
                                    try:
                                        series = Series.objects.get(pk=int(series_id))
                                        if series.product_id != product_id:
                                            results["errors"].append(f"Строка {idx}, элемент {item_idx}: серия не принадлежит продукту")
                                            continue
                                    except Series.DoesNotExist:
                                        results["errors"].append(f"Строка {idx}, элемент {item_idx}: серия {series_id} не найдена")
                                        continue
                                
                                cursor.execute(
                                    """
                                    INSERT INTO orders_items (orders_id, product_id, series_id, order_items_count)
                                    VALUES (%s, %s, %s, %s)
                                    """,
                                    [order_id, product_id, series.series_id if series else None, quantity],
                                )
                            except (KeyError, ValueError, TypeError) as e:
                                results["errors"].append(f"Строка {idx}, элемент {item_idx}: ошибка обработки элемента: {str(e)}")
                                continue
                            except Products.DoesNotExist:
                                results["errors"].append(f"Строка {idx}, элемент {item_idx}: продукт не найден")
                                continue
                        
                        results["created"] += 1
                        results["processed"] += 1
                except Exception as e:
                    results["errors"].append(f"Строка {idx}: ошибка создания заказа: {str(e)}")
                    continue
            except Exception as e:
                results["errors"].append(f"Строка {idx}: неожиданная ошибка: {str(e)}")
                continue
    
    return results


@csrf_exempt
@require_http_methods(["POST"])
@require_admin_auth
def admin_data_lake_upload(request):
    if "file" not in request.FILES:
        return JsonResponse({"error": "Файл не предоставлен"}, status=400)
    
    uploaded_file = request.FILES["file"]
    data_type = request.POST.get("data_type", "").lower()
    
    if not data_type:
        return JsonResponse({"error": "Параметр 'data_type' обязателен (products, series, stocks, orders)"}, status=400)
    
    if data_type not in ["products", "series", "stocks", "orders"]:
        return JsonResponse(
            {"error": f"Неподдерживаемый тип данных: {data_type}. Поддерживаются: products, series, stocks, orders"},
            status=400,
        )
    
    file_content = uploaded_file.read()
    
    try:
        rows = _parse_json_file(file_content)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    
    if not rows:
        return JsonResponse({"error": "Файл пуст или не содержит данных"}, status=400)
    
    try:
        if data_type == "products":
            normalized_rows = [_normalize_product_data(row) for row in rows]
            results = _process_products_data(normalized_rows)
        elif data_type == "series":
            normalized_rows = [_normalize_series_data(row) for row in rows]
            results = _process_series_data(normalized_rows)
        elif data_type == "stocks":
            normalized_rows = [_normalize_stock_data(row) for row in rows]
            results = _process_stocks_data(normalized_rows)
        elif data_type == "orders":
            normalized_rows = [_normalize_order_data(row) for row in rows]
            results = _process_orders_data(normalized_rows)
        else:
            return JsonResponse({"error": "Неподдерживаемый тип данных"}, status=400)
    except Exception as e:
        return JsonResponse(
            {
                "error": f"Ошибка обработки данных: {str(e)}",
                "traceback": traceback.format_exc(),
            },
            status=500,
        )
    
    response_data = {
        "data_type": data_type,
        "file_name": uploaded_file.name,
        "rows_count": len(rows),
        "results": results,
    }
    
    status_code = 200 if not results["errors"] else 207
    
    return JsonResponse(response_data, status=status_code)


@csrf_exempt
@require_http_methods(["GET"])
@require_admin_auth
def admin_data_lake_info(request):
    return JsonResponse(
        {
            "supported_formats": ["JSON"],
            "supported_data_types": {
                "products": {
                    "description": "Продукты",
                    "required_fields": ["product_name", "price"],
                    "optional_fields": ["product_id", "color_code", "coating_type_id", "coating_type_name", "coating_type_nomenclature"],
                },
                "series": {
                    "description": "Серии продуктов",
                    "required_fields": ["product_id"],
                    "optional_fields": ["series_id", "series_name", "production_date", "expire_date"],
                },
                "stocks": {
                    "description": "Остатки на складе",
                    "required_fields": ["series_id", "quantity"],
                    "optional_fields": ["client_id", "is_reserved", "updated_at"],
                },
                "orders": {
                    "description": "Заказы",
                    "required_fields": ["client_id", "items"],
                    "optional_fields": ["status", "created_at", "shipped_at", "delivered_at", "cancel_reason"],
                },
            },
            "field_mapping": {
                "note": "Система поддерживает различные варианты названий полей (camelCase, snake_case, etc.)",
                "examples": {
                    "product_id": ["product_id", "id", "productId"],
                    "product_name": ["product_name", "name", "productName"],
                },
            },
        }
    )

