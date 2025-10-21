import json
import time
import random
import requests
import shutil
from collections import Counter, deque # queue container
from PIL import Image, ImageSequence, ImageOps, ImageChops
import re
import io  # precise file I/O helpers
import base64
import gradio as gr
import numpy as np
import torch
import threading
from threading import Lock, Event # thread synchronization primitives
from concurrent.futures import ThreadPoolExecutor
import websocket  # websocket bridge for preview
import atexit # For NVML cleanup
import inspect
from functools import lru_cache
import uuid
from .kelnel_ui.system_monitor import update_floating_monitors_stream, custom_css as monitor_css, cleanup_nvml # system monitoring module
from .kelnel_ui.k_Preview import ComfyUIPreviewer # integrate live preview client
from .kelnel_ui.css_html_js import HACKER_CSS, get_sponsor_html # custom CSS/HTML assets
from .kelnel_ui.ui_def import ( # workflow helpers
    calculate_aspect_ratio,
    strip_prefix,
    parse_resolution,
    load_resolution_presets_from_files,
    find_closest_preset,
    get_output_images,
    find_all_nodes_by_class_type,
    # fuck, # Removed as it's deprecated and its logic is integrated elsewhere
    get_workflow_defaults_and_visibility,
    load_prompt_from_file,
)
# plugin settings helpers
from .kelnel_ui.ui_def import (
    load_plugin_settings, 
    save_plugin_settings, 
    DEFAULT_MAX_DYNAMIC_COMPONENTS, # fallback value for MAX_DYNAMIC_COMPONENTS
    DEFAULT_THEME_MODE,
)

# --- Initialize dynamic component limits ---
plugin_settings_on_load = load_plugin_settings() 
MAX_DYNAMIC_COMPONENTS = plugin_settings_on_load.get("max_dynamic_components", DEFAULT_MAX_DYNAMIC_COMPONENTS)
print(f"Plugin start: max dynamic components loaded from settings: {MAX_DYNAMIC_COMPONENTS} (via kelnel_ui.ui_def)")
# --- End initialization ---

# --- UI configuration limits ---
MAX_KSAMPLER_CONTROLS = 4
MAX_MASK_GENERATORS = 2
MAX_IMAGE_LOADERS = 6
MASK_FIELD_COUNT = 7  # face, background, hair, body, clothes, confidence, refine
IMAGE_LOADER_FIELD_COUNT = 5  # resize, width, height, keep_proportion, divisible_by
MAX_JSON_FILE_CHOICES = 500

# Friendly labels and option lists
SAMPLER_NAME_CHOICES = [
    "euler", "euler_a", "heun", "lms", "dpm_2", "dpm_2_a", "dpmpp_2s", "dpmpp_2m",
    "dpmpp_2m_sde", "dpmpp_sde", "dpmpp_3m", "ddim", "plms", "uni_pc", "residual",
]
SCHEDULER_CHOICES = [
    "simple", "normal", "karras", "exponential", "sgm_uniform", "sgm_uniform_simple", "linear"
]
BOOL_CHOICE = ["disable", "enable"]
MASK_GENERATOR_NOTICE_TEXT = (
    "No detection-based mask generators were found in the selected workflow. "
    "Add an `APersonMaskGenerator` node to unlock these controls."
)

NEGATIVE_PROMPT_COMPONENTS = []
IMAGE_LOADER_ACCORDION_COMPONENTS = []
IMAGE_LOADER_COMPONENTS_FLAT = []
KSAMPLER_COMPONENT_GROUPS = []
KSAMPLER_ACCORDION_COMPONENTS = []
KSAMPLER_COMPONENTS_FLAT = []
MASK_COMPONENT_GROUPS = []
MASK_ACCORDION_COMPONENTS = []
MASK_COMPONENTS_FLAT = []

# Determine component capabilities (handles Gradio version drift)
def _component_supports_arg(component_cls, param_name):
    try:
        return param_name in inspect.signature(component_cls.__init__).parameters
    except (ValueError, TypeError):
        return None


GRADIO_IMAGE_SUPPORTS_TYPE = _component_supports_arg(gr.Image, "type")
GRADIO_IMAGE_SUPPORTS_TOOL = _component_supports_arg(gr.Image, "tool")
GRADIO_IMAGE_SUPPORTS_IMAGE_MODE = _component_supports_arg(gr.Image, "image_mode")
GRADIO_IMAGE_SUPPORTS_BRUSH = _component_supports_arg(gr.Image, "brush_radius")
GRADIO_IMAGE_SUPPORTS_SOURCES = _component_supports_arg(gr.Image, "sources")
GRADIO_VIDEO_SUPPORTS_SOURCES = _component_supports_arg(gr.Video, "sources")
GRADIO_VIDEO_SUPPORTS_LOOP = _component_supports_arg(gr.Video, "loop")
GRADIO_HAS_IMAGE_EDITOR = hasattr(gr, "ImageEditor")


THEME_MODE_LABELS = {
    "system": "System",
    "light": "Light",
    "dark": "Dark",
}
THEME_LABEL_TO_VALUE = {label: value for value, label in THEME_MODE_LABELS.items()}
CURRENT_THEME_MODE = plugin_settings_on_load.get("theme_mode", DEFAULT_THEME_MODE)
if CURRENT_THEME_MODE not in THEME_MODE_LABELS:
    CURRENT_THEME_MODE = DEFAULT_THEME_MODE
CURRENT_THEME_LABEL = THEME_MODE_LABELS.get(CURRENT_THEME_MODE, THEME_MODE_LABELS[DEFAULT_THEME_MODE])

UI_THEME_CSS = """
:root,
html,
body {
    --hua-max-width: 100%;
    --hua-gap: 18px;
    --hua-radius: 12px;
    --hua-dark-surface: #151821;
    --hua-dark-surface-alt: #1b1f2c;
    --hua-dark-border: #23283a;
    --hua-dark-text: #f3f6ff;
    --hua-light-surface: #ffffff;
    --hua-light-surface-alt: #f4f6fb;
    --hua-light-border: #d8dce8;
    --hua-light-text: #1f2330;
    width: 100%;
    height: 100%;
    margin: 0 !important;
}

:root[data-hua-theme="dark"],
body[data-hua-theme="dark"] {
    background-color: #0e101a;
}

:root[data-hua-theme="light"],
body[data-hua-theme="light"] {
    background-color: #eef1f7;
}

:root[data-hua-theme],
body[data-hua-theme] {
    margin: 0;
}

:root[data-hua-theme] .gradio-container,
body[data-hua-theme] .gradio-container {
    max-width: none !important;
    width: 100% !important;
    padding: 0 !important;
    margin: 0 auto !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
}

.gradio-container .gradio-app {
    max-width: none !important;
    width: 100% !important;
}

.gradio-container {
    max-width: none !important;
    width: 100% !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
}

.gradio-app, .gradio-app > div {
    width: 100% !important;
}

.hua-main-row {
    gap: var(--hua-gap) !important;
    padding: 0;
}

.gradio-app, .gradio-block {
    max-width: none !important;
}

.gradio-block {
    padding: 0 !important;
    border: none !important;
    box-shadow: none !important;
}

.hua-pane {
    border-radius: 0 !important;
    border: none !important;
    padding: calc(var(--hua-gap) * 0.75) !important;
    box-shadow: none !important;
}

.hua-pane .gradio-row {
    gap: calc(var(--hua-gap) * 0.75) !important;
}

.hua-pane .gradio-column {
    gap: calc(var(--hua-gap) * 0.6) !important;
}

#hua-image-input {
    width: 100%;
    overflow: visible !important;
}

#hua-image-input [data-testid="image"],
#hua-image-input .image-editor,
#hua-image-input .image {
    min-height: 600px !important;
    height: auto !important;
}

#hua-image-input .image-editor > div,
#hua-image-input [data-testid="image"] > div {
    overflow: visible !important;
}

#hua-image-input .image-editor canvas {
    max-width: 100% !important;
}

body[data-hua-theme="light"] .log-display-container {
    background-color: #f5f6fb !important;
    color: #1f2330 !important;
}

body[data-hua-theme="light"] .log-display-container textarea {
    background-color: #ffffff !important;
    color: #1f2330 !important;
}

body[data-hua-theme="light"] .log-display-container h4 {
    color: #1f2330 !important;
}

.hua-photopea-html iframe {
    min-height: 720px;
}

.hua-pane-right .gradio-gallery {
    min-height: 640px;
}

.floating-monitor-outer-wrapper {
    pointer-events: none;
}
"""

PHOTOPEA_EMBED_HTML = """
<div id="photopea-integration-wrapper" style="height:720px; border:1px solid var(--block-border-color,#444); border-radius:6px; overflow:hidden;">
  <iframe id="photopea-iframe" src="https://www.photopea.com/" style="width:100%;height:100%;border:0;" allow="clipboard-read; clipboard-write"></iframe>
</div>
<script>
(function(){
  const wrapper = document.getElementById("photopea-integration-wrapper");
  if (!wrapper || wrapper.dataset.initialized) { return; }
  wrapper.dataset.initialized = "1";
  const iframe = document.getElementById("photopea-iframe");
  const importSelector = '#photopea-import-data textarea';
  const dataSelector = '#hua-photopea-data-store textarea';
  const sendButtonSelector = '#hua-photopea-send button';
  const fetchButtonSelector = '#hua-photopea-fetch button';

  const getImportBox = () => {
    const app = window.gradioApp ? window.gradioApp() : null;
    return app ? app.querySelector(importSelector) : null;
  };

  const postToPhotopea = async (message) => {
    if (!iframe || !iframe.contentWindow) {
      console.warn("Photopea frame not ready");
      return null;
    }

    // Create a promise to wait for Photopea's response
    return new Promise((resolve, reject) => {
      const responses = [];
      const photopeaMessageHandle = (response) => {
        responses.push(response.data);
        // Photopea returns the payload data first, then sends "done"
        if (response.data === "done") {
          window.removeEventListener("message", photopeaMessageHandle);
          resolve(responses);
        }
      };

      // Listen for Photopea's response
      window.addEventListener("message", photopeaMessageHandle);

      // Send the command to Photopea
      iframe.contentWindow.postMessage(message, "*");

      // Timeout after 10 seconds
      setTimeout(() => {
        window.removeEventListener("message", photopeaMessageHandle);
        if (responses.length === 0) {
          reject(new Error("Photopea response timeout"));
        }
      }, 10000);
    });
  };
  const getDataSource = () => {
    const app = window.gradioApp ? window.gradioApp() : document;
    if (!app) { return null; }
    return app.querySelector(dataSelector);
  };
  const dispatchValueChange = (element) => {
    if (!element) { return; }
    ["input", "change"].forEach((eventName) => {
      try {
        element.dispatchEvent(new Event(eventName, { bubbles: true }));
      } catch (err) {
        console.warn("Failed to dispatch", eventName, err);
      }
    });
  };
  const updateDataStore = (value) => {
    const dataInput = getDataSource();
    if (dataInput) {
      dataInput.value = value || "";
      dispatchValueChange(dataInput);
    }
  };

  // Helper to convert ArrayBuffer to base64
  const arrayBufferToBase64 = (buffer) => {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  };

  window.huaPhotopeaBridge = {
    open: async (dataUrl, name) => {
      console.log("[Photopea] Opening image in Photopea:", name);
      if (!dataUrl) {
        console.warn("[Photopea] No image data provided to Photopea.");
        return null;
      }

      try {
        // Use Photopea's actual API command: app.open("data_url", null, asNewDocument)
        // asNewDocument=false means add as layer if document exists
        const command = `app.open("${dataUrl}", null, false);`;
        await postToPhotopea(command);
        console.log("[Photopea] Successfully sent image to Photopea");
        updateDataStore(dataUrl);
        return dataUrl;
      } catch (err) {
        console.error("[Photopea] Failed to open image:", err);
        return null;
      }
    },
    requestExport: async (name, format) => {
      console.log("[Photopea] Requesting export from Photopea:", name, format);
      try {
        // Use Photopea's actual API command to export
        const command = 'app.activeDocument.saveToOE("png");';
        const responses = await postToPhotopea(command);

        // First element of responses is the ArrayBuffer with image data
        if (responses && responses[0] instanceof ArrayBuffer) {
          const base64Data = arrayBufferToBase64(responses[0]);
          const dataUrl = `data:image/png;base64,${base64Data}`;

          // Deliver the exported image back to Gradio
          const delivered = window.huaPhotopeaBridge.deliver({
            name: name || "photopea_export.png",
            data: dataUrl,
            timestamp: Date.now()
          });

          console.log("[Photopea] Export successful, delivered:", delivered);
          return dataUrl;
        } else {
          console.warn("[Photopea] Unexpected response format from export");
          return null;
        }
      } catch (err) {
        console.error("[Photopea] Failed to export:", err);
        return null;
      }
    },
    deliver: (payload) => {
      try {
        console.log("[Photopea] Attempting to deliver payload to Gradio");
        const importBox = getImportBox();
        if (!importBox) {
          console.warn("[Photopea] Unable to locate Photopea import textbox with selector:", importSelector);
          return false;
        }
        console.log("[Photopea] Found import textbox:", importBox);
        const serialized = typeof payload === "string" ? payload : JSON.stringify(payload || {});
        console.log("[Photopea] Setting value (length:", serialized.length, ")");
        importBox.value = serialized;
        dispatchValueChange(importBox);
        updateDataStore(serialized);
        console.log("[Photopea] Successfully delivered payload to Gradio");
        return true;
      } catch (err) {
        console.error("[Photopea] Failed to deliver payload to Gradio import box", err);
        return false;
      }
    }
  };

  // Note: Message handling for Photopea responses is now done in postToPhotopea's promise

  const attachButtonHandlers = () => {
    const app = window.gradioApp ? window.gradioApp() : document;
    if (!app) { return; }
    const sendButton = app.querySelector(sendButtonSelector);
    if (sendButton && !sendButton.dataset.huaPhotopeaBound) {
      sendButton.dataset.huaPhotopeaBound = "1";
      sendButton.addEventListener("click", async () => {
        const dataInput = getDataSource();
        const dataUrl = dataInput ? dataInput.value : null;
        if (!dataUrl) {
          console.warn("[Photopea] No encoded image available to send.");
          return;
        }
        // Use Photopea API to open the image
        try {
          const command = `app.open("${dataUrl}", null, false);`;
          await postToPhotopea(command);
          console.log("[Photopea] Image sent to Photopea");
        } catch (err) {
          console.error("[Photopea] Failed to send image:", err);
        }
      });
    }
    const fetchButton = app.querySelector(fetchButtonSelector);
    if (fetchButton && !fetchButton.dataset.huaPhotopeaBound) {
      fetchButton.dataset.huaPhotopeaBound = "1";
      fetchButton.addEventListener("click", async () => {
        // Use Photopea API to export the image
        try {
          const command = 'app.activeDocument.saveToOE("png");';
          const responses = await postToPhotopea(command);

          if (responses && responses[0] instanceof ArrayBuffer) {
            const base64Data = arrayBufferToBase64(responses[0]);
            const dataUrl = `data:image/png;base64,${base64Data}`;

            // Deliver to Gradio
            window.huaPhotopeaBridge.deliver({
              name: "photopea_export.png",
              data: dataUrl,
              timestamp: Date.now()
            });
          }
        } catch (err) {
          console.error("[Photopea] Failed to fetch from Photopea:", err);
        }
      });
    }
  };

  const observer = new MutationObserver(() => attachButtonHandlers());
  observer.observe(document.body, { childList: true, subtree: true });
  attachButtonHandlers();
}})();
</script>
"""

THEME_BOOTSTRAP_HTML = f"""
<script>
(function() {{
    const normalize = (value) => {{
        if (!value) return "system";
        const lower = ("" + value).toLowerCase();
        if (lower === "system" || lower === "dark" || lower === "light") return lower;
        if (value === "System") return "system";
        if (value === "Dark") return "dark";
        if (value === "Light") return "light";
        return "system";
    }};
    const resolve = (mode) => {{
        if (mode === "system" && window.matchMedia) {{
            return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        }}
        return mode === "light" ? "light" : "dark";
    }};
    let pendingBodyMode = null;
    const applyTheme = (mode) => {{
        const canonical = normalize(mode);
        const resolved = resolve(canonical);
        const root = document.documentElement;
        root.setAttribute("data-hua-theme-mode", canonical);
        root.setAttribute("data-hua-theme", resolved);
        const body = document.body;
        if (body) {{
            body.setAttribute("data-hua-theme-mode", canonical);
            body.setAttribute("data-hua-theme", resolved);
        }} else {{
            pendingBodyMode = canonical;
        }}
        return canonical;
    }};
    window.huaApplyTheme = (mode) => {{
        const canonical = applyTheme(mode);
        if (canonical === "system" && typeof window.matchMedia === "function") {{
            try {{
                if (!window.huaSystemThemeListener) {{
                    const handler = function () {{
                        const current = document.documentElement.getAttribute("data-hua-theme-mode") || "system";
                        if (current === "system") {{
                            applyTheme("system");
                        }}
                    }};
                    window.huaSystemThemeListener = handler;
                    const mq = window.matchMedia("(prefers-color-scheme: dark)");
                    if (mq) {{
                        if (typeof mq.addEventListener === "function") {{
                            mq.addEventListener("change", handler);
                        }} else if (typeof mq.addListener === "function") {{
                            mq.addListener(handler);
                        }}
                    }}
                }}
            }} catch (err) {{
                console.warn("Unable to bind system theme listener", err);
            }}
        }}
        return canonical;
    }};
    document.addEventListener("DOMContentLoaded", () => {{
        if (pendingBodyMode) {{
            applyTheme(pendingBodyMode);
            pendingBodyMode = null;
        }}
    }}, {{ once: true }});
    applyTheme("{CURRENT_THEME_MODE}");
}})();
</script>
"""

CIVITAI_BASE_URL = "https://civitai.com/api/v1"
CIVITAI_SORT_MAP = {
    "Highest Rated": "Highest Rated",
    "Most Downloaded": "Most Downloaded",
    "Newest": "Newest",
}
CIVITAI_NSFW_MAP = {
    "Hide": "false",
    "Show": "true",
    "Only": "only",
}

# Register NVML cleanup function to be called on exit
atexit.register(cleanup_nvml)

# --- Log polling imports ---
import requests  # ensure requests imported
import json
import time
# --- End log polling imports ---
import folder_paths
import node_helpers
from pathlib import Path
from server import PromptServer
from server import BinaryEventTypes
import sys
import os
import webbrowser
import glob
from datetime import datetime
from math import gcd
import uuid
import fnmatch
from .kelnel_ui.gradio_cancel_test import cancel_comfyui_task_action  # interrupt helper
from .kelnel_ui.api_json_manage import define_api_json_management_ui  # API JSON management UI

# --- Global state ---
task_queue = deque()
queue_lock = Lock()
accumulated_image_results = []  # cached image results
last_video_result = None  # latest video result path
results_lock = Lock()
processing_event = Event()  # True while processing a task
executor = ThreadPoolExecutor(max_workers=1)  # single worker for generation
last_used_seed = -1  # used by increment/decrement seed modes
seed_lock = Lock()  # protect last_used_seed
interrupt_requested_event = Event()  # signalled when user requests an interrupt

# --- ComfyUI live preview instance ---
# Use a unique suffix to avoid collisions with standalone preview tests
comfyui_previewer = ComfyUIPreviewer(client_id_suffix="gradio_workflow_integration", min_yield_interval=0.1)
# --- End global state ---

# --- Log polling helpers ---
COMFYUI_LOG_URL = "http://127.0.0.1:8188/internal/logs/raw"
all_logs_text = ""

