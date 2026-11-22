from redis.asyncio import Redis

from app.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
        health_check_interval=30,
    )
