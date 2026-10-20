# nvidiafku
NVIDIAFKU || Nvidia API endpoint cleanup to use for roleplay and normal use. 

---

## ⚡ Quick Start — One-Command Auto-Setup & Launch

**NVIDIAFKU (by `ai_sahil_`)** features a zero-touch startup system. You just paste one line into your terminal — it automatically checks/installs Python 3, sets up `.venv`, installs all required dependencies, registers the global command, and launches the interactive dashboard (`cli.py`).

---

# AVAILABLE MODELS

| Model | Specifications | Context Length | Parameters | Input Modalities | Output Modalities |
|---|---|---|---|---|---|
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | Nemotron 3.5 Super early-access reasoning model for agentic, coding, tool-calling, and multimodal workloads | 262K | 124B | Text, Image | Text |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | Fastest 30B A3B MoE model with leading domain accuracy for specialized agentic tasks | 1M | 30B | Text | Text |
| `nvidia/nemotron-3-ultra-550b-a55b` | Open, efficient hybrid Mamba-Transformer MoE with 1M context, excelling in agentic reasoning, coding, planning, tool calling, and more | 1M | 561B | Text | Text |
| `openai/gpt-oss-20b` | Smaller Mixture of Experts (MoE) text-only LLM for efficient AI reasoning and math | 131K | 21B | Text | Text |
There are other text models also available but these are stable and ready to use for roleplay and coding tools.

#Steps to get Nvidia API
1. go to `https://build.nvidia.com/models`
2. on the top right corner click on **Login**
3. Enter your email and login
4. click on the profile on the top right corner if you are logged in then the login should be replaced by it.
5. You will Get three options click on API Keys.
6. Click on Generate API keys name it and select the expiration date. <span style="color:red;">Note that the api will expire after that time period. </span>
7. copy the api key and then update it inside the CLI or your required destination.



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

About the API key 
1. Either you can update the api in the cli for persistence and then fill out anything on the janitor website or other tools
2.  or you can fill the nvidia api directly on the janitor website or other tools

choose whatever suits you the script will automatically understand it. 


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