def fetch_and_format_logs():
    global all_logs_text

    try:
        response = requests.get(COMFYUI_LOG_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        log_entries = data.get("entries", [])

        # Collapse redundant blank lines and merge log content
        formatted_logs = "\n".join(filter(None, [entry.get('m', '').strip() for entry in log_entries]))
        all_logs_text = formatted_logs

        return all_logs_text

    except requests.exceptions.RequestException as e:
        error_message = f"Unable to connect to ComfyUI server: {e}"
        return all_logs_text + "\n" + error_message if all_logs_text else error_message
    except json.JSONDecodeError:
        error_message = "Unable to parse server response (not JSON)"
        return all_logs_text + "\n" + error_message if all_logs_text else error_message
    except Exception as e:
        error_message = f"Unexpected error: {e}"
        return all_logs_text + "\n" + error_message if all_logs_text else error_message

# --- End log polling helpers ---

# --- ComfyUI node badge settings ---
# Try both API paths
COMFYUI_API_NODE_BADGE = "http://127.0.0.1:8188/settings/Comfy.NodeBadge.NodeIdBadgeMode"
# COMFYUI_API_NODE_BADGE = "http://127.0.0.1:8188/api/settings/Comfy.NodeBadge.NodeIdBadgeMode"  # alternative path

def update_node_badge_mode(mode):
    """Send POST request to update NodeIdBadgeMode"""
    try:
        # try JSON payload first
        response = requests.post(
            COMFYUI_API_NODE_BADGE,
            json=mode,  # json argument sets Content-Type to application/json
        )

        if response.status_code == 200:
            return f"[Success] Updated node badge mode to: {mode}"
        else:
            # Try to parse error message
            try:
                error_detail = response.json()  # try parsing JSON error response
                error_text = error_detail.get('error', response.text)
                error_traceback = error_detail.get('traceback', '')
                return f"[Error] Update failed (HTTP {response.status_code}): {error_text}\n{error_traceback}".strip()
            except json.JSONDecodeError:  # non-JSON error response
                return f"[Error] Update failed (HTTP {response.status_code}): {response.text}"
    except requests.exceptions.ConnectionError:
         return f"[Error] Unable to reach ComfyUI server ({COMFYUI_API_NODE_BADGE}). Ensure ComfyUI is running."
    except Exception as e:
        return f"[Error] Request failure: {str(e)}"
# --- End node badge settings ---

# --- Reboot and interrupt functions ---
COMFYUI_DEFAULT_URL_FOR_WORKFLOW = "http://127.0.0.1:8188"  # ComfyUI base URL

def reboot_manager():
    try:
        # send reboot request via GET
        reboot_url = f"{COMFYUI_DEFAULT_URL_FOR_WORKFLOW}/api/manager/reboot"
        response = requests.get(reboot_url)
        if response.status_code == 200:
            return "Reboot request sent. Please check ComfyUI in a few moments."
        else:
            return f"Reboot request failed with status code {response.status_code}"
    except Exception as e:
        return f"Error while sending reboot request: {str(e)}"

def trigger_comfyui_interrupt():
    """Proxy function allowing Gradio to trigger queue interrupt"""
    return cancel_comfyui_task_action(COMFYUI_DEFAULT_URL_FOR_WORKFLOW)

# --- End reboot/interrupt functions ---
# interrupt button removed; interruption handled via clear_queue


# --- Logging helper ---
def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]  # millisecond precision
    print(f"{timestamp} - {message}")

def _register_event_with_optional_js(register_fn, *, fn, inputs, outputs, js_code, description):
    """
    Register a Gradio event and optionally attach a JavaScript callback when the runtime supports it.
    Falls back gracefully if the current Gradio version rejects JS parameters.
    """
    kwargs = dict(fn=fn, inputs=inputs, outputs=outputs)
    if js_code is not None:
        for param_name in ("_js", "js"):
            try:
                return register_fn(**kwargs, **{param_name: js_code})
            except TypeError as exc:
                log_message(f"[UI_JS_COMPAT] {description} does not accept '{param_name}' parameter ({exc}).")
    if js_code is not None:
        log_message(f"[UI_JS_COMPAT] {description} registered without JS bridge; functionality is limited.")
    return register_fn(**kwargs)

# Helper to locate node by class_type
def find_key_by_class_type(prompt, class_type):
    for key, value in prompt.items():
        # direct class_type check
        if isinstance(value, dict) and value.get("class_type") == class_type:
            return key
    return None

def find_all_keys_by_class_type(prompt, class_type):
    """Find ALL nodes matching class_type, not just the first one."""
    matches = []
    for key, value in prompt.items():
        if isinstance(value, dict) and value.get("class_type") == class_type:
            matches.append(key)
    return matches

def check_seed_node(json_file):
    workflow_dir, workflow_name, workflow_path = resolve_workflow_components(json_file)
    if not workflow_path:
        print(f"JSON file invalid or missing: {json_file}")
        return gr.update(visible=False)
    json_path = workflow_path
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
        # use real class names from workflow metadata
        seed_key = find_key_by_class_type(prompt, "Hua_gradio_Seed")
        return gr.update(visible=seed_key is not None)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing JSON file ({json_file}): {e}")
        return gr.update(visible=False)

current_dir = os.path.dirname(os.path.abspath(__file__))
print("Plugin directory:", current_dir)
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(parent_dir)
try:
    from comfy.cli_args import args
except ImportError:
    print("Unable to import comfy.cli_args; some features may be limited.")
    args = None  # default fallback to avoid NameError

# Try importing icon metadata; fall back if missing
try:
    from .node.hua_icons import icons
except ImportError:
    print("Unable to import .hua_icons; using default category names.")
    icons = {"hua_boy_one": "Gradio"}  # default mapping

class GradioTextOk:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),
                "name": ("STRING", {"multiline": False, "default": "GradioTextOk", "tooltip": "Node name"}),
            }
        }
    RETURN_TYPES = ("STRING",)
    FUNCTION = "encode"
    CATEGORY = icons.get("hua_boy_one", "Gradio")  # default fallback category
    DESCRIPTION = "Encodes a text prompt..."
    def encode(self, string, name):
        return (string,)

INPUT_DIR = folder_paths.get_input_directory()
OUTPUT_DIR = folder_paths.get_output_directory()
TEMP_DIR = folder_paths.get_temp_directory()
try:
    USER_ROOT_DIR = folder_paths.get_user_directory()
except AttributeError:
    USER_ROOT_DIR = os.path.join(os.path.dirname(OUTPUT_DIR), "user")
USER_WORKFLOW_DIR = os.path.join(USER_ROOT_DIR, "default", "workflows")
WORKFLOW_FILE_MAP = {}

def cleanup_old_temp_files():
    """Clean up stale temp JSON files from previous sessions or crashes."""
    import glob
    try:
        pattern = os.path.join(TEMP_DIR, "*.json")
        temp_files = glob.glob(pattern)

        if not temp_files:
            return

        current_time = time.time()
        cleaned_count = 0

        for temp_file in temp_files:
            try:
                # Only remove files older than 1 hour (3600 seconds)
                file_age = current_time - os.path.getmtime(temp_file)
                if file_age > 3600:
                    os.remove(temp_file)
                    cleaned_count += 1
            except OSError as e:
                # Ignore errors for individual files
                pass

        if cleaned_count > 0:
            print(f"[CLEANUP] Removed {cleaned_count} old temp files from {TEMP_DIR}")
    except Exception as e:
        print(f"[CLEANUP] Warning: Failed to clean up temp files: {e}")

# Clean up old temp files on startup
cleanup_old_temp_files()

def _register_workflow_file(display_name, directory, filename):
    WORKFLOW_FILE_MAP[display_name] = {
        "folder": directory,
        "filename": filename,
        "path": os.path.join(directory, filename),
    }

def resolve_workflow_components(selection):
    meta = WORKFLOW_FILE_MAP.get(selection)
    if meta:
        return meta["folder"], meta["filename"], meta["path"]
    if selection:
        if selection not in WORKFLOW_FILE_MAP:
            get_json_files()
            meta = WORKFLOW_FILE_MAP.get(selection)
            if meta:
                return meta["folder"], meta["filename"], meta["path"]
        fallback_path = os.path.join(OUTPUT_DIR, selection)
        if os.path.exists(fallback_path):
            return os.path.dirname(fallback_path), os.path.basename(fallback_path), fallback_path
    return None, None, None

# --- Load Resolution Presets from File ---
# resolution_files and resolution_prefixes are defined here
resolution_files = [
    "Sample_preview/flux_resolution.txt",
    "Sample_preview/sdxl_1_5_resolution.txt"
]
resolution_prefixes = [
    "Flux - ",
    "SDXL - "
]
# load_resolution_presets_from_files is now imported from ui_def
# It needs current_dir (script_dir)
resolution_presets = load_resolution_presets_from_files(resolution_files, resolution_prefixes, current_dir)
# Add a print statement to confirm loading
print(f"Final resolution_presets count (including 'custom'): {len(resolution_presets)}")
if len(resolution_presets) < 10: # Print some examples if loading failed or files are short
    print(f"Example presets: {resolution_presets[:10]}")
# --- End Load Resolution Presets ---


