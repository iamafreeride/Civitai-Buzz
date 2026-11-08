# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.title="civitai-buzz" \
      org.opencontainers.image.description="Claim the daily 25 Buzz on Civitai using your own browser cookie" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    ARTIFACTS_DIR=/app/artifacts \
    BROWSER=chrome \
    WEBDRIVER_PATH=/usr/bin/chromedriver

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man /tmp/*

ENV TZ=Asia/Taipei

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY buzz.py ./

RUN useradd --create-home --uid 10001 runner \
    && mkdir -p "${ARTIFACTS_DIR}" \
    && chown -R runner:runner /app

USER runner

ENTRYPOINT ["python3", "buzz.py"]
