from __future__ import annotations

import json
import re
from datetime import date, datetime
from functools import wraps
from typing import Dict, List, Optional

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core import signing
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse

from ..models import (
    Clients,
    OrderStatusHistory,
    Orders,
    Products,
    Series,
    Users,
)


RAL_REGEX = re.compile(r"(?:ral\s*)?(?P<code>\d{4})", re.IGNORECASE)

TOKEN_SALT = "prime-top-auth"
TOKEN_TTL_SECONDS = getattr(settings, "AUTH_TOKEN_TTL_SECONDS", 60 * 60 * 12)
AUTH_HEADER_PREFIX = "Token"

ANALYSIS_NUMERIC_FIELDS: List[str] = [
    "analyses_blesk_pri_60_grad",
    "analyses_uslovnaya_vyazkost",
    "analyses_delta_e",
    "analyses_delta_l",
    "analyses_delta_a",
    "analyses_delta_b",
    "analyses_color_diff_deltae_d8",
    "analyses_vremya_sushki",
    "analyses_pikovaya_temperatura",
    "analyses_tolschina_dlya_grunta",
    "analyses_tolsch_plenki_zhidk",
    "analyses_tolsch_dly_em_lak_ch",
    "analyses_teoreticheskii_rashod",
    "analyses_prochnost_pri_izgibe",
    "analyses_stoikost_k_obrat_udaru",
    "analyses_tverdost_po_karandashu",
    "analyses_prochn_rastyazh_po_er",
    "analyses_blesk",
    "analyses_plotnost",
    "analyses_mass_dolya_nelet_vesh",
    "analyses_stepen_peretira",
    "analyses_kolvo_vykr_s_partii",
]


def _normalized_color(color_candidate: str) -> Optional[str]:
    if not color_candidate:
        return None

    match = RAL_REGEX.search(color_candidate)
    if match:
        return match.group("code")

    digits = re.sub(r"\D", "", color_candidate)
    return digits[:4] if len(digits) >= 4 else None


def _color_filter(color: str, *, prefix: str = "") -> Q:
    normalized = _normalized_color(color)

    def prefixed(field: str) -> str:
        return f"{prefix}{field}" if prefix else field

    or_filter = (
        Q(**{prefixed("product__product_name__icontains"): color})
        | Q(**{prefixed("product__coating_types__coating_type_name__icontains"): color})
        | Q(**{prefixed("product__coating_types__coating_type_nomenclatura__icontains"): color})
    )
    if normalized:
        try:
            or_filter |= Q(**{prefixed("product__color"): int(normalized)})
        except ValueError:
            pass
        or_filter |= Q(**{prefixed("product__product_name__icontains"): normalized})
        or_filter |= Q(**{prefixed("product__coating_types__coating_type_nomenclatura__icontains"): normalized})
    return or_filter


def _issue_token(user_id: int) -> str:
    return signing.dumps({"user_id": user_id}, salt=TOKEN_SALT)


def _decode_token(token: str) -> Optional[Dict[str, object]]:
    if not token:
        return None
    try:
        return signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_TTL_SECONDS)
    except (signing.BadSignature, signing.SignatureExpired):
        return None


def _authenticate_token(token: str) -> Optional[Users]:
    payload = _decode_token(token)
    if not payload:
        return None
    user_id = payload.get("user_id")
    if not user_id:
        return None
    try:
        user = Users.objects.select_related("client").get(pk=user_id)
    except Users.DoesNotExist:
        return None

    if not user.user_is_active or user.client_id is None:
        return None

    return user


def _extract_token_from_request(request) -> Optional[str]:
    header = request.META.get("HTTP_AUTHORIZATION") or request.headers.get("Authorization")
    if header:
        parts = header.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == AUTH_HEADER_PREFIX.lower():
            return parts[1].strip()
    return request.GET.get("token") or request.POST.get("token")


def _check_user_password(raw_password: str, stored_hash: str) -> bool:
    if stored_hash is None:
        return False
    if check_password(raw_password, stored_hash):
        return True
    return stored_hash == raw_password


