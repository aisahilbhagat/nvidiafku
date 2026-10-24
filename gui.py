#!/usr/bin/env python3
"""
gui.py — Dual-Form-Factor Terminal UI Engine (Desktop TUI + Minimal Android Termux UI)
======================================================================================
Provides two distinct, hot-swappable interfaces:
  1. DESKTOP UI ("desktop") — Full Neon Cyberpunk TUI for Windows, macOS, and Linux PC
     (Includes full ASCII glitch art, LAN + Localhost URLs, 5-option Command Center, arrow + key nav)
  2. MOBILE UI  ("mobile")  — Ultra-minimal, narrow-width form-factor UI crafted specifically
     for Android Termux portrait screens:
       - Minimal 1-line branding ("⚡ NVIDIAFKU • ai_sahil_")
       - Localhost URL only (`http://127.0.0.1:5000/v1`)
       - Concise 1-character number/alphabet navigation ([1] API, [2] Mode, [3] Logs, [S] Switch UI, [Q] Quit)
       - Zero clutter, zero horizontal wrapping on phone screens
"""

import os
import re
import sys
import time
import random


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


ASCII_NVIDIAFKU = [
    " ███╗   ██╗██╗   ██╗██╗██████╗ ██╗ █████╗ ███████╗██╗  ██╗██╗   ██╗",
    " ████╗  ██║██║   ██║██║██╔══██╗██║██╔══██╗██╔════╝██║ ██╔╝██║   ██║",
    " ██╔██╗ ██║██║   ██║██║██║  ██║██║███████║█████╗  █████╔╝ ██║   ██║",
    " ██║╚██╗██║╚██╗ ██╔╝██║██║  ██║██║██╔══██║██╔══╝  ██╔═██╗ ██║   ██║",
    " ██║ ╚████║ ╚████╔╝ ██║██████╔╝██║██║  ██║██║     ██║  ██╗╚██████╔╝",
    " ╚═╝  ╚═══╝  ╚═══╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝ ╚═════╝ ",
]

GLITCH_CHARS = ["#", "%", "&", "@", "$", "X", "0", "1", "▒", "▓", "█", "░", "/", "\\", "!", "?"]


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


def get_mobile_width(default=44) -> int:
    """Compact width tailored for portrait Android Termux screens."""
    try:
        cols = os.get_terminal_size().columns
        return max(34, min(cols - 2, 50))
    except Exception:
        return default


def is_android_termux_device() -> bool:
    """
    Auto-detects if the script is running on an Android phone (Termux) vs PC (Windows/macOS/Linux).
    """
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix or os.path.exists("/data/data/com.termux"):
        return True
    if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ:
        return True
    return False


# =====================================================================
# CROSS-PLATFORM KEYBOARD NAVIGATION (Unbuffered OS-level Read)
# =====================================================================
def _parse_escape_sequence(seq: str) -> str:
    if not seq:
        return "ESC"
    if seq in ("[A", "OA") or (seq.startswith("[") and seq.endswith("A")):
        return "UP"
    if seq in ("[B", "OB") or (seq.startswith("[") and seq.endswith("B")):
        return "DOWN"
    if seq in ("[C", "OC") or (seq.startswith("[") and seq.endswith("C")):
        return "RIGHT"
    if seq in ("[D", "OD") or (seq.startswith("[") and seq.endswith("D")):
        return "LEFT"
    return "ESC"


def read_key(timeout=None):
    """
    Reads a single keypress or multi-byte arrow sequence without requiring Enter.
    Works across Windows (`msvcrt`) and POSIX (`os.read` on Linux, macOS, Android Termux).
    """
    if os.name == "nt":
        import msvcrt

        if timeout is not None:
            deadline = time.time() + timeout
            while not msvcrt.kbhit():
                if time.time() >= deadline:
                    return None
                time.sleep(0.02)

        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == "\x08":
            return "BACKSPACE"
        if ch == "\x03":
            raise KeyboardInterrupt

        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            mapping = {
                "H": "UP",
                "P": "DOWN",
                "K": "LEFT",
                "M": "RIGHT",
                "I": "UP",
                "Q": "DOWN",
            }
            return mapping.get(ch2, "")

        if ch == "\x1b":
            seq = ""
            wait_until = time.time() + 0.025
            while time.time() < wait_until:
                if msvcrt.kbhit():
                    next_ch = msvcrt.getwch()
                    seq += next_ch
                    if next_ch.isalpha() or next_ch == "~" or len(seq) >= 6:
                        break
                else:
                    time.sleep(0.003)
            return _parse_escape_sequence(seq)

        return ch

    else:
        import tty
        import termios
        import select

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            if timeout is not None:
                rlist, _, _ = select.select([fd], [], [], timeout)
                if not rlist:
                    return None

            b1 = os.read(fd, 1)
            if not b1:
                return None
            ch = b1.decode("utf-8", errors="ignore")

            if ch in ("\r", "\n"):
                return "ENTER"
            if ch in ("\x7f", "\x08"):
                return "BACKSPACE"
            if ch == "\x03":
                raise KeyboardInterrupt

            if ch == "\x1b":
                seq_bytes = bytearray()
                while True:
                    rlist, _, _ = select.select([fd], [], [], 0.05)
                    if not rlist:
                        break
                    chunk = os.read(fd, 8)
                    if not chunk:
                        break
                    seq_bytes.extend(chunk)
                    if seq_bytes[-1:] and (chr(seq_bytes[-1]).isalpha() or chr(seq_bytes[-1]) == "~"):
                        break
                    if len(seq_bytes) >= 8:
                        break

                seq_str = seq_bytes.decode("utf-8", errors="ignore")
                return _parse_escape_sequence(seq_str)

            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def poll_key_nonblocking(timeout=0.45):
    return read_key(timeout=timeout)


