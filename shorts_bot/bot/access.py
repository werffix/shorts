from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from shorts_bot.config import get_settings
from shorts_bot.db.repository import is_allowed

LOCK_TEXT = (
    "🔒 Нет доступа\n\n"
    "OneShorts Creator — твой личный монтажёр Shorts на автопилоте 🎬\n\n"
    "Присылаешь ссылку или видео — получаешь готовые вертикальные ролики для TikTok, Reels и YouTube Shorts. "
    "Без монтажёров, без программ, без часов работы. Всё делает ИИ.\n\n"
    "Доступно только для команды q1 team — пиши нам"
)


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and await is_allowed(user.id, get_settings().admin_id):
            return await handler(event, data)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Написать команде", url=get_settings().access_contact_url)
        ]])
        if isinstance(event, Message):
            await event.answer(LOCK_TEXT, reply_markup=keyboard)
        elif isinstance(event, CallbackQuery):
            await event.answer("Нет доступа", show_alert=True)
        return None
