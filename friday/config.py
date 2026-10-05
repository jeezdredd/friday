import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _float(name: str, default: str) -> float:
    return float(_env(name, default))


@dataclass
class Settings:
    # LLM
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    model: str = field(default_factory=lambda: _env("FRIDAY_MODEL", "claude-sonnet-5-5"))
    max_tokens: int = field(default_factory=lambda: int(_env("FRIDAY_MAX_TOKENS", "1024")))
    max_history: int = field(default_factory=lambda: int(_env("FRIDAY_MAX_HISTORY", "30")))

    # Пользователь
    user_name: str = field(default_factory=lambda: _env("FRIDAY_USER_NAME"))
    # Как Пятница обращается к пользователю: босс, сэр, по имени
    address: str = field(default_factory=lambda: _env("FRIDAY_ADDRESS", "сэр"))
    # Приветствие голосом при запуске голосового режима
    startup_greeting: bool = field(default_factory=lambda: _env("STARTUP_GREETING", "1") == "1")
    # Пусто = берётся из местоположения дома
    timezone: str = field(default_factory=lambda: _env("FRIDAY_TIMEZONE"))
    data_dir: Path = field(default_factory=lambda: Path(_env("FRIDAY_DATA_DIR", "~/.friday")).expanduser())

    # Местоположение дома. Пусто = определяется по IP один раз и кешируется
    home_lat: str = field(default_factory=lambda: _env("HOME_LAT"))
    home_lon: str = field(default_factory=lambda: _env("HOME_LON"))
    home_city: str = field(default_factory=lambda: _env("HOME_CITY"))

    # Home Assistant
    ha_url: str = field(default_factory=lambda: _env("HA_URL", "http://localhost:8123"))
    ha_token: str = field(default_factory=lambda: _env("HA_TOKEN"))
    default_light: str = field(default_factory=lambda: _env("FRIDAY_DEFAULT_LIGHT"))

    # Распознавание речи
    stt_language: str = field(default_factory=lambda: _env("STT_LANGUAGE", "ru"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))

    # Wake word
    wake_engine: str = field(default_factory=lambda: _env("WAKE_ENGINE", "vosk"))  # vosk | porcupine
    wake_word: str = field(default_factory=lambda: _env("WAKE_WORD", "пятница"))
    vosk_model_url: str = field(
        default_factory=lambda: _env(
            "VOSK_MODEL_URL", "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
        )
    )
    porcupine_access_key: str = field(default_factory=lambda: _env("PORCUPINE_ACCESS_KEY"))
    porcupine_keyword_path: str = field(default_factory=lambda: _env("PORCUPINE_KEYWORD_PATH"))
    porcupine_model_path: str = field(default_factory=lambda: _env("PORCUPINE_MODEL_PATH"))
    porcupine_sensitivity: float = field(default_factory=lambda: _float("PORCUPINE_SENSITIVITY", "0.6"))

    # Запись фразы после wake word
    silence_seconds: float = field(default_factory=lambda: _float("SILENCE_SECONDS", "0.9"))
    max_phrase_seconds: float = field(default_factory=lambda: _float("MAX_PHRASE_SECONDS", "15"))
    start_timeout_seconds: float = field(default_factory=lambda: _float("START_TIMEOUT_SECONDS", "5"))
    followup_seconds: float = field(default_factory=lambda: _float("FOLLOWUP_SECONDS", "4"))
    chime: bool = field(default_factory=lambda: _env("CHIME", "1") == "1")
    # Поиск в интернете (серверный инструмент Anthropic, отдельный ключ не нужен)
    web_search: bool = field(default_factory=lambda: _env("WEB_SEARCH", "1") == "1")
    web_search_max_uses: int = field(default_factory=lambda: int(_env("WEB_SEARCH_MAX_USES", "3")))
    web_search_tool: str = field(default_factory=lambda: _env("WEB_SEARCH_TOOL", "web_search_20260318"))

    # Напоминания
    reminder_check_seconds: float = field(default_factory=lambda: _float("REMINDER_CHECK_SECONDS", "10"))
    # Имя списка в Apple «Напоминаниях» для дублирования (пусто = выключено)
    apple_reminders_list: str = field(default_factory=lambda: _env("APPLE_REMINDERS_LIST"))

    # Задержка звука на выходе, сек. Пусто = авто: ~2 сек для HomePod/AirPlay, иначе 0.3
    output_latency: str = field(default_factory=lambda: _env("OUTPUT_LATENCY"))

    # Голосовая идентификация владельца
    voice_id: bool = field(default_factory=lambda: _env("VOICE_ID", "1") == "1")
    # greet: чужим голосам тоже отвечать, но без личных данных; owner_only: чужих игнорировать
    voice_id_policy: str = field(default_factory=lambda: _env("VOICE_ID_POLICY", "greet"))
    # 0 = порог калибруется автоматически при знакомстве
    voice_id_threshold: float = field(default_factory=lambda: _float("VOICE_ID_THRESHOLD", "0"))
    # Голосовая проверка доступа при запуске --voice: сказать кодовое слово своим голосом
    startup_auth: bool = field(default_factory=lambda: _env("STARTUP_AUTH", "1") == "1")
    auth_phrase: str = field(default_factory=lambda: _env("AUTH_PHRASE", "подтверждаю"))
    auth_attempts: int = field(default_factory=lambda: int(_env("AUTH_ATTEMPTS", "3")))
    # Через сколько минут тишины снова поприветствовать по имени
    greet_after_minutes: float = field(default_factory=lambda: _float("GREET_AFTER_MINUTES", "30"))

    # Синтез речи
    tts_engine: str = field(default_factory=lambda: _env("TTS_ENGINE", "say"))  # say | silero | elevenlabs
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "Milena"))
    tts_rate: int = field(default_factory=lambda: int(_env("TTS_RATE", "190")))
    silero_speaker: str = field(default_factory=lambda: _env("SILERO_SPEAKER", "xenia"))
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    elevenlabs_voice_id: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_ID"))
    # v4_turbo: новейшая модель для ассистентов (~100 мс); если недоступна, откат на multilingual_v2
    elevenlabs_model: str = field(default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_v4_turbo"))
    # 0..1: ниже = живее и эмоциональнее, выше = ровнее и предсказуемее
    elevenlabs_stability: float = field(default_factory=lambda: _float("ELEVENLABS_STABILITY", "0.5"))
    elevenlabs_similarity: float = field(default_factory=lambda: _float("ELEVENLABS_SIMILARITY", "0.75"))
    # 0..1: усиление манеры голоса, повышает задержку и нестабильность
    elevenlabs_style: float = field(default_factory=lambda: _float("ELEVENLABS_STYLE", "0"))
    elevenlabs_speed: float = field(default_factory=lambda: _float("ELEVENLABS_SPEED", "1.0"))
    elevenlabs_speaker_boost: bool = field(default_factory=lambda: _env("ELEVENLABS_SPEAKER_BOOST", "1") == "1")
    # acute: ударения из словаря передаются знаком ударения; none: не передавать
    elevenlabs_stress: str = field(default_factory=lambda: _env("ELEVENLABS_STRESS", "acute"))


settings = Settings()
