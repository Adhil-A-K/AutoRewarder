"""Exit-node & IP-rotation safety primitives.

Shared by AutoRewarder_CLI.py (headless runner) and src/api.py (GUI path) so
every driver launch — headless OR headful — is gated on the same guarantee:
Microsoft must never see the VPS's datacenter IP.

verify_exit_node():
    Confirm traffic routes through the Tailscale exit node (the phone's home
    ISP) and NOT the VPS's own public IP. Reads the VPS IP from the Oracle
    cloud metadata endpoint and compares it against the external IP seen
    through the default route.

rotate_ip():
    Ask the phone's Automate HTTP API to toggle airplane mode, wait for the
    carrier to assign a new IP + Tailscale to reconnect, then verify.

Both functions accept an optional `logger` callable. The CLI passes its
timestamped console_log; library callers pass the API's log method. With no
logger, messages go to stdout.
"""

import os
import re
import time


def _get_vps_public_ip():
    """
    Determine the VPS's real public IP without going through the exit node.

    Tries, in order:
      1. Oracle metadata v2  (requires the 'Authorization: Bearer Oracle' header
         — without it the endpoint returns 403 and silently yields nothing)
      2. Oracle metadata v1  (headerless, still served on current images)
      3. VPS_PUBLIC_IP env   (manual override; comma-separated list allowed)

    Returns:
        set: candidate public IPs for this machine (empty if undeterminable).
    """
    candidates = set()

    import requests

    for url, headers in (
        ("http://169.254.169.254/opc/v2/vnics/", {"Authorization": "Bearer Oracle"}),
        ("http://169.254.169.254/opc/v1/vnics/", None),
    ):
        try:
            resp = requests.get(url, timeout=3, headers=headers)
            if resp.ok:
                vnics = resp.json()
                if isinstance(vnics, list):
                    for vnic in vnics:
                        ip = (vnic or {}).get("publicIp", "")
                        if ip:
                            candidates.add(ip)
                if candidates:
                    return candidates
        except Exception:
            pass

    # Manual override — useful on non-Oracle VPSes or hardened metadata.
    env_ips = os.environ.get("VPS_PUBLIC_IP", "")
    for ip in env_ips.split(","):
        ip = ip.strip()
        if ip:
            candidates.add(ip)

    return candidates


# Oracle Cloud public ranges (same heuristic as scripts/pre_flight.sh).
# Fail-closed backstop: if the external IP falls in ANY of these, the exit
# node is not doing its job, regardless of what metadata says.
_ORACLE_RANGE_RE = re.compile(
    r"^(129\.213\.|130\.61\.|132\.145\.|138\.1\.|140\.238\.|141\.147\.|"
    r"147\.156\.|152\.67\.|158\.101\.|168\.138\.|193\.122\.|193\.123\.)"
)


def verify_exit_node():
    """
    Verify that the Tailscale exit node is active and traffic routes through
    the phone, NOT the VPS's datacenter IP.

    Pure check — returns a result tuple; callers own the logging.

    Fails closed: if the external IP matches the VPS IP (metadata v2/v1 or
    VPS_PUBLIC_IP override) OR falls inside a known Oracle Cloud range, the
    check reports UNSAFE.

    Returns:
        tuple: (is_safe: bool, external_ip: str, message: str)
    """
    import requests

    # Get external IP through the exit node
    try:
        resp = requests.get("https://api.ipify.org", timeout=15)
        external_ip = resp.text.strip()
    except Exception as e:
        return (False, "unknown", f"Cannot determine external IP: {e}")

    if not external_ip:
        return (False, "unknown", "Empty response from ipify.org")

    if _ORACLE_RANGE_RE.match(external_ip):
        return (
            False,
            external_ip,
            f"CRITICAL: External IP ({external_ip}) is an Oracle Cloud IP! "
            f"Exit node is NOT working!",
        )

    vps_ips = _get_vps_public_ip()
    if external_ip in vps_ips:
        return (
            False,
            external_ip,
            f"CRITICAL: External IP ({external_ip}) matches VPS IP! "
            f"Exit node is NOT working!",
        )

    return (True, external_ip, f"Exit node active. External IP: {external_ip}")


