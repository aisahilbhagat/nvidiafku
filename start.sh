#!/usr/bin/env bash
# =============================================================================
# start.sh — Zero-Touch Cross-Platform Launcher for NVIDIAFKU (by ai_sahil_)
# Features:
#   - Auto-detects & Auto-installs Python 3 (Termux, Linux apt/dnf/pacman/apk, macOS)
#   - Cyberpunk Neon Green & Red Animated Spinner + Progress Bar
#   - Safe Git Auto-Update, Auto .venv, Auto Dependency Install & Global Command
#   - Launches cli.py
# =============================================================================

set -u

# -----------------------------------------------------------------------------
# 1. Project Directory Detection
# -----------------------------------------------------------------------------
resolve_script_dir() {
    local source="${BASH_SOURCE[0]}"
    while [ -h "$source" ]; do
        local dir
        dir="$(cd -P "$(dirname "$source")" >/dev/null 2>&1 && pwd)"
        source="$(readlink "$source")"
        [[ "$source" != /* ]] && source="$dir/$source"
    done
    cd -P "$(dirname "$source")" >/dev/null 2>&1 && pwd
}

PROJECT_ROOT="$(resolve_script_dir)"
cd "$PROJECT_ROOT" || {
    echo "[ERROR] Failed to switch to project directory: $PROJECT_ROOT" >&2
    exit 1
}

APP_NAME="NVIDIAFKU"
APP_AUTHOR="ai_sahil_"
ENTRY_POINT="cli.py"
GLOBAL_CMD_NAME="nvdfk"
REQ_FILE="$PROJECT_ROOT/requirements.txt"
VENV_DIR="$PROJECT_ROOT/.venv"
DEPS_STAMP_FILE="$VENV_DIR/.nvidiafku_deps_installed"

# -----------------------------------------------------------------------------
# Neon Cyberpunk ANSI Palette (Matches cli.py)
# -----------------------------------------------------------------------------
if [ -t 1 ]; then
    RESET="\033[0m"
    BOLD="\033[1m"
    DIM="\033[2m"
    NEON_GREEN="\033[38;5;46m"
    NEON_RED="\033[38;5;196m"
    CYBER_CYAN="\033[38;5;51m"
    AMBER_GOLD="\033[38;5;214m"
    WHITE="\033[97m"
    GRAY="\033[38;5;244m"
    HIDE_CURSOR="\033[?25l"
    SHOW_CURSOR="\033[?25h"
else
    RESET=""
    BOLD=""
    DIM=""
    NEON_GREEN=""
    NEON_RED=""
    CYBER_CYAN=""
    AMBER_GOLD=""
    WHITE=""
    GRAY=""
    HIDE_CURSOR=""
    SHOW_CURSOR=""
fi

cleanup_terminal() {
    printf "%b" "${SHOW_CURSOR}${RESET}" 2>/dev/null || true
}
trap cleanup_terminal EXIT INT TERM

log_info() { printf "  ${BOLD}${CYBER_CYAN}[INFO]${RESET} %s\n" "$1"; }
log_ok()   { printf "  ${BOLD}${NEON_GREEN}[ ✔ ]${RESET}  %s\n" "$1"; }
log_warn() { printf "  ${BOLD}${AMBER_GOLD}[WARN]${RESET} %s\n" "$1"; }
log_err()  { printf "  ${BOLD}${NEON_RED}[ ✖ ]${RESET}  %s\n" "$1" >&2; }

# -----------------------------------------------------------------------------
# Cyberpunk Neon Animated Task Runner
# Runs any background command with a live Braille spinner + Neon Progress Bar
# -----------------------------------------------------------------------------
run_with_neon_animation() {
    local label="$1"
    shift
    local log_file
    log_file="$(mktemp 2>/dev/null || echo "/tmp/nvidiafku_setup_$$.log")"

    # If not an interactive terminal, run directly
    if [ ! -t 1 ]; then
        log_info "$label..."
        if "$@" >"$log_file" 2>&1; then
            rm -f "$log_file"
            return 0
        else
            cat "$log_file" >&2
            rm -f "$log_file"
            return 1
        fi
    fi

    printf "%b" "$HIDE_CURSOR"
    "$@" >"$log_file" 2>&1 &
    local cmd_pid=$!

    local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    local bar_states=(
        "${NEON_GREEN}█░░░░░░░░░${RESET}"
        "${NEON_GREEN}██░░░░░░░░${RESET}"
        "${NEON_GREEN}███░░░░░░░${RESET}"
        "${NEON_GREEN}████░░░░░░${RESET}"
        "${NEON_GREEN}█████${NEON_RED}░░░░░${RESET}"
        "${NEON_GREEN}█████${NEON_RED}█░░░░${RESET}"
        "${NEON_GREEN}█████${NEON_RED}██░░░${RESET}"
        "${NEON_GREEN}█████${NEON_RED}███░░${RESET}"
        "${NEON_GREEN}█████${NEON_RED}████░${RESET}"
        "${NEON_GREEN}█████${NEON_RED}█████${RESET}"
    )
    local i=0
    while kill -0 "$cmd_pid" 2>/dev/null; do
        local f="${frames[$((i % 10))]}"
        local b="${bar_states[$((i % 10))]}"
        printf "\r  ${BOLD}${NEON_GREEN}%s${RESET} ${DIM}[${RESET}%b${DIM}]${RESET} ${WHITE}%s${RESET}   " "$f" "$b" "$label"
        sleep 0.08
        i=$((i + 1))
    done

    wait "$cmd_pid"
    local exit_code=$?

    if [ "$exit_code" -eq 0 ]; then
        printf "\r\033[K  ${BOLD}${NEON_GREEN}[ ✔ ]${RESET} ${DIM}[${NEON_GREEN}██████████${RESET}${DIM}]${RESET} ${WHITE}%s${RESET}\n" "$label"
        printf "%b" "$SHOW_CURSOR"
        rm -f "$log_file"
        return 0
    else
        printf "\r\033[K  ${BOLD}${NEON_RED}[ ✖ ]${RESET} ${DIM}[${NEON_RED}██████████${RESET}${DIM}]${RESET} ${NEON_RED}%s (FAILED)${RESET}\n" "$label"
        printf "%b" "$SHOW_CURSOR"
        printf "\n  ${BOLD}${NEON_RED}── Diagnostic Output ──────────────────────────────────────────${RESET}\n" >&2
        tail -n 25 "$log_file" >&2 2>/dev/null || true
        printf "  ${BOLD}${NEON_RED}───────────────────────────────────────────────────────────────${RESET}\n\n" >&2
        rm -f "$log_file"
        return "$exit_code"
    fi
}

# -----------------------------------------------------------------------------
# 2. Startup Banner
# -----------------------------------------------------------------------------
print_banner() {
    printf "\n"
    printf "${NEON_GREEN}╔══════════════════════════════════════════════════════════════════════════╗${RESET}\n"
    printf "${NEON_GREEN}║${RESET}  ${BOLD}${NEON_GREEN}⚡ NVIDIA${NEON_RED}FKU${RESET} ${BOLD}${NEON_RED}by ${NEON_GREEN}${APP_AUTHOR}${RESET} ${DIM}${GRAY}— Zero-Touch Auto-Setup & Launcher${RESET}          ${NEON_RED}║${RESET}\n"
    printf "${NEON_GREEN}║${RESET}  ${CYBER_CYAN}Dual-Stack HTTP (5000) + HTTPS/LAN (8443) NVIDIA NIM Engine${RESET}             ${NEON_RED}║${RESET}\n"
    printf "${NEON_RED}╚══════════════════════════════════════════════════════════════════════════╝${RESET}\n"
}

# -----------------------------------------------------------------------------
# Argument Parsing
# -----------------------------------------------------------------------------
SKIP_UPDATE="${NVIDIAFKU_NO_UPDATE:-0}"
FORCE_DEPS=0
APP_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --no-update)
            SKIP_UPDATE=1
            ;;
        --reinstall-deps)
            FORCE_DEPS=1
            ;;
        --launcher-help)
            print_banner
            printf "\n  ${BOLD}${WHITE}Launcher Options:${RESET}\n"
            printf "    ${NEON_GREEN}--no-update${RESET}       Skip Git auto-update check on startup\n"
            printf "    ${NEON_GREEN}--reinstall-deps${RESET}  Force re-verification & installation of dependencies\n"
            printf "    ${NEON_GREEN}--launcher-help${RESET}   Show this launcher help message\n\n"
            exit 0
            ;;
        *)
            APP_ARGS+=("$arg")
            ;;
    esac
done

print_banner

# -----------------------------------------------------------------------------
# 5. Termux & OS Platform Detection
# -----------------------------------------------------------------------------
IS_TERMUX=0
if [ -n "${PREFIX:-}" ] && [[ "${PREFIX:-}" == *"com.termux"* ]]; then
    IS_TERMUX=1
elif [ -d "/data/data/com.termux/files/usr" ]; then
    IS_TERMUX=1
    export PREFIX="/data/data/com.termux/files/usr"
    export PATH="$PREFIX/bin:$PATH"
fi

OS_TYPE="$(uname -s 2>/dev/null || echo "Unknown")"
if [ "$IS_TERMUX" -eq 1 ]; then
    PLATFORM_LABEL="Android Termux"
elif [ "$OS_TYPE" = "Darwin" ]; then
    PLATFORM_LABEL="macOS"
elif [ "$OS_TYPE" = "Linux" ]; then
    PLATFORM_LABEL="Linux"
else
    PLATFORM_LABEL="$OS_TYPE"
fi

log_info "Platform detected: ${PLATFORM_LABEL}"
log_info "Project root     : ${PROJECT_ROOT}"

# -----------------------------------------------------------------------------
# 3. Optional Safe Git Auto-Update
# -----------------------------------------------------------------------------
perform_git_update() {
    if [ "$SKIP_UPDATE" = "1" ] || [ "$SKIP_UPDATE" = "true" ]; then
        log_info "Git auto-update skipped."
        return 0
    fi
    command -v git >/dev/null 2>&1 || return 0
    [ -d "$PROJECT_ROOT/.git" ] || return 0

    local upstream
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
    [ -n "$upstream" ] || return 0

    if ! run_with_neon_animation "Checking Git upstream ($upstream) for updates" env GIT_TERMINAL_PROMPT=0 git fetch --quiet; then
        log_warn "Offline or unable to reach Git remote. Continuing with local version."
        return 0
    fi

    local local_sha remote_sha base_sha
    local_sha="$(git rev-parse @ 2>/dev/null || true)"
    remote_sha="$(git rev-parse "@{u}" 2>/dev/null || true)"
    base_sha="$(git merge-base @ "@{u}" 2>/dev/null || true)"

    if [ -z "$local_sha" ] || [ -z "$remote_sha" ] || [ "$local_sha" = "$remote_sha" ]; then
        log_ok "Repository is up to date."
        return 0
    fi

    if [ "$local_sha" = "$base_sha" ]; then
        if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
            log_warn "Updates available, but uncommitted local changes exist. Preserving local work."
            return 0
        fi
        if run_with_neon_animation "Applying fast-forward Git update" git merge --ff-only "@{u}"; then
            log_ok "Updated ${APP_NAME} to commit $(git rev-parse --short HEAD)."
            FORCE_DEPS=1
        else
            log_warn "Could not fast-forward cleanly. Keeping current version."
        fi
    fi
}

perform_git_update

# -----------------------------------------------------------------------------
# 4. Python 3 Detection & AUTOMATIC INSTALLATION (If Missing!)
# -----------------------------------------------------------------------------
PYTHON_BIN=""

find_python3() {
    PYTHON_BIN=""
    # Ensure common install locations are in PATH
    for extra_p in "$HOME/.local/bin" "/opt/homebrew/bin" "/usr/local/bin" "/usr/bin"; do
        if [ -d "$extra_p" ] && [[ ":$PATH:" != *":$extra_p:"* ]]; then
            export PATH="$extra_p:$PATH"
        fi
    done

    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
                PYTHON_BIN="$(command -v "$candidate")"
                return 0
            fi
        fi
    done
    return 1
}

auto_install_python() {
    log_warn "Python 3.8+ was not found on this system. Starting automatic installation..."

    # Case 1: Android Termux
    if [ "$IS_TERMUX" -eq 1 ]; then
        run_with_neon_animation "Updating Termux package catalogs" pkg update -y -o Dpkg::Options::="--force-confold" || true
        run_with_neon_animation "Auto-installing Python 3 & SSL libraries in Termux" pkg install -y python python-cryptography openssl-tool
        return $?
    fi

    # Determine sudo wrapper for Linux
    local SUDO_CMD=""
    if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            SUDO_CMD="sudo"
            log_info "Administrator privileges may be requested by your OS to install Python 3."
        fi
    fi

    # Case 2: macOS
    if [ "$OS_TYPE" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            run_with_neon_animation "Auto-installing Python 3 via Homebrew" brew install python
            return $?
        else
            local pkg_tmp="/tmp/python-macos-universal.pkg"
            if run_with_neon_animation "Downloading official Python 3.12 macOS Universal Installer" curl -fsSL "https://www.python.org/ftp/python/3.12.8/python-3.12.8-macos11.pkg" -o "$pkg_tmp"; then
                log_info "Running macOS installer for Python 3.12 (sudo password may be prompted)..."
                $SUDO_CMD installer -pkg "$pkg_tmp" -target /
                local rc=$?
                rm -f "$pkg_tmp"
                return $rc
            fi
        fi
    fi

    # Case 3: Linux (apt, dnf, yum, pacman, zypper, apk)
    if command -v apt-get >/dev/null 2>&1; then
        $SUDO_CMD apt-get update -y
        $SUDO_CMD env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip openssl
        return $?
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO_CMD dnf install -y python3 python3-pip openssl
        return $?
    elif command -v yum >/dev/null 2>&1; then
        $SUDO_CMD yum install -y python3 python3-pip openssl
        return $?
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO_CMD pacman -Sy --noconfirm python python-pip openssl
        return $?
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO_CMD zypper --non-interactive install python3 python3-pip python3-virtualenv openssl
        return $?
    elif command -v apk >/dev/null 2>&1; then
        $SUDO_CMD apk add --no-cache python3 py3-pip py3-cryptography openssl
        return $?
    fi

    return 1
}

if ! find_python3; then
    if ! auto_install_python || ! find_python3; then
        log_err "Automatic Python 3 installation could not complete."
        printf "\n  ${BOLD}${WHITE}Please install Python 3.8+ manually and re-run ./start.sh:${RESET}\n"
        printf "    • Termux        : ${NEON_GREEN}pkg install python python-cryptography openssl-tool${RESET}\n"
        printf "    • Ubuntu/Debian : ${NEON_GREEN}sudo apt update && sudo apt install -y python3 python3-venv python3-pip${RESET}\n"
        printf "    • macOS         : ${NEON_GREEN}brew install python${RESET} (or https://www.python.org/downloads/)\n\n"
        exit 1
    fi
fi

# Ensure Termux native cryptography & openssl-tool are present so Termux never hangs compiling Rust
if [ "$IS_TERMUX" -eq 1 ]; then
    if ! command -v openssl >/dev/null 2>&1; then
        run_with_neon_animation "Installing Termux openssl-tool" pkg install -y openssl-tool || true
    fi
    if ! "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
        run_with_neon_animation "Installing Termux native python-cryptography" pkg install -y python-cryptography || true
    fi
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
log_ok "Python runtime ready: ${PYTHON_BIN} (v${PY_VERSION})"

# -----------------------------------------------------------------------------
# 6. Virtual Environment Setup (.venv)
# -----------------------------------------------------------------------------
ACTIVE_PYTHON=""

if [ "$IS_TERMUX" -eq 1 ]; then
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        if run_with_neon_animation "Creating Termux virtual environment (.venv)" "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"; then
            ACTIVE_PYTHON="$VENV_DIR/bin/python"
        else
            log_warn "Using Termux prefix Python environment directly."
            ACTIVE_PYTHON="$PYTHON_BIN"
        fi
    else
        ACTIVE_PYTHON="$VENV_DIR/bin/python"
    fi
else
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        if ! run_with_neon_animation "Creating isolated virtual environment (.venv)" "$PYTHON_BIN" -m venv "$VENV_DIR"; then
            # On Ubuntu/Debian, python3-venv package might be missing even when python3 is installed
            if command -v apt-get >/dev/null 2>&1; then
                log_warn "python3-venv package missing. Auto-installing python3-venv..."
                SUDO_VENV=""
                [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO_VENV="sudo"
                $SUDO_VENV apt-get update -y && $SUDO_VENV apt-get install -y python3-venv python3-pip
            fi
            rm -rf "$VENV_DIR" 2>/dev/null || true
            if ! run_with_neon_animation "Retrying virtual environment creation (.venv)" "$PYTHON_BIN" -m venv "$VENV_DIR"; then
                log_err "Could not create virtual environment in $VENV_DIR."
                exit 1
            fi
        fi
    fi
    ACTIVE_PYTHON="$VENV_DIR/bin/python"
fi

if ! "$ACTIVE_PYTHON" -m pip --version >/dev/null 2>&1; then
    run_with_neon_animation "Bootstrapping pip package manager" "$ACTIVE_PYTHON" -m ensurepip --upgrade || true
fi

# -----------------------------------------------------------------------------
# 7 & 8. Animated Automatic Dependency Installation & Verification
# -----------------------------------------------------------------------------
check_imports() {
    "$ACTIVE_PYTHON" -c "import flask, werkzeug, requests, urllib3, cryptography, rich" >/dev/null 2>&1
}

NEEDS_INSTALL=0
if [ "$FORCE_DEPS" -eq 1 ]; then
    NEEDS_INSTALL=1
elif ! check_imports; then
    NEEDS_INSTALL=1
elif [ -f "$REQ_FILE" ] && [ -f "$DEPS_STAMP_FILE" ] && [ "$REQ_FILE" -nt "$DEPS_STAMP_FILE" ]; then
    NEEDS_INSTALL=1
fi

if [ "$NEEDS_INSTALL" -eq 1 ]; then
    PIP_ARGS=("--disable-pip-version-check" "--no-input")
    if [ -f "$REQ_FILE" ]; then
        INSTALL_CMD=("$ACTIVE_PYTHON" -m pip install "${PIP_ARGS[@]}" -r "$REQ_FILE")
    else
        INSTALL_CMD=("$ACTIVE_PYTHON" -m pip install "${PIP_ARGS[@]}" "flask>=3.0.0" "werkzeug>=3.0.0" "requests>=2.31.0" "urllib3>=2.0.0" "cryptography>=42.0.0" "rich>=13.7.0")
    fi

    if ! run_with_neon_animation "Installing NVIDIAFKU dependencies (Flask, Cryptography, Rich, Requests)" "${INSTALL_CMD[@]}"; then
        log_err "Failed to install required Python dependencies!"
        printf "\n  ${BOLD}${AMBER_GOLD}Troubleshooting Guidance:${RESET}\n"
        printf "    1. Check your internet / Wi-Fi connection.\n"
        if [ "$IS_TERMUX" -eq 1 ]; then
            printf "    2. Run: ${NEON_GREEN}pkg install python-cryptography openssl-tool${RESET}\n"
        else
            printf "    2. Run: ${NEON_GREEN}\"$ACTIVE_PYTHON\" -m pip install --upgrade pip setuptools wheel${RESET}\n"
        fi
        exit 1
    fi

    if ! check_imports; then
        log_err "Packages installed, but module verification failed."
        exit 1
    fi

    [ -d "$VENV_DIR" ] && touch "$DEPS_STAMP_FILE" 2>/dev/null || true
else
    log_ok "All runtime dependencies verified (flask, werkzeug, requests, cryptography, rich)."
fi

# -----------------------------------------------------------------------------
# 9. Global Convenience Command Registration (`nvidiafku`)
# -----------------------------------------------------------------------------
register_global_command() {
    local target_bin_dir=""
    if [ "$IS_TERMUX" -eq 1 ] && [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ] && [ -w "$PREFIX/bin" ]; then
        target_bin_dir="$PREFIX/bin"
    else
        target_bin_dir="$HOME/.local/bin"
        mkdir -p "$target_bin_dir" 2>/dev/null || return 0
    fi

    local wrapper_path="$target_bin_dir/$GLOBAL_CMD_NAME"
    local desired_content="#!/usr/bin/env bash
# Auto-generated global launcher for NVIDIAFKU by ai_sahil_
exec \"$PROJECT_ROOT/start.sh\" \"\$@\"
"
    local current_content=""
    [ -f "$wrapper_path" ] && current_content="$(cat "$wrapper_path" 2>/dev/null || true)"

    if [ "$current_content" != "$desired_content" ]; then
        if printf "%s\n" "$desired_content" > "$wrapper_path" 2>/dev/null; then
            chmod +x "$wrapper_path" 2>/dev/null || true
            log_ok "Registered global command '${GLOBAL_CMD_NAME}' -> ${wrapper_path}"
        fi
    fi

    if [ "$IS_TERMUX" -eq 0 ] && [[ ":$PATH:" != *":$target_bin_dir:"* ]]; then
        export PATH="$target_bin_dir:$PATH"
        local marker="# NVIDIAFKU PATH"
        local path_line="export PATH=\"\$HOME/.local/bin:\$PATH\""
        local updated_rc=""
        for rc_file in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
            if [ -f "$rc_file" ] && ! grep -Fq "$marker" "$rc_file" 2>/dev/null && ! grep -Fq ".local/bin" "$rc_file" 2>/dev/null; then
                printf "\n%s\n%s\n" "$marker" "$path_line" >> "$rc_file" 2>/dev/null && updated_rc="$rc_file"
            fi
        done
        if [ -n "$updated_rc" ]; then
            log_info "Added ~/.local/bin to ${updated_rc}. Restart terminal to run '${GLOBAL_CMD_NAME}' anywhere."
        fi
    fi
}

register_global_command

# -----------------------------------------------------------------------------
# 10 & 11. Launch Application (`cli.py`)
# -----------------------------------------------------------------------------
if [ ! -f "$PROJECT_ROOT/$ENTRY_POINT" ]; then
    log_err "Entry point not found: $PROJECT_ROOT/$ENTRY_POINT"
    exit 1
fi

log_ok "Environment ready! Launching ${APP_NAME} (${ENTRY_POINT})..."
sleep 0.35

if [ "${#APP_ARGS[@]}" -gt 0 ]; then
    "$ACTIVE_PYTHON" "$PROJECT_ROOT/$ENTRY_POINT" "${APP_ARGS[@]}"
else
    "$ACTIVE_PYTHON" "$PROJECT_ROOT/$ENTRY_POINT"
fi
EXIT_CODE=$?

cleanup_terminal
exit "$EXIT_CODE"
