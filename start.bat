@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================================
:: start.bat — Zero-Touch Windows Launcher for NVIDIAFKU Engine (by ai_sahil_)
:: Features:
::   - Auto-detects & Auto-installs Python 3.12 (via Winget or Official Python.org
::     silent user-level installer — NO Admin rights required!)
::   - Cyberpunk Neon Green & Red Animated Spinner + Progress Bar
::   - Safe Git Auto-Update, Auto .venv, Auto Dependency Install & Global Command
::   - Launches cli.py
:: ============================================================================

:: 1. Switch to Project Root Directory (handles spaces and cross-drive paths)
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
pushd "%PROJECT_ROOT%" || (
    echo [ERROR] Failed to switch to project directory: "%PROJECT_ROOT%"
    exit /b 1
)

:: Enable UTF-8 console encoding for box-drawing, Braille spinners & emojis
chcp 65001 >nul 2>&1

set "APP_NAME=NVIDIAFKU"
set "APP_AUTHOR=ai_sahil_"
set "ENTRY_POINT=cli.py"
set "GLOBAL_CMD_NAME=nvidiafku"
set "VENV_DIR=%PROJECT_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%PROJECT_ROOT%\requirements.txt"
set "DEPS_STAMP=%VENV_DIR%\.nvidiafku_deps_installed"

:: ANSI Escape Sequences
for /f %%A in ('echo prompt $E ^| cmd') do set "ESC=%%A"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
set "DIM=%ESC%[2m"
set "NEON_GREEN=%ESC%[38;5;46m"
set "NEON_RED=%ESC%[38;5;196m"
set "CYBER_CYAN=%ESC%[38;5;51m"
set "AMBER_GOLD=%ESC%[38;5;214m"
set "WHITE=%ESC%[97m"
set "GRAY=%ESC%[38;5;244m"

