"""Redis 연결 (2차 로그인: refresh token 저장·폐기, 로그인 시도 제한). 개발은 compose의 redis, 배포는 Upstash."""
from __future__ import annotations

from functools import lru_cache

import redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
