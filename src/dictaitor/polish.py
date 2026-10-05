"""Optional clean-up pass through a *local* LLM (Ollama).

Off by default. Refuses non-local URLs unless `allow_remote = true`, so the
text cannot leak to a cloud service by a configuration typo.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlparse

from .config import Config

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

PROMPT = """Popraw poniższą transkrypcję dyktowanego tekstu.
Zasady:
- Zachowaj sens, język i styl autora. Nie dodawaj treści, nie streszczaj.
- Usuń powtórzenia i zaczęte-a-porzucone fragmenty, jeśli autor sam się poprawił
  (np. "w poniedziałek, nie, we wtorek" -> "we wtorek").
- Popraw interpunkcję i wielkie litery.
{instructions}
Zwróć WYŁĄCZNIE poprawiony tekst.

Tekst:
{text}"""


class PolishError(RuntimeError):
    pass


def polish(text: str, config: Config) -> str:
    cfg = config["polish"]
    host = urlparse(cfg["url"]).hostname or ""
    if host not in LOCAL_HOSTS and not cfg["allow_remote"]:
        raise PolishError(
            f"polish.url wskazuje na {host!r}, a nie na localhost. "
            "Ustaw polish.allow_remote = true, jeśli naprawdę tego chcesz."
        )
    instructions = cfg["instructions"].strip()
    body = json.dumps(
        {
            "model": cfg["model"],
            "prompt": PROMPT.format(
                text=text, instructions=f"- {instructions}" if instructions else ""
            ),
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode()
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    # Bypass any system proxy: the request must stay on this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=60) as resp:
            result = json.loads(resp.read())["response"].strip()
    except OSError as exc:
        raise PolishError(f"Nie udało się połączyć z lokalnym modelem: {exc}") from exc
    return result or text
