# nvidiafku
NVIDIAFKU || Nvidia API endpoint cleanup to use for roleplay and normal use. 

---

## ⚡ Quick Start — One-Command Auto-Setup & Launch

**NVIDIAFKU (by `ai_sahil_`)** features a zero-touch startup system. You just paste one line into your terminal — it automatically checks/installs Python 3, sets up `.venv`, installs all required dependencies, registers the global command, and launches the interactive dashboard (`cli.py`).

---

### 📱 1. Android (Termux)

Open **Termux** and paste this single command:

```bash
pkg update -y && pkg install -y python git && git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && chmod +x start.sh && ./start.sh

```

---

### 🪟 2. Windows (CMD or PowerShell)

**Option A — Using Command Prompt (`cmd.exe`):**

```cmd
git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && start.bat

```

**Option B — Using PowerShell:**

```powershell
git clone https://github.com/aisahilbhagat/nvidiafku.git; cd nvidiafku; .\start.bat

```

*(Or simply open the `nvdfk` folder in File Explorer and double-click **`start.bat`**!)*

---

### 🐧 3. Linux (Ubuntu / Debian / Arch / Fedora)

Open your terminal and run:

```bash
git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && chmod +x start.sh && ./start.sh

```

---

### 🍎 4. macOS (Terminal or Finder)

Open **Terminal** and run:

```bash
git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && chmod +x start.sh start.command && ./start.command

```

*(After the first run, you can also double-click **`start.command`** directly inside Finder!)*

---

## 🚀 Launching Every Time After First Setup

Once you have run the setup command above at least once, a global shortcut command is automatically registered on your system. Next time you open a terminal from **any folder**, simply type:

```bash
nvdfk

```
---

## 🛠️ Optional Launcher Flags

If you ever need to bypass the automatic Git update check or force a clean dependency reinstall, you can pass these flags to the launcher:

* **Skip Git Auto-Update:**
```bash
./start.sh --no-update
# Or on Windows: start.bat --no-update

```


* **Force Reinstall Dependencies:**
```bash
./start.sh --reinstall-deps
# Or on Windows: start.bat --reinstall-deps

```
