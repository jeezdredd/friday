"""Тонкий клиент к REST API Home Assistant.

Документация: https://developers.home-assistant.io/docs/api/rest/
Токен: профиль пользователя в HA -> Security -> Long-lived access tokens.
"""

from __future__ import annotations

from typing import Any

import httpx

from friday.config import settings
from friday.tools.registry import ToolError


class HomeAssistantError(ToolError):
    pass


class HomeAssistant:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 10.0):
        self.url = (url or settings.ha_url).rstrip("/")
        token = token or settings.ha_token
        if not token:
            raise HomeAssistantError("HA_TOKEN не задан в .env")
        self._client = httpx.Client(
            base_url=f"{self.url}/api",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise HomeAssistantError(f"Home Assistant недоступен ({self.url}): {exc}") from exc
        if resp.status_code >= 400:
            raise HomeAssistantError(f"HA вернул {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.content else None

    def states(self) -> list[dict[str, Any]]:
        return self._request("GET", "/states")

    def state(self, entity_id: str) -> dict[str, Any]:
        return self._request("GET", f"/states/{entity_id}")

    def entities(self, domain: str) -> list[dict[str, Any]]:
        prefix = f"{domain}."
        return [s for s in self.states() if s["entity_id"].startswith(prefix)]

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        return self._request("POST", f"/services/{domain}/{service}", json=data)


_ha: HomeAssistant | None = None


def get_ha() -> HomeAssistant:
    """Ленивый синглтон, чтобы ассистент запускался даже без настроенного HA."""
    global _ha
    if _ha is None:
        _ha = HomeAssistant()
    return _ha