# =====================================================================
# 📱 MINIMAL ANDROID TERMUX MOBILE UI (Compact Form-Factor)
# =====================================================================
def render_mobile_header(server_module, roleplay_module, config_store, engine, is_valid_nvapi_key) -> str:
    """
    Ultra-clean, minimal mobile header designed for narrow Termux phone screens:
      - Minimal branding: `⚡ NVIDIAFKU • ai_sahil_`
      - Localhost URL only (`http://127.0.0.1:5000/v1`)
      - Compact 1-line status pills for API & AI Mode
    """
    w = get_mobile_width()
    bar = "─" * w

    http_port = getattr(server_module.server_state, "http_port", 5000)
    localhost_url = f"http://127.0.0.1:{http_port}/v1"

    current_key = engine.api_keys.get("runtime_override") or engine.api_keys.get("env") or ""
    api_ok = config_store.api_verified and is_valid_nvapi_key(current_key)
    api_pill = f"{UI.BOLD}{UI.NEON_GREEN}API:OK{UI.RESET}" if api_ok else f"{UI.BOLD}{UI.NEON_RED}API:NONE{UI.RESET}"

    active_mode = roleplay_module.get_mode().upper()
    short_mode = "RP" if active_mode == "ROLEPLAY" else "PRO"
    mode_col = UI.NEON_GREEN if short_mode == "RP" else UI.CYBER_CYAN
    mode_pill = f"{UI.BOLD}{mode_col}MODE:{short_mode}{UI.RESET}"

    lines = [
        f" {UI.NEON_GREEN}{bar}{UI.RESET}",
        f" {UI.BOLD}{UI.NEON_GREEN}⚡ NVIDIA{UI.NEON_RED}FKU{UI.RESET} {UI.DIM}• ai_sahil_{UI.RESET}   {api_pill}  {mode_pill}",
        f" {UI.DARK_GRAY}{bar}{UI.RESET}",
        f" {UI.CYBER_CYAN}URL:{UI.RESET} {UI.BOLD}{UI.WHITE}{localhost_url}{UI.RESET}",
        f" {UI.NEON_RED}{bar}{UI.RESET}",
    ]
    return "\n".join(lines)


def mobile_screen_api_key(ctx: dict):
    """Minimal Termux API Key updater using numbers/alphabets."""
    config_store = ctx["config_store"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]

    msg = ""
    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_mobile_header(server_module, roleplay_module, config_store, engine, is_valid_nvapi_key))

        current_key = engine.api_keys.get("runtime_override") or engine.api_keys.get("env") or ""
        masked = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 14 else "Not Set"
        ok = config_store.api_verified and is_valid_nvapi_key(current_key)
        col = UI.NEON_GREEN if ok else UI.NEON_RED

        print(f"\n {UI.BOLD}{UI.WHITE}[1] UPDATE API KEY{UI.RESET}")
        print(f" {UI.GRAY}Key    :{UI.RESET} {col}{masked}{UI.RESET}")
        print(f" {UI.GRAY}Status :{UI.RESET} {col}{config_store.api_status_msg}{UI.RESET}")
        print(f" {UI.DIM}Get key: https://build.nvidia.com/models{UI.RESET}")

        if msg:
            print(f"\n {msg}")

        print(f"\n {UI.BOLD}{UI.NEON_GREEN}[A]{UI.RESET} Paste New Key")
        print(f" {UI.BOLD}{UI.CYBER_CYAN}[T]{UI.RESET} Test Key")
        print(f" {UI.BOLD}{UI.GRAY}[B]{UI.RESET} Back")
        sys.stdout.write(f"\n {UI.BOLD}{UI.WHITE}Select (A/T/B): {UI.RESET}")
        sys.stdout.flush()

        k = read_key()
        if k in ("b", "B", "q", "Q", "ESC", "0"):
            return
        elif k in ("t", "T", "2"):
            print(f"\n {UI.CYBER_CYAN}Testing...{UI.RESET}", flush=True)
            v_ok, v_msg = config_store.verify_api_key_with_nvidia(current_key)
            msg = f"{UI.NEON_GREEN}✔ Verified!{UI.RESET}" if v_ok else f"{UI.NEON_RED}✖ {v_msg}{UI.RESET}"
        elif k in ("a", "A", "1", "ENTER"):
            sys.stdout.write(UI.SHOW_CURSOR)
            print(f"\n\n {UI.BOLD}{UI.NEON_GREEN}Paste nvapi- key:{UI.RESET}\n > ", end="", flush=True)
            try:
                pasted = input().strip()
            except (EOFError, KeyboardInterrupt):
                pasted = ""
            sys.stdout.write(UI.HIDE_CURSOR)
            if not pasted:
                msg = f"{UI.AMBER_GOLD}Cancelled.{UI.RESET}"
                continue
            print(f" {UI.CYBER_CYAN}Checking...{UI.RESET}", flush=True)
            v_ok, v_msg = config_store.verify_api_key_with_nvidia(pasted)
            config_store.save_env_api_key(pasted)
            msg = f"{UI.NEON_GREEN}✔ Saved & Verified!{UI.RESET}" if v_ok else f"{UI.NEON_RED}✖ {v_msg}{UI.RESET}"


