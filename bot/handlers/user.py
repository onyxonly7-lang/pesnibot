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
from bot.states import OrderForm

log = logging.getLogger(__name__)
router = Router()


_SEPARATOR = "➖➖➖➖➖➖➖➖➖➖"


def _is_ukrainian(text: str) -> bool:
    ua_chars = set("іїєґІЇЄҐ")
    return bool(ua_chars.intersection(text))


def _after_lyrics_text(lyrics: str) -> str:
    return (
        f"\n\n\n{_SEPARATOR}\n\n"
        "🎵 Це лише текст — у музиці та голосі\n"
        "пісня розкриється зовсім інакше.\n\n"
        "Ви можете внести правки або одразу створити музичне превью.\n"
    )


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

KB_GENERATE = _kb(("📝 Створити текст пісні", "generate_lyrics"))


def kb_lyrics(can_edit: bool) -> InlineKeyboardMarkup:
    buttons = []
    if can_edit:
        buttons.append(("✏️ Внести правки", "edit_lyrics"))
    buttons.append(("🎵 Створити музичне превью", "request_preview"))
    return _kb(*buttons)


def _manager_btn() -> InlineKeyboardButton:
    username = MANAGER_USERNAME.lstrip("@")
    return InlineKeyboardButton(text="💬 Написати менеджеру", url=f"https://t.me/{username}")



def kb_payment_failed(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Повторити оплату", callback_data=f"pay:{order_id}")],
        [InlineKeyboardButton(text="🏦 Банківський переказ", callback_data=f"bank:{order_id}")],
        [_manager_btn()],
    ])


# ── /start ────────────────────────────────────────────────────────────────

async def _send_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🎵 Створіть персональну пісню за своєю історією.\n\n"
        "Спочатку ви отримаєте безкоштовне музичне превью.\n"
        "Оплачуйте лише якщо пісня сподобається. 🎁\n",
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
            await bot.send_audio(uid, audio=file_id, title=title, performer="Studio 24")
            any_sent = True
    if not any_sent:
        await bot.send_message(uid, "Приклади поки не завантажені. Зверніться до менеджера.")
    await bot.send_message(uid, "Хочете створити свою?\n\n", reply_markup=KB_AFTER_EXAMPLES)


# ── order flow ────────────────────────────────────────────────────────────

def _kb_limit_reached() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_manager_btn()]])


@router.callback_query(F.data == "start_order")
async def cb_start_order(call: CallbackQuery, state: FSMContext) -> None:
    # TODO: re-enable after testing
    # is_admin = call.from_user.id == ADMIN_CHAT_ID
    # if not is_admin:
    #     count = await db.count_orders_last_24h(call.from_user.id)
    #     if count >= 2:
    #         await call.message.answer(
    #             "Ви вже створили 2 пісні сьогодні.\n"
    #             "Спробуйте завтра або напишіть менеджеру.\n",
    #             reply_markup=_kb_limit_reached(),
    #         )
    #         await call.answer()
    #         return
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
        "✨ Чудово! А тепер найважливіше — розкажіть про цю людину.\n"
        "Саме від цього залежить ваша пісня."
    )
    await call.message.answer(
        "🎵 Розкажіть, що робить цю людину особливою:\n"
        "ім'я або як ви її/його називаєте, характер, захоплення,\n"
        "ваші теплі або смішні моменти і спогади,\n"
        "важливі фрази та побажання.\n\n"
        "Пишіть вільно, як відчуваєте 💛\n\n"
        "Пісня буде створена мовою вашої історії"
    )
    await call.answer()


@router.message(OrderForm.story)
async def msg_story(message: Message, state: FSMContext) -> None:
    story = message.text or ""
    await state.update_data(story=story)
    data = await state.get_data()
    await db.update_order(data["order_id"], story=story)
    await state.set_state(OrderForm.confirm_story)
    await message.answer(
        "Чудово! Натисніть кнопку, щоб створити текст пісні.\n\n",
        reply_markup=KB_GENERATE,
    )


