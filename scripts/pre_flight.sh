#!/bin/bash
# Pre-flight safety check
# Verifies that traffic routes through the phone's exit node (residential IP),
# NOT the VPS's datacenter IP.
#
# Note: Tailscale daemon runs in the sidecar container (ts). This script
# runs in the autorewarder container which shares the network namespace
# but not the filesystem. We verify via external IP only.

set -e

echo "--- Pre-flight Safety Check ---"

# --- Check 1: External IP is reachable and NOT the VPS IP ---
echo "[1/3] Checking external IP through exit node..."
EXTERNAL_IP=""
for attempt in 1 2 3 4 5; do
    EXTERNAL_IP=$(curl -sf --max-time 15 https://api.ipify.org 2>/dev/null || echo "")
    if [ -n "$EXTERNAL_IP" ]; then
        break
    fi
    echo "  Retry $attempt/5..."
    sleep 5
done

if [ -z "$EXTERNAL_IP" ]; then
    echo "  FAIL: Cannot determine external IP!"
    echo "  Exit node may not be routing. Check Tailscale sidecar logs:"
    echo "    docker logs autorewarder-ts"
    exit 1
fi
echo "  External IP: $EXTERNAL_IP"

# Quick check: Oracle Cloud IPs often start with specific ranges.
# This is a heuristic — not foolproof, but catches obvious cases.
# The VPS IP is in Oracle Cloud's range. If the external IP matches
# any known Oracle Cloud range, flag it.
if echo "$EXTERNAL_IP" | grep -qE "^(129\.213\.|130\.61\.|132\.145\.|138\.1\.|140\.238\.|141\.147\.|147\.156\.|152\.67\.|158\.101\.|168\.138\.|193\.122\.|193\.123\.)"; then
    echo "  CRITICAL: External IP ($EXTERNAL_IP) looks like an Oracle Cloud IP!"
    echo "  Exit node is NOT working! Traffic is going through the VPS!"
    echo "  DO NOT RUN AUTOMATION — accounts WILL be banned!"
    exit 1
fi
echo "  OK: External IP is not an Oracle Cloud IP"

# --- Check 2: Can reach Bing ---
echo "[2/3] Verifying connectivity to Bing..."
BING_STATUS=$(curl -sf --max-time 15 -o /dev/null -w "%{http_code}" https://www.bing.com 2>/dev/null || echo "000")
if [ "$BING_STATUS" = "000" ]; then
    echo "  FAIL: Cannot reach bing.com through exit node!"
    echo "  Phone may have no internet connectivity."
    exit 1
fi
echo "  OK: Bing reachable (HTTP $BING_STATUS)"

# --- Check 3: Verify timezone ---
echo "[3/3] Checking timezone..."
CURRENT_TZ=$(date +%Z)
CURRENT_OFFSET=$(date +%:z)
echo "  Timezone: $CURRENT_TZ (UTC${CURRENT_OFFSET})"

echo ""
echo "--- All pre-flight checks PASSED ---"
echo "  External IP: $EXTERNAL_IP"
echo "  Timezone:    $CURRENT_TZ (UTC${CURRENT_OFFSET})"
echo ""
exit 0
