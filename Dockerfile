# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.title="civitai-buzz" \
      org.opencontainers.image.description="Claim the daily 25 Buzz on Civitai, then exit" \
      org.opencontainers.image.licenses="MIT"

# Runtime knobs only. CIVITAI_COOKIE / USER_AGENT are supplied at `docker run`
# time and are deliberately absent from this file, the image layers and git.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    ARTIFACTS_DIR=/app/artifacts \
    BROWSER=chrome \
    WEBDRIVER_PATH=/usr/bin/chromedriver \
    HEADLESS=true

# xvfb + xauth let us run a headed browser (HEADLESS=false) when Cloudflare
# wants a real, rendered window.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        xvfb \
        xauth \
        fonts-liberation \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man /tmp/*

ENV TZ=Asia/Taipei

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY buzz.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

RUN useradd --create-home --uid 10001 runner \
    && mkdir -p "${ARTIFACTS_DIR}" \
    && chown -R runner:runner /app

USER runner

ENTRYPOINT ["/app/entrypoint.sh"]
