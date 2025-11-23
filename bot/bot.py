import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "replace_me")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prime_top_bot")


def api_url(path: str) -> str:
    base = API_BASE_URL.rstrip("/")
    p = path if path.startswith("/") else f"/{path}"
    return f"{base}{p}"


# -----------------------------------------------------------------------------
# FSM States
# -----------------------------------------------------------------------------


class LinkStates(StatesGroup):
    waiting_email = State()
    waiting_password = State()


# -----------------------------------------------------------------------------
# Keyboards
# -----------------------------------------------------------------------------


def guest_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/start")],
            [KeyboardButton(text="/link")],
            [KeyboardButton(text="/reset")],
        ],
        resize_keyboard=True,
    )


def authed_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/profile")],
            [KeyboardButton(text="/orders")],
            [KeyboardButton(text="/help")],
            [KeyboardButton(text="/unlink")],
        ],
        resize_keyboard=True,
    )


def orders_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Все заказы", callback_data="status:all")],
            [InlineKeyboardButton(text="Текущие", callback_data="status:current")],
            [InlineKeyboardButton(text="Завершенные", callback_data="status:completed")],
            [InlineKeyboardButton(text="Отмененные", callback_data="status:cancelled")],
        ]
    )


# -----------------------------------------------------------------------------
# API helpers
# -----------------------------------------------------------------------------


async def api_post(session: aiohttp.ClientSession, path: str, payload: dict) -> tuple[int, dict]:
    try:
        async with session.post(api_url(path), json=payload, timeout=10) as resp:
            status = resp.status
            text = await resp.text()
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"error": "Invalid JSON from backend", "raw": text}
            return status, data
    except Exception as exc:  # noqa: BLE001
        logger.exception("API POST failed: %s", exc)
        return 500, {"error": str(exc)}


async def api_get(session: aiohttp.ClientSession, path: str, params: dict) -> tuple[int, dict]:
    try:
        async with session.get(api_url(path), params=params, timeout=10) as resp:
            status = resp.status
            text = await resp.text()
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"error": "Invalid JSON from backend", "raw": text}
            return status, data
    except Exception as exc:  # noqa: BLE001
        logger.exception("API GET failed: %s", exc)
        return 500, {"error": str(exc)}


# -----------------------------------------------------------------------------
# Handlers
# -----------------------------------------------------------------------------


async def cmd_help(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "Как пользоваться ботом:\n\n"
        "• /link — привязать аккаунт (e-mail и пароль с сайта). Без привязки заказы и уведомления недоступны.\n"
        "• /profile — показать ваши данные и компанию.\n"
        "• /orders — список заказов с фильтрами: Все, Текущие, Завершенные, Отмененные."
        " В списке можно обновить или вернуться к выбору фильтра.\n"
        "• /unlink — отключить уведомления и отвязать чат.\n"
        "• /reset — полный сброс (отвязка) + при необходимости очистите историю чата вручную.\n"
    )
    await message.answer(text, reply_markup=authed_menu())


