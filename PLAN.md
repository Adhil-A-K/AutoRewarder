# AutoRewarder — VPS Deployment Plan

## Overview
Run AutoRewarder (Bing Rewards automation) on our ARM64 VPS inside Docker, routing
browser traffic through your Android phone via Tailscale exit node. Each account gets
a fresh mobile IP via the Automate app's HTTP API.

## Safety Principles (HIGHEST PRIORITY)
1. **NEVER** let an account session touch the VPS's datacenter IP — instant ban
2. All browser traffic MUST route through the phone exit node, no exceptions
3. Account timezone/locale must match your real location (India, UTC+5:30)
4. Human-like behavior — the repo already does this, we enhance it
5. Separate IP per account — rotate via airplane mode between accounts
6. Graceful failure — if exit node drops, STOP the run, don't fallback to VPS IP

## Architecture

```
┌─────────────────────── VPS (ARM64) ───────────────────────┐
│                                                            │
│  ┌─── Docker Network (isolated) ──────────────────────┐   │
│  │                                                     │   │
│  │  ┌──── ts (Tailscale sidecar) ────┐                │   │
│  │  │  - Tailscale daemon            │                │   │
│  │  │  - Exit node: phone            │                │   │
│  │  │  - Exposes VNC :5900           │                │   │
│  │  │  - network_mode: shared with   │                │   │
│  │  │    autorewarder container      │                │   │
│  │  └──────────────┬─────────────────┘                │   │
│  │                 │ network_mode: service:ts          │   │
│  │  ┌──── autorewarder ──────────────┐                │   │
│  │  │  - Brave Browser + chromedriver │                │   │
│  │  │  - Python 3 + AutoRewarder     │                │   │
│  │  │  - Xvfb (virtual display)      │                │   │
│  │  │  - x11vnc (for first login)    │                │   │
│  │  │  - Modified CLI with IP rotate │                │   │
│  │  └────────────────────────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                            │
│  Host traffic: NORMAL (VPS internet, unaffected)           │
└────────────────────────────┬───────────────────────────────┘
                             │ Tailscale tunnel (only container)
                             ▼
                  ┌─── Android Phone ───┐
                  │  Tailscale exit node │
                  │  Automate HTTP API   │
                  │  :9090/newip         │
                  │  :9090/status        │
                  │  Mobile data →       │
                  │  residential IP      │
                  └──────────────────────┘
```

## Implementation Progress

### Phase 1: Browser Migration (Edge → Brave) ✅ DONE
- [x] `src/emulator/driver.py` — Changed from `webdriver.Edge` to `webdriver.Chrome`
      with `options.binary_location = '/usr/bin/brave-browser'`
- [x] Added anti-detection: navigator.webdriver removal, disable-infobars, etc.
- [x] `src/config.py` — Updated profile path from `EdgeProfile/` to `BrowserProfile/`
- [x] `edge_policy.py` — Left as-is (already no-op on Linux)
- [x] `requirements.txt` — No changes needed (selenium already there)

### Phase 2: Docker Setup ✅ DONE
- [x] `Dockerfile` — Ubuntu 24.04, Brave, Python 3, Xvfb, x11vnc
- [x] `docker-compose.yml` — ts sidecar + autorewarder with network_mode
- [x] `scripts/entrypoint.sh` — Start Xvfb → VNC → pre-flight → run
- [x] `.env.example` — Template for required env vars
- [x] `.gitignore` — Added .env

### Phase 3: Tailscale Integration ✅ DONE (in Docker config)
- [x] Sidecar container (`tailscale/tailscale:latest`)
- [x] Exit node configured via `TS_EXTRA_ARGS`
- [x] VNC exposed through ts container's network

### Phase 4: IP Rotation ✅ DONE
- [x] `scripts/rotate_ip.sh` — Shell script for manual rotation
- [x] `AutoRewarder_CLI.py` — Added `rotate_ip()`, `verify_exit_node()` functions
- [x] CLI flags: `--no-rotate`, `--no-preflight`
- [x] Automatic rotation between account runs
- [x] Post-rotation verification (exit node still active)

### Phase 5: Safety Hardening ✅ DONE
- [x] Pre-flight check: verify exit node before any automation
- [x] VPS IP detection via cloud metadata
- [x] IP change verification after rotation
- [x] Abort if exit node fails mid-run
- [x] Per-account IP isolation via rotation

### Phase 6: First-Time Login (VNC) 🔲 PENDING (runtime)
- [ ] Build and start container
- [ ] Connect VNC from Windows PC
- [ ] Log into Microsoft accounts
- [ ] Test headless run

## What You Need To Do

1. **Create GitHub repo**: Go to github.com/new → name `AutoRewarder`, make it **private**
2. **Phone setup**:
   - Install Automate app
   - Create HTTP server flow on port 9090:
     - `GET /newip` → toggle airplane mode → return response
     - `GET /status` → return `{"ready": true/false, "ip": "x.x.x.x"}`
   - Enable phone as Tailscale exit node
3. **Tailscale admin**: Accept the phone's exit node at console.tailscale.com
4. **Generate auth key**: At console.tailscale.com/admin/settings/keys
   - Use ephemeral, single-use
5. **Fill .env**: Copy `.env.example` to `.env` and fill values

## Open Questions
- [ ] What's your phone's Tailscale IP? (needed for .env)
- [ ] Timezone for the container: Asia/Kolkata correct?
