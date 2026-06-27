import asyncio
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import db
from bot.config import ADMIN_CHAT_ID, MANAGER_USERNAME
from bot.services import gpt
from bot.services.wayforpay import build_payment_url
from bot.states import OrderForm

log = logging.getLogger(__name__)
router = Router()

ASSETS = Path(__file__).parent.parent.parent / "assets"

_SEPARATOR = "➖➖➖➖➖➖➖➖➖➖"

def _is_ukrainian(text: str) -> bool:
    """Detect Ukrainian by presence of Ukrainian-specific letters."""
    ua_chars = set("іїєґІЇЄҐ")
    return bool(ua_chars.intersection(text))

def _after_lyrics_text(lyrics: str) -> str:
    return (
        f"\n\n\n{_SEPARATOR}\n\n"
        "🎵 Это лишь текст — в музыке и голосе\n"
        "песня раскроется совсем иначе.\n\n"
        "Вы можете внести правки или сразу\n"
        "создать музыкальное превью."
    )

# ── keyboard helper ────────────────────────────────────────────────────────

def _kb(*buttons: tuple[str, str]) -> InlineKeyboardMarkup:
    """Each tuple becomes its own row (one column layout)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in buttons]
    )


# ── static keyboards ───────────────────────────────────────────────────────

KB_START = _kb(
    ("🎵 Создать песню", "start_order"),
    ("🎧 Примеры песен", "examples"),
    ("❓ Как это работает", "how_it_works"),
)

KB_AFTER_EXAMPLES = _kb(
    ("🎵 Создать песню", "start_order"),
    ("❓ Как это работает", "how_it_works"),
)

KB_HOW = _kb(("🎵 Создать песню", "start_order"))

KB_RECIPIENT = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Мужу", callback_data="r:Мужу"),       InlineKeyboardButton(text="Жене",    callback_data="r:Жене")],
    [InlineKeyboardButton(text="Парню", callback_data="r:Парню"),     InlineKeyboardButton(text="Девушке", callback_data="r:Девушке")],
    [InlineKeyboardButton(text="Маме", callback_data="r:Маме"),       InlineKeyboardButton(text="Подруге", callback_data="r:Подруге")],
    [InlineKeyboardButton(text="Ребёнку", callback_data="r:Ребёнку"), InlineKeyboardButton(text="Другое",  callback_data="r:Другое")],
])

KB_OCCASION = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="День рождения", callback_data="o:День рождения"), InlineKeyboardButton(text="Годовщина",    callback_data="o:Годовщина")],
    [InlineKeyboardButton(text="Признание",     callback_data="o:Признание"),     InlineKeyboardButton(text="Благодарность", callback_data="o:Благодарность")],
    [InlineKeyboardButton(text="Извинения",     callback_data="o:Извинения"),     InlineKeyboardButton(text="Другой повод", callback_data="o:Другой повод")],
])

KB_VOICE = _kb(
    ("Мужской", "v:Мужской"),
    ("Женский", "v:Женский"),
    ("Мужской + женский", "v:Мужской + женский"),
)

KB_GENERATE = _kb(("📝 Создать текст песни", "generate_lyrics"))


def kb_lyrics(can_edit: bool) -> InlineKeyboardMarkup:
    buttons = []
    if can_edit:
        buttons.append(("✏️ Внести правки", "edit_lyrics"))
    buttons.append(("🎵 Создать музыкальное превью", "request_preview"))
    return _kb(*buttons)


def _manager_btn() -> InlineKeyboardButton:
    username = MANAGER_USERNAME.lstrip("@")
    return InlineKeyboardButton(text="💬 Написать менеджеру", url=f"https://t.me/{username}")


def kb_after_choose(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Получить полную песню — 399 грн", callback_data=f"pay:{order_id}")],
        [_manager_btn()],
    ])



def kb_payment_failed(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Повторить оплату", callback_data=f"pay:{order_id}")],
        [InlineKeyboardButton(text="🏦 Банковский перевод", callback_data=f"bank:{order_id}")],
        [_manager_btn()],
    ])


# ── /start ────────────────────────────────────────────────────────────────

async def _send_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🎵 Создайте персональную песню по своей истории.\n\n"
        "Сначала вы получите бесплатное музыкальное превью.\n"
        "Оплачивайте только если песня понравится.\n",
        reply_markup=KB_START,
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await _send_start(message, state)


@router.message(F.text.lower().in_({"start", "старт", "начать", "привет", "hi", "hello"}))
async def cmd_start_text(message: Message, state: FSMContext) -> None:
    await _send_start(message, state)


# ── static sections ───────────────────────────────────────────────────────

@router.callback_query(F.data == "how_it_works")
async def cb_how(call: CallbackQuery) -> None:
    await call.message.answer(
        "1️⃣ Расскажите, для кого песня и по какому поводу.\n"
        "2️⃣ Добавьте историю, воспоминания и пожелания.\n"
        "3️⃣ Получите готовый текст песни.\n"
        "4️⃣ При необходимости внесите одну правку.\n"
        "5️⃣ Получите два бесплатных музыкальных превью.\n"
        "6️⃣ Выберите понравившийся вариант.\n"
        "7️⃣ Оплатите и получите полную версию песни.\n",
        reply_markup=KB_HOW,
    )
    await call.answer()


@router.callback_query(F.data == "examples")
async def cb_examples(call: CallbackQuery, bot: Bot) -> None:
    await call.answer()
    uid = call.from_user.id
    examples = [
        ("example_mom.mp3", "🎵 Песня для мамы"),
        ("example_beloved_female.mp3", "💕 Песня для любимой"),
        ("example_beloved_male.mp3", "🎸 Песня для любимого"),
    ]
    for filename, caption in examples:
        path = ASSETS / filename
        if path.exists():
            await bot.send_audio(uid, audio=FSInputFile(str(path)), caption=caption)
        else:
            await bot.send_message(uid, f"{caption} — пока не загружена.")
    await bot.send_message(uid, "Хотите создать свою?\n", reply_markup=KB_AFTER_EXAMPLES)


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
    #             "Вы уже создали 2 песни сегодня.\n"
    #             "Попробуйте завтра или напишите менеджеру.\n",
    #             reply_markup=_kb_limit_reached(),
    #         )
    #         await call.answer()
    #         return
    await state.clear()
    order_id = await db.create_order(call.from_user.id, call.from_user.username or "")
    await state.update_data(order_id=order_id)
    await state.set_state(OrderForm.recipient)
    await call.message.answer("Для кого песня?\n", reply_markup=KB_RECIPIENT)
    await call.answer()


@router.callback_query(F.data.startswith("r:"), OrderForm.recipient)
async def cb_recipient(call: CallbackQuery, state: FSMContext) -> None:
    recipient = call.data.split(":", 1)[1]
    await state.update_data(recipient=recipient)
    data = await state.get_data()
    await db.update_order(data["order_id"], recipient=recipient)
    await state.set_state(OrderForm.occasion)
    await call.message.answer("По какому поводу?\n", reply_markup=KB_OCCASION)
    await call.answer()


@router.callback_query(F.data.startswith("o:"), OrderForm.occasion)
async def cb_occasion(call: CallbackQuery, state: FSMContext) -> None:
    occasion = call.data.split(":", 1)[1]
    await state.update_data(occasion=occasion)
    data = await state.get_data()
    await db.update_order(data["order_id"], occasion=occasion)
    await state.set_state(OrderForm.voice)
    await call.message.answer("Какой голос нужен?\n", reply_markup=KB_VOICE)
    await call.answer()


@router.callback_query(F.data.startswith("v:"), OrderForm.voice)
async def cb_voice(call: CallbackQuery, state: FSMContext) -> None:
    voice = call.data.split(":", 1)[1]
    await state.update_data(voice=voice)
    data = await state.get_data()
    await db.update_order(data["order_id"], voice=voice)
    await state.set_state(OrderForm.story)
    await call.message.answer(
        "Расскажите всё, что поможет создать песню именно про вашего человека:\n"
        "имя, характер, увлечения, ваши воспоминания, тёплые или смешные моменты,\n"
        "важные фразы и пожелания.\n\n"
        "Пишите свободно, как чувствуете."
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
        "Отлично! Нажмите кнопку, чтобы создать текст песни.\n",
        reply_markup=KB_GENERATE,
    )


@router.callback_query(F.data == "generate_lyrics", OrderForm.confirm_story)
async def cb_generate_lyrics(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await call.message.answer("⏳ Создаю текст песни, подождите...")
    await call.answer()
    try:
        lyrics = await gpt.generate_lyrics(
            data["recipient"], data["occasion"], data["voice"], data["story"]
        )
    except Exception as e:
        log.exception("GPT error")
        await call.message.answer(f"Ошибка генерации текста: {e}")
        return
    await db.update_order(data["order_id"], lyrics=lyrics)
    await state.update_data(lyrics=lyrics)
    await call.message.answer(
        f"Ваш текст песни готов.\n\n{lyrics}" + _after_lyrics_text(lyrics),
        reply_markup=kb_lyrics(can_edit=True),
    )


@router.callback_query(F.data == "edit_lyrics")
async def cb_edit_lyrics(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    order = await db.get_order(data.get("order_id", ""))
    if not order:
        await call.answer("Заказ не найден.", show_alert=True)
        return
    if order["edit_used"]:
        await call.answer("Правка уже была использована.", show_alert=True)
        return
    await state.set_state(OrderForm.awaiting_edit)
    await call.message.answer("Что именно хотите изменить в тексте? Напишите одним сообщением.")
    await call.answer()


@router.message(OrderForm.awaiting_edit)
async def msg_edit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order = await db.get_order(data.get("order_id", ""))
    if not order or order["edit_used"]:
        await message.answer("Правка уже была использована.")
        return
    await message.answer("⏳ Вношу правку...")
    try:
        new_lyrics = await gpt.edit_lyrics(order["lyrics"], message.text or "", recipient=order.get("recipient", ""))
    except Exception as e:
        log.exception("GPT edit error")
        await message.answer(f"Ошибка: {e}")
        return
    await db.update_order(order["id"], lyrics=new_lyrics, edit_used=1)
    await state.update_data(lyrics=new_lyrics)
    await state.set_state(OrderForm.confirm_story)
    await message.answer(
        f"Ваш обновлённый текст песни:\n\n{new_lyrics}" + _after_lyrics_text(new_lyrics),
        reply_markup=kb_lyrics(can_edit=False),
    )


@router.callback_query(F.data == "request_preview")
async def cb_request_preview(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    order_id = data.get("order_id", "")
    order = await db.get_order(order_id)
    if not order:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    await db.update_order(order_id, status="preview_sent")
    await state.set_state(OrderForm.preview_requested)
    await call.answer()

    await call.message.answer(
        "🎧 Мы создаём для вас музыкальное превью.\n"
        "Обычно превью готово в течение 10–15 минут."
    )

    progress = [
        "✅ Анализируем историю",
        "✅ Подбираем настроение песни",
        "✅ Создаём музыку",
        "⏳ Готовим превью...",
    ]
    for step in progress:
        await asyncio.sleep(20)
        await call.message.answer(step)

    # Уведомление только в ADMIN_CHAT_ID
    admin_text = (
        f"🎵 Новый заказ на музыкальное превью\n\n"
        f"Заказ: {order_id}\n"
        f"Telegram: @{order['username']} / {order['user_id']}\n"
        f"Кому: {order['recipient']}\n"
        f"Повод: {order['occasion']}\n"
        f"Голос: {order['voice']}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 Текст песни:\n"
        f"{order['lyrics']}\n"
        f"━━━━━━━━━━━━━━━"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_text)
    await bot.send_message(
        ADMIN_CHAT_ID,
        "Загрузите два аудиофайла.\n"
        "В названии первого файла должна быть цифра 1,\n"
        "второго — цифра 2.\n"
        "Например: track_1.mp3 и track_2.mp3"
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
    await db.update_order(order_id, chosen_variant=variant, status="chosen")
    await call.message.answer(
        f"Вы выбрали вариант {variant}.\n"
        "Полная версия песни будет доступна после оплаты.\n",
        reply_markup=kb_after_choose(order_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(call: CallbackQuery) -> None:
    order_id = call.data.split(":", 1)[1]
    order = await db.get_order(order_id)
    if not order:
        await call.answer("Заказ не найден.", show_alert=True)
        return
    if order["status"] == "paid":
        await call.answer("Этот заказ уже оплачен.", show_alert=True)
        return
    url = build_payment_url(order_id, call.from_user.id)
    await call.message.answer(
        "Полная версия песни — 399 грн.\n"
        "После оплаты бот сразу отправит вам полный трек.\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 399 грн", url=url)],
        ]),
    )
    await call.answer()



@router.callback_query(F.data.startswith("bank:"))
async def cb_bank(call: CallbackQuery) -> None:
    from bot.config import IBAN
    order_id = call.data.split(":", 1)[1]
    await call.message.answer(
        f"Реквизиты для оплаты:\n"
        f"IBAN: {IBAN}\n"
        f"Назначение платежа: {order_id}\n\n"
        f"После оплаты отправьте скриншот менеджеру.",
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
        await message.answer("Использование: /paid ORDER-XXXX")
        return
    order_id = parts[1].upper()
    await _deliver_full_track(bot, order_id, message)


async def _deliver_full_track(bot: Bot, order_id: str, reply_to: Message | None = None) -> None:
    order = await db.get_order(order_id)
    if not order:
        if reply_to:
            await reply_to.answer("Заказ не найден.")
        return
    if order["status"] == "paid":
        return  # идемпотентность

    variant = order["chosen_variant"] or 1
    file_id = order[f"variant{variant}_file_id"]
    if not file_id:
        if reply_to:
            await reply_to.answer("Файл ещё не загружен.")
        return

    await db.update_order(order_id, status="paid")
    await bot.send_audio(order["user_id"], audio=file_id, caption="🎵 Ваша полная версия песни!")


deliver_full_track = _deliver_full_track