def start_queue(prompt_workflow, client_id=None):
    if isinstance(prompt_workflow, dict):
        missing_nodes = [node_id for node_id, node_data in prompt_workflow.items()
                         if not isinstance(node_data, dict) or "class_type" not in node_data]
        if missing_nodes:
            print(f"Prompt validation failed locally. Missing class_type for nodes: {missing_nodes}")
            return None
    client_id = client_id or f"gradio_workflow_{uuid.uuid4().hex}"
    payload = {"prompt": prompt_workflow, "client_id": client_id}
    URL = "http://127.0.0.1:8188/prompt"
    max_retries = 5
    retry_delay = 10
    request_timeout = 60

    for attempt in range(max_retries):
        try:
            # simplified server check: try POST directly
            response = requests.post(URL, json=payload, timeout=request_timeout)
            response.raise_for_status()  # raise on 4xx/5xx
            prompt_id = ""
            try:
                response_payload = response.json()
                prompt_id = response_payload.get("prompt_id") or response_payload.get("promptId") or ""
            except (json.JSONDecodeError, ValueError):
                pass
            print(f"Prompt submission succeeded (attempt {attempt + 1}/{max_retries})"
                  f"{' prompt_id=' + prompt_id if prompt_id else ''} using client_id={client_id}")
            return prompt_id or ""  # success (prompt_id may be blank on older servers)
        except requests.exceptions.HTTPError as http_err:  # handle HTTP errors
            status_code = http_err.response.status_code
            text = ""
            try:
                text = http_err.response.text
            except Exception:
                pass
            print(f"Prompt submission failed (attempt {attempt + 1}/{max_retries}, HTTP {status_code}): {str(http_err)} {text}")
            if status_code == 400:  # invalid prompt
                print("Received HTTP 400 (likely invalid prompt); aborting retries.")
                return None  # do not retry
            # for other HTTP errors continue retry loop
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("Reached maximum retries (HTTPError). Giving up.")
                return None
        except requests.exceptions.RequestException as e:  # network errors (timeout, connection, etc.)
            error_type = type(e).__name__
            print(f"Prompt request failed (attempt {attempt + 1}/{max_retries}, {error_type}): {str(e)}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("Reached maximum retries (RequestException). Giving up.")
                print("Possible causes: server not running or a network problem.")
                return None  # request failed
    return None  # ensure consistent failure indicator

def get_json_files():
    WORKFLOW_FILE_MAP.clear()
    discovered = []
    search_dirs = []
    if OUTPUT_DIR and os.path.isdir(OUTPUT_DIR):
        search_dirs.append(OUTPUT_DIR)
    if USER_WORKFLOW_DIR and os.path.isdir(USER_WORKFLOW_DIR):
        search_dirs.append(USER_WORKFLOW_DIR)

    for directory in search_dirs:
        try:
            entries = sorted(
                name for name in os.listdir(directory)
                if name.endswith(".json") and os.path.isfile(os.path.join(directory, name))
            )
        except FileNotFoundError:
            continue
        except Exception as exc:
            print(f"Error while listing JSON files in {directory}: {exc}")
            continue

        for filename in entries:
            if os.path.abspath(directory) == os.path.abspath(OUTPUT_DIR):
                display = filename
            else:
                rel_path = os.path.relpath(os.path.join(directory, filename), USER_ROOT_DIR)
                display = rel_path.replace(os.sep, "/")

            base_display = display
            suffix = 2
            while display in WORKFLOW_FILE_MAP:
                display = f"{base_display} ({suffix})"
                suffix += 1

            _register_workflow_file(display, directory, filename)
            discovered.append(display)

    return discovered

def refresh_json_files():
    new_choices = get_json_files()
    return gr.update(choices=new_choices)

# strip_prefix, parse_resolution, calculate_aspect_ratio, find_closest_preset are now imported from ui_def

def update_from_preset(resolution_str_with_prefix):
    if resolution_str_with_prefix == "custom":
        # return empty updates so the user can type manually
        return "custom", gr.update(), gr.update(), "Current ratio: Custom"

    # parse_resolution is imported, needs resolution_prefixes
    width, height, ratio, original_str = parse_resolution(resolution_str_with_prefix, resolution_prefixes)

    if width is None:  # invalid format
        return "custom", gr.update(), gr.update(), "Current ratio: Invalid format"

    # Return the original string with prefix for the dropdown value
    return original_str, width, height, f"Current ratio: {ratio}"

def update_from_inputs(width, height):
    # calculate_aspect_ratio and find_closest_preset are imported
    # find_closest_preset needs resolution_presets and resolution_prefixes
    ratio = calculate_aspect_ratio(width, height)
    closest_preset = find_closest_preset(width, height, resolution_presets, resolution_prefixes)
    return closest_preset, f"Current ratio: {ratio}"

def flip_resolution(width, height):
    if width is None or height is None:
        return None, None
    try:
        # ensure we return numeric values
        return int(height), int(width)
    except (ValueError, TypeError):
        return width, height  # fallback if conversion fails

# --- Model list helpers ---
def get_model_list(model_type):
    try:
        # include "None" option
        return ["None"] + folder_paths.get_filename_list(model_type)
    except Exception as e:
        print(f"Error retrieving list for {model_type}: {e}")
        return ["None"]

# --- Image helpers ---
def _load_image_from_path(path, execution_id):
    if not path:
        return None
    try:
        with Image.open(path) as pil_img:
            return pil_img.convert("RGBA")
    except FileNotFoundError:
        print(f"[{execution_id}] Image path not found: {path}")
    except Exception as exc:
        print(f"[{execution_id}] Error loading image from '{path}': {exc}")
    return None


def _decode_base64_image(data, execution_id):
    if not isinstance(data, str):
        return None
    if data.startswith("data:image"):
        try:
            header, encoded = data.split(",", 1)
        except ValueError:
            print(f"[{execution_id}] Invalid data URL format.")
            return None
    else:
        encoded = data
    try:
        binary = base64.b64decode(encoded)
        with Image.open(io.BytesIO(binary)) as pil_img:
            return pil_img.convert("RGBA")
    except Exception as exc:
        print(f"[{execution_id}] Failed to decode base64 image: {exc}")
        return None


try:
    from gradio.data_classes import FileData as GradioFileData  # type: ignore
except Exception:
    GradioFileData = None


def _decode_payload_to_pil(payload, execution_id, skip_keys=None):
    skip_keys = set(skip_keys or ())
    if payload is None:
        return None
    if isinstance(payload, Image.Image):
        return payload
    if isinstance(payload, np.ndarray):
        try:
            if payload.ndim == 2:
                payload = np.stack([payload]*3, axis=-1)
            if payload.ndim == 3 and payload.shape[2] == 4:
                mode = "RGBA"
            else:
                mode = "RGB"
            return Image.fromarray(payload.astype(np.uint8), mode=mode)
        except Exception as exc:
            print(f"[{execution_id}] Unsupported numpy payload: {exc}")
            return None
    if isinstance(payload, (bytes, bytearray)):
        try:
            with Image.open(io.BytesIO(payload)) as pil_img:
                return pil_img.convert("RGBA")
        except Exception as exc:
            print(f"[{execution_id}] Failed to decode raw bytes: {exc}")
            return None
    if isinstance(payload, str):
        return _load_image_from_path(payload, execution_id) or _decode_base64_image(payload, execution_id)
    if GradioFileData is not None and isinstance(payload, GradioFileData):
        candidate_path = getattr(payload, "path", None)
        pil_img = _decode_payload_to_pil(candidate_path, execution_id, skip_keys)
        if pil_img is not None:
            return pil_img
        candidate_data = getattr(payload, "data", None)
        return _decode_payload_to_pil(candidate_data, execution_id, skip_keys)
    if isinstance(payload, (list, tuple)):
        for item in payload:
            pil_img = _decode_payload_to_pil(item, execution_id, skip_keys)
            if pil_img is not None:
                return pil_img
        return None
    if isinstance(payload, dict):
        for key in ("image", "background", "value", "data", "orig", "canvas", "input"):
            if key in payload and key not in skip_keys:
                pil_img = _decode_payload_to_pil(payload[key], execution_id, skip_keys)
                if pil_img is not None:
                    return pil_img
        for key in ("path", "name", "tempfile"):
            if key in payload and key not in skip_keys:
                pil_img = _decode_payload_to_pil(payload[key], execution_id, skip_keys)
                if pil_img is not None:
                    return pil_img
        for key, value in payload.items():
            if key in skip_keys:
                continue
            pil_img = _decode_payload_to_pil(value, execution_id, skip_keys)
            if pil_img is not None:
                return pil_img
        return None
    print(f"[{execution_id}] Warning: unrecognized payload type {type(payload)}.")
    return None


def _extract_mask_from_editor_payload(payload, execution_id):
    if not isinstance(payload, dict):
        return None
    combined_mask = None
    layers = payload.get("layers")
    if isinstance(layers, (list, tuple)):
        for layer_payload in layers:
            layer_img = _decode_payload_to_pil(layer_payload, execution_id)
            if layer_img is None:
                continue
            try:
                alpha = layer_img.split()[-1] if layer_img.mode in ("RGBA", "LA") else layer_img.convert("RGBA").split()[-1]
                alpha_l = alpha.convert("L")
                combined_mask = alpha_l if combined_mask is None else ImageChops.lighter(combined_mask, alpha_l)
            except Exception as exc:
                print(f"[{execution_id}] Unable to extract alpha from editor layer: {exc}")
    background_payload = payload.get("background")
    composite_payload = payload.get("composite")
    if background_payload is not None and composite_payload is not None:
        background_img = _decode_payload_to_pil(background_payload, execution_id)
        composite_img = _decode_payload_to_pil(composite_payload, execution_id)
        if background_img and composite_img and background_img.size == composite_img.size:
            try:
                diff = ImageChops.difference(composite_img.convert("RGB"), background_img.convert("RGB")).convert("L")
                diff_mask = diff.point(lambda px: 255 if px > 12 else 0)
                if diff_mask.getbbox():
                    combined_mask = diff_mask if combined_mask is None else ImageChops.lighter(combined_mask, diff_mask)
            except Exception as exc:
                print(f"[{execution_id}] Failed to derive mask diff: {exc}")
    if combined_mask is not None:
        try:
            normalized = combined_mask.point(lambda px: 255 if px >= 10 else 0)
            if normalized.getbbox():
                return normalized
            return combined_mask
        except Exception:
            return combined_mask
    return None


def _coerce_uploaded_image_to_pil(upload, execution_id, *, return_mask=False):
    mask_image = None
    if isinstance(upload, dict):
        mask_payload = upload.get("mask") or upload.get("alpha")
        if mask_payload is not None and mask_payload is not upload:
            mask_image = _decode_payload_to_pil(mask_payload, execution_id)
        if mask_image is None:
            mask_image = _extract_mask_from_editor_payload(upload, execution_id)
    image = _decode_payload_to_pil(upload, execution_id, skip_keys={"mask", "alpha"})
    if return_mask:
        return image, mask_image if isinstance(mask_image, Image.Image) else None
    return image


def _encode_pil_to_data_url(image, *, format_hint="PNG"):
    if image is None:
        return None
    try:
        buffer = io.BytesIO()
        fmt = (format_hint or "PNG").upper()
        writable = image.convert("RGBA") if fmt == "PNG" else image
        writable.save(buffer, format=fmt)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/{fmt.lower()};base64,{encoded}"
    except Exception as exc:
        print(f"[DATA_URL] Failed to encode image: {exc}")
        return None


def _assign_unique_ids_to_outputs(prompt, base_token):
    image_ids = []
    video_ids = []
    if not isinstance(prompt, dict):
        return image_ids, video_ids

    image_nodes = find_all_nodes_by_class_type(prompt, "Hua_Output")
    for idx, node_info in enumerate(image_nodes):
        node_id = node_info.get("id")
        if not node_id or node_id not in prompt:
            continue
        unique_id = f"{base_token}_img{idx}"
        node_inputs = prompt[node_id].setdefault("inputs", {})
        node_inputs["unique_id"] = unique_id
        image_ids.append(unique_id)
        print(f"[{base_token}] Assigned image unique_id '{unique_id}' to Hua_Output node {node_id}.")

    video_nodes = find_all_nodes_by_class_type(prompt, "Hua_Video_Output")
    for idx, node_info in enumerate(video_nodes):
        node_id = node_info.get("id")
        if not node_id or node_id not in prompt:
            continue
        unique_id = f"{base_token}_vid{idx}"
        node_inputs = prompt[node_id].setdefault("inputs", {})
        node_inputs["unique_id"] = unique_id
        video_ids.append(unique_id)
        print(f"[{base_token}] Assigned video unique_id '{unique_id}' to Hua_Video_Output node {node_id}.")

    return image_ids, video_ids


def _wait_for_prompt_completion(client_id, prompt_id, *, timeout=420, poll_interval=0.75):
    if not client_id or not prompt_id:
        return None

    deadline = time.time() + timeout
    history_url = f"http://127.0.0.1:8188/history/{client_id}"
    last_status = None
    failure_streak = 0
    max_failures = 12  # roughly ~9 seconds with default poll interval

    while time.time() < deadline:
        try:
            response = requests.get(history_url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            failure_streak = 0
        except requests.exceptions.RequestException as exc:
            failure_streak += 1
            print(f"[{prompt_id}] History poll failed ({exc}); retrying...")
            if failure_streak >= max_failures:
                print(f"[{prompt_id}] History poll giving up after {failure_streak} consecutive failures.")
                break
            time.sleep(min(poll_interval * 2, 2.0))
            continue
        except json.JSONDecodeError as exc:
            print(f"[{prompt_id}] Unable to parse history response ({exc}); retrying...")
            time.sleep(poll_interval)
            continue

        prompt_entry = None
        if isinstance(payload, dict):
            prompt_entry = payload.get(prompt_id)
            if prompt_entry is None:
                history_dict = payload.get("history") or payload.get("prompts") or payload.get("data")
                if isinstance(history_dict, dict):
                    prompt_entry = history_dict.get(prompt_id)

        if prompt_entry:
            raw_status = prompt_entry.get("status")
            status_value = None
            if isinstance(raw_status, dict):
                status_value = raw_status.get("status") or raw_status.get("result")
            elif isinstance(raw_status, str):
                status_value = raw_status

            # Debug: log what we actually received
            if status_value:
                normalized = str(status_value).lower()
                last_status = normalized
                if normalized in {"completed", "complete", "finished", "success", "succeeded"}:
                    print(f"[{prompt_id}] Prompt marked as {normalized} in history.")
                    return prompt_entry
                if normalized in {"error", "failed", "failure", "cancelled", "canceled", "stopped"}:
                    print(f"[{prompt_id}] Prompt marked as {normalized} in history.")
                    return prompt_entry
            else:
                # No status value but entry exists - might mean it's still processing or complete without explicit status
                # Check if entry has 'outputs' field which indicates completion
                if "outputs" in prompt_entry or "images" in prompt_entry:
                    print(f"[{prompt_id}] Prompt entry found with outputs but no explicit status - assuming complete.")
                    return prompt_entry

        time.sleep(poll_interval)

    if last_status:
        print(f"[{prompt_id}] History poll timed out after {timeout}s (last status: {last_status}).")
    else:
        print(f"[{prompt_id}] History poll timed out after {timeout}s (no status available).")
    return None


def _wait_for_output_json(unique_ids, *, timeout=420, poll_interval=0.5):
    resolved = {}
    pending = {uid: os.path.join(TEMP_DIR, f"{uid}.json") for uid in unique_ids if uid}
    if not pending:
        return resolved, {}

    deadline = time.time() + timeout
    start_time = time.time()
    last_log_time = start_time

    while pending and time.time() < deadline:
        # Check if processing has been interrupted or aborted
        if interrupt_requested_event.is_set():
            print(f"[OUTPUT_JSON] Interrupt detected, aborting wait for {len(pending)} pending outputs")
            break

        # Check if processing event was cleared (indicates abort)
        if not processing_event.is_set():
            elapsed = time.time() - start_time
            if elapsed > 30:  # Allow 30 seconds grace period for normal completion
                print(f"[OUTPUT_JSON] Processing aborted, returning {len(resolved)} resolved outputs")
                break

        for uid, path in list(pending.items()):
            if not os.path.exists(path):
                continue
            try:
                if os.path.getsize(path) == 0:
                    continue
            except OSError:
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    resolved[uid] = json.load(handle)
                del pending[uid]
                try:
                    os.remove(path)
                except OSError:
                    pass
                print(f"[{uid}] Loaded output metadata from {path}.")
            except (OSError, json.JSONDecodeError):
                # File may still be in-flight; retry on next loop
                continue

        # Log progress every 10 seconds if still waiting
        current_time = time.time()
        if pending and (current_time - last_log_time) >= 10:
            elapsed = current_time - start_time
            print(f"[OUTPUT_JSON] Still waiting for {len(pending)} outputs after {elapsed:.1f}s (timeout in {deadline - current_time:.1f}s)")
            last_log_time = current_time

        if pending:
            time.sleep(poll_interval)

    # Clean up any remaining pending temp files on timeout or abort
    if pending:
        print(f"[OUTPUT_JSON] Cleaning up {len(pending)} pending temp files")
        for uid, path in pending.items():
            try:
                if os.path.exists(path):
                    os.remove(path)
                    print(f"[{uid}] Removed stale temp file: {path}")
            except OSError as e:
                print(f"[{uid}] Failed to remove temp file {path}: {e}")

    return resolved, pending


def _extract_paths_from_output_payload(payload_map, *, kind):
    collected_paths = []
    errors = []
    for uid, payload in payload_map.items():
        try:
            paths = []
            error_message = None
            if isinstance(payload, list):
                paths = payload
            elif isinstance(payload, dict):
                error_message = payload.get("error")
                paths = payload.get("generated_files") or payload.get("files") or []
            else:
                error_message = f"Unexpected {kind} JSON payload type: {type(payload)}"

            for path in paths:
                normalized_path = path
                if isinstance(path, str) and not os.path.isabs(path):
                    normalized_path = os.path.abspath(path)
                if isinstance(normalized_path, str):
                    collected_paths.append(normalized_path)
                else:
                    error_message = error_message or f"Invalid path entry for {uid}: {path!r}"

            if error_message:
                errors.append(f"{uid}: {error_message}")
        except Exception as exc:
            errors.append(f"{uid}: failed to parse {kind} payload ({exc})")
    return collected_paths, errors


def _resolve_history_item_path(item, *, expected_kind):
    if not isinstance(item, dict):
        return None
    filename = item.get("filename")
    if not filename:
        return None
    subfolder = item.get("subfolder") or ""
    base_type = item.get("type") or ""
    base_dir = None
    if base_type == "output":
        base_dir = OUTPUT_DIR
    elif base_type == "temp":
        base_dir = TEMP_DIR
    elif base_type == "input":
        base_dir = INPUT_DIR
    if base_dir is None:
        base_dir = OUTPUT_DIR if expected_kind == "image" else TEMP_DIR
    path = os.path.join(base_dir, subfolder, filename)
    return os.path.abspath(path)


def _extract_paths_from_history_entry(history_entry):
    image_paths = []
    video_paths = []
    errors = []
    if not isinstance(history_entry, dict):
        return image_paths, video_paths, errors

    outputs = history_entry.get("outputs") or history_entry.get("output")
    if not isinstance(outputs, dict):
        return image_paths, video_paths, errors

    seen = set()

    for node_id, node_outputs in outputs.items():
        if not isinstance(node_outputs, dict):
            continue
        for image_info in node_outputs.get("images", []):
            path = _resolve_history_item_path(image_info, expected_kind="image")
            if path:
                if os.path.isfile(path):
                    if path not in seen:
                        image_paths.append(path)
                        seen.add(path)
                else:
                    errors.append(f"{node_id}: image file missing at '{path}'")
        for video_info in node_outputs.get("videos", []):
            path = _resolve_history_item_path(video_info, expected_kind="video")
            if path:
                if os.path.isfile(path):
                    if path not in seen:
                        video_paths.append(path)
                        seen.add(path)
                else:
                    errors.append(f"{node_id}: video file missing at '{path}'")

    return image_paths, video_paths, errors


def _format_gallery_items(paths):
    formatted = []
    for entry in paths or []:
        if isinstance(entry, dict):
            candidate = entry.get("path") or entry.get("filename")
            if candidate:
                formatted.append(candidate)
            else:
                formatted.append(entry)
        elif isinstance(entry, (list, tuple)) and entry:
            formatted.append(entry[0])
        else:
            formatted.append(entry)
    return formatted


def _ensure_absolute_path(path):
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(OUTPUT_DIR, path))


def _inject_mask_into_prompt(prompt, mask_filename, execution_id):
    if not mask_filename:
        return
    mask_keys = {"mask", "mask_image", "mask_input", "mask_path", "mask_file"}
    for node_id, node_data in (prompt or {}).items():
        inputs = node_data.get("inputs") if isinstance(node_data, dict) else None
        if not isinstance(inputs, dict):
            continue
        updated = False
        for key in mask_keys:
            if key not in inputs:
                continue
            value = inputs[key]
            if isinstance(value, list):  # respect existing connections
                continue
            inputs[key] = mask_filename
            updated = True
        if updated:
            print(f"[{execution_id}] Injected mask '{mask_filename}' into node {node_id}.")


def _parse_ksampler_settings(workflow_info, flat_values):
    settings = []
    dynamic_data = (workflow_info or {}).get("dynamic_components", {}).get("KSampler", [])

    def _coerce_int(value, default=0):
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (ValueError, TypeError):
            return default

    def _coerce_float(value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    for idx in range(MAX_KSAMPLER_CONTROLS):
        base = idx * 9
        fields = list(flat_values[base:base + 9])
        while len(fields) < 9:
            fields.append(None)

        steps_val, cfg_val, sampler_val, scheduler_val, start_step_val, end_step_val, add_noise_val, return_leftover_val, noise_seed_val = fields[:9]
        source_node_data = dynamic_data[idx] if idx < len(dynamic_data) else {}

        settings.append({
            "steps": _coerce_int(steps_val, 20),
            "cfg": _coerce_float(cfg_val, 7.0),
            "sampler_name": sampler_val if isinstance(sampler_val, str) else (sampler_val or ""),
            "scheduler": scheduler_val if isinstance(scheduler_val, str) else (scheduler_val or ""),
            "start_at_step": _coerce_int(start_step_val, 0),
            "end_at_step": _coerce_int(end_step_val, 0),
            "add_noise": add_noise_val or "enable",
            "return_with_leftover_noise": return_leftover_val or "disable",
            "seed_value": noise_seed_val,
            "seed_field": source_node_data.get("seed_field", "noise_seed"),
        })
    return settings


def _parse_mask_settings(mask_flat):
    settings = []

    def _as_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "on", "enable"}
        if value is None:
            return default
        return bool(value)

    def _as_float(value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    for idx in range(MAX_MASK_GENERATORS):
        base = idx * MASK_FIELD_COUNT
        fields = list(mask_flat[base:base + MASK_FIELD_COUNT])
        while len(fields) < MASK_FIELD_COUNT:
            fields.append(None)
        settings.append({
            "face_mask": _as_bool(fields[0], True),
            "background_mask": _as_bool(fields[1], False),
            "hair_mask": _as_bool(fields[2], False),
            "body_mask": _as_bool(fields[3], False),
            "clothes_mask": _as_bool(fields[4], False),
            "confidence": _as_float(fields[5], 0.15),
            "refine_mask": _as_bool(fields[6], False),
        })
    return settings


def _parse_image_loader_settings(loader_data, flat_values):
    settings = []

    def _as_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "on", "enable"}
        if value is None:
            return default
        return bool(value)

    def _as_int(value, default=None):
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (ValueError, TypeError):
            return default

    for idx in range(MAX_IMAGE_LOADERS):
        base = idx * IMAGE_LOADER_FIELD_COUNT
        fields = list(flat_values[base:base + IMAGE_LOADER_FIELD_COUNT])
        while len(fields) < IMAGE_LOADER_FIELD_COUNT:
            fields.append(None)
        loader_info = loader_data[idx] if idx < len(loader_data) else {}
        settings.append({
            "resize": _as_bool(fields[0], loader_info.get("resize", False)),
            "width": _as_int(fields[1], loader_info.get("width")),
            "height": _as_int(fields[2], loader_info.get("height")),
            "keep_proportion": _as_bool(fields[3], loader_info.get("keep_proportion", False)),
            "divisible_by": _as_int(fields[4], loader_info.get("divisible_by")),
        })
    return settings


lora_list = get_model_list("loras")
checkpoint_list = get_model_list("checkpoints")
unet_list = get_model_list("unet")  # assume UNet models live under the "unet" directory

# get_output_images is now imported from ui_def

# generate_image accepts lists of dynamic components
def generate_image(
    inputimage1,
    input_video,
    dynamic_positive_prompts_values,
    prompt_text_negative,
    json_file,
    hua_width,
    hua_height,
    dynamic_loras_values,
    hua_checkpoint,
    hua_unet,
    dynamic_float_nodes_values,
    dynamic_int_nodes_values,
    dynamic_ksampler_values,
    dynamic_mask_generator_values,
    dynamic_image_loader_values,
    seed_mode,
    fixed_seed,
    negative_prompt_extra_values=None,
):
    global last_used_seed
    execution_id = str(uuid.uuid4())
    print(f"[{execution_id}] Generation task started (seed mode: {seed_mode})")
    output_type = None

    if not json_file:
        print(f"[{execution_id}] Error: no workflow JSON selected.")
        return None, None

    workflow_dir, workflow_name, workflow_path = resolve_workflow_components(json_file)
    if not workflow_path:
        print(f"[{execution_id}] Error: workflow JSON not found for selection '{json_file}'")
        return None, None

    prompt = load_prompt_from_file(workflow_path)
    if not isinstance(prompt, dict) or not prompt:
        print(f"[{execution_id}] Failed to load workflow '{workflow_path}': unsupported or empty structure.")
        return None, None

    workflow_info = get_workflow_defaults_and_visibility(
        workflow_name if workflow_name else "",
        workflow_dir if workflow_dir else OUTPUT_DIR,
        resolution_prefixes,
        resolution_presets,
        MAX_DYNAMIC_COMPONENTS
    )

    queue_client_id = None
    try:
        if 'comfyui_previewer' in globals():
            previewer_client = getattr(comfyui_previewer, "client_id", None)
            if isinstance(previewer_client, str) and previewer_client:
                queue_client_id = previewer_client
    except Exception:
        queue_client_id = None

    output_tracking_token = execution_id.replace("-", "")
    image_result_ids, video_result_ids = _assign_unique_ids_to_outputs(prompt, output_tracking_token)
    if not image_result_ids and not video_result_ids:
        print(f"[{execution_id}] Warning: no Hua output nodes discovered; results will rely on default ComfyUI paths.")
    if not queue_client_id:
        queue_client_id = f"gradio_workflow_{output_tracking_token}"

    snapshot_mtime = time.time()
    preexisting_outputs = {}
    try:
        for existing_path in get_output_images(OUTPUT_DIR):
            try:
                preexisting_outputs[existing_path] = os.path.getmtime(existing_path)
            except OSError:
                preexisting_outputs[existing_path] = None
    except Exception as exc:
        print(f"[{execution_id}] Warning: unable to snapshot output directory before run: {exc}")

    # Find ALL image input nodes (workflows may have multiple)
    gradio_input_keys = find_all_keys_by_class_type(prompt, 'GradioInputImage')
    load_and_resize_keys = find_all_keys_by_class_type(prompt, 'LoadAndResizeImage')
    load_image_keys = find_all_keys_by_class_type(prompt, 'LoadImage')
    all_image_input_keys = gradio_input_keys + load_and_resize_keys + load_image_keys

    video_input_key = find_key_by_class_type(prompt, 'VHS_LoadVideo')
    seed_key = find_key_by_class_type(prompt, 'Hua_gradio_Seed')
    text_bad_key = find_key_by_class_type(prompt, 'GradioTextBad')
    resolution_key = find_key_by_class_type(prompt, 'Hua_gradio_resolution')
    checkpoint_key = find_key_by_class_type(prompt, 'Hua_CheckpointLoaderSimple')
    unet_key = find_key_by_class_type(prompt, 'Hua_UNETLoader')
    hua_output_key = find_key_by_class_type(prompt, 'Hua_Output')
    hua_video_output_key = find_key_by_class_type(prompt, 'Hua_Video_Output')

    saved_mask_filename = None
    saved_mask_path = None

    # Update ALL image input nodes with the uploaded image
    if all_image_input_keys and inputimage1 is not None:
        base_img, mask_img = _coerce_uploaded_image_to_pil(inputimage1, execution_id, return_mask=True)
        if base_img is not None:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                inputfilename = f"gradio_input_{timestamp}_{random.randint(100, 999)}.png"
                save_path = os.path.join(INPUT_DIR, inputfilename)
                base_img.convert('RGBA').save(save_path)

                # Set the image parameter on ALL image input nodes
                for node_key in all_image_input_keys:
                    prompt[node_key].setdefault('inputs', {})['image'] = inputfilename
                    node_type = prompt[node_key].get('class_type', 'unknown')
                    print(f"[{execution_id}] Updated node {node_key} ({node_type}) with input image")

                print(f"[{execution_id}] Saved input image to {save_path} (updated {len(all_image_input_keys)} nodes)")
            except Exception as exc:
                print(f"[{execution_id}] Failed to save input image: {exc}")
        if mask_img is not None:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                saved_mask_filename = f"gradio_input_mask_{timestamp}_{random.randint(100, 999)}.png"
                saved_mask_path = os.path.join(INPUT_DIR, saved_mask_filename)
                mask_l = mask_img.convert('L')
                if base_img and mask_l.size != base_img.size:
                    try:
                        mask_l = mask_l.resize(base_img.size, Image.NEAREST)
                        print(f"[{execution_id}] Resized mask to match input image {base_img.size}.")
                    except Exception as resize_exc:
                        print(f"[{execution_id}] Warning: failed to resize mask: {resize_exc}")
                alpha_channel = ImageOps.invert(mask_l)
                alpha_channel.save(saved_mask_path)
                print(f"[{execution_id}] Saved mask to {saved_mask_path}")
            except Exception as mask_exc:
                print(f"[{execution_id}] Warning: unable to save mask payload: {mask_exc}")
                saved_mask_filename = None
                saved_mask_path = None
    elif inputimage1 is not None:
        print(f"[{execution_id}] Warning: input payload provided but no image input node found in workflow.")
        print(f"[{execution_id}] Supported node types: GradioInputImage, LoadAndResizeImage, LoadImage")

    if saved_mask_filename:
        _inject_mask_into_prompt(prompt, saved_mask_filename, execution_id)

    if video_input_key:
        if input_video and os.path.exists(input_video):
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                original_ext = os.path.splitext(input_video)[1]
                inputvideofilename = f"gradio_input_{timestamp}_{random.randint(100, 999)}{original_ext}"
                dest_path = os.path.join(INPUT_DIR, inputvideofilename)
                shutil.copy2(input_video, dest_path)
                prompt[video_input_key]['inputs']['video'] = inputvideofilename
                print(f"[{execution_id}] Copied input video to {dest_path}")
            except Exception as exc:
                print(f"[{execution_id}] Failed to handle input video: {exc}")
                prompt[video_input_key]['inputs'].pop('video', None)
        else:
            prompt.get(video_input_key, {}).get('inputs', {}).pop('video', None)

    current_seed = None
    with seed_lock:
        if seed_mode == 'Random':
            current_seed = random.randint(0, 0xffffffff)
            last_used_seed = current_seed
        elif seed_mode == 'Increment':
            if last_used_seed == -1:
                last_used_seed = random.randint(0, 0xffffffff - 1)
            last_used_seed = (last_used_seed + 1) & 0xffffffff
            current_seed = last_used_seed
        elif seed_mode == 'Decrement':
            if last_used_seed == -1:
                last_used_seed = random.randint(1, 0xffffffff)
            last_used_seed = (last_used_seed - 1) & 0xffffffff
            current_seed = last_used_seed
        elif seed_mode == 'Fixed':
            try:
                current_seed = int(fixed_seed) & 0xffffffff
                last_used_seed = current_seed
            except (ValueError, TypeError):
                current_seed = random.randint(0, 0xffffffff)
                last_used_seed = current_seed
                print(f"[{execution_id}] Warning: invalid fixed seed '{fixed_seed}', falling back to random {current_seed}")
        else:
            current_seed = random.randint(0, 0xffffffff)
            last_used_seed = current_seed
            print(f"[{execution_id}] Warning: unknown seed mode '{seed_mode}'. Using random seed {current_seed}")

    if current_seed is not None:
        if seed_key:
            prompt[seed_key]['inputs']['seed'] = current_seed
            print(f"[{execution_id}] Using seed {current_seed} ({seed_mode})")
        else:
            print(f"[{execution_id}] Using seed {current_seed} ({seed_mode}) (no dedicated seed node found; applying directly to samplers)")

    actual_positive_prompt_nodes = workflow_info['dynamic_components'].get('GradioTextOk', [])
    for i, node_info in enumerate(actual_positive_prompt_nodes):
        if i < len(dynamic_positive_prompts_values):
            node_id_to_update = node_info.get('id')
            if node_id_to_update in prompt:
                prompt[node_id_to_update]['inputs']['string'] = dynamic_positive_prompts_values[i]
                print(f"[{execution_id}] Updated positive prompt node {node_id_to_update} (UI slot {i+1}).")

    if negative_prompt_extra_values:
        for i, extra_value in enumerate(negative_prompt_extra_values):
            extra_node = workflow_info['dynamic_components'].get('GradioTextBad', [])
            if i < len(extra_node):
                node_id = extra_node[i].get('id')
                if node_id and node_id in prompt:
                    prompt[node_id]['inputs']['string'] = extra_value
                    print(f"[{execution_id}] Updated additional negative prompt {node_id} (slot {i+1}).")

    if text_bad_key:
        prompt[text_bad_key]['inputs']['string'] = prompt_text_negative or ''

    if resolution_key:
        try:
            width_val = int(hua_width)
            height_val = int(hua_height)
            prompt[resolution_key]['inputs']['custom_width'] = width_val
            prompt[resolution_key]['inputs']['custom_height'] = height_val
            print(f"[{execution_id}] Set workflow resolution to {width_val}x{height_val}")
        except (ValueError, TypeError) as exc:
            print(f"[{execution_id}] Warning: unable to update resolution values: {exc}")

    if checkpoint_key and hua_checkpoint != 'None':
        prompt[checkpoint_key]['inputs']['ckpt_name'] = hua_checkpoint
    if unet_key and hua_unet != 'None':
        prompt[unet_key]['inputs']['unet_name'] = hua_unet

    actual_lora_nodes = workflow_info['dynamic_components'].get('Hua_LoraLoaderModelOnly', [])
    for i, node_info in enumerate(actual_lora_nodes):
        if i < len(dynamic_loras_values):
            node_id = node_info.get('id')
            selected = dynamic_loras_values[i]
            if node_id in prompt:
                prompt[node_id]['inputs']['lora_name'] = selected if selected != 'None' else node_info.get('value', 'None')

    actual_int_nodes = workflow_info['dynamic_components'].get('HuaIntNode', [])
    for i, node_info in enumerate(actual_int_nodes):
        if i < len(dynamic_int_nodes_values):
            node_id = node_info.get('id')
            value = dynamic_int_nodes_values[i]
            if node_id in prompt and value is not None:
                try:
                    prompt[node_id]['inputs']['int_value'] = int(value)
                except (ValueError, TypeError):
                    pass

    actual_float_nodes = workflow_info['dynamic_components'].get('HuaFloatNode', [])
    for i, node_info in enumerate(actual_float_nodes):
        if i < len(dynamic_float_nodes_values):
            node_id = node_info.get('id')
            value = dynamic_float_nodes_values[i]
            if node_id in prompt and value is not None:
                try:
                    prompt[node_id]['inputs']['float_value'] = float(value)
                except (ValueError, TypeError):
                    pass

    ksampler_settings = _parse_ksampler_settings(workflow_info, dynamic_ksampler_values or [])
    actual_ksampler_nodes = workflow_info['dynamic_components'].get('KSampler', [])
    seed_override = current_seed if seed_mode in {"Random", "Increment", "Decrement", "Fixed"} else None

    for idx, node_info in enumerate(actual_ksampler_nodes):
        if idx < len(ksampler_settings):
            node_id = node_info.get('id')
            if node_id in prompt:
                settings = ksampler_settings[idx]
                node_inputs = prompt[node_id].setdefault('inputs', {})
                node_inputs['steps'] = settings['steps']
                node_inputs['cfg'] = settings['cfg']
                node_inputs['sampler_name'] = settings['sampler_name']
                node_inputs['scheduler'] = settings['scheduler']
                node_inputs['start_at_step'] = settings['start_at_step']
                node_inputs['end_at_step'] = settings['end_at_step']
                node_inputs['add_noise'] = settings['add_noise']
                node_inputs['return_with_leftover_noise'] = settings['return_with_leftover_noise']
                if seed_override is not None:
                    node_inputs[settings['seed_field']] = seed_override
                elif settings['seed_value'] not in (None, ''):
                    node_inputs[settings['seed_field']] = settings['seed_value']

    mask_settings = _parse_mask_settings(dynamic_mask_generator_values or [])
    actual_mask_nodes = workflow_info['dynamic_components'].get('APersonMaskGenerator', [])
    for idx, node_info in enumerate(actual_mask_nodes):
        if idx < len(mask_settings):
            node_id = node_info.get('id')
            if node_id in prompt:
                node_inputs = prompt[node_id].setdefault('inputs', {})
                config = mask_settings[idx]
                node_inputs['face_mask'] = bool(config.get('face_mask', True))
                node_inputs['background_mask'] = bool(config.get('background_mask', False))
                node_inputs['hair_mask'] = bool(config.get('hair_mask', False))
                node_inputs['body_mask'] = bool(config.get('body_mask', False))
                node_inputs['clothes_mask'] = bool(config.get('clothes_mask', False))
                node_inputs['confidence'] = float(config.get('confidence', 0.15))
                node_inputs['refine_mask'] = bool(config.get('refine_mask', False))

    image_loader_nodes = workflow_info['dynamic_components'].get('ImageLoaders', [])
    loader_settings = _parse_image_loader_settings(image_loader_nodes, dynamic_image_loader_values or [])
    for idx, node_info in enumerate(image_loader_nodes):
        node_id = node_info.get('id')
        if node_id in prompt and idx < len(loader_settings):
            node_inputs = prompt[node_id].setdefault('inputs', {})
            config = loader_settings[idx]
            node_inputs['resize'] = bool(config.get('resize', False))
            node_inputs['width'] = config.get('width')
            node_inputs['height'] = config.get('height')
            node_inputs['keep_proportion'] = bool(config.get('keep_proportion', False))
            node_inputs['divisible_by'] = config.get('divisible_by')
    try:
        prompt_id = start_queue(prompt, client_id=queue_client_id)
        if prompt_id is None:
            print(f"[{execution_id}] Failed to send prompt to ComfyUI queue.")
            return None, None

        tracking_id = prompt_id or output_tracking_token

        # Only wait for history completion if we have Hua output nodes (which write their own status)
        # Otherwise, skip straight to filesystem diff to avoid hanging on history API
        status_entry = None
        if image_result_ids or video_result_ids:
            status_entry = _wait_for_prompt_completion(queue_client_id, tracking_id, timeout=300)
        else:
            # Poll the /queue endpoint to wait for our prompt to finish
            deadline = time.time() + 300  # 5 minute timeout
            while time.time() < deadline:
                try:
                    resp = requests.get("http://127.0.0.1:8188/queue", timeout=5)
                    if resp.ok:
                        queue_data = resp.json()
                        # Check if our prompt is still in queue_running or queue_pending
                        # Queue items are lists: [number, prompt_id, {...}, class_type]
                        in_running = any((item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item.get('prompt_id', '')) == prompt_id
                                       for item in queue_data.get('queue_running', []))
                        in_pending = any((item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item.get('prompt_id', '')) == prompt_id
                                       for item in queue_data.get('queue_pending', []))
                        if not in_running and not in_pending:
                            break
                except Exception:
                    pass  # Silently retry on errors
                time.sleep(0.5)
            time.sleep(1)  # Brief delay to let filesystem settle

        if status_entry:
            status_block = status_entry.get("status")
            status_text = ""
            detail_text = ""
            if isinstance(status_block, dict):
                status_text = status_block.get("status") or status_block.get("result") or ""
                detail_text = status_block.get("message") or status_block.get("error") or status_block.get("detail") or ""
            elif isinstance(status_block, str):
                status_text = status_block
            normalized_status = status_text.lower() if status_text else ""
            if normalized_status in {"error", "failed", "failure", "cancelled", "canceled", "stopped"}:
                print(f"[{execution_id}] ComfyUI reported status '{normalized_status}' for prompt {tracking_id}.")
                if detail_text:
                    print(f"[{execution_id}] Detail: {detail_text}")
                return "COMFYUI_REJECTED", None
        else:
            print(f"[{execution_id}] Warning: prompt {tracking_id} did not report completion before timeout; checking for outputs anyway.")

        image_payloads, pending_image_ids = _wait_for_output_json(image_result_ids)
        video_payloads, pending_video_ids = _wait_for_output_json(video_result_ids)

        if pending_image_ids:
            log_message(f"[{execution_id}] Timed out waiting for image outputs from IDs: {', '.join(pending_image_ids.keys())}")
        if pending_video_ids:
            log_message(f"[{execution_id}] Timed out waiting for video outputs from IDs: {', '.join(pending_video_ids.keys())}")

        image_paths, image_errors = _extract_paths_from_output_payload(image_payloads, kind="image")
        video_paths, video_errors = _extract_paths_from_output_payload(video_payloads, kind="video")

        for error_msg in image_errors + video_errors:
            log_message(f"[{execution_id}] Output parsing warning: {error_msg}")

        if video_paths:
            print(f"[{execution_id}] Collected {len(video_paths)} video file(s) from Hua_Video_Output nodes.")
            return "video", video_paths
        if image_paths:
            print(f"[{execution_id}] Collected {len(image_paths)} image file(s) from Hua_Output nodes.")
            return "image", image_paths

        history_image_paths, history_video_paths, history_errors = _extract_paths_from_history_entry(status_entry)
        for error_msg in history_errors:
            log_message(f"[{execution_id}] History output warning: {error_msg}")
        if history_video_paths:
            print(f"[{execution_id}] Collected {len(history_video_paths)} video file(s) from ComfyUI history.")
            return "video", history_video_paths
        if history_image_paths:
            print(f"[{execution_id}] Collected {len(history_image_paths)} image file(s) from ComfyUI history.")
            return "image", history_image_paths

        try:
            post_run_outputs = get_output_images(OUTPUT_DIR)
        except Exception as exc:
            post_run_outputs = []
            log_message(f"[{execution_id}] Warning: failed to enumerate output directory after run: {exc}")

        fresh_outputs = []
        for candidate_path in post_run_outputs:
            try:
                mtime = os.path.getmtime(candidate_path)
            except OSError:
                continue
            previous_mtime = preexisting_outputs.get(candidate_path)
            if previous_mtime is None or mtime > (previous_mtime or 0):
                if mtime >= snapshot_mtime - 0.01:
                    fresh_outputs.append(candidate_path)

        if fresh_outputs:
            log_message(f"[{execution_id}] Falling back to filesystem diff; detected {len(fresh_outputs)} new image(s).")
            for sample_path in fresh_outputs[:3]:
                try:
                    log_message(f"[{execution_id}] New image detected: {sample_path} (mtime={os.path.getmtime(sample_path):.3f})")
                except OSError:
                    log_message(f"[{execution_id}] New image detected: {sample_path}")
            return "image", fresh_outputs

        fallback_paths = []
        if hua_output_key and hua_output_key in prompt:
            filename_prefix = prompt[hua_output_key].get('inputs', {}).get('filename_prefix')
            if isinstance(filename_prefix, list):
                fallback_paths.extend(filename_prefix)
            elif isinstance(filename_prefix, str):
                fallback_paths.append(filename_prefix)
        if fallback_paths:
            log_message(f"[{execution_id}] Falling back to workflow filename_prefix values: {fallback_paths}")
            return "image", fallback_paths

        log_message(f"[{execution_id}] No output files detected for prompt {tracking_id}.")
        return None, None
    except Exception as exc:
        print(f"[{execution_id}] Exception while starting queue: {exc}")
        return None, None


def _split_run_inputs(raw_args):
    args = list(raw_args)
    expected_base = (
        MAX_DYNAMIC_COMPONENTS  # positive prompts
        + 1  # primary negative prompt
        + MAX_DYNAMIC_COMPONENTS  # extra negative prompts
        + 1  # json file
        + 2  # width, height
        + MAX_DYNAMIC_COMPONENTS  # lora dropdowns
        + 2  # checkpoint, unet
        + MAX_DYNAMIC_COMPONENTS  # float inputs
        + MAX_DYNAMIC_COMPONENTS  # int inputs
        + MAX_IMAGE_LOADERS * IMAGE_LOADER_FIELD_COUNT  # image loader controls
        + 2  # seed mode, fixed seed
        + 1  # queue count
    )

    if len(args) < expected_base:
        args.extend([None] * (expected_base - len(args)))

    idx = 0
    positive_prompts = list(args[idx:idx + MAX_DYNAMIC_COMPONENTS]); idx += MAX_DYNAMIC_COMPONENTS
    prompt_negative = args[idx]; idx += 1
    negative_extras = list(args[idx:idx + MAX_DYNAMIC_COMPONENTS]); idx += MAX_DYNAMIC_COMPONENTS
    json_file = args[idx]; idx += 1
    hua_width = args[idx]; idx += 1
    hua_height = args[idx]; idx += 1
    lora_values = list(args[idx:idx + MAX_DYNAMIC_COMPONENTS]); idx += MAX_DYNAMIC_COMPONENTS
    checkpoint = args[idx]; idx += 1
    unet = args[idx]; idx += 1
    float_values = list(args[idx:idx + MAX_DYNAMIC_COMPONENTS]); idx += MAX_DYNAMIC_COMPONENTS
    int_values = list(args[idx:idx + MAX_DYNAMIC_COMPONENTS]); idx += MAX_DYNAMIC_COMPONENTS
    image_loader_values = list(args[idx:idx + (MAX_IMAGE_LOADERS * IMAGE_LOADER_FIELD_COUNT)]); idx += MAX_IMAGE_LOADERS * IMAGE_LOADER_FIELD_COUNT
    seed_mode = args[idx]; idx += 1
    fixed_seed = args[idx]; idx += 1
    queue_count_value = args[idx] if idx < len(args) else None
    idx += 1

    advanced = list(args[idx:])
    expected_ksampler = MAX_KSAMPLER_CONTROLS * 9
    expected_mask = MAX_MASK_GENERATORS * MASK_FIELD_COUNT
    expected_advanced = expected_ksampler + expected_mask
    if len(advanced) < expected_advanced:
        advanced.extend([None] * (expected_advanced - len(advanced)))
    elif len(advanced) > expected_advanced:
        advanced = advanced[:expected_advanced]

    ksampler_flat = advanced[:expected_ksampler]
    mask_flat = advanced[expected_ksampler:]

    return {
        "positive_prompts": positive_prompts,
        "prompt_negative": prompt_negative,
        "negative_extras": negative_extras,
        "json_file": json_file,
        "hua_width": hua_width,
        "hua_height": hua_height,
        "loras": lora_values,
        "checkpoint": checkpoint,
        "unet": unet,
        "floats": float_values,
        "ints": int_values,
        "image_loaders": image_loader_values,
        "seed_mode": seed_mode,
        "fixed_seed": fixed_seed,
        "queue_count": queue_count_value,
        "ksampler_flat": ksampler_flat,
        "mask_flat": mask_flat,
    }

def format_queue_status(queue_size, is_processing, include_progress=False):
    """Helper function to format queue status with optional progress bar."""
    processing_text = "Yes" if is_processing else "No"
    progress_html = ""
    progress_value = None
    progress_max = None

    # Try to get progress info from the previewer
    if include_progress and is_processing and 'comfyui_previewer' in globals():
        try:
            progress_info = comfyui_previewer.get_progress_info()
            progress_value = progress_info.get("value")
            progress_max = progress_info.get("max")

            if progress_value is not None and progress_max is not None and progress_max > 0:
                percentage = int((progress_value / progress_max) * 100)
                processing_text = f"Yes ({progress_value}/{progress_max} - {percentage}%)"

                # Create HTML progress bar
                progress_html = f"""
<div style="width: 100%; background-color: #333; border-radius: 4px; margin-top: 8px; overflow: hidden;">
    <div style="width: {percentage}%; background: linear-gradient(90deg, #ff7c00 0%, #ffaa00 100%); height: 20px; border-radius: 4px; transition: width 0.3s ease;"></div>
</div>"""
        except Exception as e:
            # Silently fall back to simple "Yes" if progress info unavailable
            pass

    status_text = f"In Queue: {queue_size} | Processing: {processing_text}"

    # Combine status text with progress bar HTML if available
    if progress_html:
        return f"{status_text}{progress_html}"
    else:
        return status_text

def run_queued_tasks(inputimage1, input_video, *dynamic_args, queue_count=1, progress=gr.Progress(track_tqdm=True)):
    global accumulated_image_results, last_video_result, executor

    # Helper function to convert update dict to tuple matching outputs order
    # outputs=[queue_status_display, output_gallery, output_video, main_output_tabs_component,
    #          live_preview_image, live_preview_status, selected_gallery_image_state,
    #          photopea_image_data_state, photopea_data_bus, photopea_status]
    def dict_to_tuple(update_dict):
        try:
            result = (
                update_dict.get("status", gr.update()),
                update_dict.get("gallery", gr.update()),
                update_dict.get("video", gr.update()),
                update_dict.get("tabs", gr.update()),
                update_dict.get("preview_img", gr.update()),
                update_dict.get("preview_status", gr.update()),
                update_dict.get("selected_state", None),
                update_dict.get("photopea_state", None),
                update_dict.get("photopea_bus", gr.update()),
                update_dict.get("photopea_status", gr.update())
            )
            return result
        except Exception as e:
            log_message(f"[ERROR] dict_to_tuple failed: {e}")
            return (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), None, None, gr.update(), gr.update())

    unpacked_inputs = _split_run_inputs(dynamic_args)
    dynamic_positive_prompts_values = unpacked_inputs["positive_prompts"]
    prompt_text_negative = unpacked_inputs["prompt_negative"] or ""
    negative_prompt_extras = unpacked_inputs["negative_extras"]
    json_file = unpacked_inputs["json_file"]
    hua_width = unpacked_inputs["hua_width"]
    hua_height = unpacked_inputs["hua_height"]
    dynamic_loras_values = unpacked_inputs["loras"]
    hua_checkpoint = unpacked_inputs["checkpoint"]
    hua_unet = unpacked_inputs["unet"]
    dynamic_float_nodes_values = unpacked_inputs["floats"]
    dynamic_int_nodes_values = unpacked_inputs["ints"]
    dynamic_image_loader_values = unpacked_inputs["image_loaders"]
    seed_mode = (unpacked_inputs["seed_mode"] or "Random").strip()
    fixed_seed = unpacked_inputs["fixed_seed"]
    queue_count_value = unpacked_inputs["queue_count"]
    if queue_count_value is None:
        queue_count_value = queue_count
    try:
        queue_count_value = int(queue_count_value)
    except (TypeError, ValueError):
        queue_count_value = 1
    queue_count_value = max(1, queue_count_value)

    dynamic_ksampler_values = unpacked_inputs["ksampler_flat"]
    dynamic_mask_generator_values = unpacked_inputs["mask_flat"]

    current_batch_image_results = []

    if queue_count_value > 1:
        with results_lock:
            accumulated_image_results = []
            current_batch_image_results = []
            last_video_result = None
    else:
        with results_lock:
            last_video_result = None

    task_params_tuple = (
        inputimage1,
        input_video,
        dynamic_positive_prompts_values,
        prompt_text_negative,
        json_file,
        hua_width,
        hua_height,
        dynamic_loras_values,
        hua_checkpoint,
        hua_unet,
        dynamic_float_nodes_values,
        dynamic_int_nodes_values,
        dynamic_ksampler_values,
        dynamic_mask_generator_values,
        dynamic_image_loader_values,
        seed_mode,
        fixed_seed,
        negative_prompt_extras,
    )

    log_message(f"[QUEUE] Adding {queue_count_value} job(s) to queue.")
    with queue_lock:
        for _ in range(queue_count_value):
            task_queue.append(task_params_tuple)
        current_queue_size = len(task_queue)
    log_message(f"[QUEUE] Queue size after enqueue: {current_queue_size}")

    # Prepare initial updates as tuple matching outputs order:
    # outputs=[queue_status_display, output_gallery, output_video, main_output_tabs_component,
    #          live_preview_image, live_preview_status, selected_gallery_image_state,
    #          photopea_image_data_state, photopea_data_bus, photopea_status]
    with results_lock:
        initial_gallery = accumulated_image_results[:]
        initial_video = last_video_result

    yield (
        gr.update(value=format_queue_status(current_queue_size, processing_event.is_set(), include_progress=False)),  # queue_status_display
        gr.update(value=initial_gallery),  # output_gallery
        gr.update(value=initial_video),  # output_video
        gr.Tabs(selected="tab_generate_result"),  # main_output_tabs_component
        gr.update(),  # live_preview_image (no change)
        gr.update(),  # live_preview_status (no change)
        None,  # selected_gallery_image_state (no change)
        None,  # photopea_image_data_state (no change)
        gr.update(),  # photopea_data_bus (no change)
        gr.update()  # photopea_status (no change)
    )

    # Check if worker is already active - if so, skip starting a new one
    # but still go through the finally block to yield final status
    should_process_queue = not processing_event.is_set()

    if not should_process_queue:
        log_message("[QUEUE] Worker already active. Tasks added to queue but will be processed by existing worker.")
        # Don't start a new worker, but still go through finally block
    else:
        processing_event.set()
        log_message("[QUEUE] Worker started.")

    def process_task(task_params):
        try:
            return generate_image(*task_params)
        except Exception as exc:
            log_message(f"[QUEUE] Exception while executing task: {exc}")
            return None, None

    try:
        # Only process queue if we're the active worker
        while should_process_queue:
            with queue_lock:
                if task_queue:
                    task_to_run = task_queue.popleft()
                    current_queue_size = len(task_queue)
                else:
                    break
            log_message(f"[QUEUE] Dequeued task. Remaining queue size: {current_queue_size}")

            with results_lock:
                current_images_copy = accumulated_image_results[:]
                current_video = last_video_result

            log_message(f"[QUEUE] About to yield status update")
            try:
                yield dict_to_tuple({
                    "status": gr.update(value=format_queue_status(current_queue_size, True, include_progress=False)),
                    "gallery": gr.update(value=current_images_copy),
                    "video": gr.update(value=current_video),
                })
                log_message(f"[QUEUE] Yielded successfully")
            except Exception as e:
                log_message(f"[ERROR] Yield failed: {e}")
                raise

            current_task_json_file = task_to_run[4]
            should_switch_to_preview = False
            if isinstance(current_task_json_file, str):
                workflow_dir_for_check, workflow_name_for_check, json_path_for_check = resolve_workflow_components(current_task_json_file)
                if json_path_for_check and os.path.exists(json_path_for_check):
                    try:
                        prompt_for_preview = load_prompt_from_file(json_path_for_check)
                        if isinstance(prompt_for_preview, dict):
                            for node_data in prompt_for_preview.values():
                                if not isinstance(node_data, dict):
                                    continue
                                class_type = node_data.get("class_type")
                                if class_type in {"KSampler", "KSamplerAdvanced", "KSamplerSelect"}:
                                    should_switch_to_preview = True
                                    break
                    except Exception as exc:
                        log_message(f"[QUEUE] Failed to inspect workflow for preview switch: {exc}")
            if should_switch_to_preview:
                yield dict_to_tuple({"tabs": gr.Tabs(selected="tab_k_sampler_preview")})

            log_message(f"[QUEUE] About to submit task to executor")
            try:
                progress(0, desc=f"Processing task (queue remaining {current_queue_size})")
            except Exception as e:
                log_message(f"[QUEUE] Progress call failed (non-fatal): {e}")

            future = executor.submit(process_task, task_to_run)
            log_message(f"[QUEUE] Task submitted, waiting for completion")

            task_interrupted = False
            while not future.done():
                if interrupt_requested_event.is_set():
                    log_message("[QUEUE] Interrupt requested by user.")
                    task_interrupted = True
                    break
                time.sleep(0.1)
                with results_lock:
                    current_images_copy = accumulated_image_results[:]
                    current_video = last_video_result
                yield dict_to_tuple({
                    "status": gr.update(value=format_queue_status(current_queue_size, True, include_progress=True)),
                    "gallery": gr.update(value=current_images_copy),
                    "video": gr.update(value=current_video),
                })

            if task_interrupted:
                interrupt_requested_event.clear()
                try:
                    executor.shutdown(wait=False)
                except Exception as exc:
                    log_message(f"[QUEUE] Failed to shutdown executor after interrupt: {exc}")
                executor = ThreadPoolExecutor(max_workers=1)
                yield dict_to_tuple({"status": gr.update(value=f"In Queue: {current_queue_size} | Processing: Interrupted")})
                progress(0, desc="Interrupted task")
                continue

            try:
                output_type, new_paths = future.result()
                log_message(f"[QUEUE] Task completed. Output type: {output_type}, Paths count: {len(new_paths) if new_paths else 0}")
            except Exception as exc:
                log_message(f"[QUEUE] Future raised exception: {exc}")
                output_type, new_paths = None, None

            if output_type == "COMFYUI_REJECTED":
                yield dict_to_tuple({
                    "status": gr.update(value=f"In Queue: {current_queue_size} | Processing: Rejected"),
                    "gallery": gr.update(value=accumulated_image_results[:]),
                    "video": gr.update(value=last_video_result),
                })
                continue

            # Log if no output was received
            if not output_type or not new_paths:
                log_message(f"[QUEUE] Warning: Task completed but no valid output received (type={output_type}, paths={new_paths})")

            if output_type in {"image", "video"} and new_paths:
                update_dict = {}
                with results_lock:
                    if output_type == "image":
                        if queue_count_value == 1:
                            accumulated_image_results = _format_gallery_items(new_paths)
                        else:
                            current_batch_image_results.extend(new_paths)
                            accumulated_image_results = _format_gallery_items(current_batch_image_results[:])
                        last_video_result = None
                        update_dict["gallery"] = gr.update(value=accumulated_image_results[:], visible=True)
                        update_dict["video"] = gr.update(value=None, visible=False)

                        latest_display_path = accumulated_image_results[-1] if accumulated_image_results else None
                        latest_display_path = _ensure_absolute_path(latest_display_path)
                        if latest_display_path and os.path.exists(latest_display_path):
                            final_preview = _load_image_from_path(latest_display_path, f"final-{os.path.basename(latest_display_path)}")
                            if final_preview is not None:
                                update_dict["preview_img"] = gr.update(value=final_preview)
                                update_dict["preview_status"] = gr.update(value=f"Final image ready • {os.path.basename(latest_display_path)}")
                                encoded_preview = _encode_pil_to_data_url(final_preview)
                                update_dict["selected_state"] = latest_display_path
                                update_dict["photopea_state"] = encoded_preview
                                update_dict["photopea_bus"] = gr.update(value=encoded_preview or "")
                                update_dict["photopea_status"] = gr.update(value="Latest result synced. Open Photopea to edit.")
                    else:
                        last_video_result = _ensure_absolute_path(new_paths[0])
                        accumulated_image_results = []
                        update_dict["gallery"] = gr.update(value=[], visible=False)
                        update_dict["video"] = gr.update(value=last_video_result, visible=True)
                update_dict["status"] = gr.update(value=f"In Queue: {current_queue_size} | Processing: Completed")
                log_message(f"[QUEUE] About to yield completion update with {len(update_dict)} keys")
                yield dict_to_tuple(update_dict)
            else:
                with results_lock:
                    current_images_copy = accumulated_image_results[:]
                    current_video = last_video_result
                yield dict_to_tuple({
                    "status": gr.update(value=f"In Queue: {current_queue_size} | Processing: Failed"),
                    "gallery": gr.update(value=current_images_copy),
                    "video": gr.update(value=current_video),
                })

    finally:
        # Only clear processing_event if we were the active worker
        if should_process_queue:
            processing_event.clear()
            log_message("[QUEUE] Worker finished, processing_event cleared.")
        else:
            log_message("[QUEUE] Passive monitor finished (worker still active elsewhere).")

        with queue_lock:
            current_queue_size = len(task_queue)
        with results_lock:
            final_images = accumulated_image_results[:]
            final_video = last_video_result
        log_message(f"[QUEUE] Finally block - yielding final status")
        try:
            yield dict_to_tuple({
                "status": gr.update(value=format_queue_status(current_queue_size, processing_event.is_set(), include_progress=False)),
                "gallery": gr.update(value=final_images),
                "video": gr.update(value=final_video),
                "tabs": gr.Tabs(selected="tab_generate_result"),
            })
        except Exception as e:
            log_message(f"[ERROR] Finally block yield failed (client may have disconnected): {e}")

