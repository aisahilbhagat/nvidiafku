#!/usr/bin/env bash
# =============================================================================
# start.command — macOS Finder & Terminal Launcher for NVIDIAFKU (by ai_sahil_)
# =============================================================================

set -u

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
cd "$PROJECT_ROOT" || exit 1

if [ -d "/opt/homebrew/bin" ] && [[ ":$PATH:" != *":/opt/homebrew/bin:"* ]]; then
    export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
fi
if [ -d "/usr/local/bin" ] && [[ ":$PATH:" != *":/usr/local/bin:"* ]]; then
    export PATH="/usr/local/bin:/usr/local/sbin:$PATH"
fi

chmod +x "$PROJECT_ROOT/start.sh" 2>/dev/null || true
"$PROJECT_ROOT/start.sh" "$@"
EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ] && [ -t 0 ]; then
    echo ""
    read -r -p "Press [Enter] to close this window..." _
fi

exit "$EXIT_CODE"