:: Parse Launcher Flags
set "SKIP_UPDATE=0"
if /i "%NVIDIAFKU_NO_UPDATE%"=="1" set "SKIP_UPDATE=1"
if /i "%NVIDIAFKU_NO_UPDATE%"=="true" set "SKIP_UPDATE=1"
set "FORCE_DEPS=0"
set "FORWARD_ARGS="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-update" (
    set "SKIP_UPDATE=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--reinstall-deps" (
    set "FORCE_DEPS=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--launcher-help" (
    call :print_banner
    echo.
    echo   %BOLD%%WHITE%Launcher Options:%RESET%
    echo     %NEON_GREEN%--no-update%RESET%       Skip Git auto-update check on startup
    echo     %NEON_GREEN%--reinstall-deps%RESET%  Force re-verification ^& installation of dependencies
    echo     %NEON_GREEN%--launcher-help%RESET%   Show this launcher help message
    echo.
    popd
    exit /b 0
)
set "FORWARD_ARGS=!FORWARD_ARGS! "%~1""
shift
goto :parse_args

:args_done

:: 2. Display Startup Banner
call :print_banner
echo   %BOLD%%CYBER_CYAN%[INFO]%RESET% Platform detected: Windows
echo   %BOLD%%CYBER_CYAN%[INFO]%RESET% Project root     : "%PROJECT_ROOT%"

:: 3. Optional Safe Git Auto-Update
if "%SKIP_UPDATE%"=="1" (
    echo   %BOLD%%CYBER_CYAN%[INFO]%RESET% Git auto-update skipped.
    goto :detect_python
)

where git >nul 2>&1
if errorlevel 1 goto :detect_python
if not exist "%PROJECT_ROOT%\.git" goto :detect_python

set "UPSTREAM_BRANCH="
for /f "delims=" %%U in ('git rev-parse --abbrev-ref --symbolic-full-name @{u} 2^>nul') do set "UPSTREAM_BRANCH=%%U"
if not defined UPSTREAM_BRANCH goto :detect_python

set "GIT_TERMINAL_PROMPT=0"
call :run_animated "Checking Git upstream (!UPSTREAM_BRANCH!) for updates" "git fetch --quiet"
if errorlevel 1 (
    echo   %BOLD%%AMBER_GOLD%[WARN]%RESET% Offline or unable to reach Git remote. Continuing with local version.
    goto :detect_python
)

set "LOCAL_SHA="
set "REMOTE_SHA="
set "BASE_SHA="
for /f "delims=" %%L in ('git rev-parse @ 2^>nul') do set "LOCAL_SHA=%%L"
for /f "delims=" %%R in ('git rev-parse @{u} 2^>nul') do set "REMOTE_SHA=%%R"
for /f "delims=" %%B in ('git merge-base @ @{u} 2^>nul') do set "BASE_SHA=%%B"

if not defined LOCAL_SHA goto :detect_python
if not defined REMOTE_SHA goto :detect_python
if "!LOCAL_SHA!"=="!REMOTE_SHA!" (
    echo   %BOLD%%NEON_GREEN%[ ✔ ]%RESET%  Repository is up to date.
    goto :detect_python
)

if "!LOCAL_SHA!"=="!BASE_SHA!" (
    git diff --quiet >nul 2>&1
    if errorlevel 1 (
        echo   %BOLD%%AMBER_GOLD%[WARN]%RESET% Updates available, but uncommitted local changes detected. Preserving work.
        goto :detect_python
    )
    git diff --cached --quiet >nul 2>&1
    if errorlevel 1 (
        echo   %BOLD%%AMBER_GOLD%[WARN]%RESET% Updates available, but staged changes detected. Preserving work.
        goto :detect_python
    )
    call :run_animated "Applying fast-forward Git update" "git merge --ff-only @{u}"
    if not errorlevel 1 (
        echo   %BOLD%%NEON_GREEN%[ ✔ ]%RESET%  Updated %APP_NAME% to latest commit.
        set "FORCE_DEPS=1"
    )
)

:: 4. Python 3 Detection & AUTOMATIC INSTALLATION (If Missing!)
:detect_python
call :find_python
if defined BASE_PYTHON goto :python_ready

echo   %BOLD%%AMBER_GOLD%[WARN]%RESET% Python 3.8+ not found. Starting zero-touch automatic Python 3.12 installation...

:: Method A: Try Winget User-Scope Install (No Administrator prompt required)
where winget >nul 2>&1
if not errorlevel 1 (
    call :run_animated "Auto-installing Python 3.12 via Windows Package Manager (winget)" "winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements"
    call :refresh_env_path
    call :find_python
    if defined BASE_PYTHON goto :python_ready
)

:: Method B: Official Python.org Silent Per-User Installer via PowerShell (Works on all Windows 10/11 systems)
set "PY_INSTALLER=%TEMP%\python-3.12.8-amd64.exe"
call :run_animated "Downloading official Python 3.12.8 installer from python.org" "powershell -NoProfile -ExecutionPolicy Bypass -Command \"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile '%PY_INSTALLER%' -UseBasicParsing\""
if exist "%PY_INSTALLER%" (
    call :run_animated "Installing Python 3.12 (User Scope + PATH + pip)" "\"%PY_INSTALLER%\" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_venv=1 Include_test=0"
    del /q "%PY_INSTALLER%" >nul 2>&1
    call :refresh_env_path
    call :find_python
    if defined BASE_PYTHON goto :python_ready
)

echo   %BOLD%%NEON_RED%[ ✖ ]%RESET%  Automatic Python installation could not complete.
echo          Please install Python 3.12 from %NEON_GREEN%https://www.python.org/downloads/windows/%RESET%
echo          (Be sure to check "Add python.exe to PATH") and re-run start.bat.
popd
exit /b 1

:python_ready
for /f "delims=" %%V in ('!BASE_PYTHON! -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"') do set "PY_VER=%%V"
echo   %BOLD%%NEON_GREEN%[ ✔ ]%RESET%  Python runtime ready: !BASE_PYTHON! (v!PY_VER!)

:: 6. Virtual Environment (.venv\Scripts\python.exe)
if not exist "%VENV_PYTHON%" (
    call :run_animated "Creating isolated virtual environment (.venv)" "!BASE_PYTHON! -m venv \"%VENV_DIR%\""
    if errorlevel 1 (
        echo   %BOLD%%NEON_RED%[ ✖ ]%RESET%  Failed to create virtual environment at "%VENV_DIR%".
        popd
        exit /b 1
    )
    set "FORCE_DEPS=1"
)

"%VENV_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    call :run_animated "Bootstrapping pip inside .venv" "\"%VENV_PYTHON%\" -m ensurepip --upgrade"
)

