from __future__ import annotations

from datetime import date

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.hashers import make_password

from ..models import Clients, Users
from .utils import (
    TOKEN_TTL_SECONDS,
    _check_user_password,
    _issue_token,
    _clip,
    _parse_json_body,
    _serialize_client,
)


@csrf_exempt
@require_http_methods(["POST"])
def login_view(request):
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    email_raw = payload.get("email")
    password = payload.get("password")

    if not email_raw or not password:
        return JsonResponse({"error": "Fields 'email' and 'password' are required."}, status=400)

    email = str(email_raw).strip()
    user = Users.objects.select_related("client").filter(user_email__iexact=email).first()
    if not user or not _check_user_password(str(password), user.user_password_hash):
        return JsonResponse({"error": "Invalid email or password."}, status=401)

    if not user.user_is_active:
        return JsonResponse({"error": "User account is inactive."}, status=403)

    if not user.client_id:
        return JsonResponse({"error": "User is not linked to a client profile."}, status=403)

    token = _issue_token(user.user_id)
    response_payload = {
        "token": token,
        "expires_in": TOKEN_TTL_SECONDS,
        "user": {
            "id": user.user_id,
            "email": user.user_email,
            "created_at": user.user_created_at,
            "client": _serialize_client(user.client),
        },
    }
    return JsonResponse(response_payload)


@csrf_exempt
@require_http_methods(["POST"])
def register_view(request):
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    email_raw = payload.get("email")
    password = payload.get("password")
    client_id = payload.get("client_id")
    client_block = payload.get("client") or {}
    client_name_raw = payload.get("client_name") or client_block.get("name")
    client_email_raw = payload.get("client_email") or client_block.get("email")

    if not email_raw or not password:
        return JsonResponse({"error": "Fields 'email' and 'password' are required."}, status=400)
    if not client_id and (not client_name_raw or not client_email_raw):
        return JsonResponse({"error": "Provide either 'client_id' or both 'client_name' and 'client_email'."}, status=400)

    email = str(email_raw).strip()

    if Users.objects.filter(user_email__iexact=email).exists():
        return JsonResponse({"error": "User with this email already exists."}, status=409)

    client = None
    if client_id:
        try:
            client = Clients.objects.get(pk=int(client_id))
        except (Clients.DoesNotExist, ValueError):
            return JsonResponse({"error": "Client not found."}, status=404)
    else:
        # Reuse existing client by email if found; otherwise create a new one
        client_email = _clip(str(client_email_raw).strip(), length=30)
        client_name = _clip(str(client_name_raw).strip(), length=20)
        existing = Clients.objects.filter(client_email__iexact=client_email).first()
        client = existing or Clients.objects.create(
            client_name=client_name,
            client_email=client_email,
        )

    user = Users.objects.create(
        client=client,
        user_email=email,
        user_password_hash=make_password(str(password)),
        user_is_active=True,
        user_created_at=date.today(),
    )

    token = _issue_token(user.user_id)
    response_payload = {
        "token": token,
        "expires_in": TOKEN_TTL_SECONDS,
        "user": {
            "id": user.user_id,
            "email": user.user_email,
            "created_at": user.user_created_at,
            "client": _serialize_client(client),
        },
    }
    return JsonResponse(response_payload, status=201)

