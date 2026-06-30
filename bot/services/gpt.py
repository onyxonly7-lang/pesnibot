from openai import AsyncOpenAI
from bot.config import OPENAI_API_KEY

_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_PROMPT_TEMPLATE = """\
Створи персональний текст пісні на основі даних клієнта.

Дані клієнта:
Кому пісня: {recipient}
Привід: {occasion}
Тип вокалу: {vocal_type}
Історія клієнта: {story}

Правила:
- Враховуй усі обрані користувачем параметри.
- Якщо в історії мало деталей, всеодно використовуй обрані поля як основу змісту пісні.
- Якщо обрано "Чоловіку", "Дружині", "Хлопцю", "Дівчині" — пісня має звучати як звернення до коханої людини.
- Якщо обрано "Мамі" — пісня має бути теплою, вдячною і сімейною.
- Якщо обрано "Дитині" — пісня має бути ніжною, підтримуючою і світлою.
- Якщо обрано "Подрузі" — пісня має звучати дружньо, тепло і живо.
- Привід обов'язково врахувати в тексті: день народження, річниця, подяка, вибачення або інший обраний варіант.
- Ім'я людини, якщо воно є в історії, використовуй природно, без надмірного повторення.
- Вже в першому куплеті мають прозвучати головна ідея пісні та персональні деталі.
- Не вигадуй фактів, яких немає в історії.
- Пиши мовою історії клієнта.
- Текст має бути музичним, простим для співу і підходящим для генерації в Suno.
- Не роби текст занадто загальним. Навіть якщо даних мало, використовуй звернення, привід та емоцію з анкети.
- Якщо історія коротка (наприклад: "Я його люблю, Паша"), але раніше обрано отримувача та привід — текст всеодно має чітко показувати, кому присвячена пісня і з якого приводу вона створюється.

Формат відповіді:
Поверни ЛИШЕ готовий текст пісні з мітками структури [Verse], [Chorus], [Bridge] там, де це доречно для пісенної форми — цей текст напряму вставляється в Suno для генерації музики. Не додавай жодних вступних фраз, пояснень, привітань, лапок чи коментарів — тільки сам текст пісні з мітками, готовий для копіювання.\
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


async def generate_lyrics(
    recipient: str,
    occasion: str,
    voice: str,
    story: str,
) -> str:
    prompt = _PROMPT_TEMPLATE.format(
        recipient=recipient,
        occasion=occasion,
        vocal_type=voice,
        story=story,
    )
    response = await _client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
    )
    return _trim_to_limit(response.choices[0].message.content.strip())
