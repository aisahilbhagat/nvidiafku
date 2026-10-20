import os
import re
import json
import time
import logging
import threading
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, request, Response, jsonify

# =====================================================================
# UNIVERSAL NVIDIA NIM ENGINE — CORE CONFIGURATION & STATE REGISTRY
# =====================================================================
HARDCODED_API_KEY = ""
ENV_API_KEY = os.environ.get("NVIDIA_API_KEY", "")

DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
PORT = int(os.environ.get("ENGINE_PORT", 5000))


# =====================================================================
# COLORFUL CONSOLE LOGGER & SILENT WERKZEUG ACCESS LOGS
# =====================================================================
# Enable ANSI escape sequences on Windows/Termux/Linux
os.system("")

# Silence noisy default Flask/Werkzeug "127.0.0.1 - - [Date] POST ..." logs
logging.getLogger("werkzeug").setLevel(logging.ERROR)


class TermColors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    WHITE = "\033[97m"


def log_generation_event(model_name, generated_ok, output_tokens, total_tokens, error_detail=None):
    """
    Prints a single, clean, colorful log line per request:
    [HH:MM:SS] 🤖 Model | ✅ GENERATED (or ❌ FAILED) | 📝 Out: X tok | 📊 Total: Y tok
    """
    now_str = datetime.now().strftime("%H:%M:%S")
    c = TermColors

    if generated_ok:
        status_badge = f"{c.BOLD}{c.GREEN}✅ GENERATED{c.RESET}"
    else:
        reason = f" ({error_detail})" if error_detail else ""
        status_badge = f"{c.BOLD}{c.RED}❌ FAILED{reason}{c.RESET}"

    print(
        f"{c.DIM}[{now_str}]{c.RESET} "
        f"{c.BOLD}{c.MAGENTA}🤖 {model_name}{c.RESET} "
        f"{c.DIM}|{c.RESET} {status_badge} "
        f"{c.DIM}|{c.RESET} {c.CYAN}📝 Out: {c.BOLD}{output_tokens}{c.RESET}{c.CYAN} tok{c.RESET} "
        f"{c.DIM}|{c.RESET} {c.YELLOW}📊 Total: {c.BOLD}{total_tokens}{c.RESET}{c.YELLOW} tok{c.RESET}",
        flush=True
    )


