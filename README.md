# Friday

Личный голосовой ассистент для дома в духе Джарвиса и Пятницы.
Мозг на Claude с tool calling, умный дом через Home Assistant, голос локально (faster-whisper + `say` на macOS).

Главная идея: ассистент расширяется обычными Python-функциями. Написал функцию с декоратором `@tool`, перезапустил, Пятница умеет новое.

## Архитектура

```
микрофон -> recorder -> faster-whisper (STT) -> Agent (Claude + tools) -> TTS -> колонка / HomePod
                                                    |
                                                    +-> tools/home.py   -> Home Assistant REST -> Matter лампа
                                                    +-> tools/system.py -> время, погода
                                                    +-> tools/memory.py -> ~/.friday/memory.json
                                                    +-> tools/<твой_модуль>.py
```

```
friday/
  agent.py              цикл диалога и вызова инструментов
  config.py             настройки из .env
  tools/
    registry.py         декоратор @tool, автогенерация JSON-схемы
    home.py             лампы, датчики
    system.py           время, погода
    memory.py           долговременная память
  integrations/
    homeassistant.py    клиент REST API Home Assistant
  voice/
    recorder.py         push-to-talk запись
    stt.py              распознавание речи
    tts.py              синтез речи
```

## Быстрый старт

```bash
git clone https://github.com/jeezdredd/friday.git
cd friday
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[voice,dev]"
cp .env.example .env   # заполни ANTHROPIC_API_KEY и остальное

python -m friday --tools   # какие инструменты доступны
python -m friday           # текстовый чат
python -m friday --speak   # текстовый чат с озвучкой
python -m friday --voice   # голосом: Enter говорить, Enter стоп
```

Для голоса на macOS нужен PortAudio: `brew install portaudio`.
Чтобы ответы звучали из HomePod, выбери его устройством вывода звука на маке.

## Home Assistant и Matter-лампа

HomeKit API закрыт для Python, поэтому устройства идут через Home Assistant. Matter поддерживает multi-admin: лампа остаётся в Apple Home и одновременно добавляется в HA.

1. Подними Home Assistant. На macOS проще всего HA OS в виртуалке [UTM](https://www.home-assistant.io/installation/macos) или на отдельной Raspberry Pi. Docker Desktop на маке плохо дружит с Matter из-за сетевого режима, `docker-compose.yml` в репо рассчитан на Linux-хост.
2. В HA: Settings -> Devices & services -> Add integration -> Matter.
3. В Apple Home: лампа -> настройки -> Turn On Pairing Mode, скопируй код.
4. В HA: Add device -> Matter -> вставь код.
5. Профиль пользователя в HA -> Security -> создай Long-lived access token, положи в `.env` как `HA_TOKEN`.
6. Узнай entity_id лампы (`python -m friday`, спроси "какие у меня лампы") и пропиши в `FRIDAY_DEFAULT_LIGHT`.

## Как добавить свою возможность

Создай файл в `friday/tools/`, например `friday/tools/music.py`:

```python
from typing import Annotated, Literal

from friday.tools import tool


@tool
def play_music(
    query: Annotated[str, "Что включить: исполнитель, трек или плейлист"],
    source: Literal["apple_music", "spotify"] = "apple_music",
) -> str:
    """Включить музыку."""
    ...
    return f"Играет {query}"
```

Всё. Модуль подхватится автоматически, схема для LLM соберётся из type hints:

- docstring обязателен, это описание инструмента для модели
- `Annotated[T, "описание"]` описывает параметр
- `Literal[...]` превращается в enum
- параметры без значения по умолчанию становятся обязательными
- исключения внутри инструмента не роняют ассистента, модель получит текст ошибки
- модули с префиксом `_` игнорируются, удобно для черновиков

## Тесты

```bash
pytest
ruff check .
```

## Безопасность

- Все ключи и токены только в `.env`, он в `.gitignore`.
- Память ассистента лежит в `~/.friday`, вне репозитория.
- Инструменты, которые что-то меняют (замки, покупки, сообщения), лучше делать с подтверждением голосом.

## Roadmap

- [ ] wake word ("Пятница") через openWakeWord
- [ ] потоковый TTS, чтобы начинать говорить до конца ответа
- [ ] проактивность: утренний брифинг по расписанию
- [ ] голос получше: Piper или ElevenLabs
- [ ] веб-панель со статусом и историей
