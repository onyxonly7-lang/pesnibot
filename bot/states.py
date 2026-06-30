from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    recipient = State()
    occasion = State()
    voice = State()
    story = State()
    preview_requested = State()


class UploadExamples(StatesGroup):
    collecting = State()


