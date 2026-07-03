from openai import AsyncOpenAI
from bot.config import OPENAI_API_KEY

_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_PROMPT_TEMPLATE = """\
Напиши текст пісні на тій самій мові, якою написана історія користувача. \
Структура обов'язкова: Куплет 1 (6 рядків) → Передприспів (2 рядки) → \
Приспів (6 рядків) → Куплет 2 (6 рядків) → Перехід (4 рядки) → \
Приспів повтор (6 рядків) → Фінал (3 рядки). Мінімум 33 рядки. \
Повтор приспіву має трохи відрізнятися від першого приспіву — \
збережи ту саму головну думку і настрій, але зміни частину рядків \
(інші слова чи образи), щоб він звучав схоже, але не ідентично. \
Кожен рядок — закінчена думка. Римування AABB або ABAB. \
Використай всі деталі з історії користувача: {history}

У першому куплеті обов'язково згадай: ім'я людини якщо є, одну яскраву \
рису характеру або захоплення, один особистий момент або спогад з історії. \
Це найважливіше — людина повинна одразу відчути що пісня саме про неї.

Додатковий контекст (підказки, не головне джерело — головне це історія вище):
- Кому адресована пісня: {recipient} — використай як орієнтир, якщо з історії адресат зрозумілий погано.
- Привід: {occasion} — врахуй як контекст і настрій пісні, як доповнення до історії.
- Тип вокалу: {voice} — від якої особи виконується пісня.\
"""


def _is_section_tag(line: str) -> bool:
    s = line.strip()
    return s.startswith("[") and s.endswith("]")


def _trim_to_limit(lyrics: str, max_lines: int = 38) -> str:
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


async def generate_lyrics(
    recipient: str,
    occasion: str,
    voice: str,
    story: str,
) -> str:
    prompt = _PROMPT_TEMPLATE.format(
        history=story,
        recipient=recipient,
        occasion=occasion,
        voice=voice,
    )
    response = await _client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
    )
    return _trim_to_limit(response.choices[0].message.content.strip())
