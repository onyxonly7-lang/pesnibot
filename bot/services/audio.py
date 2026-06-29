import asyncio
import logging
import os
import shutil
import subprocess
import tempfile

from bot.config import PREVIEW_START_MS, PREVIEW_END_MS

log = logging.getLogger(__name__)

_START_SEC = PREVIEW_START_MS / 1000
_DURATION_SEC = (PREVIEW_END_MS - PREVIEW_START_MS) / 1000

_FFMPEG_PATH: str | None = None


def _find_ffmpeg() -> str | None:
    # 1. system ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        log.info("ffmpeg found at %s", ffmpeg)
        return ffmpeg
    # 2. static-ffmpeg package
    try:
        import static_ffmpeg
        ffmpeg_path, _ = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        log.info("static-ffmpeg found at %s", ffmpeg_path)
        return ffmpeg_path
    except Exception as e:
        log.warning("static-ffmpeg not available: %s", e)
    return None


def _get_ffmpeg() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH is None:
        _FFMPEG_PATH = _find_ffmpeg()
    if not _FFMPEG_PATH:
        raise RuntimeError("ffmpeg not found on this system")
    return _FFMPEG_PATH


async def make_preview(file_bytes: bytes, suffix: str = ".mp3") -> bytes:
    """Cut [START_SEC : START_SEC+DURATION_SEC] via ffmpeg subprocess."""

    def _cut(data: bytes) -> bytes:
        ffmpeg = _get_ffmpeg()
        log.info(
            "Cutting preview: ffmpeg=%s start=%.1fs duration=%.1fs input_size=%d bytes",
            ffmpeg, _START_SEC, _DURATION_SEC, len(data),
        )

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
            tmp_in.write(data)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path + "_preview.mp3"
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss", str(_START_SEC),
                    "-i", tmp_in_path,
                    "-t", str(_DURATION_SEC),
                    "-acodec", "libmp3lame",
                    "-ab", "192k",
                    tmp_out_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                log.error("ffmpeg stderr: %s", result.stderr[-1000:])
                raise RuntimeError(f"ffmpeg exited with code {result.returncode}")

            size = os.path.getsize(tmp_out_path)
            log.info("Preview ready: %d bytes", size)

            if size == 0:
                raise RuntimeError("ffmpeg produced an empty file")

            with open(tmp_out_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp_in_path)
            except OSError:
                pass
            if os.path.exists(tmp_out_path):
                try:
                    os.unlink(tmp_out_path)
                except OSError:
                    pass

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _cut, file_bytes)
