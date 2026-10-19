"""
model_switch.py — Dynamic Model Catalog & Switcher for NVIDIA NIM Engine
========================================================================
How to add new models in the future:
  Simply add a new line inside `AVAILABLE_MODELS` below!
  You can either add just the model string:
      "nvidia/your-new-model-name",
  OR a dictionary if you want a custom label/description in the CLI:
      {
          "id": "nvidia/your-new-model-name",
          "name": "Friendly Display Name",
          "vision": True,
          "thinking": True,
          "tools": True,
          "description": "Short note shown in CLI menu"
      },

`cli.py` and `nvidia_rp_cleaner.py` automatically read this list on startup
and whenever refreshed, so you NEVER have to touch `cli.py` when adding models!
"""

import threading
from flask import request, jsonify

# Import existing engine singletons without modifying nvidia_rp_cleaner.py
from nvidia_rp_cleaner import app, engine, DEFAULT_MODEL


# =====================================================================
# ✏️ USER MODEL CATALOG — ADD OR EDIT YOUR NVIDIA MODELS HERE!
# =====================================================================
# Pattern: Add as many NVIDIA model IDs as you want below.
# `cli.py` will automatically number and list every model in this list!
AVAILABLE_MODELS = [
    # 1. Default Primary Model
    {
        "id": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "name": "Nemotron 3.5 Super VL 120B",
        "vision": True,
        "thinking": True,
        "tools": True,
        "description": "Primary Multimodal (Text + Vision + Coding + RP)",
    },

    # -----------------------------------------------------------------
    # 👇 ADD YOUR FUTURE NVIDIA MODELS BELOW Following This Pattern 👇
    # (You can paste a simple string OR a dict like above)
    # -----------------------------------------------------------------
    # "meta/llama-3.2-90b-vision-instruct",
    # "deepseek-ai/deepseek-r1",
    # "qwen/qwen2.5-coder-32b-instruct",
    # {
    #     "id": "nvidia/model-id-here",
    #     "name": "Custom Name Here",
    #     "vision": True,
    #     "thinking": True,
    #     "tools": True,
    #     "description": "Notes for CLI display",
    # },
]


# =====================================================================
# INTERNAL STATE & SYNCHRONIZATION WITH ENGINE REGISTRY
# =====================================================================
_catalog_lock = threading.RLock()


def _normalize_model_entry(entry, index=1):
    """
    Normalizes either a plain string ("org/model-name") or a metadata dict
    into a standard dictionary structure for `cli.py` and `engine.model_registry`.
    """
    if isinstance(entry, str):
        model_id = entry.strip()
        if not model_id:
            return None
        short_title = model_id.split("/")[-1] if "/" in model_id else model_id
        return {
            "index": index,
            "id": model_id,
            "name": short_title,
            "vision": True,
            "thinking_capable": True,
            "tools_capable": True,
            "description": f"NVIDIA NIM Model ({model_id})",
        }

    if isinstance(entry, dict):
        model_id = str(entry.get("id") or entry.get("model") or "").strip()
        if not model_id:
            return None
        short_title = model_id.split("/")[-1] if "/" in model_id else model_id
        return {
            "index": index,
            "id": model_id,
            "name": str(entry.get("name") or short_title).strip(),
            "vision": bool(entry.get("vision", True)),
            "thinking_capable": bool(entry.get("thinking", entry.get("thinking_capable", True))),
            "tools_capable": bool(entry.get("tools", entry.get("tools_capable", True))),
            "description": str(entry.get("description") or f"NVIDIA NIM Model ({model_id})").strip(),
        }

    return None


def sync_catalog_to_engine():
    """
    Reads `AVAILABLE_MODELS` (plus any custom runtime-registered models in the engine)
    and registers all of them into `engine.model_registry` so both `/v1/models`
    and `cli.py` automatically see every model.
    """
    with _catalog_lock:
        catalog = []
        seen_ids = set()

        # Ensure DEFAULT_MODEL is always present if AVAILABLE_MODELS was emptied
        raw_entries = list(AVAILABLE_MODELS) if AVAILABLE_MODELS else [DEFAULT_MODEL]

        for entry in raw_entries:
            norm = _normalize_model_entry(entry, index=len(catalog) + 1)
            if not norm or norm["id"] in seen_ids:
                continue
            seen_ids.add(norm["id"])
            catalog.append(norm)

            # Register in nvidia_rp_cleaner.py's engine singleton
            engine.register_model(
                model_id=norm["id"],
                vision=norm["vision"],
                thinking_capable=norm["thinking_capable"],
                tools_capable=norm["tools_capable"],
                description=norm["description"],
            )

        # Also include any models dynamically registered at runtime via API/CLI
        for m_id, meta in list(engine.model_registry.items()):
            if m_id not in seen_ids:
                seen_ids.add(m_id)
                catalog.append({
                    "index": len(catalog) + 1,
                    "id": m_id,
                    "name": m_id.split("/")[-1] if "/" in m_id else m_id,
                    "vision": bool(meta.get("vision", True)),
                    "thinking_capable": bool(meta.get("thinking_capable", True)),
                    "tools_capable": bool(meta.get("tools_capable", True)),
                    "description": str(meta.get("description") or m_id),
                })

        return catalog


