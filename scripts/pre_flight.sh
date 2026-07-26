#!/bin/bash
# Pre-flight safety check
# Verifies that the Tailscale exit node is active and traffic routes through
# the phone (residential IP), NOT the VPS's datacenter IP.
#
# If this check fails, the container will NOT start automation.
# This is the #1 safety mechanism against Microsoft banning accounts.

set -e

echo "--- Pre-flight Safety Check ---"

# --- Check 1: Tailscale is running ---
echo "[1/4] Checking Tailscale status..."
if ! tailscale status > /dev/null 2>&1; then
    echo "  FAIL: Tailscale is not running or not connected!"
    echo "  Check TS_AUTHKEY and container networking."
    exit 1
fi
echo "  OK: Tailscale is connected"

# --- Check 2: Exit node is configured ---
echo "[2/4] Checking exit node configuration..."
EXIT_NODE=$(tailscale status --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    peer = data.get('Peer', {})
    self_id = data.get('Self', {}).get('ID', '')
    for pid, info in peer.items():
        if info.get('ExitNode', False):
            print(info.get('HostName', info.get('TailscaleIPs', ['unknown'])[0]))
            break
    else:
        print('NONE')
except:
    print('ERROR')
" 2>/dev/null || echo "ERROR")

if [ "$EXIT_NODE" = "NONE" ] || [ "$EXIT_NODE" = "ERROR" ]; then
    echo "  FAIL: No exit node configured!"
    echo "  Set PHONE_TS_IP in .env and restart."
    exit 1
fi
echo "  OK: Exit node active — routing through: $EXIT_NODE"

# --- Check 3: External IP is NOT the VPS IP ---
echo "[3/4] Verifying external IP is residential (not datacenter)..."
EXTERNAL_IP=$(curl -sf --max-time 10 https://api.ipify.org 2>/dev/null || echo "FAILED")

if [ "$EXTERNAL_IP" = "FAILED" ]; then
    echo "  FAIL: Could not determine external IP!"
    echo "  Exit node may not be routing correctly."
    exit 1
fi
echo "  External IP: $EXTERNAL_IP"

# Quick heuristic: datacenter IPs often belong to known cloud providers.
# This is a basic check — not foolproof, but catches obvious cases.
# Oracle Cloud IP ranges start with specific prefixes.
VPS_IP=$(curl -sf --max-time 5 http://169.254.169.254/opc/v2/vnics/ 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('publicIp',''))" 2>/dev/null || echo "")

if [ -n "$VPS_IP" ] && [ "$EXTERNAL_IP" = "$VPS_IP" ]; then
    echo "  CRITICAL FAIL: External IP matches VPS IP ($VPS_IP)!"
    echo "  Exit node is NOT working! Traffic is going through the VPS!"
    echo "  DO NOT RUN AUTOMATION — accounts WILL be banned!"
    exit 1
fi
echo "  OK: External IP is different from VPS IP"

# --- Check 4: Can reach Bing ---
echo "[4/4] Verifying connectivity to Bing..."
BING_STATUS=$(curl -sf --max-time 10 -o /dev/null -w "%{http_code}" https://www.bing.com 2>/dev/null || echo "000")
if [ "$BING_STATUS" = "000" ]; then
    echo "  FAIL: Cannot reach bing.com through exit node!"
    echo "  Phone may have no internet connectivity."
    exit 1
fi
echo "  OK: Bing reachable (HTTP $BING_STATUS)"

echo ""
echo "--- All pre-flight checks PASSED ---"
echo "  External IP: $EXTERNAL_IP"
echo "  Exit node:   $EXIT_NODE"
echo ""
exit 0
