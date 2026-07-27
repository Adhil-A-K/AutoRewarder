#!/usr/bin/env python3
"""
First-time account setup helper.
Creates an account and launches Brave for manual Microsoft login.

Usage:
    python3 setup_account.py [account_name]
    
Run this inside the Docker container via VNC terminal:
    docker compose exec autorewarder python3 /app/scripts/setup_account.py "MyAccount"
"""

import sys
import os
import subprocess
import time
import json

sys.path.insert(0, '/app')

from src.accounts import AccountManager, GlobalSettingsManager
from src.config import edge_profile_path, account_meta_path, ACCOUNTS_DIR

BRAVE_BINARY = os.environ.get("BRAVE_BINARY", "/usr/bin/brave-browser")
DATA_DIR = os.environ.get("HOME_DIR", "/data")


def create_account(name):
    """Create a new AutoRewarder account."""
    gs = GlobalSettingsManager()
    am = AccountManager(gs)
    
    acc = am.create(name)
    am.select(acc["id"])
    
    profile = edge_profile_path(acc["id"])
    os.makedirs(profile, exist_ok=True)
    
    print(f"Created account: {name} (id={acc['id']})")
    print(f"Profile path: {profile}")
    return acc


def launch_brave_for_login(account_id):
    """Launch Brave with the account's profile for manual login."""
    profile = edge_profile_path(account_id)
    
    print(f"\nLaunching Brave for manual login...")
    print(f"Profile: {profile}")
    print(f"")
    print(f"INSTRUCTIONS:")
    print(f"  1. Brave will open on this display")
    print(f"  2. Go to https://www.bing.com")
    print(f"  3. Click 'Sign in' and log into your Microsoft account")
    print(f"  4. Make sure you're fully logged in (see your points/profile)")
    print(f"  5. After login, come back here and press Enter")
    print(f"")
    print(f"  DO NOT close Brave — it needs to save the session!")
    print(f"")
    
    # Launch Brave with the account profile
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    
    proc = subprocess.Popen([
        BRAVE_BINARY,
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=AutomationControlled",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "https://www.bing.com",
    ], env=env)
    
    print(f"Brave launched (PID: {proc.pid})")
    print(f"Waiting for you to complete login...")
    
    input("\n>>> Press Enter here AFTER you've logged in successfully <<<\n")
    
    # Mark setup as done
    meta_path = account_meta_path(account_id)
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            meta = json.load(f)
    
    meta["first_setup_done"] = True
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=4)
    
    print(f"Account marked as setup complete!")
    print(f"")
    print(f"Brave is still running. You can close it now or it will be")
    print(f"automatically managed by AutoRewarder during runs.")
    print(f"")
    print(f"To test a run:")
    print(f"  python3 AutoRewarder_CLI.py --headless --account \"{name}\" --pc 3 --force")
    
    # Don't kill Brave — let it save the profile properly
    return proc.pid


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Default"
    
    print("=" * 50)
    print("  AutoRewarder — First-Time Account Setup")
    print("=" * 50)
    print()
    
    acc = create_account(name)
    launch_brave_for_login(acc["id"])
