import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import db
from bot.config import ADMIN_CHAT_ID, MANAGER_USERNAME
from bot.services import gpt
from bot.services.wayforpay import create_invoice
from bot.states import OrderForm

log = logging.getLogger(__name__)
router = Router()


# ── keyboard helper ────────────────────────────────────────────────────────

def _kb(*buttons: tuple[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in buttons]
    )


# ── static keyboards ───────────────────────────────────────────────────────

KB_START = _kb(
    ("🎵 Створити пісню", "start_order"),
    ("🎧 Приклади пісень", "examples"),
    ("❓ Як це працює", "how_it_works"),
)

KB_AFTER_EXAMPLES = _kb(
    ("🎵 Створити пісню", "start_order"),
    ("❓ Як це працює", "how_it_works"),
)

KB_HOW = _kb(("🎵 Створити пісню", "start_order"))

KB_RECIPIENT = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Чоловіку",  callback_data="r:Чоловіку"),  InlineKeyboardButton(text="Дружині",  callback_data="r:Дружині")],
    [InlineKeyboardButton(text="Хлопцю",    callback_data="r:Хлопцю"),    InlineKeyboardButton(text="Дівчині",  callback_data="r:Дівчині")],
    [InlineKeyboardButton(text="Мамі",      callback_data="r:Мамі"),      InlineKeyboardButton(text="Подрузі",  callback_data="r:Подрузі")],
    [InlineKeyboardButton(text="Дитині",    callback_data="r:Дитині"),    InlineKeyboardButton(text="Інше",     callback_data="r:Інше")],
])

KB_OCCASION = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="День народження", callback_data="o:День народження"), InlineKeyboardButton(text="Річниця",      callback_data="o:Річниця")],
    [InlineKeyboardButton(text="Освідчення",      callback_data="o:Освідчення"),      InlineKeyboardButton(text="Подяка",       callback_data="o:Подяка")],
    [InlineKeyboardButton(text="Вибачення",       callback_data="o:Вибачення"),       InlineKeyboardButton(text="Інший привід", callback_data="o:Інший привід")],
])

KB_VOICE = _kb(
    ("Чоловічий", "v:Чоловічий"),
    ("Жіночий", "v:Жіночий"),
    ("Чоловічий + жіночий", "v:Чоловічий + жіночий"),
)


def _manager_btn() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="💬 Написати менеджеру", url="https://t.me/Studio24pro")


def kb_payment_failed(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Повторити оплату", callback_data=f"pay:{order_id}")],
        [InlineKeyboardButton(text="🏦 Банківський переказ", callback_data=f"bank:{order_id}")],
        [_manager_btn()],
    ])


# ── progress animation ────────────────────────────────────────────────────

_PROGRESS_STEPS = [
    (27, "📖 Аналізуємо вашу історію…\nШукаємо найважливіші моменти, щоб пісня була саме про вас.\n⏳"),
    (35, "✍️ Створюємо текст пісні…\nПеретворюємо ваші спогади на рядки, які легко лягають на музику.\n⏳"),
    (35, "🎼 Підбираємо мелодію та настрій…\nВаша історія може звучати зовсім по-різному, тому ми підбираємо найкращий варіант.\n⏳"),
    (35, "🎤 Створюємо вокал…\nНамагаємося, щоб голос і подача максимально передавали емоції вашої історії.\n⏳"),
    (35, "✨ Майже готово…\nПеревіряємо фінальний результат і готуємо два музичні варіанти для прослуховування.\n⏳"),
]


