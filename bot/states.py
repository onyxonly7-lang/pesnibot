from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    recipient = State()
    occasion = State()
    voice = State()
    story = State()
    story_review = State()
    preview_requested = State()


class UploadExamples(StatesGroup):
    collecting = State()


class UploadOrder(StatesGroup):
    waiting = State()