class EngineCore:
    """
    Central stateful engine and plugin bus designed for seamless integration with:
      1. roleplay.py     -> Registers custom RP pre/post hooks, system prompts, and presets
      2. server.py       -> Imports `app` or `engine` for Gunicorn/Uvicorn/Waitress & custom session scaling
      3. model_switch.py -> Dynamically switches active models and updates the model registry
      4. cli.py          -> Controls runtime config via Python API or `/v1/engine/*` REST endpoints
    """
    def __init__(self):
        self.lock = threading.RLock()
        self.start_time = time.time()

        # Dynamic Runtime Configuration (Controllable via CLI / REST API / External Modules)
        self.config = {
            "active_model": DEFAULT_MODEL,
            "force_active_model": True,       # If False, honors valid NVIDIA models requested by client
            "default_thinking": False,        # Default thinking state when not specified by request
            "expose_reasoning": False,        # When thinking=True, whether to keep or strip reasoning_content
            "rp_mode": False,                 # Controlled by roleplay.py (adds RP-specific prompt nudges if True)
            "custom_system_prefix": "",       # Optional system prompt prefix injected by roleplay.py or CLI
            "vision_enabled": True,           # Enables multimodal image_url array passthrough for VL models
            "strip_empty_max_tokens": True,   # Lets client/NVIDIA decide token limits (drops 0/None limits)
            "connect_timeout": 15,
            "read_timeout": 300,              # Extended timeout for large coding files & vision tasks
        }

        # Dynamic API Key Store
        self.api_keys = {
            "hardcoded": HARDCODED_API_KEY,
            "env": ENV_API_KEY,
            "runtime_override": ""            # Set via CLI or /v1/engine/apikey
        }

        # Dynamic Model Registry (Populated/Managed by model_switch.py)
        self.model_registry = {
            DEFAULT_MODEL: {
                "id": DEFAULT_MODEL,
                "owned_by": "nvidia",
                "vision": True,
                "thinking_capable": True,
                "tools_capable": True,
                "description": "NVIDIA Nemotron 3.5 Super VL 120B (Text + Vision + Coding + RP)"
            }
        }

        # Telemetry & Diagnostics (Read by cli.py and server.py)
        self.metrics = {
            "total_requests": 0,
            "streaming_requests": 0,
            "vision_requests": 0,
            "tool_requests": 0,
            "errors": 0,
            "last_error": None,
            "last_request_timestamp": None,
            # Token Tracking (Accessible by cli.py, server.py, roleplay.py)
            "current_input_tokens": 0,
            "current_output_tokens": 0,
            "last_response_output_tokens": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

        # Extension Hook Pipelines for future modules (roleplay.py, model_switch.py, server.py)
        self.hooks = {
            "pre_process_request": [],        # fn(req_data, context) -> req_data
            "pre_clean_messages": [],         # fn(messages, context) -> messages
            "post_clean_messages": [],        # fn(messages, context) -> messages
            "pre_upstream_payload": [],       # fn(safe_payload, context) -> safe_payload
            "post_response_chunk": [],        # fn(token_text, context) -> token_text
            "post_full_response": [],         # fn(response_dict, context) -> response_dict
            "on_model_switch": [],            # fn(old_model, new_model)
        }

    # --- Hook Registration Circuitry for External Modules ---
    def register_hook(self, hook_name, callback):
        """Allows roleplay.py, model_switch.py, or server.py to attach middleware hooks."""
        with self.lock:
            if hook_name not in self.hooks:
                raise ValueError(f"Unknown hook '{hook_name}'. Valid hooks: {list(self.hooks.keys())}")
            if callback not in self.hooks[hook_name]:
                self.hooks[hook_name].append(callback)

    def clear_hooks(self, hook_name=None):
        """Clears registered hooks (useful when toggling roleplay.py on/off via CLI)."""
        with self.lock:
            if hook_name:
                self.hooks[hook_name] = []
            else:
                for k in self.hooks:
                    self.hooks[k] = []

    def run_hooks(self, hook_name, data, context):
        """Executes all registered callbacks for a specific lifecycle stage."""
        callbacks = list(self.hooks.get(hook_name, []))
        for cb in callbacks:
            try:
                result = cb(data, context)
                if result is not None:
                    data = result
            except Exception as e:
                print(f"[Engine Hook Error in {hook_name}]: {e}")
        return data

    # --- Model Management Circuitry for model_switch.py ---
    def register_model(self, model_id, vision=True, thinking_capable=True, tools_capable=True, description=""):
        with self.lock:
            self.model_registry[model_id] = {
                "id": model_id,
                "owned_by": "nvidia",
                "vision": vision,
                "thinking_capable": thinking_capable,
                "tools_capable": tools_capable,
                "description": description or model_id
            }

    def switch_model(self, new_model_id, register_if_missing=True):
        with self.lock:
            old_model = self.config["active_model"]
            if register_if_missing and new_model_id not in self.model_registry:
                self.register_model(new_model_id)
            self.config["active_model"] = new_model_id
            for cb in self.hooks["on_model_switch"]:
                try:
                    cb(old_model, new_model_id)
                except Exception as e:
                    print(f"[Model Switch Hook Error]: {e}")
            return old_model, new_model_id

    def update_config(self, updates: dict):
        with self.lock:
            for k, v in updates.items():
                if k in self.config:
                    self.config[k] = v
            return dict(self.config)

    # --- Token Counter Circuitry for CLI & External Modules ---
    def record_input_tokens(self, input_tokens: int):
        """Records the input token count for the active request."""
        with self.lock:
            self.metrics["current_input_tokens"] = int(input_tokens)
            self.metrics["current_output_tokens"] = 0

    def update_live_output_tokens(self, output_tokens: int):
        """Updates the live output token length while a response is actively streaming."""
        with self.lock:
            self.metrics["current_output_tokens"] = int(output_tokens)

    def finalize_token_counts(self, input_tokens: int, output_tokens: int):
        """Finalizes token counts at the end of a request and updates cumulative totals."""
        with self.lock:
            in_tok = int(input_tokens)
            out_tok = int(output_tokens)
            self.metrics["current_input_tokens"] = in_tok
            self.metrics["current_output_tokens"] = out_tok
            self.metrics["last_response_output_tokens"] = out_tok
            self.metrics["total_input_tokens"] += in_tok
            self.metrics["total_output_tokens"] += out_tok

    def get_token_stats(self):
        """Direct Python API for cli.py / server.py to query token counters."""
        with self.lock:
            return {
                "current_input_tokens": self.metrics["current_input_tokens"],
                "current_output_tokens": self.metrics["current_output_tokens"],
                "last_response_output_tokens": self.metrics["last_response_output_tokens"],
                "total_input_tokens": self.metrics["total_input_tokens"],
                "total_output_tokens": self.metrics["total_output_tokens"],
            }


# Instantiate global singleton engine for standalone or external module import
engine = EngineCore()
app = Flask(__name__)


# =====================================================================
# PERSISTENT SESSION SETUP (Reusable & Overrideable by server.py)
# =====================================================================
def create_persistent_session(pool_connections=50, pool_maxsize=50):
    """
    Creates a high-concurrency persistent HTTP session with connection pooling
    and automatic retries for NVCF cold-starts and socket drops.
    `server.py` can call `set_http_session()` to inject custom adapters or proxies.
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        max_retries=retry_strategy
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


http_session = create_persistent_session()


def set_http_session(custom_session):
    """Hook for server.py to replace the HTTP session with a custom-tuned pool."""
    global http_session
    http_session = custom_session


# =====================================================================
# UNIVERSAL CORS MIDDLEWARE (Works with JanitorAI, Web UIs, VS Code, Browser Extensions)
# =====================================================================
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin:
        # Echo exact Origin so browsers allow credentials + Private Network Access (localhost / 127.0.0.1)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers.pop("Access-Control-Allow-Credentials", None)

    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    req_headers = request.headers.get("Access-Control-Request-Headers")
    if req_headers:
        response.headers["Access-Control-Allow-Headers"] = req_headers
    else:
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Requested-With, Accept, Origin, "
            "X-Thinking, X-Enable-Thinking, X-Model-Override, X-RP-Mode, OpenAI-Beta, HTTP-Referer, X-Title"
        )

    # Required by Chrome / Edge / Brave for HTTPS websites calling http://127.0.0.1 or localhost
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.route("/v1/chat/completions", methods=["OPTIONS"])
@app.route("/chat/completions", methods=["OPTIONS"])
@app.route("/v1/models", methods=["OPTIONS"])
@app.route("/models", methods=["OPTIONS"])
@app.route("/v1/engine/<path:subpath>", methods=["OPTIONS"])
def handle_options(subpath=None):
    return Response(status=204)

# =====================================================================
# API KEY RESOLUTION & DYNAMIC THINKING / MODEL RESOLVERS
# =====================================================================
def is_valid_nvapi_key(key):
    """Checks if a key is non-empty and matches NVIDIA's 'nvapi-' format."""
    if not key or not isinstance(key, str):
        return False
    cleaned_key = key.strip()
    return (
        cleaned_key.startswith("nvapi-")
        and len(cleaned_key) > 20
        and cleaned_key != "nvapi-YOUR-KEY-HERE"
    )


def resolve_api_key(req):
    """
    Priority Order:
    1. Runtime CLI/API override key (`engine.api_keys['runtime_override']`) if valid.
    2. `HARDCODED_API_KEY` if it is a valid `nvapi-...` key.
    3. Incoming request `Authorization: Bearer nvapi-...` header (from JanitorAI, VS Code, etc.).
    4. `NVIDIA_API_KEY` environment variable fallback.
    """
    runtime_key = engine.api_keys.get("runtime_override", "")
    if is_valid_nvapi_key(runtime_key):
        return runtime_key.strip()

    hardcoded_key = engine.api_keys.get("hardcoded", "")
    if is_valid_nvapi_key(hardcoded_key):
        return hardcoded_key.strip()

    auth_header = req.headers.get("Authorization", "")
    incoming_key = auth_header.replace("Bearer ", "").replace("bearer ", "").strip()
    if is_valid_nvapi_key(incoming_key):
        return incoming_key

    env_key = engine.api_keys.get("env", "")
    if is_valid_nvapi_key(env_key):
        return env_key.strip()

    return incoming_key or hardcoded_key


def resolve_thinking_mode(req_data, req_headers):
    """
    Dynamically determines whether thinking mode should be ON or OFF for this specific request.
    """
    # 1. Check HTTP Headers
    header_val = req_headers.get("X-Thinking") or req_headers.get("X-Enable-Thinking")
    if header_val is not None:
        return str(header_val).strip().lower() in ["true", "1", "on", "yes", "enabled"]

    # 2. Check nested chat_template_kwargs or extra_body
    for container_key in ["chat_template_kwargs", "extra_body"]:
        sub = req_data.get(container_key)
        if isinstance(sub, dict):
            if "thinking" in sub and isinstance(sub["thinking"], bool):
                return sub["thinking"]
            if "enable_thinking" in sub and isinstance(sub["enable_thinking"], bool):
                return sub["enable_thinking"]
            nested_ctk = sub.get("chat_template_kwargs")
            if isinstance(nested_ctk, dict):
                if "thinking" in nested_ctk:
                    return bool(nested_ctk["thinking"])
                if "enable_thinking" in nested_ctk:
                    return bool(nested_ctk["enable_thinking"])

    # 3. Check top-level `enable_thinking` or `thinking`
    if "enable_thinking" in req_data:
        return bool(req_data["enable_thinking"])

    if "thinking" in req_data:
        t_val = req_data["thinking"]
        if isinstance(t_val, bool):
            return t_val
        if isinstance(t_val, dict):
            t_type = str(t_val.get("type", "")).lower()
            if t_type in ["enabled", "on", "true"]:
                return True
            if t_type in ["disabled", "off", "false"]:
                return False
        if isinstance(t_val, str):
            return t_val.strip().lower() in ["true", "1", "on", "enabled"]

    # 4. Check OpenAI `reasoning_effort`
    if "reasoning_effort" in req_data and req_data["reasoning_effort"] is not None:
        effort = str(req_data["reasoning_effort"]).strip().lower()
        if effort in ["none", "off", "false", "disable", "disabled"]:
            return False
        if effort in ["low", "medium", "high", "on", "true"]:
            return True

    # 5. Check inline message text for explicit override ("detailed thinking on" / "/think")
    messages = req_data.get("messages", [])
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                lower_c = m["content"].lower()
                if "detailed thinking on" in lower_c:
                    return True
                if "detailed thinking off" in lower_c:
                    return False

    # 6. Fallback to Engine default
    return bool(engine.config.get("default_thinking", False))


def resolve_target_model(req_data, req_headers):
    """Resolves which NVIDIA model to call."""
    header_override = req_headers.get("X-Model-Override")
    if header_override:
        return header_override.strip()

    active_model = engine.config.get("active_model", DEFAULT_MODEL)
    if engine.config.get("force_active_model", True):
        return active_model

    requested = req_data.get("model")
    if requested and isinstance(requested, str):
        requested = requested.strip()
        if requested in engine.model_registry or "/" in requested:
            return requested

    return active_model


# =====================================================================
# UNIVERSAL MESSAGE SANITIZER (Vision + Coding Tools + General Chat + RP)
# =====================================================================
def normalize_content(content, vision_enabled=True):
    """
    Handles both plain string content and OpenAI/Anthropic multimodal content arrays.
    """
    if content is None:
        return "", False

    if isinstance(content, str):
        return content, False

    if not isinstance(content, list):
        return str(content), False

    has_media = False
    normalized_parts = []
    text_only_parts = []

    for part in content:
        if isinstance(part, str):
            if part.strip():
                normalized_parts.append({"type": "text", "text": part})
                text_only_parts.append(part)
            continue

        if not isinstance(part, dict):
            continue

        p_type = part.get("type", "text")

        if p_type == "text" or "text" in part:
            txt = part.get("text", "")
            if txt:
                normalized_parts.append({"type": "text", "text": txt})
                text_only_parts.append(txt)

        elif p_type == "image_url" and vision_enabled:
            has_media = True
            img_val = part.get("image_url")
            if isinstance(img_val, str):
                normalized_parts.append({"type": "image_url", "image_url": {"url": img_val}})
            elif isinstance(img_val, dict) and img_val.get("url"):
                clean_img = {"url": img_val["url"]}
                if "detail" in img_val:
                    clean_img["detail"] = img_val["detail"]
                normalized_parts.append({"type": "image_url", "image_url": clean_img})

        elif p_type == "image" and vision_enabled:
            source = part.get("source", {})
            if isinstance(source, dict):
                media_type = source.get("media_type", "image/jpeg")
                data_b64 = source.get("data", "")
                url = source.get("url", "")
                if data_b64:
                    has_media = True
                    normalized_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data_b64}"}
                    })
                elif url:
                    has_media = True
                    normalized_parts.append({
                        "type": "image_url",
                        "image_url": {"url": url}
                    })

        elif p_type in ["input_audio", "audio_url", "video_url"] and vision_enabled:
            has_media = True
            normalized_parts.append(part)

    if has_media and vision_enabled:
        return normalized_parts, True

    return "\n".join(text_only_parts), False


