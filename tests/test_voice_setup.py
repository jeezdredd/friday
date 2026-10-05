import httpx
import pytest

from friday.voice_setup import FeatureUnavailable, _check, rank_voices


def _resp(status: int, json: dict) -> httpx.Response:
    return httpx.Response(status, json=json, request=httpx.Request("POST", "https://api.elevenlabs.io/v1/x"))


def test_paid_feature_raises_feature_unavailable():
    resp = _resp(
        403,
        {
            "detail": {
                "code": "feature_not_available",
                "message": "Creating a voice through the API is only available on a paid plan.",
            }
        },
    )
    with pytest.raises(FeatureUnavailable, match="paid plan"):
        _check(resp)


def test_other_errors_exit():
    with pytest.raises(SystemExit):
        _check(_resp(401, {"detail": {"status": "invalid_api_key"}}))


def test_rank_voices_prefers_female_and_own():
    voices = [
        {"voice_id": "1", "name": "Adam", "category": "premade", "labels": {"gender": "male"}},
        {"voice_id": "2", "name": "Sarah", "category": "premade", "labels": {"gender": "female"}},
        {"voice_id": "3", "name": "Friday", "category": "generated", "labels": {"gender": "female"}},
        {"voice_id": "4", "name": "Alice", "category": "premade", "labels": {"gender": "female"}},
    ]
    assert [v["voice_id"] for v in rank_voices(voices)] == ["3", "4", "2"]
    assert [v["voice_id"] for v in rank_voices(voices, show_all=True)] == ["3", "4", "2", "1"]


def test_rank_voices_falls_back_when_no_gender_labels():
    voices = [{"voice_id": "1", "name": "B"}, {"voice_id": "2", "name": "A"}]
    assert [v["voice_id"] for v in rank_voices(voices)] == ["2", "1"]
