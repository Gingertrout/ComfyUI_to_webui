"""
ComfyUI_to_webui V2 - Main Gradio Application

This is the entry point for the dynamic Gradio interface.
Currently implementing Phase 3 features.

Completed Features:
Phase 1:
- Load workflow JSON (file upload or selector)
- Parse workflow and extract editable inputs
- Dynamically generate Gradio components from /object_info schemas
- Display organized UI grouped by node type

Phase 2:
- Workflow execution and result retrieval
- Model loaders (checkpoint, LoRA, VAE)
- LoRA strength control
- Result gallery

Phase 3 (Current):
- WebSocket live preview
- Real-time progress monitoring

Future Phases:
- Phase 4: UI polish and grouping enhancements
- Phase 5: Civitai browser, batch processing
"""

import gradio as gr
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Disable Gradio analytics for offline/headless operation
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

# Handle both ComfyUI import and direct execution
if __name__ == "__main__" and __package__ is None:
    # Direct execution - add parent to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ComfyUI_to_webui.core.comfyui_client import ComfyUIClient
    from ComfyUI_to_webui.core.ui_generator import UIGenerator, GeneratedUI
    from ComfyUI_to_webui.core.execution_engine import ExecutionEngine
    from ComfyUI_to_webui.core.result_retriever import ResultRetriever
    from ComfyUI_to_webui.utils.workflow_utils import load_workflow_from_file
    from ComfyUI_to_webui.utils.image_utils import (
        extract_image_and_mask,
        save_pil_image_to_input
    )
    from ComfyUI_to_webui.features.live_preview import ComfyUIPreviewer
    from ComfyUI_to_webui.features import civitai_browser
    from ComfyUI_to_webui.utils.settings import get_setting, set_setting
    from ComfyUI_to_webui.config import (
        COMFYUI_BASE_URL,
        GRADIO_PORTS,
        VERSION,
        PROJECT_NAME,
        PROJECT_DESCRIPTION
    )
else:
    # ComfyUI import - use relative imports
    from .core.comfyui_client import ComfyUIClient
    from .core.ui_generator import UIGenerator, GeneratedUI
    from .core.execution_engine import ExecutionEngine
    from .core.result_retriever import ResultRetriever
    from .utils.workflow_utils import load_workflow_from_file
    from .utils.image_utils import (
        extract_image_and_mask,
        save_pil_image_to_input
    )
    from .features.live_preview import ComfyUIPreviewer
    from .features import civitai_browser
    from .utils.settings import get_setting, set_setting
    from .config import (
        COMFYUI_BASE_URL,
        GRADIO_PORTS,
        VERSION,
        PROJECT_NAME,
        PROJECT_DESCRIPTION
    )

# Photopea Integration Constants
PHOTOPEA_EMBED_HTML = """
<div id="photopea-integration-wrapper" style="height:720px; border:1px solid var(--block-border-color,#444); border-radius:6px; overflow:hidden;">
  <iframe id="photopea-iframe" src="https://www.photopea.com/" style="width:100%;height:100%;border:0;" allow="clipboard-read; clipboard-write"></iframe>
</div>
"""

PHOTOPEA_SEND_JS = """
() => {
    const showError = (message) => {
        console.error('[Photopea Send]', message);
        const buttons = document.querySelectorAll('button');
        for (let btn of buttons) {
            if (btn.textContent.includes('Send to Photopea')) {
                btn.style.background = '#ef4444';
                setTimeout(() => btn.style.background = '', 2000);
                break;
            }
        }
    };

    if (!window.photopeaWindow) {
        const iframe = document.querySelector('#photopea-iframe');
        if (iframe) window.photopeaWindow = iframe.contentWindow;
    }

    if (!window.photopeaWindow) {
        showError("Photopea not ready. Make sure the Photopea accordion is open.");
        return;
    }

    const container = document.querySelector('#image-upload');
    if (!container) {
        showError("Image input field not found");
        return;
    }

    console.log('[Photopea Send] Searching for image in ImageEditor...');

    // Strategy 1: Try to find canvas element
    let sourceCanvas = container.querySelector('canvas');
    if (!sourceCanvas) {
        sourceCanvas = container.querySelector('.image-container canvas');
    }
    if (!sourceCanvas) {
        sourceCanvas = container.querySelector('[data-testid="image"] canvas');
    }

    let dataUrl = null;

    // If canvas found, get data from it
    if (sourceCanvas) {
        console.log('[Photopea Send] Found canvas, extracting image data');
        dataUrl = sourceCanvas.toDataURL('image/png');
    } else {
        // Strategy 2: Try to find img element and convert it to canvas
        console.log('[Photopea Send] No canvas found, looking for img element');
        let imgElement = container.querySelector('img');
        if (!imgElement) {
            imgElement = container.querySelector('.image-container img');
        }
        if (!imgElement) {
            imgElement = container.querySelector('[data-testid="image"] img');
        }

        if (imgElement && imgElement.src) {
            console.log('[Photopea Send] Found img element, converting to canvas');
            // Create a temporary canvas to convert img to data URL
            const tempCanvas = document.createElement('canvas');
            tempCanvas.width = imgElement.naturalWidth || imgElement.width;
            tempCanvas.height = imgElement.naturalHeight || imgElement.height;
            const ctx = tempCanvas.getContext('2d');
            ctx.drawImage(imgElement, 0, 0);
            dataUrl = tempCanvas.toDataURL('image/png');
        }
    }

    if (!dataUrl) {
        console.error('[Photopea Send] No image found. DOM structure:', container.innerHTML.substring(0, 500));
        showError("No image loaded. Upload or generate an image first, then try again.");
        return;
    }

    console.log('[Photopea Send] Image data URL length:', dataUrl.length);
    window.photopeaWindow.postMessage('app.open("' + dataUrl + '", null, true);', "*");
    console.log('[Photopea Send] Image sent successfully');

    // Success feedback (green flash)
    setTimeout(() => {
        const buttons = document.querySelectorAll('button');
        for (let btn of buttons) {
            if (btn.textContent.includes('Send to Photopea')) {
                btn.style.background = '#10b981';
                setTimeout(() => btn.style.background = '', 1500);
                break;
            }
        }
    }, 100);
}
"""

PHOTOPEA_EXPORT_JS = """
() => {
    const showError = (message) => {
        console.error('[Photopea Export]', message);
        alert(message);
        const buttons = document.querySelectorAll('button');
        for (let btn of buttons) {
            if (btn.textContent.includes('Export from Photopea')) {
                btn.style.background = '#ef4444';
                setTimeout(() => btn.style.background = '', 2000);
                break;
            }
        }
    };

    if (!window.photopeaWindow) {
        const iframe = document.querySelector('#photopea-iframe');
        if (iframe) window.photopeaWindow = iframe.contentWindow;
    }

    if (!window.photopeaWindow) {
        showError("Photopea not ready. Make sure the Photopea accordion is open.");
        return null;
    }

    console.log('[Photopea Export] Starting export...');

    // Return a promise that resolves with the image data
    return new Promise((resolve, reject) => {
        let responses = [];
        const handler = (e) => {
            // Photopea sends ArrayBuffer responses, then "done" string
            if (e.data === "done") {
                window.removeEventListener("message", handler);

                if (!responses || !responses[0]) {
                    showError("No image data received from Photopea");
                    reject("No data");
                    return;
                }

                console.log('[Photopea Export] Received data, creating blob...');

                // Convert ArrayBuffer to base64 for Python backend
                const arrayBuffer = responses[0];
                const bytes = new Uint8Array(arrayBuffer);
                let binary = '';
                for (let i = 0; i < bytes.length; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                const base64 = btoa(binary);

                console.log('[Photopea Export] Converted to base64, length:', base64.length);
                console.log('[Photopea Export] ✓ Export complete - returning data to Python backend');

                // Flash button green
                setTimeout(() => {
                    const buttons = document.querySelectorAll('button');
                    for (let btn of buttons) {
                        if (btn.textContent.includes('Export from Photopea')) {
                            btn.style.background = '#10b981';
                            setTimeout(() => btn.style.background = '', 1500);
                            break;
                        }
                    }
                }, 100);

                // Return base64 data
                resolve(base64);
            } else {
                // Collect ArrayBuffer responses
                responses.push(e.data);
                console.log('[Photopea Export] Received data chunk:', e.data.byteLength, 'bytes');
            }
        };

        window.addEventListener("message", handler);

        // Timeout after 10 seconds
        setTimeout(() => {
            window.removeEventListener("message", handler);
            if (responses.length === 0) {
                console.error('[Photopea Export] Timeout - no response from Photopea');
                reject("Timeout");
            }
        }, 10000);

        // Request export from Photopea
        window.photopeaWindow.postMessage('app.activeDocument.saveToOE("png");', "*");
        console.log('[Photopea Export] Export request sent to Photopea');
    });
}
"""


