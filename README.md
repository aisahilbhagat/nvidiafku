# nvidiafku
NVIDIAFKU || Nvidia API endpoint cleanup to use for roleplay and normal use. 

---

## ⚡ Quick Start — One-Command Auto-Setup & Launch

**NVIDIAFKU (by `ai_sahil_`)** features a zero-touch startup system. You just paste one line into your terminal — it automatically checks/installs Python 3, sets up `.venv`, installs all required dependencies, registers the global command, and launches the interactive dashboard (`cli.py`).

---

### 📱 1. Android (Termux)

Open **Termux** and paste this single command:

```bash
pkg update -y && pkg install -y python git openssl-tool && git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && chmod +x start.sh && ./start.sh

```

# WELL I DESIGNED IT KEEPING IS MIND FOR PROFESSIONAL WORK AND RP TOO SO HERE ARE THE CONFIG FOR ROPEPLAY 

| Setting | Value |
|---|---|
| **API Architecture** | `OpenAI` |
| **Reverse Proxy URL** | `http://localhost:5000/v1/chat/completions` |
| **API Key** | `anything` (if you havent fill in the cli fill your nvidia api here other wise anything) |
| **Model** | `nvidia/nemotron-3.5-super-vl-120b-a12b` (see more from the list) |


---

### 🪟 2. Windows (CMD or PowerShell) 
<span style="color:red;">This command expects git to be installed on your windows PC so ensure its installed</span>
<span style="color:green;">If you are smart just download it and unzip it and then run the start.bat .</span>




**Option A — Using Command Prompt (`cmd.exe`):**

```cmd
git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && start.bat

```

**Option B — Using PowerShell:**

```powershell
git clone https://github.com/aisahilbhagat/nvidiafku.git; cd nvidiafku; .\start.bat

```

*(Or simply open the `nvidiafku` folder in File Explorer and double-click **`start.bat`**!)*

---

### 🐧 3. Linux (Ubuntu / Debian / Arch / Fedora)

<span style="color:red;"><bold>I haven't test on the Any of these Linux distros. So if any problem occurs do tell me.</bold></span>


Open your terminal and run:

```bash
git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && chmod +x start.sh && ./start.sh

```

---

### 🍎 4. macOS (Terminal or Finder)

<span style="color:red;"><bold>I haven't test on the MacOS because I am poor.. So if any problem occurs do tell me.</bold></span>

Open **Terminal** and run:

```bash
git clone https://github.com/aisahilbhagat/nvidiafku.git && cd nvidiafku && chmod +x start.sh start.command && ./start.command

```

*(After the first run, you can also double-click **`start.command`** directly inside Finder!)*

---

## 🚀 Launching Every Time After First Setup

Once you have run the setup command above at least once, a global shortcut command is automatically registered on your system. Next time you open a terminal from **any folder**, simply type:

```bash
nvidiafku

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
