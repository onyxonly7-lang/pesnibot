import asyncio
import logging
import os
import signal

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot import db
from bot.handlers import user, admin
from bot.handlers.stats import router as stats_router, run_daily_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

PID_FILE = "/tmp/pesnibot.pid"


def _kill_previous() -> None:
    if not os.path.exists(PID_FILE):
        return
    try:
        with open(PID_FILE) as f:
            old_pid = int(f.read().strip())
        if old_pid != os.getpid():
            os.kill(old_pid, signal.SIGTERM)
            log.info("Killed previous instance pid=%d", old_pid)
            import time; time.sleep(2)
    except (ProcessLookupError, ValueError, OSError):
        pass
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


def _write_pid() -> None:
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


async def main() -> None:
    _kill_previous()
    _write_pid()

    await db.init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(stats_router)
    dp.include_router(admin.router)
    dp.include_router(user.router)

    await bot.delete_webhook(drop_pending_updates=False)

    # Запускаем фоновую задачу рассылки статистики
    stats_task = asyncio.create_task(run_daily_stats(bot))

    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=False,
        )
    finally:
        stats_task.cancel()
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