def clear_queue():
    global task_queue, queue_lock, interrupt_requested_event, processing_event
    
    action_log_messages = []  # accumulate messages for gr.Info()

    with queue_lock:
        is_currently_processing_a_task_in_comfyui = processing_event.is_set()
        num_tasks_waiting_in_gradio_queue = len(task_queue)

        log_message(f"[CLEAR_QUEUE] Entry. Gradio pending queue size: {num_tasks_waiting_in_gradio_queue}, ComfyUI processing active: {is_currently_processing_a_task_in_comfyui}")

        if is_currently_processing_a_task_in_comfyui and num_tasks_waiting_in_gradio_queue == 0:
            # Case 1: ComfyUI is actively processing a task while the Gradio queue is empty. Interrupt the running task.
            log_message("[CLEAR_QUEUE] Action: Interrupting the single, currently running ComfyUI task.")
            
            # Send HTTP interrupt request to ComfyUI
            interrupt_comfyui_status_message = trigger_comfyui_interrupt() 
            action_log_messages.append(f"Attempted to interrupt the active ComfyUI task: {interrupt_comfyui_status_message}")
            log_message(f"[CLEAR_QUEUE] ComfyUI interrupt triggered via HTTP: {interrupt_comfyui_status_message}")

            # Set the internal interrupt flag.
            # run_queued_tasks loop will handle the future accordingly.
            interrupt_requested_event.set()
            log_message("[CLEAR_QUEUE] Gradio internal interrupt_requested_event was SET.")
            
            # task_queue should be empty in this scenario.
            
        elif num_tasks_waiting_in_gradio_queue > 0:
            # Case 2: pending tasks exist in the Gradio queue. Clear them without interrupting the running task.
            cleared_count = num_tasks_waiting_in_gradio_queue
            task_queue.clear()  # clear pending queue entries
            log_message(f"[CLEAR_QUEUE] Action: Cleared {cleared_count} task(s) from Gradio's queue. Any ComfyUI task currently processing was NOT interrupted by this action.")
            action_log_messages.append(f"Cleared {cleared_count} pending task(s) from the Gradio queue.")
            
            # If an interrupt flag was previously set and we did not interrupt this time, clearing it is safe.
            if interrupt_requested_event.is_set():
                interrupt_requested_event.clear()
                log_message("[CLEAR_QUEUE] Cleared a pre-existing interrupt_requested_event because we are only clearing the Gradio queue this time.")
        else:
            # Case 3: no tasks running and queue already empty.
            log_message("[CLEAR_QUEUE] Action: No tasks currently processing in ComfyUI and Gradio queue is empty. Nothing to clear or interrupt.")
            action_log_messages.append("Queue already empty; nothing to clear.")

    # Show operation summary to the user
    if action_log_messages:
        gr.Info(" ".join(action_log_messages))

    # Update queue status in the UI
    with queue_lock:  # grab latest queue size (should be 0 if cleared)
        current_gradio_queue_size_for_display = len(task_queue) 
    
    # processing_event state is managed inside run_queued_tasks.
    # If we interrupted a task here, the finally block in run_queued_tasks will clear it.
    # If we only cleared the waiting queue, processing_event stays set until the running task finishes or is interrupted.
    current_processing_status_for_display = processing_event.is_set()
    
    log_message(f"[CLEAR_QUEUE] Exit. Gradio queue size for display: {current_gradio_queue_size_for_display}, ComfyUI processing status for display: {current_processing_status_for_display}")

    return gr.update(value=format_queue_status(current_gradio_queue_size_for_display, current_processing_status_for_display, include_progress=False))

