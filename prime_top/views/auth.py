from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Users
from .utils import (
    TOKEN_TTL_SECONDS,
    _check_user_password,
    _issue_token,
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

