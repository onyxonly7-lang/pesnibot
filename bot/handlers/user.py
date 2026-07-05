import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import db
from bot.config import ADMIN_CHAT_ID, MANAGER_USERNAME
from bot.services import gpt, mureka
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

# value → display label with emoji (used both on buttons and in the edited message)
RECIPIENT_LABELS = {
    "Чоловіку": "👨 Чоловіку",
    "Дружині": "👩 Дружині",
    "Хлопцю": "👦 Хлопцю",
    "Дівчині": "👧 Дівчині",
    "Мамі": "👩‍👦 Мамі",
    "Подрузі": "👯 Подрузі",
    "Дитині": "👶 Дитині",
    "Інше": "✨ Інше",
}

OCCASION_LABELS = {
    "День народження": "🎂 День народження",
    "Річниця": "💍 Річниця",
    "Освідчення": "💕 Освідчення",
    "Подяка": "🙏 Подяка",
    "Вибачення": "🤍 Вибачення",
    "Інший привід": "🎊 Інший привід",
}

MOOD_LABELS = {
    "Весела і легка": "🌟 Весела і легка",
    "Душевна і зворушлива": "❤️ Душевна і зворушлива",
    "Сучасна і нестандартна": "🎸 Сучасна і нестандартна",
}

VOICE_LABELS = {
    "Чоловічий": "Чоловічий",
    "Жіночий": "Жіночий",
    "Дует": "Дует",
}

def _grid2(labels: dict[str, str], prefix: str) -> InlineKeyboardMarkup:
    """2 buttons per row so they fit even on small (~5\") screens."""
    btns = [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{value}")
            for value, label in labels.items()]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


KB_RECIPIENT = _grid2(RECIPIENT_LABELS, "r")
KB_OCCASION = _grid2(OCCASION_LABELS, "o")

KB_MOOD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=label, callback_data=f"m:{value}")]
    for value, label in MOOD_LABELS.items()
])

KB_VOICE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=label, callback_data=f"v:{value}")]
    for value, label in VOICE_LABELS.items()
])


def _manager_btn() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="💬 Написати менеджеру", url="https://t.me/Studio24pro")


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
    await db.log_event(call.from_user.id, "start")
    await call.message.answer("Для кого пісня?\n\n", reply_markup=KB_RECIPIENT)
    await call.answer()


async def _collapse_buttons(call: CallbackQuery, question: str, label: str) -> None:
    """Remove the keyboard and leave only the question + chosen option."""
    try:
        await call.message.edit_text(f"{question}: {label}")
    except Exception:
        pass


@router.callback_query(F.data.startswith("r:"), OrderForm.recipient)
async def cb_recipient(call: CallbackQuery, state: FSMContext) -> None:
    recipient = call.data.split(":", 1)[1]
    await state.update_data(recipient=recipient)
    data = await state.get_data()
    await db.update_order(data["order_id"], recipient=recipient)
    await db.log_event(call.from_user.id, "q1_recipient")
    await state.set_state(OrderForm.occasion)
    await _collapse_buttons(call, "Для кого пісня?", RECIPIENT_LABELS.get(recipient, recipient))
    await call.message.answer("З якого приводу?\n\n", reply_markup=KB_OCCASION)
    await call.answer()


@router.callback_query(F.data.startswith("o:"), OrderForm.occasion)
async def cb_occasion(call: CallbackQuery, state: FSMContext) -> None:
    occasion = call.data.split(":", 1)[1]
    await state.update_data(occasion=occasion)
    data = await state.get_data()
    await db.update_order(data["order_id"], occasion=occasion)
    await db.log_event(call.from_user.id, "q2_occasion")
    await state.set_state(OrderForm.mood)
    await _collapse_buttons(call, "З якого приводу?", OCCASION_LABELS.get(occasion, occasion))
    await call.message.answer("Який настрій пісні? 🎭\n\n", reply_markup=KB_MOOD)
    await call.answer()