def clear_history():
    global accumulated_image_results, last_video_result
    with results_lock:
        accumulated_image_results.clear()
        last_video_result = None
    log_message("Cleared cached image and video history.")
    with queue_lock: current_queue_size = len(task_queue)
    return {
        output_gallery: gr.update(value=[]),  # clear but keep visible
        output_video: gr.update(value=None),  # clear but keep visible
        queue_status_display: gr.update(value=format_queue_status(current_queue_size, processing_event.is_set(), include_progress=False))
    }


# --- Gradio UI ---

# Combine imported HACKER_CSS with monitor CSS
combined_css = "\n".join([HACKER_CSS, monitor_css, UI_THEME_CSS])

with gr.Blocks(css=combined_css) as demo:
    selected_gallery_image_state = gr.State(value=None)
    photopea_image_data_state = gr.State(value=None)
    theme_bootstrap = gr.HTML(THEME_BOOTSTRAP_HTML, visible=False)

    with gr.Tabs(elem_id="hua-main-tabs"):
        with gr.TabItem("ComfyUI Workflow Wrapper", id="tab_workflow_main"):
            with gr.Row(equal_height=False, elem_classes=["hua-main-row"]):
                with gr.Column(scale=6, min_width=720, elem_classes=["hua-pane", "hua-pane-left"]):
                    with gr.Accordion("Upload Image", open=True, visible=True) as image_accordion:
                        base_image_kwargs = {
                            "label": "Upload / Inpaint Image",
                            "height": 512,
                            "width": "100%",
                            "elem_id": "hua-image-input",
                        }
                        if GRADIO_HAS_IMAGE_EDITOR:
                            image_editor_kwargs = dict(base_image_kwargs)
                            image_editor_kwargs.update({
                                "image_mode": "RGBA",
                                "sources": ["upload", "clipboard"],
                                "type": "pil",
                                "layers": True,
                                "transforms": (),
                                "canvas_size": None,
                                "brush": gr.Brush(default_size=56, color_mode="fixed", colors=["#ffffffff"], default_color="#ffffffff"),
                                "eraser": gr.Eraser(default_size=48),
                            })
                            input_image = gr.ImageEditor(**image_editor_kwargs)
                        elif GRADIO_IMAGE_SUPPORTS_TOOL:
                            image_kwargs = dict(base_image_kwargs)
                            if GRADIO_IMAGE_SUPPORTS_TYPE:
                                image_kwargs["type"] = "pil"
                            if GRADIO_IMAGE_SUPPORTS_IMAGE_MODE:
                                image_kwargs["image_mode"] = "RGBA"
                            image_kwargs["tool"] = "sketch"
                            if GRADIO_IMAGE_SUPPORTS_BRUSH:
                                image_kwargs["brush_radius"] = 40
                            if GRADIO_IMAGE_SUPPORTS_SOURCES:
                                image_kwargs["sources"] = ["upload", "clipboard"]
                            input_image = gr.Image(**image_kwargs)
                        else:
                            fallback_kwargs = dict(base_image_kwargs)
                            if GRADIO_IMAGE_SUPPORTS_TYPE:
                                fallback_kwargs["type"] = "pil"
                            if GRADIO_IMAGE_SUPPORTS_IMAGE_MODE:
                                fallback_kwargs["image_mode"] = "RGBA"
                            if GRADIO_IMAGE_SUPPORTS_SOURCES:
                                fallback_kwargs["sources"] = ["upload", "clipboard"]
                            input_image = gr.Image(**fallback_kwargs)
                        upload_to_photopea_button = gr.Button("🎨 Send to Photopea", variant="secondary", size="sm")
                        upload_photopea_js_trigger = gr.HTML("", visible=False)

                    with gr.Accordion("Upload Video", open=False, visible=False) as video_accordion:
                        video_kwargs = {
                            "label": "Upload Video",
                            "height": 360,
                            "width": "100%",
                        }
                        if GRADIO_VIDEO_SUPPORTS_SOURCES:
                            video_kwargs["sources"] = ["upload"]
                        input_video = gr.Video(**video_kwargs)

                    for i in range(MAX_IMAGE_LOADERS):
                        with gr.Accordion(f"Image Loader Settings {i+1}", open=False, visible=False) as loader_section:
                            resize_checkbox = gr.Checkbox(label="Resize", value=False, visible=False)
                            with gr.Row():
                                width_number = gr.Number(label="Width", minimum=1, step=1, visible=False)
                                height_number = gr.Number(label="Height", minimum=1, step=1, visible=False)
                            keep_proportion_checkbox = gr.Checkbox(label="Keep Proportion", value=False, visible=False)
                            divisible_number = gr.Number(label="Divisible By", minimum=1, step=1, visible=False)
                        IMAGE_LOADER_ACCORDION_COMPONENTS.append(loader_section)
                        IMAGE_LOADER_COMPONENTS_FLAT.extend([
                            resize_checkbox,
                            width_number,
                            height_number,
                            keep_proportion_checkbox,
                            divisible_number,
                        ])

                    initial_json_choices = get_json_files()
                    initial_json_value = initial_json_choices[0] if initial_json_choices else None

                    with gr.Row():
                        with gr.Column(scale=4, min_width=420):
                            json_dropdown = gr.Dropdown(choices=initial_json_choices, value=initial_json_value, label="Select Workflow")
                        with gr.Column(scale=2, min_width=220):
                            refresh_button = gr.Button("Refresh Workflows")
                            refresh_model_button = gr.Button("Refresh Models")

                    with gr.Row():
                        with gr.Column(scale=2):
                            with gr.Accordion("Positive Prompts", open=True):
                                positive_prompt_texts = []
                                for i in range(MAX_DYNAMIC_COMPONENTS):
                                    positive_prompt_texts.append(
                                        gr.Textbox(label=f"Prompt {i+1}", visible=False, elem_id=f"dynamic_positive_prompt_{i+1}")
                                    )
                        with gr.Column(scale=2):
                            with gr.Accordion("Negative Prompts", open=False) as negative_prompt_accordion:
                                prompt_negative = gr.Textbox(label="Primary Negative Prompt", elem_id="prompt_negative")
                                negative_prompt_extras = []
                                for i in range(MAX_DYNAMIC_COMPONENTS):
                                    extra = gr.Textbox(
                                        label=f"Negative Prompt Extra {i+1}",
                                        visible=False,
                                        elem_id=f"dynamic_negative_prompt_{i+1}"
                                    )
                                    negative_prompt_extras.append(extra)
                                    NEGATIVE_PROMPT_COMPONENTS.append(extra)

                    with gr.Row() as resolution_row:
                        with gr.Column(scale=2, min_width=280):
                            resolution_dropdown = gr.Dropdown(choices=resolution_presets, label="Resolution Preset", value=resolution_presets[0])
                        with gr.Column(scale=2, min_width=280):
                            with gr.Accordion("Width and Height", open=False):
                                with gr.Column():
                                    hua_width = gr.Number(label="Width", value=512, minimum=64, step=64, elem_id="hua_width_input")
                                    hua_height = gr.Number(label="Height", value=512, minimum=64, step=64, elem_id="hua_height_input")
                                    ratio_display = gr.Markdown("Current ratio: 1:1")
                            flip_btn = gr.Button("Swap Width/Height")

                    with gr.Row():
                        queue_status_display = gr.Markdown("In Queue: 0 | Processing: No")

                    with gr.Row():
                        run_button = gr.Button("Generate (enqueue)", variant="primary", elem_id="align-center")
                        clear_queue_button = gr.Button("Clear Queue", elem_id="align-center")
                        clear_history_button = gr.Button("Clear History")
                        sponsor_button = gr.Button("Sponsor Author")
                        queue_count = gr.Number(label="Queue Count", value=1, minimum=1, step=1, precision=0)
                    sponsor_display = gr.Markdown(visible=False)

                    with gr.Row():
                        with gr.Column(scale=1, visible=False) as seed_options_col:
                            seed_mode_dropdown = gr.Dropdown(
                                choices=["Random", "Increment", "Decrement", "Fixed"],
                                value="Random",
                                label="Seed Mode",
                                elem_id="seed_mode_dropdown"
                            )
                            fixed_seed_input = gr.Number(
                                label="Fixed Seed Value",
                                value=0,
                                minimum=0,
                                maximum=0xffffffff,
                                step=1,
                                precision=0,
                                visible=False,
                                elem_id="fixed_seed_input"
                            )

                    with gr.Row():
                        with gr.Column(scale=1):
                            hua_unet_dropdown = gr.Dropdown(
                                choices=unet_list,
                                label="Select UNet Model",
                                value="None",
                                elem_id="hua_unet_dropdown",
                                visible=False,
                            )
                        with gr.Column(scale=1):
                            lora_dropdowns = []
                            for i in range(MAX_DYNAMIC_COMPONENTS):
                                lora_dropdowns.append(
                                    gr.Dropdown(
                                        choices=lora_list,
                                        label=f"Lora {i+1}",
                                        value="None",
                                        visible=False,
                                        elem_id=f"dynamic_lora_dropdown_{i+1}"
                                    )
                                )
                        with gr.Column(scale=1):
                            hua_checkpoint_dropdown = gr.Dropdown(
                                choices=checkpoint_list,
                                label="Select Checkpoint",
                                value="None",
                                elem_id="hua_checkpoint_dropdown",
                                visible=False,
                            )

                    with gr.Row() as float_int_row:
                        with gr.Column(scale=1):
                            float_inputs = []
                            for i in range(MAX_DYNAMIC_COMPONENTS):
                                float_inputs.append(
                                    gr.Number(
                                        label=f"Float Input {i+1}",
                                        visible=False,
                                        elem_id=f"dynamic_float_input_{i+1}"
                                    )
                                )
                        with gr.Column(scale=1):
                            int_inputs = []
                            for i in range(MAX_DYNAMIC_COMPONENTS):
                                int_inputs.append(
                                    gr.Number(
                                        label=f"Int Input {i+1}",
                                        visible=False,
                                        elem_id=f"dynamic_int_input_{i+1}"
                                    )
                                )

                    with gr.Accordion("Sampler Settings", open=False) as ksampler_settings_parent:
                        for i in range(MAX_KSAMPLER_CONTROLS):
                            with gr.Accordion(f"KSampler {i+1}", open=False, visible=False) as ks_section:
                                ks_steps = gr.Slider(label="Steps", minimum=1, maximum=150, step=1, value=20, visible=True)
                                ks_cfg = gr.Slider(label="CFG", minimum=0.0, maximum=30.0, step=0.1, value=7.0, visible=True)
                                ks_sampler = gr.Dropdown(choices=SAMPLER_NAME_CHOICES, allow_custom_value=True, label="Sampler", value="euler", visible=True)
                                ks_scheduler = gr.Dropdown(choices=SCHEDULER_CHOICES, allow_custom_value=True, label="Scheduler", value="simple", visible=True)
                                with gr.Row():
                                    ks_start = gr.Slider(label="Start Step", minimum=0, maximum=10000, step=1, value=0, visible=True)
                                    ks_end = gr.Slider(label="End Step", minimum=0, maximum=10000, step=1, value=0, visible=True)
                                ks_add_noise = gr.Dropdown(choices=BOOL_CHOICE, label="Add Noise", value="enable", visible=True)
                                ks_return_leftover = gr.Dropdown(choices=BOOL_CHOICE, label="Return With Leftover Noise", value="disable", visible=True)
                                ks_noise_seed = gr.Textbox(label="Noise Seed", value="", placeholder="Leave blank for random", visible=True)
                            KSAMPLER_COMPONENT_GROUPS.append({
                                "accordion": ks_section,
                                "steps": ks_steps,
                                "cfg": ks_cfg,
                                "sampler": ks_sampler,
                                "scheduler": ks_scheduler,
                                "start": ks_start,
                                "end": ks_end,
                                "add_noise": ks_add_noise,
                                "return_leftover": ks_return_leftover,
                                "noise_seed": ks_noise_seed,
                            })
                            KSAMPLER_ACCORDION_COMPONENTS.append(ks_section)
                            KSAMPLER_COMPONENTS_FLAT.extend([
                                ks_steps,
                                ks_cfg,
                                ks_sampler,
                                ks_scheduler,
                                ks_start,
                                ks_end,
                                ks_add_noise,
                                ks_return_leftover,
                                ks_noise_seed,
                            ])

                    with gr.Accordion("Mask & Detection Settings", open=False) as mask_settings_parent:
                        for i in range(MAX_MASK_GENERATORS):
                            with gr.Accordion(f"Mask Generator {i+1}", open=False, visible=False) as mask_section:
                                mask_face = gr.Checkbox(label="Face Mask", value=True, visible=True)
                                mask_background = gr.Checkbox(label="Background Mask", value=False, visible=True)
                                mask_hair = gr.Checkbox(label="Hair Mask", value=False, visible=True)
                                mask_body = gr.Checkbox(label="Body Mask", value=False, visible=True)
                                mask_clothes = gr.Checkbox(label="Clothes Mask", value=False, visible=True)
                                mask_confidence = gr.Slider(label="Confidence", minimum=0.0, maximum=1.0, step=0.01, value=0.15, visible=True)
                                mask_refine = gr.Checkbox(label="Refine Mask", value=False, visible=True)
                            MASK_COMPONENT_GROUPS.append({
                                "accordion": mask_section,
                                "face_mask": mask_face,
                                "background_mask": mask_background,
                                "hair_mask": mask_hair,
                                "body_mask": mask_body,
                                "clothes_mask": mask_clothes,
                                "confidence": mask_confidence,
                                "refine_mask": mask_refine,
                            })
                            MASK_ACCORDION_COMPONENTS.append(mask_section)
                            MASK_COMPONENTS_FLAT.extend([
                                mask_face,
                                mask_background,
                                mask_hair,
                                mask_body,
                                mask_clothes,
                                mask_confidence,
                                mask_refine,
                            ])
                    mask_generator_notice = gr.Markdown(MASK_GENERATOR_NOTICE_TEXT, visible=False)

                with gr.Column(scale=5, min_width=640, elem_classes=["hua-pane", "hua-pane-right"]):
                    with gr.Tabs(elem_id="main_output_tabs") as main_output_tabs_component:
                        with gr.Tab("Results & Preview", id="tab_generate_result"):
                            with gr.Row():
                                with gr.Column(scale=2):
                                    output_gallery = gr.Gallery(
                                        label="Image Results",
                                        columns=3,
                                        height=720,
                                        preview=True,
                                        object_fit="contain",
                                        visible=False
                                    )
                                    with gr.Row():
                                        send_to_upload_button = gr.Button("📤 Send to Upload", size="sm", variant="secondary")
                                        send_to_photopea_button = gr.Button("🎨 Send to Photopea", size="sm", variant="secondary")
                                    photopea_js_trigger = gr.HTML("", visible=False)
                                    video_output_kwargs = {
                                        "label": "Video Results",
                                        "height": 720,
                                        "autoplay": True,
                                        "visible": False,
                                    }
                                    if GRADIO_VIDEO_SUPPORTS_LOOP:
                                        video_output_kwargs["loop"] = True
                                    output_video = gr.Video(**video_output_kwargs)
                                with gr.Column(scale=1):
                                    live_preview_image = gr.Image(
                                        label="Live Preview",
                                        type="pil",
                                        interactive=False,
                                        height=560,
                                        show_label=True
                                    )
                                    live_preview_status = gr.Textbox(
                                        label="Preview Status",
                                        interactive=False,
                                        lines=2
                                    )
                        with gr.Tab("Preview All Outputs", id="tab_all_outputs_preview"):
                            output_preview_gallery = gr.Gallery(
                                label="Output Images Preview",
                                columns=4,
                                height=640,
                                preview=True,
                                object_fit="contain"
                            )
                            load_output_button = gr.Button("Load Output Images")
        with gr.TabItem("Photopea Editor", id="tab_photopea_editor"):
            with gr.Column():
                gr.Markdown("### Photopea Editor")
                photopea_status = gr.Markdown("Load or select an image, then send it to Photopea for detailed edits.", elem_id="photopea-status")
                with gr.Row():
                    load_photopea_button = gr.Button("Send to Photopea", variant="secondary", elem_id="hua-photopea-send")
                    photopea_fetch_button = gr.Button("Import from Photopea", variant="secondary", elem_id="hua-photopea-fetch")
                photopea_html_panel = gr.HTML(PHOTOPEA_EMBED_HTML, elem_id="photopea-embed", elem_classes=["hua-photopea-html"])
                photopea_data_bus = gr.Textbox(value="", visible=False, interactive=False, elem_id="hua-photopea-data-store")
                photopea_import_box = gr.Textbox(visible=False, elem_id="photopea-import-data")
        with gr.TabItem("Settings", id="tab_settings"):
            with gr.Column():
                with gr.Accordion("Live Logs (ComfyUI)", open=False, elem_classes="log-display-container"):
                    with gr.Group(elem_id="log_area_relative_wrapper"):
                        log_display = gr.Textbox(
                            label="Logs",
                            lines=20,
                            max_lines=20,
                            autoscroll=True,
                            interactive=False,
                            show_copy_button=True,
                            elem_classes="log-display-container"
                        )
                        floating_monitor_html_output = gr.HTML(elem_classes="floating-monitor-outer-wrapper")

                gr.Markdown("## ComfyUI Control")
                gr.Markdown("Restart ComfyUI or interrupt the queue worker.")
                with gr.Row():
                    reboot_button = gr.Button("Reboot ComfyUI")
                reboot_output = gr.Textbox(label="Reboot Result", interactive=False)
                reboot_button.click(fn=reboot_manager, inputs=[], outputs=[reboot_output])

                gr.Markdown("## Plugin Core Settings")
                gr.Markdown("---")
                gr.Markdown("### Dynamic Component Count")
                gr.Markdown("Set the maximum number of dynamically generated components. Restart required to take effect.")
                initial_max_comp_for_ui = load_plugin_settings().get("max_dynamic_components", DEFAULT_MAX_DYNAMIC_COMPONENTS)
                max_dynamic_components_input = gr.Number(label="Max dynamic components (1-20)", value=initial_max_comp_for_ui, minimum=1, maximum=20, step=1, precision=0, elem_id="max_dynamic_components_setting_input")
                save_max_components_button = gr.Button("Save dynamic component count")
                max_components_save_status = gr.Markdown("", elem_id="max_components_save_status_md")
                def handle_save_max_components(new_max_value_from_input):
                    try:
                        new_max_value = int(float(new_max_value_from_input))
                        if not (1 <= new_max_value <= 20):
                            return gr.update(value="<p style='color:red;'>Error: value must be between 1 and 20.</p>")
                    except ValueError:
                        return gr.update(value="<p style='color:red;'>Error: please enter a valid integer.</p>")
                    current_settings = load_plugin_settings()
                    current_settings["max_dynamic_components"] = new_max_value
                    status_message = save_plugin_settings(current_settings)
                    return gr.update(value=f"<p style='color:green;'>{status_message} Please restart the plugin or ComfyUI for changes to take effect.</p>")
                save_max_components_button.click(fn=handle_save_max_components, inputs=[max_dynamic_components_input], outputs=[max_components_save_status])
                gr.Markdown("---")
                gr.Markdown("### Appearance")
                gr.Markdown("Choose the interface theme. System mode follows your OS preference.")
                theme_choices = [THEME_MODE_LABELS[key] for key in ("system", "light", "dark")]
                theme_selector = gr.Radio(choices=theme_choices, value=CURRENT_THEME_LABEL, label="Color theme")
                theme_status = gr.Markdown(visible=False)
                theme_apply_html = gr.HTML("", visible=False, elem_id="hua-theme-sync")
                def handle_theme_change(selected_label):
                    canonical = THEME_LABEL_TO_VALUE.get(selected_label, "system")
                    current_settings = load_plugin_settings()
                    current_settings["theme_mode"] = canonical
                    status_message = save_plugin_settings(current_settings)
                    script = f"<script>window.huaApplyTheme && window.huaApplyTheme('{canonical}');</script>"
                    return (
                        gr.update(value=f"Theme preference set to **{selected_label}**. {status_message}", visible=True),
                        gr.update(value=script)
                    )
                theme_selector.change(
                    fn=handle_theme_change,
                    inputs=[theme_selector],
                    outputs=[theme_status, theme_apply_html]
                )
                gr.Markdown("---")
        with gr.TabItem("Civitai Browser", id="tab_civitai_browser"):
            with gr.Column():
                gr.Markdown("### Browse & Download Models from Civitai")
                stored_civitai_key = plugin_settings_on_load.get("civitai_api_key", "") if isinstance(plugin_settings_on_load, dict) else ""
                with gr.Row():
                    civitai_api_key_input = gr.Textbox(label="Civitai API Key (optional)", value=stored_civitai_key, type="password", placeholder="Paste API key or leave blank.")
                    civitai_save_key_button = gr.Button("Save Key", variant="secondary")
                civitai_key_status = gr.Markdown(visible=False)
                with gr.Row():
                    civitai_query = gr.Textbox(label="Search", placeholder="Model name, tag, etc.")
                    civitai_type = gr.Dropdown(label="Model Type", choices=["", "Checkpoint", "LORA", "LoCon", "TextualInversion", "VAE", "Controlnet"], value="")
                    civitai_sort = gr.Dropdown(label="Sort By", choices=list(CIVITAI_SORT_MAP.keys()), value="Highest Rated")
                with gr.Row():
                    civitai_page = gr.Number(value=1, minimum=1, step=1, label="Page", precision=0)
                    civitai_per_page = gr.Number(value=20, minimum=1, maximum=50, step=1, label="Results / Page", precision=0)
                    civitai_nsfw = gr.Dropdown(label="NSFW", choices=["Hide", "Show", "Only"], value="Hide")
                    civitai_search_button = gr.Button("Search", variant="primary")
                civitai_results_state = gr.State(value=[])
                civitai_selected_model_state = gr.State(value=None)
                civitai_selected_file_state = gr.State(value=None)
                civitai_search_status = gr.Markdown(visible=False)
                civitai_results_dropdown = gr.Dropdown(label="Results", choices=[], value=None)
                civitai_model_details = gr.Markdown(visible=False)
                civitai_preview_gallery = gr.Gallery(label="Preview Images", visible=False, height=300)
                civitai_version_dropdown = gr.Dropdown(label="Versions", choices=[], value=None, visible=False)
                civitai_file_dropdown = gr.Dropdown(label="Files", choices=[], value=None, visible=False)
                civitai_target_dir = gr.Textbox(label="Download Directory", value="", placeholder="Absolute path to save the file.")
                civitai_download_button = gr.Button("Download Selected File", variant="primary")
                civitai_download_status = gr.Markdown(visible=False)
        with gr.TabItem("Info", id="tab_info"):
            with gr.Column():
                gr.Markdown("### Plugin & Developer Info")
                github_repo_btn = gr.Button("GitHub Repository")
                gitthub_display = gr.Markdown(visible=False)
                github_repo_btn.click(lambda: gr.update(value="https://github.com/kungful/ComfyUI_to_webui.git", visible=True), inputs=[], outputs=[gitthub_display])
                free_mirror_btn = gr.Button("Developer's Free Image")
                free_mirror_display = gr.Markdown(visible=False)
                free_mirror_btn.click(lambda: gr.update(value="https://www.xiangongyun.com/image/detail/7b36c1a3-da41-4676-b5b3-03ec25d6e197", visible=True), inputs=[], outputs=[free_mirror_display])
                contact_btn = gr.Button("Developer Contact")
                contact_display = gr.Markdown(visible=False)
                contact_btn.click(lambda: gr.update(value="**Email:** blenderkrita@gmail.com", visible=True), inputs=[], outputs=[contact_display])
                tutorial_btn = gr.Button("Tutorial (GitHub)")
                tutorial_display = gr.Markdown(visible=False)
                tutorial_btn.click(lambda: gr.update(value="https://github.com/kungful/ComfyUI_to_webui.git", visible=True), inputs=[], outputs=[tutorial_display])
                gr.Markdown("---")
                gr.Markdown("Click the buttons above for links and information.")
        with gr.TabItem("API JSON Manager", id="tab_api_json_manager"):
            define_api_json_management_ui()