def mobile_screen_change_mode(ctx: dict):
    """Minimal Termux AI Mode switcher using numbers/alphabets."""
    config_store = ctx["config_store"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]

    msg = ""
    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_mobile_header(server_module, roleplay_module, config_store, engine, is_valid_nvapi_key))

        curr = roleplay_module.get_mode()
        saved_def = config_store.get_saved_default_mode() or "roleplay"

        rp_mark = f"{UI.NEON_GREEN}●{UI.RESET}" if curr == "roleplay" else " "
        pro_mark = f"{UI.CYBER_CYAN}●{UI.RESET}" if curr == "professional" else " "

        print(f"\n {UI.BOLD}{UI.WHITE}[2] CHANGE AI MODE{UI.RESET}")
        print(f" {UI.GRAY}Default: {saved_def.upper()}{UI.RESET}\n")
        print(f" {rp_mark} {UI.BOLD}{UI.WHITE}[1 / R]{UI.RESET} Roleplay Mode {UI.DIM}(JanitorAI/RP){UI.RESET}")
        print(f" {pro_mark} {UI.BOLD}{UI.WHITE}[2 / P]{UI.RESET} Professional  {UI.DIM}(Coding/Clean){UI.RESET}")
        print(f"   {UI.BOLD}{UI.AMBER_GOLD}[D]{UI.RESET}     Save current as Default")
        print(f"   {UI.BOLD}{UI.GRAY}[B]{UI.RESET}     Back")

        if msg:
            print(f"\n {msg}")

        sys.stdout.write(f"\n {UI.BOLD}{UI.WHITE}Select (1/2/D/B): {UI.RESET}")
        sys.stdout.flush()

        k = read_key()
        if k in ("b", "B", "q", "Q", "ESC", "0"):
            return
        elif k in ("1", "r", "R"):
            roleplay_module.set_mode("roleplay")
            msg = f"{UI.NEON_GREEN}✔ Roleplay Mode Active{UI.RESET}"
        elif k in ("2", "p", "P"):
            roleplay_module.set_mode("professional")
            msg = f"{UI.CYBER_CYAN}✔ Professional Mode Active{UI.RESET}"
        elif k in ("d", "D"):
            now_m = roleplay_module.get_mode()
            config_store.set_saved_default_mode(now_m)
            msg = f"{UI.AMBER_GOLD}✔ Saved {now_m.upper()} as Default{UI.RESET}"


