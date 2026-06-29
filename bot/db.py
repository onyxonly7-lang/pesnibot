import os
import aiosqlite
import uuid
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "orders.db")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                recipient TEXT,
                occasion TEXT,
                voice TEXT,
                story TEXT,
                lyrics TEXT,
                edit_used INTEGER DEFAULT 0,
                variant1_file_id TEXT,
                variant2_file_id TEXT,
                chosen_variant INTEGER,
                status TEXT DEFAULT 'new',
                created_at TEXT
            )
        """)
        await db.commit()


def _new_order_id() -> str:
    suffix = str(uuid.uuid4().int)[:4].zfill(4)
    return f"ORDER-{suffix}"


async def create_order(user_id: int, username: str) -> str:
    order_id = _new_order_id()
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Ensure uniqueness
        while True:
            async with db.execute("SELECT id FROM orders WHERE id=?", (order_id,)) as cur:
                if not await cur.fetchone():
                    break
            order_id = _new_order_id()
        await db.execute(
            "INSERT INTO orders (id, user_id, username, status, created_at) VALUES (?,?,?,'new',?)",
            (order_id, user_id, username, now),
        )
        await db.commit()
    return order_id


async def update_order(order_id: str, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [order_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE orders SET {sets} WHERE id=?", vals)
        await db.commit()


async def get_order(order_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE id=?", (order_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def count_orders_last_24h(user_id: int) -> int:
    since = (datetime.now(timezone.utc).timestamp() - 86400)
    # created_at is ISO-8601 UTC string — lexicographic compare works
    since_str = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at >= ?",
            (user_id, since_str),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_latest_order_for_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()