class ComfyUIGradioApp:
    """
    Main Gradio application for ComfyUI_to_webui V2
    """

    def __init__(self):
        """Initialize the application"""
        self.client = ComfyUIClient(COMFYUI_BASE_URL)
        self.ui_generator = UIGenerator(self.client)
        self.execution_engine = ExecutionEngine(self.client)
        self.result_retriever = ResultRetriever(self.client)

        # Initialize live preview (Phase 3)
        self.previewer = ComfyUIPreviewer(
            server_address="127.0.0.1:8188",
            client_id_suffix="v2_workflow",
            min_yield_interval=0.1
        )
        # Start the preview worker thread
        self.previewer.start_worker()

        self.current_workflow: Optional[Dict[str, Any]] = None
        self.current_ui: Optional[GeneratedUI] = None
        self.current_loaders: Dict[str, Dict[str, Any]] = {}  # Track discovered loaders
        self.current_workflow_name: str = "None"  # Track current workflow name

        # Scan for available workflows in ComfyUI workflows directory
        self.workflows_dir = self._find_workflows_directory()
        self.available_workflows = self._scan_workflows()

        # Settings checkpoint file path
        self.settings_checkpoint_file = Path(__file__).parent / "last_successful_settings.json"

        # Image history file path
        self.image_history_file = Path(__file__).parent / "image_history.json"
        self.image_history = self._load_image_history()

    def _find_workflows_directory(self) -> Optional[Path]:
        """Find the ComfyUI workflows directory"""
        # Try relative path from current location
        possible_paths = [
            Path(__file__).parent.parent.parent.parent / "user" / "default" / "workflows",
            Path.home() / ".comfyui" / "workflows",
            Path("/home/oconnorja/Unstable-Diffusion/ComfyUI/user/default/workflows"),
        ]

        for path in possible_paths:
            if path.exists() and path.is_dir():
                return path

        return None

    def _scan_workflows(self) -> Dict[str, str]:
        """
        Scan workflows directory for JSON files

        Returns:
            Dictionary mapping display name to file path
        """
        if self.workflows_dir is None:
            return {}

        workflows = {}
        for json_file in sorted(self.workflows_dir.glob("*.json")):
            # Use filename without extension as display name
            display_name = json_file.stem
            workflows[display_name] = str(json_file)

        return workflows

    # Note: load_workflow_from_file is now imported from utils.workflow_utils

    def discover_loaders_in_workflow(self) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically discover all loader nodes in the current workflow

        Returns:
            Dictionary mapping loader categories to loader info:
            {
                "checkpoint": {"node_id": "3", "class_type": "CheckpointLoaderSimple", "param": "ckpt_name"},
                "unet": {"node_id": "5", "class_type": "UNETLoader", "param": "unet_name"},
                ...
            }
        """
        if not self.current_workflow:
            return {}

        loaders = {}

        # DEBUG: Print all nodes to understand structure
        print("[GradioApp] === ALL NODES IN WORKFLOW ===")
        for node_id, node_data in self.current_workflow.items():
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})
            print(f"  Node {node_id}: {class_type}")

            # Show all top-level keys for lora nodes
            if "lora" in class_type.lower():
                print(f"    [DEBUG] All keys in node: {list(node_data.keys())}")
                if "_meta" in node_data:
                    print(f"    [DEBUG] _meta: {node_data['_meta']}")
                if "widgets_values" in node_data:
                    print(f"    [DEBUG] widgets_values: {node_data['widgets_values']}")

            for param, value in inputs.items():
                # Print all parameters, not just strings
                if isinstance(value, str):
                    display_value = value[:50] if len(str(value)) > 50 else value
                    print(f"    - {param}: \"{display_value}\" (str)")
                elif isinstance(value, (int, float, bool)):
                    print(f"    - {param}: {value} ({type(value).__name__})")
                elif isinstance(value, list):
                    # Links are lists like [node_id, output_index]
                    print(f"    - {param}: {value} (link)")
                else:
                    print(f"    - {param}: {type(value).__name__}")
        print("[GradioApp] === END ALL NODES ===")

        # Common loader node patterns
        LOADER_PATTERNS = {
            "checkpoint": [
                ("CheckpointLoaderSimple", "ckpt_name"),
                ("CheckpointLoader", "ckpt_name"),
            ],
            "unet": [
                ("UNETLoader", "unet_name"),
                ("UnetLoader", "unet_name"),
                ("UnetLoaderGGUF", "unet_name"),  # GGUF quantized UNET models
            ],
            "lora": [
                ("LoraLoader", "lora_name"),
                ("LoraLoaderModelOnly", "lora_name"),
                ("PowerLoraLoader", "lora_name"),
                ("LoraLoaderStacked", "lora_name"),
            ],
            "vae": [
                ("VAELoader", "vae_name"),
            ],
            "clip": [
                ("CLIPLoader", "clip_name"),
                ("CLIPLoaderGGUF", "clip_name"),  # GGUF quantized CLIP models
                ("DualCLIPLoader", "clip_name1"),
            ]
        }

        for node_id, node_data in self.current_workflow.items():
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})

            # Check against known patterns
            for category, patterns in LOADER_PATTERNS.items():
                for pattern_type, param_name in patterns:
                    if class_type == pattern_type and param_name in inputs:
                        # Extract actual value (handle both direct values and links)
                        raw_value = inputs[param_name]
                        if isinstance(raw_value, str):
                            current_value = raw_value
                        elif isinstance(raw_value, list):
                            # This is a link to another node, we can't resolve it
                            # Leave as None so dropdown shows available choices
                            current_value = None
                        else:
                            current_value = None

                        loaders[category] = {
                            "node_id": node_id,
                            "class_type": class_type,
                            "param": param_name,
                            "current_value": current_value
                        }
                        print(f"[GradioApp] Discovered {category} loader: node {node_id}, param={param_name}, value={current_value}")
                        break

            # DYNAMIC DISCOVERY: Catch any loader we missed
            # Look for nodes with "Lora" or "LoRA" in name that have model parameters
            if "lora" not in loaders and ("lora" in class_type.lower() or "LoRA" in class_type):
                lora_param = None
                lora_value = None

                # Special handling for Power Lora Loader (rgthree)
                # It stores LoRAs in _meta.info.unused_widget_values, NOT in inputs!
                if "Power Lora Loader" in class_type:
                    print(f"[GradioApp] Detected Power Lora Loader (node {node_id})")
                    meta = node_data.get("_meta", {})
                    info = meta.get("info", {})
                    widget_values = info.get("unused_widget_values", [])

                    # Capture all LoRA slots (on/off, name, strength)
                    power_loras = []
                    for item in widget_values:
                        if isinstance(item, dict) and "lora" in item:
                            power_loras.append({
                                "lora": item.get("lora"),
                                "enabled": bool(item.get("on")),
                                "strength": float(item.get("strength", 1.0)) if item.get("strength") is not None else 1.0
                            })

                    active_loras = [slot["lora"] for slot in power_loras if slot["enabled"] and slot.get("lora")]

                    if active_loras:
                        # Show the first active LoRA in the dropdown
                        lora_value = active_loras[0]
                        lora_param = "lora_01"  # Power Lora Loader uses lora_01, lora_02, etc.
                        print(f"[GradioApp] Found {len(active_loras)} active LoRAs: {active_loras}")
                        print(f"[GradioApp] Using first active LoRA: {lora_value}")
                    else:
                        print(f"[GradioApp] Power Lora Loader found but no active LoRAs")
                        lora_param = "lora_01"
                        lora_value = None

                    loaders["lora"] = {
                        "node_id": node_id,
                        "class_type": class_type,
                        "param": lora_param,
                        "current_value": lora_value,
                        "is_power_lora": True,
                        "active_loras": active_loras,  # Store all active LoRAs for reference
                        "power_loras": power_loras
                    }
                else:
                    # Standard LoRA loaders - look in inputs
                    for param_name, param_value in inputs.items():
                        # Look for parameters that are strings ending in .safetensors
                        if isinstance(param_value, str) and param_value.endswith(".safetensors"):
                            lora_param = param_name
                            lora_value = param_value
                            print(f"[GradioApp] Found LoRA parameter in {class_type}: {param_name} = {param_value}")
                            break
                        # Also look for parameters that start with "lora" (like lora_01, lora_name, etc.)
                        elif isinstance(param_value, str) and "lora" in param_name.lower():
                            lora_param = param_name
                            lora_value = param_value
                            print(f"[GradioApp] Found LoRA-like parameter in {class_type}: {param_name} = {param_value}")
                            break

                    if lora_param:
                        print(f"[GradioApp] Found LoRA loader: {class_type} with param {lora_param}")
                        loaders["lora"] = {
                            "node_id": node_id,
                            "class_type": class_type,
                            "param": lora_param,
                            "current_value": lora_value
                        }

        print(f"[GradioApp] Discovered loaders: {list(loaders.keys())}")
        for category, info in loaders.items():
            print(f"[GradioApp]   - {category}: {info['class_type']} (node {info['node_id']}, param: {info['param']})")
        return loaders

    def extract_defaults_from_workflow(self) -> Dict[str, Any]:
        """
        Extract default values from the current workflow

        Returns:
            Dictionary with default values for UI fields
        """
        if not self.current_workflow:
            return {}

        defaults = {
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": -1,
            "steps": 20,
            "cfg": 7.0,
            "denoise": 1.0,
            "checkpoint": None,
            "lora": "None",
            "vae": "None"
        }

        for node_id, node_data in self.current_workflow.items():
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})

            # Extract prompts from CLIPTextEncode nodes
            if class_type == "CLIPTextEncode":
                text = inputs.get("text", "")
                node_title = node_data.get("_meta", {}).get("title", "").lower()

                # Guess if this is positive or negative
                is_negative = (
                    "negative" in node_title or
                    any(word in text.lower() for word in ["bad", "ugly", "worst", "low quality", "watermark", "3d", "cg"])
                )

                if is_negative:
                    defaults["negative_prompt"] = text
                else:
                    defaults["positive_prompt"] = text

            # Extract sampling parameters from KSampler nodes
            if class_type in {"KSampler", "KSamplerAdvanced", "SamplerCustom"}:
                if "steps" in inputs:
                    defaults["steps"] = int(inputs["steps"])
                if "cfg" in inputs:
                    defaults["cfg"] = float(inputs["cfg"])
                if "denoise" in inputs:
                    defaults["denoise"] = float(inputs["denoise"])
                # Don't extract seed - keep it at -1 for randomization

            # Extract model selections from discovered loaders
            # (Deprecated - now using self.current_loaders directly)

        # Override with discovered loader values
        for category, loader_info in self.current_loaders.items():
            if category in defaults:
                defaults[category] = loader_info["current_value"]

        return defaults

    def _get_model_choices_for_loader(self, *categories) -> tuple[list, str]:
        """
        Get model choices and current value for discovered loader categories

        Args:
            *categories: Loader categories to check (e.g., "checkpoint", "unet")

        Returns:
            Tuple of (choices_list, current_value)
        """
        # Check which category exists in current loaders
        for category in categories:
            if category in self.current_loaders:
                loader_info = self.current_loaders[category]
                class_type = loader_info["class_type"]
                param = loader_info["param"]
                current_value = loader_info["current_value"]

                # Get available models from ComfyUI
                try:
                    print(f"[GradioApp] Getting models for {category}: {class_type}.{param}")
                    models = self.client.get_available_models(class_type, param)

                    # Fallback for LoRA loaders: If we get 0 models, try standard LoRA loader types
                    if category == "lora" and len(models) == 0:
                        print(f"[GradioApp]   No models found for {class_type}, trying fallback LoRA loaders...")
                        fallback_loaders = [
                            ("LoraLoader", "lora_name"),
                            ("LoraLoaderModelOnly", "lora_name"),
                        ]
                        for fallback_type, fallback_param in fallback_loaders:
                            try:
                                models = self.client.get_available_models(fallback_type, fallback_param)
                                if len(models) > 0:
                                    print(f"[GradioApp]   ✓ Found {len(models)} LoRA models using {fallback_type}")
                                    # Update param to use for injection
                                    loader_info["fallback_type"] = fallback_type
                                    loader_info["fallback_param"] = fallback_param
                                    break
                            except:
                                continue
                    else:
                        print(f"[GradioApp]   Found {len(models)} models")

                    # Add "None" option for optional loaders
                    if category in ["lora", "vae", "clip"]:
                        choices = ["None"] + models
                        # Keep current value if it's in choices, otherwise "None"
                        if current_value and current_value in choices:
                            value = current_value
                        else:
                            value = "None"
                    else:
                        choices = models
                        value = current_value if current_value and current_value in models else (models[0] if models else None)

                    print(f"[GradioApp]   Returning choices: {len(choices)} items, value: {value}")
                    return choices, value
                except Exception as e:
                    print(f"[GradioApp] ERROR getting models for {class_type}: {e}")
                    import traceback
                    traceback.print_exc()

        # No loader found for this category
        print(f"[GradioApp] No loader found for category: {categories}")
        return ["None"], "None"

    def _get_lora_slot_defaults(self, lora_choices: list[str]) -> list[dict[str, Any]]:
        """
        Build default values for up to three LoRA slots (Power Lora Loader)

        Returns:
            List of dicts with keys: enabled, value, strength
        """
        defaults = []
        loader_info = self.current_loaders.get("lora", {})
        power_loras = loader_info.get("power_loras", []) if loader_info.get("is_power_lora") else []

        for idx in range(3):
            slot_default = {
                "enabled": False,
                "value": "None",
                "strength": 1.0
            }

            if power_loras and idx < len(power_loras):
                entry = power_loras[idx]
                slot_default["enabled"] = bool(entry.get("enabled"))
                slot_default["value"] = entry.get("lora") if entry.get("lora") else "None"
                slot_default["strength"] = float(entry.get("strength", 1.0))
            elif not loader_info.get("is_power_lora") and idx == 0:
                # Standard LoRA loader fallback - use the single selection if present
                if loader_info.get("current_value"):
                    slot_default["enabled"] = True
                    slot_default["value"] = loader_info["current_value"]

            # Ensure value is in choices
            if slot_default["value"] not in lora_choices:
                slot_default["value"] = "None"

            defaults.append(slot_default)

        return defaults

    def _get_loader_label(self, *categories) -> str:
        """Get appropriate label for discovered loader"""
        for category in categories:
            if category in self.current_loaders:
                class_type = self.current_loaders[category]["class_type"]
                if "UNET" in class_type or "Unet" in class_type:
                    return "UNET Model"
                elif "Checkpoint" in class_type:
                    return "Checkpoint Model"
                elif "CLIP" in class_type:
                    return "CLIP Model"
        return "Model"

    def generate_ui_from_workflow_path(self, workflow_path: str) -> tuple:
        """
        Generate UI from workflow file path (used by dropdown)

        Args:
            workflow_path: Full path to workflow JSON file

        Returns:
            Tuple of (markdown_summary, positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora1_enabled, lora1, lora1_strength, lora2_enabled, lora2, lora2_strength, lora3_enabled, lora3, lora3_strength, vae)
        """
        if not workflow_path or workflow_path == "None":
            self.current_workflow_name = "None"
            return ("", "", "", -1, 20, 7.0, 1.0, None, False, "None", 1.0, False, "None", 1.0, False, "None", 1.0, "None")

        try:
            # Load workflow
            self.current_workflow = load_workflow_from_file(workflow_path)

            # Track workflow name (extract from path)
            self.current_workflow_name = Path(workflow_path).stem

            # Discover loaders dynamically
            self.current_loaders = self.discover_loaders_in_workflow()

            # Generate UI metadata
            self.current_ui = self.ui_generator.generate_ui_for_workflow(
                self.current_workflow
            )

            # Extract defaults
            defaults = self.extract_defaults_from_workflow()

            # Build markdown representation
            summary = self._build_workflow_summary_markdown()

            # Get available models for discovered loaders
            checkpoint_choices, checkpoint_value = self._get_model_choices_for_loader("checkpoint", "unet")
            lora_choices, _ = self._get_model_choices_for_loader("lora")
            lora_slots = self._get_lora_slot_defaults(lora_choices)
            vae_choices, vae_value = self._get_model_choices_for_loader("vae")

            return (
                summary,
                defaults["positive_prompt"],
                defaults["negative_prompt"],
                defaults["seed"],
                defaults["steps"],
                defaults["cfg"],
                defaults["denoise"],
                gr.update(choices=checkpoint_choices, value=checkpoint_value, label=self._get_loader_label("checkpoint", "unet")),
                lora_slots[0]["enabled"],
                gr.update(choices=lora_choices, value=lora_slots[0]["value"]),
                lora_slots[0]["strength"],
                lora_slots[1]["enabled"],
                gr.update(choices=lora_choices, value=lora_slots[1]["value"]),
                lora_slots[1]["strength"],
                lora_slots[2]["enabled"],
                gr.update(choices=lora_choices, value=lora_slots[2]["value"]),
                lora_slots[2]["strength"],
                gr.update(choices=vae_choices, value=vae_value)
            )

        except Exception as e:
            return (
                f"### ❌ Error Loading Workflow\n\n```\n{str(e)}\n```",
                "", "", -1, 20, 7.0, 1.0,
                gr.update(choices=[], value=None),
                False,
                gr.update(choices=["None"], value="None"),
                1.0,
                False,
                gr.update(choices=["None"], value="None"),
                1.0,
                False,
                gr.update(choices=["None"], value="None"),
                1.0,
                gr.update(choices=["None"], value="None")
            )

    def _build_workflow_summary_markdown(self) -> str:
        """Build markdown summary of workflow and editable parameters"""
        if not self.current_ui:
            return ""

        lines = ["## ✅ Workflow Loaded Successfully\n"]

        # Summary stats
        total_components = len(self.current_ui.components)
        categories = len(self.current_ui.grouped_components)

        lines.append(f"**Total Editable Parameters:** {total_components}  ")
        lines.append(f"**Component Groups:** {categories}\n")

        # Group by category
        for category, components in sorted(self.current_ui.grouped_components.items()):
            # Pretty category names
            category_names = {
                "sampler": "🎨 Samplers",
                "lora_loader": "🎯 LoRA Loaders",
                "checkpoint_loader": "📦 Checkpoint Loaders",
                "unet_loader": "🧠 UNET Loaders",
                "image_input": "🖼️ Image Inputs",
                "video_input": "🎬 Video Inputs",
                "output": "💾 Output Nodes",
                "other": "⚙️ Other Parameters"
            }
            category_title = category_names.get(category, category.replace("_", " ").title())

            lines.append(f"\n### {category_title} ({len(components)})\n")

            # Group by node
            from collections import defaultdict
            nodes = defaultdict(list)
            for comp in components:
                nodes[comp.node_id].append(comp)

            for node_id, node_components in nodes.items():
                # Get node title from first component (safely)
                try:
                    label = getattr(node_components[0].component, 'label', None)
                    if label and " › " in str(label):
                        node_title = str(label).split(" › ")[0]
                    else:
                        node_title = node_id
                except:
                    node_title = node_id

                lines.append(f"**{node_title}** (Node ID: `{node_id}`)")

                for comp in node_components:
                    input_name = comp.input_name
                    value = comp.current_value
                    comp_type = type(comp.component).__name__

                    # Format value nicely
                    if isinstance(value, (int, float)):
                        value_str = str(value)
                    elif isinstance(value, str) and len(value) > 50:
                        value_str = value[:50] + "..."
                    else:
                        value_str = str(value)

                    lines.append(f"- **{input_name}**: `{value_str}` ({comp_type})")

                lines.append("")

        lines.append("\n---\n")
        lines.append("**Note:** Phase 1 demonstrates dynamic UI generation. ")
        lines.append("In Phase 2, these parameters will be editable with actual Gradio components!")

        return "\n".join(lines)

    def generate_ui_from_workflow(self, workflow_file: str) -> tuple:
        """
        Gradio callback: Generate UI when workflow file is uploaded

        Args:
            workflow_file: File path string (Gradio 4.x type="filepath")

        Returns:
            Tuple of (markdown_summary, positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora1_enabled, lora1, lora1_strength, lora2_enabled, lora2, lora2_strength, lora3_enabled, lora3, lora3_strength, vae)
        """
        if not workflow_file:
            self.current_workflow_name = "None"
            return ("", "", "", -1, 20, 7.0, 1.0, None, False, "None", 1.0, False, "None", 1.0, False, "None", 1.0, "None")

        try:
            # Load workflow (auto-converts from workflow format to API format)
            self.current_workflow = load_workflow_from_file(workflow_file)

            # Track workflow name (extract from uploaded file)
            self.current_workflow_name = Path(workflow_file).stem

            # Discover loaders dynamically
            self.current_loaders = self.discover_loaders_in_workflow()

            # Generate UI metadata
            self.current_ui = self.ui_generator.generate_ui_for_workflow(
                self.current_workflow
            )

            # Extract defaults
            defaults = self.extract_defaults_from_workflow()

            # Build markdown representation
            summary = self._build_workflow_summary_markdown()

            # Get available models for discovered loaders
            checkpoint_choices, checkpoint_value = self._get_model_choices_for_loader("checkpoint", "unet")
            lora_choices, _ = self._get_model_choices_for_loader("lora")
            lora_slots = self._get_lora_slot_defaults(lora_choices)
            vae_choices, vae_value = self._get_model_choices_for_loader("vae")

            return (
                summary,
                defaults["positive_prompt"],
                defaults["negative_prompt"],
                defaults["seed"],
                defaults["steps"],
                defaults["cfg"],
                defaults["denoise"],
                gr.update(choices=checkpoint_choices, value=checkpoint_value, label=self._get_loader_label("checkpoint", "unet")),
                lora_slots[0]["enabled"],
                gr.update(choices=lora_choices, value=lora_slots[0]["value"]),
                lora_slots[0]["strength"],
                lora_slots[1]["enabled"],
                gr.update(choices=lora_choices, value=lora_slots[1]["value"]),
                lora_slots[1]["strength"],
                lora_slots[2]["enabled"],
                gr.update(choices=lora_choices, value=lora_slots[2]["value"]),
                lora_slots[2]["strength"],
                gr.update(choices=vae_choices, value=vae_value)
            )

        except Exception as e:
            return (
                f"### ❌ Error Loading Workflow\n\n```\n{str(e)}\n```",
                "", "", -1, 20, 7.0, 1.0,
                gr.update(choices=[], value=None),
                False,
                gr.update(choices=["None"], value="None"),
                1.0,
                False,
                gr.update(choices=["None"], value="None"),
                1.0,
                False,
                gr.update(choices=["None"], value="None"),
                1.0,
                gr.update(choices=["None"], value="None")
            )

    def execute_current_workflow(
        self,
        image_data,
        invert_mask_flag: bool,
        image_data_2,
        positive_prompt: str,
        negative_prompt: str,
        width: float,
        height: float,
        seed: float,
        steps: float,
        cfg: float,
        denoise: float,
        checkpoint: str,
        lora1_enabled: bool,
        lora1: str,
        lora1_strength: float,
        lora2_enabled: bool,
        lora2: str,
        lora2_strength: float,
        lora3_enabled: bool,
        lora3: str,
        lora3_strength: float,
        vae: str
    ) -> tuple[str, list, list, list]:
        """
        Execute the currently loaded workflow with user-provided parameters

        Args:
            image_data: Gradio ImageEditor payload (contains image + mask)
            image_data_2: Second Gradio ImageEditor payload (optional)
            positive_prompt: Positive prompt text
            negative_prompt: Negative prompt text
            width: Image width in pixels
            height: Image height in pixels
            seed: Random seed (-1 for random)
            steps: Number of sampling steps
            cfg: CFG scale value
            denoise: Denoise strength
            checkpoint: Checkpoint model name
            lora1/lora2/lora3: LoRA model names (optional)
            lora*_enabled: Whether each LoRA slot should be active
            lora*_strength: LoRA strength/weight (0.0 to 2.0)
            vae: VAE model name

        Returns:
            Tuple of (status_message, result_images, state_data, history_gallery)
        """
        print("[GradioApp] Execute button clicked")

        if not self.current_workflow:
            print("[GradioApp] No workflow loaded!")
            return "❌ No workflow loaded. Please select a workflow first.", [], None, self.image_history

        try:
            def _process_image_payload(payload, image_prefix: str, mask_prefix: str, label: str):
                if isinstance(payload, dict):
                    print(f"[GradioApp] {label} ImageEditor dict keys: {list(payload.keys())}")

                upload_image, upload_mask = extract_image_and_mask(payload)
                saved_image_path = None
                saved_mask_path = None

                if upload_image:
                    print(f"[GradioApp] {label} upload image size: {upload_image.size}, mode: {upload_image.mode}")
                    if "A" in upload_image.getbands():
                        print(f"[GradioApp] {label} upload image alpha extrema: {upload_image.getchannel('A').getextrema()}")
                if upload_mask:
                    print(f"[GradioApp] {label} upload mask size: {upload_mask.size}, mode: {upload_mask.mode}, extrema: {upload_mask.getextrema()}")

                # If no explicit mask provided but image has alpha, derive mask from alpha channel
                if upload_mask is None and upload_image and upload_image.mode in {"RGBA", "LA"}:
                    alpha = upload_image.getchannel("A")
                    extrema = alpha.getextrema()
                    if extrema and extrema[0] < 255:
                        upload_mask = alpha

                # If we have both, embed mask into image alpha so LoadImage emits mask correctly
                if upload_image and upload_mask:
                    mask_resized = upload_mask.convert("L").resize(upload_image.size)
                    base_rgba = upload_image.convert("RGBA")
                    base_rgba.putalpha(mask_resized)
                    upload_image = base_rgba

                if upload_image:
                    upload_ref = self.client.upload_pil_image(upload_image, filename_prefix=image_prefix)
                    if upload_ref and upload_ref.get("name"):
                        saved_image_path = upload_ref["name"]
                        print(f"[GradioApp] ✓ Uploaded {label.lower()} image: {saved_image_path}")
                    else:
                        # Fallback to saving locally
                        saved_image_path = save_pil_image_to_input(upload_image, prefix=image_prefix)
                        if saved_image_path:
                            print(f"[GradioApp] ✓ Saved {label.lower()} image to ComfyUI input: {saved_image_path}")
                        else:
                            print(f"[GradioApp] ⚠️ Failed to save {label.lower()} image to ComfyUI input directory")

                if upload_mask:
                    mask_ref = self.client.upload_pil_image(upload_mask.convert("L"), filename_prefix=mask_prefix)
                    if mask_ref and mask_ref.get("name"):
                        saved_mask_path = mask_ref["name"]
                        print(f"[GradioApp] ✓ Uploaded {label.lower()} mask: {saved_mask_path}")
                    else:
                        saved_mask_path = save_pil_image_to_input(upload_mask, prefix=mask_prefix)
                        if saved_mask_path:
                            print(f"[GradioApp] ✓ Saved {label.lower()} mask to ComfyUI input: {saved_mask_path}")
                        else:
                            print(f"[GradioApp] ⚠️ Failed to save {label.lower()} mask to ComfyUI input directory")

                return saved_image_path, saved_mask_path

            # Extract image and mask from ImageEditor payloads
            saved_image_path, saved_mask_path = _process_image_payload(
                image_data, "input", "mask", "Input 1"
            )
            saved_image_path_2, saved_mask_path_2 = _process_image_payload(
                image_data_2, "input2", "mask2", "Input 2"
            )

            print(
                "[GradioApp] Injection paths — "
                f"image1: {saved_image_path}, mask1: {saved_mask_path}, "
                f"image2: {saved_image_path_2}, mask2: {saved_mask_path_2}"
            )

            # Build user values dict
            lora_slots = [
                {"name": lora1 if lora1 and lora1 != "None" else None, "enabled": bool(lora1_enabled), "strength": float(lora1_strength)},
                {"name": lora2 if lora2 and lora2 != "None" else None, "enabled": bool(lora2_enabled), "strength": float(lora2_strength)},
                {"name": lora3 if lora3 and lora3 != "None" else None, "enabled": bool(lora3_enabled), "strength": float(lora3_strength)},
            ]

            # Pick the first enabled LoRA as a legacy single selection (for standard loaders)
            first_enabled_lora = next((slot["name"] for slot in lora_slots if slot["enabled"] and slot["name"]), None)

            user_values = {
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "width": int(width),
                "height": int(height),
                "seed": int(seed) if seed >= 0 else None,  # None means randomize
                "steps": int(steps),
                "cfg": float(cfg),
                "denoise": float(denoise),
                "checkpoint": checkpoint if checkpoint else None,
                "lora": first_enabled_lora,
                "loras": lora_slots,
                "lora_strength": float(lora1_strength),  # legacy for standard loaders
                "vae": vae if vae and vae != "None" else None,
                "image_path": saved_image_path,
                "mask_path": saved_mask_path,
                "image_path_2": saved_image_path_2,
                "mask_path_2": saved_mask_path_2
            }

            print(f"[GradioApp] Executing workflow with {len(self.current_workflow)} nodes")
            print(f"[GradioApp] User parameters: {user_values}")

            # Execute workflow with user values and discovered loaders
            # IMPORTANT: Use previewer's client_id so we receive preview images via WebSocket
            status_msg = "🚀 **Submitting workflow to ComfyUI...**"
            exec_result = self.execution_engine.execute_workflow(
                self.current_workflow,
                self.current_ui,
                user_values,
                self.current_loaders,  # Pass discovered loaders for targeted injection
                client_id=self.previewer.client_id  # Use previewer's client_id for preview images
            )

            print(f"[GradioApp] Execution result: success={exec_result.success}, prompt_id={exec_result.prompt_id}")

            if not exec_result.success:
                error_msg = exec_result.error or "Unknown error"
                if exec_result.node_errors:
                    error_details = "\n".join(
                        f"- Node {nid}: {err}"
                        for nid, err in exec_result.node_errors.items()
                    )
                    return f"❌ **Execution Failed**\n\n{error_msg}\n\n**Node Errors:**\n{error_details}", [], None, self.image_history
                return f"❌ **Execution Failed**\n\n{error_msg}", [], None, self.image_history

            # Wait for results
            status_msg = f"⏳ **Executing workflow...**\n\nPrompt ID: `{exec_result.prompt_id}`"
            print(f"[GradioApp] Waiting for results...")

            retrieval_result = self.result_retriever.retrieve_results(
                exec_result.prompt_id,
                exec_result.client_id,
                self.current_workflow,
                timeout=self.client.timeout_config.prompt_execution
            )

            print(f"[GradioApp] Retrieval result: success={retrieval_result.success}")

            if not retrieval_result.success:
                return f"❌ **Result Retrieval Failed**\n\n{retrieval_result.error}", [], None, self.image_history

            # Success!
            num_images = len(retrieval_result.images)
            num_videos = len(retrieval_result.videos)

            status_msg = f"✅ **Generation Complete!**\n\n"
            status_msg += f"- **Images**: {num_images}\n"
            status_msg += f"- **Videos**: {num_videos}\n"
            status_msg += f"- **Prompt ID**: `{exec_result.prompt_id}`"

            # Save settings checkpoint on successful generation
            self.save_settings_checkpoint(
                self.current_workflow_name,
                positive_prompt,
                negative_prompt,
                width,
                height,
                seed,
                steps,
                cfg,
                denoise,
                checkpoint,
                lora1_enabled,
                lora1,
                lora1_strength,
                lora2_enabled,
                lora2,
                lora2_strength,
                lora3_enabled,
                lora3,
                lora3_strength,
                vae
            )

            # Return images for gallery and state
            all_results = retrieval_result.images + retrieval_result.videos

            # Add to image history
            self.add_to_image_history(all_results)

            return status_msg, all_results, None, self.image_history

        except Exception as e:
            return f"❌ **Unexpected Error**\n\n```\n{str(e)}\n```", [], None, self.image_history

    def interrupt_generation(self) -> str:
        """
        Interrupt/stop the current generation

        Returns:
            Status message
        """
        try:
            print("[GradioApp] Interrupt requested by user")
            success = self.client.interrupt()

            if success:
                return "⏹️ **Generation Interrupted**\n\nThe current generation has been stopped."
            else:
                return "⚠️ **Interrupt Failed**\n\nCould not interrupt the generation."

        except Exception as e:
            return f"❌ **Interrupt Error**\n\n```\n{str(e)}\n```"

    def get_preview_update(self):
        """
        Get the latest preview image and status (non-generator version for polling)

        Returns:
            Tuple of (image, status_text)
        """
        import time

        # Debug: Print every 50th call to avoid log spam
        if not hasattr(self, '_preview_call_count'):
            self._preview_call_count = 0
        self._preview_call_count += 1
        if self._preview_call_count % 50 == 1:
            print(f"[GradioApp] Preview update called (#{self._preview_call_count}), ws_status: {self.previewer.ws_connection_status}")

        # Get current preview image from the previewer
        preview_image = self.previewer.latest_preview_image

        # Build status message
        with self.previewer.active_prompt_lock:
            current_node = self.previewer.active_prompt_info.get("current_executing_node")
            progress_value = self.previewer.active_prompt_info.get("progress_value")
            progress_max = self.previewer.active_prompt_info.get("progress_max")

        status_parts = []

        if preview_image:
            status_parts.append(f"Last update: {time.strftime('%H:%M:%S')}")
        else:
            status_parts.append("Waiting for preview...")

        if current_node:
            status_parts.append(f"Node: {current_node}")

        if progress_value is not None and progress_max is not None:
            status_parts.append(f"Progress: {progress_value}/{progress_max}")

        status_parts.append(f"Connection: {self.previewer.ws_connection_status}")

        status_text = " | ".join(status_parts)

        return preview_image, status_text

    def send_gallery_to_input(self, gallery_data, state_data):
        """
        Send gallery image to input field for iterative editing with auto-dimension detection

        Args:
            gallery_data: Gallery data from Gradio (list of results)
            state_data: State variable tracking results

        Returns:
            Tuple of (image, width, height) to populate input field and dimension controls
        """
        from PIL import Image

        print(f"[GradioApp] Gallery data: {gallery_data}")
        print(f"[GradioApp] State data: {state_data}")

        def resolve_image(obj):
            """
            Resolve an image from mixed gallery/state formats.
            Returns either a PIL.Image.Image or a filesystem/URL string.
            """
            if obj is None:
                return None

            if isinstance(obj, Image.Image):
                return obj

            # Handle lists/tuples by checking the first meaningful entry
            if isinstance(obj, (list, tuple)):
                for entry in obj:
                    resolved = resolve_image(entry)
                    if resolved is not None:
                        return resolved
                return None

            # Handle dict payloads (Gradio file data or our own structures)
            if isinstance(obj, dict):
                # Some payloads nest under the "image" key
                if "image" in obj:
                    resolved = resolve_image(obj.get("image"))
                    if resolved is not None:
                        return resolved

                # Common fields for file-like objects
                for key in ("path", "name", "url"):
                    val = obj.get(key)
                    if isinstance(val, str) and val:
                        return val

                return None

            if isinstance(obj, str):
                return obj

            return None

        # Try state data first (from last generation)
        data_to_use = state_data if state_data else gallery_data

        if not data_to_use:
            print("[GradioApp] No image data available")
            return None, 512, 512

        try:
            resolved = resolve_image(data_to_use)
            if resolved is None and gallery_data:
                resolved = resolve_image(gallery_data)

            if resolved is None:
                print("[GradioApp] Could not resolve image path/object from data")
                return None, 512, 512

            if isinstance(resolved, Image.Image):
                pil_image = resolved
            else:
                print(f"[GradioApp] Resolved image path: {resolved}")
                pil_image = Image.open(resolved)

            # Auto-detect dimensions from image
            if pil_image:
                img_width, img_height = pil_image.size
                print(f"[GradioApp] Auto-detected dimensions: {img_width}x{img_height}")
                target_height = min(max(img_height, 512), 1400)
                return gr.update(value=pil_image, height=target_height), img_width, img_height

        except Exception as e:
            print(f"[GradioApp] Error: {e}")
            import traceback
            traceback.print_exc()

        return gr.update(value=None), 512, 512

    def save_settings_checkpoint(
        self,
        workflow_name: str,
        positive_prompt: str,
        negative_prompt: str,
        width: float,
        height: float,
        seed: float,
        steps: float,
        cfg: float,
        denoise: float,
        checkpoint: str,
        lora1_enabled: bool,
        lora1: str,
        lora1_strength: float,
        lora2_enabled: bool,
        lora2: str,
        lora2_strength: float,
        lora3_enabled: bool,
        lora3: str,
        lora3_strength: float,
        vae: str
    ):
        """
        Save current settings to checkpoint file

        Args:
            All current UI values (sampling/model values are accepted for compatibility but not persisted)
        """
        import json
        from datetime import datetime

        # Only persist prompts and dimensions to avoid overriding sampling/model selections on restore
        settings = {
            "saved_at": datetime.now().isoformat(),
            "workflow_name": workflow_name,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "width": int(width),
            "height": int(height)
        }

        try:
            with open(self.settings_checkpoint_file, 'w') as f:
                json.dump(settings, f, indent=2)
            print("[GradioApp] ✓ Settings saved (sampling/model params skipped)")
            print(f"[GradioApp] ✓ Settings saved: pos_prompt={settings['positive_prompt'][:50]}...")
        except Exception as e:
            print(f"[GradioApp] Failed to save settings: {e}")

    def restore_settings_checkpoint(self):
        """
        Legacy workflow restore hook (kept for compatibility, no longer used to switch workflows)
        """
        import json

        if not self.settings_checkpoint_file.exists():
            print("[GradioApp] No saved settings found")
            return "None", False

        try:
            with open(self.settings_checkpoint_file, 'r') as f:
                settings = json.load(f)

            print(f"[GradioApp] ✓ Restoring settings from {settings['saved_at']}")

            # Return workflow name and set restore mode to True
            return settings.get("workflow_name", "None"), True

        except Exception as e:
            print(f"[GradioApp] Failed to restore settings: {e}")
            return "None", False

    def restore_settings_checkpoint_step2(self):
        """
        Restore settings from checkpoint file - Step 2: Restore parameters
        (used directly for parameter restoration without changing workflow)

        Sampling-related controls (seed/steps/cfg/denoise) are intentionally left unchanged.
        Model selections (checkpoint/LoRA/VAE) are also left unchanged.

        Returns:
            Tuple of parameter settings to override workflow defaults
        """
        import json

        if not self.settings_checkpoint_file.exists():
            return (
                "", "", 512, 512,
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(),  # checkpoint
                gr.update(), gr.update(), gr.update(),  # lora1 enabled, value, strength
                gr.update(), gr.update(), gr.update(),  # lora2 enabled, value, strength
                gr.update(), gr.update(), gr.update(),  # lora3 enabled, value, strength
                gr.update()  # vae
            )

        try:
            with open(self.settings_checkpoint_file, 'r') as f:
                settings = json.load(f)

            print(f"[GradioApp] ✓ Restored prompts and dimensions from checkpoint (sampling/model params left untouched)")

            # Step 2: Return all parameters (workflow already loaded in step 1)
            return (
                settings.get("positive_prompt", ""),
                settings.get("negative_prompt", ""),
                settings.get("width", 512),
                settings.get("height", 512),
                gr.update(),  # keep current seed
                gr.update(),  # keep current steps
                gr.update(),  # keep current cfg
                gr.update(),  # keep current denoise
                gr.update(),  # keep current checkpoint
                gr.update(),  # keep current lora1 enabled
                gr.update(),  # keep current lora1
                gr.update(),  # keep current lora1 strength
                gr.update(),  # keep current lora2 enabled
                gr.update(),  # keep current lora2
                gr.update(),  # keep current lora2 strength
                gr.update(),  # keep current lora3 enabled
                gr.update(),  # keep current lora3
                gr.update(),  # keep current lora3 strength
                gr.update()   # keep current vae
            )

        except Exception as e:
            print(f"[GradioApp] Failed to restore parameters: {e}")
            return (
                "", "", 512, 512,
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(),  # checkpoint
                gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(),
                gr.update()
            )

    def restore_settings_parameters(self):
        """
        Restore saved parameters without changing the current workflow selection.

        Sampling and model controls remain untouched to avoid overriding ComfyUI defaults.

        Returns:
            Tuple of parameter settings to populate UI controls
        """
        return self.restore_settings_checkpoint_step2()

    def _load_image_history(self) -> list:
        """
        Load image history from file

        Returns:
            List of image paths in history
        """
        import json

        if not self.image_history_file.exists():
            return []

        try:
            with open(self.image_history_file, 'r') as f:
                history = json.load(f)
            print(f"[GradioApp] ✓ Loaded {len(history)} images from history")
            return history
        except Exception as e:
            print(f"[GradioApp] Failed to load image history: {e}")
            return []

    def _save_image_history(self):
        """
        Save image history to file
        """
        import json

        try:
            with open(self.image_history_file, 'w') as f:
                json.dump(self.image_history, f, indent=2)
            print(f"[GradioApp] ✓ Saved {len(self.image_history)} images to history")
        except Exception as e:
            print(f"[GradioApp] Failed to save image history: {e}")

    def add_to_image_history(self, image_paths: list):
        """
        Add new images to history

        Args:
            image_paths: List of image file paths to add
        """
        if not image_paths:
            return

        # Add new images to the front of the history (most recent first)
        for path in reversed(image_paths):
            if path not in self.image_history:
                self.image_history.insert(0, path)

        # Limit history to 100 images
        self.image_history = self.image_history[:100]

        # Save to file
        self._save_image_history()

        print(f"[GradioApp] ✓ Added {len(image_paths)} images to history (total: {len(self.image_history)})")


    def send_history_to_input(self, history_gallery, history_selection):
        """
        Send selected history image to input field (with gallery fallback)

        Args:
            history_gallery: Current gallery contents from the client
            history_selection: Gallery selection event data

        Returns:
            Tuple of (image, width, height)
        """
        print(f"[GradioApp] History selection: {history_selection}")

        # Reuse the gallery helper so we can fall back to the gallery contents
        return self.send_gallery_to_input(history_gallery, history_selection)

    def process_photopea_export(self, base64_data: str):
        """
        Process exported image data from Photopea

        Args:
            base64_data: Base64-encoded PNG image data from Photopea

        Returns:
            PIL Image for the ImageEditor component
        """
        import base64
        import io
        from PIL import Image

        if not base64_data or base64_data == "null" or base64_data == "":
            print("[GradioApp] No Photopea data received")
            return None

        try:
            print(f"[GradioApp] Processing Photopea export ({len(base64_data)} chars)")

            # Decode base64 to bytes
            image_bytes = base64.b64decode(base64_data)
            print(f"[GradioApp] Decoded {len(image_bytes)} bytes")

            # Convert to PIL Image
            pil_image = Image.open(io.BytesIO(image_bytes))
            print(f"[GradioApp] ✓ Photopea image loaded: {pil_image.size[0]}x{pil_image.size[1]}")

            return pil_image

        except Exception as e:
            print(f"[GradioApp] Error processing Photopea export: {e}")
            import traceback
            traceback.print_exc()
            return None

    def create_interface(self) -> gr.Blocks:
        """
        Create the main Gradio interface

        Returns:
            Gradio Blocks application
        """
        # Load theme mode preference (light, dark, or system)
        saved_theme_mode = get_setting("theme_mode", "system")

        with gr.Blocks(
            title=PROJECT_NAME,
            theme=gr.themes.Default(),
            analytics_enabled=False,
            js=f"""
            function() {{
                // Set initial theme mode from saved preference
                const themeMode = '{saved_theme_mode}';
                const gradioContainer = document.querySelector('.gradio-container');
                if (gradioContainer) {{
                    if (themeMode === 'dark') {{
                        gradioContainer.classList.add('dark');
                    }} else if (themeMode === 'light') {{
                        gradioContainer.classList.remove('dark');
                    }} else {{
                        // System - follow OS preference
                        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {{
                            gradioContainer.classList.add('dark');
                        }} else {{
                            gradioContainer.classList.remove('dark');
                        }}
                    }}
                }}
            }}
            """
        ) as app:
            # Header
            gr.Markdown(f"""
            # {PROJECT_NAME} 🚀
            {PROJECT_DESCRIPTION}

            ---

            """)

            # Workflow selection
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 1. Select Workflow")

                    # Dropdown for saved workflows
                    if self.available_workflows:
                        workflow_dropdown = gr.Dropdown(
                            label=f"Saved Workflows ({len(self.available_workflows)} found)",
                            choices=["None"] + list(self.available_workflows.keys()),
                            value="None",
                            interactive=True
                        )
                        gr.Markdown(f"📁 **Workflows directory:** `{self.workflows_dir}`")
                    else:
                        gr.Markdown("⚠️ **No workflows found** in ComfyUI workflows directory")
                        workflow_dropdown = gr.Dropdown(
                            label="Saved Workflows",
                            choices=["None"],
                            value="None",
                            interactive=False
                        )

                    gr.Markdown("**— OR —**")

                    # File upload option
                    workflow_file = gr.File(
                        label="Upload Workflow JSON",
                        file_types=[".json"],
                        type="filepath"  # Gradio 4.x
                    )

                    gr.Markdown("""
                    **Tip:** Workflows are auto-converted from graph format to API format.
                    Both ComfyUI workflow JSON and API JSON formats are supported.
                    """)

            # Editable Parameters Section
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 2. Edit Parameters")

                    # Common editable parameters
                    with gr.Accordion("🖼️ Image Input 1 (Optional)", open=True):
                        gr.Markdown("Upload an image for img2img, inpainting, or editing in Photopea")
                        image_upload = gr.ImageEditor(
                            label="Input Image",
                            type="pil",
                            image_mode="RGBA",
                            sources=["upload", "clipboard"],
                            elem_id="image-upload",
                            height=720,
                            brush=gr.Brush(default_size=56, color_mode="fixed", colors=["#ffffffff"], default_color="#ffffffff"),
                            eraser=gr.Eraser(default_size=48),
                            layers=True,
                            transforms=(),
                            canvas_size=None
                        )
                        invert_mask = gr.Checkbox(
                            label="Invert Mask (white = protect)",
                            value=False,
                            interactive=True,
                            info="Toggle if your workflow expects inverted masks"
                        )

                    with gr.Accordion("🖼️ Image Input 2 (Optional)", open=False):
                        gr.Markdown("Upload a second image for workflows that accept multiple image inputs")
                        image_upload_2 = gr.ImageEditor(
                            label="Second Input Image",
                            type="pil",
                            image_mode="RGBA",
                            sources=["upload", "clipboard"],
                            elem_id="image-upload-2",
                            height=720,
                            brush=gr.Brush(default_size=56, color_mode="fixed", colors=["#ffffffff"], default_color="#ffffffff"),
                            eraser=gr.Eraser(default_size=48),
                            layers=True,
                            transforms=(),
                            canvas_size=None
                        )

                    with gr.Accordion("🎨 Models (Dynamic)", open=True):
                        gr.Markdown("""
                        **Note:** Model dropdowns populate dynamically based on the loaded workflow.
                        Different workflows may use different model loaders (Checkpoint, UNET, CLIP, etc.).
                        """)

                        # These will be populated dynamically when workflow loads
                        # For now, create generic dropdowns that will be updated
                        checkpoint = gr.Dropdown(
                            label="Checkpoint / UNET",
                            choices=[],
                            value=None,
                            allow_custom_value=True,
                            interactive=True,
                            visible=True
                        )
                        gr.Markdown("Power Lora Loader slots (up to three):")
                        with gr.Row():
                            lora1_enabled = gr.Checkbox(
                                label="Enable LoRA 1",
                                value=False,
                                interactive=True,
                                visible=True
                            )
                            lora1 = gr.Dropdown(
                                label="LoRA 1",
                                choices=["None"],
                                value="None",
                                allow_custom_value=True,
                                interactive=True,
                                visible=True
                            )
                            lora1_strength = gr.Slider(
                                label="Strength 1",
                                minimum=0.0,
                                maximum=2.0,
                                value=1.0,
                                step=0.05,
                                interactive=True,
                                visible=True
                            )
                        with gr.Row():
                            lora2_enabled = gr.Checkbox(
                                label="Enable LoRA 2",
                                value=False,
                                interactive=True,
                                visible=True
                            )
                            lora2 = gr.Dropdown(
                                label="LoRA 2",
                                choices=["None"],
                                value="None",
                                allow_custom_value=True,
                                interactive=True,
                                visible=True
                            )
                            lora2_strength = gr.Slider(
                                label="Strength 2",
                                minimum=0.0,
                                maximum=2.0,
                                value=1.0,
                                step=0.05,
                                interactive=True,
                                visible=True
                            )
                        with gr.Row():
                            lora3_enabled = gr.Checkbox(
                                label="Enable LoRA 3",
                                value=False,
                                interactive=True,
                                visible=True
                            )
                            lora3 = gr.Dropdown(
                                label="LoRA 3",
                                choices=["None"],
                                value="None",
                                allow_custom_value=True,
                                interactive=True,
                                visible=True
                            )
                            lora3_strength = gr.Slider(
                                label="Strength 3",
                                minimum=0.0,
                                maximum=2.0,
                                value=1.0,
                                step=0.05,
                                interactive=True,
                                visible=True
                            )
                        vae = gr.Dropdown(
                            label="VAE (Optional)",
                            choices=["None"],
                            value="None",
                            allow_custom_value=True,
                            interactive=True,
                            visible=True
                        )

                    with gr.Accordion("🎲 Sampling Parameters", open=True):
                        with gr.Row():
                            width = gr.Number(
                                label="Width",
                                value=512,
                                minimum=64,
                                maximum=4096,
                                step=64,
                                precision=0,
                                elem_id="width-input"
                            )
                            height = gr.Number(
                                label="Height",
                                value=512,
                                minimum=64,
                                maximum=4096,
                                step=64,
                                precision=0,
                                elem_id="height-input"
                            )
                        with gr.Row():
                            seed = gr.Number(
                                label="Seed (-1 for random)",
                                value=-1,
                                precision=0
                            )
                            steps = gr.Slider(
                                label="Steps",
                                minimum=1,
                                maximum=150,
                                value=20,
                                step=1
                            )
                        with gr.Row():
                            cfg = gr.Slider(
                                label="CFG Scale",
                                minimum=1.0,
                                maximum=30.0,
                                value=7.0,
                                step=0.5
                            )
                            denoise = gr.Slider(
                                label="Denoise",
                                minimum=0.0,
                                maximum=1.0,
                                value=1.0,
                                step=0.05
                            )

                    with gr.Accordion("📝 Prompts", open=True):
                        positive_prompt = gr.Textbox(
                            label="Positive Prompt",
                            placeholder="Enter positive prompt...",
                            lines=3,
                            value=""
                        )
                        negative_prompt = gr.Textbox(
                            label="Negative Prompt",
                            placeholder="Enter negative prompt...",
                            lines=2,
                            value=""
                        )
                        # Restore last successful settings button (does not change workflow)
                        restore_settings_btn = gr.Button(
                            "🔄 Restore Last Successful Settings",
                            variant="secondary",
                            size="sm"
                        )
                        gr.Markdown("*Restores prompts and dimensions from the last successful generation without changing the selected workflow. Sampling and model selections are left as-is.*")

                    # Photopea Integration (Phase 3)
                    with gr.Accordion("🎨 Photopea Editor", open=False):
                        gr.Markdown("""
                        **Photopea** is a free online image editor for masking, inpainting, and image editing.
                        - Upload an image first
                        - Click **Send to Photopea** to edit it
                        - Make your edits in Photopea
                        - Click **Export from Photopea** to use the edited image
                        """)

                        # Photopea iframe
                        photopea_panel = gr.HTML(
                            PHOTOPEA_EMBED_HTML,
                            elem_id="photopea-embed"
                        )

                        # Photopea control buttons
                        with gr.Row():
                            photopea_send_btn = gr.Button(
                                "📤 Send to Photopea",
                                variant="secondary"
                            )
                            photopea_export_btn = gr.Button(
                                "📥 Export from Photopea",
                                variant="primary"
                            )

                        # Hidden state to hold Photopea export data
                        photopea_data = gr.Textbox(
                            value="",
                            visible=False,
                            elem_id="photopea-data-hidden"
                        )

                    # Workflow summary (read-only info)
                    with gr.Accordion("ℹ️ Workflow Details", open=False):
                        dynamic_ui_container = gr.Markdown(
                            value="",
                            label="Workflow Analysis"
                        )

            # Hidden state for restore settings mode (top-level)
            restore_mode = gr.State(value=False)

            # Results section
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 3. Results")

                    # Tabbed interface for Live Preview and Final Results
                    with gr.Tabs():
                        with gr.Tab("🔴 Live Preview"):
                            live_preview_image = gr.Image(
                                label="Live Preview",
                                type="pil",
                                interactive=False,
                                height=512
                            )
                            with gr.Row():
                                generate_btn = gr.Button(
                                    "🚀 Generate",
                                    variant="primary",
                                    scale=3
                                )
                                stop_btn = gr.Button(
                                    "⏹️ Stop",
                                    variant="stop",
                                    scale=1
                                )
                            live_preview_status = gr.Textbox(
                                label="Preview Status",
                                value="Waiting for generation...",
                                interactive=False,
                                max_lines=1
                            )
                            execution_status = gr.Markdown(
                                value="",
                                label="Status"
                            )

                        with gr.Tab("✅ Final Results"):
                            gr.Markdown("### Current Generation")
                            result_gallery = gr.Gallery(
                                label="Generated Images/Videos",
                                show_label=False,
                                columns=3,
                                object_fit="contain",
                                height="auto",
                                elem_id="result-gallery"
                            )

                            # Hidden state to track selected gallery image
                            selected_gallery_image = gr.State(value=None)

                            # Button to send result back to input for iterative editing
                            send_to_input_btn = gr.Button(
                                "📤 Use Result as Input",
                                variant="secondary",
                                size="sm"
                            )

                            gr.Markdown("---")
                            gr.Markdown("### Image History")
                            gr.Markdown("*Click an image to select it, then use the buttons below*")

                            history_gallery = gr.Gallery(
                                label="Image History (100 most recent)",
                                show_label=True,
                                columns=4,
                                object_fit="contain",
                                height="auto",
                                value=[],  # Load on page load to avoid threading issues
                                elem_id="history-gallery"
                            )

                            # Hidden state to track selected history image
                            selected_history_image = gr.State(value=None)

                            # Buttons to send history selection
                            with gr.Row():
                                history_to_input_btn = gr.Button(
                                    "📤 Send to Input",
                                    variant="secondary",
                                    size="sm"
                                )
                                history_to_photopea_btn = gr.Button(
                                    "🎨 Send to Photopea",
                                    variant="secondary",
                                    size="sm"
                                )

                        with gr.Tab("🌐 Civitai Browser"):
                            gr.Markdown("### Browse & Download Models from Civitai")

                            with gr.Row():
                                civitai_api_key = gr.Textbox(
                                    label="Civitai API Key (optional)",
                                    value=get_setting("civitai_api_key", ""),
                                    type="password",
                                    placeholder="Paste API key or leave blank"
                                )
                                civitai_save_key_btn = gr.Button("Save Key", variant="secondary")

                            civitai_key_status = gr.Markdown(visible=False)

                            with gr.Row():
                                civitai_query = gr.Textbox(
                                    label="Search",
                                    placeholder="Model name, tag, etc."
                                )
                                civitai_type = gr.Dropdown(
                                    label="Model Type",
                                    choices=["", "Checkpoint", "LORA", "LoCon", "TextualInversion", "VAE", "Controlnet"],
                                    value=""
                                )

                            with gr.Row():
                                civitai_sort = gr.Dropdown(
                                    label="Sort By",
                                    choices=["Highest Rated", "Most Downloaded", "Newest"],
                                    value=get_setting("civitai_sort", "Highest Rated")
                                )
                                civitai_nsfw = gr.Dropdown(
                                    label="NSFW",
                                    choices=["Hide", "Show", "Only"],
                                    value=get_setting("civitai_nsfw", "Hide")
                                )
                                civitai_search_btn = gr.Button("🔍 Search", variant="primary")

                            civitai_search_status = gr.Markdown(visible=False)
                            civitai_results_state = gr.State(value=[])

                            civitai_results_dropdown = gr.Dropdown(
                                label="Search Results",
                                choices=[],
                                value=None
                            )
                            civitai_results_gallery = gr.Gallery(
                                label="Search Results",
                                show_label=False,
                                columns=3,
                                height=320,
                                visible=False,
                                elem_id="civitai-results-gallery"
                            )

                            civitai_model_details = gr.Markdown(visible=False)
                            civitai_preview_gallery = gr.Gallery(
                                label="Preview Images",
                                visible=False,
                                columns=3,
                                height=300
                            )

                            with gr.Row():
                                civitai_version_dropdown = gr.Dropdown(
                                    label="Versions",
                                    choices=[],
                                    value=None,
                                    visible=False
                                )
                                civitai_file_dropdown = gr.Dropdown(
                                    label="Files",
                                    choices=[],
                                    value=None,
                                    visible=False
                                )

                            civitai_target_dir = gr.Textbox(
                                label="Download Directory",
                                value="",
                                placeholder="Auto-suggested based on model type"
                            )

                            civitai_download_btn = gr.Button(
                                "⬇️ Download Selected File",
                                variant="primary"
                            )

                            civitai_download_status = gr.Markdown(visible=False)

                        with gr.Tab("⚙️ Settings"):
                            gr.Markdown("### Application Settings")

                            gr.Markdown("#### Theme Mode")
                            gr.Markdown("Choose between light mode, dark mode, or follow your system preference")

                            theme_mode = gr.Dropdown(
                                label="Theme",
                                choices=["Light", "Dark", "System"],
                                value=saved_theme_mode.capitalize() if saved_theme_mode else "System",
                                elem_id="theme-mode-selector",
                                interactive=True
                            )

                            theme_status = gr.Markdown(
                                value="",
                                visible=False
                            )

            # Info section
            with gr.Row():
                gr.Markdown(f"""
                ---
                This is **ComfyUI_to_webui V2**

                **Development Info:**
                - Branch: `v2-dynamic-rewrite`
                - ComfyUI Server: {COMFYUI_BASE_URL}
                """)
                # Ensure galleries default to newest at the start and allow scrolling back
                gr.HTML(
                    """
                    <style>
                        /* Ensure all galleries are left-aligned and fully scrollable */
                        #result-gallery [data-testid="gallery"],
                        #history-gallery [data-testid="gallery"],
                        #civitai-results-gallery [data-testid="gallery"] {
                            justify-content: flex-start !important;
                            overflow-x: auto !important;
                        }
                        #result-gallery [data-testid="gallery"] .grid-container,
                        #history-gallery [data-testid="gallery"] .grid-container,
                        #civitai-results-gallery [data-testid="gallery"] .grid-container {
                            justify-content: flex-start !important;
                            width: 100% !important;
                            margin: 0 !important;
                        }
                        /* Target Gradio's thumbnail container explicitly */
                        .thumbnails.scroll-hide {
                            justify-content: flex-start !important;
                            overflow-x: auto !important;
                            width: 100% !important;
                        }
                    </style>
                    <script>
                    (function() {
                        const snapThumbnails = () => {
                            document.querySelectorAll('.thumbnails.scroll-hide').forEach((el) => {
                                el.style.overflowX = 'auto';
                                el.dir = 'ltr';
                                el.scrollLeft = 0;
                            });
                        };
                        if (document.readyState === "complete" || document.readyState === "interactive") {
                            snapThumbnails();
                        } else {
                            window.addEventListener("DOMContentLoaded", snapThumbnails);
                        }
                        setTimeout(snapThumbnails, 300);
                        setTimeout(snapThumbnails, 900);
                    })();
                    </script>
                    """,
                    visible=False,
                    elem_id="gallery-scroll-helper"
                )

            # Wire up event handlers
            # Dropdown selection - populate defaults when workflow is selected
            def on_dropdown_change(workflow_name, is_restore_mode):
                if workflow_name == "None" or not workflow_name:
                    return (
                        "", "", "",
                        512, 512,
                        -1, 20, 7.0, 1.0,
                        gr.update(choices=[], value=None),
                        False, gr.update(choices=["None"], value="None"), 1.0,
                        False, gr.update(choices=["None"], value="None"), 1.0,
                        False, gr.update(choices=["None"], value="None"), 1.0,
                        gr.update(choices=["None"], value="None"),
                        False
                    )

                workflow_path = self.available_workflows.get(workflow_name)
                result = self.generate_ui_from_workflow_path(workflow_path)

                # If in restore mode, override with saved settings
                if is_restore_mode:
                    print("[GradioApp] Restore mode active - applying saved settings after workflow load")
                    saved_settings = self.restore_settings_checkpoint_step2()
                    print(f"[GradioApp] Saved settings: width={saved_settings[2]}, height={saved_settings[3]}")
                    print(f"[GradioApp] Saved settings: pos_prompt={saved_settings[0][:50]}...")
                    # Replace workflow defaults with saved settings
                    result = (
                        result[0],  # Keep workflow summary
                        saved_settings[0],  # positive_prompt
                        saved_settings[1],  # negative_prompt
                        saved_settings[2],  # width
                        saved_settings[3],  # height
                        saved_settings[4],  # seed
                        saved_settings[5],  # steps
                        saved_settings[6],  # cfg
                        saved_settings[7],  # denoise
                        saved_settings[8],  # checkpoint
                        saved_settings[9],  # lora1 enabled
                        saved_settings[10], # lora1
                        saved_settings[11], # lora1 strength
                        saved_settings[12], # lora2 enabled
                        saved_settings[13], # lora2
                        saved_settings[14], # lora2 strength
                        saved_settings[15], # lora3 enabled
                        saved_settings[16], # lora3
                        saved_settings[17], # lora3 strength
                        saved_settings[18], # vae
                        False  # Reset restore mode
                    )
                    print(f"[GradioApp] Result tuple: width={result[3]}, height={result[4]}")
                else:
                    # Normal workflow loading - INSERT width, height at correct position
                    # result = (summary, pos_prompt, neg_prompt, seed, steps, cfg, denoise, checkpoint, lora1_enabled, lora1, lora1_strength, lora2_enabled, lora2, lora2_strength, lora3_enabled, lora3, lora3_strength, vae)
                    # outputs = (summary, pos_prompt, neg_prompt, width, height, seed, steps, cfg, denoise, checkpoint, lora1_enabled, lora1, lora1_strength, lora2_enabled, lora2, lora2_strength, lora3_enabled, lora3, lora3_strength, vae, restore_mode)
                    result = (
                        result[0],  # summary
                        result[1],  # positive_prompt
                        result[2],  # negative_prompt
                        512,        # width (default)
                        512,        # height (default)
                        result[3],  # seed
                        result[4],  # steps
                        result[5],  # cfg
                        result[6],  # denoise
                        result[7],  # checkpoint
                        result[8],  # lora1 enabled
                        result[9],  # lora1
                        result[10], # lora1 strength
                        result[11], # lora2 enabled
                        result[12], # lora2
                        result[13], # lora2 strength
                        result[14], # lora3 enabled
                        result[15], # lora3
                        result[16], # lora3 strength
                        result[17], # vae
                        False       # restore_mode
                    )

                return result

            workflow_dropdown.change(
                fn=on_dropdown_change,
                inputs=[workflow_dropdown, restore_mode],
                outputs=[
                    dynamic_ui_container, positive_prompt, negative_prompt, width, height,
                    seed, steps, cfg, denoise, checkpoint,
                    lora1_enabled, lora1, lora1_strength,
                    lora2_enabled, lora2, lora2_strength,
                    lora3_enabled, lora3, lora3_strength,
                    vae, restore_mode
                ]
            )

            # File upload - populate defaults when workflow is uploaded
            workflow_file.change(
                fn=self.generate_ui_from_workflow,
                inputs=[workflow_file],
                outputs=[
                    dynamic_ui_container, positive_prompt, negative_prompt,
                    seed, steps, cfg, denoise, checkpoint,
                    lora1_enabled, lora1, lora1_strength,
                    lora2_enabled, lora2, lora2_strength,
                    lora3_enabled, lora3, lora3_strength,
                    vae
                ]
            )

            # Restore last successful settings (parameters only, keep current workflow)
            restore_settings_btn.click(
                fn=self.restore_settings_parameters,
                inputs=[],
                outputs=[
                    positive_prompt, negative_prompt, width, height,
                    seed, steps, cfg, denoise, checkpoint,
                    lora1_enabled, lora1, lora1_strength,
                    lora2_enabled, lora2, lora2_strength,
                    lora3_enabled, lora3, lora3_strength,
                    vae
                ]
            )

            # Generate button - pass editable parameters including models and dimensions
            generate_btn.click(
                fn=self.execute_current_workflow,
                inputs=[
                    image_upload, invert_mask, image_upload_2, positive_prompt, negative_prompt,
                    width, height, seed, steps, cfg, denoise, checkpoint,
                    lora1_enabled, lora1, lora1_strength,
                    lora2_enabled, lora2, lora2_strength,
                    lora3_enabled, lora3, lora3_strength,
                    vae
                ],
                outputs=[execution_status, result_gallery, selected_history_image, history_gallery]
            )

            # Load image history on page load (avoids threading issues at init)
            app.load(
                fn=lambda: self.image_history,
                inputs=[],
                outputs=[history_gallery]
            )

            # Live preview polling - polls every 200ms for preview updates
            preview_event = app.load(
                fn=self.get_preview_update,
                inputs=[],
                outputs=[live_preview_image, live_preview_status],
                every=0.2  # Poll every 200ms
            )

            # Stop button - interrupts current generation
            stop_btn.click(
                fn=self.interrupt_generation,
                inputs=[],
                outputs=[execution_status]
            )

            # Theme mode switcher
            def on_theme_change(mode: str):
                """Save theme preference and return status message"""
                mode_lower = mode.lower()
                result = set_setting("theme_mode", mode_lower)
                status_msg = f"✅ Theme changed to **{mode}** mode"
                return status_msg

            theme_mode.change(
                fn=on_theme_change,
                inputs=[theme_mode],
                outputs=[theme_status],
                js="""
                (mode) => {
                    const modeLower = mode.toLowerCase();
                    const gradioContainer = document.querySelector('.gradio-container');
                    if (gradioContainer) {
                        if (modeLower === 'dark') {
                            gradioContainer.classList.add('dark');
                        } else if (modeLower === 'light') {
                            gradioContainer.classList.remove('dark');
                        } else {
                            // System - follow OS preference
                            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                                gradioContainer.classList.add('dark');
                            } else {
                                gradioContainer.classList.remove('dark');
                            }
                        }
                    }
                }
                """
            )

            # Show theme status after change
            theme_status.change(
                fn=lambda x: gr.update(visible=True),
                inputs=[theme_status],
                outputs=[theme_status]
            )

            # Photopea buttons - image editing integration
            photopea_send_btn.click(
                None,
                inputs=[],
                outputs=[],
                js=PHOTOPEA_SEND_JS
            )

            # Photopea export - JS populates textbox, textbox change triggers Python
            photopea_export_btn.click(
                fn=None,
                inputs=[],
                outputs=[photopea_data],
                js=PHOTOPEA_EXPORT_JS
            )

            # When textbox changes (JS populates it), automatically process the image
            photopea_data.change(
                fn=self.process_photopea_export,
                inputs=[photopea_data],
                outputs=[image_upload]
            )

            # Send gallery result to input for iterative editing (with auto-dimension detection)
            send_to_input_btn.click(
                fn=self.send_gallery_to_input,
                inputs=[result_gallery, selected_gallery_image],
                outputs=[image_upload, width, height]
            )

            # History gallery - track selected image
            def on_history_select(evt: gr.SelectData):
                """Track selected history image"""
                print(f"[GradioApp] History selected: index={evt.index}, value={evt.value}")
                return evt.value

            history_gallery.select(
                fn=on_history_select,
                inputs=[],
                outputs=[selected_history_image]
            )

            def on_result_select(evt: gr.SelectData):
                """Track selected result image"""
                print(f"[GradioApp] Result selected: index={evt.index}, value={evt.value}")
                return evt.value

            result_gallery.select(
                fn=on_result_select,
                inputs=[],
                outputs=[selected_gallery_image]
            )

            # Send history to input
            history_to_input_btn.click(
                fn=self.send_history_to_input,
                inputs=[history_gallery, selected_history_image],
                outputs=[image_upload, width, height]
            )

            # Send history to Photopea - use JavaScript with dynamic image path
            # We need a helper function to get the selected image and send it
            history_to_photopea_btn.click(
                fn=None,
                inputs=[history_gallery, selected_history_image],
                outputs=[],
                js="""
                async (galleryData, selectedPath) => {
                    const showError = (message) => {
                        console.error('[History to Photopea]', message);
                        const buttons = document.querySelectorAll('button');
                        for (let btn of buttons) {
                            if (btn.textContent.includes('Send to Photopea')) {
                                btn.style.background = '#ef4444';
                                setTimeout(() => btn.style.background = '', 2000);
                                break;
                            }
                        }
                    };

                    if (!window.photopeaWindow) {
                        const iframe = document.querySelector('#photopea-iframe');
                        if (iframe) window.photopeaWindow = iframe.contentWindow;
                    }

                    if (!window.photopeaWindow) {
                        showError("Photopea not ready. Make sure the Photopea accordion is open.");
                        return;
                    }

                    const normalizeSource = (item) => {
                        if (!item) return "";
                        if (Array.isArray(item)) {
                            for (const entry of item) {
                                const norm = normalizeSource(entry);
                                if (norm) return norm;
                            }
                            return "";
                        }
                        if (typeof item === "string") return item;
                        if (typeof item === "object") {
                            return item.image || item.name || item.path || item.url || "";
                        }
                        return "";
                    };

                    // Prefer DOM selection so we get the rendered src (blob/http/data URL)
                    const galleryEl = document.querySelector('#history-gallery');
                    const selectedImg = galleryEl?.querySelector('[aria-selected=\"true\"] img') || galleryEl?.querySelector('img');
                    let src = selectedImg?.src || normalizeSource(selectedPath) || normalizeSource(galleryData);

                    if (!src) {
                        showError("No history image selected. Click an image first.");
                        return;
                    }

                    // Convert filesystem paths to a fetchable URL for the current Gradio server
                    const toUrl = (value) => {
                        if (!value) return "";
                        if (value.startsWith("http") || value.startsWith("blob:") || value.startsWith("data:")) return value;
                        if (value.startsWith("/")) return `${window.location.origin}/file=${encodeURIComponent(value)}`;
                        return value;
                    };

                    src = toUrl(src);

                    const toDataUrl = async (url) => {
                        const response = await fetch(url);
                        const blob = await response.blob();
                        return await new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result);
                            reader.onerror = reject;
                            reader.readAsDataURL(blob);
                        });
                    };

                    const sendToPhotopea = (dataUrl) => {
                        window.photopeaWindow.postMessage('app.open(\"' + dataUrl + '\", null, true);', "*");
                        console.log('[History to Photopea] Sent image:', dataUrl.substring(0, 100) + '...');
                        setTimeout(() => {
                            const buttons = document.querySelectorAll('button');
                            for (let btn of buttons) {
                                if (btn.textContent.includes('Send to Photopea')) {
                                    btn.style.background = '#10b981';
                                    setTimeout(() => btn.style.background = '', 1500);
                                    break;
                                }
                            }
                        }, 100);
                    };

                    try {
                        const dataUrl = src.startsWith("data:") ? src : await toDataUrl(src);
                        sendToPhotopea(dataUrl);
                    } catch (err) {
                        console.error('[History to Photopea] Failed to load image', err);
                        showError("Failed to load history image. Make sure it still exists.");
                    }
                }
                """
            )

            # Civitai browser event handlers
            civitai_save_key_btn.click(
                fn=civitai_browser.save_api_key,
                inputs=[civitai_api_key],
                outputs=[civitai_key_status]
            )

            # Hidden state for pagination (fixed values for now)
            civitai_page_state = gr.State(value=1)
            civitai_per_page_state = gr.State(value=20)

            civitai_search_btn.click(
                fn=civitai_browser.search_models,
                inputs=[
                    civitai_query,
                    civitai_type,
                    civitai_sort,
                    civitai_page_state,
                    civitai_per_page_state,
                    civitai_nsfw,
                    civitai_api_key
                ],
                outputs=[
                    civitai_search_status,
                    civitai_results_state,
                    civitai_results_dropdown,
                    civitai_results_gallery
                ]
            )

            civitai_results_dropdown.change(
                fn=civitai_browser.select_model,
                inputs=[civitai_results_dropdown, civitai_results_state],
                outputs=[
                    civitai_model_details,
                    civitai_preview_gallery,
                    civitai_version_dropdown,
                    civitai_file_dropdown,
                    civitai_target_dir
                ]
            )
            civitai_results_gallery.select(
                fn=civitai_browser.select_model_by_index,
                inputs=[civitai_results_state],
                outputs=[
                    civitai_model_details,
                    civitai_preview_gallery,
                    civitai_version_dropdown,
                    civitai_file_dropdown,
                    civitai_target_dir
                ]
            )

            civitai_version_dropdown.change(
                fn=civitai_browser.select_version,
                inputs=[civitai_version_dropdown, civitai_results_state],
                outputs=[
                    civitai_file_dropdown,
                    civitai_target_dir
                ]
            )

            civitai_download_btn.click(
                fn=civitai_browser.download_file,
                inputs=[
                    civitai_version_dropdown,
                    civitai_file_dropdown,
                    civitai_target_dir,
                    civitai_api_key
                ],
                outputs=[civitai_download_status]
            )

        # Initialize queue with proper configuration to prevent Gradio 4.44.0 streaming bug
        # This fixes: AttributeError: 'NoneType' object has no attribute 'wait'
        # Disable API to avoid queue errors, set concurrency limit
        queue_kwargs = {
            "api_open": False,
            "default_concurrency_limit": 20
        }
        if "client_max_timeout" in inspect.signature(app.queue).parameters:
            queue_kwargs["client_max_timeout"] = self.client.timeout_config.prompt_execution
        app.queue(**queue_kwargs)

        return app

    def launch(self, **kwargs):
        """
        Launch the Gradio application in offline/headless mode

        Args:
            **kwargs: Additional arguments passed to gr.Blocks.launch()
        """
        app = self.create_interface()

        # Ensure offline/headless mode - disable all external calls
        kwargs.setdefault('share', False)
        kwargs.setdefault('show_api', False)
        kwargs.setdefault('quiet', False)

        # Try to find an available port
        server_port = kwargs.pop('server_port', None)
        if server_port is None:
            for port in GRADIO_PORTS:
                try:
                    app.launch(
                        server_port=port,
                        server_name="127.0.0.1",
                        **kwargs
                    )
                    print(f"✅ Gradio server started on port {port}")
                    print(f"   Access at: http://127.0.0.1:{port}")
                    print(f"   Mode: Offline/Headless (no external calls)")
                    return
                except OSError:
                    continue

            # If all ports fail
            raise RuntimeError(
                f"Could not find available port. Tried: {GRADIO_PORTS}"
            )
        else:
            app.launch(
                server_port=server_port,
                server_name="127.0.0.1",
                **kwargs
            )
            print(f"✅ Gradio server started on port {server_port}")
            print(f"   Access at: http://127.0.0.1:{server_port}")
            print(f"   Mode: Offline/Headless (no external calls)")


def main():
    """
    Main entry point for standalone execution
    """
    print(f"""
    ╔══════════════════════════════════════════════════════════════╗
    ║  {PROJECT_NAME:^58}  ║
    ║  {VERSION:^58}  ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  Phase 1 MVP: Dynamic UI Generation                          ║
    ║                                                              ║
    ║  This demo shows schema-driven UI generation that works      ║
    ║  with ANY ComfyUI workflow without hardcoded node types.     ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    app = ComfyUIGradioApp()
    app.launch(inbrowser=True)


if __name__ == "__main__":
    main()
