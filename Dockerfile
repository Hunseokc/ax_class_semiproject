# API 서버 이미지: FastAPI(uvicorn) + 앱 안 스케줄러 + 적재 CLI(python -m app.ingest)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul

WORKDIR /srv

# 의존성 레이어를 먼저 만들어 소스만 바뀌면 재설치하지 않는다
COPY requirements.txt .
RUN pip install -r requirements.txt

# 비root 실행. yfinance·pykrx가 홈 디렉터리에 캐시를 쓰므로 홈을 만든다
RUN useradd --create-home --uid 1000 app && mkdir -p /srv/data && chown app:app /srv/data

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Windows 체크아웃(CRLF)이어도 셸 스크립트가 동작하도록 줄 끝을 정리한다
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

COPY app ./app
COPY config ./config
COPY db ./db
COPY web ./web
COPY sample_data ./sample_data
COPY tests ./tests

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/db', timeout=4)"

ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