:: 7 & 8. Animated Automatic Dependency Installation & Verification
set "NEEDS_INSTALL=%FORCE_DEPS%"
if "%NEEDS_INSTALL%"=="0" (
    "%VENV_PYTHON%" -c "import flask, werkzeug, requests, urllib3, cryptography, rich" >nul 2>&1
    if errorlevel 1 set "NEEDS_INSTALL=1"
)
if "%NEEDS_INSTALL%"=="0" (
    if not exist "%DEPS_STAMP%" set "NEEDS_INSTALL=1"
)

if "%NEEDS_INSTALL%"=="1" (
    if exist "%REQ_FILE%" (
        call :run_animated "Installing NVIDIAFKU dependencies (Flask, Cryptography, Rich, Requests)" "\"%VENV_PYTHON%\" -m pip install --disable-pip-version-check --no-input -r \"%REQ_FILE%\""
    ) else (
        call :run_animated "Installing NVIDIAFKU dependencies (Flask, Cryptography, Rich, Requests)" "\"%VENV_PYTHON%\" -m pip install --disable-pip-version-check --no-input flask>=3.0.0 werkzeug>=3.0.0 requests>=2.31.0 urllib3>=2.0.0 cryptography>=42.0.0 rich>=13.7.0"
    )
    if errorlevel 1 (
        echo.
        echo   %BOLD%%NEON_RED%[ ✖ ]%RESET%  Failed to install required Python dependencies!
        echo   %BOLD%%AMBER_GOLD%Troubleshooting:%RESET% Check your internet connection and run:
        echo     %NEON_GREEN%start.bat --reinstall-deps%RESET%
        popd
        exit /b 1
    )

    "%VENV_PYTHON%" -c "import flask, werkzeug, requests, urllib3, cryptography, rich" >nul 2>&1
    if errorlevel 1 (
        echo   %BOLD%%NEON_RED%[ ✖ ]%RESET%  Dependency verification failed after installation.
        popd
        exit /b 1
    )
    type nul > "%DEPS_STAMP%" 2>nul
) else (
    echo   %BOLD%%NEON_GREEN%[ ✔ ]%RESET%  All runtime dependencies verified (flask, werkzeug, requests, cryptography, rich).
)

:: 9. Global Convenience Command Registration (`nvidiafku`)
set "USER_BIN_DIR=%USERPROFILE%\.local\bin"
if not exist "%USER_BIN_DIR%" mkdir "%USER_BIN_DIR%" >nul 2>&1
set "GLOBAL_CMD_FILE=%USER_BIN_DIR%\%GLOBAL_CMD_NAME%.cmd"

(
    echo @echo off
    echo call "%PROJECT_ROOT%\start.bat" %%*
) > "%GLOBAL_CMD_FILE%" 2>nul

echo ";%PATH%;" | findstr /I /C:";%USER_BIN_DIR%;" >nul 2>&1
if errorlevel 1 (
    set "PATH=%USER_BIN_DIR%;%PATH%"
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$uPath = [Environment]::GetEnvironmentVariable('Path', 'User'); if (-not $uPath) { $uPath = '' }; $bin = '%USER_BIN_DIR%'; if (($uPath -split ';') -notcontains $bin) { $newPath = if ($uPath) { $uPath.TrimEnd(';') + ';' + $bin } else { $bin }; [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'); Write-Output 'ADDED' }" 2>nul | findstr /C:"ADDED" >nul 2>&1
    if not errorlevel 1 (
        echo   %BOLD%%NEON_GREEN%[ ✔ ]%RESET%  Registered global command '%GLOBAL_CMD_NAME%' in "%USER_BIN_DIR%".
    )
)

:: 10 & 11. Application Startup (`cli.py`)
if not exist "%PROJECT_ROOT%\%ENTRY_POINT%" (
    echo   %BOLD%%NEON_RED%[ ✖ ]%RESET%  Entry point not found: "%PROJECT_ROOT%\%ENTRY_POINT%"
    popd
    exit /b 1
)

echo   %BOLD%%NEON_GREEN%[ ✔ ]%RESET%  Environment ready! Launching %APP_NAME% (%ENTRY_POINT%)...
echo.

"%VENV_PYTHON%" "%PROJECT_ROOT%\%ENTRY_POINT%" !FORWARD_ARGS!
set "APP_EXIT_CODE=%ERRORLEVEL%"

echo %ESC%[?25h
popd
exit /b %APP_EXIT_CODE%


:: ============================================================================
:: HELPER SUBROUTINES
:: ============================================================================

:find_python
set "BASE_PYTHON="
:: Check standard User-Scope Python install directories first in case PATH was just updated
for %%D in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python312\python.exe"
) do (
    if exist %%D (
        %%D -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "BASE_PYTHON=%%D"
            exit /b 0
        )
    )
)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "BASE_PYTHON=py -3"
        exit /b 0
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "BASE_PYTHON=python"
        exit /b 0
    )
)
exit /b 1

