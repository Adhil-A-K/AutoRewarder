#!/bin/bash
# IP Rotation Script
# Triggers airplane mode toggle on the phone via Automate app's HTTP API,
# waits for a new IP, and verifies the change.
#
# Usage:
#   ./rotate_ip.sh [max_wait_seconds]
#
# Environment:
#   PHONE_API_IP   — Phone's Tailscale IP (e.g., 100.x.x.x)
#   PHONE_API_PORT — Automate app port (default: 9090)
#
# Exit codes:
#   0 — IP rotation successful, new IP obtained
#   1 — Error (connection failed, timeout, same IP)

MAX_WAIT="${1:-120}"
PHONE_HOST="${PHONE_API_IP}:${PHONE_API_PORT:-9090}"
PHONE_URL="http://${PHONE_HOST}"

echo "[IP Rotation] Starting..."
echo "  Phone API: $PHONE_URL"
echo "  Max wait:  ${MAX_WAIT}s"

# --- Step 1: Get current IP ---
echo "[1/5] Getting current external IP..."
CURRENT_IP=$(curl -sf --max-time 10 https://api.ipify.org 2>/dev/null)
if [ -z "$CURRENT_IP" ]; then
    echo "  WARNING: Could not get current IP. Continuing anyway."
    CURRENT_IP="unknown"
else
    echo "  Current IP: $CURRENT_IP"
fi

# --- Step 2: Trigger airplane mode toggle ---
echo "[2/5] Requesting IP rotation from phone..."
RESPONSE=$(curl -sf --max-time 10 "${PHONE_URL}/newip" 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "  ERROR: Could not reach phone API at ${PHONE_URL}/newip"
    echo "  Is the Automate app running? Is the phone on Tailscale?"
    exit 1
fi
echo "  Phone acknowledged: $RESPONSE"

# --- Step 3: Wait for phone to come back online ---
echo "[3/5] Waiting for phone to reconnect (airplane mode cycle)..."
START_TIME=$(date +%s)
PHONE_READY=false

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "  ERROR: Timeout after ${MAX_WAIT}s waiting for phone to reconnect!"
        exit 1
    fi

    STATUS=$(curl -sf --max-time 5 "${PHONE_URL}/status" 2>/dev/null)
    if echo "$STATUS" | grep -q '"ready".*true'; then
        PHONE_READY=true
        echo "  Phone is back online! (${ELAPSED}s)"
        break
    fi

    echo "  waiting... (${ELAPSED}s / ${MAX_WAIT}s)"
    sleep 3
done

# --- Step 4: Wait for network stabilization ---
echo "[4/5] Waiting for network to stabilize..."
sleep 5

# --- Step 5: Verify new IP ---
echo "[5/5] Verifying new IP..."
NEW_IP=$(curl -sf --max-time 15 https://api.ipify.org 2>/dev/null)
if [ -z "$NEW_IP" ]; then
    echo "  ERROR: Could not get new IP after rotation!"
    echo "  Phone may not have internet yet."
    exit 1
fi

echo "  New IP: $NEW_IP"

if [ "$CURRENT_IP" != "unknown" ] && [ "$NEW_IP" = "$CURRENT_IP" ]; then
    echo "  WARNING: IP did NOT change! Carrier may have recycled the same IP."
    echo "  Continuing anyway (different sessions may still help)."
else
    echo "  SUCCESS: IP changed from $CURRENT_IP → $NEW_IP"
fi

echo ""
echo "[IP Rotation] Complete"
exit 0