def merge_message_contents(existing_content, new_content):
    """Safely merges two consecutive messages of the same role."""
    if isinstance(existing_content, str) and isinstance(new_content, str):
        if not existing_content:
            return new_content
        if not new_content:
            return existing_content
        return f"{existing_content}\n\n{new_content}"

    list_a = (
        [{"type": "text", "text": existing_content}]
        if isinstance(existing_content, str) and existing_content
        else (list(existing_content) if isinstance(existing_content, list) else [])
    )
    list_b = (
        [{"type": "text", "text": new_content}]
        if isinstance(new_content, str) and new_content
        else (list(new_content) if isinstance(new_content, list) else [])
    )
    return list_a + list_b


def clean_messages_universal(messages, thinking_enabled=False, rp_mode=False, vision_enabled=True):
    """Universal message sanitizer supporting Vision, Coding Tools, RP, and Dynamic Thinking."""
    if not isinstance(messages, list) or len(messages) == 0:
        messages = [{"role": "user", "content": "Hello"}]

    cleaned = []
    has_any_vision = False

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        raw_role = str(msg.get("role", "user")).strip().lower()
        if raw_role == "developer":
            role = "system"
        elif raw_role == "function":
            role = "tool"
        elif raw_role in ["system", "user", "assistant", "tool"]:
            role = raw_role
        else:
            role = "user"

        norm_content, is_vision = normalize_content(msg.get("content"), vision_enabled=vision_enabled)
        if is_vision:
            has_any_vision = True

        if isinstance(norm_content, str):
            norm_content = norm_content.strip()

        tool_calls = msg.get("tool_calls")
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name")

        has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0
        has_content = bool(norm_content) if isinstance(norm_content, str) else len(norm_content) > 0

        if not has_content and not has_tool_calls and role != "tool":
            continue

        if role == "system" and len(cleaned) > 0:
            if cleaned[0]["role"] == "system" and len(cleaned) == 1 and isinstance(norm_content, str):
                cleaned[0]["content"] = merge_message_contents(cleaned[0]["content"], norm_content)
                continue
            else:
                role = "user"
                if isinstance(norm_content, str):
                    norm_content = f"[System Instruction: {norm_content}]"

        clean_msg = {
            "role": role,
            "content": norm_content if has_content else ("" if role == "tool" else None)
        }
        if has_tool_calls:
            clean_msg["tool_calls"] = tool_calls
        if role == "tool" and tool_call_id:
            clean_msg["tool_call_id"] = str(tool_call_id)
        if name and role in ["tool", "user"]:
            clean_msg["name"] = str(name)

        if (
            len(cleaned) > 0
            and cleaned[-1]["role"] == role
            and role in ["user", "system"]
            and not cleaned[-1].get("tool_calls")
            and not has_tool_calls
        ):
            cleaned[-1]["content"] = merge_message_contents(cleaned[-1]["content"], clean_msg["content"])
        else:
            cleaned.append(clean_msg)

    if not cleaned:
        cleaned = [{"role": "user", "content": "Hello"}]

    thinking_directive = "detailed thinking on" if thinking_enabled else "detailed thinking off"
    custom_prefix = engine.config.get("custom_system_prefix", "").strip()

    header_parts = [thinking_directive]
    if rp_mode and not thinking_enabled:
        header_parts.append(
            "[Instruction: Respond directly with the roleplay story and dialogue only. "
            "Do not output internal thoughts, planning, or meta-commentary.]"
        )
    if custom_prefix:
        header_parts.append(custom_prefix)

    full_system_header = "\n".join(header_parts)

    if cleaned[0]["role"] == "system" and isinstance(cleaned[0].get("content"), str):
        existing_sys = cleaned[0]["content"]
        existing_sys = re.sub(r"^detailed thinking (on|off)\s*", "", existing_sys, flags=re.IGNORECASE).strip()
        cleaned[0]["content"] = f"{full_system_header}\n\n{existing_sys}".strip()
    else:
        cleaned.insert(0, {"role": "system", "content": full_system_header})

    if len(cleaned) == 1 and cleaned[0]["role"] == "system":
        cleaned.append({"role": "user", "content": "Continue."})

    return cleaned, has_any_vision


