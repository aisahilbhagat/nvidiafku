#!/usr/bin/env python3
"""
cli.py — Master Interactive TUI & Orchestrator for NVIDIAFKU Engine
===================================================================
Connects:
  1. nvidia_rp_cleaner.py  (Core Engine, Token Counters, API Key Store, Logs)
  2. server.py             (Dual-Stack HTTP Port 5000 + HTTPS & LAN Server Port 8443)
  3. roleplay.py           (Roleplay Mode & Professional Mode Controller)
  4. model_switch.py       (Dynamic Model Catalog & Switcher)

Features:
  - Neon Green & Red Glitch-Animated Title ("NVIDIAFKU by ai_sahil_")
  - First-Launch Default Mode Wizard (persisted in `cli_preferences.json`)
  - Auto-starts Dual-Stack HTTP/HTTPS & LAN Server in background with clean log capture
  - Auto-generates & updates `.env` for `NVIDIA_API_KEY` + live NVIDIA API verification
  - Claude Code / OpenCode style arrow-key & numeric keyboard navigation
  - Live Connection Mode dashboard with Test URLs & real-time engine generation logs
"""

import os
import re
import sys
import json
import time
import random
import threading
from collections import deque
from datetime import datetime

# Enable ANSI escape sequences on Windows/Termux/Linux
os.system("")

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

import requests

# Connect all 4 modules together
import nvidia_rp_cleaner as core_module
from nvidia_rp_cleaner import (
    app,
    engine,
    is_valid_nvapi_key,
    NVIDIA_BASE_URL,
    TermColors,
)
import server as server_module
import roleplay as roleplay_module
import model_switch as model_switch_module


# =====================================================================
# ✏️ USER EDITABLE API KEY INSTRUCTIONS (Shown in Option 1: Add API)
# =====================================================================
# Edit the text inside the list below however you want!
# The CLI will automatically style and wrap this inside a sleek neon box
# right underneath the API Key input field.
API_KEY_INSTRUCTIONS = [
    "1. Visit https://build.nvidia.com and sign in or create a free account.",
    "2. Click on any model (e.g., 'nemotron-3.5-super-vl-120b-a12b') -> 'Get API Key'.",
    "3. Click 'Generate Key' and copy your key starting with 'nvapi-...'.",
    "4. Paste the key above and press [Enter] — we will verify & save it to .env!",
]

PREFERENCES_FILE = os.path.abspath("cli_preferences.json")
ENV_FILE = os.path.abspath(".env")


# =====================================================================
# NEON CYBERPUNK / CLAUDE-CODE STYLE ANSI PALETTE
# =====================================================================
class UI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # TrueColor / 256-color Neon Accents
    NEON_GREEN = "\033[38;5;46m"       # Electric Matrix Green
    SOFT_GREEN = "\033[38;5;83m"       # Mint Success Green
    NEON_RED = "\033[38;5;196m"        # Pure Neon Red
    CRIMSON_RED = "\033[38;5;160m"     # Deep Red
    CYBER_CYAN = "\033[38;5;51m"       # Bright Cyan
    SLATE_BLUE = "\033[38;5;75m"       # Claude Code Accent Blue
    AMBER_GOLD = "\033[38;5;214m"      # Warning / Highlight Gold
    PURPLE_GLOW = "\033[38;5;141m"     # Lavender / Model badge
    WHITE = "\033[97m"
    GRAY = "\033[38;5;244m"
    DARK_GRAY = "\033[38;5;238m"

    # Background Highlights for Active Menu Selection
    BG_SELECT = "\033[48;5;236m"
    BG_GREEN_BADGE = "\033[48;5;22m\033[38;5;46m"
    BG_RED_BADGE = "\033[48;5;52m\033[38;5;196m"

    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    CLEAR_SCREEN = "\033[2J\033[H"