def mobile_screen_logs(ctx: dict):
    """Minimal Termux Live Logs & Localhost Telemetry view."""
    config_store = ctx["config_store"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    live_log_buffer = ctx["live_log_buffer"]

    w = get_mobile_width()
    bar = "─" * w

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_mobile_header(server_module, roleplay_module, config_store, engine, is_valid_nvapi_key))

        tok = engine.get_token_stats()
        total_tok = tok["total_input_tokens"] + tok["total_output_tokens"]
        print(
            f" {UI.CYBER_CYAN}Out:{UI.RESET} {UI.BOLD}{tok['last_response_output_tokens']}{UI.RESET} tok  "
            f"{UI.AMBER_GOLD}Total:{UI.RESET} {UI.BOLD}{total_tok}{UI.RESET} tok"
        )
        print(f" {UI.DARK_GRAY}{bar}{UI.RESET}")
        print(f" {UI.BOLD}{UI.NEON_GREEN}LIVE LOGS{UI.RESET}")

        if not live_log_buffer:
            print(f" {UI.DIM}{UI.GRAY}Waiting for requests...{UI.RESET}")
        else:
            for entry in list(live_log_buffer)[-10:]:
                # Keep mobile log lines concise
                clean = strip_ansi(entry)
                if len(clean) > w + 6:
                    print(f" {clean[:w + 4]}")
                else:
                    print(f" {entry}")

        print(f" {UI.DARK_GRAY}{bar}{UI.RESET}")
        print(f" {UI.BOLD}{UI.WHITE}[C]{UI.RESET} {UI.GRAY}Clear{UI.RESET}   {UI.BOLD}{UI.WHITE}[B / Enter]{UI.RESET} {UI.GRAY}Back{UI.RESET}")
        sys.stdout.flush()

        k = poll_key_nonblocking(timeout=0.5)
        if k in ("b", "B", "q", "Q", "ESC", "ENTER", "0"):
            return
        elif k in ("c", "C"):
            live_log_buffer.clear()


def run_mobile_dashboard(ctx: dict) -> str:
    """
    Runs the minimal Android Termux CLI loop.
    Returns:
      - "switch_desktop" if user presses [S] to switch to the full PC CLI
      - "quit" if user presses [Q] to exit
    """
    config_store = ctx["config_store"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    live_log_buffer = ctx["live_log_buffer"]

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_mobile_header(server_module, roleplay_module, config_store, engine, is_valid_nvapi_key))

        current_key = engine.api_keys.get("runtime_override") or engine.api_keys.get("env") or ""
        api_ok = config_store.api_verified and is_valid_nvapi_key(current_key)
        api_tag = f"{UI.NEON_GREEN}[OK]{UI.RESET}" if api_ok else f"{UI.NEON_RED}[SET KEY]{UI.RESET}"

        mode_str = roleplay_module.get_mode().upper()
        tok = engine.get_token_stats()

        print(f"\n {UI.BOLD}{UI.WHITE}[1 / A]{UI.RESET} Update API Key  {api_tag}")
        print(f" {UI.BOLD}{UI.WHITE}[2 / M]{UI.RESET} Change AI Mode  {UI.CYBER_CYAN}[{mode_str}]{UI.RESET}")
        print(f" {UI.BOLD}{UI.WHITE}[3 / L]{UI.RESET} Live Logs       {UI.GRAY}[{len(live_log_buffer)} | {tok['last_response_output_tokens']}t]{UI.RESET}")
        print(f"\n {UI.BOLD}{UI.AMBER_GOLD}[S]{UI.RESET} {UI.GRAY}Switch to PC CLI{UI.RESET}   {UI.BOLD}{UI.NEON_RED}[Q]{UI.RESET} {UI.GRAY}Quit{UI.RESET}")
        sys.stdout.write(f"\n {UI.BOLD}{UI.NEON_GREEN}❯ {UI.RESET}{UI.GRAY}Press 1-3, A/M/L, S, Q:{UI.RESET} ")
        sys.stdout.flush()

        key = read_key()
        if key in ("1", "a", "A"):
            mobile_screen_api_key(ctx)
        elif key in ("2", "m", "M"):
            mobile_screen_change_mode(ctx)
        elif key in ("3", "l", "L"):
            mobile_screen_logs(ctx)
        elif key in ("s", "S"):
            return "switch_desktop"
        elif key in ("q", "Q"):
            return "quit"


