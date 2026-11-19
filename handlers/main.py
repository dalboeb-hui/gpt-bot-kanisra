import logging

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from providers.gemini import (
    available_keys,
    ask_gemini,
    GeminiQuotaError,
    GeminiUnavailableError,
    GeminiTemporaryError,
)

router = Router()
logger = logging.getLogger(__name__)

# Активный API выбирается отдельно для каждого пользователя.
selected_key: dict[int, int] = {}


def main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    current = selected_key.get(user_id, 1)
    for number in (1, 2, 3):
        mark = " ✅" if number == current else ""
        state = "🟢" if number in available_keys() else "⚪"
        builder.button(
            text=f"{state} Gemini API №{number}{mark}",
            callback_data=f"select:{number}",
        )
    builder.button(text="🗑 Новый диалог", callback_data="clear")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def welcome_text(user_id: int) -> str:
    current = selected_key.get(user_id, 1)
    ready = available_keys()
    if not ready:
        status = "⚠️ Ни один API-ключ пока не добавлен."
    else:
        status = f"Доступны ключи: {', '.join('№' + str(x) for x in ready)}."
    return (
        "🤖 <b>Gemini AI Bot</b>\n\n"
        "Выбери один из трёх API-ключей и отправь сообщение.\n"
        f"Сейчас выбран: <b>Gemini API №{current}</b>\n"
        f"{status}\n\n"
        "История хранится в памяти, пока бот работает. "
        "После перезапуска она очищается."
    )


@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    selected_key.setdefault(user_id, 1)
    await message.answer(welcome_text(user_id), reply_markup=main_keyboard(user_id))


@router.message(Command("menu"))
async def menu(message: Message):
    user_id = message.from_user.id
    selected_key.setdefault(user_id, 1)
    await message.answer(welcome_text(user_id), reply_markup=main_keyboard(user_id))


@router.callback_query(F.data.startswith("select:"))
async def select_api(callback: CallbackQuery):
    user_id = callback.from_user.id
    number = int(callback.data.split(":", 1)[1])

    if number not in available_keys():
        await callback.answer(
            f"Gemini API №{number} не настроен. Добавь его ключ в Render.",
            show_alert=True,
        )
        return

    selected_key[user_id] = number
    await callback.answer(f"Выбран Gemini API №{number}")
    if callback.message:
        await callback.message.edit_text(
            welcome_text(user_id),
            reply_markup=main_keyboard(user_id),
        )


@router.callback_query(F.data == "clear")
async def clear_history(callback: CallbackQuery):
    from providers.gemini import clear_user_history

    clear_user_history(callback.from_user.id)
    await callback.answer("История диалога очищена")
    if callback.message:
        await callback.message.edit_text(
            "🗑 <b>Новый диалог начат.</b>\n\n"
            "Выбери API и отправь сообщение.",
            reply_markup=main_keyboard(callback.from_user.id),
        )


@router.message()
async def chat(message: Message):
    if not message.text or message.text.startswith("/"):
        return

    user_id = message.from_user.id
    selected_key.setdefault(user_id, 1)
    key_number = selected_key[user_id]

    if key_number not in available_keys():
        await message.answer(
            f"⚠️ Gemini API №{key_number} не настроен или недоступен. "
            "Выбери другой API в меню."
        )
        return

    status = await message.answer("⏳ Gemini готовит ответ…")
    try:
        answer = await ask_gemini(user_id, key_number, message.text)
        # Telegram ограничивает длину одного сообщения.
        chunks = [answer[i:i + 4000] for i in range(0, len(answer), 4000)] or ["Пустой ответ от Gemini."]
        await status.edit_text(chunks[0], parse_mode=None)
        for chunk in chunks[1:]:
            await message.answer(chunk, parse_mode=None)
    except GeminiQuotaError:
        await status.edit_text(
            f"🔴 <b>Лимит исчерпан</b> для Gemini API №{key_number}.\n"
            "Попробуй другой ключ или проверь квоту и ограничения в Google AI Studio."
        )
    except GeminiTemporaryError:
        await status.edit_text(
            f"⏳ Gemini API №{key_number} временно ограничил запросы или не отвечает. "
            "Попробуй немного позже."
        )
    except GeminiUnavailableError:
        await status.edit_text(
            f"⚠️ <b>Gemini API №{key_number} недоступен.</b>\n"
            "Проверь ключ, доступ к модели и настройки проекта Google AI."
        )
    except Exception:
        logger.exception("Unexpected error while processing Telegram message")
        await status.edit_text("❌ Произошла непредвиденная ошибка. Подробности есть в логах Render.")