:refresh_env_path
for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')" 2^>nul') do (
    set "PATH=%%P"
)
exit /b 0

:run_animated
:: Runs a command in the background with a Cyberpunk Neon Green & Red Braille spinner + progress bar
set "ANIM_LABEL=%~1"
set "ANIM_CMD=%~2"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$label = $env:ANIM_LABEL; $cmd = $env:ANIM_CMD; " ^
    "$logOut = [System.IO.Path]::GetTempFileName(); $logErr = [System.IO.Path]::GetTempFileName(); " ^
    "$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/d', '/s', '/c', $cmd -NoNewWindow -PassThru -RedirectStandardOutput $logOut -RedirectStandardError $logErr; " ^
    "$frames = @('⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'); " ^
    "$bars = @('█░░░░░░░░░','██░░░░░░░░','███░░░░░░░','████░░░░░░','█████░░░░░','██████░░░░','███████░░░','████████░░','█████████░','██████████'); " ^
    "$e = [char]27; $g = \"$e[38;5;46m\"; $r = \"$e[38;5;196m\"; $w = \"$e[97m\"; $d = \"$e[2m\"; $rst = \"$e[0m\"; " ^
    "[Console]::CursorVisible = $false; $i = 0; " ^
    "while (-not $p.HasExited) { " ^
    "  $f = $frames[$i %% 10]; $b = $bars[$i %% 10]; " ^
    "  $c = if (($i %% 10) -lt 5) { $g } else { $r }; " ^
    "  Write-Host -NoNewline (\"`r  $e[1m$g$f$rst $d[$rst$c$b$rst$d]$rst$w$label$rst   \"); " ^
    "  Start-Sleep -Milliseconds 85; $i++; " ^
    "} " ^
    "$p.WaitForExit();$code = $p.ExitCode; [Console]::CursorVisible =$true; " ^
    "if ($code -eq 0) { " ^
    "  Write-Host (\"`r  $e[1m$g[ ✔ ]$rst $d[$g\" + '██████████' + \"$rst$d]$rst $w$label$rst       \"); " ^
    "} else { " ^
    "  Write-Host (\"`r  $e[1m$r[ ✖ ]$rst $d[$r\" + '██████████' + \"$rst$d]$rst$r$label (FAILED)$rst       \"); " ^
    "  Get-Content $logOut,$logErr -ErrorAction SilentlyContinue | Select-Object -Last 20 | ForEach-Object { Write-Host \"    $_\" -ForegroundColor Red }; " ^
    "} " ^
    "Remove-Item $logOut, $logErr -Force -ErrorAction SilentlyContinue; exit$code"
exit /b %ERRORLEVEL%

:print_banner
echo.
echo %NEON_GREEN%╔══════════════════════════════════════════════════════════════════════════╗%RESET%
echo %NEON_GREEN%║%RESET%  %BOLD%%NEON_GREEN%⚡ NVIDIA%NEON_RED%FKU%RESET% %BOLD%%NEON_RED%by %NEON_GREEN%%APP_AUTHOR%%RESET% %DIM%%GRAY%— Zero-Touch Auto-Setup ^& Launcher%RESET%          %NEON_RED%║%RESET%
echo %NEON_GREEN%║%RESET%  %CYBER_CYAN%Dual-Stack HTTP (5000) + HTTPS/LAN (8443) NVIDIA NIM Engine%RESET%             %NEON_RED%║%RESET%
echo %NEON_RED%╚══════════════════════════════════════════════════════════════════════════╝%RESET%
exit /b 0