# --- Event Handlers ---

    def refresh_workflow_and_ui(current_selected_json_file):
        log_message(f"[REFRESH_WORKFLOW_UI] Triggered. Current selection: {current_selected_json_file}")
        
        new_json_choices = get_json_files()
        log_message(f"[REFRESH_WORKFLOW_UI] New JSON choices: {new_json_choices}")

        json_to_load_for_ui_update = None
        
        if current_selected_json_file and current_selected_json_file in new_json_choices:
            json_to_load_for_ui_update = current_selected_json_file
            log_message(f"[REFRESH_WORKFLOW_UI] Current selection '{current_selected_json_file}' is still valid.")
        elif new_json_choices:
            json_to_load_for_ui_update = new_json_choices[0]
            log_message(f"[REFRESH_WORKFLOW_UI] Current selection '{current_selected_json_file}' is invalid or not present. Defaulting to first new choice: '{json_to_load_for_ui_update}'.")
        else:
            # No JSON files available at all
            log_message(f"[REFRESH_WORKFLOW_UI] No JSON files available after refresh.")
            # update_ui_on_json_change(None) will handle hiding/resetting components.

        # Get the UI updates based on the json_to_load_for_ui_update
        # update_ui_on_json_change returns a tuple of gr.update objects
        ui_updates_tuple = update_ui_on_json_change(json_to_load_for_ui_update)
        
        # The first part of the return will be the update for the json_dropdown itself
        dropdown_update = gr.update(choices=new_json_choices, value=json_to_load_for_ui_update)
        
        # Combine the dropdown update with the rest of the UI updates
        final_updates = (dropdown_update,) + ui_updates_tuple
        log_message(f"[REFRESH_WORKFLOW_UI] Returning {len(final_updates)} updates. Dropdown will be set to '{json_to_load_for_ui_update}'.")
        return final_updates

    # --- Node badge events (handled in Settings tab) ---
    # node_badge_mode_radio.change(fn=update_node_badge_mode, inputs=node_badge_mode_radio, outputs=node_badge_output_text)

    # --- Additional event handlers ---
    resolution_dropdown.change(fn=update_from_preset, inputs=resolution_dropdown, outputs=[resolution_dropdown, hua_width, hua_height, ratio_display])
    hua_width.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    hua_height.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    flip_btn.click(fn=flip_resolution, inputs=[hua_width, hua_height], outputs=[hua_width, hua_height])

    # When JSON selection changes, update all related component visibility and defaults
    def update_ui_on_json_change(json_file):
        workflow_dir, workflow_name, workflow_path = resolve_workflow_components(json_file)
        if workflow_dir and workflow_name:
            defaults = get_workflow_defaults_and_visibility(
                workflow_name,
                workflow_dir,
                resolution_prefixes,
                resolution_presets,
                MAX_DYNAMIC_COMPONENTS
            )
        elif json_file:
            defaults = get_workflow_defaults_and_visibility(
                json_file,
                OUTPUT_DIR,
                resolution_prefixes,
                resolution_presets,
                MAX_DYNAMIC_COMPONENTS
            )
        else:
            defaults = get_workflow_defaults_and_visibility(
                "",
                OUTPUT_DIR,
                resolution_prefixes,
                resolution_presets,
                MAX_DYNAMIC_COMPONENTS
            )

        updates = []

        updates.append(gr.update(visible=defaults["visible_image_input"]))  # image_accordion
        updates.append(gr.update(visible=defaults["visible_video_input"]))  # video_accordion
        updates.append(gr.update(visible=defaults["visible_neg_prompt"]))  # negative_prompt_accordion
        updates.append(gr.update(value=defaults["default_neg_prompt"]))  # prompt_negative

        negative_nodes = defaults.get("negative_prompt_nodes", [])
        for i in range(MAX_DYNAMIC_COMPONENTS):
            if i < len(negative_nodes):
                node_data = negative_nodes[i]
                node_id = node_data.get("id")
                label = node_data.get("title") or node_id or f"Negative Prompt Extra {i+1}"
                if node_id and label != node_id:
                    label = f"{label} (ID: {node_id})"
                elif node_id:
                    label = f"Negative Prompt Extra {i+1} (ID: {node_id})"
                updates.append(gr.update(visible=True, label=label, value=node_data.get("value", "")))
            else:
                updates.append(gr.update(visible=False, label=f"Negative Prompt Extra {i+1}", value=""))

        updates.append(gr.update(visible=defaults["visible_resolution"]))  # resolution_row
        closest_preset = find_closest_preset(defaults["default_width"], defaults["default_height"], resolution_presets, resolution_prefixes)
        ratio_str = calculate_aspect_ratio(defaults["default_width"], defaults["default_height"])
        ratio_display_text = f"Current ratio: {ratio_str}"
        updates.append(gr.update(value=closest_preset))
        updates.append(gr.update(value=defaults["default_width"]))
        updates.append(gr.update(value=defaults["default_height"]))
        updates.append(gr.update(value=ratio_display_text))

        updates.append(gr.update(visible=defaults["visible_checkpoint"], value=defaults["default_checkpoint"]))
        updates.append(gr.update(visible=defaults["visible_unet"], value=defaults["default_unet"]))
        updates.append(gr.update(visible=defaults["visible_seed_indicator"]))
        updates.append(gr.update(visible=defaults["visible_image_output"]))
        updates.append(gr.update(visible=defaults["visible_video_output"]))

        dynamic_prompts_data = defaults["dynamic_components"]["GradioTextOk"]
        for i in range(MAX_DYNAMIC_COMPONENTS):
            if i < len(dynamic_prompts_data):
                node_data = dynamic_prompts_data[i]
                node_id = node_data.get("id")
                node_title = node_data.get("title") or f"Prompt {i+1}"
                if node_id and node_title != node_id:
                    label = f"{node_title} (ID: {node_id})"
                elif node_id:
                    label = f"Prompt {i+1} (ID: {node_id})"
                else:
                    label = f"Prompt {i+1}"
                updates.append(gr.update(visible=True, label=label, value=node_data.get("value", "")))
            else:
                updates.append(gr.update(visible=False, label=f"Prompt {i+1}", value=""))

        dynamic_loras_data = defaults["dynamic_components"]["Hua_LoraLoaderModelOnly"]
        for i in range(MAX_DYNAMIC_COMPONENTS):
            if i < len(dynamic_loras_data):
                node_data = dynamic_loras_data[i]
                node_id = node_data.get("id")
                node_title = node_data.get("title") or f"Lora {i+1}"
                if node_id and node_title != node_id:
                    label = f"{node_title} (ID: {node_id})"
                elif node_id:
                    label = f"Lora {i+1} (ID: {node_id})"
                else:
                    label = f"Lora {i+1}"
                updates.append(gr.update(visible=True, label=label, value=node_data.get("value", "None"), choices=lora_list))
            else:
                updates.append(gr.update(visible=False, label=f"Lora {i+1}", value="None", choices=lora_list))

        dynamic_int_nodes = defaults["dynamic_components"]["HuaIntNode"]
        for i in range(MAX_DYNAMIC_COMPONENTS):
            if i < len(dynamic_int_nodes):
                node_data = dynamic_int_nodes[i]
                node_id = node_data.get("id")
                node_title = node_data.get("title") or f"Integer {i+1}"
                if node_id and node_title != node_id:
                    label = f"{node_title} (ID: {node_id})"
                elif node_id:
                    label = f"Integer {i+1} (ID: {node_id})"
                else:
                    label = f"Integer {i+1}"
                updates.append(gr.update(visible=True, label=label, value=node_data.get("value", 0)))
            else:
                updates.append(gr.update(visible=False, label=f"Integer {i+1}", value=0))

        dynamic_float_nodes = defaults["dynamic_components"]["HuaFloatNode"]
        for i in range(MAX_DYNAMIC_COMPONENTS):
            if i < len(dynamic_float_nodes):
                node_data = dynamic_float_nodes[i]
                node_id = node_data.get("id")
                node_title = node_data.get("title") or f"Float {i+1}"
                if node_id and node_title != node_id:
                    label = f"{node_title} (ID: {node_id})"
                elif node_id:
                    label = f"Float {i+1} (ID: {node_id})"
                else:
                    label = f"Float {i+1}"
                updates.append(gr.update(visible=True, label=label, value=node_data.get("value", 0.0)))
            else:
                updates.append(gr.update(visible=False, label=f"Float {i+1}", value=0.0))

        image_loader_nodes = defaults["dynamic_components"].get("ImageLoaders", [])
        image_loader_accordion_updates = []
        image_loader_value_updates = []
        for idx in range(MAX_IMAGE_LOADERS):
            if idx < len(image_loader_nodes):
                node_info = image_loader_nodes[idx]
                node_id = node_info.get("id")
                node_title = node_info.get("title") or f"Image Loader {idx+1}"
                connected_suffix = " [Connected]" if node_info.get("connected") else ""
                label = f"{node_title}{connected_suffix}"
                if node_id:
                    label = f"{label} (ID: {node_id})"
                image_loader_accordion_updates.append(gr.update(visible=True, label=label, open=False))
                image_loader_value_updates.extend([
                    gr.update(visible=True, value=node_info.get("resize", False)),
                    gr.update(visible=True, value=node_info.get("width")),
                    gr.update(visible=True, value=node_info.get("height")),
                    gr.update(visible=True, value=node_info.get("keep_proportion", False)),
                    gr.update(visible=True, value=node_info.get("divisible_by")),
                ])
            else:
                image_loader_accordion_updates.append(gr.update(visible=False, open=False))
                image_loader_value_updates.extend([
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=None),
                    gr.update(visible=False, value=None),
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=None),
                ])
        updates.extend(image_loader_accordion_updates)
        updates.extend(image_loader_value_updates)

        dynamic_ksampler_data = defaults["dynamic_components"].get("KSampler", [])
        ksampler_accordion_updates = []
        ksampler_value_updates = []
        for idx in range(MAX_KSAMPLER_CONTROLS):
            if idx < len(dynamic_ksampler_data):
                node_data = dynamic_ksampler_data[idx]
                node_id = node_data.get("id")
                label = node_data.get("title") or node_id or f"KSampler {idx+1}"
                if node_id:
                    label = f"{label} (ID: {node_id})"
                ksampler_accordion_updates.append(gr.update(visible=True, label=label, open=False))
                steps_value = node_data.get("steps", 20)
                cfg_value = node_data.get("cfg", 7.0)
                seed_hint = node_data.get("seed_hint", "")
                seed_display_value = node_data.get("seed", "")
                seed_update_kwargs = {"visible": True, "value": seed_display_value or "", "placeholder": ""}
                if seed_hint:
                    seed_update_kwargs["placeholder"] = f"Saved seed: {seed_hint} (clear for random)"
                ksampler_value_updates.extend([
                    gr.update(visible=True, value=steps_value),
                    gr.update(visible=True, value=cfg_value),
                    gr.update(visible=True, value=node_data.get("sampler_name", "")),
                    gr.update(visible=True, value=node_data.get("scheduler", "")),
                    gr.update(visible=True, value=node_data.get("start_at_step", 0)),
                    gr.update(visible=True, value=node_data.get("end_at_step", 0)),
                    gr.update(visible=True, value=node_data.get("add_noise", "enable")),
                    gr.update(visible=True, value=node_data.get("return_with_leftover_noise", "disable")),
                    gr.update(**seed_update_kwargs),
                ])
            else:
                ksampler_accordion_updates.append(gr.update(visible=False))
                ksampler_value_updates.extend([
                    gr.update(visible=False, value=20),
                    gr.update(visible=False, value=7.0),
                    gr.update(visible=False, value=""),
                    gr.update(visible=False, value=""),
                    gr.update(visible=False, value=0),
                    gr.update(visible=False, value=0),
                    gr.update(visible=False, value="enable"),
                    gr.update(visible=False, value="disable"),
                    gr.update(visible=False, value=""),
                ])
        updates.extend(ksampler_accordion_updates)
        updates.extend(ksampler_value_updates)

        dynamic_mask_data = defaults["dynamic_components"].get("APersonMaskGenerator", [])
        mask_accordion_updates = []
        mask_value_updates = []
        for idx in range(MAX_MASK_GENERATORS):
            if idx < len(dynamic_mask_data):
                node_data = dynamic_mask_data[idx]
                node_id = node_data.get("id")
                label = node_data.get("title") or node_id or f"Mask Generator {idx+1}"
                if node_id:
                    label = f"{label} (ID: {node_id})"
                mask_accordion_updates.append(gr.update(visible=True, label=label, open=False))
                mask_value_updates.extend([
                    gr.update(visible=True, value=bool(node_data.get("face_mask", True))),
                    gr.update(visible=True, value=bool(node_data.get("background_mask", False))),
                    gr.update(visible=True, value=bool(node_data.get("hair_mask", False))),
                    gr.update(visible=True, value=bool(node_data.get("body_mask", False))),
                    gr.update(visible=True, value=bool(node_data.get("clothes_mask", False))),
                    gr.update(visible=True, value=float(node_data.get("confidence", 0.15))),
                    gr.update(visible=True, value=bool(node_data.get("refine_mask", False))),
                ])
            else:
                mask_accordion_updates.append(gr.update(visible=False))
                mask_value_updates.extend([
                    gr.update(visible=False, value=True),
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=0.15),
                    gr.update(visible=False, value=False),
                ])
        updates.extend(mask_accordion_updates)
        updates.extend(mask_value_updates)
        notice_visible = len(dynamic_mask_data) == 0
        notice_text = MASK_GENERATOR_NOTICE_TEXT if notice_visible else ""
        updates.append(gr.update(visible=notice_visible, value=notice_text))
        updates.append(gr.update(value=""))

        return tuple(updates)



    json_dropdown.change(
        fn=update_ui_on_json_change,
        inputs=json_dropdown,
        outputs=[
            image_accordion,
            video_accordion,
            negative_prompt_accordion,
            prompt_negative,
            *negative_prompt_extras,
            resolution_row,
            resolution_dropdown,
            hua_width,
            hua_height,
            ratio_display,
            hua_checkpoint_dropdown,
            hua_unet_dropdown,
            seed_options_col,
            output_gallery,
            output_video,
            *positive_prompt_texts,
            *lora_dropdowns,
            *int_inputs,
            *float_inputs,
            *IMAGE_LOADER_ACCORDION_COMPONENTS,
            *IMAGE_LOADER_COMPONENTS_FLAT,
            *KSAMPLER_ACCORDION_COMPONENTS,
            *KSAMPLER_COMPONENTS_FLAT,
            *MASK_ACCORDION_COMPONENTS,
            *MASK_COMPONENTS_FLAT,
            mask_generator_notice,
            photopea_data_bus
        ]
    )

    # --- Toggle fixed seed input visibility based on seed mode ---
    def toggle_fixed_seed_input(mode):
        return gr.update(visible=(mode == "Fixed"))

    seed_mode_dropdown.change(
        fn=toggle_fixed_seed_input,
        inputs=seed_mode_dropdown,
        outputs=fixed_seed_input
    )
    # --- End toggle helper ---

    refresh_button.click(
        fn=refresh_workflow_and_ui,
        inputs=[json_dropdown],
        outputs=[
            json_dropdown,
            image_accordion,
            video_accordion,
            negative_prompt_accordion,
            prompt_negative,
            *negative_prompt_extras,
            resolution_row,
            resolution_dropdown,
            hua_width,
            hua_height,
            ratio_display,
            hua_checkpoint_dropdown,
            hua_unet_dropdown,
            seed_options_col,
            output_gallery,
            output_video,
            *positive_prompt_texts,
            *lora_dropdowns,
            *int_inputs,
            *float_inputs,
            *IMAGE_LOADER_ACCORDION_COMPONENTS,
            *IMAGE_LOADER_COMPONENTS_FLAT,
            *KSAMPLER_ACCORDION_COMPONENTS,
            *KSAMPLER_COMPONENTS_FLAT,
            *MASK_ACCORDION_COMPONENTS,
            *MASK_COMPONENTS_FLAT,
            mask_generator_notice,
            photopea_data_bus
        ]
    )

    def handle_gallery_select(evt: gr.SelectData | None = None):
        if evt is None:
            return gr.update(), None, None, ""

        selected = getattr(evt, "value", None)
        candidate_path = None

        if isinstance(selected, (list, tuple)) and selected:
            candidate_path = selected[0]
        elif isinstance(selected, dict):
            candidate_path = selected.get("path") or selected.get("name") or selected.get("value")
        elif isinstance(selected, str):
            candidate_path = selected

        if isinstance(candidate_path, str):
            candidate_path = candidate_path.strip()
            if candidate_path and not os.path.isabs(candidate_path) and not os.path.exists(candidate_path):
                potential = os.path.join(OUTPUT_DIR, candidate_path)
                if os.path.exists(potential):
                    candidate_path = potential

        if not candidate_path or not os.path.exists(candidate_path):
            log_message(f"[GALLERY_SELECT] Unable to resolve selected image path from value '{selected}'.")
            return gr.update(), None, None, ""

        pil_img = _load_image_from_path(candidate_path, "gallery-select")
        if pil_img is None:
            log_message(f"[GALLERY_SELECT] Failed to load image at '{candidate_path}'.")
            return gr.update(), candidate_path, None, ""

        try:
            pil_for_component = pil_img.convert("RGBA")
        except Exception:
            pil_for_component = pil_img

        data_url = _encode_pil_to_data_url(pil_for_component)
        log_message(f"[GALLERY_SELECT] Forwarded '{candidate_path}' to image input.")
        return gr.update(value=pil_for_component), candidate_path, data_url, (data_url or "")

    def sync_photopea_state(image_payload):
        base_img, _ = _coerce_uploaded_image_to_pil(image_payload, "photopea-sync", return_mask=True)
        if base_img is None:
            return None, ""
        try:
            rgba = base_img.convert("RGBA")
        except Exception:
            rgba = base_img
        data_url = _encode_pil_to_data_url(rgba)
        return data_url, data_url or ""

    def notify_photopea_load(data_url):
        if not data_url:
            return gr.update(value="Please select or edit an image before sending it to Photopea.")
        return gr.update(value="Image sent to Photopea. Switch to the editor above to start editing.")

    def notify_photopea_request():
        return gr.update(value="Waiting for Photopea to return the edited image...")

    def ingest_photopea_payload(payload_str):
        print(f"[PHOTOPEA] Received payload (length: {len(payload_str) if payload_str else 0})")
        if not payload_str:
            return gr.update(), None, "", gr.update(value=""), gr.update(value="Photopea did not return any data."), None

        raw_data = payload_str
        export_name = "photopea.png"
        try:
            parsed = json.loads(payload_str)
            if isinstance(parsed, dict):
                print(f"[PHOTOPEA] Parsed JSON payload with keys: {parsed.keys()}")
                raw_data = parsed.get("data") or raw_data
                export_name = parsed.get("name") or export_name
                print(f"[PHOTOPEA] Export name: {export_name}, data length: {len(raw_data) if raw_data else 0}")
        except json.JSONDecodeError as e:
            print(f"[PHOTOPEA] Failed to parse as JSON, using raw data: {e}")
            pass

        if not raw_data:
            print("[PHOTOPEA] Error: Empty data received")
            return gr.update(), None, "", gr.update(value=""), gr.update(value="Received empty data from Photopea."), None

        try:
            # Handle data URL format (data:image/png;base64,...)
            if raw_data.startswith("data:"):
                print("[PHOTOPEA] Detected data URL format, extracting base64...")
                raw_data = raw_data.split(",", 1)[1] if "," in raw_data else raw_data

            binary = base64.b64decode(raw_data)
            print(f"[PHOTOPEA] Decoded {len(binary)} bytes of image data")
            with Image.open(io.BytesIO(binary)) as pil_img:
                converted = pil_img.convert("RGBA")
            print(f"[PHOTOPEA] Successfully loaded image: {converted.width}x{converted.height}")
            data_url = _encode_pil_to_data_url(converted)
            status_msg = f"Imported '{export_name}' from Photopea ({converted.width}x{converted.height})."
            print(f"[PHOTOPEA] {status_msg}")
            return (
                gr.update(value=converted),
                data_url,
                data_url or "",
                gr.update(value=""),
                gr.update(value=status_msg),
                "photopea_import",
            )
        except Exception as exc:
            print(f"[PHOTOPEA] Error importing from Photopea: {exc}")
            import traceback
            traceback.print_exc()
            return (
                gr.update(),
                None,
                "",
                gr.update(value=""),
                gr.update(value=f"Failed to import from Photopea: {exc}"),
                None,
            )

    def send_latest_to_upload():
        """Send latest gallery image to upload input."""
        # Get latest image from accumulated results
        with results_lock:
            latest_images = accumulated_image_results[:]

        if not latest_images:
            log_message("[FORWARD] No images in gallery to send to upload.")
            return gr.update()

        # Get the last (most recent) image
        latest_path = latest_images[-1]
        if not os.path.isfile(latest_path):
            log_message(f"[FORWARD] Latest image path not found: {latest_path}")
            return gr.update()

        try:
            with Image.open(latest_path) as pil_img:
                rgba = pil_img.convert("RGBA")
            log_message(f"[FORWARD] Sent latest image to upload: {os.path.basename(latest_path)}")
            return gr.update(value=rgba)
        except Exception as exc:
            log_message(f"[FORWARD] Error loading latest image: {exc}")
            return gr.update()

    def send_selected_to_photopea(photopea_data):
        """Send selected gallery image to Photopea."""
        if not photopea_data:
            return gr.update(value="Please select an image from the gallery first."), gr.update()
        log_message("[FORWARD] Sending selected image to Photopea.")
        # Escape the data for JavaScript (replace quotes and backslashes)
        escaped_data = photopea_data.replace('\\', '\\\\').replace('"', '\\"')
        # Trigger JavaScript to open in Photopea
        js_trigger = f"""<script>
        (function() {{
            const dataUrl = "{escaped_data}";
            if (window.huaPhotopeaBridge && window.huaPhotopeaBridge.open) {{
                window.huaPhotopeaBridge.open(dataUrl, "selected_image.png");
                console.log("[FORWARD] Triggered Photopea bridge - data length:", dataUrl.length);
            }} else {{
                console.warn("[FORWARD] Photopea bridge not available");
            }}
        }})();
        </script>"""
        return gr.update(value="Image sent to Photopea. Switch to the Photopea tab to edit."), gr.update(value=js_trigger)

    def send_upload_to_photopea(photopea_data):
        """Send current upload image to Photopea."""
        if not photopea_data:
            return gr.update(value="Please upload an image first."), gr.update()
        log_message("[FORWARD] Sending upload image to Photopea.")
        # Escape the data for JavaScript
        escaped_data = photopea_data.replace('\\', '\\\\').replace('"', '\\"')
        # Trigger JavaScript to open in Photopea
        js_trigger = f"""<script>
        (function() {{
            const dataUrl = "{escaped_data}";
            if (window.huaPhotopeaBridge && window.huaPhotopeaBridge.open) {{
                window.huaPhotopeaBridge.open(dataUrl, "upload_image.png");
                console.log("[FORWARD] Triggered Photopea bridge - data length:", dataUrl.length);
            }} else {{
                console.warn("[FORWARD] Photopea bridge not available");
            }}
        }})();
        </script>"""
        return gr.update(value="Image sent to Photopea. Switch to the Photopea tab to edit."), gr.update(value=js_trigger)

    def _format_bytes_from_kb(kilobytes: float | int | None) -> str:
        try:
            if kilobytes is None:
                return "Unknown size"
            bytes_value = float(kilobytes) * 1024.0
            for unit in ("B", "KB", "MB", "GB", "TB"):
                if bytes_value < 1024 or unit == "TB":
                    return f"{bytes_value:.2f} {unit}"
                bytes_value /= 1024
        except (TypeError, ValueError):
            pass
        return "Unknown size"

    def _sanitize_filename(name: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in (" ", ".", "_", "-", "(", ")") else "_" for ch in (name or ""))
        return safe.strip() or "download.bin"

    def _suggest_civitai_target_directory(model_type: str | None, file_info: dict | None) -> str:
        base_dir = os.path.join(OUTPUT_DIR, "civitai_downloads")
        model_folder = (model_type or "misc").replace(" ", "_").lower()
        return os.path.join(base_dir, model_folder)

    def _determine_civitai_api_key(override_key: str | None) -> str:
        candidate = (override_key or "").strip()
        if candidate:
            return candidate
        settings = load_plugin_settings()
        if isinstance(settings, dict):
            return (settings.get("civitai_api_key") or "").strip()
        return ""

    def _save_civitai_api_key(api_key_value: str) -> str:
        settings = load_plugin_settings()
        if not isinstance(settings, dict):
            settings = {}
        settings["civitai_api_key"] = (api_key_value or "").strip()
        return save_plugin_settings(settings)

    def _civitai_api_get(endpoint: str, params: dict, api_key: str | None, timeout: float = 30.0) -> dict:
        url = f"{CIVITAI_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {"User-Agent": "ComfyUI-to-WebUI Civitai Client"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def _summarize_civitai_model(model: dict) -> str:
        if not isinstance(model, dict):
            return ""
        stats = model.get("stats") or {}
        downloads = stats.get("downloadCount")
        rating = stats.get("rating")
        tags = model.get("tags") or []
        lines = [f"**{model.get('name', 'Unnamed model')}**"]
        if model.get("type"):
            lines.append(f"Type: {model['type']}")
        if downloads is not None:
            lines.append(f"Downloads: {downloads}")
        if rating is not None:
            try:
                lines.append(f"Rating: {float(rating):.2f}")
            except (TypeError, ValueError):
                lines.append(f"Rating: {rating}")
        if tags:
            lines.append("Tags: " + ", ".join(tags[:10]))
        description = model.get("description") or ""
        if description:
            snippet = description[:600]
            if len(description) > 600:
                snippet += "…"
            lines.append("")
            lines.append(snippet)
        return "\n".join(lines)

    def _civitai_parse_image_gallery(images: list | None) -> list:
        gallery = []
        if not isinstance(images, list):
            return gallery
        for image in images[:10]:
            if not isinstance(image, dict):
                continue
            url = image.get("url") or image.get("originalUrl")
            if not url:
                continue
            caption = image.get("meta", {}).get("prompt") or image.get("alt") or ""
            gallery.append((url, caption))
        return gallery

    def civitai_save_api_key(api_key_value: str):
        status = _save_civitai_api_key(api_key_value or "")
        message = "🔐 Civitai API key saved." if (api_key_value or "").strip() else "🔓 Cleared stored Civitai API key."
        return gr.update(value=f"{message} ({status})", visible=True)

    def civitai_perform_search(query, model_type, sort_label, page_value, per_page_value, nsfw_setting, api_key_override):
        api_key = _determine_civitai_api_key(api_key_override)
        try:
            page = max(1, int(page_value or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = int(per_page_value or 20)
            per_page = max(1, min(per_page, 50))
        except (TypeError, ValueError):
            per_page = 20

        params = {"page": page, "perPage": per_page}
        if query:
            params["query"] = query.strip()
        if model_type:
            params["types"] = model_type.strip()
        sort_value = CIVITAI_SORT_MAP.get(sort_label or "")
        if sort_value:
            params["sort"] = sort_value
        nsfw_value = CIVITAI_NSFW_MAP.get(nsfw_setting or "Hide")
        if nsfw_value:
            params["nsfw"] = nsfw_value

        try:
            response = _civitai_api_get("models", params, api_key, timeout=45)
            items = response.get("items") or []
        except requests.RequestException as exc:
            message = f"Search failed: {exc}"
            return (
                gr.update(choices=[], value=None, visible=True),
                [],
                gr.update(value=message, visible=True),
                gr.update(value="", visible=False),
                gr.update(value=[], visible=False),
                gr.update(choices=[], value=None, visible=False),
                gr.update(choices=[], value=None, visible=False),
                None,
                None,
                gr.update(value="", visible=False),
                gr.update(value=_suggest_civitai_target_directory(model_type, None), visible=True),
            )

        choices = []
        state_payload = []
        for idx, model in enumerate(items):
            if not isinstance(model, dict):
                continue
            label_parts = [model.get("name") or f"Model {idx+1}"]
            model_type_label = model.get("type")
            if model_type_label:
                label_parts.append(f"[{model_type_label}]")
            rating = model.get("stats", {}).get("rating")
            if rating:
                try:
                    label_parts.append(f"⭐ {float(rating):.2f}")
                except (TypeError, ValueError):
                    label_parts.append(f"⭐ {rating}")
            label = " ".join(label_parts)
            choices.append(label)
            state_payload.append({"index": idx, "label": label, "model": model})

        message = f"Found {len(state_payload)} model(s)." if state_payload else "No models found."
        return (
            gr.update(choices=choices, value=choices[0] if choices else None, visible=bool(choices)),
            state_payload,
            gr.update(value=message, visible=True),
            gr.update(value="", visible=False),
            gr.update(value=[], visible=False),
            gr.update(choices=[], value=None, visible=False),
            gr.update(choices=[], value=None, visible=False),
            None,
            None,
            gr.update(value="", visible=False),
            gr.update(value=_suggest_civitai_target_directory(model_type, None), visible=True),
        )

    def civitai_select_model(selected_label, results_state):
        if not results_state:
            return (
                gr.update(value="", visible=False),
                gr.update(value=[], visible=False),
                gr.update(choices=[], value=None, visible=False),
                gr.update(choices=[], value=None, visible=False),
                None,
                None,
                gr.update(value="", visible=False),
                gr.update(value=_suggest_civitai_target_directory(None, None), visible=True),
            )

        entry = None
        for candidate in results_state:
            if candidate.get("label") == selected_label:
                entry = candidate
                break
        if entry is None:
            entry = results_state[0]

        model = entry.get("model") or {}
        versions = model.get("modelVersions") or []
        version_choices = []
        selected_version_index = 0 if versions else None
        for idx, version in enumerate(versions):
            version_choices.append(version.get("name") or f"Version {idx+1}")
        preview_items = _civitai_parse_image_gallery(versions[selected_version_index].get("images")) if versions else []

        files = versions[selected_version_index].get("files") if versions else []
        files = files or []
        file_choices = []
        for idx, file_info in enumerate(files):
            name = file_info.get("name") or f"File {idx+1}"
            size_kb = file_info.get("sizeKB")
            if size_kb:
                name = f"{name} ({_format_bytes_from_kb(size_kb)})"
            file_choices.append(name)

        model_state = {
            "model": model,
            "version_index": selected_version_index,
            "label": entry.get("label"),
        }
        file_state = {"file": files[0], "file_index": 0} if files else None

        details = _summarize_civitai_model(model)
        target_dir = _suggest_civitai_target_directory(model.get("type"), files[0] if files else None)

        return (
            gr.update(value=details, visible=True),
            gr.update(value=preview_items, visible=bool(preview_items)),
            gr.update(choices=version_choices, value=version_choices[0] if version_choices else None, visible=bool(version_choices)),
            gr.update(choices=file_choices, value=file_choices[0] if file_choices else None, visible=bool(file_choices)),
            model_state,
            file_state,
            gr.update(value="", visible=False),
            gr.update(value=target_dir, visible=True),
        )

    def civitai_select_version(version_label, selected_model_state):
        if not isinstance(selected_model_state, dict):
            return (
                gr.update(choices=[], value=None, visible=False),
                None,
                None,
                gr.update(value=_suggest_civitai_target_directory(None, None), visible=True),
                gr.update(value="", visible=False),
            )

        model = selected_model_state.get("model") or {}
        versions = model.get("modelVersions") or []
        version_index = 0
        version_choices = []
        for idx, version in enumerate(versions):
            name = version.get("name") or f"Version {idx+1}"
            version_choices.append(name)
            if name == version_label:
                version_index = idx

        files = versions[version_index].get("files") if versions else []
        files = files or []
        file_choices = []
        for idx, file_info in enumerate(files):
            name = file_info.get("name") or f"File {idx+1}"
            size_kb = file_info.get("sizeKB")
            if size_kb:
                name = f"{name} ({_format_bytes_from_kb(size_kb)})"
            file_choices.append(name)

        file_state = {"file": files[0], "file_index": 0} if files else None

        selected_model_state = dict(selected_model_state)
        selected_model_state["version_index"] = version_index
        target_dir = _suggest_civitai_target_directory(model.get("type"), files[0] if files else None)

        return (
            gr.update(choices=file_choices, value=file_choices[0] if file_choices else None, visible=bool(file_choices)),
            selected_model_state,
            file_state,
            gr.update(value=target_dir, visible=True),
            gr.update(value="", visible=False),
        )

    def civitai_select_file(file_label, selected_model_state):
        if not isinstance(selected_model_state, dict):
            return None, None, gr.update(value=_suggest_civitai_target_directory(None, None), visible=True), gr.update(value="", visible=False)

        model = selected_model_state.get("model") or {}
        version_index = selected_model_state.get("version_index", 0)
        versions = model.get("modelVersions") or []
        files = versions[version_index].get("files") if versions else []
        files = files or []

        file_state = None
        for idx, file_info in enumerate(files):
            name = file_info.get("name") or f"File {idx+1}"
            size_kb = file_info.get("sizeKB")
            if size_kb:
                name = f"{name} ({_format_bytes_from_kb(size_kb)})"
            if name == file_label:
                file_state = {"file": file_info, "file_index": idx}
                break
        if file_state is None and files:
            file_state = {"file": files[0], "file_index": 0}

        target_dir = _suggest_civitai_target_directory(model.get("type"), file_state["file"] if file_state else None)
        return selected_model_state, file_state, gr.update(value=target_dir, visible=True), gr.update(value="", visible=False)

    def civitai_download_file_action(selected_model_state, selected_file_state, target_dir_value, api_key_override):
        state = selected_model_state or {}
        model = state.get("model")
        version_index = state.get("version_index", 0)
        if not model:
            return gr.update(value="⚠️ Select a model before downloading.", visible=True)

        versions = model.get("modelVersions") or []
        if not versions or version_index >= len(versions):
            return gr.update(value="⚠️ Selected model has no versions.", visible=True)

        files = versions[version_index].get("files") or []
        if not files:
            return gr.update(value="⚠️ Selected version has no downloadable files.", visible=True)

        if not selected_file_state or "file" not in selected_file_state:
            file_info = files[0]
        else:
            file_info = selected_file_state["file"]

        download_url = file_info.get("downloadUrl")
        if not download_url:
            return gr.update(value="⚠️ Selected file does not provide a download URL.", visible=True)

        api_key = _determine_civitai_api_key(api_key_override)
        target_dir = (target_dir_value or "").strip() or _suggest_civitai_target_directory(model.get("type"), file_info)
        target_dir = os.path.abspath(target_dir)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as exc:
            return gr.update(value=f"❌ Unable to create directory '{target_dir}': {exc}", visible=True)

        filename = file_info.get("name") or os.path.basename(download_url.split("?", 1)[0])
        filename = _sanitize_filename(filename)
        file_path = os.path.join(target_dir, filename)
        if os.path.exists(file_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(target_dir, f"{base}_{counter}{ext}")):
                counter += 1
            file_path = os.path.join(target_dir, f"{base}_{counter}{ext}")

        headers = {"User-Agent": "ComfyUI-to-WebUI Civitai Client"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            with requests.get(download_url, headers=headers, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(file_path, "wb") as outfile:
                    for chunk in response.itercontent(chunk_size=8192):
                        if chunk:
                            outfile.write(chunk)
        except requests.RequestException as exc:
            return gr.update(value=f"❌ Download failed: {exc}", visible=True)
        except OSError as exc:
            return gr.update(value=f"❌ Failed to save file: {exc}", visible=True)

        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        size_label = _format_bytes_from_kb(size_bytes / 1024 if size_bytes else None)
        return gr.update(value=f"✅ Downloaded to `{file_path}` ({size_label}).", visible=True)

    # get_output_images is imported, needs OUTPUT_DIR

    # get_output_images is imported, needs OUTPUT_DIR
    load_output_button.click(fn=lambda: get_output_images(OUTPUT_DIR), inputs=[], outputs=output_preview_gallery)

    output_gallery.select(
        fn=handle_gallery_select,
        inputs=[],
        outputs=[input_image, selected_gallery_image_state, photopea_image_data_state, photopea_data_bus]
    )

    output_preview_gallery.select(
        fn=handle_gallery_select,
        inputs=[],
        outputs=[input_image, selected_gallery_image_state, photopea_image_data_state, photopea_data_bus]
    )

    # Image forwarding buttons
    send_to_upload_button.click(
        fn=send_latest_to_upload,
        inputs=[],
        outputs=[input_image]
    )

    send_to_photopea_button.click(
        fn=send_selected_to_photopea,
        inputs=[photopea_image_data_state],
        outputs=[photopea_status, photopea_js_trigger]
    )

    upload_to_photopea_button.click(
        fn=send_upload_to_photopea,
        inputs=[photopea_image_data_state],
        outputs=[photopea_status, upload_photopea_js_trigger]
    )

    photopea_sync_events = [getattr(input_image, "change", None), getattr(input_image, "upload", None)]
    if hasattr(input_image, "edit"):
        photopea_sync_events.append(getattr(input_image, "edit"))
    for event_binding in photopea_sync_events:
        if callable(event_binding):
            event_binding(
                fn=sync_photopea_state,
                inputs=input_image,
                outputs=[photopea_image_data_state, photopea_data_bus]
            )

    load_photopea_button.click(
        fn=notify_photopea_load,
        inputs=[photopea_data_bus],
        outputs=[photopea_status]
    )

    photopea_fetch_button.click(
        fn=notify_photopea_request,
        inputs=[],
        outputs=[photopea_status]
    )

    photopea_import_box.change(
        fn=ingest_photopea_payload,
        inputs=photopea_import_box,
        outputs=[input_image, photopea_image_data_state, photopea_data_bus, photopea_import_box, photopea_status, selected_gallery_image_state]
    )

    civitai_save_key_button.click(
        fn=civitai_save_api_key,
        inputs=[civitai_api_key_input],
        outputs=[civitai_key_status]
    )

    civitai_search_button.click(
        fn=civitai_perform_search,
        inputs=[civitai_query, civitai_type, civitai_sort, civitai_page, civitai_per_page, civitai_nsfw, civitai_api_key_input],
        outputs=[
            civitai_results_dropdown,
            civitai_results_state,
            civitai_search_status,
            civitai_model_details,
            civitai_preview_gallery,
            civitai_version_dropdown,
            civitai_file_dropdown,
            civitai_selected_model_state,
            civitai_selected_file_state,
            civitai_download_status,
            civitai_target_dir,
        ]
    )

    civitai_results_dropdown.change(
        fn=civitai_select_model,
        inputs=[civitai_results_dropdown, civitai_results_state],
        outputs=[
            civitai_model_details,
            civitai_preview_gallery,
            civitai_version_dropdown,
            civitai_file_dropdown,
            civitai_selected_model_state,
            civitai_selected_file_state,
            civitai_download_status,
            civitai_target_dir,
        ]
    )

    civitai_version_dropdown.change(
        fn=civitai_select_version,
        inputs=[civitai_version_dropdown, civitai_selected_model_state],
        outputs=[
            civitai_file_dropdown,
            civitai_selected_model_state,
            civitai_selected_file_state,
            civitai_target_dir,
            civitai_download_status,
        ]
    )

    civitai_file_dropdown.change(
        fn=civitai_select_file,
        inputs=[civitai_file_dropdown, civitai_selected_model_state],
        outputs=[
            civitai_selected_model_state,
            civitai_selected_file_state,
            civitai_target_dir,
            civitai_download_status,
        ]
    )

    civitai_download_button.click(
        fn=civitai_download_file_action,
        inputs=[civitai_selected_model_state, civitai_selected_file_state, civitai_target_dir, civitai_api_key_input],
        outputs=[civitai_download_status]
    )

    # --- Run button wiring ---
    run_button.click(
        fn=run_queued_tasks,
        inputs=[
            input_image,
            input_video,
            *positive_prompt_texts,
            prompt_negative,
            *negative_prompt_extras,
            json_dropdown,
            hua_width,
            hua_height,
            *lora_dropdowns,
            hua_checkpoint_dropdown,
            hua_unet_dropdown,
            *float_inputs,
            *int_inputs,
            *IMAGE_LOADER_COMPONENTS_FLAT,
            seed_mode_dropdown,
            fixed_seed_input,
            queue_count,
            *KSAMPLER_COMPONENTS_FLAT,
            *MASK_COMPONENTS_FLAT
        ],
        outputs=[
            queue_status_display,
            output_gallery,
            output_video,
            main_output_tabs_component,
            live_preview_image,
            live_preview_status,
            selected_gallery_image_state,
            photopea_image_data_state,
            photopea_data_bus,
            photopea_status
        ]
    )
    
    # interrupt button removed in favour of queue controls

    # --- Additional button events ---
    clear_queue_button.click(fn=clear_queue, inputs=[], outputs=[queue_status_display])
    clear_history_button.click(fn=clear_history, inputs=[], outputs=[output_gallery, output_video, queue_status_display])

    refresh_model_button.click(
        lambda: tuple(
            [gr.update(choices=get_model_list("loras")) for _ in range(MAX_DYNAMIC_COMPONENTS)] +
            [gr.update(choices=get_model_list("checkpoints")), gr.update(choices=get_model_list("unet"))]
        ),
        inputs=[],
        outputs=[*lora_dropdowns, hua_checkpoint_dropdown, hua_unet_dropdown]
    )

    # --- Initial load ---
    def on_load_setup():
        json_files = get_json_files()
        # The number of outputs from update_ui_on_json_change is now:
        # 13 (single instance UI elements) + 4 * MAX_DYNAMIC_COMPONENTS (dynamic elements)
        # = 13 + 4 * 5 = 13 + 20 = 33
        
        if not json_files:
            print("No workflow JSON files found; hiding dynamic components and using defaults.")

            initial_updates = [
                gr.update(visible=False),  # image_accordion
                gr.update(visible=False),  # video_accordion
                gr.update(visible=False),  # negative_prompt_accordion
                gr.update(visible=False, value=""),  # prompt_negative
            ]
            for _ in range(MAX_DYNAMIC_COMPONENTS):
                initial_updates.append(gr.update(visible=False, label="Negative Prompt Extra", value=""))
            initial_updates.extend([
                gr.update(visible=False),  # resolution_row
                gr.update(value="custom"),
                gr.update(value=512),
                gr.update(value=512),
                gr.update(value="Current ratio: 1:1"),
                gr.update(visible=False, value="None"),
                gr.update(visible=False, value="None"),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
            ])
            for _ in range(MAX_DYNAMIC_COMPONENTS):
                initial_updates.append(gr.update(visible=False, label="Prompt", value=""))
            for _ in range(MAX_DYNAMIC_COMPONENTS):
                initial_updates.append(gr.update(visible=False, label="Lora", value="None"))
            for _ in range(MAX_DYNAMIC_COMPONENTS):
                initial_updates.append(gr.update(visible=False, label="Integer", value=0))
            for _ in range(MAX_DYNAMIC_COMPONENTS):
                initial_updates.append(gr.update(visible=False, label="Float", value=0.0))
            for _ in range(MAX_IMAGE_LOADERS):
                initial_updates.append(gr.update(visible=False, open=False))
                initial_updates.extend([
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=None),
                    gr.update(visible=False, value=None),
                    gr.update(visible=False, value=False),
                    gr.update(visible=False, value=None),
                ])
            for _ in range(MAX_KSAMPLER_CONTROLS):
                initial_updates.append(gr.update(visible=False, open=False))
            for _ in range(MAX_KSAMPLER_CONTROLS * 9):
                initial_updates.append(gr.update(visible=False))
            for _ in range(MAX_MASK_GENERATORS):
                initial_updates.append(gr.update(visible=False))
            for _ in range(MAX_MASK_GENERATORS * MASK_FIELD_COUNT):
                initial_updates.append(gr.update(visible=False))
            initial_updates.append(gr.update(visible=False, value=""))
            return tuple(initial_updates)
        else:
            default_json = json_files[0]
            print(f"Initial load check for default JSON: {default_json}")
            return update_ui_on_json_change(default_json) # This now returns a tuple of gr.update calls

    demo.load(
        fn=on_load_setup,
        inputs=[],
        outputs=[ # This list must exactly match the components updated by on_load_setup / update_ui_on_json_change
            image_accordion,
            video_accordion,
            negative_prompt_accordion,
            prompt_negative,
            *negative_prompt_extras,
            resolution_row,
            resolution_dropdown,
            hua_width,
            hua_height,
            ratio_display,
            hua_checkpoint_dropdown,
            hua_unet_dropdown,
            seed_options_col,
            output_gallery,
            output_video,
            *positive_prompt_texts,
            *lora_dropdowns,
            *int_inputs,
            *float_inputs,
            *IMAGE_LOADER_ACCORDION_COMPONENTS,
            *IMAGE_LOADER_COMPONENTS_FLAT,
            *KSAMPLER_ACCORDION_COMPONENTS,
            *KSAMPLER_COMPONENTS_FLAT,
            *MASK_ACCORDION_COMPONENTS,
            *MASK_COMPONENTS_FLAT,
            mask_generator_notice
        ]
    )

    # --- Log polling timer ---
    # Poll fetch_and_format_logs every 0.1s for smoother updates
    log_timer = gr.Timer(0.1, active=True)  # tick every 0.1 seconds
    log_timer.tick(fetch_and_format_logs, inputs=None, outputs=log_display)

    # --- System monitor stream ---
    # outputs should reference floating_monitor_html_output defined above
    # ensure floating_monitor_html_output is accessible at load time
    # (defined within the Blocks context so demo knows about it)
    demo.load(fn=update_floating_monitors_stream, inputs=None, outputs=[floating_monitor_html_output], show_progress="hidden")

    # --- ComfyUI live preview stream ---
    demo.load(
        fn=comfyui_previewer.get_update_generator(),
        inputs=[],
        outputs=[live_preview_image, live_preview_status],
        show_progress="hidden"  # preview stream does not need progress bar
    )
    # Start preview worker thread
    # demo.load(fn=comfyui_previewer.start_worker, inputs=[], outputs=[], show_progress="hidden")
    # Starting after Gradio launch is more reliable
    # Alternatively call from on_load_setup


    # --- Gradio launch helper ---
def luanch_gradio(demo_instance):  # receive demo instance
    # Start worker before launching Gradio
    print("Starting ComfyUIPreviewer worker thread...")
    comfyui_previewer.start_worker()
    print("ComfyUIPreviewer worker start requested.")

    try:
        # try ports 7861-7870 until one is free
        port = 7861
        while True:
            try:
                # share=True would attempt to create a public link (not needed here)
                # server_name="0.0.0.0" enables LAN access
                demo_instance.launch(server_name="0.0.0.0", server_port=port, share=False, prevent_thread_lock=True)
                print(f"Gradio UI started at http://127.0.0.1:{port} (or LAN IP)")
                # open local link on success
                webbrowser.open(f"http://127.0.0.1:{port}/")
                break  # success
            except OSError as e:
                if "address already in use" in str(e).lower():
                    print(f"Port {port} already in use, trying next...")
                    port += 1
                    if port > 7870:  # limit retries
                        print("Unable to find a free port in range 7861-7870.")
                        break
                else:
                    print(f"Unexpected OS error while starting Gradio: {e}")
                    break
            except Exception as e:
                print(f"Unexpected error starting Gradio: {e}")
                break
    except Exception as e:
        print(f"Error in luanch_gradio: {e}")


# Use a daemon thread so the worker exits with the main program
gradio_thread = threading.Thread(target=luanch_gradio, args=(demo,), daemon=True)
gradio_thread.start()

# Ensure preview worker stops when the process exits
def cleanup_previewer_on_exit():
    print("Gradio shutting down; stopping ComfyUIPreviewer worker...")
    if comfyui_previewer:
        comfyui_previewer.stop_worker()
    print("ComfyUIPreviewer worker stop requested.")

atexit.register(cleanup_previewer_on_exit)


# Main thread can continue doing other work or just idle
# In plugin context the main thread is ComfyUI itself, so no loop here
# print("Main thread running... press Ctrl+C to exit.")
# try:
#     while True:
#         time.sleep(1)
# except KeyboardInterrupt:
#     print("Received exit signal, shutting down...")
#     # demo.close()  # close Gradio service if needed
#     # cleanup_previewer_on_exit()  # manual cleanup (atexit handles it)
