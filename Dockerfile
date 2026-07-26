FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV BRAVE_BINARY=/usr/bin/brave-browser

# Locale and timezone — configurable via docker-compose build args.
# These MUST match the region of the phone's exit node IP.
# If browser Date() shows UTC while IP is Indian, Microsoft flags it.
ARG LOCALE_GEN=en_IN.UTF-8
ARG LOCALE=en_IN.UTF-8
ARG LANGUAGE_VAL=en_IN:en
ARG TZ=Asia/Kolkata

ENV LANG=${LOCALE}
ENV LC_ALL=${LOCALE}
ENV LANGUAGE=${LANGUAGE_VAL}
ENV TZ=${TZ}

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
    libasound2t64 libdbus-1-3 libudev1 libvulkan1 libexpat1 \
    # Process management
    procps \
    && rm -rf /var/lib/apt/lists/*

# Configure locale and timezone from build args
RUN sed -i "s/# ${LOCALE_GEN}/${LOCALE_GEN}/" /etc/locale.gen && \
    locale-gen ${LOCALE_GEN} && \
    ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime && \
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

# Data volume mount point (browser profiles, history, stats)
VOLUME ["/data"]

# VNC port (for first-time login)
EXPOSE 5900

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD pgrep -x Xvfb > /dev/null || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
