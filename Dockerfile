FROM python:3.10-slim-bullseye

# Build argument to control voice dependencies
ARG ENABLE_VOICE=false

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# ---- system deps (ONE layer) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    libglib2.0-0 \
    build-essential \
    tzdata \
    wget \
    ffmpeg \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libgbm1 \
    gnupg \
    libportaudio2 \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# ---- chrome (ONE layer) ----
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/* *.deb

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

# ---- app code LAST ----
COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

RUN mkdir -p /app/out && chmod 777 /app/out

ENTRYPOINT ["/entrypoint.sh"]
