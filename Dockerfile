FROM python:3.10-slim-bullseye

# Build argument to control voice dependencies
ARG ENABLE_VOICE=false

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Configure APT to use multiple mirrors and be more resilient
RUN echo 'deb http://deb.debian.org/debian bullseye main' > /etc/apt/sources.list \
    && echo 'deb http://deb.debian.org/debian-security bullseye-security main' >> /etc/apt/sources.list \
    && echo 'deb http://deb.debian.org/debian bullseye-updates main' >> /etc/apt/sources.list \
    && echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/80-retries \
    && echo 'Acquire::http::Timeout "30";' >> /etc/apt/apt.conf.d/80-retries \
    && echo 'Acquire::ftp::Timeout "30";' >> /etc/apt/apt.conf.d/80-retries

# ---- system deps (ONE layer) ----
# Add retry logic and use multiple mirrors for reliability
RUN apt-get update --fix-missing || apt-get update --fix-missing || apt-get update --fix-missing \
    && apt-get install -y --no-install-recommends --fix-missing \
    openssl \
    libglib2.0-0 \
    build-essential \
    tzdata \
    wget \
    ca-certificates \
    && apt-get update --fix-missing \
    && apt-get install -y --no-install-recommends --fix-missing \
    ffmpeg \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    fonts-liberation \
    libnss3 \
    libgbm1 \
    gnupg \
    libportaudio2 \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ---- chrome (ONE layer) ----
# Download and install Chrome with retry logic
RUN wget --tries=3 --timeout=30 --retry-connrefused \
    -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    -O /tmp/chrome.deb || \
    (echo "Primary download failed, trying alternative..." && \
     wget --tries=3 --timeout=30 \
     -q https://dl-ssl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
     -O /tmp/chrome.deb) \
    && apt-get update --fix-missing \
    && apt-get install -y --fix-missing /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ---- python deps (cache-critical) ----
# Use socket-based requirements (WebSocket TTS, no ML models)
COPY requirements-socket.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install --timeout=20000 -r requirements-socket.txt \
    && pip install boto3

# Conditionally install voice dependencies (Pipecat) if ENABLE_VOICE=true
COPY google_meet/speak/requirements_voice.txt ./google_meet/speak/
RUN if [ "$ENABLE_VOICE" = "true" ]; then \
        echo "🎤 Installing voice dependencies (Pipecat)..." && \
        pip install --timeout=20000 -r google_meet/speak/requirements_voice.txt; \
    else \
        echo "⏩ Skipping voice dependencies (ENABLE_VOICE=false)"; \
    fi

# ---- configs ----
COPY pulse-client.conf /etc/pulse/client.conf
COPY pulse-daemon.conf /etc/pulse/daemon.conf
RUN sed -i 's/\r$//' /etc/pulse/*.conf

# ---- bot runtime only (no FastAPI server) ----
# Keep the image focused on the bot entrypoint and its meeting/audio code.
COPY app.py utils.py logger.py ./
COPY monitoring.py ./
COPY config ./config
COPY google_meet ./google_meet

COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

RUN mkdir -p /app/out && chmod 777 /app/out

ENTRYPOINT ["/entrypoint.sh"]
