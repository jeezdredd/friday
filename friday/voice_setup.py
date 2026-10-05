"""Настройка голоса Пятницы в ElevenLabs.

    python -m friday.voice_setup               # создать голос по описанию, на бесплатном тарифе выбрать готовый
    python -m friday.voice_setup --pick        # сразу выбрать из готовых голосов аккаунта
    python -m friday.voice_setup --voice-id ID # прописать конкретный голос

Создание голоса через API (Voice Design) доступно только на платных тарифах.
На бесплатном скрипт автоматически переключается на выбор из готовых голосов.
Результат: ELEVENLABS_VOICE_ID и TTS_ENGINE=elevenlabs записываются в .env.
"""

from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import find_dotenv, set_key

from friday.config import settings

API = "https://api.elevenlabs.io/v1"

VOICE_NAME = "Friday"

# Описываем характер и тембр, а не копируем голос актрисы: клонировать
# реального человека без согласия запрещают правила ElevenLabs.
VOICE_DESCRIPTION = (
    "A young woman in her early thirties with a warm, slightly low and smooth voice. "
    "Calm, confident and quick-witted, with a subtle dry sense of humor. "
    "Speaks clearly at a natural conversational pace, like a brilliant personal AI assistant "
    "who is loyal, efficient and a little playful. Close-mic studio quality, no background noise."
)

PREVIEW_TEXT = (
    "Доброе утро. В комнате двадцать два градуса, на улице солнечно, свет я уже включила. "
    "Напоминаю, что в десять у тебя созвон, так что кофе лучше сделать прямо сейчас. "
    "Если что, я рядом, просто скажи моё имя."
)

SHORT_TEST_TEXT = "Привет. Я Пятница. Свет включила, в комнате двадцать два градуса."


class FeatureUnavailable(Exception):
    """Функция недоступна на текущем тарифе."""


def _client() -> httpx.Client:
    if not settings.elevenlabs_api_key:
        sys.exit("ELEVENLABS_API_KEY не задан. Добавь его в .env и запусти снова.")
    return httpx.Client(base_url=API, headers={"xi-api-key": settings.elevenlabs_api_key}, timeout=120)


def _check(resp: httpx.Response) -> httpx.Response:
    if resp.status_code == 403 and "feature_not_available" in resp.text:
        raise FeatureUnavailable(resp.json().get("detail", {}).get("message", resp.text))
    if resp.status_code >= 400:
        sys.exit(f"ElevenLabs вернул {resp.status_code}: {resp.text[:300]}")
    return resp


def _play(path: Path) -> None:
    player = shutil.which("afplay")
    if player:
        subprocess.run([player, str(path)], check=False)
    else:
        print(f"  afplay не найден, файл: {path}")


def write_env(voice_id: str) -> Path:
    path = Path(find_dotenv(usecwd=True) or ".env")
    path.touch(exist_ok=True)
    set_key(str(path), "ELEVENLABS_VOICE_ID", voice_id, quote_mode="never")
    set_key(str(path), "TTS_ENGINE", "elevenlabs", quote_mode="never")
    return path


# ---------- Voice Design (платные тарифы) ----------


def design_previews(client: httpx.Client, description: str) -> list[dict]:
    resp = _check(client.post("/text-to-voice/design", json={"voice_description": description, "text": PREVIEW_TEXT}))
    return resp.json()["previews"]


def create_voice(client: httpx.Client, generated_voice_id: str, description: str) -> str:
    resp = _check(
        client.post(
            "/text-to-voice",
            json={"voice_name": VOICE_NAME, "voice_description": description, "generated_voice_id": generated_voice_id},
        )
    )
    return resp.json()["voice_id"]


def design_flow(client: httpx.Client, description: str, out_dir: Path) -> str | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    while True:
        print("Генерирую варианты голоса, это занимает до минуты...")
        previews = design_previews(client, description)
        paths = []
        for i, p in enumerate(previews, 1):
            path = out_dir / f"friday_preview_{i}.mp3"
            path.write_bytes(base64.b64decode(p["audio_base_64"]))
            paths.append(path)
            print(f"\nВариант {i}")
            _play(path)

        while True:
            choice = input(f"\nНомер (1-{len(previews)}), p N = переслушать, r = заново, q = выйти: ").strip().lower()
            if choice.startswith("p ") and choice[2:].isdigit() and 1 <= int(choice[2:]) <= len(paths):
                _play(paths[int(choice[2:]) - 1])
            elif choice in ("q", "r"):
                break
            elif choice.isdigit() and 1 <= int(choice) <= len(previews):
                return create_voice(client, previews[int(choice) - 1]["generated_voice_id"], description)
            else:
                print("Не понял.")
        if choice == "q":
            return None


