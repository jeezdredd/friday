"""Голосовая идентификация владельца.

Модель WeSpeaker ResNet34 (ONNX, ~26 МБ) через sherpa-onnx превращает фразу в
256-мерный отпечаток голоса. При знакомстве (python -m friday.enroll) записывается
несколько фраз, их отпечатки усредняются, порог калибруется по разбросу твоих же
фраз. Дальше каждая команда сравнивается с отпечатком по косинусному сходству.

Это удобство, а не защита: запись или клон голоса могут её обмануть. Для замков,
платежей и подобного нужна настоящая аутентификация.

Отпечаток хранится локально: FRIDAY_DATA_DIR/voiceprint.json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from friday.config import settings

log = logging.getLogger(__name__)

MODEL_NAME = "wespeaker_en_voxceleb_resnet34.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_NAME}"
SAMPLE_RATE = 16_000

MIN_SECONDS = 1.0  # короче этого отпечаток ненадёжен
# Живой голос с разного расстояния гуляет сильнее синтетики, а разные люди у этой модели
# обычно дают сходство заметно ниже 0.5, поэтому потолок порога 0.6.
THRESHOLD_FLOOR = 0.40
THRESHOLD_CEIL = 0.60
THRESHOLD_MARGIN = 0.15


@dataclass
class Voiceprint:
    name: str
    embedding: list[float]
    threshold: float
    model: str = MODEL_NAME
    samples: int = 0
    self_similarity: list[float] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def vector(self) -> np.ndarray:
        return np.asarray(self.embedding, dtype=np.float32)


@dataclass(frozen=True)
class Verification:
    score: float
    threshold: float
    duration: float
    name: str = ""

    @property
    def reliable(self) -> bool:
        return self.duration >= MIN_SECONDS

    @property
    def is_owner(self) -> bool:
        return self.score >= self.threshold


def voiceprint_path() -> Path:
    return settings.data_dir / "voiceprint.json"


def load_voiceprint(path: Path | None = None) -> Voiceprint | None:
    path = path or voiceprint_path()
    if not path.exists():
        return None
    try:
        return Voiceprint(**json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError) as exc:
        log.warning("Отпечаток голоса повреждён (%s), нужно познакомиться заново", exc)
        return None


def save_voiceprint(vp: Voiceprint, path: Path | None = None) -> Path:
    path = path or voiceprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(vp), ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)  # биометрия: читать может только владелец файла
    return path


def ensure_model(models_dir: Path | None = None) -> Path:
    target = (models_dir or settings.data_dir / "models") / MODEL_NAME
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    log.warning("Скачиваю модель голосовой идентификации (~26 МБ)")
    tmp = target.with_suffix(".part")
    with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=120) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
    tmp.rename(target)
    return target


def normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(normalize(a), normalize(b)))


class Embedder:
    """Обёртка над sherpa-onnx. extractor можно подменить в тестах."""

    def __init__(self, extractor=None):
        if extractor is None:
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(ensure_model()), num_threads=2)
            extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.extractor = extractor

    def embed(self, audio: np.ndarray) -> np.ndarray:
        stream = self.extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, np.ascontiguousarray(audio, dtype=np.float32))
        stream.input_finished()
        return normalize(np.asarray(self.extractor.compute(stream), dtype=np.float32))


def calibrate_threshold(embeddings: list[np.ndarray]) -> tuple[float, list[float]]:
    """Порог по разбросу твоих же фраз: каждую сравниваем со средним остальных
    (leave-one-out) и ставим порог с запасом ниже худшего совпадения."""
    if len(embeddings) < 2:
        return THRESHOLD_FLOOR, []
    scores = []
    for i, e in enumerate(embeddings):
        rest = normalize(np.mean([x for j, x in enumerate(embeddings) if j != i], axis=0))
        scores.append(cosine(e, rest))
    threshold = min(THRESHOLD_CEIL, max(THRESHOLD_FLOOR, min(scores) - THRESHOLD_MARGIN))
    return threshold, scores


def build_voiceprint(name: str, embeddings: list[np.ndarray]) -> Voiceprint:
    threshold, scores = calibrate_threshold(embeddings)
    centroid = normalize(np.mean(embeddings, axis=0))
    return Voiceprint(
        name=name.strip(),
        embedding=[float(x) for x in centroid],
        threshold=float(settings.voice_id_threshold or threshold),
        samples=len(embeddings),
        self_similarity=[round(s, 3) for s in scores],
    )


class SpeakerID:
    def __init__(self, voiceprint: Voiceprint, embedder: Embedder | None = None):
        self.voiceprint = voiceprint
        self.embedder = embedder or Embedder()

    def verify(self, audio: np.ndarray) -> Verification:
        started = time.monotonic()
        duration = audio.size / SAMPLE_RATE
        score = cosine(self.embedder.embed(audio), self.voiceprint.vector) if audio.size else 0.0
        threshold = float(settings.voice_id_threshold or self.voiceprint.threshold)
        log.info(
            "Голос: сходство %.2f (порог %.2f), %.1f сек, %.2f сек на проверку",
            score,
            threshold,
            duration,
            time.monotonic() - started,
        )
        return Verification(score, threshold, duration, self.voiceprint.name)


@lru_cache(maxsize=1)
def load_speaker_id() -> SpeakerID | None:
    vp = load_voiceprint()
    if vp is None:
        return None
    if vp.model != MODEL_NAME:
        log.warning("Отпечаток сделан другой моделью, нужно познакомиться заново: python -m friday.enroll")
        return None
    return SpeakerID(vp)


# ---------- решения на основе голоса ----------

POLICIES = ("greet", "owner_only")


@dataclass(frozen=True)
class Identity:
    verification: Verification | None  # None: идентификация выключена или нет отпечатка

    @property
    def known(self) -> bool:
        return self.verification is not None and self.verification.reliable and self.verification.is_owner

    @property
    def stranger(self) -> bool:
        return self.verification is not None and self.verification.reliable and not self.verification.is_owner

    @property
    def name(self) -> str:
        return self.verification.name if self.verification else ""


class IdentityGate:
    """Что делать с услышанной фразой в зависимости от того, кто говорит."""

    def __init__(self, speaker_id: SpeakerID | None, policy: str = "greet", greet_after_minutes: float = 30):
        if policy not in POLICIES:
            raise ValueError(f"VOICE_ID_POLICY должен быть одним из {POLICIES}")
        self.speaker_id = speaker_id
        self.policy = policy
        self.greet_after = greet_after_minutes * 60
        self._last_owner_contact = float("-inf")

    @property
    def enabled(self) -> bool:
        return self.speaker_id is not None

    def identify(self, audio: np.ndarray) -> Identity:
        if self.speaker_id is None or audio.size == 0:
            return Identity(None)
        return Identity(self.speaker_id.verify(audio))

    def allowed(self, identity: Identity) -> bool:
        """owner_only: чужие голоса игнорируются. Короткие фразы, по которым голос не определить,
        пропускаем: иначе будет раздражать отказами на "Пятница" без команды."""
        return not (self.policy == "owner_only" and identity.stranger)

    def should_greet(self, identity: Identity, now: float | None = None) -> bool:
        """Приветствие по имени при первом обращении в сессии или после долгого перерыва."""
        if not identity.known:
            return False
        now = time.monotonic() if now is None else now
        greet = now - self._last_owner_contact >= self.greet_after
        self._last_owner_contact = now
        return greet

    @staticmethod
    def context_note(identity: Identity) -> str | None:
        """Пояснение для модели: кто сейчас говорит."""
        if identity.verification is None:
            return None
        if identity.known:
            return f"Сейчас говорит {identity.name}, владелец, голос подтверждён."
        if identity.stranger:
            return (
                "Голос не совпал с владельцем, возможно, говорит гость. Отвечай вежливо, "
                "но не рассказывай личное владельца (напоминания, память, планы) и не выполняй "
                "действия, которые нельзя отменить. Не называй гостя именем владельца."
            )
        return None  # фраза слишком короткая, чтобы судить