def require_client_auth(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        token = _extract_token_from_request(request)
        if not token:
            return JsonResponse({"error": "Authentication credentials were not provided."}, status=401)

        user = _authenticate_token(token)
        if not user:
            return JsonResponse({"error": "Invalid or expired authentication token."}, status=401)

        request.authenticated_user = user
        request.authenticated_client = user.client
        return view_func(request, *args, **kwargs)

    return _wrapped


def _parse_json_body(request) -> Dict[str, object]:
    if not request.body:
        return {}
    try:
        raw = request.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("JSON payload must be UTF-8 encoded.") from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON payload.") from exc


def _parse_iso_date(value: Optional[str], *, field: str) -> Optional[date]:
    if value in (None, "", []):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError as exc:
        raise ValueError(f"Field '{field}' must be a valid ISO date (YYYY-MM-DD).") from exc


def _analysis_range_filters_from_request(request, prefix: str = "") -> Dict[str, float]:
    filters: Dict[str, float] = {}
    for field in ANALYSIS_NUMERIC_FIELDS:
        min_param = request.GET.get(f"min_{field}")
        if min_param is not None:
            try:
                filters[f"{prefix}{field}__gte"] = float(min_param)
            except (TypeError, ValueError):
                raise Http404(f"Query parameter 'min_{field}' must be numeric.")
        max_param = request.GET.get(f"max_{field}")
        if max_param is not None:
            try:
                filters[f"{prefix}{field}__lte"] = float(max_param)
            except (TypeError, ValueError):
                raise Http404(f"Query parameter 'max_{field}' must be numeric.")
    return filters


def _serialize_client(client: Clients) -> Dict[str, object]:
    return {
        "id": client.client_id,
        "name": client.client_name,
        "email": client.client_email,
    }


def _serialize_product(product: Products) -> Dict[str, object]:
    coating = product.coating_types if hasattr(product, "coating_types") else None
    return {
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


def _serialize_series(
    series: Optional[Series],
    *,
    include_product: bool = True,
    available_quantity: Optional[float] = None,
) -> Optional[Dict[str, object]]:
    if series is None:
        return None
    product = series.product if include_product else None
    payload = {
        "id": series.series_id,
        "name": series.series_name,
        "production_date": series.series_production_date,
        "expire_date": series.series_expire_date,
    }
    if available_quantity is not None:
        payload["available_quantity"] = float(available_quantity)
    if include_product and product is not None:
        payload["product"] = _serialize_product(product)
    return payload


def _clip(value: Optional[str], *, length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= length else text[:length]


def _serialize_order(order: Orders, *, include_items: bool = True) -> Dict[str, object]:
    payload = {
        "id": order.orders_id,
        "client": _serialize_client(order.client),
        "status": order.orders_status,
        "created_at": order.orders_created_at,
        "shipped_at": order.orders_shipped_at,
        "delivered_at": order.orders_delivered_at,
        "cancel_reason": order.orders_cancel_reason,
    }

    if include_items:
        items = []
        order_items_qs = order.ordersitems_set.select_related(
            "product",
            "product__coating_types",
            "series",
            "series__product",
            "series__product__coating_types",
        )
        for item in order_items_qs:
            items.append(
                {
                    "id": item.order_items_id,
                    "quantity": item.order_items_count,
                    "product": _serialize_product(item.product),
                    "series": _serialize_series(item.series),
                }
            )
        payload["items"] = items
        payload["total_quantity"] = float(sum(i["quantity"] for i in items))

    history = OrderStatusHistory.objects.filter(orders=order).order_by("order_status_history_id")
    payload["status_history"] = [
        {
            "id": record.order_status_history_id,
            "from_status": record.order_status_history_from_stat,
            "to_status": record.order_status_history_to_status,
            "changed_at": record.order_status_history_chang_at,
            "note": record.order_status_history_note,
        }
        for record in history
    ]

    return payload


def _orders_summary_payload(qs) -> List[Dict[str, object]]:
    summary: List[Dict[str, object]] = []
    for row in (
        qs.values("orders_status")
        .annotate(
            total_quantity=Coalesce(Sum("ordersitems__order_items_count"), 0),
            series_count=Count("ordersitems__series", distinct=True),
            orders_count=Count("orders_id", distinct=True),
        )
        .order_by("orders_status")
    ):
        summary.append(
            {
                "status": row["orders_status"],
                "orders_count": row["orders_count"],
                "series_count": row["series_count"],
                "total_quantity": float(row["total_quantity"] or 0),
            }
        )
    return summary


__all__ = [
    "ANALYSIS_NUMERIC_FIELDS",
    "AUTH_HEADER_PREFIX",
    "TOKEN_SALT",
    "TOKEN_TTL_SECONDS",
    "_analysis_range_filters_from_request",
    "_authenticate_token",
    "_check_user_password",
    "_clip",
    "_color_filter",
    "_extract_token_from_request",
    "_issue_token",
    "_normalized_color",
    "_orders_summary_payload",
    "_parse_iso_date",
    "_parse_json_body",
    "_serialize_client",
    "_serialize_order",
    "_serialize_product",
    "_serialize_series",
    "require_client_auth",
]

