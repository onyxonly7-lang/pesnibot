from datetime import datetime, timezone, timedelta
import aiosqlite
from bot.db import DB_PATH
from bot.config import PRICE_UAH


async def _fetch(query: str, params: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _fetchone(query: str, params: tuple = ()) -> dict | None:
    rows = await _fetch(query, params)
    return rows[0] if rows else None


def _day_range(date: datetime) -> tuple[str, str]:
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _month_range(date: datetime) -> tuple[str, str]:
    start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # next month
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


async def daily_stats(date: datetime | None = None) -> dict:
    date = date or datetime.now(timezone.utc)
    since, until = _day_range(date)

    rows = await _fetch(
        "SELECT status FROM orders WHERE created_at >= ? AND created_at < ?",
        (since, until),
    )
    statuses = [r["status"] for r in rows]

    paid_count = statuses.count("paid")
    new_count = len(statuses)
    await_preview = statuses.count("preview_sent")  # preview requested, admin hasn't uploaded yet
    await_payment = sum(1 for s in statuses if s in ("chosen",))
    incomplete = sum(1 for s in statuses if s in ("new",))

    day_revenue = paid_count * PRICE_UAH

    # Month revenue
    month_since, month_until = _month_range(date)
    month_row = await _fetchone(
        "SELECT COUNT(*) as cnt FROM orders WHERE status='paid' AND created_at >= ? AND created_at < ?",
        (month_since, month_until),
    )
    month_revenue = (month_row["cnt"] if month_row else 0) * PRICE_UAH

    return {
        "date": date,
        "new": new_count,
        "paid": paid_count,
        "await_preview": await_preview,
        "await_payment": await_payment,
        "incomplete": incomplete,
        "day_revenue": day_revenue,
        "month_revenue": month_revenue,
    }


async def monthly_stats(date: datetime | None = None) -> dict:
    date = date or datetime.now(timezone.utc)
    since, until = _month_range(date)

    rows = await _fetch(
        "SELECT status, occasion, voice FROM orders WHERE created_at >= ? AND created_at < ?",
        (since, until),
    )

    total = len(rows)
    paid = sum(1 for r in rows if r["status"] == "paid")
    revenue = paid * PRICE_UAH

    occasions = [r["occasion"] for r in rows if r.get("occasion")]
    voices = [r["voice"] for r in rows if r.get("voice")]

    top_occasion = _top(occasions)
    top_voice = _top(voices)

    return {
        "date": date,
        "total": total,
        "paid": paid,
        "revenue": revenue,
        "top_occasion": top_occasion,
        "top_voice": top_voice,
    }


def _top(items: list[str]) -> str:
    if not items:
        return "—"
    counts: dict[str, int] = {}
    for i in items:
        counts[i] = counts.get(i, 0) + 1
    best = max(counts, key=lambda k: counts[k])
    return f"{best} ({counts[best]})"


def format_daily(s: dict) -> str:
    date_str = s["date"].strftime("%d.%m.%Y")
    return (
        f"📊 Статистика за {date_str}\n\n"
        f"📝 Новых заказов: {s['new']}\n"
        f"✅ Оплачено: {s['paid']} ({s['paid'] * PRICE_UAH} грн)\n"
        f"⏳ Ожидают загрузки превью: {s['await_preview']}\n"
        f"🎧 Превью отправлено, ожидают оплаты: {s['await_payment']}\n"
        f"❌ Незавершённых заказов: {s['incomplete']}\n\n"
        f"💰 Выручка за день: {s['day_revenue']} грн\n"
        f"💰 Выручка за месяц: {s['month_revenue']} грн"
    )


def format_monthly(s: dict) -> str:
    date_str = s["date"].strftime("%m.%Y")
    return (
        f"📊 Статистика за {date_str}\n\n"
        f"📝 Всего заказов: {s['total']}\n"
        f"✅ Оплачено: {s['paid']}\n"
        f"💰 Общая выручка: {s['revenue']} грн\n\n"
        f"🏆 Популярный повод: {s['top_occasion']}\n"
        f"🎤 Популярный голос: {s['top_voice']}"
    )
