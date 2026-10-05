import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # LLM
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    model: str = field(default_factory=lambda: _env("FRIDAY_MODEL", "claude-sonnet-5-5"))
    max_tokens: int = field(default_factory=lambda: int(_env("FRIDAY_MAX_TOKENS", "1024")))
    max_history: int = field(default_factory=lambda: int(_env("FRIDAY_MAX_HISTORY", "30")))

    # Пользователь
    user_name: str = field(default_factory=lambda: _env("FRIDAY_USER_NAME"))
    timezone: str = field(default_factory=lambda: _env("FRIDAY_TIMEZONE", "UTC"))
    data_dir: Path = field(default_factory=lambda: Path(_env("FRIDAY_DATA_DIR", "~/.friday")).expanduser())

    # Home Assistant
    ha_url: str = field(default_factory=lambda: _env("HA_URL", "http://localhost:8123"))
    ha_token: str = field(default_factory=lambda: _env("HA_TOKEN"))
    default_light: str = field(default_factory=lambda: _env("FRIDAY_DEFAULT_LIGHT"))

    # Погода (open-meteo, ключ не нужен)
    weather_lat: str = field(default_factory=lambda: _env("WEATHER_LAT"))
    weather_lon: str = field(default_factory=lambda: _env("WEATHER_LON"))

    # Голос
    stt_language: str = field(default_factory=lambda: _env("STT_LANGUAGE", "ru"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "Milena"))
    tts_rate: int = field(default_factory=lambda: int(_env("TTS_RATE", "190")))


settings = Settings()