def strip_think_tags(text):
    """Removes <think>...</think> blocks and orphaned closing </think> tags."""
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?</think>\s*", "", text, flags=re.IGNORECASE)
    if "</think>" in cleaned.lower():
        parts = re.split(r"</think>", cleaned, flags=re.IGNORECASE)
        cleaned = parts[-1]
    if "<think>" in cleaned.lower():
        parts = re.split(r"<think>", cleaned, maxsplit=1, flags=re.IGNORECASE)
        cleaned = parts[0]
    return cleaned.strip()


# =====================================================================
# TOKEN ESTIMATION & COUNTING UTILITIES
# =====================================================================
def estimate_text_tokens(text):
    """Fast, dependency-free token estimator for LLM text/code."""
    if not text or not isinstance(text, str):
        return 0
    char_est = max(1, (len(text) + 3) // 4)
    word_punct_pieces = len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE))
    return max(char_est, int(word_punct_pieces * 0.85))


def estimate_messages_input_tokens(messages, tools=None):
    """Calculates input token count across all cleaned messages and tools."""
    total = 0
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            total += 4
            content = msg.get("content")
            if isinstance(content, str):
                total += estimate_text_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            total += estimate_text_tokens(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            total += 256
            if msg.get("tool_calls"):
                total += estimate_text_tokens(json.dumps(msg["tool_calls"], ensure_ascii=False))
    if tools:
        total += estimate_text_tokens(json.dumps(tools, ensure_ascii=False))
    return total


# =====================================================================
# STREAMING GENERATOR (UTF-8 Safe, Tool-Call Aware, Colorful Summary Log)
# =====================================================================
def stream_cleaned_response(upstream_response, model_name, thinking_enabled=False, context=None, estimated_input_tokens=0):
    """
    Streams NVIDIA SSE chunks with strict UTF-8 byte decoding and outputs a single
    colorful summary line upon completion.
    """
    inside_think = False
    has_sent_meaningful_data = False
    stream_had_error = False
    error_reason = None
    expose_reasoning = bool(engine.config.get("expose_reasoning", False)) or thinking_enabled

    accumulated_output_text = []
    accumulated_tool_fragments = []
    upstream_input_tokens = None
    upstream_output_tokens = None

    upstream_response.encoding = "utf-8"

    try:
        for raw_bytes in upstream_response.iter_lines(decode_unicode=False):
            if not raw_bytes:
                continue

            line = raw_bytes.decode("utf-8", errors="replace").strip()

            if line.startswith(":"):
                continue

            if line == "data: [DONE]":
                if not has_sent_meaningful_data:
                    empty_notice = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": ""},
                            "finish_reason": "stop"
                        }]
                    }
                    yield f"data: {json.dumps(empty_notice, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"
                break

            if not line.startswith("data: "):
                continue

            json_str = line[6:].strip()
            try:
                chunk = json.loads(json_str)
            except Exception:
                continue

            if chunk.get("id") == "chatcmpl-keepalive":
                continue

            usage = chunk.get("usage")
            if isinstance(usage, dict):
                if usage.get("prompt_tokens") is not None:
                    upstream_input_tokens = int(usage["prompt_tokens"])
                if usage.get("completion_tokens") is not None:
                    upstream_output_tokens = int(usage["completion_tokens"])

            choices = chunk.get("choices")
            if not choices or not isinstance(choices, list):
                if usage:
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            choice = choices[0]
            delta = choice.get("delta", {})
            finish_reason = choice.get("finish_reason")

            has_tool_calls = bool(delta.get("tool_calls") or delta.get("function_call"))
            if has_tool_calls:
                has_sent_meaningful_data = True
                accumulated_tool_fragments.append(
                    json.dumps(delta.get("tool_calls") or delta.get("function_call"), ensure_ascii=False)
                )

            if not expose_reasoning:
                delta.pop("reasoning_content", None)
                delta.pop("reasoning", None)
            else:
                r_tok = delta.get("reasoning_content") or delta.get("reasoning")
                if r_tok:
                    has_sent_meaningful_data = True
                    accumulated_output_text.append(str(r_tok))

            token = delta.get("content")

            if token is not None and not thinking_enabled:
                if "<think>" in token.lower():
                    inside_think = True
                    token = re.split(r"<think>", token, maxsplit=1, flags=re.IGNORECASE)[0]

                if inside_think:
                    if "</think>" in token.lower():
                        inside_think = False
                        token = re.split(r"</think>", token, maxsplit=1, flags=re.IGNORECASE)[-1]
                    else:
                        token = ""
                elif "</think>" in token.lower():
                    token = re.split(r"</think>", token, maxsplit=1, flags=re.IGNORECASE)[-1]

            if token and engine.hooks["post_response_chunk"]:
                token = engine.run_hooks("post_response_chunk", token, context or {})

            has_reasoning_token = expose_reasoning and bool(delta.get("reasoning_content") or delta.get("reasoning"))
            if not token and not has_tool_calls and not has_reasoning_token and not finish_reason and "role" not in delta:
                continue

            if token:
                has_sent_meaningful_data = True
                delta["content"] = token
                accumulated_output_text.append(token)
            elif "content" in delta and not has_tool_calls:
                delta["content"] = ""

            live_out_est = estimate_text_tokens("".join(accumulated_output_text) + "".join(accumulated_tool_fragments))
            engine.update_live_output_tokens(upstream_output_tokens or live_out_est)

            choice["delta"] = delta
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    except Exception as e:
        stream_had_error = True
        error_reason = "Stream Interrupted"
        engine.metrics["errors"] += 1
        engine.metrics["last_error"] = str(e)
        err_chunk = {
            "id": "chatcmpl-err",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {"content": f"\n\n[Engine Stream Interrupted: {str(e)}]"},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(err_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        upstream_response.close()
        final_in_tokens = upstream_input_tokens if upstream_input_tokens is not None else estimated_input_tokens
        computed_out_tokens = estimate_text_tokens(
            "".join(accumulated_output_text) + "".join(accumulated_tool_fragments)
        )
        final_out_tokens = computed_out_tokens if computed_out_tokens > 0 else (upstream_output_tokens or 0)
        engine.finalize_token_counts(final_in_tokens, final_out_tokens)

        total_tokens = final_in_tokens + final_out_tokens
        generated_ok = (not stream_had_error) and (final_out_tokens > 0 or has_sent_meaningful_data)
        log_generation_event(
            model_name=model_name,
            generated_ok=generated_ok,
            output_tokens=final_out_tokens,
            total_tokens=total_tokens,
            error_detail=error_reason
        )


# =====================================================================
# UPSTREAM PAYLOAD BUILDER (No Artificial Token Limits + Full Tool & Vision Support)
# =====================================================================
def build_upstream_payload(req_data, model_name, cleaned_messages, thinking_enabled, is_stream):
    """Constructs a clean, NIM-compatible request payload."""
    safe_payload = {
        "model": model_name,
        "messages": cleaned_messages,
        "stream": is_stream,
        "chat_template_kwargs": {
            "enable_thinking": thinking_enabled,
            "thinking": thinking_enabled
        }
    }

    if "temperature" in req_data and req_data["temperature"] is not None:
        safe_payload["temperature"] = float(req_data["temperature"])
    else:
        safe_payload["temperature"] = 0.7

    if "top_p" in req_data and req_data["top_p"] is not None:
        safe_payload["top_p"] = float(req_data["top_p"])
    else:
        safe_payload["top_p"] = 0.95

    raw_max_tokens = req_data.get("max_tokens") or req_data.get("max_completion_tokens")
    if raw_max_tokens is not None:
        try:
            parsed_limit = int(raw_max_tokens)
            if parsed_limit > 0:
                safe_payload["max_tokens"] = parsed_limit
        except (ValueError, TypeError):
            pass

    for optional_key in ["tools", "tool_choice", "response_format", "stop", "seed"]:
        if optional_key in req_data and req_data[optional_key] is not None:
            if optional_key == "tools" and isinstance(req_data["tools"], list) and len(req_data["tools"]) == 0:
                continue
            safe_payload[optional_key] = req_data[optional_key]

    if is_stream and "stream_options" in req_data and isinstance(req_data["stream_options"], dict):
        safe_payload["stream_options"] = req_data["stream_options"]

    return safe_payload


# =====================================================================
# STANDARD OPENAI ENDPOINTS (`/v1/models` & `/v1/chat/completions`)
# =====================================================================
@app.route("/v1/models", methods=["GET"])
@app.route("/models", methods=["GET"])
def list_models():
    models_data = []
    active_id = engine.config["active_model"]

    models_data.append({
        "id": active_id,
        "object": "model",
        "created": int(engine.start_time),
        "owned_by": "nvidia",
        "meta": engine.model_registry.get(active_id, {})
    })

    for m_id, meta in engine.model_registry.items():
        if m_id != active_id:
            models_data.append({
                "id": m_id,
                "object": "model",
                "created": int(engine.start_time),
                "owned_by": meta.get("owned_by", "nvidia"),
                "meta": meta
            })

    return jsonify({
        "object": "list",
        "data": models_data
    })


@app.route("/v1/chat/completions", methods=["POST"])
@app.route("/chat/completions", methods=["POST"])
def chat_completions():
    model_name = engine.config.get("active_model", DEFAULT_MODEL)
    estimated_input_tokens = 0
    try:
        req_data = request.get_json(force=True, silent=True) or {}
        api_key = resolve_api_key(request)

        context = {
            "headers": dict(request.headers),
            "remote_addr": request.remote_addr,
            "timestamp": time.time()
        }

        # 1. Pre-process request hook
        req_data = engine.run_hooks("pre_process_request", req_data, context)

        # 2. Resolve dynamic settings (Model, Thinking, RP Mode, Stream)
        model_name = resolve_target_model(req_data, request.headers)
        thinking_enabled = resolve_thinking_mode(req_data, request.headers)
        rp_mode = bool(
            req_data.get("rp_mode")
            or request.headers.get("X-RP-Mode", "").lower() == "true"
            or engine.config.get("rp_mode", False)
        )
        vision_enabled = bool(engine.config.get("vision_enabled", True))
        is_stream = bool(req_data.get("stream", False))

        context.update({
            "model_name": model_name,
            "thinking_enabled": thinking_enabled,
            "rp_mode": rp_mode,
            "is_stream": is_stream
        })

        # 3. Clean & normalize messages
        raw_messages = req_data.get("messages", [])
        raw_messages = engine.run_hooks("pre_clean_messages", raw_messages, context)
        cleaned_messages, has_vision = clean_messages_universal(
            raw_messages,
            thinking_enabled=thinking_enabled,
            rp_mode=rp_mode,
            vision_enabled=vision_enabled
        )
        cleaned_messages = engine.run_hooks("post_clean_messages", cleaned_messages, context)

        # 4. Build upstream payload
        safe_payload = build_upstream_payload(
            req_data=req_data,
            model_name=model_name,
            cleaned_messages=cleaned_messages,
            thinking_enabled=thinking_enabled,
            is_stream=is_stream
        )
        safe_payload = engine.run_hooks("pre_upstream_payload", safe_payload, context)

        # 5. Calculate & record current input tokens
        estimated_input_tokens = estimate_messages_input_tokens(
            safe_payload.get("messages", []),
            tools=safe_payload.get("tools")
        )
        engine.record_input_tokens(estimated_input_tokens)

        # 6. Update telemetry metrics
        with engine.lock:
            engine.metrics["total_requests"] += 1
            engine.metrics["last_request_timestamp"] = int(time.time())
            if is_stream:
                engine.metrics["streaming_requests"] += 1
            if has_vision:
                engine.metrics["vision_requests"] += 1
            if "tools" in safe_payload:
                engine.metrics["tool_requests"] += 1

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if is_stream else "application/json",
            "Connection": "keep-alive"
        }

        timeouts = (
            engine.config.get("connect_timeout", 15),
            engine.config.get("read_timeout", 300)
        )

        upstream = http_session.post(
            f"{NVIDIA_BASE_URL}/chat/completions",
            headers=headers,
            json=safe_payload,
            stream=is_stream,
            timeout=timeouts
        )
        upstream.encoding = "utf-8"

        # Automatic fallback if a specific NIM container rejects `chat_template_kwargs`
        if upstream.status_code in [400, 422] and "chat_template_kwargs" in safe_payload:
            upstream.close()
            safe_payload.pop("chat_template_kwargs", None)
            upstream = http_session.post(
                f"{NVIDIA_BASE_URL}/chat/completions",
                headers=headers,
                json=safe_payload,
                stream=is_stream,
                timeout=timeouts
            )
            upstream.encoding = "utf-8"

        if upstream.status_code != 200:
            err_text = upstream.text
            engine.metrics["errors"] += 1
            engine.metrics["last_error"] = f"HTTP {upstream.status_code}: {err_text[:300]}"
            engine.finalize_token_counts(estimated_input_tokens, 0)
            log_generation_event(
                model_name=model_name,
                generated_ok=False,
                output_tokens=0,
                total_tokens=estimated_input_tokens,
                error_detail=f"HTTP {upstream.status_code}"
            )
            return Response(
                err_text,
                status=upstream.status_code,
                content_type="application/json; charset=utf-8"
            )

        # --- STREAMING RESPONSE ---
        if is_stream:
            return Response(
                stream_cleaned_response(
                    upstream,
                    model_name=model_name,
                    thinking_enabled=thinking_enabled,
                    context=context,
                    estimated_input_tokens=estimated_input_tokens
                ),
                content_type="text/event-stream; charset=utf-8",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no"
                }
            )

        # --- NON-STREAMING RESPONSE ---
        data = json.loads(upstream.content.decode("utf-8"))
        choices = data.get("choices", [])
        expose_reasoning = bool(engine.config.get("expose_reasoning", False)) or thinking_enabled
        final_text = ""
        tool_calls_str = ""

        if choices and isinstance(choices, list):
            msg = choices[0].get("message", {})
            raw_content = msg.get("content")
            has_tool_calls = bool(msg.get("tool_calls"))
            if has_tool_calls:
                tool_calls_str = json.dumps(msg.get("tool_calls"), ensure_ascii=False)

            if raw_content is not None and not thinking_enabled:
                final_text = strip_think_tags(raw_content)
            else:
                final_text = raw_content or ""

            if not expose_reasoning:
                msg.pop("reasoning_content", None)
                msg.pop("reasoning", None)

            if not has_tool_calls:
                msg["content"] = final_text

            choices[0]["message"] = msg

        # Record input & output tokens in engine state
        usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
        final_in_tokens = usage.get("prompt_tokens") or estimated_input_tokens
        estimated_out_tokens = estimate_text_tokens(final_text + tool_calls_str)
        final_out_tokens = estimated_out_tokens if estimated_out_tokens > 0 else (usage.get("completion_tokens") or 0)
        engine.finalize_token_counts(final_in_tokens, final_out_tokens)

        total_tokens = final_in_tokens + final_out_tokens
        log_generation_event(
            model_name=model_name,
            generated_ok=bool(final_out_tokens > 0),
            output_tokens=final_out_tokens,
            total_tokens=total_tokens
        )

        # Run post_full_response hooks
        data = engine.run_hooks("post_full_response", data, context)

        return Response(
            json.dumps(data, ensure_ascii=False),
            status=200,
            content_type="application/json; charset=utf-8"
        )

    except Exception as e:
        engine.metrics["errors"] += 1
        engine.metrics["last_error"] = str(e)
        log_generation_event(
            model_name=model_name,
            generated_ok=False,
            output_tokens=0,
            total_tokens=estimated_input_tokens,
            error_detail="Exception"
        )
        return jsonify({
            "error": {
                "message": f"NVIDIA Engine Error: {str(e)}",
                "type": "engine_error"
            }
        }), 500