def rotate_ip(logger=None):
    """
    Trigger IP rotation on the phone via the Automate app's HTTP API.

    The phone toggles airplane mode ON then OFF, which forces the carrier
    to assign a new dynamic IP.

    Args:
        logger: optional callable for progress messages (defaults to print).

    Returns:
        tuple: (success: bool, new_ip: str, message: str)
    """
    _log = logger if logger is not None else print

    import requests

    phone_ip = os.environ.get("PHONE_API_IP", "")
    phone_port = os.environ.get("PHONE_API_PORT", "9090")

    if not phone_ip:
        return (
            False,
            "unknown",
            "PHONE_API_IP not set. Cannot rotate IP.",
        )

    phone_url = f"http://{phone_ip}:{phone_port}"

    # Get current IP
    try:
        resp = requests.get("https://api.ipify.org", timeout=15)
        current_ip = resp.text.strip()
    except Exception:
        current_ip = "unknown"

    _log(f"[IP Rotation] Current IP: {current_ip}")
    _log(f"[IP Rotation] Triggering rotation via {phone_url}/newip...")

    # Trigger rotation — retry a few times in case the phone is on slow data
    triggered = False
    for attempt in range(3):
        try:
            resp = requests.get(f"{phone_url}/newip", timeout=15)
            if resp.ok:
                triggered = True
                _log(f"[IP Rotation] Phone acknowledged: {resp.text[:100]}")
                break
        except Exception:
            pass
        _log(f"[IP Rotation] Phone not responding, retry {attempt+1}/3...")
        time.sleep(5)

    if not triggered:
        return (False, current_ip, "Cannot reach phone API after 3 attempts")

    # Wait for phone to cycle through airplane mode.
    # Realistic timeline:
    #   0s   — airplane ON (radio disconnects)
    #   3s   — airplane OFF (radio starts reconnecting)
    #   8-15s — cellular data establishes
    #   15-30s — Tailscale reconnects
    #   20-40s — HTTP server reachable again
    # Total: 30-60s typical, up to 90s on slow carriers
    _log("[IP Rotation] Waiting for phone to reconnect (be patient)...")
    _log("[IP Rotation]   Phone needs: airplane cycle + data + Tailscale reconnect")
    max_wait = 180
    start = time.time()

    # Initial grace period — don't poll during airplane mode
    _log("[IP Rotation]   Initial grace period (20s)...")
    time.sleep(20)

    while True:
        elapsed = time.time() - start
        if elapsed >= max_wait:
            return (
                False,
                current_ip,
                f"Timeout after {max_wait}s waiting for phone",
            )

        try:
            resp = requests.get(f"{phone_url}/status", timeout=10)
            data = resp.json()
            if data.get("ready"):
                _log(
                    f"[IP Rotation] Phone back online ({elapsed:.0f}s)"
                )
                break
        except Exception:
            pass

        time.sleep(8)  # Longer intervals — don't hammer slow mobile data

    # Wait for network stabilization
    _log("[IP Rotation] Waiting for network to stabilize...")
    time.sleep(8)

    # Verify new IP — with retries
    new_ip = ""
    for attempt in range(5):
        try:
            resp = requests.get("https://api.ipify.org", timeout=20)
            new_ip = resp.text.strip()
            if new_ip:
                break
        except Exception:
            pass
        _log(f"[IP Rotation] Retry {attempt+1}/5 getting new IP...")
        time.sleep(5)

    if not new_ip:
        return (False, "unknown", "Cannot get new IP after 5 attempts")

    if new_ip == current_ip and current_ip != "unknown":
        _log(
            f"[IP Rotation] WARNING: IP unchanged ({new_ip}). "
            f"Carrier may have recycled the same IP."
        )
    else:
        _log(f"[IP Rotation] IP changed: {current_ip} → {new_ip}")

    return (True, new_ip, f"New IP: {new_ip}")
