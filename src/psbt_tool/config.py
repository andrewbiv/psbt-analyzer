"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    mempool_base_url: str
    network: str
    mempool_cache_ttl: int
    max_psbt_bytes: int


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so we don't pull in python-dotenv just for this."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        mempool_base_url=os.getenv("MEMPOOL_BASE_URL", "https://mempool.space/api").rstrip("/"),
        network=os.getenv("NETWORK", "mainnet"),
        mempool_cache_ttl=int(os.getenv("MEMPOOL_CACHE_TTL", "60")),
        max_psbt_bytes=int(os.getenv("MAX_PSBT_BYTES", str(1024 * 1024))),
    )