# =====================================================================
# PYTHON API FOR `cli.py` (Auto-lists & switches models by number or ID)
# =====================================================================
def get_available_models():
    """
    Returns the complete, numbered list of models for `cli.py` to display.
    Each item includes `is_active: True/False` so the CLI can highlight the active one.
    """
    catalog = sync_catalog_to_engine()
    active_id = engine.config.get("active_model", DEFAULT_MODEL)
    for item in catalog:
        item["is_active"] = (item["id"] == active_id)
    return catalog


def get_active_model():
    """Returns the currently active NVIDIA model ID."""
    return engine.config.get("active_model", DEFAULT_MODEL)


def switch_model(selection, force_active_model=None):
    """
    Switches the active model in the engine.
    `selection` can be:
      - An integer or numeric string (1-based index from the CLI menu, e.g. `1` or `"2"`)
      - A full model ID string (e.g. `"nvidia/nemotron-3.5-super-vl-120b-a12b"`)
      - A partial model name / display name match
    """
    catalog = get_available_models()
    target_model_id = None

    # 1. Check if selection is a 1-based menu index (e.g., 1, 2, "1", "2")
    if isinstance(selection, int) or (isinstance(selection, str) and selection.strip().isdigit()):
        idx = int(selection)
        for item in catalog:
            if item["index"] == idx:
                target_model_id = item["id"]
                break
        if not target_model_id:
            raise ValueError(
                f"Invalid model number '{idx}'. Available range: 1 to {len(catalog)}."
            )

    # 2. Check if selection is a model ID or name string
    elif isinstance(selection, str):
        cleaned_sel = selection.strip()
        if not cleaned_sel:
            raise ValueError("Model selection cannot be empty.")

        # Exact ID match
        for item in catalog:
            if item["id"].lower() == cleaned_sel.lower():
                target_model_id = item["id"]
                break

        # Display name or partial substring match
        if not target_model_id:
            for item in catalog:
                if cleaned_sel.lower() in item["id"].lower() or cleaned_sel.lower() in item["name"].lower():
                    target_model_id = item["id"]
                    break

        # If not in catalog yet, allow switching & auto-registering any valid "org/model" ID
        if not target_model_id:
            target_model_id = cleaned_sel

    if not target_model_id:
        raise ValueError("Could not resolve model selection.")

    previous_model, active_model = engine.switch_model(target_model_id, register_if_missing=True)

    if force_active_model is not None:
        engine.update_config({"force_active_model": bool(force_active_model)})

    return {
        "status": "switched",
        "previous_model": previous_model,
        "active_model": active_model,
        "force_active_model": engine.config.get("force_active_model", True),
        "available_models": get_available_models(),
    }


def add_model_at_runtime(model_id, name="", description="", vision=True, thinking=True, tools=True):
    """
    Allows `cli.py` to temporarily or dynamically add a model ID during a session
    even if the user hasn't edited `AVAILABLE_MODELS` yet.
    """
    model_id = str(model_id or "").strip()
    if not model_id:
        raise ValueError("Model ID cannot be empty.")

    with _catalog_lock:
        # Avoid duplicates in AVAILABLE_MODELS
        existing_ids = [m["id"] for m in get_available_models()]
        if model_id not in existing_ids:
            AVAILABLE_MODELS.append({
                "id": model_id,
                "name": name or (model_id.split("/")[-1] if "/" in model_id else model_id),
                "vision": bool(vision),
                "thinking": bool(thinking),
                "tools": bool(tools),
                "description": description or f"NVIDIA NIM Model ({model_id})",
            })

    return get_available_models()


# =====================================================================
# REST ENDPOINT FOR `cli.py` (`/v1/engine/models/catalog`)
# =====================================================================
_ROUTES_ATTACHED = False


def _attach_model_catalog_routes():
    """
    Attaches `/v1/engine/models/catalog` onto the shared Flask `app` so `cli.py`
    can query the numbered list and switch models by index or ID over HTTP as well
    as via direct Python import.
    """
    global _ROUTES_ATTACHED
    if _ROUTES_ATTACHED:
        return

    @app.route("/v1/engine/models/catalog", methods=["GET", "POST"])
    def model_catalog_endpoint():
        if request.method == "GET":
            models = get_available_models()
            return jsonify({
                "active_model": get_active_model(),
                "force_active_model": engine.config.get("force_active_model", True),
                "total_models": len(models),
                "models": models,
            })

        # POST: switch model by number (index) or ID, or add a new model
        data = request.get_json(force=True, silent=True) or {}
        action = str(data.get("action", "switch")).lower()

        if action == "add":
            new_id = data.get("model") or data.get("id")
            if not new_id:
                return jsonify({"error": "Missing 'model' ID"}), 400
            updated = add_model_at_runtime(
                model_id=new_id,
                name=data.get("name", ""),
                description=data.get("description", ""),
                vision=data.get("vision", True),
                thinking=data.get("thinking", True),
                tools=data.get("tools", True),
            )
            return jsonify({
                "status": "added",
                "active_model": get_active_model(),
                "models": updated,
            })

        selection = data.get("selection") or data.get("index") or data.get("model") or data.get("id")
        if selection is None:
            return jsonify({"error": "Provide 'selection', 'index', or 'model' to switch."}), 400

        try:
            result = switch_model(
                selection=selection,
                force_active_model=data.get("force_active_model"),
            )
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    _ROUTES_ATTACHED = True


# Automatically sync the catalog and attach routes on import
sync_catalog_to_engine()
_attach_model_catalog_routes()