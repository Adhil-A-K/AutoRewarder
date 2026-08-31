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
        # Handle of the Brave process launched by setup_driver. Stored so a
        # future close path can terminate it directly if Selenium quit fails.
        self._proc = None
        # Process group id of the launched browser tree (see terminate_browser).
        self._proc_pgid = None

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
            # GPU stays ENABLED (SwiftShader in the container) so Microsoft's
            # "browse 30 min" task tracks — upstream fix 9d8fb93. Do NOT add
            # --disable-gpu or --disable-software-rasterizer here: in the
            # container the "GPU" IS the software rasterizer, and disabling
            # either kills rendering and re-breaks task tracking.
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

        # Sweep orphaned Brave processes from dead runs BEFORE launching.
        # This is the single chokepoint every browser launch flows through
        # (GUI warmup, first-setup login, PC/mobile runs), so even a run
        # that died abnormally can never leak more than one generation of
        # browsers. Only orphans are killed — never a live browser owned by
        # a running process — so anti-detection is completely unaffected.
        self.close_running_browser()

        # Clean up stale profile locks AFTER the sweep (an orphan killed
        # here could otherwise recreate its SingletonLock after we removed
        # it). Locks from crashed/hung sessions would block the new launch.
        if self.profile_path:
            for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
                lock_path = os.path.join(self.profile_path, lock_name)
                try:
                    os.remove(lock_path)
                except FileNotFoundError:
                    pass

        _proc = subprocess.Popen(
            launch_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":99")},
            # New session = new process group. /usr/bin/brave-browser is a
            # bash wrapper, so the real browser is a CHILD of the wrapper;
            # killing the wrapper alone would orphan the browser. With its
            # own process group we can killpg the whole tree (wrapper +
            # brave + renderers) in terminate_browser().
            start_new_session=True,
        )
        self._proc = _proc
        self._proc_pgid = _proc.pid

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

        # Run anti-detection immediately on the current page context
        # (addScriptToEvaluateOnNewDocument only applies to FUTURE navigations)
        try:
            _driver.execute_script("""
                for (var key of Object.keys(document)) {
                    if (key.indexOf('cdc_') >= 0 || key.indexOf('$cdc_') >= 0) {
                        delete document[key];
                    }
                }
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
        except Exception:
            pass  # best-effort on initial context

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

    def terminate_browser(self):
        """
        Hard-terminate the browser process tree launched by the last
        setup_driver call, including the bash wrapper AND the real Brave
        binary plus all renderers (killpg on the process group).

        Why this exists: Selenium connects via debuggerAddress, so
        driver.quit() only disconnects the CDP client — it does NOT kill
        the browser process. Every run that relied on quit() alone leaked
        its browser (this caused the 279-proc / ~6GB accumulation). This
        method is the actual cleanup; call it after driver.quit() in
        finally blocks. Safe to call when nothing is running (no-op).
        """
        import signal
        import time as _time

        pgid = getattr(self, "_proc_pgid", None)
        self._proc = None
        self._proc_pgid = None
        if not pgid:
            return

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return  # already gone
        except PermissionError:
            return
        except OSError:
            return

        # Give the browser a moment to flush profile state, then SIGKILL
        # anything still alive in the group.
        _time.sleep(3)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            pass

    def close_running_browser(self):
        """
        Kill orphaned Brave/chromedriver processes left over from prior runs.

        When a run dies abnormally (VNC session killed, GUI closed, exception
        before driver.quit()), the Brave process it spawned is orphaned and
        keeps running — PID 1 can only reap zombies, it cannot kill live
        orphans. Without this, every dead run leaks one or more headless
        Brave instances (12 days of manual runs accumulated 250+ procs /
        ~6GB in the container).

        Safety model — anti-detection untouched, nothing leaves this host:
          * Only processes whose --user-data-dir matches THIS account's
            profile are considered, so other accounts / real browsers are
            never touched.
          * Only ORPHANS are killed: a process whose parent is gone or whose
            PPID chain leads to PID 1 (the container init). A browser owned
            by a live process — an active run, the visible first-setup
            login window — is never touched.
          * SIGTERM first (graceful, lets Brave flush profile state), then
            SIGKILL only if it survives the grace period.
        """
        import signal
        import time as _time

        profile = self.profile_path
        if not profile:
            return

        # Find candidate PIDs: Brave/chromedriver bound to our profile dir,
        # and build the PPID map in the same single pass. We match the
        # profile path with a literal substring check (not pgrep regex) so
        # paths containing regex metacharacters can never misfire, and we
        # never touch anything outside this account.
        import subprocess

        try:
            ps_out = subprocess.run(
                ["ps", "-eo", "pid=,ppid=,args="],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
        except Exception:
            return  # ps unavailable or failed — never block a launch

        ppid_map = {}
        python_pids = set()
        candidates = []
        for line in ps_out.splitlines():
            cols = line.strip().split(None, 2)
            if len(cols) < 3:
                continue
            try:
                pid = int(cols[0])
                ppid = int(cols[1])
            except ValueError:
                continue
            cmd = cols[2]
            ppid_map[pid] = ppid
            if "python" in cmd:
                python_pids.add(pid)
            if profile in cmd and ("brave" in cmd or "chromedriver" in cmd):
                candidates.append(pid)

        if not candidates:
            return

        # Decide orphan status by walking the PPID chain up to PID 1.
        # If every ancestor above us is also dead (PPID 1 at the top), it's
        # an orphan from a dead run. If any live python process owns it, the
        # browser is in active use and we leave it alone.
        def _is_orphan(pid):
            seen = set()
            cur = pid
            while cur in ppid_map and cur not in seen:
                seen.add(cur)
                cur = ppid_map[cur]
                if cur in python_pids:
                    return False  # owned by a live run / GUI / login window
                if cur == 1 or cur not in ppid_map:
                    # Chain dead-ended: either container init (PID 1) or the
                    # namespace boundary — docker top reports the init's
                    # host-side parent, which is invisible inside the
                    # container, so `cur not in ppid_map` is the boundary.
                    return True
            return False

        to_kill = [pid for pid in candidates if _is_orphan(pid)]
        if not to_kill:
            return

        _log = getattr(self, "log", None)
        if callable(_log):
            _log(f"Killing {len(to_kill)} orphaned Brave process(es) from previous runs")

        # SIGTERM → grace → SIGKILL
        for sig, grace in ((signal.SIGTERM, 3), (signal.SIGKILL, 0)):
            remaining = []
            for pid in to_kill:
                try:
                    os.kill(pid, sig)
                    remaining.append(pid)
                except ProcessLookupError:
                    pass  # already gone
                except PermissionError:
                    pass
            if sig == signal.SIGTERM and remaining:
                _time.sleep(grace)
            to_kill = remaining
