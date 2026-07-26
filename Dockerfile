FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV BRAVE_BINARY=/usr/bin/brave-browser

# Timezone and locale — MUST match the phone's exit node region (India)
# This is critical: if the browser's JS Date() shows UTC while the IP is
# Indian, Microsoft can detect the mismatch and flag the account.
ENV TZ=Asia/Kolkata
ENV LANG=en_IN.UTF-8
ENV LC_ALL=en_IN.UTF-8
ENV LANGUAGE=en_IN:en

# System deps: Brave, Python, Xvfb, VNC, fonts, misc
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Brave browser deps
    curl wget gnupg2 ca-certificates \
    # Python
    python3 python3-pip python3-venv \
    # Virtual display + VNC
    xvfb x11vnc xauth \
    # Fonts (Brave needs these for rendering)
    fonts-liberation fonts-noto-color-emoji fonts-dejavu-core \
    # Locale + timezone
    locales tzdata \
    # X11 libs
    libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libxkbcommon0 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libgbm1 libgtk-3-0 libnss3 libnspr4 libpango-1.0-0 \
    libasound2 libdbus-1-3 libudev1 libvulkan1 libexpat1 \
    # Process management
    procps \
    && rm -rf /var/lib/apt/lists/*
# Configure locale and timezone
RUN sed -i 's/# en_IN.UTF-8/en_IN.UTF-8/' /etc/locale.gen && \
    locale-gen en_IN.UTF-8 && \
    ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Install Brave Browser (ARM64)
RUN curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg \
    https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] \
    https://brave-browser-apt-release.s3.brave.com/ stable main" \
    > /etc/apt/sources.list.d/brave-browser-release.list \
    && apt-get update \
    && apt-get install -y brave-browser \
    && rm -rf /var/lib/apt/lists/*

# Create venv and install Python deps
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy AutoRewarder source
WORKDIR /app
COPY src/ /app/src/
COPY assets/ /app/assets/
COPY datasets/ /app/datasets/
COPY gui/ /app/gui/
COPY AutoRewarder.py /app/
COPY AutoRewarder_CLI.py /app/

# Copy our custom scripts
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
COPY scripts/pre_flight.sh /app/scripts/pre_flight.sh
RUN chmod +x /app/scripts/*.sh

# Data volume mount point (Edge profiles, history, stats)
VOLUME ["/data"]

# VNC port (for first-time login)
EXPOSE 5900

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD pgrep -x Xvfb > /dev/null && pgrep -x brave-browser > /dev/null || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
