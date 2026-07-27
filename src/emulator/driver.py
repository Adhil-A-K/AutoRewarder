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

# ChromeDriver binary — must match Brave's Chromium version.
# On ARM64, Selenium Manager doesn't work, so we need an explicit path.
CHROMEDRIVER_BINARY = os.environ.get("CHROMEDRIVER_BINARY", "/usr/local/bin/chromedriver")


def _find_free_port():
    """Find a free TCP port for Chrome DevTools debugging."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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

    @staticmethod
    def _build_brave_args(options, debug_port):
        """Extract Chrome arguments from Options and add remote debugging."""
        args = []
        for arg in options.arguments:
            args.append(arg)
        args.append(f"--remote-debugging-port={debug_port}")
        return args

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

        # Locale & language — must match exit node region
        # Read from environment (set in .env → docker-compose.yml)
        # This affects navigator.language, Accept-Language header, and
        # Date formatting. Critical for avoiding timezone mismatch detection.
        browser_lang = os.environ.get("BROWSER_LANG", "en-IN")
        browser_accept = os.environ.get("BROWSER_ACCEPT_LANG", "en-IN,en;q=0.9")
        options.add_argument(f"--lang={browser_lang}")
        options.add_argument(f"--accept-lang={browser_accept}")

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
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-position=-32000,-32000")

        # On ARM64 Linux, chromedriver can't launch Brave directly (version
        # mismatch / sandbox issues). We launch Brave ourselves with
        # --remote-debugging-port, then connect Selenium via debuggerAddress.
        import subprocess
        import socket
        import time as _time

        debug_port = _find_free_port()
        launch_args = [BRAVE_BINARY] + self._build_brave_args(options, debug_port)

        _proc = subprocess.Popen(
            launch_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":99")},
        )

        # Wait for Brave's debug port to become available
        for _attempt in range(30):
            try:
                with socket.create_connection(("127.0.0.1", debug_port), timeout=1):
                    break
            except OSError:
                _time.sleep(0.5)
        else:
            raise RuntimeError(
                f"Brave did not open debug port {debug_port} within 15s"
            )

        # Connect Selenium to the running Brave instance
        connect_options = Options()
        connect_options.binary_location = BRAVE_BINARY
        connect_options.add_experimental_option(
            "debuggerAddress", f"127.0.0.1:{debug_port}"
        )
        _driver = webdriver.Chrome(
            service=Service(CHROMEDRIVER_BINARY),
            options=connect_options,
        )

        # Anti-detection: comprehensive stealth injection
        _driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    // 1. Remove webdriver flag
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    // 2. Remove CDP (ChromeDriver Protocol) detection markers
                    // ChromeDriver injects properties starting with 'cdc_' onto document.
                    // Websites check for these to detect automation.
                    for (let key of Object.keys(document)) {
                        if (key.startsWith('cdc_') || key.startsWith('$cdc_') || key.startsWith('__cdc_')) {
                            delete document[key];
                        }
                    }
                    // Prevent re-injection by making cdc_ properties non-configurable stubs
                    const cdpHandler = {
                        get: function(target, prop) {
                            if (typeof prop === 'string' && (prop.startsWith('cdc_') || prop.startsWith('$cdc_'))) {
                                return undefined;
                            }
                            return Reflect.get(target, prop);
                        }
                    };
                    
                    // 3. Fake media devices (speakers, mic, webcam)
                    // Real browsers always have at least audio devices.
                    // Server/headless environments report 0 which is suspicious.
                    const fakeDevices = [
                        { deviceId: '', groupId: '', kind: 'audioinput', label: '' },
                        { deviceId: '', groupId: '', kind: 'audiooutput', label: '' },
                        { deviceId: '', groupId: '', kind: 'videoinput', label: '' },
                    ];
                    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
                        navigator.mediaDevices.enumerateDevices = function() {
                            return Promise.resolve(fakeDevices);
                        };
                    }
                    
                    // 4. Fake permissions query for media devices
                    // When a site checks if microphone/camera permission is granted,
                    // a headless browser returns 'denied' which is suspicious.
                    if (navigator.permissions && navigator.permissions.query) {
                        const originalQuery = navigator.permissions.query.bind(navigator.permissions);
                        navigator.permissions.query = function(params) {
                            if (params.name === 'microphone' || params.name === 'camera') {
                                return Promise.resolve({ state: 'prompt', onchange: null });
                            }
                            return originalQuery(params);
                        };
                    }
                    
                    // 5. Ensure plugins array is not empty (headless has 0 plugins)
                    if (navigator.plugins.length === 0) {
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => {
                                const plugins = [
                                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                                    { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
                                ];
                                plugins.length = 3;
                                return plugins;
                            }
                        });
                    }
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
