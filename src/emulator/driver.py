"""
Brave WebDriver setup for per-account profiles.

Migrated from Edge to Brave (Chromium-based) for ARM64 Linux compatibility.
Brave provides built-in anti-fingerprinting (canvas/WebGL randomization per
session) which adds an extra layer of safety for bot detection evasion.
"""

import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# Brave binary location — can be overridden via environment variable.
BRAVE_BINARY = os.environ.get("BRAVE_BINARY", "/usr/bin/brave-browser")


class DriverManager:
    """
    Manages the Selenium WebDriver for Brave Browser.

    Each DriverManager instance is bound to a specific --user-data-dir
    (i.e. one account). Switching account = rebuilding this manager with a
    different profile_path.
    """

    def __init__(self, profile_path=None, hide_browser=False):
        """
        Args:
            profile_path (str | None): Absolute path to the Selenium --user-data-dir
                directory. None when no account is selected (empty state). In that
                case setup_driver will raise, since there is nothing to launch.
            hide_browser (bool): Whether to run the browser in headless mode.
        """
        self.profile_path = profile_path
        self.hide_browser = hide_browser

    # Realistic iPhone UA so Microsoft Rewards credits the searches as mobile.
    MOBILE_USER_AGENT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 "
        "Mobile/15E148 Safari/604.1"
    )
    MOBILE_WINDOW_SIZE = "412,915"
    DESKTOP_WINDOW_SIZE = "1920,1080"

    def setup_driver(self, headless=None, disable_identity=False, mobile=False):
        """
        Set up the Selenium WebDriver for Brave Browser using this manager's profile.

        Args:
            headless: Headless override. Falls back to self.hide_browser.
            disable_identity: Kept for API compatibility. On Linux/Brave this
                is a no-op (the flags were Windows Edge-specific).
            mobile: When True, launch Brave with an iPhone user agent and a
                mobile-sized viewport so Rewards credits the searches as
                mobile. When False, use the desktop viewport.

        Returns:
            webdriver.Chrome: The configured WebDriver instance.

        Raises:
            RuntimeError: If profile_path is None (no account selected).
        """
        if not self.profile_path:
            raise RuntimeError(
                "No account selected: cannot start the browser. "
                "Create or select an account first."
            )

        if headless is None:
            headless = self.hide_browser

        options = Options()

        # Brave binary
        options.binary_location = BRAVE_BINARY

        # Per-account isolated profile
        options.add_argument(f"--user-data-dir={self.profile_path}")
        options.add_argument("--profile-directory=Default")

        # Anti-detection flags
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-infobars")  # "Chrome is being controlled" bar
        options.add_argument("--disable-extensions")  # avoid extension interference
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # VPS/Docker specific
        options.add_argument("--no-sandbox")  # Required in Docker
        options.add_argument("--disable-dev-shm-usage")  # Overcome limited /dev/shm

        # Locale & language — must match exit node region (India)
        # This affects navigator.language, Accept-Language header, and
        # Date formatting. Critical for avoiding timezone mismatch detection.
        options.add_argument("--lang=en-IN")
        options.add_argument("--accept-lang=en-IN,en;q=0.9")

        if mobile:
            options.add_argument(f"--user-agent={self.MOBILE_USER_AGENT}")
            window_size = self.MOBILE_WINDOW_SIZE
        else:
            window_size = self.DESKTOP_WINDOW_SIZE
        options.add_argument(f"--window-size={window_size}")

        # disable_identity was Windows Edge-specific; kept as no-op for
        # backward compatibility with callers.

        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")

        _driver = webdriver.Chrome(options=options)

        # Anti-detection: remove webdriver flag from navigator
        _driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """
            },
        )

        if mobile:
            # Turn the session into a genuine mobile one at the engine level.
            # Beyond the UA string, this makes `navigator.maxTouchPoints > 0`,
            # `window.matchMedia("(pointer: coarse)")` true, the viewport match
            # iPhone metrics, and touch events fire for real — so sites that
            # fingerprint using the DOM/CSS touch surface see a real mobile.
            try:
                _driver.execute_cdp_cmd(
                    "Emulation.setTouchEmulationEnabled",
                    {"enabled": True, "maxTouchPoints": 5},
                )
                _driver.execute_cdp_cmd(
                    "Emulation.setEmitTouchEventsForMouse",
                    {"enabled": True, "configuration": "mobile"},
                )
                _driver.execute_cdp_cmd(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": 412,
                        "height": 915,
                        "deviceScaleFactor": 3,
                        "mobile": True,
                    },
                )
                _driver.execute_cdp_cmd(
                    "Emulation.setUserAgentOverride",
                    {
                        "userAgent": self.MOBILE_USER_AGENT,
                        "platform": "iPhone",
                        "userAgentMetadata": {
                            "platform": "iOS",
                            "platformVersion": "17.2.1",
                            "architecture": "",
                            "model": "iPhone",
                            "mobile": True,
                        },
                    },
                )
            except Exception:
                # CDP is best-effort; fall back to the UA+window-size flags.
                pass

        return _driver

    def close_running_browser(self):
        """
        Close running Brave processes to avoid conflicts with the Selenium profile.
        Kept as a no-op for backward compatibility; per-account profiles make this
        generally unnecessary.
        """
        return
