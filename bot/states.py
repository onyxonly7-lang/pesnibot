from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    recipient = State()
    occasion = State()
    voice = State()
    story = State()
    confirm_story = State()
    awaiting_edit = State()
    preview_requested = State()