async def _run_progress(chat_id: int, bot: Bot) -> None:
    """Show all progress steps; intermediate steps edit one message, last step is a new message."""
    msg = await bot.send_message(
        chat_id,
        "🎵 Починаємо створення вашої пісні.\n"
        "Це займе приблизно 5–10 хвилин. Ми повідомимо, щойно все буде готово.\n⏳",
    )
    *intermediate, (last_delay, last_text) = _PROGRESS_STEPS
    for delay, text in intermediate:
        await asyncio.sleep(delay)
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
        except Exception:
            pass
    # Last step: delete the edited message and send a NEW one so Telegram triggers a notification
    await asyncio.sleep(last_delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass
    await bot.send_message(chat_id, last_text)


# ── /start ────────────────────────────────────────────────────────────────

async def _send_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🎵 Ми спочатку створимо вашу пісню.\n\n"
        "❤️ Ви безкоштовно прослухаєте прев'ю.\n\n"
        "💳 Оплата — лише якщо результат вам справді сподобається.",
        reply_markup=KB_START,
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await _send_start(message, state)


@router.message(F.text.lower().in_({"start", "старт", "начать", "привет", "hi", "hello", "почати", "привіт"}))
async def cmd_start_text(message: Message, state: FSMContext) -> None:
    await _send_start(message, state)


# ── static sections ───────────────────────────────────────────────────────

@router.callback_query(F.data == "how_it_works")
async def cb_how(call: CallbackQuery) -> None:
    await call.message.answer(
        "🎵 Як це працює:\n\n"
        "1️⃣ Розкажіть для кого пісня і з якого приводу.\n"
        "2️⃣ Поділіться історією, спогадами та побажаннями.\n"
        "3️⃣ Отримайте готовий текст пісні.\n"
        "4️⃣ Прослухайте два безкоштовних музичних превью.\n"
        "5️⃣ Оберіть варіант, який сподобався.\n"
        "6️⃣ Оплатіть і отримайте повну версію пісні.\n\n",
        reply_markup=KB_HOW,
    )
    await call.answer()


@router.callback_query(F.data == "examples")
async def cb_examples(call: CallbackQuery, bot: Bot) -> None:
    await call.answer()
    uid = call.from_user.id
    examples = [
        ("EXAMPLE_SONG_WIFE",    "Пісня для дружини"),
        ("EXAMPLE_SONG_HUSBAND", "Пісня для чоловіка"),
        ("EXAMPLE_SONG_FRIEND",  "Пісня для подруги"),
        ("EXAMPLE_SONG_MOM",     "Пісня для мами"),
    ]
    any_sent = False
    for key, title in examples:
        file_id = await db.get_setting(key)
        if file_id:
            await bot.send_audio(uid, audio=file_id, title=title)
            any_sent = True
    if not any_sent:
        await bot.send_message(uid, "Приклади поки не завантажені. Зверніться до менеджера.")
    await bot.send_message(uid, "Хочете створити свою?\n\n", reply_markup=KB_AFTER_EXAMPLES)


# ── order flow ────────────────────────────────────────────────────────────

def _kb_limit_reached() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_manager_btn()]])


@router.callback_query(F.data == "start_order")
async def cb_start_order(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    order_id = await db.create_order(call.from_user.id, call.from_user.username or "")
    await state.update_data(order_id=order_id)
    await state.set_state(OrderForm.recipient)
    await call.message.answer("Для кого пісня?\n\n", reply_markup=KB_RECIPIENT)
    await call.answer()


@router.callback_query(F.data.startswith("r:"), OrderForm.recipient)
async def cb_recipient(call: CallbackQuery, state: FSMContext) -> None:
    recipient = call.data.split(":", 1)[1]
    await state.update_data(recipient=recipient)
    data = await state.get_data()
    await db.update_order(data["order_id"], recipient=recipient)
    await state.set_state(OrderForm.occasion)
    await call.message.answer("З якого приводу?\n\n", reply_markup=KB_OCCASION)
    await call.answer()


@router.callback_query(F.data.startswith("o:"), OrderForm.occasion)
async def cb_occasion(call: CallbackQuery, state: FSMContext) -> None:
    occasion = call.data.split(":", 1)[1]
    await state.update_data(occasion=occasion)
    data = await state.get_data()
    await db.update_order(data["order_id"], occasion=occasion)
    await state.set_state(OrderForm.voice)
    await call.message.answer("Який голос потрібен?\n\n", reply_markup=KB_VOICE)
    await call.answer()


@router.callback_query(F.data.startswith("v:"), OrderForm.voice)
async def cb_voice(call: CallbackQuery, state: FSMContext) -> None:
    voice = call.data.split(":", 1)[1]
    await state.update_data(voice=voice)
    data = await state.get_data()
    await db.update_order(data["order_id"], voice=voice)
    await state.set_state(OrderForm.story)
    await call.message.answer(
        "А тепер найважливіше — саме від цього залежить ваша пісня."
    )
    await call.message.answer(
        "🎵 Розкажіть, що робить цю людину особливою:\n"
        "ім'я або як ви її/його називаєте, характер, захоплення,\n"
        "ваші теплі або смішні моменти і спогади,\n"
        "важливі фрази та побажання.\n\n"
        "Пишіть вільно, як відчуваєте 💛"
    )
    await call.answer()


@router.message(OrderForm.story)
async def msg_story(message: Message, state: FSMContext, bot: Bot) -> None:
    story = message.text or ""
    await state.update_data(story=story)
    data = await state.get_data()
    order_id = data["order_id"]
    await db.update_order(order_id, story=story)
    await state.set_state(OrderForm.preview_requested)

    gpt_error: list[Exception] = []

    async def _generate() -> None:
        try:
            lyrics = await gpt.generate_lyrics(
                data["recipient"], data["occasion"], data["voice"], story
            )
        except Exception as e:
            log.exception("GPT error for order %s", order_id)
            gpt_error.append(e)
            return
        await db.update_order(order_id, lyrics=lyrics, status="preview_sent")
        order = await db.get_order(order_id)
        admin_text = (
            f"🎵 Нове замовлення на музичне превью\n\n"
            f"Замовлення: {order_id}\n"
            f"Telegram: @{order['username']} / {order['user_id']}\n"
            f"Кому: {order['recipient']}\n"
            f"Привід: {order['occasion']}\n"
            f"Голос: {order['voice']}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📝 Текст пісні:\n"
            f"{lyrics}\n"
            f"━━━━━━━━━━━━━━━"
        )
        await bot.send_message(ADMIN_CHAT_ID, admin_text)
        await bot.send_message(ADMIN_CHAT_ID, "Завантажте 2 аудіофайли")

    # Animation and GPT run in parallel; animation always plays all steps
    await asyncio.gather(
        _run_progress(message.from_user.id, bot),
        _generate(),
    )

    if gpt_error:
        await bot.send_message(
            message.from_user.id,
            "⚠️ Виникла помилка під час генерації тексту. Спробуйте ще раз або зверніться до менеджера.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_manager_btn()]]),
        )
    else:
        await bot.send_message(
            message.from_user.id,
            "🎧 Ми створюємо для вас музичне превью.\n"
            "Зазвичай превью готове протягом 10–15 хвилин.\n"
            "Ми надішлемо його сюди, щойно воно буде готове.",
        )


# ── variant selection & payment ───────────────────────────────────────────

@router.callback_query(F.data.startswith("choose:"))
async def cb_choose_variant(call: CallbackQuery, state: FSMContext) -> None:
    variant = int(call.data.split(":")[1])
    data = await state.get_data()
    order_id = data.get("order_id", "")
    if not order_id:
        order = await db.get_latest_order_for_user(call.from_user.id)
        if order:
            order_id = order["id"]
    order = await db.get_order(order_id)
    if order and order["status"] == "paid":
        await call.answer("Це замовлення вже оплачено.", show_alert=True)
        return
    await db.update_order(order_id, chosen_variant=variant, status="chosen")
    await call.answer()

    await call.message.answer(
        "❤️ Чудовий вибір!\n\n"
        "Ваша пісня вже повністю готова.\n\n"
        "У безкоштовному прев'ю ви почули лише її частину.\n"
        "Щоб отримати повну версію без обмежень, натисніть кнопку нижче\n"
        "👇",
    )

    try:
        pay_url = await create_invoice(order_id)
    except Exception:
        log.exception("Failed to create WayForPay invoice for order %s", order_id)
        await call.message.answer(
            "⚠️ Не вдалося сформувати посилання на оплату. "
            "Будь ласка, зверніться до менеджера.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_manager_btn()]]),
        )
        return

    await call.message.answer(
        "💳 Оплатити пісню:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатити пісню — 349 грн", url=pay_url)],
            [_manager_btn()],
        ]),
    )


