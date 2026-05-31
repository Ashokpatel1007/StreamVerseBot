import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    search_bot_token: str
    delivery_bot_token: str
    delivery_bot_username: str

    source_channel_id: int

    redis_url: str

    page_size: int
    session_ttl_seconds: int

    search_rate_limit_seconds: int
    delivery_rate_limit_seconds: int

    delivery_concurrency_per_user: int
    delivery_progress_every: int


def load_config() -> Config:
    def req(name: str) -> str:
        v = os.getenv(name)
        if not v:
            raise RuntimeError(f"Missing env: {name}")
        return v

    return Config(
        search_bot_token=req("SEARCH_BOT_TOKEN"),
        delivery_bot_token=req("DELIVERY_BOT_TOKEN"),
        delivery_bot_username=req("DELIVERY_BOT_USERNAME").lstrip("@"),
        source_channel_id=int(req("SOURCE_CHANNEL_ID")),
        redis_url=req("REDIS_URL"),
        page_size=int(os.getenv("PAGE_SIZE", "10")),
        session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
        search_rate_limit_seconds=int(os.getenv("SEARCH_RATE_LIMIT_SECONDS", "2")),
        delivery_rate_limit_seconds=int(os.getenv("DELIVERY_RATE_LIMIT_SECONDS", "2")),
        delivery_concurrency_per_user=int(os.getenv("DELIVERY_CONCURRENCY_PER_USER", "1")),
        delivery_progress_every=int(os.getenv("DELIVERY_PROGRESS_EVERY", "5")),
    )