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
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

from .core.comfyui_client import ComfyUIClient
from .core.ui_generator import UIGenerator, GeneratedUI
from .core.execution_engine import ExecutionEngine
from .core.result_retriever import ResultRetriever
from .utils.workflow_utils import load_workflow_from_file

# Import from sibling package (kelnel_ui is at same level as ComfyUI_to_webui_v2)
try:
    from kelnel_ui.k_Preview import ComfyUIPreviewer
except ImportError:
    # Fallback for standalone testing - try relative import from parent
    import sys
    from pathlib import Path
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from kelnel_ui.k_Preview import ComfyUIPreviewer
from .config import (
    COMFYUI_BASE_URL,
    GRADIO_PORTS,
    VERSION,
    PROJECT_NAME,
    PROJECT_DESCRIPTION
)


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

        # Scan for available workflows in ComfyUI workflows directory
        self.workflows_dir = self._find_workflows_directory()
        self.available_workflows = self._scan_workflows()

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
                        loaders[category] = {
                            "node_id": node_id,
                            "class_type": class_type,
                            "param": param_name,
                            "current_value": inputs[param_name]
                        }
                        break

            # DYNAMIC DISCOVERY: Catch any loader we missed
            # Look for nodes with "Lora" or "LoRA" in name that have model parameters
            if "lora" not in loaders and ("lora" in class_type.lower() or "LoRA" in class_type):
                # Power Lora Loader (rgthree) uses dynamic inputs like lora_01, lora_02, etc.
                # Look for any parameter that looks like a LoRA
                lora_param = None
                lora_value = None

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

                # Even if no LoRA is loaded, mark the node as a LoRA loader
                # This handles Power Lora Loader nodes that exist but have no LoRAs selected
                if lora_param or "Power Lora Loader" in class_type:
                    print(f"[GradioApp] Found LoRA loader: {class_type} (node {node_id})")
                    loaders["lora"] = {
                        "node_id": node_id,
                        "class_type": class_type,
                        "param": lora_param or "lora_01",  # Default param name for Power Lora Loader
                        "current_value": lora_value or ""
                    }
                elif lora_param:
                    print(f"[GradioApp] Found unknown LoRA loader: {class_type} with param {lora_param}")
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
                        value = current_value if current_value else "None"
                    else:
                        choices = models
                        value = current_value if current_value in models else (models[0] if models else None)

                    print(f"[GradioApp]   Returning choices: {len(choices)} items, value: {value}")
                    return choices, value
                except Exception as e:
                    print(f"[GradioApp] ERROR getting models for {class_type}: {e}")
                    import traceback
                    traceback.print_exc()

        # No loader found for this category
        print(f"[GradioApp] No loader found for category: {categories}")
        return ["None"], "None"

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
            Tuple of (markdown_summary, positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora, lora_strength, vae)
        """
        if not workflow_path or workflow_path == "None":
            return ("", "", "", -1, 20, 7.0, 1.0, None, "None", 1.0, "None")

        try:
            # Load workflow
            self.current_workflow = load_workflow_from_file(workflow_path)

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
            lora_choices, lora_value = self._get_model_choices_for_loader("lora")
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
                gr.update(choices=lora_choices, value=lora_value),
                1.0,  # lora_strength default
                gr.update(choices=vae_choices, value=vae_value)
            )

        except Exception as e:
            return (
                f"### ❌ Error Loading Workflow\n\n```\n{str(e)}\n```",
                "", "", -1, 20, 7.0, 1.0,
                gr.update(choices=[], value=None),
                gr.update(choices=["None"], value="None"),
                1.0,  # lora_strength default
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
            Tuple of (markdown_summary, positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora, lora_strength, vae)
        """
        if not workflow_file:
            return ("", "", "", -1, 20, 7.0, 1.0, None, "None", 1.0, "None")

        try:
            # Load workflow (auto-converts from workflow format to API format)
            self.current_workflow = load_workflow_from_file(workflow_file)

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
            lora_choices, lora_value = self._get_model_choices_for_loader("lora")
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
                gr.update(choices=lora_choices, value=lora_value),
                1.0,  # lora_strength default
                gr.update(choices=vae_choices, value=vae_value)
            )

        except Exception as e:
            return (
                f"### ❌ Error Loading Workflow\n\n```\n{str(e)}\n```",
                "", "", -1, 20, 7.0, 1.0,
                gr.update(choices=[], value=None),
                gr.update(choices=["None"], value="None"),
                1.0,  # lora_strength default
                gr.update(choices=["None"], value="None")
            )

    def execute_current_workflow(
        self,
        positive_prompt: str,
        negative_prompt: str,
        seed: float,
        steps: float,
        cfg: float,
        denoise: float,
        checkpoint: str,
        lora: str,
        lora_strength: float,
        vae: str
    ) -> tuple[str, list]:
        """
        Execute the currently loaded workflow with user-provided parameters

        Args:
            positive_prompt: Positive prompt text
            negative_prompt: Negative prompt text
            seed: Random seed (-1 for random)
            steps: Number of sampling steps
            cfg: CFG scale value
            denoise: Denoise strength
            checkpoint: Checkpoint model name
            lora: LoRA model name
            lora_strength: LoRA strength/weight (0.0 to 2.0)
            vae: VAE model name

        Returns:
            Tuple of (status_message, result_images)
        """
        print("[GradioApp] Execute button clicked")

        if not self.current_workflow:
            print("[GradioApp] No workflow loaded!")
            return "❌ No workflow loaded. Please select a workflow first.", []

        try:
            # Build user values dict
            user_values = {
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "seed": int(seed) if seed >= 0 else None,  # None means randomize
                "steps": int(steps),
                "cfg": float(cfg),
                "denoise": float(denoise),
                "checkpoint": checkpoint if checkpoint else None,
                "lora": lora if lora and lora != "None" else None,
                "lora_strength": float(lora_strength),
                "vae": vae if vae and vae != "None" else None
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
                    return f"❌ **Execution Failed**\n\n{error_msg}\n\n**Node Errors:**\n{error_details}", []
                return f"❌ **Execution Failed**\n\n{error_msg}", []

            # Wait for results
            status_msg = f"⏳ **Executing workflow...**\n\nPrompt ID: `{exec_result.prompt_id}`"
            print(f"[GradioApp] Waiting for results...")

            retrieval_result = self.result_retriever.retrieve_results(
                exec_result.prompt_id,
                exec_result.client_id,
                self.current_workflow,
                timeout=30  # Reduced timeout for debugging
            )

            print(f"[GradioApp] Retrieval result: success={retrieval_result.success}")

            if not retrieval_result.success:
                return f"❌ **Result Retrieval Failed**\n\n{retrieval_result.error}", []

            # Success!
            num_images = len(retrieval_result.images)
            num_videos = len(retrieval_result.videos)

            status_msg = f"✅ **Generation Complete!**\n\n"
            status_msg += f"- **Images**: {num_images}\n"
            status_msg += f"- **Videos**: {num_videos}\n"
            status_msg += f"- **Prompt ID**: `{exec_result.prompt_id}`"

            # Return images for gallery
            all_results = retrieval_result.images + retrieval_result.videos

            return status_msg, all_results

        except Exception as e:
            return f"❌ **Unexpected Error**\n\n```\n{str(e)}\n```", []

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

    def create_interface(self) -> gr.Blocks:
        """
        Create the main Gradio interface

        Returns:
            Gradio Blocks application
        """
        with gr.Blocks(
            title=PROJECT_NAME,
            theme=gr.themes.Default()
        ) as app:
            # Header
            gr.Markdown(f"""
            # {PROJECT_NAME} 🚀
            {PROJECT_DESCRIPTION}

            **Version:** {VERSION}
            **Phase 2:** Dynamic UI Generation + Workflow Execution

            ---

            ## Instructions
            1. **Select workflow** from dropdown or upload JSON file
            2. **Review** the detected parameters in the analysis section
            3. **Click Generate** to execute the workflow
            4. **View results** in the gallery below

            **Phase 2 Features:**
            - ✅ Dynamic UI generation (any workflow)
            - ✅ Workflow execution via ComfyUI API
            - ✅ Result retrieval from SaveImage nodes
            - ✅ Image/video gallery display
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
                        lora = gr.Dropdown(
                            label="LoRA (Optional)",
                            choices=["None"],
                            value="None",
                            allow_custom_value=True,
                            interactive=True,
                            visible=True
                        )
                        lora_strength = gr.Slider(
                            label="LoRA Strength",
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

                    # Workflow summary (read-only info)
                    with gr.Accordion("ℹ️ Workflow Details", open=False):
                        dynamic_ui_container = gr.Markdown(
                            value="",
                            label="Workflow Analysis"
                        )

            # Execution section
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 3. Generate")

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

                    execution_status = gr.Markdown(
                        value="",
                        label="Status"
                    )

            # Results section
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 4. Results")

                    # Tabbed interface for Live Preview and Final Results
                    with gr.Tabs():
                        with gr.Tab("🔴 Live Preview"):
                            live_preview_image = gr.Image(
                                label="Live Preview",
                                type="pil",
                                interactive=False,
                                height=512
                            )
                            live_preview_status = gr.Textbox(
                                label="Preview Status",
                                value="Waiting for generation...",
                                interactive=False,
                                max_lines=1
                            )

                        with gr.Tab("✅ Final Results"):
                            result_gallery = gr.Gallery(
                                label="Generated Images/Videos",
                                show_label=False,
                                columns=3,
                                object_fit="contain",
                                height="auto"
                            )

            # Info section
            with gr.Row():
                gr.Markdown(f"""
                ---
                ### About This Demo

                This is **ComfyUI_to_webui V2** - now in **Phase 3**!

                **Completed Features:**
                - ✅ **Phase 1:** Schema-driven dynamic UI generation
                - ✅ **Phase 2:** Workflow execution, result retrieval, model loaders
                - ✅ **Phase 3:** WebSocket live preview (active now!)

                **What's Different from V1:**
                - ❌ No hardcoded node types (Hua_Output, GradioTextOk, etc.)
                - ❌ No fixed component pools (MAX_DYNAMIC_COMPONENTS=20)
                - ❌ No custom output nodes required
                - ✅ Works with ANY ComfyUI workflow
                - ✅ Unlimited dynamic components
                - ✅ Auto-detects node types via /object_info API
                - ✅ Live preview during generation

                **Coming in Future Phases:**
                - Phase 4: UI polish, component grouping, model scanner
                - Phase 5: Civitai browser, batch processing

                **Development Info:**
                - Branch: `v2-dynamic-rewrite`
                - ComfyUI Server: {COMFYUI_BASE_URL}
                """)

            # Wire up event handlers
            # Dropdown selection - populate defaults when workflow is selected
            def on_dropdown_change(workflow_name):
                if workflow_name == "None" or not workflow_name:
                    return ("", "", "", -1, 20, 7.0, 1.0, None, "None", 1.0, "None")
                workflow_path = self.available_workflows.get(workflow_name)
                return self.generate_ui_from_workflow_path(workflow_path)

            workflow_dropdown.change(
                fn=on_dropdown_change,
                inputs=[workflow_dropdown],
                outputs=[dynamic_ui_container, positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora, lora_strength, vae]
            )

            # File upload - populate defaults when workflow is uploaded
            workflow_file.change(
                fn=self.generate_ui_from_workflow,
                inputs=[workflow_file],
                outputs=[dynamic_ui_container, positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora, lora_strength, vae]
            )

            # Generate button - pass editable parameters including models
            generate_btn.click(
                fn=self.execute_current_workflow,
                inputs=[positive_prompt, negative_prompt, seed, steps, cfg, denoise, checkpoint, lora, lora_strength, vae],
                outputs=[execution_status, result_gallery]
            )

            # Live preview polling - updates every 200ms
            # Using polling instead of generator for better Gradio 4.x compatibility
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

        return app

    def launch(self, **kwargs):
        """
        Launch the Gradio application

        Args:
            **kwargs: Additional arguments passed to gr.Blocks.launch()
        """
        app = self.create_interface()

        # Try to find an available port
        server_port = kwargs.pop('server_port', None)
        if server_port is None:
            for port in GRADIO_PORTS:
                try:
                    app.launch(
                        server_port=port,
                        server_name="127.0.0.1",
                        share=False,
                        **kwargs
                    )
                    print(f"✅ Gradio server started on port {port}")
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
                share=False,
                **kwargs
            )


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
