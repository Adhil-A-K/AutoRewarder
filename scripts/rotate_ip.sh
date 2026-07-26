#!/bin/bash
# IP Rotation Script — with patience for mobile data reconnection
#
# The airplane mode cycle takes time:
#   1. Toggle airplane ON (radio disconnects) — 2-5s
#   2. Toggle airplane OFF (radio reconnects) — 5-10s
#   3. Cellular data establishes — 5-15s
#   4. Tailscale reconnects — 5-20s
#   5. HTTP server reachable — 2-5s
#   Total realistic: 30-60s, can be up to 90s on slow carriers
#
# Usage:
#   ./rotate_ip.sh [max_wait_seconds]
#
# Exit codes:
#   0 — IP rotation successful
#   1 — Error (timeout, unreachable, same IP)

set -e

MAX_WAIT="${1:-180}"
PHONE_HOST="${PHONE_API_IP}:${PHONE_API_PORT:-9090}"
PHONE_URL="http://${PHONE_HOST}"

echo "[IP Rotation] Starting..."
echo "  Phone API: $PHONE_URL"
echo "  Max wait:  ${MAX_WAIT}s"

# --- Step 1: Get current IP (with retries) ---
echo "[1/5] Getting current external IP..."
CURRENT_IP=""
for attempt in 1 2 3; do
    CURRENT_IP=$(curl -sf --max-time 15 https://api.ipify.org 2>/dev/null || echo "")
    if [ -n "$CURRENT_IP" ]; then
        break
    fi
    echo "  Retry $attempt/3..."
    sleep 3
done

if [ -z "$CURRENT_IP" ]; then
    echo "  WARNING: Could not get current IP. Continuing anyway."
    CURRENT_IP="unknown"
else
    echo "  Current IP: $CURRENT_IP"
fi

# --- Step 2: Trigger airplane mode toggle ---
echo "[2/5] Requesting IP rotation from phone..."
# Retry connecting to phone — it might be on slow mobile data
RESPONSE=""
for attempt in 1 2 3; do
    RESPONSE=$(curl -sf --max-time 15 "${PHONE_URL}/newip" 2>/dev/null || echo "")
    if [ -n "$RESPONSE" ]; then
        break
    fi
    echo "  Phone not responding, retry $attempt/3..."
    sleep 5
done

if [ -z "$RESPONSE" ]; then
    echo "  ERROR: Could not reach phone API at ${PHONE_URL}/newip"
    echo "  Is the Automate app running? Is the phone on Tailscale?"
    exit 1
fi
echo "  Phone acknowledged: $RESPONSE"

# --- Step 3: Wait for phone to come back online ---
# This is the LONGEST step — phone needs to:
# - Toggle airplane OFF → radio reconnects → data establishes → Tailscale connects
echo "[3/5] Waiting for phone to reconnect (be patient, mobile data is slow)..."
START_TIME=$(date +%s)
PHONE_READY=false

# Initial grace period — don't even try polling for the first 20s
# because the phone is definitely still in airplane mode
echo "  Initial grace period (20s)..."
sleep 20

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "  ERROR: Timeout after ${MAX_WAIT}s waiting for phone to reconnect!"
        echo "  The phone may be on a slow carrier or airplane mode failed."
        exit 1
    fi

    # Use longer timeout for phone API calls — it's over mobile data
    STATUS=$(curl -sf --max-time 10 "${PHONE_URL}/status" 2>/dev/null || echo "")
    if echo "$STATUS" | grep -q '"ready".*true\|"ready":\s*true'; then
        PHONE_READY=true
        echo "  Phone is back online! (${ELAPSED}s)"
        break
    fi

    # Show progress with longer intervals to reduce log spam
    REMAINING=$(( MAX_WAIT - ELAPSED ))
    echo "  still waiting... (${ELAPSED}s elapsed, ${REMAINING}s remaining)"
    sleep 8
done

# --- Step 4: Wait for network stabilization ---
# Even after phone reports ready, the connection might be flaky
echo "[4/5] Waiting for network to stabilize..."
sleep 8

# --- Step 5: Verify new IP (with retries) ---
echo "[5/5] Verifying new IP..."
NEW_IP=""
for attempt in 1 2 3 4 5; do
    NEW_IP=$(curl -sf --max-time 20 https://api.ipify.org 2>/dev/null || echo "")
    if [ -n "$NEW_IP" ]; then
        break
    fi
    echo "  Retry $attempt/5 getting new IP..."
    sleep 5
done

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
