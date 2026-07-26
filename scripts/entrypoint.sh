#!/bin/bash
set -e

echo "========================================="
echo "  AutoRewarder — Container Entrypoint"
echo "========================================="

# --- Virtual Display ---
echo "[1/4] Starting virtual display (Xvfb)..."
# Clean up stale lock files from previous container runs
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
sleep 1

# Verify Xvfb started
if ! pgrep -x Xvfb > /dev/null; then
    echo "ERROR: Xvfb failed to start!"
    exit 1
fi
echo "  Xvfb running on :99"

# --- VNC Server ---
echo "[2/4] Starting VNC server..."
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -bg -o /tmp/x11vnc.log
sleep 1
echo "  VNC available on port 5900"

# --- Pre-flight Safety Check ---
echo "[3/4] Running pre-flight safety check..."
if [ -f /app/scripts/pre_flight.sh ]; then
    /app/scripts/pre_flight.sh
    if [ $? -ne 0 ]; then
        echo "FATAL: Pre-flight check failed! Not starting automation."
        echo "Fix the issue and restart the container."
        # Keep container alive for debugging but don't run automation
        tail -f /dev/null
        exit 1
    fi
else
    echo "  WARNING: pre_flight.sh not found, skipping safety check"
fi

# --- Data Directory ---
echo "[4/4] Setting up data directory..."
export AUTOREWARDER_DATA_DIR="${HOME_DIR:-/data}"
mkdir -p "$AUTOREWARDER_DATA_DIR"
echo "  Data dir: $AUTOREWARDER_DATA_DIR"

echo "========================================="
echo "  Ready! Starting AutoRewarder..."
echo "========================================="
echo ""
echo "  VNC:     Connect to <vps-tailscale-ip>:5900"
echo "  CLI:     docker compose exec autorewarder python3 AutoRewarder_CLI.py --headless"
echo "  Logs:    docker compose logs -f autorewarder"
echo ""

# If a command was passed, run it; otherwise keep container alive
if [ $# -gt 0 ]; then
    exec "$@"
else
    # Default: keep container running for manual CLI use
    echo "Container is idle. Use 'docker compose exec' to run commands."
    echo "Or attach to see logs: docker compose logs -f"
    tail -f /dev/null
fi
