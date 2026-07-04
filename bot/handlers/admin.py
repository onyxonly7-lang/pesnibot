import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import db
from bot.config import ADMIN_CHAT_ID
from bot.services.audio import make_preview
from bot.states import UploadExamples, UploadOrder

log = logging.getLogger(__name__)
router = Router()

_EXAMPLE_KEYS = [
    "EXAMPLE_SONG_WIFE",
    "EXAMPLE_SONG_HUSBAND",
    "EXAMPLE_SONG_FRIEND",
    "EXAMPLE_SONG_MOM",
]
_EXAMPLE_LABELS = [
    "дружини",
    "чоловіка",
    "подруги",
    "мами",
]


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID


def _detect_variant(filename: str) -> int | None:
    """Return 1 or 2 based on digits found in the filename, or None if unclear."""
    digits = re.findall(r"\d+", filename)
    for d in digits:
        if "1" in d and "2" not in d:
            return 1
        if "2" in d and "1" not in d:
            return 2
    # fallback: last digit sequence
    if digits:
        last = digits[-1]
        if last.endswith("1"):
            return 1
        if last.endswith("2"):
            return 2
    return None


# ── Upload files for a specific order (via inline button) ─────────────────

@router.callback_query(F.data.startswith("upload:"))
async def cb_upload_files(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    order_id = call.data.split(":", 1)[1]
    order = await db.get_order(order_id)
    if not order:
        await call.answer("Замовлення не знайдено.", show_alert=True)
        return
    await state.set_state(UploadOrder.waiting)
    await state.update_data(upload_order_id=order_id)
    await call.message.answer(f"📎 Надішліть 2 MP3 файли для {order_id}")
    await call.answer()


async def _bind_audio_to_order(order_id: str, audio, message: Message, bot: Bot, state: FSMContext) -> None:
    order = await db.get_order(order_id)
    if not order:
        await message.answer(f"⚠️ Замовлення {order_id} не знайдено.")
        await state.clear()
        return

    filename = getattr(audio, "file_name", None) or ""
    variant = _detect_variant(filename)
    if variant is None:
        # fallback: fill the next empty slot in upload order
        if not order["variant1_file_id"]:
            variant = 1
        elif not order["variant2_file_id"]:
            variant = 2
        else:
            variant = 1

    await db.update_order(order_id, **{f"variant{variant}_file_id": audio.file_id})
    await message.answer(f"✅ Варіант {variant} збережено для {order_id}.")

    order = await db.get_order(order_id)
    if order["variant1_file_id"] and order["variant2_file_id"]:
        await message.answer("✅ Обидва варіанти завантажено. Надсилаю превью клієнту...")
        await state.clear()
        await _send_previews_to_client(bot, order)
    else:
        missing = 2 if not order["variant2_file_id"] else 1
        await message.answer(f"⏳ Чекаю варіант {missing} для {order_id}...")


@router.message(UploadOrder.waiting, F.audio | F.document)
async def handle_order_audio(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    order_id = data.get("upload_order_id")
    if not order_id:
        await state.clear()
        await message.answer("⚠️ Не вибрано замовлення. Натисніть кнопку «📎 Завантажити файли» під потрібним замовленням.")
        return
    audio = message.audio or message.document
    await _bind_audio_to_order(order_id, audio, message, bot, state)


# ── Fallback: audio sent without picking an order ─────────────────────────

@router.message(~StateFilter(UploadExamples.collecting, UploadOrder.waiting), F.audio | F.document)
async def handle_admin_audio(message: Message, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "⚠️ Спочатку натисніть кнопку «📎 Завантажити файли для ORDER-XXXX» "
        "під потрібним замовленням, а потім надішліть файли."
    )


async def _claim_order(order_id: str) -> bool:
    """Atomically transition status from preview_sent → previewing. Returns True if claimed."""
    import aiosqlite
    from bot.db import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "UPDATE orders SET status='previewing' WHERE id=? AND status='preview_sent'",
            (order_id,),
        )
        await db_conn.commit()
        return db_conn.total_changes > 0


async def _send_previews_to_client(bot: Bot, order: dict) -> None:
    order_id = order["id"]

    if not await _claim_order(order_id):
        log.info("Order %s already claimed for preview, skipping duplicate send", order_id)
        return

    user_id = order["user_id"]

    await bot.send_message(
        user_id,
        "🎧 Ваше музичне превью готове.\n\n"
        "Послухайте два варіанти і оберіть той, який сподобався більше.",
    )

    all_ok = True
    for variant_num in (1, 2):
        file_id = order[f"variant{variant_num}_file_id"]
        try:
            tg_file = await bot.get_file(file_id)
            downloaded = await bot.download_file(tg_file.file_path)
            preview_bytes = await make_preview(downloaded.read())
            audio_input = BufferedInputFile(preview_bytes, filename=f"Варіант {variant_num}.mp3")
            await bot.send_audio(
                user_id,
                audio=audio_input,
                title=f"Варіант {variant_num}",
            )
        except Exception:
            log.exception("Preview error: variant=%s order=%s", variant_num, order_id)
            await bot.send_message(user_id, f"(Варіант {variant_num} — помилка генерації превью)")
            all_ok = False

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Обираю варіант 1", callback_data="choose:1")],
        [InlineKeyboardButton(text="🎵 Обираю варіант 2", callback_data="choose:2")],
    ])
    await bot.send_message(
        user_id,
        "Який варіант вам більше сподобався?\n",
        reply_markup=kb,
    )

    await db.update_order(order_id, status="chosen" if all_ok else "previewing")


# ── /upload_examples ──────────────────────────────────────────────────────

@router.message(Command("clear_examples"))
async def cmd_clear_examples(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    for key in _EXAMPLE_KEYS:
        await db.set_setting(key, "")
    await message.answer("🗑 Всі приклади пісень видалено.")


@router.message(Command("upload_examples"))
async def cmd_upload_examples(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(UploadExamples.collecting)
    await state.update_data(example_index=0, example_file_ids=[])
    await message.answer(
        "📤 Режим завантаження прикладів.\n\n"
        "Надішліть 4 аудіофайли по черзі:\n"
        "1️⃣ Пісня для дружини\n"
        "2️⃣ Пісня для чоловіка\n"
        "3️⃣ Пісня для подруги\n"
        "4️⃣ Пісня для мами\n\n"
        "Надішліть перший файл ⬇️"
    )


@router.message(UploadExamples.collecting, F.audio | F.document)
async def handle_example_audio(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    data = await state.get_data()
    index: int = data.get("example_index", 0)
    file_ids: list = data.get("example_file_ids", [])

    audio = message.audio or message.document
    current_label = _EXAMPLE_LABELS[index]
    file_ids.append(audio.file_id)
    index += 1
    await state.update_data(example_index=index, example_file_ids=file_ids)

    if index < len(_EXAMPLE_KEYS):
        next_label = _EXAMPLE_LABELS[index]
        await message.answer(
            f"✅ Пісня для {current_label} збережена.\n\n"
            f"Надішліть наступний файл — пісня для {next_label}:"
        )
    else:
        for key, file_id in zip(_EXAMPLE_KEYS, file_ids):
            await db.set_setting(key, file_id)
        await state.clear()
        await message.answer(
            f"✅ Пісня для {current_label} збережена.\n\n"
            "✅ Всі приклади завантажено успішно!"
        )
