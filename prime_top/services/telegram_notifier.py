from __future__ import annotations

import logging
import os
from typing import Iterable

import requests
from django.conf import settings

from ..models import TelegramLink, Orders

logger = logging.getLogger(__name__)


def _bot_token() -> str | None:
    return getattr(settings, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN")


def _api_base() -> str:
    return getattr(settings, "TELEGRAM_API_URL", None) or os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")


def _enabled() -> bool:
    raw = getattr(settings, "NOTIFY_TG_ENABLED", True)
    if isinstance(raw, str):
        return raw.lower() == "true"
    return bool(raw)


def send_message(chat_id: int, text: str) -> bool:
    """Send a plain text message to Telegram chat."""
    if not _enabled():
        logger.info("Telegram notifications disabled; skipped sending to chat_id=%s", chat_id)
        return False

    token = _bot_token()
    if not token:
        logger.warning("Telegram bot token is not configured; cannot send notification.")
        return False

    url = f"{_api_base().rstrip('/')}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            logger.warning("Telegram API returned %s for chat_id=%s: %s", response.status_code, chat_id, response.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.exception("Failed to send Telegram message to chat_id=%s: %s", chat_id, exc)
        return False


def notify_order_status_change(order: Orders, from_status: str | None, to_status: str | None, note: str | None = None) -> int:
    """
    Notify all active Telegram links of the client's users about order status change.
    Returns count of attempted deliveries.
    """
    links: Iterable[TelegramLink] = TelegramLink.objects.filter(
        user__client=order.client,
        is_active=True,
    )

    parts = [f"Заказ #{order.orders_id}"]
    if from_status or to_status:
        parts.append(f"Статус: {from_status or '-'} → {to_status or '-'}")
    if note:
        parts.append(f"Комментарий: {note}")
    text = ". ".join(parts)

    sent = 0
    for link in links:
        if send_message(link.tg_chat_id, text):
            link.last_status_sent_at = getattr(order, "orders_created_at", None) or getattr(order, "orders_delivered_at", None)
            link.save(update_fields=["last_status_sent_at"])
        sent += 1
    return sent


__all__ = ["send_message", "notify_order_status_change"]
