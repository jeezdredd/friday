"""Создаёт голос Пятницы в ElevenLabs и прописывает его в .env.

    python -m friday.voice_setup

Нужен только ELEVENLABS_API_KEY в .env. Скрипт генерирует несколько вариантов
голоса по описанию (Voice Design), проигрывает их, ты выбираешь лучший,
голос сохраняется в твоём аккаунте, а его ID и TTS_ENGINE=elevenlabs
записываются в .env.
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


def _client() -> httpx.Client:
    if not settings.elevenlabs_api_key:
        sys.exit("ELEVENLABS_API_KEY не задан. Добавь его в .env и запусти снова.")
    return httpx.Client(base_url=API, headers={"xi-api-key": settings.elevenlabs_api_key}, timeout=120)


def _check(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        sys.exit(f"ElevenLabs вернул {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def design_previews(client: httpx.Client, description: str) -> list[dict]:
    data = _check(
        client.post(
            "/text-to-voice/design",
            json={"voice_description": description, "text": PREVIEW_TEXT},
        )
    )
    return data["previews"]


def save_and_play(previews: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    player = shutil.which("afplay")
    for i, p in enumerate(previews, 1):
        path = out_dir / f"friday_preview_{i}.mp3"
        path.write_bytes(base64.b64decode(p["audio_base_64"]))
        paths.append(path)
        print(f"\nВариант {i}: {path}")
        if player:
            subprocess.run([player, str(path)], check=False)
    if not player:
        print("\nafplay не найден, послушай файлы вручную.")
    return paths


def create_voice(client: httpx.Client, generated_voice_id: str, description: str) -> str:
    data = _check(
        client.post(
            "/text-to-voice",
            json={
                "voice_name": VOICE_NAME,
                "voice_description": description,
                "generated_voice_id": generated_voice_id,
            },
        )
    )
    return data["voice_id"]


def write_env(voice_id: str) -> Path:
    env_path = find_dotenv(usecwd=True) or ".env"
    path = Path(env_path)
    path.touch(exist_ok=True)
    set_key(str(path), "ELEVENLABS_VOICE_ID", voice_id, quote_mode="never")
    set_key(str(path), "TTS_ENGINE", "elevenlabs", quote_mode="never")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday.voice_setup", description="Создать голос Пятницы в ElevenLabs")
    parser.add_argument("--description", default=VOICE_DESCRIPTION, help="своё описание голоса (на английском)")
    args = parser.parse_args()

    client = _client()
    out_dir = settings.data_dir / "voice_previews"

    while True:
        print("Генерирую варианты голоса, это занимает до минуты...")
        previews = design_previews(client, args.description)
        save_and_play(previews, out_dir)

        choice = (
            input(
                f"\nНомер понравившегося варианта (1-{len(previews)}), r = сгенерировать заново, "
                "p = переслушать, q = выйти: "
            )
            .strip()
            .lower()
        )
        while choice == "p":
            save_and_play(previews, out_dir)
            choice = input(f"Номер (1-{len(previews)}), r, q: ").strip().lower()
        if choice == "q":
            return
        if choice == "r":
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(previews):
            chosen = previews[int(choice) - 1]
            break
        print("Не понял, попробуем ещё раз.")

    voice_id = create_voice(client, chosen["generated_voice_id"], args.description)
    env_path = write_env(voice_id)
    print(f"\nГолос сохранён в аккаунте ElevenLabs как {VOICE_NAME!r}.")
    print(f"ELEVENLABS_VOICE_ID и TTS_ENGINE=elevenlabs записаны в {env_path}")
    print("Проверь: python -m friday --speak")


if __name__ == "__main__":
    main()
