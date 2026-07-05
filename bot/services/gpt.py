import logging

from openai import AsyncOpenAI
from bot.config import OPENAI_API_KEY

log = logging.getLogger(__name__)
_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_PROMPT_TEMPLATE = """\
Напиши текст пісні на тій самій мові, якою написана історія користувача.

Структура обов'язкова (дотримуйся рівно цього порядку і кількості рядків):
Куплет 1 (6 рядків) → Передприспів (2 рядки) → Приспів (6 рядків) → \
Куплет 2 (6 рядків) → Перехід (4 рядки) → Приспів повтор (6 рядків) → \
Фінал (4 рядки).

Вимоги до тексту:
- Мінімальна довжина тексту — не менше 1200 символів.
- Кожен рядок — закінчена думка. Римування AABB або ABAB.
- Повтор приспіву має трохи відрізнятися від першого приспіву: збережи ту саму \
головну думку і настрій, але зміни частину рядків (інші слова чи образи), \
щоб він звучав схоже, але не ідентично.
- Фінал завжди дописуй до кінця — текст не повинен обриватися на півслові чи \
незакінченому рядку.
- Якщо історія коротка — розвивай образи, додавай метафори, розширюй емоції. \
Ніколи не скорочуй структуру через малу кількість інформації від користувача.

У першому куплеті обов'язково згадай ім'я людини (якщо воно є) та яскраву \
деталь з історії, щоб клієнт одразу впізнав себе і відчув, що пісня саме про нього.

Історія користувача (головне джерело тексту): {history}

Фоновий контекст для настрою (не обов'язково згадувати явно в тексті):
- Кому пісня: {recipient}
- Привід: {occasion}
- Настрій: {mood}
- Голос: {voice}

Формат відповіді — поверни СТРОГО валідний JSON без markdown, без пояснень, \
без ```:
{{"lyrics": "<готовий текст пісні за структурою вище>", "mureka_prompt": \
"<короткий музичний опис англійською, 1-2 речення>"}}\
"""


def _is_section_tag(line: str) -> bool:
    s = line.strip()
    return s.startswith("[") and s.endswith("]")


def _trim_to_limit(lyrics: str, max_lines: int = 60) -> str:
    result_lines = []
    text_line_count = 0
    for line in lyrics.splitlines():
        if not _is_section_tag(line):
            if text_line_count >= max_lines:
                continue
            text_line_count += 1
        result_lines.append(line)
    return "\n".join(result_lines)


async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe a Telegram voice message via OpenAI Whisper."""
    response = await _client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes),
    )
    return (response.text or "").strip()


def _parse_lyrics(raw: str) -> str:
    """Extract the lyrics from GPT's JSON reply (tolerant of stray markdown)."""
    import json
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
        lyrics = data.get("lyrics")
        if lyrics:
            return str(lyrics).strip()
    except Exception:
        log.warning("GPT reply is not valid JSON, using raw text as lyrics")
    return raw.strip()


async def generate_lyrics(
    recipient: str,
    occasion: str,
    mood: str,
    voice: str,
    story: str,
) -> str:
    prompt = _PROMPT_TEMPLATE.format(
        history=story,
        recipient=recipient,
        occasion=occasion,
        mood=mood,
        voice=voice,
    )
    response = await _client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        response_format={"type": "json_object"},
    )
    lyrics = _parse_lyrics(response.choices[0].message.content or "")
    return _trim_to_limit(lyrics)
