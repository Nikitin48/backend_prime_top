from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from ..models import Orders, TelegramLink, Users
from .utils import _check_user_password, _parse_json_body, _serialize_order


@csrf_exempt
@require_http_methods(["POST"])
def bot_link_view(request):
    """
    Привязка Telegram-чата к пользователю по email+пароль.
    """
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    email_raw = payload.get("email")
    password = payload.get("password")
    chat_id = payload.get("chat_id")
    username = payload.get("username")

    if not email_raw or not password or chat_id is None:
        return JsonResponse({"error": "Fields 'email', 'password', and 'chat_id' are required."}, status=400)

    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Field 'chat_id' must be an integer."}, status=400)

    try:
        email = str(email_raw).strip().lower()
        user = Users.objects.select_related("client").filter(user_email__iexact=email).first()
        if not user:
            return JsonResponse({"error": "Invalid credentials."}, status=401)

        if not _check_user_password(str(password), user.user_password_hash):
            return JsonResponse({"error": "Invalid credentials."}, status=401)

        if not user.user_is_active:
            return JsonResponse({"error": "User is inactive."}, status=403)

        if getattr(user, "user_is_admin", False):
            return JsonResponse({"error": "Admin accounts cannot link to Telegram."}, status=403)

        conflict = TelegramLink.objects.filter(tg_chat_id=chat_id_int).exclude(user=user).first()
        if conflict:
            return JsonResponse({"error": "This chat is already linked to another user."}, status=409)

        # lookup by user to avoid unique tg_chat_id conflicts on update
        link, created = TelegramLink.objects.update_or_create(
            user=user,
            defaults={
                "tg_chat_id": chat_id_int,
                "tg_username": str(username).strip() if username else None,
                "is_active": True,
            },
        )

        return JsonResponse(
            {
                "linked": True,
                "user_id": user.user_id,
                "chat_id": link.tg_chat_id,
                "created": created,
            },
            status=201 if created else 200,
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": "Internal error", "detail": str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def bot_unlink_view(request):
    """
    Отключение Telegram-уведомлений по chat_id (опционально с email).
    """
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    chat_id = payload.get("chat_id")
    email_raw = payload.get("email")

    if chat_id is None:
        return JsonResponse({"error": "Field 'chat_id' is required."}, status=400)

    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Field 'chat_id' must be an integer."}, status=400)

    link = TelegramLink.objects.select_related("user").filter(tg_chat_id=chat_id_int).first()
    if not link:
        return JsonResponse({"error": "Chat link not found."}, status=404)

    if email_raw:
        if str(email_raw).strip().lower() != str(link.user.user_email).strip().lower():
            return JsonResponse({"error": "Email does not match linked account."}, status=403)

    link.is_active = False
    link.save(update_fields=["is_active"])

    return JsonResponse({"unlinked": True})


@require_GET
def bot_orders_view(request):
    """
    Получение последних заказов по chat_id для отображения в боте.
    """
    chat_id = request.GET.get("chat_id")
    if chat_id is None:
        return JsonResponse({"error": "Query parameter 'chat_id' is required."}, status=400)

    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Query parameter 'chat_id' must be an integer."}, status=400)

    link = TelegramLink.objects.select_related("user", "user__client").filter(
        tg_chat_id=chat_id_int,
        is_active=True,
    ).first()
    if not link:
        return JsonResponse({"error": "Active chat link not found."}, status=404)

    status_param = (request.GET.get("status") or "").strip().lower()

    try:
        orders_qs = Orders.objects.select_related("client").filter(client=link.user.client)

        if status_param:
            if status_param == "current":
                # исключаем доставленные и отмененные (учитываем возможные русские варианты и пробелы)
                orders_qs = orders_qs.exclude(
                    orders_status__iregex=r'^\s*(delivered|доставлен|доставлено)\s*$'
                ).exclude(
                    orders_status__iregex=r'^\s*(cancelled|canceled|отменен|отменён|отменено)\s*$'
                )
            elif status_param == "completed":
                orders_qs = orders_qs.filter(orders_status__iregex=r'^\s*(delivered|доставлен|доставлено)\s*$')
            elif status_param in ("canceled", "cancelled"):
                orders_qs = orders_qs.filter(
                    orders_status__iregex=r'^\s*(cancelled|canceled|отменен|отменён|отменено)\s*$'
                )
            elif status_param == "all":
                pass
            else:
                statuses = [s.strip() for s in status_param.split(",") if s.strip()]
                if statuses:
                    orders_qs = orders_qs.filter(orders_status__in=statuses)

        orders_qs = orders_qs.order_by("-orders_created_at")[:20]

        orders_payload = [
            {
                "id": order.orders_id,
                "status": order.orders_status,
                "created_at": order.orders_created_at,
                "shipped_at": order.orders_shipped_at,
                "delivered_at": order.orders_delivered_at,
                "cancel_reason": order.orders_cancel_reason,
            }
            for order in orders_qs
        ]

        return JsonResponse({"count": len(orders_payload), "orders": orders_payload})
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": "Internal error", "detail": str(exc)}, status=500)


@require_GET
def bot_profile_view(request):
    """
    Профиль по chat_id: пользователь и клиент.
    """
    chat_id = request.GET.get("chat_id")
    if chat_id is None:
        return JsonResponse({"error": "Query parameter 'chat_id' is required."}, status=400)

    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Query parameter 'chat_id' must be an integer."}, status=400)

    link = TelegramLink.objects.select_related("user", "user__client").filter(
        tg_chat_id=chat_id_int,
        is_active=True,
    ).first()
    if not link:
        return JsonResponse({"error": "Active chat link not found."}, status=404)

    user = link.user
    client = user.client
    payload = {
        "user": {
            "id": user.user_id,
            "email": user.user_email,
            "first_name": getattr(user, "user_name", None),
            "last_name": getattr(user, "user_surname", None),
        },
        "client": {
            "id": client.client_id,
            "name": client.client_name,
            "email": client.client_email,
        },
    }
    return JsonResponse(payload)


@require_GET
def bot_order_detail_view(request, order_id: int):
    """
    Детали заказа по chat_id: доступно только для связанных клиентов.
    """
    chat_id = request.GET.get("chat_id")
    if chat_id is None:
        return JsonResponse({"error": "Query parameter 'chat_id' is required."}, status=400)

    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Query parameter 'chat_id' must be an integer."}, status=400)

    link = TelegramLink.objects.select_related("user", "user__client").filter(
        tg_chat_id=chat_id_int,
        is_active=True,
    ).first()
    if not link:
        return JsonResponse({"error": "Active chat link not found."}, status=404)

    try:
        order = Orders.objects.select_related("client").get(pk=order_id)
    except Orders.DoesNotExist:
        return JsonResponse({"error": "Order not found."}, status=404)

    if order.client_id != link.user.client_id:
        return JsonResponse({"error": "Order does not belong to this client."}, status=403)

    try:
        return JsonResponse(_serialize_order(order))
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": "Internal error", "detail": str(exc)}, status=500)


__all__ = ["bot_link_view", "bot_unlink_view", "bot_orders_view", "bot_profile_view", "bot_order_detail_view"]