@router.callback_query(F.data.startswith("m:"), OrderForm.mood)
async def cb_mood(call: CallbackQuery, state: FSMContext) -> None:
    mood = call.data.split(":", 1)[1]
    await state.update_data(mood=mood)
    data = await state.get_data()
    await db.update_order(data["order_id"], mood=mood)
    await db.log_event(call.from_user.id, "q3_mood")
    await state.set_state(OrderForm.voice)
    await _collapse_buttons(call, "Який настрій пісні? 🎭", MOOD_LABELS.get(mood, mood))
    await call.message.answer("Який голос потрібен?\n\n", reply_markup=KB_VOICE)
    await call.answer()


@router.callback_query(F.data.startswith("v:"), OrderForm.voice)
async def cb_voice(call: CallbackQuery, state: FSMContext) -> None:
    voice = call.data.split(":", 1)[1]
    await state.update_data(voice=voice)
    data = await state.get_data()
    await db.update_order(data["order_id"], voice=voice)
    await db.log_event(call.from_user.id, "q4_voice")
    await state.set_state(OrderForm.story)
    await _collapse_buttons(call, "Який голос потрібен?", VOICE_LABELS.get(voice, voice))
    await call.message.answer(
        "А тепер найважливіше — саме від цього залежить ваша пісня."
    )
    await call.message.answer(
        "🎵 Розкажіть, що робить цю людину особливою:\n"
        "ім'я або як ви її/його називаєте, характер, захоплення,\n"
        "ваші теплі або смішні моменти і спогади,\n"
        "важливі фрази та побажання.\n\n"
        "Пишіть вільно, як відчуваєте 💛\n\n"
        "🎙 Або надиктуйте голосове повідомлення — ми все зрозуміємо!"
    )
    await call.answer()


async def _transcribe_message_voice(message: Message, bot: Bot) -> str | None:
    """Download a voice message and return its Whisper transcription."""
    from io import BytesIO
    buf = BytesIO()
    await bot.download(message.voice, destination=buf)
    try:
        return await gpt.transcribe_voice(buf.getvalue())
    except Exception:
        log.exception("Whisper transcription failed")
        return None


async def _save_first_story(message: Message, state: FSMContext, story: str) -> None:
    await state.update_data(story=story)
    data = await state.get_data()
    await db.update_order(data["order_id"], story=story)
    await db.log_event(message.from_user.id, "story")
    await state.set_state(OrderForm.story_review)
    await message.answer(
        "✅ Ми зберегли вашу історію.\n"
        "Якщо хочете щось додати — просто напишіть ще одним повідомленням. "
        "Коли будете готові — натисніть кнопку нижче.",
        reply_markup=_kb(("🚀 Стартуємо!", "start_generation")),
    )


async def _save_addition(message: Message, state: FSMContext, addition: str) -> None:
    data = await state.get_data()
    story = "\n".join(p for p in (data.get("story", ""), addition) if p).strip()
    await state.update_data(story=story)
    await db.update_order(data["order_id"], story=story)
    await message.answer(
        "✅ Додано! Готові?",
        reply_markup=_kb(("🚀 Стартуємо!", "start_generation")),
    )


@router.message(OrderForm.story, F.voice)
async def msg_story_voice(message: Message, state: FSMContext, bot: Bot) -> None:
    text = await _transcribe_message_voice(message, bot)
    if not text:
        await message.answer("⚠️ Не вдалося розпізнати голосове. Спробуйте ще раз або напишіть текстом.")
        return
    await _save_first_story(message, state, text)


@router.message(OrderForm.story)
async def msg_story(message: Message, state: FSMContext) -> None:
    await _save_first_story(message, state, message.text or "")


@router.message(OrderForm.story_review, F.voice)
async def msg_story_addition_voice(message: Message, state: FSMContext, bot: Bot) -> None:
    text = await _transcribe_message_voice(message, bot)
    if not text:
        await message.answer("⚠️ Не вдалося розпізнати голосове. Спробуйте ще раз або напишіть текстом.")
        return
    await _save_addition(message, state, text)


@router.message(OrderForm.story_review)
async def msg_story_addition(message: Message, state: FSMContext) -> None:
    await _save_addition(message, state, message.text or "")


@router.callback_query(F.data == "start_generation", OrderForm.story_review)
async def cb_start_generation(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await call.answer()
    await state.set_state(OrderForm.preview_requested)
    data = await state.get_data()
    await _run_generation(call.from_user.id, data, bot)


def _admin_upload_kb(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"📎 Завантажити файли вручну для {order_id}",
            callback_data=f"upload:{order_id}",
        )
    ]])


