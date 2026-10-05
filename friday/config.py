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

    # Синтез речи
    tts_engine: str = field(default_factory=lambda: _env("TTS_ENGINE", "say"))  # say | silero | elevenlabs
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "Milena"))
    tts_rate: int = field(default_factory=lambda: int(_env("TTS_RATE", "190")))
    silero_speaker: str = field(default_factory=lambda: _env("SILERO_SPEAKER", "xenia"))
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    elevenlabs_voice_id: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_ID"))
    # multilingual_v2: лучшая интонация и склонение чисел в русском; flash_v2_5: быстрее, но площе
    elevenlabs_model: str = field(default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_multilingual_v2"))
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
