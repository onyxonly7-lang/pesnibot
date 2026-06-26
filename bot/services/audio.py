import asyncio
import os
import shutil
import subprocess
import tempfile

from bot.config import PREVIEW_START_MS, PREVIEW_END_MS

_START_SEC = PREVIEW_START_MS / 1000
_DURATION_SEC = (PREVIEW_END_MS - PREVIEW_START_MS) / 1000


def _find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # static-ffmpeg fallback (used in BotObrezchik)
    try:
        import static_ffmpeg
        path, _ = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        return path
    except Exception:
        pass
    raise RuntimeError("ffmpeg not found. Install it: brew install ffmpeg")


_FFMPEG = _find_ffmpeg()


async def make_preview(file_bytes: bytes, suffix: str = ".mp3") -> bytes:
    """Cut [START_SEC : START_SEC+DURATION_SEC] via ffmpeg, return preview bytes."""

    def _cut(data: bytes) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
            tmp_in.write(data)
            tmp_in_path = tmp_in.name
        tmp_out_path = tmp_in_path + "_preview.mp3"
        try:
            result = subprocess.run(
                [
                    _FFMPEG,
                    "-ss", str(_START_SEC),
                    "-t", str(_DURATION_SEC),
                    "-i", tmp_in_path,
                    "-acodec", "libmp3lame",
                    "-ab", "192k",
                    "-y",
                    tmp_out_path,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg error: {result.stderr[-500:]}")
            with open(tmp_out_path, "rb") as f:
                return f.read()
        finally:
            os.unlink(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.unlink(tmp_out_path)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _cut, file_bytes)
