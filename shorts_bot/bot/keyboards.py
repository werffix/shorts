from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="15-30 секунд", callback_data="duration:15:30")],
            [InlineKeyboardButton(text="30-60 секунд", callback_data="duration:30:60")],
            [InlineKeyboardButton(text="60-90 секунд", callback_data="duration:60:90")],
        ]
    )


def format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="9:16 вертикальный", callback_data="format:9:16")],
        [InlineKeyboardButton(text="16:9 горизонтальный", callback_data="format:16:9")],
        [InlineKeyboardButton(text="16:9 с размытым фоном", callback_data="format:16:9_blur")],
        [InlineKeyboardButton(text="1:1 квадрат", callback_data="format:1:1")],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")],
        [InlineKeyboardButton(text="🖼 Баннер", callback_data="admin:banner")],
        [InlineKeyboardButton(text="💾 Память", callback_data="admin:memory")],
    ])


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Спросить у ИИ", callback_data="ai:open")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:open")],
    ])