# =====================================================================
# ENGINE CONTROL & INTEGRATION CIRCUITRY (`/v1/engine/*`)
# =====================================================================
@app.route("/health", methods=["GET"])
@app.route("/v1/engine/status", methods=["GET"])
def engine_status():
    return jsonify({
        "status": "online",
        "uptime_seconds": int(time.time() - engine.start_time),
        "config": engine.config,
        "active_model": engine.config["active_model"],
        "registered_models": list(engine.model_registry.keys()),
        "api_key_configured": is_valid_nvapi_key(resolve_api_key(request)),
        "active_hooks": {k: len(v) for k, v in engine.hooks.items()},
        "metrics": engine.metrics
    })


@app.route("/v1/engine/config", methods=["GET", "POST", "PATCH"])
def engine_config_endpoint():
    if request.method == "GET":
        return jsonify({"config": engine.config})

    updates = request.get_json(force=True, silent=True) or {}
    updated_cfg = engine.update_config(updates)
    return jsonify({
        "status": "updated",
        "config": updated_cfg
    })


@app.route("/v1/engine/model", methods=["GET", "POST", "PUT"])
def engine_model_endpoint():
    if request.method == "GET":
        return jsonify({
            "active_model": engine.config["active_model"],
            "force_active_model": engine.config["force_active_model"],
            "registry": engine.model_registry
        })

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "switch")

    if action == "register":
        model_id = data.get("model") or data.get("id")
        if not model_id:
            return jsonify({"error": "Missing 'model' ID"}), 400
        engine.register_model(
            model_id=model_id,
            vision=data.get("vision", True),
            thinking_capable=data.get("thinking_capable", True),
            tools_capable=data.get("tools_capable", True),
            description=data.get("description", "")
        )
        return jsonify({"status": "registered", "registry": engine.model_registry})

    new_model = data.get("model") or data.get("active_model")
    if not new_model:
        return jsonify({"error": "Missing 'model' field in payload"}), 400

    old_model, active = engine.switch_model(new_model, register_if_missing=True)
    if "force_active_model" in data:
        engine.config["force_active_model"] = bool(data["force_active_model"])

    return jsonify({
        "status": "switched",
        "previous_model": old_model,
        "active_model": active,
        "force_active_model": engine.config["force_active_model"]
    })


