"""Mureka AI song generation (https://api.mureka.ai).

Flow: POST /v1/song/generate -> task id; poll GET /v1/song/query/{id}
until a downloadable audio URL appears; download the MP3 bytes.
"""
import asyncio
import json
import logging

import aiohttp

from bot.config import MUREKA_API_KEY

log = logging.getLogger(__name__)

_BASE = "https://api.mureka.ai"
_GENERATE_URL = _BASE + "/v1/song/generate"
_QUERY_URL = _BASE + "/v1/song/query/{task_id}"

_DONE_STATES = {"succeeded", "success", "finished", "completed", "done"}
_FAILED_STATES = {"failed", "error", "cancelled", "canceled", "timeouted", "timeout"}

POLL_INTERVAL_SEC = 10
POLL_TIMEOUT_SEC = 300  # 5 minutes


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {MUREKA_API_KEY}",
        "Content-Type": "application/json",
    }


def _extract_audio_url(data: dict) -> str | None:
    """Find the first downloadable MP3 URL in a Mureka query response."""
    for key in ("choices", "songs", "data", "results"):
        arr = data.get(key)
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                for f in ("mp3_url", "url", "audio_url", "flac_url"):
                    if item.get(f):
                        return item[f]
    for f in ("mp3_url", "url", "audio_url"):
        if data.get(f):
            return data[f]
    return None


async def _start_task(session: aiohttp.ClientSession, lyrics: str, prompt: str) -> str:
    payload = {"lyrics": lyrics, "model": "auto", "prompt": prompt}
    async with session.post(_GENERATE_URL, json=payload, headers=_headers()) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"Mureka generate HTTP {resp.status}: {text}")
        data = json.loads(text)
    task_id = data.get("id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Mureka generate: no task id in response {data}")
    log.info("Mureka task started: %s", task_id)
    return str(task_id)


async def _poll_task(session: aiohttp.ClientSession, task_id: str) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_TIMEOUT_SEC
    while True:
        async with session.get(_QUERY_URL.format(task_id=task_id), headers=_headers()) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Mureka query HTTP {resp.status}: {text}")
            data = json.loads(text)
        status = str(data.get("status", "")).lower()
        url = _extract_audio_url(data)
        if url:
            log.info("Mureka task %s ready", task_id)
            return url
        if status in _FAILED_STATES:
            raise RuntimeError(f"Mureka task {task_id} failed: {data}")
        if status in _DONE_STATES:
            raise RuntimeError(f"Mureka task {task_id} done but no audio url: {data}")
        if loop.time() >= deadline:
            raise TimeoutError(f"Mureka task {task_id} timed out after {POLL_TIMEOUT_SEC}s")
        await asyncio.sleep(POLL_INTERVAL_SEC)


async def generate_track(lyrics: str, prompt: str) -> bytes:
    """Run one Mureka generation end-to-end and return the MP3 bytes."""
    async with aiohttp.ClientSession() as session:
        task_id = await _start_task(session, lyrics, prompt)
        audio_url = await _poll_task(session, task_id)
        async with session.get(audio_url) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Mureka download HTTP {resp.status} for {audio_url}")
            return await resp.read()


# ── mureka_prompt builder (deterministic, per spec) ───────────────────────

_STYLE_BY_RECIPIENT = {
    "Мамі": "Warm emotional pop ballad with soft piano, gentle strings, heartfelt vocal, medium-slow tempo",
    "Чоловіку": "Romantic pop-rock ballad with acoustic guitar, piano, soft drums, emotional vocal",
    "Дружині": "Romantic modern pop ballad with piano, cinematic strings, soft drums, intimate vocal",
    "Хлопцю": "Modern romantic pop with soft piano, light beat, emotional vocal, warm mood",
    "Дівчині": "Modern romantic pop with soft piano, light beat, emotional vocal, warm intimate mood",
    "Подрузі": "Light modern pop with warm acoustic guitar, soft beat, friendly emotional vocal",
    "Дитині": "Gentle bright pop with piano, soft acoustic instruments, warm vocal, kind mood",
    "Інше": "Choose most suitable style based on story and occasion, prefer modern melodic pop",
}

_MOOD_ADDON = {
    "Весела і легка": "upbeat tempo, cheerful mood, light and positive energy",
    "Душевна і зворушлива": "slow tempo, emotional depth, touching and heartfelt mood",
    "Сучасна і нестандартна": "modern production, contemporary sound, fresh and unexpected arrangement",
}

_VOCAL_SUFFIX = {
    "Чоловічий": "male vocal",
    "Жіночий": "female vocal",
    "Дует": "male and female duet vocals",
}


def build_mureka_prompt(recipient: str, mood: str, voice: str) -> str:
    """Compose the Mureka style prompt from recipient + mood + voice."""
    base = _STYLE_BY_RECIPIENT.get(recipient, _STYLE_BY_RECIPIENT["Інше"])
    parts = [base]
    addon = _MOOD_ADDON.get(mood)
    if addon:
        parts.append(addon)
    vocal = _VOCAL_SUFFIX.get(voice)
    if vocal:
        parts.append(vocal)
    return ", ".join(parts)