# =====================================================================
# 🖥️ DESKTOP TUI (Full Neon Cyberpunk CLI for Windows, macOS & Linux)
# =====================================================================
def play_startup_glitch_animation(duration=1.65):
    """
    Plays a high-framerate cyberpunk Neon Green & Neon Red glitch materialization
    animation for 'NVIDIAFKU by ai_sahil_' when the Desktop CLI launches.
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


def render_static_header(server_module, roleplay_module, glitch_variant=0) -> str:
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

    # ─── URL DISPLAY BLOCK (Localhost + LAN URL or OFFLINE) ───
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


def ensure_default_mode_configured(ctx: dict, ui_mode="desktop"):
    """First-launch default mode wizard (compact on mobile, full on desktop)."""
    config_store = ctx["config_store"]
    roleplay_module = ctx["roleplay_module"]
    server_module = ctx["server_module"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]

    saved_mode = config_store.get_saved_default_mode()
    if saved_mode in ("roleplay", "professional"):
        roleplay_module.set_mode(saved_mode)
        return saved_mode

    if ui_mode == "mobile":
        while True:
            sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
            print(render_mobile_header(server_module, roleplay_module, config_store, engine, is_valid_nvapi_key))
            print(f"\n {UI.BOLD}{UI.AMBER_GOLD}SELECT DEFAULT AI MODE{UI.RESET}")
            print(f"\n {UI.BOLD}{UI.NEON_GREEN}[1 / R]{UI.RESET} Roleplay Mode {UI.DIM}(JanitorAI){UI.RESET}")
            print(f" {UI.BOLD}{UI.CYBER_CYAN}[2 / P]{UI.RESET} Professional  {UI.DIM}(Coding){UI.RESET}")
            sys.stdout.write(f"\n {UI.BOLD}{UI.WHITE}Select (1/2): {UI.RESET}")
            sys.stdout.flush()
            k = read_key()
            if k in ("1", "r", "R", "ENTER"):
                chosen = "roleplay"
                break
            elif k in ("2", "p", "P"):
                chosen = "professional"
                break
        config_store.set_saved_default_mode(chosen)
        roleplay_module.set_mode(chosen)
        return chosen

    selected_idx = 0
    options = [
        {
            "key": "roleplay",
            "title": "🎭 Roleplay Mode (JanitorAI / SillyTavern / Creative Storytelling)",
        },
        {
            "key": "professional",
            "title": "💻 Professional Mode (VS Code / Coding Agents / Clean Passthrough)",
        },
    ]

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header(server_module, roleplay_module))
        print()
        print(f"  {UI.BOLD}{UI.AMBER_GOLD}✨ FIRST-TIME SETUP — SELECT YOUR DEFAULT AI MODE{UI.RESET}\n")

        for idx, opt in enumerate(options):
            is_sel = (idx == selected_idx)
            pointer = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "
            title_style = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.WHITE}"
            bg_prefix = UI.BG_SELECT if is_sel else ""
            print(f"  {pointer} {bg_prefix}{title_style}[{idx + 1}] {opt['title']}{UI.RESET}")

        sys.stdout.flush()
        key = read_key()
        if key in ("UP", "LEFT", "k", "K", "w", "W"):
            selected_idx = (selected_idx - 1) % len(options)
        elif key in ("DOWN", "RIGHT", "j", "J", "s", "S"):
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


def screen_manage_api_key(ctx: dict):
    w = get_term_width()
    status_banner = ""
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    config_store = ctx["config_store"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]
    env_file = ctx["env_file"]
    api_key_instructions = ctx["api_key_instructions"]

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header(server_module, roleplay_module))

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
        print(f"  {UI.GRAY}.env Path   :{UI.RESET} {UI.DIM}{env_file}{UI.RESET}")

        print(f"\n  {UI.CYBER_CYAN}╭─ 📖 HOW TO GET YOUR NVIDIA API KEY {'─' * max(1, w - 42)}╮{UI.RESET}")
        for line in api_key_instructions:
            print(f"  {UI.CYBER_CYAN}│{UI.RESET} {UI.WHITE}{line}{UI.RESET}")
        print(f"  {UI.CYBER_CYAN}╰{'─' * (w - 5)}╯{UI.RESET}")

        if status_banner:
            print(f"\n  {status_banner}")

        print(f"\n  {UI.AMBER_GOLD}Commands:{UI.RESET} Press {UI.BOLD}{UI.WHITE}[Enter]{UI.RESET} to paste a new API key, {UI.BOLD}{UI.WHITE}[T]{UI.RESET} to re-test current key, or {UI.BOLD}{UI.WHITE}[Esc / B]{UI.RESET} to go back.")
        sys.stdout.flush()

        k = read_key()
        if k in ("ESC", "b", "B", "q", "Q", "LEFT"):
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


def screen_change_mode(ctx: dict):
    w = get_term_width()
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    config_store = ctx["config_store"]

    current_mode = roleplay_module.get_mode()
    saved_default = config_store.get_saved_default_mode() or "roleplay"

    modes = [
        {
            "id": "roleplay",
            "name": "🎭 Roleplay Mode",
        },
        {
            "id": "professional",
            "name": "💻 Professional Mode",
        },
    ]
    sel = 0 if current_mode == "roleplay" else 1
    feedback = ""

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header(server_module, roleplay_module))
        current_mode = roleplay_module.get_mode()
        saved_default = config_store.get_saved_default_mode() or "Not Set"

        print(f"\n  {UI.BOLD}{UI.WHITE}⚙️  OPTION 2 — CHANGE AI OPERATING MODE{UI.RESET}")
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
            bg_prefix = UI.BG_SELECT if is_sel else ""

            print(f"  {cursor} {bg_prefix}{row_color}[{idx + 1}] {m['name']}{UI.RESET}{active_tag}{def_tag}")

        if feedback:
            print(f"\n  {feedback}")

        print(f"\n  {UI.GRAY}Use {UI.WHITE}[↑/↓]{UI.GRAY} to select, {UI.WHITE}[Enter]{UI.GRAY} to switch mode, or {UI.WHITE}[Esc / B]{UI.GRAY} to return.{UI.RESET}")
        sys.stdout.flush()

        key = read_key()
        if key in ("ESC", "b", "B", "q", "Q", "LEFT"):
            return
        elif key in ("UP", "k", "K", "w", "W"):
            sel = (sel - 1) % len(modes)
        elif key in ("DOWN", "j", "J", "s", "S"):
            sel = (sel + 1) % len(modes)
        elif key in ("1", "2"):
            sel = int(key) - 1
            key = "ENTER"

        if key in ("ENTER", "RIGHT"):
            target_mode = modes[sel]["id"]
            scope_sel = 0
            scope_choices = [
                ("session", "⚡ Just for This Session (Temporary)"),
                ("default", "💾 Make it Default Mode (Auto-load on future startups)"),
            ]
            while True:
                sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
                print(render_static_header(server_module, roleplay_module))
                print(f"\n  {UI.BOLD}{UI.AMBER_GOLD}🔄 APPLY MODE: {target_mode.upper()}{UI.RESET}")
                print(f"  {UI.GRAY}How would you like to apply {UI.WHITE}{target_mode.upper()}{UI.GRAY} mode?{UI.RESET}\n")
                for s_idx, (_, s_label) in enumerate(scope_choices):
                    s_cur = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if s_idx == scope_sel else " "
                    s_col = f"{UI.BOLD}{UI.NEON_GREEN}" if s_idx == scope_sel else UI.WHITE
                    bg_p = UI.BG_SELECT if s_idx == scope_sel else ""
                    print(f"  {s_cur} {bg_p}{s_col}[{s_idx + 1}] {s_label}{UI.RESET}\n")

                print(f"  {UI.DIM}{UI.GRAY}Press [Enter] to confirm or [Esc] to cancel.{UI.RESET}")
                sys.stdout.flush()

                sk = read_key()
                if sk in ("ESC", "b", "B", "LEFT"):
                    break
                elif sk in ("UP", "DOWN", "k", "K", "j", "J", "w", "W", "s", "S"):
                    scope_sel = (scope_sel + 1) % 2
                elif sk in ("1", "2"):
                    scope_sel = int(sk) - 1
                    sk = "ENTER"

                if sk in ("ENTER", "RIGHT"):
                    roleplay_module.set_mode(target_mode)
                    if scope_choices[scope_sel][0] == "default":
                        config_store.set_saved_default_mode(target_mode)
                        feedback = f"{UI.BOLD}{UI.NEON_GREEN}✔ Switched to {target_mode.upper()} mode and saved as your permanent Default!{UI.RESET}"
                    else:
                        feedback = f"{UI.BOLD}{UI.NEON_GREEN}✔ Switched to {target_mode.upper()} mode for this session only!{UI.RESET}"
                    break


def screen_models_catalog(ctx: dict):
    w = get_term_width()
    sel = 0
    notice = ""
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    model_switch_module = ctx["model_switch_module"]

    while True:
        models = model_switch_module.get_available_models()
        if sel >= len(models):
            sel = max(0, len(models) - 1)

        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header(server_module, roleplay_module))
        print(f"\n  {UI.BOLD}{UI.WHITE}🤖 OPTION 3 — AVAILABLE NVIDIA MODELS{UI.RESET}")
        print(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}\n")

        for idx, m in enumerate(models):
            is_sel = (idx == sel)
            is_act = m.get("is_active", False)
            pointer = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "
            active_badge = f" {UI.BG_GREEN_BADGE} ● ACTIVE {UI.RESET}" if is_act else ""
            name_col = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.BOLD}{UI.WHITE}"
            bg_prefix = UI.BG_SELECT if is_sel else ""

            print(f"  {pointer} {bg_prefix}{name_col}[{m['index']}] {m['name']}{UI.RESET} {UI.DIM}({m['id']}){UI.RESET}{active_badge}")

        if notice:
            print(f"\n  {notice}")

        print(f"\n  {UI.GRAY}Use {UI.WHITE}[↑/↓]{UI.GRAY} to select, {UI.WHITE}[Enter]{UI.GRAY} to activate, {UI.WHITE}[A]{UI.GRAY} to add model, or {UI.WHITE}[Esc / B]{UI.GRAY} to go back.{UI.RESET}")
        sys.stdout.flush()

        key = read_key()
        if key in ("ESC", "b", "B", "q", "Q", "LEFT"):
            return
        elif key in ("UP", "k", "K", "w", "W"):
            sel = (sel - 1) % max(1, len(models))
        elif key in ("DOWN", "j", "J", "s", "S"):
            sel = (sel + 1) % max(1, len(models))
        elif key and key.isdigit() and 1 <= int(key) <= len(models):
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
        elif key in ("ENTER", "RIGHT") and models:
            res = model_switch_module.switch_model(models[sel]["id"])
            notice = f"{UI.BOLD}{UI.NEON_GREEN}✔ Active model switched to: {res['active_model']}{UI.RESET}"


def screen_connection_mode(ctx: dict):
    w = get_term_width()
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    engine = ctx["engine"]
    live_log_buffer = ctx["live_log_buffer"]

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

        out.append(f"\n  {UI.BOLD}{UI.NEON_GREEN}📈 LIVE ENGINE TOKEN GENERATION LOGS{UI.RESET} {UI.DIM}(Auto-updating in real time){UI.RESET}")
        out.append(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}")

        if not live_log_buffer:
            out.append(f"  {UI.DIM}{UI.GRAY}Waiting for incoming requests on http://localhost:{http_port}/v1 or https://localhost:{https_port}/v1 ...{UI.RESET}")
        else:
            for log_entry in list(live_log_buffer)[-14:]:
                out.append(f"  {log_entry}")

        out.append(f"\n  {UI.GRAY}Press {UI.BOLD}{UI.WHITE}[C]{UI.RESET}{UI.GRAY} to clear logs, {UI.BOLD}{UI.WHITE}[R]{UI.RESET}{UI.GRAY} to refresh LAN IP, or {UI.BOLD}{UI.WHITE}[Esc / B / Enter]{UI.RESET}{UI.GRAY} to return to main menu.{UI.RESET}   ")

        sys.stdout.write(UI.CLEAR_SCREEN + "\n".join(out) + "\n")
        sys.stdout.flush()

        key_pressed = poll_key_nonblocking(timeout=0.45)
        if key_pressed in ("ESC", "b", "B", "q", "Q", "ENTER", "LEFT"):
            break
        elif key_pressed in ("c", "C"):
            live_log_buffer.clear()
        elif key_pressed in ("r", "R"):
            net = server_module.get_network_status(refresh=True)
            lan_ip = net.get("lan_ip", "127.0.0.1")
            has_lan = (lan_ip and lan_ip != "127.0.0.1")


def screen_gemini_future(ctx: dict):
    w = get_term_width()
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]

    sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
    print(render_static_header(server_module, roleplay_module))
    print(f"\n  {UI.BOLD}{UI.PURPLE_GLOW}✦ OPTION 5 — GEMINI ENGINE INTEGRATION{UI.RESET}")
    print(f"  {UI.GRAY}{'─' * (w - 4)}{UI.RESET}\n")
    print(f"  {UI.BOLD}{UI.NEON_GREEN}🚧 Reserved for Future Update{UI.RESET}")
    print(f"  {UI.WHITE}This slot is pre-wired for your upcoming `gemini.py` integration.{UI.RESET}")
    print(f"  {UI.GRAY}When connected, you will be able to hot-swap between NVIDIA NIM and Gemini endpoints directly from here.{UI.RESET}\n")
    print(f"  {UI.DIM}{UI.GRAY}Press any key to return to the main dashboard...{UI.RESET}")
    sys.stdout.flush()
    read_key()


def run_desktop_dashboard(ctx: dict) -> str:
    """
    Runs the full Desktop TUI loop.
    Returns:
      - "switch_mobile" if user selects Option 6 or presses [M] to switch to Mobile CLI
      - "quit" if user presses [Q] to exit
    """
    selected = 0
    glitch_tick = 0
    server_module = ctx["server_module"]
    roleplay_module = ctx["roleplay_module"]
    model_switch_module = ctx["model_switch_module"]
    config_store = ctx["config_store"]
    engine = ctx["engine"]
    is_valid_nvapi_key = ctx["is_valid_nvapi_key"]
    live_log_buffer = ctx["live_log_buffer"]

    while True:
        sys.stdout.write(UI.CLEAR_SCREEN + UI.HIDE_CURSOR)
        print(render_static_header(server_module, roleplay_module, glitch_variant=glitch_tick))
        glitch_tick = (glitch_tick + 1) % 5

        w = get_term_width()
        current_key = engine.api_keys.get("runtime_override") or engine.api_keys.get("env") or ""
        api_ok = config_store.api_verified and is_valid_nvapi_key(current_key)

        if api_ok:
            opt1_color = UI.NEON_GREEN
            opt1_badge = f"{UI.BG_GREEN_BADGE} ✔ VERIFIED (.env) {UI.RESET}"
        else:
            opt1_color = UI.NEON_RED
            opt1_badge = f"{UI.BG_RED_BADGE} ✖ ACTION REQUIRED {UI.RESET}"

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
                "action": lambda: screen_manage_api_key(ctx),
            },
            {
                "num": "2",
                "title": "Change AI Mode (Roleplay / Professional)",
                "color": UI.WHITE,
                "badge": f"{UI.BOLD}{UI.NEON_GREEN}[Active: {active_mode}]{UI.RESET} {UI.DIM}(Default: {default_mode}){UI.RESET}",
                "action": lambda: screen_change_mode(ctx),
            },
            {
                "num": "3",
                "title": "Available Models & Switcher",
                "color": UI.WHITE,
                "badge": f"{UI.BOLD}{UI.PURPLE_GLOW}[{active_model.split('/')[-1]}]{UI.RESET} {UI.DIM}({total_models}){UI.RESET}",
                "action": lambda: screen_models_catalog(ctx),
            },
            {
                "num": "4",
                "title": "Connection Mode & Live Token Logs",
                "color": UI.WHITE,
                "badge": f"{UI.BOLD}{UI.CYBER_CYAN}[Logs: {len(live_log_buffer)} | Out: {tok_stats['last_response_output_tokens']} tok]{UI.RESET}",
                "action": lambda: screen_connection_mode(ctx),
            },
            {
                "num": "5",
                "title": "Gemini Integration",
                "color": UI.WHITE,
                "badge": f"{UI.DIM}{UI.AMBER_GOLD}[Upcoming Update]{UI.RESET}",
                "action": lambda: screen_gemini_future(ctx),
            },
            {
                "num": "6",
                "title": "Switch to Mobile Termux CLI",
                "color": UI.CYBER_CYAN,
                "badge": f"{UI.BOLD}{UI.AMBER_GOLD}[Shortcut: M]{UI.RESET}",
                "action": "switch_mobile",
            },
        ]

        print(f"\n  {UI.BOLD}{UI.SLATE_BLUE}◈ COMMAND CENTER{UI.RESET}")
        print(f"  {UI.DARK_GRAY}{'─' * (w - 4)}{UI.RESET}")

        for idx, item in enumerate(menu_items):
            is_sel = (idx == selected)
            pointer = f"{UI.BOLD}{UI.NEON_GREEN}❯{UI.RESET}" if is_sel else " "

            if idx == 0 and not api_ok:
                title_col = f"{UI.BOLD}{UI.NEON_RED}" if not is_sel else f"{UI.BOLD}{UI.NEON_GREEN}"
            else:
                title_col = f"{UI.BOLD}{UI.NEON_GREEN}" if is_sel else f"{UI.BOLD}{item['color']}"

            bg_prefix = UI.BG_SELECT if is_sel else ""
            print(f"  {pointer} {bg_prefix}{title_col}[{item['num']}] {item['title']}{UI.RESET}  {item['badge']}")

        print(f"  {UI.DARK_GRAY}{'─' * (w - 4)}{UI.RESET}")
        print(
            f"  {UI.DIM}{UI.GRAY}Controls: {UI.WHITE}[↑/↓ or 1-6]{UI.GRAY} Navigate  •  {UI.WHITE}[Enter]{UI.GRAY} Open  •  {UI.WHITE}[M]{UI.GRAY} Mobile UI  •  {UI.WHITE}[Q]{UI.GRAY} Quit{UI.RESET}"
        )
        sys.stdout.flush()

        key = read_key()
        if key in ("UP", "k", "K", "w", "W"):
            selected = (selected - 1) % len(menu_items)
        elif key in ("DOWN", "j", "J", "s", "S"):
            selected = (selected + 1) % len(menu_items)
        elif key in ("m", "M", "6"):
            return "switch_mobile"
        elif key in ("1", "2", "3", "4", "5"):
            selected = int(key) - 1
            menu_items[selected]["action"]()
        elif key in ("ENTER", "RIGHT"):
            act = menu_items[selected]["action"]
            if act == "switch_mobile":
                return "switch_mobile"
            act()
        elif key in ("q", "Q"):
            return "quit"


# =====================================================================
# 🔄 UNIFIED UI ORCHESTRATOR (Auto-Detects Device + Hot-Swaps UIs)
# =====================================================================
def launch_ui_orchestrator(ctx: dict):
    """
    Auto-detects the device at launch:
      - Android Termux -> Boots directly into the minimal Mobile UI (`run_mobile_dashboard`)
      - Windows / macOS / Linux PC -> Plays the startup glitch animation and boots into
        the full Desktop UI (`run_desktop_dashboard`)
    Allows instant live switching between Desktop UI and Mobile UI at any time!
    """
    active_ui = "mobile" if is_android_termux_device() else "desktop"

    if active_ui == "desktop":
        play_startup_glitch_animation(duration=1.65)

    ensure_default_mode_configured(ctx, ui_mode=active_ui)

    while True:
        if active_ui == "mobile":
            result = run_mobile_dashboard(ctx)
            if result == "switch_desktop":
                active_ui = "desktop"
                continue
            break
        else:
            result = run_desktop_dashboard(ctx)
            if result == "switch_mobile":
                active_ui = "mobile"
                continue
            break