from __future__ import annotations

import re
from datetime import date

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.hashers import make_password
from django.db import transaction

from ..models import Cart, Clients, Users
from django.utils import timezone
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

    email = str(email_raw).strip().lower()
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


def _validate_email(email: str) -> bool:
    """Basic email validation."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


@csrf_exempt
@require_http_methods(["POST"])
def register_view(request):
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    email_raw = payload.get("email")
    password = payload.get("password")
    client_block = payload.get("client") or {}
    client_name_raw = payload.get("client_name") or client_block.get("name")
    client_email_raw = payload.get("client_email") or client_block.get("email")

    # Validate required fields
    if not email_raw or not password:
        return JsonResponse({"error": "Fields 'email' and 'password' are required."}, status=400)
    
    if not client_name_raw or not client_email_raw:
        return JsonResponse(
            {"error": "Fields 'client_name' and 'client_email' are required for registration."},
            status=400,
        )

    email = str(email_raw).strip().lower()
    client_email_normalized = str(client_email_raw).strip().lower()
    client_name_raw_clean = str(client_name_raw).strip()
    client_name_normalized = client_name_raw_clean.lower()

    # Validate email format
    if not _validate_email(email):
        return JsonResponse({"error": "Invalid user email format."}, status=400)
    
    if not _validate_email(client_email_normalized):
        return JsonResponse({"error": "Invalid client email format."}, status=400)

    # Check if user already exists
    if Users.objects.filter(user_email__iexact=email).exists():
        return JsonResponse({"error": "User with this email already exists."}, status=409)

    # Validate password length
    if len(str(password)) < 6:
        return JsonResponse({"error": "Password must be at least 6 characters long."}, status=400)

    # Validate client name length
    if len(client_name_raw_clean) == 0:
        return JsonResponse({"error": "Client name cannot be empty."}, status=400)

    # Find or create client with transactional safety
    client_email_clipped = _clip(client_email_normalized, length=30)
    client_name_clipped = _clip(client_name_raw_clean, length=20)

    with transaction.atomic():
        client = (
            Clients.objects.filter(
                client_email__iexact=client_email_normalized,
                client_name__iexact=client_name_normalized,
            ).first()
        )
        if client is None:
            client = Clients.objects.create(
                client_name=client_name_clipped,
                client_email=client_email_clipped,
            )

        # Create user
        email_clipped = _clip(email, length=30)
        user = Users.objects.create(
            client=client,
            user_email=email_clipped,
            user_password_hash=make_password(str(password)),
            user_is_active=True,
            user_created_at=date.today(),
        )

    # Create cart for user if it doesn't exist
    # This ensures every user has their own personal cart
    Cart.objects.get_or_create(
        user=user,
        defaults={
            "cart_created_at": timezone.now(),
            "cart_updated_at": timezone.now(),
        },
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