def strip_ansi(text: str) -> str:
    """Removes ANSI escape codes to measure exact visible character width."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", str(text))


def visible_len(text: str) -> int:
    return len(strip_ansi(text))


def get_term_width(default=82) -> int:
    try:
        cols = os.get_terminal_size().columns
        return max(64, min(cols - 2, 96))
    except Exception:
        return default


# =====================================================================
# CROSS-PLATFORM KEYBOARD NAVIGATION (Windows msvcrt + Linux/Termux/macOS tty)
# =====================================================================
def read_key():
    """
    Reads a single keypress without requiring Enter.
    Returns: 'UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'ESC', 'BACKSPACE', or character.
    """
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == "\x1b":
            return "ESC"
        if ch == "\x08":
            return "BACKSPACE"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            mapping = {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT"}
            return mapping.get(ch2, "")
        return ch
    else:
        import tty
        import termios
        import select
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch in ("\x7f", "\x08"):
                return "BACKSPACE"
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x1b":
                rlist, _, _ = select.select([sys.stdin], [], [], 0.04)
                if rlist:
                    seq = sys.stdin.read(2)
                    if seq == "[A":
                        return "UP"
                    if seq == "[B":
                        return "DOWN"
                    if seq == "[C":
                        return "RIGHT"
                    if seq == "[D":
                        return "LEFT"
                return "ESC"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# =====================================================================
# PERSISTENT CONFIGURATION (.env & cli_preferences.json)
# =====================================================================
class ConfigStore:
    """
    Manages:
      1. `cli_preferences.json` -> stores `default_mode` ("roleplay" or "professional")
      2. `.env`                 -> stores `NVIDIA_API_KEY=nvapi-...`
    """
    def __init__(self):
        self.lock = threading.RLock()
        self.api_verified = False
        self.api_status_msg = "Not Configured"
        self.last_verified_key = ""

    def load_preferences(self) -> dict:
        if not os.path.exists(PREFERENCES_FILE):
            return {}
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_preferences(self, updates: dict) -> dict:
        with self.lock:
            current = self.load_preferences()
            current.update(updates)
            try:
                with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
                    json.dump(current, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
            return current

    def get_saved_default_mode(self):
        prefs = self.load_preferences()
        mode = prefs.get("default_mode", "")
        if mode in ("roleplay", "professional"):
            return mode
        return None

    def set_saved_default_mode(self, mode: str):
        if mode in ("roleplay", "professional"):
            self.save_preferences({"default_mode": mode, "updated_at": datetime.now().isoformat()})

    def load_env_api_key(self) -> str:
        """Reads NVIDIA_API_KEY from `.env` if present and injects into engine."""
        if not os.path.exists(ENV_FILE):
            self._write_env_file("")
            engine.api_keys["hardcoded"] = ""
            return ""

        found_key = ""
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if not line_s or line_s.startswith("#"):
                        continue
                    if line_s.startswith("NVIDIA_API_KEY="):
                        val = line_s.split("=", 1)[1].strip().strip('"').strip("'")
                        found_key = val
                        break
        except Exception:
            pass

        engine.api_keys["hardcoded"] = ""
        engine.api_keys["env"] = found_key
        engine.api_keys["runtime_override"] = found_key
        os.environ["NVIDIA_API_KEY"] = found_key
        return found_key

    def save_env_api_key(self, new_key: str):
        """Saves `NVIDIA_API_KEY` into `.env` and updates the running engine."""
        clean_key = (new_key or "").strip()
        self._write_env_file(clean_key)
        os.environ["NVIDIA_API_KEY"] = clean_key
        engine.api_keys["runtime_override"] = clean_key
        engine.api_keys["env"] = clean_key
        engine.api_keys["hardcoded"] = clean_key

    def _write_env_file(self, api_key: str):
        lines = []
        key_written = False
        if os.path.exists(ENV_FILE):
            try:
                with open(ENV_FILE, "r", encoding="utf-8") as f:
                    for raw_l in f:
                        if raw_l.strip().startswith("NVIDIA_API_KEY="):
                            lines.append(f'NVIDIA_API_KEY="{api_key}"\n')
                            key_written = True
                        else:
                            lines.append(raw_l)
            except Exception:
                lines = []

        if not key_written:
            if not lines:
                lines.append("# Auto-generated by NVIDIAFKU CLI (by ai_sahil_)\n")
            lines.append(f'NVIDIA_API_KEY="{api_key}"\n')

        try:
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:
            pass

    def verify_api_key_with_nvidia(self, candidate_key: str) -> tuple:
        """
        Tests whether `candidate_key`:
          1. Matches NVIDIA's `nvapi-...` format
          2. Authenticates cleanly against NVIDIA's live API
        Returns (is_valid: bool, message: str)
        """
        clean_key = (candidate_key or "").strip()
        if not clean_key:
            self.api_verified = False
            self.api_status_msg = "No API Key Set"
            return False, "API Key is empty."

        if not is_valid_nvapi_key(clean_key):
            self.api_verified = False
            self.api_status_msg = "Invalid Format (Must start with 'nvapi-')"
            return False, "Format invalid: NVIDIA API keys must start with 'nvapi-' and be >20 chars."

        headers = {
            "Authorization": f"Bearer {clean_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            probe_payload = {
                "model": engine.config.get("active_model"),
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "stream": False,
            }
            resp = requests.post(
                f"{NVIDIA_BASE_URL}/chat/completions",
                headers=headers,
                json=probe_payload,
                timeout=10,
            )
            if resp.status_code in (401, 403):
                self.api_verified = False
                self.api_status_msg = f"Rejected by NVIDIA (HTTP {resp.status_code})"
                return False, f"Authentication failed (HTTP {resp.status_code}): Invalid or expired NVIDIA API key."
            elif resp.status_code in (200, 400, 404, 422, 429):
                self.api_verified = True
                self.last_verified_key = clean_key
                self.api_status_msg = "Verified & Active"
                return True, "API Key verified with NVIDIA NIM servers and saved to .env!"
            else:
                m_resp = requests.get(f"{NVIDIA_BASE_URL}/models", headers=headers, timeout=6)
                if m_resp.status_code == 200:
                    self.api_verified = True
                    self.last_verified_key = clean_key
                    self.api_status_msg = "Verified & Active"
                    return True, "API Key verified against NVIDIA /v1/models and saved to .env!"
                self.api_verified = False
                self.api_status_msg = f"Unexpected HTTP {resp.status_code}"
                return False, f"NVIDIA returned HTTP {resp.status_code}."
        except requests.exceptions.RequestException as e:
            self.api_verified = True
            self.last_verified_key = clean_key
            self.api_status_msg = "Format Valid (Offline Mode)"
            return True, f"Format valid & saved to .env! (Could not ping NVIDIA right now: {type(e).__name__})"


config_store = ConfigStore()


# =====================================================================
# LIVE GENERATION LOG RING-BUFFER (For Option 4: Connection Mode)
# =====================================================================
LIVE_LOG_BUFFER = deque(maxlen=50)
LIVE_VIEW_ACTIVE = False
_original_log_generation_event = core_module.log_generation_event


def _cli_hooked_log_generation_event(model_name, generated_ok, output_tokens, total_tokens, error_detail=None):
    """
    Captures every generation event from `nvidia_rp_cleaner.py` into `LIVE_LOG_BUFFER`
    so the user never gets random text printed over their main menu, AND streams it
    live in real-time when the user is inside Option 4 (Connection Mode)!
    """
    now_str = datetime.now().strftime("%H:%M:%S")
    c = TermColors
    if generated_ok:
        status_badge = f"{c.BOLD}{c.GREEN}✅ GENERATED{c.RESET}"
    else:
        reason = f" ({error_detail})" if error_detail else ""
        status_badge = f"{c.BOLD}{c.RED}❌ FAILED{reason}{c.RESET}"

    formatted_line = (
        f"{c.DIM}[{now_str}]{c.RESET} "
        f"{c.BOLD}{c.MAGENTA}🤖 {model_name}{c.RESET} "
        f"{c.DIM}|{c.RESET} {status_badge} "
        f"{c.DIM}|{c.RESET} {c.CYAN}📝 Out: {c.BOLD}{output_tokens}{c.RESET}{c.CYAN} tok{c.RESET} "
        f"{c.DIM}|{c.RESET} {c.YELLOW}📊 Total: {c.BOLD}{total_tokens}{c.RESET}{c.YELLOW} tok{c.RESET}"
    )
    LIVE_LOG_BUFFER.append(formatted_line)


# Attach log interceptor onto nvidia_rp_cleaner
core_module.log_generation_event = _cli_hooked_log_generation_event


# =====================================================================
# NEON GREEN & RED GLITCH ANIMATION BANNER ("NVIDIAFKU by ai_sahil_")
# =====================================================================
ASCII_NVIDIAFKU = [
    " ███╗   ██╗██╗   ██╗██╗██████╗ ██╗ █████╗ ███████╗██╗  ██╗██╗   ██╗",
    " ████╗  ██║██║   ██║██║██╔══██╗██║██╔══██╗██╔════╝██║ ██╔╝██║   ██║",
    " ██╔██╗ ██║██║   ██║██║██║  ██║██║███████║█████╗  █████╔╝ ██║   ██║",
    " ██║╚██╗██║╚██╗ ██╔╝██║██║  ██║██║██╔══██║██╔══╝  ██╔═██╗ ██║   ██║",
    " ██║ ╚████║ ╚████╔╝ ██║██████╔╝██║██║  ██║██║     ██║  ██╗╚██████╔╝",
    " ╚═╝  ╚═══╝  ╚═══╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝ ╚═════╝ ",
]

GLITCH_CHARS = ["#", "%", "&", "@", "$", "X", "0", "1", "▒", "▓", "█", "░", "/", "\\", "!", "?"]


def play_startup_glitch_animation(duration=1.65):
    """
    Plays a high-framerate cyberpunk Neon Green & Neon Red glitch materialization
    animation for 'NVIDIAFKU by ai_sahil_' when the CLI launches.
    """
    sys.stdout.write(UI.HIDE_CURSOR + UI.CLEAR_SCREEN)
    sys.stdout.flush()

    frames = 22
    frame_delay = duration / frames

    for step in range(frames + 1):
        progress = step / frames
        sys.stdout.write("\033[H")
        lines_out = ["\n"]

        for row_idx, line in enumerate(ASCII_NVIDIAFKU):
            rendered_row = []
            jitter = ""
            if progress < 0.75 and random.random() < 0.35:
                jitter = " " * random.randint(1, 3)

            for col_idx, ch in enumerate(line):
                if ch == " ":
                    rendered_row.append(" ")
                    continue

                lock_threshold = (col_idx / max(1, len(line))) * 0.75 + (row_idx * 0.03)
                if progress >= lock_threshold or step == frames:
                    if step < frames and random.random() < 0.08:
                        spark_color = UI.NEON_RED if col_idx < 42 else UI.NEON_GREEN
                        rendered_row.append(f"{UI.BOLD}{spark_color}{ch}{UI.RESET}")
                    else:
                        base_color = UI.NEON_GREEN if col_idx < 42 else UI.NEON_RED
                        rendered_row.append(f"{UI.BOLD}{base_color}{ch}{UI.RESET}")
                else:
                    g_char = random.choice(GLITCH_CHARS)
                    g_col = UI.NEON_RED if random.random() < 0.5 else UI.NEON_GREEN
                    rendered_row.append(f"{g_col}{g_char}{UI.RESET}")

            lines_out.append(jitter + "".join(rendered_row))

        if step < frames:
            sub_glitch = "".join(
                c if random.random() < progress else random.choice(GLITCH_CHARS)
                for c in "NVIDIAFKU by ai_sahil_"
            )
            sub_col = UI.NEON_RED if step % 2 == 0 else UI.NEON_GREEN
            lines_out.append(
                f"\n   {UI.BOLD}{sub_col}⚡ {sub_glitch} ⚡{UI.RESET}   "
                f"{UI.DIM}{UI.GRAY}[INITIALIZING NEURAL ENGINE...]{UI.RESET}"
            )
        else:
            lines_out.append(
                f"\n   {UI.BOLD}{UI.NEON_GREEN}⚡ NVIDIA{UI.NEON_RED}FKU{UI.RESET} "
                f"{UI.BOLD}{UI.NEON_RED}by {UI.NEON_GREEN}ai_sahil_{UI.RESET} "
                f"{UI.DIM}{UI.GRAY}— Universal NVIDIA NIM Dual-Stack HTTP/HTTPS & LAN Engine{UI.RESET}      "
            )

        sys.stdout.write("\n".join(lines_out) + "\n")
        sys.stdout.flush()
        time.sleep(frame_delay)


def render_static_header(glitch_variant=0) -> str:
    """
    Renders the top 'NVIDIAFKU by ai_sahil_' header in Neon Green & Red with subtle
    cyberpunk glitch styling and the Localhost / LAN URLs immediately below it.
    """
    w = get_term_width()
    out = []

    border_bar = "═" * (w - 2)
    out.append(f"{UI.NEON_GREEN}╔{border_bar}╗{UI.RESET}")

    if w >= 74:
        for row_idx, line in enumerate(ASCII_NVIDIAFKU):
            colored_chars = []
            for col_idx, ch in enumerate(line):
                if ch == " ":
                    colored_chars.append(" ")
                else:
                    if glitch_variant > 0 and random.random() < 0.025:
                        c_code = UI.NEON_RED if col_idx < 42 else UI.NEON_GREEN
                    else:
                        c_code = UI.NEON_GREEN if col_idx < 42 else UI.NEON_RED
                    colored_chars.append(f"{UI.BOLD}{c_code}{ch}{UI.RESET}")
            row_str = "".join(colored_chars)
            pad = max(0, (w - 2) - visible_len(row_str))
            out.append(f"{UI.NEON_GREEN}║{UI.RESET}{row_str}{' ' * pad}{UI.NEON_RED}║{UI.RESET}")
    else:
        title_line = (
            f"  {UI.BOLD}{UI.NEON_GREEN}▓▒░ NVIDIA{UI.NEON_RED}FKU "
            f"{UI.NEON_GREEN}by {UI.NEON_RED}ai_sahil_ ░▒▓{UI.RESET}"
        )
        pad = max(0, (w - 2) - visible_len(title_line))
        out.append(f"{UI.NEON_GREEN}║{UI.RESET}{title_line}{' ' * pad}{UI.NEON_RED}║{UI.RESET}")

    sig_left = (
        f"  {UI.BOLD}{UI.NEON_GREEN}⚡ NVIDIA{UI.NEON_RED}FKU{UI.RESET} "
        f"{UI.BOLD}{UI.NEON_RED}by {UI.NEON_GREEN}ai_sahil_{UI.RESET}"
    )
    active_mode = roleplay_module.get_mode().upper()
    mode_color = UI.NEON_GREEN if active_mode == "ROLEPLAY" else (UI.CYBER_CYAN if active_mode == "PROFESSIONAL" else UI.AMBER_GOLD)
    sig_right = f"{UI.DIM}MODE:{UI.RESET} {UI.BOLD}{mode_color}[{active_mode}]{UI.RESET}  "
    space_between = max(1, (w - 2) - visible_len(sig_left) - visible_len(sig_right))
    out.append(f"{UI.NEON_GREEN}║{UI.RESET}{sig_left}{' ' * space_between}{sig_right}{UI.NEON_RED}║{UI.RESET}")

    out.append(f"{UI.NEON_GREEN}╠{'─' * (w - 2)}╣{UI.RESET}")

    # ─── URL DISPLAY BLOCK (Localhost + LAN URL or OFFLINE, No Test URLs Here) ───
    net_info = server_module.get_network_status(refresh=False)
    https_port = net_info.get("https_port", 8443)
    http_port = net_info.get("http_port", 5000)
    lan_ip = net_info.get("lan_ip", "127.0.0.1")

    localhost_str = (
        f"{UI.BOLD}{UI.NEON_GREEN}http://localhost:{http_port}/v1{UI.RESET} "
        f"{UI.DIM}{UI.GRAY}(& https://localhost:{https_port}/v1){UI.RESET}"
    )
    if lan_ip and lan_ip != "127.0.0.1":
        lan_display = (
            f"{UI.BOLD}{UI.NEON_GREEN}https://{lan_ip}:{https_port}/v1{UI.RESET} "
            f"{UI.DIM}{UI.GRAY}(& http://{lan_ip}:{http_port}/v1){UI.RESET}"
        )
    else:
        lan_display = f"{UI.BOLD}{UI.NEON_RED}OFFLINE{UI.RESET} {UI.DIM}{UI.GRAY}(No Wi-Fi / LAN network detected){UI.RESET}"

    row_local = f"  {UI.BOLD}{UI.CYBER_CYAN}🏠 Localhost URL :{UI.RESET} {localhost_str}"
    row_lan   = f"  {UI.BOLD}{UI.CYBER_CYAN}📡 LAN Wi-Fi URL :{UI.RESET} {lan_display}"

    pad_local = max(0, (w - 2) - visible_len(row_local))
    pad_lan   = max(0, (w - 2) - visible_len(row_lan))

    out.append(f"{UI.NEON_GREEN}║{UI.RESET}{row_local}{' ' * pad_local}{UI.NEON_RED}║{UI.RESET}")
    out.append(f"{UI.NEON_GREEN}║{UI.RESET}{row_lan}{' ' * pad_lan}{UI.NEON_RED}║{UI.RESET}")
    out.append(f"{UI.NEON_RED}╚{border_bar}╝{UI.RESET}")

    return "\n".join(out)


# =====================================================================
# FIRST-TIME LAUNCH WIZARD: SELECT DEFAULT AI MODE (Roleplay vs Professional)
# =====================================================================
def ensure_default_mode_configured():
    saved_mode = config_store.get_saved_default_mode()
    if saved_mode in ("roleplay", "professional"):
        roleplay_module.set_mode(saved_mode)
        return saved_mode

    selected_idx = 0
    options = [
        {
            "key": "roleplay",
            "title": "🎭 Roleplay Mode (JanitorAI / SillyTavern / Creative Storytelling)",
            "desc": "Auto-binds {{char}} & {{user}}, locks immersion, prevents AI disclaimers & godmoding.",
        },
        {
            "key": "professional",
            "title": "💻 Professional Mode (VS Code / Coding Agents / Clean Passthrough)",
            "desc": "Pure tool & code passthrough. Suppresses all RP directives for IDE & agent workflows.",
        },
    ]

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header())
        print()
        print(f"  {UI.BOLD}{UI.AMBER_GOLD}✨ FIRST-TIME SETUP — SELECT YOUR DEFAULT AI MODE{UI.RESET}")
        print(f"  {UI.GRAY}Use {UI.WHITE}[↑/↓]{UI.GRAY} or {UI.WHITE}[1/2]{UI.GRAY} and press {UI.WHITE}[Enter]{UI.GRAY}. We'll remember this for all future launches!{UI.RESET}\n")

        for idx, opt in enumerate(options):
            is_sel = (idx == selected_idx)
            pointer = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "
            title_style = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.WHITE}"
            print(f"  {pointer} {title_style}[{idx + 1}] {opt['title']}{UI.RESET}")
            print(f"       {UI.DIM}{UI.GRAY}{opt['desc']}{UI.RESET}\n")

        sys.stdout.flush()
        key = read_key()
        if key in ("UP", "LEFT", "k", "K"):
            selected_idx = (selected_idx - 1) % len(options)
        elif key in ("DOWN", "RIGHT", "j", "J"):
            selected_idx = (selected_idx + 1) % len(options)
        elif key == "1":
            selected_idx = 0
            break
        elif key == "2":
            selected_idx = 1
            break
        elif key == "ENTER":
            break

    chosen_mode = options[selected_idx]["key"]
    config_store.set_saved_default_mode(chosen_mode)
    roleplay_module.set_mode(chosen_mode)
    return chosen_mode


# =====================================================================
# OPTION 1: ADD / UPDATE NVIDIA API KEY (Red when missing/invalid, Green when valid)
# =====================================================================
def screen_manage_api_key():
    w = get_term_width()
    status_banner = ""

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header())

        current_key = engine.api_keys.get("runtime_override") or engine.api_keys.get("env") or ""
        masked = f"{current_key[:10]}••••••••••••••••{current_key[-4:]}" if len(current_key) > 16 else "None (Not Set)"

        if config_store.api_verified and is_valid_nvapi_key(current_key):
            badge = f"{UI.BG_GREEN_BADGE} ● ACTIVE & VERIFIED {UI.RESET}"
            key_color = UI.NEON_GREEN
        else:
            badge = f"{UI.BG_RED_BADGE} ● MISSING OR UNVERIFIED {UI.RESET}"
            key_color = UI.NEON_RED

        print(f"\n  {UI.BOLD}{UI.WHITE}🔑 OPTION 1 — NVIDIA API KEY MANAGEMENT (.env){UI.RESET}   {badge}")
        print(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}")
        print(f"  {UI.GRAY}Current Key :{UI.RESET} {UI.BOLD}{key_color}{masked}{UI.RESET}")
        print(f"  {UI.GRAY}Status      :{UI.RESET} {key_color}{config_store.api_status_msg}{UI.RESET}")
        print(f"  {UI.GRAY}.env Path   :{UI.RESET} {UI.DIM}{ENV_FILE}{UI.RESET}")

        # ─── STYLED INSTRUCTION BOX (User-Editable via API_KEY_INSTRUCTIONS at top of cli.py) ───
        print(f"\n  {UI.CYBER_CYAN}╭─ 📖 HOW TO GET YOUR NVIDIA API KEY {'─' * max(1, w - 42)}╮{UI.RESET}")
        for line in API_KEY_INSTRUCTIONS:
            print(f"  {UI.CYBER_CYAN}│{UI.RESET} {UI.WHITE}{line}{UI.RESET}")
        print(f"  {UI.CYBER_CYAN}╰{'─' * (w - 5)}╯{UI.RESET}")

        if status_banner:
            print(f"\n  {status_banner}")

        print(f"\n  {UI.AMBER_GOLD}Commands:{UI.RESET} Press {UI.BOLD}{UI.WHITE}[Enter]{UI.RESET} to paste a new API key, {UI.BOLD}{UI.WHITE}[T]{UI.RESET} to re-test current key, or {UI.BOLD}{UI.WHITE}[Esc / B]{UI.RESET} to go back.")
        sys.stdout.flush()

        k = read_key()
        if k in ("ESC", "b", "B", "q", "Q"):
            return
        elif k in ("t", "T"):
            print(f"\n  {UI.CYBER_CYAN}⏳ Testing current API key against NVIDIA NIM...{UI.RESET}", flush=True)
            ok, msg = config_store.verify_api_key_with_nvidia(current_key)
            if ok:
                status_banner = f"{UI.BOLD}{UI.NEON_GREEN}✔ {msg}{UI.RESET}"
            else:
                status_banner = f"{UI.BOLD}{UI.NEON_RED}✖ {msg}{UI.RESET}"
        elif k == "ENTER":
            sys.stdout.write(UI.SHOW_CURSOR)
            print(f"\n  {UI.BOLD}{UI.NEON_GREEN}❯ Paste your NVIDIA API Key (nvapi-...): {UI.RESET}", end="", flush=True)
            try:
                pasted = input().strip()
            except (EOFError, KeyboardInterrupt):
                pasted = ""
            sys.stdout.write(UI.HIDE_CURSOR)

            if not pasted:
                status_banner = f"{UI.AMBER_GOLD}⚠ Input cancelled — API key unchanged.{UI.RESET}"
                continue

            print(f"  {UI.CYBER_CYAN}⏳ Validating format & authenticating with NVIDIA servers...{UI.RESET}", flush=True)
            ok, msg = config_store.verify_api_key_with_nvidia(pasted)
            if ok:
                config_store.save_env_api_key(pasted)
                status_banner = f"{UI.BOLD}{UI.NEON_GREEN}✔ {msg}{UI.RESET}"
            else:
                config_store.save_env_api_key(pasted)
                status_banner = f"{UI.BOLD}{UI.NEON_RED}✖ {msg}{UI.RESET}"


# =====================================================================
# OPTION 2: CHANGE AI MODE (Roleplay Mode <-> Professional Mode)
# =====================================================================
def screen_change_mode():
    w = get_term_width()
    current_mode = roleplay_module.get_mode()
    saved_default = config_store.get_saved_default_mode() or "roleplay"

    modes = [
        {
            "id": "roleplay",
            "name": "🎭 Roleplay Mode",
            "desc": "Injects <system_context> & <narrative_directives>, auto-detects {{char}}/{{user}}, strips citation chips.",
        },
        {
            "id": "professional",
            "name": "💻 Professional Mode",
            "desc": "Pure coding & agent passthrough. Clears all RP prompts so VS Code / Cline / Roo Code work untouched.",
        },
    ]
    sel = 0 if current_mode == "roleplay" else 1
    feedback = ""

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header())
        current_mode = roleplay_module.get_mode()
        saved_default = config_store.get_saved_default_mode() or "Not Set"

        print(f"\n  {UI.BOLD}{UI.WHITE}⚙️  OPTION 2 — CHANGE AI OPERATING MODE (roleplay.py){UI.RESET}")
        print(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}")
        print(f"  {UI.GRAY}Current Session Mode :{UI.RESET} {UI.BOLD}{UI.NEON_GREEN}{current_mode.upper()}{UI.RESET}")
        print(f"  {UI.GRAY}Saved Default Mode   :{UI.RESET} {UI.BOLD}{UI.CYBER_CYAN}{saved_default.upper()}{UI.RESET}\n")

        for idx, m in enumerate(modes):
            is_sel = (idx == sel)
            is_active = (m["id"] == current_mode)
            is_def = (m["id"] == saved_default)

            cursor = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "
            active_tag = f" {UI.BG_GREEN_BADGE} ACTIVE {UI.RESET}" if is_active else ""
            def_tag = f" {UI.DIM}{UI.CYBER_CYAN}(Default){UI.RESET}" if is_def else ""
            row_color = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.WHITE}"

            print(f"  {cursor} {row_color}[{idx + 1}] {m['name']}{UI.RESET}{active_tag}{def_tag}")
            print(f"       {UI.DIM}{UI.GRAY}{m['desc']}{UI.RESET}\n")

        if feedback:
            print(f"  {feedback}\n")

        print(f"  {UI.GRAY}Use {UI.WHITE}[↑/↓]{UI.GRAY} to select, {UI.WHITE}[Enter]{UI.GRAY} to switch mode, or {UI.WHITE}[Esc / B]{UI.GRAY} to return.{UI.RESET}")
        sys.stdout.flush()

        key = read_key()
        if key in ("ESC", "b", "B", "q", "Q"):
            return
        elif key in ("UP", "LEFT", "k", "K"):
            sel = (sel - 1) % len(modes)
        elif key in ("DOWN", "RIGHT", "j", "J"):
            sel = (sel + 1) % len(modes)
        elif key in ("1", "2"):
            sel = int(key) - 1
            key = "ENTER"

        if key == "ENTER":
            target_mode = modes[sel]["id"]
            scope_sel = 0
            scope_choices = [
                ("session", "⚡ Just for This Session (Temporary)"),
                ("default", "💾 Make it Default Mode (Auto-load on future startups)"),
            ]
            while True:
                sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
                print(render_static_header())
                print(f"\n  {UI.BOLD}{UI.AMBER_GOLD}🔄 APPLY MODE: {target_mode.upper()}{UI.RESET}")
                print(f"  {UI.GRAY}How would you like to apply {UI.WHITE}{target_mode.upper()}{UI.GRAY} mode?{UI.RESET}\n")
                for s_idx, (_, s_label) in enumerate(scope_choices):
                    s_cur = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if s_idx == scope_sel else " "
                    s_col = f"{UI.BOLD}{UI.NEON_GREEN}" if s_idx == scope_sel else UI.WHITE
                    print(f"  {s_cur} {s_col}[{s_idx + 1}] {s_label}{UI.RESET}\n")

                print(f"  {UI.DIM}{UI.GRAY}Press [Enter] to confirm or [Esc] to cancel.{UI.RESET}")
                sys.stdout.flush()

                sk = read_key()
                if sk in ("ESC", "b", "B"):
                    break
                elif sk in ("UP", "DOWN", "LEFT", "RIGHT"):
                    scope_sel = (scope_sel + 1) % 2
                elif sk in ("1", "2"):
                    scope_sel = int(sk) - 1
                    sk = "ENTER"

                if sk == "ENTER":
                    roleplay_module.set_mode(target_mode)
                    if scope_choices[scope_sel][0] == "default":
                        config_store.set_saved_default_mode(target_mode)
                        feedback = f"{UI.BOLD}{UI.NEON_GREEN}✔ Switched to {target_mode.upper()} mode and saved as your permanent Default!{UI.RESET}"
                    else:
                        feedback = f"{UI.BOLD}{UI.NEON_GREEN}✔ Switched to {target_mode.upper()} mode for this session only!{UI.RESET}"
                    break


# =====================================================================
# OPTION 3: AVAILABLE MODELS LIST & SWITCHER (`model_switch.py`)
# =====================================================================
def screen_models_catalog():
    w = get_term_width()
    sel = 0
    notice = ""

    while True:
        models = model_switch_module.get_available_models()
        if sel >= len(models):
            sel = max(0, len(models) - 1)

        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header())
        print(f"\n  {UI.BOLD}{UI.WHITE}🤖 OPTION 3 — AVAILABLE NVIDIA MODELS (model_switch.py){UI.RESET}")
        print(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}")
        print(f"  {UI.DIM}{UI.GRAY}Add new models inside `model_switch.py` -> `AVAILABLE_MODELS` and they appear here automatically!{UI.RESET}\n")

        for idx, m in enumerate(models):
            is_sel = (idx == sel)
            is_act = m.get("is_active", False)
            pointer = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "
            active_badge = f" {UI.BG_GREEN_BADGE} ● ACTIVE {UI.RESET}" if is_act else ""
            name_col = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.BOLD}{UI.WHITE}"

            caps = []
            if m.get("vision"):
                caps.append("Vision")
            if m.get("thinking_capable"):
                caps.append("Thinking")
            if m.get("tools_capable"):
                caps.append("Tools")
            caps_str = " • ".join(caps)

            print(f"  {pointer} {name_col}[{m['index']}] {m['name']}{UI.RESET}{active_badge}")
            print(f"       {UI.CYBER_CYAN}ID   :{UI.RESET} {UI.WHITE}{m['id']}{UI.RESET}")
            print(f"       {UI.GRAY}Info :{UI.RESET} {UI.DIM}{m['description']} ({caps_str}){UI.RESET}\n")

        if notice:
            print(f"  {notice}\n")

        print(f"  {UI.GRAY}Use {UI.WHITE}[↑/↓]{UI.GRAY} to select, {UI.WHITE}[Enter]{UI.GRAY} to activate model, {UI.WHITE}[A]{UI.GRAY} to add runtime model, or {UI.WHITE}[Esc / B]{UI.GRAY} to go back.{UI.RESET}")
        sys.stdout.flush()

        key = read_key()
        if key in ("ESC", "b", "B", "q", "Q"):
            return
        elif key in ("UP", "LEFT", "k", "K"):
            sel = (sel - 1) % max(1, len(models))
        elif key in ("DOWN", "RIGHT", "j", "J"):
            sel = (sel + 1) % max(1, len(models))
        elif key.isdigit() and 1 <= int(key) <= len(models):
            sel = int(key) - 1
            res = model_switch_module.switch_model(models[sel]["id"])
            notice = f"{UI.BOLD}{UI.NEON_GREEN}✔ Active model switched to: {res['active_model']}{UI.RESET}"
        elif key in ("a", "A"):
            sys.stdout.write(UI.SHOW_CURSOR)
            print(f"\n  {UI.BOLD}{UI.NEON_GREEN}❯ Enter NVIDIA Model ID (e.g. deepseek-ai/deepseek-r1): {UI.RESET}", end="", flush=True)
            try:
                new_id = input().strip()
            except (EOFError, KeyboardInterrupt):
                new_id = ""
            sys.stdout.write(UI.HIDE_CURSOR)
            if new_id:
                model_switch_module.add_model_at_runtime(new_id)
                model_switch_module.switch_model(new_id)
                notice = f"{UI.BOLD}{UI.NEON_GREEN}✔ Added & switched to '{new_id}'!{UI.RESET}"
        elif key == "ENTER" and models:
            res = model_switch_module.switch_model(models[sel]["id"])
            notice = f"{UI.BOLD}{UI.NEON_GREEN}✔ Active model switched to: {res['active_model']}{UI.RESET}"


# =====================================================================
# OPTION 4: CONNECTION MODE (Test URLs + Connection URLs + Live Token Generation Logs)
# =====================================================================
def screen_connection_mode():
    """
    Live Dashboard showing:
      - All Connection URLs & Test URLs at the top (Zero-Warning HTTP + Trusted HTTPS + LAN)
      - Live Token Telemetry counters (Last Output Tokens, Session Input/Output Totals)
      - Real-time auto-refreshing stream of the Engine's colorful token generation logs!
    """
    global LIVE_VIEW_ACTIVE
    LIVE_VIEW_ACTIVE = True
    w = get_term_width()

    try:
        net = server_module.get_network_status(refresh=True)
        https_port = net.get("https_port", 8443)
        http_port = net.get("http_port", 5000)
        lan_ip = net.get("lan_ip", "127.0.0.1")
        has_lan = (lan_ip and lan_ip != "127.0.0.1")

        while True:
            sys.stdout.write("\033[H" + UI.HIDE_CURSOR)
            out = []
            border = "═" * (w - 2)
            out.append(f"{UI.NEON_GREEN}╔{border}╗{UI.RESET}")
            head_title = f"  {UI.BOLD}{UI.NEON_GREEN}📡 CONNECTION MODE{UI.RESET} {UI.DIM}—{UI.RESET} {UI.BOLD}{UI.NEON_RED}LIVE ENDPOINTS & TOKEN TELEMETRY{UI.RESET}"
            pad_h = max(0, (w - 2) - visible_len(head_title))
            out.append(f"{UI.NEON_GREEN}║{UI.RESET}{head_title}{' ' * pad_h}{UI.NEON_RED}║{UI.RESET}")
            out.append(f"{UI.NEON_GREEN}╠{'─' * (w - 2)}╣{UI.RESET}")

            # 1. Connection & Test URLs at the Top (Both Zero-Warning Port 5000 & HTTPS Port 8443)
            url_rows = [
                (f"{UI.BOLD}{UI.NEON_GREEN}Local Chat (No SSL Warn){UI.RESET}", f"{UI.NEON_GREEN}http://localhost:{http_port}/v1/chat/completions{UI.RESET}"),
                (f"{UI.BOLD}{UI.CYBER_CYAN}Local Chat (HTTPS)      {UI.RESET}", f"{UI.NEON_GREEN}https://localhost:{https_port}/v1/chat/completions{UI.RESET}"),
                (f"{UI.BOLD}{UI.CYBER_CYAN}LAN Chat (HTTPS / HTTP) {UI.RESET}", f"{UI.NEON_GREEN}https://{lan_ip}:{https_port}/v1/chat/completions{UI.RESET}" if has_lan else f"{UI.NEON_RED}OFFLINE{UI.RESET}"),
                (f"{UI.BOLD}{UI.AMBER_GOLD}Test Models (No Warn)   {UI.RESET}", f"{UI.WHITE}http://localhost:{http_port}/v1/models{UI.RESET}"),
                (f"{UI.BOLD}{UI.AMBER_GOLD}Test Models (HTTPS)     {UI.RESET}", f"{UI.WHITE}https://localhost:{https_port}/v1/models{UI.RESET}"),
                (f"{UI.BOLD}{UI.PURPLE_GLOW}LAN Mobile Root CA Cert {UI.RESET}", f"{UI.WHITE}http://{lan_ip}:{http_port}/cert.crt{UI.RESET}" if has_lan else f"{UI.WHITE}http://localhost:{http_port}/cert.crt{UI.RESET}"),
            ]
            for label, val in url_rows:
                line_s = f"  {label} : {val}"
                pad = max(0, (w - 2) - visible_len(line_s))
                out.append(f"{UI.NEON_GREEN}║{UI.RESET}{line_s}{' ' * pad}{UI.NEON_RED}║{UI.RESET}")

            out.append(f"{UI.NEON_GREEN}╠{'─' * (w - 2)}╣{UI.RESET}")

            # 2. Live Token Counters Summary Bar
            tok_stats = engine.get_token_stats()
            active_m = engine.config.get("active_model", "")
            curr_mode = roleplay_module.get_mode().upper()
            stats_line = (
                f"  {UI.BOLD}{UI.WHITE}Model:{UI.RESET} {UI.PURPLE_GLOW}{active_m}{UI.RESET}  "
                f"{UI.DIM}|{UI.RESET}  {UI.BOLD}{UI.WHITE}Mode:{UI.RESET} {UI.NEON_GREEN}{curr_mode}{UI.RESET}"
            )
            tok_line = (
                f"  {UI.CYBER_CYAN}⚡ Live Out: {UI.BOLD}{tok_stats['current_output_tokens']} tok{UI.RESET}  "
                f"{UI.DIM}|{UI.RESET}  {UI.NEON_GREEN}📝 Last Reply: {UI.BOLD}{tok_stats['last_response_output_tokens']} tok{UI.RESET}  "
                f"{UI.DIM}|{UI.RESET}  {UI.AMBER_GOLD}📊 Session Total: {UI.BOLD}{tok_stats['total_input_tokens'] + tok_stats['total_output_tokens']} tok{UI.RESET}"
            )
            out.append(f"{UI.NEON_GREEN}║{UI.RESET}{stats_line}{' ' * max(0, (w - 2) - visible_len(stats_line))}{UI.NEON_RED}║{UI.RESET}")
            out.append(f"{UI.NEON_GREEN}║{UI.RESET}{tok_line}{' ' * max(0, (w - 2) - visible_len(tok_line))}{UI.NEON_RED}║{UI.RESET}")
            out.append(f"{UI.NEON_RED}╚{border}╝{UI.RESET}")

            # 3. Live Engine Generation Logs Stream
            out.append(f"\n  {UI.BOLD}{UI.NEON_GREEN}📈 LIVE ENGINE TOKEN GENERATION LOGS{UI.RESET} {UI.DIM}(Auto-updating in real time){UI.RESET}")
            out.append(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}")

            if not LIVE_LOG_BUFFER:
                out.append(f"  {UI.DIM}{UI.GRAY}Waiting for incoming requests on http://localhost:{http_port}/v1 or https://localhost:{https_port}/v1 ...{UI.RESET}")
            else:
                for log_entry in list(LIVE_LOG_BUFFER)[-14:]:
                    out.append(f"  {log_entry}")

            out.append(f"\n  {UI.GRAY}Press {UI.BOLD}{UI.WHITE}[C]{UI.RESET}{UI.GRAY} to clear logs, {UI.BOLD}{UI.WHITE}[R]{UI.RESET}{UI.GRAY} to refresh LAN IP, or {UI.BOLD}{UI.WHITE}[Esc / B / Enter]{UI.RESET}{UI.GRAY} to return to main menu.{UI.RESET}   ")

            sys.stdout.write(UI.CLEAR_SCREEN + "\n".join(out) + "\n")
            sys.stdout.flush()

            key_pressed = _poll_key_nonblocking(timeout=0.45)
            if key_pressed in ("ESC", "b", "B", "q", "Q", "ENTER"):
                break
            elif key_pressed in ("c", "C"):
                LIVE_LOG_BUFFER.clear()
            elif key_pressed in ("r", "R"):
                net = server_module.get_network_status(refresh=True)
                lan_ip = net.get("lan_ip", "127.0.0.1")
                has_lan = (lan_ip and lan_ip != "127.0.0.1")
    finally:
        LIVE_VIEW_ACTIVE = False


def _poll_key_nonblocking(timeout=0.45):
    if os.name == "nt":
        import msvcrt
        steps = max(1, int(timeout / 0.05))
        for _ in range(steps):
            if msvcrt.kbhit():
                return read_key()
            time.sleep(0.05)
        return None
    else:
        import select
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            rlist, _, _ = select.select([sys.stdin], [], [], timeout)
            if rlist:
                ch = sys.stdin.read(1)
                if ch in ("\r", "\n"):
                    return "ENTER"
                if ch == "\x1b":
                    r2, _, _ = select.select([sys.stdin], [], [], 0.03)
                    if r2:
                        sys.stdin.read(2)
                    return "ESC"
                return ch
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# =====================================================================
# OPTION 5: GEMINI MODULE (Reserved for Future Integration)
# =====================================================================
def screen_gemini_future():
    w = get_term_width()
    sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
    print(render_static_header())
    print(f"\n  {UI.BOLD}{UI.PURPLE_GLOW}✦ OPTION 5 — GEMINI ENGINE INTEGRATION{UI.RESET}")
    print(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}\n")
    print(f"  {UI.BOLD}{UI.NEON_GREEN}🚧 Reserved for Future Update{UI.RESET}")
    print(f"  {UI.WHITE}This slot is pre-wired for your upcoming `gemini.py` integration.{UI.RESET}")
    print(f"  {UI.GRAY}When connected, you will be able to hot-swap between NVIDIA NIM and Gemini endpoints directly from here.{UI.RESET}\n")
    print(f"  {UI.DIM}{UI.GRAY}Press any key to return to the main dashboard...{UI.RESET}")
    sys.stdout.flush()
    read_key()


# =====================================================================
# MAIN INTERACTIVE DASHBOARD LOOP
# =====================================================================
def run_main_dashboard():
    selected = 0
    glitch_tick = 0

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header(glitch_variant=glitch_tick))
        glitch_tick = (glitch_tick + 1) % 5

        w = get_term_width()
        current_key = engine.api_keys.get("runtime_override") or engine.api_keys.get("env") or ""
        api_ok = config_store.api_verified and is_valid_nvapi_key(current_key)

        if api_ok:
            opt1_color = UI.NEON_GREEN
            opt1_badge = f"{UI.BG_GREEN_BADGE} ✔ VERIFIED (.env) {UI.RESET}"
            opt1_sub = "API Key authenticated with NVIDIA NIM & active in engine"
        else:
            opt1_color = UI.NEON_RED
            opt1_badge = f"{UI.BG_RED_BADGE} ✖ ACTION REQUIRED {UI.RESET}"
            opt1_sub = "No valid NVIDIA API Key configured — click here to paste & verify"

        active_mode = roleplay_module.get_mode().upper()
        default_mode = (config_store.get_saved_default_mode() or "roleplay").upper()
        active_model = model_switch_module.get_active_model()
        total_models = len(model_switch_module.get_available_models())
        tok_stats = engine.get_token_stats()

        menu_items = [
            {
                "num": "1",
                "title": "Add / Change NVIDIA API Key",
                "color": opt1_color,
                "badge": opt1_badge,
                "subtitle": opt1_sub,
                "action": screen_manage_api_key,
            },
            {
                "num": "2",
                "title": "Change AI Mode (Roleplay / Professional)",
                "color": UI.WHITE,
                "badge": f"{UI.BOLD}{UI.NEON_GREEN}[Active: {active_mode}]{UI.RESET} {UI.DIM}(Default: {default_mode}){UI.RESET}",
                "subtitle": "Switch between JanitorAI Roleplay directives & clean Coding/IDE passthrough",
                "action": screen_change_mode,
            },
            {
                "num": "3",
                "title": "Available Models & Switcher",
                "color": UI.WHITE,
                "badge": f"{UI.BOLD}{UI.PURPLE_GLOW}[{active_model.split('/')[-1]}]{UI.RESET} {UI.DIM}({total_models} in catalog){UI.RESET}",
                "subtitle": "Browse & hot-swap models synced from model_switch.py",
                "action": screen_models_catalog,
            },
            {
                "num": "4",
                "title": "Connection Mode & Live Token Logs",
                "color": UI.WHITE,
                "badge": f"{UI.BOLD}{UI.CYBER_CYAN}[Logs: {len(LIVE_LOG_BUFFER)} | Out: {tok_stats['last_response_output_tokens']} tok]{UI.RESET}",
                "subtitle": "View all Test URLs, Connection URLs & live streaming token generation logs",
                "action": screen_connection_mode,
            },
            {
                "num": "5",
                "title": "Gemini Integration",
                "color": UI.WHITE,
                "badge": f"{UI.DIM}{UI.AMBER_GOLD}[Upcoming Update]{UI.RESET}",
                "subtitle": "Reserved expansion slot for Gemini module integration",
                "action": screen_gemini_future,
            },
        ]

        print(f"\n  {UI.BOLD}{UI.SLATE_BLUE}◈ COMMAND CENTER{UI.RESET}  {UI.DIM}{UI.GRAY}(Navigate with ↑/↓ Arrows or 1-5, press Enter to open, Q to quit){UI.RESET}")
        print(f"  {UI.DARK_GRAY}{'─' * (w - 4)}{UI.RESET}")

        for idx, item in enumerate(menu_items):
            is_sel = (idx == selected)
            pointer = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "

            if idx == 0:
                title_col = f"{UI.BOLD}{item['color']}"
            else:
                title_col = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.BOLD}{item['color']}"

            bg_prefix = UI.BG_SELECT if is_sel else ""
            print(f"  {pointer} {bg_prefix}{title_col}[{item['num']}] {item['title']}{UI.RESET}  {item['badge']}")
            print(f"       {UI.DIM}{UI.GRAY}{item['subtitle']}{UI.RESET}\n")

        print(f"  {UI.DARK_GRAY}{'─' * (w - 4)}{UI.RESET}")
        print(
            f"  {UI.DIM}{UI.GRAY}Dual-Stack Server: {UI.NEON_GREEN}HTTP:{server_module.server_state.http_port} & HTTPS:{server_module.server_state.https_port}{UI.GRAY}  •  "
            f"Controls: {UI.WHITE}[↑/↓]{UI.GRAY} Move  {UI.WHITE}[Enter]{UI.GRAY} Select  {UI.WHITE}[Q]{UI.GRAY} Shutdown{UI.RESET}"
        )
        sys.stdout.flush()

        key = read_key()
        if key in ("UP", "LEFT", "k", "K"):
            selected = (selected - 1) % len(menu_items)
        elif key in ("DOWN", "RIGHT", "j", "J"):
            selected = (selected + 1) % len(menu_items)
        elif key in ("1", "2", "3", "4", "5"):
            selected = int(key) - 1
            menu_items[selected]["action"]()
        elif key == "ENTER":
            menu_items[selected]["action"]()
        elif key in ("q", "Q"):
            break


# =====================================================================
# MASTER BOOTSTRAP & ENTRYPOINT
# =====================================================================
def bootstrap_cli():
    try:
        play_startup_glitch_animation(duration=1.65)

        saved_key = config_store.load_env_api_key()
        if saved_key and is_valid_nvapi_key(saved_key):
            config_store.verify_api_key_with_nvidia(saved_key)
        else:
            config_store.api_verified = False
            config_store.api_status_msg = "No valid API Key in .env"

        orig_banner = server_module.print_server_banner
        server_module.print_server_banner = lambda: None
        try:
            server_module.start_server(background=True)
        finally:
            server_module.print_server_banner = orig_banner

        model_switch_module.sync_catalog_to_engine()
        ensure_default_mode_configured()
        run_main_dashboard()

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(UI.SHOW_CURSOR + "\n")
        print(f"  {UI.BOLD}{UI.NEON_RED}⚡ Shutting down NVIDIAFKU Server...{UI.RESET}")
        server_module.stop_server()
        print(f"  {UI.BOLD}{UI.NEON_GREEN}✔ Goodbye from NVIDIAFKU by ai_sahil_!{UI.RESET}\n")


if __name__ == "__main__":
    bootstrap_cli()