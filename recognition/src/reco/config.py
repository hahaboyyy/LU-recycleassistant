"""Provider configuration, all overridable by environment variables.

Defaults target DeepSeek's vision-capable OpenAI-compatible endpoint, because
that is the API named in the team brief. Nothing here is DeepSeek-specific:
any OpenAI-compatible ``POST {base_url}/chat/completions`` that accepts
``image_url`` content works.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

#: base_url / model are starting points -- confirm both in the provider console
#: before the first measured run, since vision model names change.
PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash-vision-exp",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY"},
    "qwen": {
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-plus",
        "key_env": "DASHSCOPE_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "qwen/qwen2.5-vl-72b-instruct",
        "key_env": "OPENROUTER_API_KEY",
    },
    "mock": {"base_url": "", "model": "mock-vision-1", "key_env": ""},
}

DEFAULT_LOG = "runs/recognition.jsonl"


@dataclass(frozen=True)
class Config:
    provider: str = "deepseek"
    base_url: str = PRESETS["deepseek"]["base_url"]
    model: str = PRESETS["deepseek"]["model"]
    api_key: str = ""
    timeout_s: float = 90.0
    max_retries: int = 2
    temperature: float = 0.0
    max_tokens: int = 900
    json_mode: bool = True
    #: Ask the model not to confirm entries whose scope depends on an invisible property.
    strict_scope: bool = False
    image_max_edge: int = 1280
    jpeg_quality: int = 85
    log_path: str = DEFAULT_LOG
    #: Role A's item catalogue; empty -> <project>/data/supported_items.csv
    catalogue_path: str = ""
    #: USD per 1M tokens. Left empty on purpose: read the real numbers from the
    #: provider console and export them, so the report never quotes invented prices.
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None

    def cost_usd(self, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
        if self.price_in_per_mtok is None or self.price_out_per_mtok is None:
            return None
        pt = prompt_tokens or 0
        ct = completion_tokens or 0
        return round(
            pt / 1_000_000 * self.price_in_per_mtok + ct / 1_000_000 * self.price_out_per_mtok,
            6,
        )

    def describe(self) -> str:
        return f"{self.provider}:{self.model} (image<={self.image_max_edge}px, json_mode={self.json_mode})"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


def _env_opt_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _load_dotenv() -> None:
    """Minimal .env reader so the key never has to be typed into a shell.

    Existing environment variables win, so CI / shell exports still work.
    """
    path = Path(os.environ.get("RECO_ENV_FILE", ".env"))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(provider: str | None = None, **overrides: object) -> Config:
    _load_dotenv()
    provider = (provider or os.environ.get("RECO_PROVIDER") or "deepseek").strip().lower()
    if provider not in PRESETS:
        raise ValueError(
            f"unknown provider {provider!r}; choose from {sorted(PRESETS)} "
            "or set RECO_BASE_URL + RECO_MODEL explicitly"
        )
    preset = PRESETS[provider]
    key_env = preset["key_env"]
    cfg = Config(
        provider=provider,
        base_url=os.environ.get("RECO_BASE_URL", preset["base_url"]),
        model=os.environ.get("RECO_MODEL", preset["model"]),
        api_key=os.environ.get("RECO_API_KEY", os.environ.get(key_env, "") if key_env else ""),
        timeout_s=_env_float("RECO_TIMEOUT", 90.0),
        max_retries=int(_env_float("RECO_MAX_RETRIES", 2)),
        temperature=_env_float("RECO_TEMPERATURE", 0.0),
        max_tokens=int(_env_float("RECO_MAX_TOKENS", 900)),
        json_mode=os.environ.get("RECO_JSON_MODE", "1") not in {"0", "false", "no"},
        strict_scope=os.environ.get("RECO_STRICT_SCOPE", "0") not in {"0", "false", "no"},
        image_max_edge=int(_env_float("RECO_IMAGE_MAX_EDGE", 1280)),
        jpeg_quality=int(_env_float("RECO_JPEG_QUALITY", 85)),
        log_path=os.environ.get("RECO_LOG", DEFAULT_LOG),
        catalogue_path=os.environ.get("RECO_CATALOGUE", ""),
        price_in_per_mtok=_env_opt_float("RECO_PRICE_IN"),
        price_out_per_mtok=_env_opt_float("RECO_PRICE_OUT"),
    )
    if overrides:
        cfg = replace(cfg, **overrides)  # type: ignore[arg-type]
    return cfg
