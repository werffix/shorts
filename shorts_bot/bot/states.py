from aiogram.fsm.state import State, StatesGroup


class JobSettings(StatesGroup):
    choosing_duration = State()