@app.route("/v1/engine/apikey", methods=["GET", "POST", "PUT", "DELETE"])
def engine_apikey_endpoint():
    if request.method == "GET":
        resolved = resolve_api_key(request)
        masked = f"{resolved[:10]}...{resolved[-4:]}" if len(resolved) > 16 else "not-set"
        return jsonify({
            "valid_format": is_valid_nvapi_key(resolved),
            "masked_key": masked,
            "has_runtime_override": bool(engine.api_keys["runtime_override"]),
            "has_hardcoded": is_valid_nvapi_key(engine.api_keys["hardcoded"])
        })

    if request.method == "DELETE":
        engine.api_keys["runtime_override"] = ""
        return jsonify({"status": "runtime_override_cleared"})

    data = request.get_json(force=True, silent=True) or {}
    new_key = data.get("api_key", "").strip()
    target = data.get("target", "runtime_override")

    if target in engine.api_keys:
        engine.api_keys[target] = new_key

    return jsonify({
        "status": "api_key_updated",
        "target": target,
        "valid_format": is_valid_nvapi_key(new_key)
    })


@app.route("/v1/engine/tokens", methods=["GET", "DELETE"])
def engine_tokens_endpoint():
    if request.method == "DELETE":
        with engine.lock:
            engine.metrics["current_input_tokens"] = 0
            engine.metrics["current_output_tokens"] = 0
            engine.metrics["last_response_output_tokens"] = 0
            engine.metrics["total_input_tokens"] = 0
            engine.metrics["total_output_tokens"] = 0
        return jsonify({"status": "token_counters_reset", "tokens": engine.get_token_stats()})

    return jsonify(engine.get_token_stats())


