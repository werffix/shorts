from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="15-30 секунд", callback_data="duration:15:30")],
            [InlineKeyboardButton(text="30-60 секунд", callback_data="duration:30:60")],
            [InlineKeyboardButton(text="60-90 секунд", callback_data="duration:60:90")],
        ]
    )
