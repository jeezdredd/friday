# Friday

Личный голосовой ассистент для дома в духе Джарвиса и Пятницы.
Мозг на Claude с tool calling, умный дом через Home Assistant, wake word "Пятница", голос через ElevenLabs или локально.

Главная идея: ассистент расширяется обычными Python-функциями. Написал функцию с декоратором `@tool`, перезапустил, Пятница умеет новое.

## Архитектура

```
микрофон -> Vosk: услышал "пятница"? -> запись до паузы -> Whisper -> это обращение? -> Agent (Claude + tools) -> TTS -> HomePod
                                                                                          |
                                                          tools/home.py   -> Home Assistant REST -> Matter лампа
                                                          tools/system.py -> время, погода, местоположение
                                                          tools/memory.py -> ~/.friday/memory.json
                                                          tools/<твой_модуль>.py
```

```
friday/
  agent.py              цикл диалога и вызова инструментов
  prompts.py            системный промпт (характер и правила Пятницы)
  config.py             настройки из .env
  location.py           автоопределение дома по IP с кешем
  voice_setup.py        создание голоса Пятницы в ElevenLabs
  tools/
    registry.py         декоратор @tool, автогенерация JSON-схемы
    home.py             лампы, датчики
    system.py           время, погода, местоположение
    memory.py           долговременная память
  integrations/
    homeassistant.py    клиент REST API Home Assistant
  voice/
    audio.py            общий поток с микрофона
    wakeword.py         детекторы wake word (Vosk, Porcupine)
    listener.py         ожидание обращения и запись фразы до паузы
    recorder.py         push-to-talk запись
    stt.py              распознавание речи
    tts.py              синтез речи (ElevenLabs, Silero, say)
```

## Быстрый старт

```bash
git clone https://github.com/jeezdredd/friday.git
cd friday
brew install portaudio
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[voice,dev]"
cp .env.example .env   # заполни ANTHROPIC_API_KEY и ELEVENLABS_API_KEY

python -m friday.voice_setup   # один раз: создать голос Пятницы
python -m friday --tools       # какие инструменты доступны
python -m friday               # текстовый чат
python -m friday --speak       # текстовый чат с озвучкой
python -m friday --voice       # голосом: "Пятница, включи свет"
python -m friday --ptt         # голосом без wake word: Enter говорить, Enter стоп
```

Чтобы ответы звучали из HomePod, выбери его устройством вывода звука на маке. При первом запуске `--voice` скачается модель Vosk (~45 МБ) и Whisper.

## Местоположение

Город и координаты дома определяются по IP при первом запуске и кешируются в `~/.friday/location.json`. Оттуда же берётся таймзона. Пятница знает, где дом, и по умолчанию отвечает про погоду и время там.

Если IP показывает не тот город (VPN), задай `HOME_LAT`, `HOME_LON`, `HOME_CITY` в `.env`. Определить заново: `rm ~/.friday/location.json`.

## Wake word

Работает в два этапа, чтобы не срабатывать на всё подряд:

1. Vosk (офлайн, без регистрации) постоянно слушает и ждёт точное слово "пятница".
2. После срабатывания фраза записывается до паузы, Whisper её расшифровывает, и команда выполняется, только если "Пятница" стоит в начале как обращение. "В пятницу пойдём в кино" будет проигнорировано.

Можно сказать на одном дыхании ("Пятница, какая погода?") или с паузой: на "Пятница" она ответит "Да?" и будет ждать команду. После ответа ещё 4 секунды можно продолжать разговор без повторного обращения (`FOLLOWUP_SECONDS`).

Для максимальной точности есть Porcupine: создай слово "Пятница" (язык Russian) в [Picovoice Console](https://console.picovoice.ai/), скачай `.ppn` и `porcupine_params_ru.pv`, пропиши пути и ключ в `.env`, `WAKE_ENGINE=porcupine`, `pip install -e ".[porcupine]"`.

## Голос

| `TTS_ENGINE` | Что это |
|---|---|
| `elevenlabs` | Лучшее качество. Голос создаётся командой `python -m friday.voice_setup` |
| `silero` | Локально и бесплатно, русские голоса xenia, baya, kseniya. `pip install -e ".[silero]"` |
| `say` | Системный голос macOS, работает сразу |

`voice_setup` генерирует несколько вариантов голоса по описанию характера (Voice Design), проигрывает их, ты выбираешь лучший, голос сохраняется в твоём аккаунте ElevenLabs, а его ID записывается в `.env`. Своё описание: `python -m friday.voice_setup --description "..."`. Голос именно актрисы из фильма не клонируется: правила ElevenLabs запрещают клонировать человека без его согласия.

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

- [x] wake word "Пятница"
- [x] голос через ElevenLabs и Silero
- [x] автоопределение местоположения
- [ ] потоковый TTS, чтобы начинать говорить до конца ответа
- [ ] проактивность: утренний брифинг по расписанию
- [ ] веб-панель со статусом и историей