# ---------- Выбор из готовых голосов (любой тариф) ----------


def list_voices(client: httpx.Client) -> list[dict]:
    return _check(client.get("/voices")).json()["voices"]


def rank_voices(voices: list[dict], show_all: bool = False) -> list[dict]:
    """Женские голоса первыми, затем свои/сгенерированные, затем остальные по имени."""

    def gender(v: dict) -> str:
        return (v.get("labels") or {}).get("gender", "").lower()

    if not show_all:
        female = [v for v in voices if gender(v) == "female"]
        voices = female or voices
    return sorted(voices, key=lambda v: (gender(v) != "female", v.get("category") == "premade", v["name"].lower()))


def describe_voice(v: dict) -> str:
    labels = v.get("labels") or {}
    extra = ", ".join(x for x in (labels.get("age"), labels.get("accent"), labels.get("description")) if x)
    return f"{v['name']} ({extra})" if extra else v["name"]


def test_in_russian(client: httpx.Client, voice_id: str, out_dir: Path) -> None:
    resp = _check(
        client.post(
            f"/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            json={"text": SHORT_TEST_TEXT, "model_id": settings.elevenlabs_model},
        )
    )
    path = out_dir / f"test_{voice_id}.mp3"
    path.write_bytes(resp.content)
    _play(path)


def play_sample(client: httpx.Client, v: dict, out_dir: Path) -> None:
    url = v.get("preview_url")
    if not url:
        print("  У этого голоса нет образца, попробуй t N")
        return
    path = out_dir / f"sample_{v['voice_id']}.mp3"
    if not path.exists():
        path.write_bytes(httpx.get(url, timeout=30, follow_redirects=True).raise_for_status().content)
    _play(path)


def pick_flow(client: httpx.Client, out_dir: Path, show_all: bool = False) -> str | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    voices = rank_voices(list_voices(client), show_all)
    if not voices:
        sys.exit("В аккаунте нет доступных голосов.")

    print("\nДоступные голоса:")
    for i, v in enumerate(voices, 1):
        print(f"  {i:2}. {describe_voice(v)}")
    print(
        "\nКоманды:\n"
        "  p N  образец голоса (бесплатно, обычно на английском)\n"
        f"  t N  тестовая фраза на русском (тратит ~{len(SHORT_TEST_TEXT)} символов лимита)\n"
        "  N    выбрать голос\n"
        "  q    выйти"
    )
    while True:
        cmd = input("> ").strip().lower()
        if cmd == "q":
            return None
        action, _, num = cmd.partition(" ")
        if action.isdigit():
            action, num = "", action
        if not (num.isdigit() and 1 <= int(num) <= len(voices)):
            print("Укажи номер из списка.")
            continue
        v = voices[int(num) - 1]
        if action == "p":
            play_sample(client, v, out_dir)
        elif action == "t":
            test_in_russian(client, v["voice_id"], out_dir)
        elif action == "":
            print(f"Выбран: {v['name']}")
            return v["voice_id"]
        else:
            print("Не понял команду.")


# ---------- CLI ----------


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday.voice_setup", description="Настроить голос Пятницы в ElevenLabs")
    parser.add_argument("--description", default=VOICE_DESCRIPTION, help="описание голоса для Voice Design (англ.)")
    parser.add_argument("--pick", action="store_true", help="выбрать из готовых голосов аккаунта")
    parser.add_argument("--all", action="store_true", help="показывать все голоса, не только женские")
    parser.add_argument("--voice-id", help="прописать конкретный voice_id без выбора")
    args = parser.parse_args()

    client = _client()
    out_dir = settings.data_dir / "voice_previews"

    if args.voice_id:
        _check(client.get(f"/voices/{args.voice_id}"))
        voice_id = args.voice_id
    elif args.pick:
        voice_id = pick_flow(client, out_dir, args.all)
    else:
        try:
            voice_id = design_flow(client, args.description, out_dir)
        except FeatureUnavailable as exc:
            print(f"\nСоздание голоса недоступно на твоём тарифе: {exc}")
            print("Переключаюсь на выбор из готовых голосов.")
            voice_id = pick_flow(client, out_dir, args.all)

    if not voice_id:
        print("Ничего не изменено.")
        return
    env_path = write_env(voice_id)
    print(f"\nELEVENLABS_VOICE_ID и TTS_ENGINE=elevenlabs записаны в {env_path}")
    print("Проверь: python -m friday --speak")


if __name__ == "__main__":
    main()