@router.callback_query(F.data.startswith("bank:"))
async def cb_bank(call: CallbackQuery) -> None:
    from bot.config import IBAN
    order_id = call.data.split(":", 1)[1]
    await call.message.answer(
        f"Реквізити для оплати:\n"
        f"IBAN: {IBAN}\n"
        f"Призначення платежу: {order_id}\n\n"
        f"Після оплати надішліть скриншот менеджеру.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_manager_btn()]]),
    )
    await call.answer()


# ── /paid manual close ────────────────────────────────────────────────────

@router.message(Command("paid"))
async def cmd_paid(message: Message, bot: Bot) -> None:
    if message.from_user.id != ADMIN_CHAT_ID and message.chat.id != ADMIN_CHAT_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Використання: /paid ORDER-XXXX")
        return
    order_id = parts[1].upper()
    await _deliver_full_track(bot, order_id, message)


async def _deliver_full_track(bot: Bot, order_id: str, reply_to: Message | None = None) -> None:
    order = await db.get_order(order_id)
    if not order:
        if reply_to:
            await reply_to.answer("Замовлення не знайдено.")
        return
    if order["status"] == "paid":
        return

    await db.update_order(order_id, status="paid")
    uid = order["user_id"]
    chosen = order["chosen_variant"]

    await bot.send_message(
        uid,
        "🎉 Дякуємо за довіру!\nВаша повна версія пісні готова — тримайте 🎵",
    )

    if chosen:
        file_id = order[f"variant{chosen}_file_id"]
        if not file_id:
            log.error("Order %s: chosen_variant=%s but file_id is empty", order_id, chosen)
            if reply_to:
                await reply_to.answer(f"Файл варіанту {chosen} ще не завантажено.")
            return
        await bot.send_audio(uid, audio=file_id, title="Ваша пісня")
    else:
        log.warning("Order %s paid but chosen_variant is NULL — sending both variants", order_id)
        await bot.send_message(uid, "Будь ласка, ось обидва варіанти вашої пісні:")
        for v in (1, 2):
            fid = order[f"variant{v}_file_id"]
            if fid:
                await bot.send_audio(uid, audio=fid, title=f"Варіант {v}")

    await bot.send_message(
        uid,
        "Бажаєте створити ще одну пісню?",
        reply_markup=_kb(("🎵 Створити нову пісню", "start_order")),
    )


deliver_full_track = _deliver_full_track
