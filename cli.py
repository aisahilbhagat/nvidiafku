#!/usr/bin/env python3
"""
cli.py — Master Interactive Orchestrator for NVIDIAFKU Engine
=============================================================
Connects:
  1. nvidia_rp_cleaner.py  (Core Engine, Token Counters, API Key Store, Logs)
  2. server.py             (Dual-Stack HTTP Port 5000 + HTTPS & LAN Server Port 8443)
  3. roleplay.py           (Roleplay Mode & Professional Mode Controller)
  4. model_switch.py       (Dynamic Model Catalog & Switcher)
  5. gui.py                (Auto-detecting Desktop TUI + Minimal Android Termux Mobile UI)

Features:
  - Auto-detects device: launches Minimal Mobile UI on Android Termux, and full
    Neon Cyberpunk Desktop TUI on Windows, macOS, and Linux PC
  - Built-in UI Switcher button in both interfaces ([M]/[6] on Desktop, [S] on Mobile)
  - Auto-starts Dual-Stack HTTP/HTTPS & LAN Server in background with clean log capture
  - Auto-generates & updates `.env` for `NVIDIA_API_KEY` + live NVIDIA API verification
"""

import os
import sys
import json
import threading
from collections import deque
from datetime import datetime

# Enable ANSI escape sequences on Windows/Termux/Linux
os.system("")

import requests

# Connect all modules together
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
import gui as gui_module
from gui import UI


# =====================================================================
# ✏️ USER EDITABLE API KEY INSTRUCTIONS (Shown in Desktop Option 1)
# =====================================================================
API_KEY_INSTRUCTIONS = [
    "1. go to `https://build.nvidia.com/models`",
    "2. on the top right corner click on Login",
    "3. Enter your email and login",
    "4. click on the profile on the top right corner if you are logged in then the login should be replaced by it.",
    "5. You will Get three options click on API Keys.",
    "6. Click on Generate API keys name it and select the expiration date. Note that the api will expire after that time period.",
    "7. copy the api key and then update it inside the CLI or your required destination.",
]
PREFERENCES_FILE = os.path.abspath("cli_preferences.json")
ENV_FILE = os.path.abspath(".env")


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
# LIVE GENERATION LOG RING-BUFFER
# =====================================================================
LIVE_LOG_BUFFER = deque(maxlen=50)
_original_log_generation_event = core_module.log_generation_event


def _cli_hooked_log_generation_event(model_name, generated_ok, output_tokens, total_tokens, error_detail=None):
    """
    Captures every generation event from `nvidia_rp_cleaner.py` into `LIVE_LOG_BUFFER`
    for both the Desktop Connection Mode and Mobile Live Logs screens.
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
# MASTER BOOTSTRAP & ENTRYPOINT
# =====================================================================
def bootstrap_cli():
    try:
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

        # Pass shared state context into gui.py's auto-detecting UI orchestrator
        ui_context = {
            "server_module": server_module,
            "roleplay_module": roleplay_module,
            "model_switch_module": model_switch_module,
            "config_store": config_store,
            "engine": engine,
            "is_valid_nvapi_key": is_valid_nvapi_key,
            "live_log_buffer": LIVE_LOG_BUFFER,
            "env_file": ENV_FILE,
            "api_key_instructions": API_KEY_INSTRUCTIONS,
        }
        gui_module.launch_ui_orchestrator(ui_context)

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(UI.SHOW_CURSOR + "\n")
        print(f"  {UI.BOLD}{UI.NEON_RED}⚡ Shutting down NVIDIAFKU Server...{UI.RESET}")
        server_module.stop_server()
        print(f"  {UI.BOLD}{UI.NEON_GREEN}✔ Goodbye from NVIDIAFKU by ai_sahil_!{UI.RESET}\n")


if __name__ == "__main__":
    bootstrap_cli()