@router.callback_query(F.data == "generate_lyrics", OrderForm.confirm_story)
async def cb_generate_lyrics(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await call.answer()
    wait_msg = await call.message.answer("⏳ Аналізуємо вашу історію...")
    try:
        lyrics = await gpt.generate_lyrics(
            data["recipient"], data["occasion"], data["voice"], data["story"]
        )
    except Exception as e:
        log.exception("GPT error")
        await wait_msg.delete()
        await call.message.answer(f"Помилка генерації тексту: {e}")
        return
    await db.update_order(data["order_id"], lyrics=lyrics)
    await state.update_data(lyrics=lyrics)
    await wait_msg.delete()
    await call.message.answer(
        f"Ваш текст пісні готовий.\n\n{lyrics}" + _after_lyrics_text(lyrics),
        reply_markup=kb_lyrics(can_edit=True),
    )


@router.callback_query(F.data == "edit_lyrics")
async def cb_edit_lyrics(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    order = await db.get_order(data.get("order_id", ""))
    if not order:
        await call.answer("Замовлення не знайдено.", show_alert=True)
        return
    if order["edit_used"]:
        await call.answer("Правку вже було використано.", show_alert=True)
        return
    await state.set_state(OrderForm.awaiting_edit)
    await call.message.answer("Напишіть що змінити — слово, фразу або загальний напрямок. Чим детальніше, тим краще результат ✨")
    await call.answer()


@router.message(OrderForm.awaiting_edit)
async def msg_edit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order = await db.get_order(data.get("order_id", ""))
    if not order or order["edit_used"]:
        await message.answer("Правку вже було використано.")
        return
    wait_msg = await message.answer("⏳ Вношу правки...")
    try:
        new_lyrics = await gpt.edit_lyrics(order["lyrics"], message.text or "", recipient=order.get("recipient", ""))
    except Exception as e:
        log.exception("GPT edit error")
        await wait_msg.delete()
        await message.answer(f"Помилка: {e}")
        return
    await db.update_order(order["id"], lyrics=new_lyrics, edit_used=1)
    await state.update_data(lyrics=new_lyrics)
    await state.set_state(OrderForm.confirm_story)
    await wait_msg.delete()
    await message.answer(
        f"Ваш оновлений текст пісні:\n\n{new_lyrics}" + _after_lyrics_text(new_lyrics),
        reply_markup=kb_lyrics(can_edit=False),
    )


@router.callback_query(F.data == "request_preview")
async def cb_request_preview(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    order_id = data.get("order_id", "")
    order = await db.get_order(order_id)
    if not order:
        await call.answer("Замовлення не знайдено.", show_alert=True)
        return

    await db.update_order(order_id, status="preview_sent")
    await state.set_state(OrderForm.preview_requested)
    await call.answer()

    await call.message.answer(
        "🎧 Ми створюємо для вас музичне превью.\n"
        "Зазвичай превью готове протягом 10–15 хвилин."
    )

    progress = [
        "✅ Аналізуємо історію",
        "✅ Підбираємо настрій пісні",
        "✅ Створюємо музику",
        "⏳ Готуємо превью...",
    ]
    for step in progress:
        await asyncio.sleep(20)
        await call.message.answer(step)

    admin_text = (
        f"🎵 Нове замовлення на музичне превью\n\n"
        f"Замовлення: {order_id}\n"
        f"Telegram: @{order['username']} / {order['user_id']}\n"
        f"Кому: {order['recipient']}\n"
        f"Привід: {order['occasion']}\n"
        f"Голос: {order['voice']}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 Текст пісні:\n"
        f"{order['lyrics']}\n"
        f"━━━━━━━━━━━━━━━"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_text)
    await bot.send_message(
        ADMIN_CHAT_ID,
        "Завантажте два аудіофайли.\n"
        "У назві першого файлу має бути цифра 1,\n"
        "другого — цифра 2.\n"
        "Наприклад: track_1.mp3 і track_2.mp3"
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
    pay_url = f"https://worker-production-2e5c.up.railway.app/pay/{order_id}"
    await call.message.answer(
        f"🎵 Ви обрали варіант {variant}.\n\n"
        "Натисніть кнопку нижче, щоб оплатити та отримати\n"
        "повну версію пісні одразу після оплати.\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатити повну пісню — 349 грн", url=pay_url)],
            [_manager_btn()],
        ]),
    )
    await call.answer()


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

    variant = order["chosen_variant"] or 1
    file_id = order[f"variant{variant}_file_id"]
    if not file_id:
        if reply_to:
            await reply_to.answer("Файл ще не завантажено.")
        return

    await db.update_order(order_id, status="paid")
    await bot.send_audio(order["user_id"], audio=file_id, caption="🎵 Ваша повна версія пісні!")


deliver_full_track = _deliver_full_track