async def _run_generation(chat_id: int, data: dict, bot: Bot) -> None:
    order_id = data["order_id"]
    story = data.get("story", "")
    recipient = data.get("recipient", "")
    occasion = data.get("occasion", "")
    mood = data.get("mood", "")
    voice = data.get("voice", "")

    # 1. Lyrics via GPT (JSON → lyrics)
    try:
        lyrics = await gpt.generate_lyrics(recipient, occasion, mood, voice, story)
    except Exception:
        log.exception("GPT error for order %s", order_id)
        await bot.send_message(
            chat_id,
            "⚠️ Виникла помилка під час генерації тексту. Спробуйте ще раз або зверніться до менеджера.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_manager_btn()]]),
        )
        return

    # 2. Deterministic Mureka style prompt (recipient + mood + voice)
    mureka_prompt = mureka.build_mureka_prompt(recipient, mood, voice)
    await db.update_order(order_id, lyrics=lyrics, mureka_prompt=mureka_prompt, status="preview_sent")
    order = await db.get_order(order_id)

    # 3. Notify admin: order + lyrics + mureka_prompt + manual-upload fallback button
    admin_text = (
        f"🎵 Нове замовлення на музичне превью\n\n"
        f"Замовлення: {order_id}\n"
        f"Telegram: @{order['username']} / {order['user_id']}\n"
        f"Кому: {recipient}\n"
        f"Привід: {occasion}\n"
        f"Настрій: {mood}\n"
        f"Голос: {voice}\n\n"
        f"🎚 Mureka prompt:\n{mureka_prompt}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 Текст пісні:\n{lyrics}\n"
        f"━━━━━━━━━━━━━━━"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_text, reply_markup=_admin_upload_kb(order_id))

    # 4. Tell the client generation started
    await bot.send_message(
        chat_id,
        "🎵 Ваша пісня створюється...\n"
        "Це займе близько 5 хвилин. Ми надішлемо превью одразу як буде готово!",
    )

    # 5. Two independent Mureka generations (Variant 1 + Variant 2)
    try:
        tracks = await asyncio.gather(
            mureka.generate_track(lyrics, mureka_prompt),
            mureka.generate_track(lyrics, mureka_prompt),
        )
    except Exception as e:
        log.exception("Mureka generation failed for order %s", order_id)
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"⚠️ Mureka не змогла згенерувати пісню для {order_id}.\n"
            f"Причина: {type(e).__name__}: {str(e)[:600]}\n\n"
            f"Завантажте файли вручну 👇",
            reply_markup=_admin_upload_kb(order_id),
        )
        return

    # 6. Upload full tracks to Telegram to obtain persistent file_ids
    #    (first downloaded = Варіант 1, second = Варіант 2)
    file_ids: list[str] = []
    for i, mp3_bytes in enumerate(tracks, start=1):
        sent = await bot.send_audio(
            ADMIN_CHAT_ID,
            audio=BufferedInputFile(mp3_bytes, filename=f"{order_id}_variant{i}.mp3"),
            title=f"{order_id} — Варіант {i} (повна версія)",
        )
        media = sent.audio or sent.document
        file_ids.append(media.file_id)

    await db.update_order(order_id, variant1_file_id=file_ids[0], variant2_file_id=file_ids[1])

    # 7. Send previews to the client via the existing preview pipeline
    from bot.handlers.admin import _send_previews_to_client
    order = await db.get_order(order_id)
    await _send_previews_to_client(bot, order)


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
    await db.log_event(call.from_user.id, "chosen")
    await call.answer()

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
        "❤️ Чудовий вибір!\n\n"
        "Ваша пісня вже повністю готова.\n\n"
        "Щоб отримати повну версію без обмежень, натисніть кнопку оплатити 👇",
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
    await db.log_event(uid, "paid")

    await bot.send_message(
        uid,
        "🎉 Дякуємо за довіру!\nВаша повна версія пісні готова 🎵",
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
        reply_markup=_kb(("🎵 Створити ще одну пісню", "start_order")),
    )


deliver_full_track = _deliver_full_track