# =====================================================================
# STANDALONE SERVER ENTRYPOINT (Can also be imported by server.py)
# =====================================================================
def run_standalone_server(host="0.0.0.0", port=PORT, threaded=True):
    c = TermColors
    print(f"{c.BOLD}{c.CYAN}" + "=" * 72 + f"{c.RESET}")
    print(f"{c.BOLD}{c.GREEN}🚀 UNIVERSAL NVIDIA NIM ENGINE (Vision + Coding + Chat + RP){c.RESET}")
    print(f"{c.CYAN}📌 OpenAI Endpoint : {c.WHITE}http://localhost:{port}/v1/chat/completions{c.RESET}")
    print(f"{c.CYAN}📌 Models Endpoint : {c.WHITE}http://localhost:{port}/v1/models{c.RESET}")
    print(f"{c.CYAN}📌 Control API     : {c.WHITE}http://localhost:{port}/v1/engine/status{c.RESET}")
    print(f"{c.MAGENTA}🤖 Active Model    : {c.BOLD}{engine.config['active_model']}{c.RESET}")
    print(f"{c.BOLD}{c.CYAN}" + "=" * 72 + f"{c.RESET}")
    app.run(host=host, port=port, threaded=threaded)


if __name__ == "__main__":
    run_standalone_server()

