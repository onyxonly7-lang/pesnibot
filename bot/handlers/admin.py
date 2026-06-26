import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import db
from bot.config import ADMIN_CHAT_ID
from bot.services.audio import make_preview

log = logging.getLogger(__name__)
router = Router()


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


# ── Incoming audio from admin (any state) ─────────────────────────────────

@router.message(F.audio | F.document)
async def handle_admin_audio(message: Message, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    audio = message.audio or message.document
    filename = getattr(audio, "file_name", None) or ""

    variant = _detect_variant(filename)
    if variant is None:
        await message.answer(
            f"⚠️ Не могу определить номер варианта по имени файла «{filename}».\n"
            "В названии должна быть цифра 1 или 2. Например: track_1.mp3"
        )
        return

    # Find the latest order that needs audio
    order = await _find_active_order()
    if not order:
        await message.answer("⚠️ Нет активных заказов в статусе preview_sent.")
        return

    order_id = order["id"]
    file_id = audio.file_id
    await db.update_order(order_id, **{f"variant{variant}_file_id": file_id})
    await message.answer(f"✅ Вариант {variant} сохранён для {order_id}.")

    # Reload order to check if both variants are now present
    order = await db.get_order(order_id)
    if order["variant1_file_id"] and order["variant2_file_id"]:
        await message.answer(f"✅ Оба варианта загружены. Отправляю превью клиенту...")
        await _send_previews_to_client(bot, order)
    else:
        missing = 2 if not order["variant2_file_id"] else 1
        await message.answer(f"⏳ Жду вариант {missing}...")


async def _find_active_order() -> dict | None:
    """Find the most recent order with status preview_sent."""
    import aiosqlite
    from bot.db import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            "SELECT * FROM orders WHERE status='preview_sent' ORDER BY created_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


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
        "🎧 Ваше музыкальное превью готово.\n\n"
        "Послушайте два варианта и выберите тот, который понравился больше.",
    )

    all_ok = True
    for variant_num in (1, 2):
        file_id = order[f"variant{variant_num}_file_id"]
        try:
            tg_file = await bot.get_file(file_id)
            downloaded = await bot.download_file(tg_file.file_path)
            preview_bytes = await make_preview(downloaded.read())
            audio_input = BufferedInputFile(preview_bytes, filename=f"preview_{variant_num}.mp3")
            await bot.send_audio(
                user_id,
                audio=audio_input,
                caption=f"🎵 Вариант {variant_num}",
            )
        except Exception:
            log.exception("Preview error: variant=%s order=%s", variant_num, order_id)
            await bot.send_message(user_id, f"(Вариант {variant_num} — ошибка генерации превью)")
            all_ok = False

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Выбираю вариант 1", callback_data="choose:1")],
        [InlineKeyboardButton(text="🎵 Выбираю вариант 2", callback_data="choose:2")],
    ])
    await bot.send_message(
        user_id,
        "Какой вариант вам больше понравился?\n",
        reply_markup=kb,
    )

    await db.update_order(order_id, status="chosen" if all_ok else "previewing")
