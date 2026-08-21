from aiogram.fsm.state import State, StatesGroup


class JobSettings(StatesGroup):
    choosing_duration = State()
    choosing_format = State()


class AdminStates(StatesGroup):
    waiting_user = State()
    waiting_banner = State()