async def cmd_start(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    await state.clear()
    linked = await is_linked(session, message.chat.id)
    if linked:
        text = (
            "Снова на связи! Чат привязан.\n\n"
            "Меню:\n"
            "• /profile — профиль\n"
            "• /orders — заказы\n"
            "• /help — подсказки\n"
            "• /unlink — отключить уведомления"
        )
        await message.answer(text, reply_markup=authed_menu())
    else:
        text = (
            "Привет! Я бот Prime Top.\n"
            "Отправляю уведомления об изменении статусов заказов.\n\n"
            "Сначала привяжите аккаунт: /link (email + пароль сайта).\n"
            "Если нет аккаунта — зарегистрируйтесь на сайте, затем вернитесь сюда."
        )
        await send_welcome_with_logo(message, text)
        await message.answer("Нажмите /link, чтобы привязать аккаунт.", reply_markup=guest_menu())


async def cmd_link(message: types.Message, state: FSMContext):
    await state.set_state(LinkStates.waiting_email)
    await message.answer("Введите ваш e-mail (как на сайте):", reply_markup=ReplyKeyboardRemove())


async def process_email(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    email = (message.text or "").strip()
    if "@" not in email:
        await message.answer("Похоже, это не e-mail. Попробуйте еще раз или /cancel.")
        return
    await state.update_data(email=email)
    await state.set_state(LinkStates.waiting_password)
    await message.answer("Теперь введите пароль от сайта:", reply_markup=ReplyKeyboardRemove())


async def process_password(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    password = message.text or ""
    data = await state.get_data()
    email = data.get("email")
    payload = {
        "email": email,
        "password": password,
        "chat_id": message.chat.id,
        "username": message.from_user.username,
    }
    status, resp = await api_post(session, "/bot/link/", payload)

    if status in (200, 201):
        await message.answer(
            "Готово! Чат привязан. Теперь я буду слать уведомления при смене статуса заказов.\n\n"
            "Меню: /profile, /orders, /unlink",
            reply_markup=authed_menu(),
        )
        await state.clear()
        return

    detail = resp.get("detail")
    err = resp.get("error", "Ошибка")
    msg = err if not detail else f"{err}: {detail}"

    if status == 401:
        await message.answer(
            "Неверный e-mail или пароль.\n"
            "Если вы еще не зарегистрированы, зайдите на сайт и создайте аккаунт, затем попробуйте /link снова.",
            reply_markup=guest_menu(),
        )
    elif status == 403:
        await message.answer("Доступ запрещен (возможно, аккаунт неактивен или это админ).", reply_markup=guest_menu())
    elif status == 409:
        await message.answer("Этот чат уже привязан к другому аккаунту. Используйте /unlink или другой чат.", reply_markup=guest_menu())
    else:
        await message.answer(f"Не удалось привязать: {msg}", reply_markup=guest_menu())
    await state.clear()


async def cmd_unlink(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    payload = {"chat_id": message.chat.id}
    status, resp = await api_post(session, "/bot/unlink/", payload)
    if status == 200:
        await message.answer("Уведомления отключены. Если захотите снова — используйте /link.", reply_markup=guest_menu())
    else:
        await message.answer(f"Не удалось отключить: {resp.get('error', 'ошибка')}", reply_markup=guest_menu())
    await state.clear()


async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=guest_menu())


async def cmd_reset(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    await state.clear()
    await api_post(session, "/bot/unlink/", {"chat_id": message.chat.id})
    text = (
        "Сброс выполнен. Я отвязал чат.\n"
        "Удалите историю чата вручную, если нужно.\n"
        "Готов к новой привязке: нажмите /link."
    )
    await send_welcome_with_logo(message, text)


async def cmd_profile(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    status, resp = await api_get(session, "/bot/profile/", {"chat_id": message.chat.id})
    if status != 200:
        if status == 404:
            await message.answer("Активная привязка не найдена. Сначала выполните /link.", reply_markup=guest_menu())
        else:
            await message.answer(f"Не удалось получить профиль: {resp.get('error', 'ошибка')}", reply_markup=authed_menu())
        return

    user = resp.get("user", {})
    client = resp.get("client", {})
    lines = [
        f"Почта: {user.get('email')}",
        f"Имя: {user.get('first_name') or '-'}",
        f"Фамилия: {user.get('last_name') or '-'}",
        f"Компания: {client.get('name')}",
        f"Почта компании: {client.get('email')}",
    ]
    await message.answer("\n".join(lines), reply_markup=authed_menu())
    await state.clear()


async def cmd_orders(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    linked = await check_linked(session, message.chat.id)
    if not linked:
        await message.answer("Активная привязка не найдена. Сначала выполните /link.", reply_markup=guest_menu())
        return
    await send_orders_menu(message)
    await state.clear()


async def cmd_orders_current(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    await send_orders_with_status(message, session, status_value="current", title="Текущие заказы")


async def cmd_orders_completed(message: types.Message, state: FSMContext, session: aiohttp.ClientSession):
    await send_orders_with_status(message, session, status_value="completed", title="Завершенные заказы")


async def send_orders_menu(message: types.Message):
    await message.answer("Выберите категорию заказов:", reply_markup=orders_menu_keyboard())


async def send_orders_with_status(message: types.Message, session: aiohttp.ClientSession, status_value: Optional[str], title: str):
    params = {"chat_id": message.chat.id}
    if status_value:
        params["status"] = status_value
    status, resp = await api_get(session, "/bot/orders/", params)
    if status != 200:
        if status == 404:
            await message.answer("Активная привязка не найдена. Сначала выполните /link.", reply_markup=guest_menu())
        else:
            detail = resp.get("detail")
            err = resp.get("error", "Ошибка")
            msg = err if not detail else f"{err}: {detail}"
            await message.answer(f"Не удалось получить заказы: {msg}", reply_markup=authed_menu())
        return

    orders = resp.get("orders") or []
    buttons = []
    for o in orders:
        order_id = o.get("id")
        buttons.append([InlineKeyboardButton(text=f"Заказ #{order_id}", callback_data=f"order:{order_id}")])

    buttons.append(
        [
            InlineKeyboardButton(text="Обновить", callback_data=f"refresh:{status_value or 'all'}"),
            InlineKeyboardButton(text="Назад", callback_data="orders_menu"),
        ]
    )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    caption = title if orders else f"{title}: нет записей."
    await message.answer(caption, reply_markup=kb)


async def send_order_detail(message: types.Message, session: aiohttp.ClientSession, order_id: int):
    status, resp = await api_get(session, f"/bot/orders/{order_id}/", {"chat_id": message.chat.id})
    if status != 200:
        detail = resp.get("detail")
        err = resp.get("error", "Ошибка")
        msg = err if not detail else f"{err}: {detail}"
        await message.answer(f"Не удалось получить заказ #{order_id}: {msg}", reply_markup=authed_menu())
        return

    order = resp
    lines = [
        f"Заказ #{order.get('id')}",
        f"Статус: {order.get('status')}",
        f"Создан: {order.get('created_at')}",
    ]
    if order.get("shipped_at"):
        lines.append(f"Отгружен: {order.get('shipped_at')}")
    if order.get("delivered_at"):
        lines.append(f"Доставлен: {order.get('delivered_at')}")
    if order.get("cancel_reason"):
        lines.append(f"Причина отмены: {order.get('cancel_reason')}")

    items = order.get("items") or []
    if items:
        lines.append("Позиции:")
        for item in items:
            prod = item.get("product", {})
            lines.append(f"- {prod.get('name')} x {item.get('quantity')} (#{prod.get('id')})")

    await message.answer("\n".join(lines), reply_markup=authed_menu())


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def is_linked(session: aiohttp.ClientSession, chat_id: int) -> bool:
    status, _ = await api_get(session, "/bot/profile/", {"chat_id": chat_id})
    return status == 200


async def check_linked(session: aiohttp.ClientSession, chat_id: int) -> bool:
    status, _ = await api_get(session, "/bot/profile/", {"chat_id": chat_id})
    return status == 200


async def send_welcome_with_logo(message: types.Message, text: str):
    logo_path = Path(__file__).resolve().parent.parent / "image_vid" / "logo.png"
    if logo_path.exists():
        try:
            with open(logo_path, "rb") as photo:
                await message.answer_photo(photo=photo, caption=text)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отправить логотип: %s", exc)
    await message.answer(text)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def register_handlers(dp: Dispatcher, session: aiohttp.ClientSession):
    async def start_handler(message: types.Message, state: FSMContext):
        await cmd_start(message, state, session)

    async def link_handler(message: types.Message, state: FSMContext):
        await cmd_link(message, state)

    async def help_handler(message: types.Message, state: FSMContext):
        await cmd_help(message, state)

    async def unlink_handler(message: types.Message, state: FSMContext):
        await cmd_unlink(message, state, session)

    async def orders_handler(message: types.Message, state: FSMContext):
        await cmd_orders(message, state, session)

    async def profile_handler(message: types.Message, state: FSMContext):
        await cmd_profile(message, state, session)

    async def orders_current_handler(message: types.Message, state: FSMContext):
        await cmd_orders_current(message, state, session)

    async def orders_completed_handler(message: types.Message, state: FSMContext):
        await cmd_orders_completed(message, state, session)

    async def orders_cancelled_handler(message: types.Message, state: FSMContext):
        await send_orders_with_status(message, session, status_value="cancelled", title="Отмененные заказы")

    async def cancel_handler(message: types.Message, state: FSMContext):
        await cmd_cancel(message, state)

    async def reset_handler(message: types.Message, state: FSMContext):
        await cmd_reset(message, state, session)

    async def status_callback_handler(callback: types.CallbackQuery, state: FSMContext):
        data = callback.data or ""
        if data.startswith("status:"):
            status_value = data.split(":", 1)[1]
            if status_value == "current":
                title = "Текущие заказы"
            elif status_value == "completed":
                title = "Завершенные заказы"
            elif status_value in ("cancelled", "canceled"):
                title = "Отмененные заказы"
            else:
                title = "Все заказы"
            linked = await check_linked(session, callback.message.chat.id)
            if not linked:
                await callback.answer("Сначала привяжите аккаунт через /link", show_alert=True)
                return
            await send_orders_with_status(callback.message, session, status_value=status_value, title=title)
            await callback.answer()
        elif data.startswith("order:"):
            try:
                order_id = int(data.split(":", 1)[1])
            except ValueError:
                await callback.answer("Некорректный номер заказа", show_alert=True)
                return
            linked = await check_linked(session, callback.message.chat.id)
            if not linked:
                await callback.answer("Сначала привяжите аккаунт через /link", show_alert=True)
                return
            await send_order_detail(callback.message, session, order_id)
            await callback.answer()
        elif data.startswith("refresh:"):
            status_value = data.split(":", 1)[1]
            if status_value == "current":
                title = "Текущие заказы"
            elif status_value == "completed":
                title = "Завершенные заказы"
            elif status_value in ("cancelled", "canceled"):
                title = "Отмененные заказы"
            else:
                title = "Все заказы"
            await send_orders_with_status(
                callback.message,
                session,
                status_value=status_value if status_value != "all" else None,
                title=title,
            )
            await callback.answer("Обновлено")
        elif data == "orders_menu":
            await send_orders_menu(callback.message)
            await callback.answer()

    dp.message.register(start_handler, Command("start"))
    dp.message.register(help_handler, Command("help"))
    dp.message.register(link_handler, Command("link"))
    dp.message.register(unlink_handler, Command("unlink"))
    dp.message.register(profile_handler, Command("profile"))
    dp.message.register(orders_handler, Command("orders"))
    dp.message.register(orders_current_handler, Command("present"))
    dp.message.register(orders_completed_handler, Command("completed"))
    dp.message.register(orders_cancelled_handler, Command("cancelled"))
    dp.message.register(cancel_handler, Command("cancel"))
    dp.message.register(reset_handler, Command("reset"))
    dp.callback_query.register(status_callback_handler)

    async def email_handler(message: types.Message, state: FSMContext):
        await process_email(message, state, session)

    async def password_handler(message: types.Message, state: FSMContext):
        await process_password(message, state, session)

    dp.message.register(email_handler, LinkStates.waiting_email)
    dp.message.register(password_handler, LinkStates.waiting_password)


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "replace_me":
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    async with aiohttp.ClientSession() as session:
        register_handlers(dp, session)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
