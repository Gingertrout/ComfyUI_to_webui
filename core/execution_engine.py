"""
Execution Engine

This module handles workflow execution:
- Building prompts with user-provided values
- Submitting to ComfyUI
- Tracking execution status
- Managing client IDs

Phase 2: Simple single-execution model
Future: Add queue system for concurrent requests
"""

import uuid
import copy
import random
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .comfyui_client import ComfyUIClient
from .ui_generator import GeneratedUI
from ..config import IMAGE_INPUT_NODE_TYPES


@dataclass
class ExecutionResult:
    """Result of a workflow execution"""
    success: bool
    prompt_id: str
    client_id: str
    error: Optional[str] = None
    node_errors: Optional[Dict] = None


class ExecutionEngine:
    """
    Handles workflow execution

    Responsibilities:
    - Build execution prompt from workflow + UI values
    - Submit to ComfyUI
    - Track execution status
    """

    def __init__(self, comfyui_client: ComfyUIClient):
        """
        Initialize execution engine

        Args:
            comfyui_client: ComfyUI API client
        """
        self.client = comfyui_client

    def execute_workflow(
        self,
        workflow: Dict[str, Any],
        generated_ui: Optional[GeneratedUI] = None,
        user_values: Optional[Dict[str, Any]] = None,
        discovered_loaders: Optional[Dict[str, Dict[str, Any]]] = None,
        client_id: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute a workflow with optional user-provided values

        Args:
            workflow: Original workflow JSON (API format)
            generated_ui: Generated UI structure (contains current values)
            user_values: User-provided values (from interactive UI)
            discovered_loaders: Map of discovered loader nodes (category -> loader info)
            client_id: Optional client ID (for WebSocket preview integration)

        Returns:
            ExecutionResult with prompt_id and status
        """
        # Use provided client_id or generate a unique one
        if client_id is None:
            client_id = str(uuid.uuid4())

        try:
            print(f"[ExecutionEngine] Building prompt for client_id: {client_id}")

            # Build execution prompt
            prompt = self._build_execution_prompt(
                workflow,
                generated_ui,
                user_values,
                discovered_loaders
            )

            print(f"[ExecutionEngine] Prompt has {len(prompt)} nodes")

            # Debug: Print node 9 (Power Lora Loader) if it exists to see injected values
            if discovered_loaders and "lora" in discovered_loaders:
                lora_node_id = discovered_loaders["lora"]["node_id"]
                if lora_node_id in prompt:
                    print(f"[ExecutionEngine] DEBUG - LoRA Node {lora_node_id} after injection: {prompt[lora_node_id]}")

            # Debug: Print a sample node to verify structure
            if prompt:
                first_node_id = list(prompt.keys())[0]
                print(f"[ExecutionEngine] Sample node {first_node_id}: {prompt[first_node_id]}")

            # Submit to ComfyUI
            print(f"[ExecutionEngine] Submitting to ComfyUI...")
            response = self.client.submit_prompt(prompt, client_id)

            print(f"[ExecutionEngine] Response received: prompt_id={response.prompt_id}, number={response.number}")
            print(f"[ExecutionEngine] Node errors: {response.node_errors}")

            # Check for node errors
            if response.node_errors:
                print(f"[ExecutionEngine] VALIDATION FAILED - Node errors detected: {response.node_errors}")
                return ExecutionResult(
                    success=False,
                    prompt_id=response.prompt_id,
                    client_id=client_id,
                    error="Node validation errors",
                    node_errors=response.node_errors
                )

            return ExecutionResult(
                success=True,
                prompt_id=response.prompt_id,
                client_id=client_id
            )

        except Exception as e:
            print(f"[ExecutionEngine] Exception: {e}")
            import traceback
            traceback.print_exc()
            return ExecutionResult(
                success=False,
                prompt_id="",
                client_id=client_id,
                error=str(e)
            )

    def _build_execution_prompt(
        self,
        workflow: Dict[str, Any],
        generated_ui: Optional[GeneratedUI],
        user_values: Optional[Dict[str, Any]],
        discovered_loaders: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Build execution prompt from workflow and user values

        For Phase 2: Just use the workflow as-is (no user edits yet)
        Future: Inject user_values from interactive UI components

        Args:
            workflow: Original workflow
            generated_ui: UI structure with components
            user_values: User-provided values
            discovered_loaders: Map of discovered loader nodes (for targeted injection)

        Returns:
            Execution prompt ready for /prompt endpoint
        """
        # Clone workflow
        prompt = copy.deepcopy(workflow)

        # Filter out non-executable nodes (annotations, UI-only nodes, etc.)
        prompt = self._filter_non_executable_nodes(prompt)

        # Inject user values (if provided)
        if user_values:
            prompt = self._inject_user_values(prompt, generated_ui, user_values, discovered_loaders)
        else:
            # No user values - randomize seeds to prevent ComfyUI caching
            prompt = self._randomize_seeds(prompt)

        return prompt

    def _filter_non_executable_nodes(self, prompt: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove non-executable nodes from prompt

        ComfyUI workflows can contain annotation nodes like "Note" which are
        for documentation only and should not be included in execution prompts.

        Args:
            prompt: Workflow prompt

        Returns:
            Filtered prompt with only executable nodes
        """
        # Node types that should be filtered out (non-executable)
        NON_EXECUTABLE_TYPES = {
            "Note",           # Annotation/comment nodes
            "Reroute",        # Sometimes non-executable depending on context
            "PrimitiveNode",  # UI-only nodes (sometimes)
        }

        filtered_prompt = {}
        removed_nodes = []

        for node_id, node_data in prompt.items():
            class_type = node_data.get("class_type", "")

            # Keep executable nodes
            if class_type not in NON_EXECUTABLE_TYPES:
                filtered_prompt[node_id] = node_data
            else:
                removed_nodes.append(f"{node_id} ({class_type})")

        if removed_nodes:
            print(f"[ExecutionEngine] Filtered out non-executable nodes: {', '.join(removed_nodes)}")

        return filtered_prompt

    def _randomize_seeds(self, prompt: Dict[str, Any]) -> Dict[str, Any]:
        """
        Randomize seed values in the prompt to prevent ComfyUI caching

        ComfyUI caches execution results when the exact same prompt is submitted.
        By randomizing seeds, we ensure fresh generations each time.

        Args:
            prompt: Workflow prompt

        Returns:
            Prompt with randomized seeds
        """
        # Sampler node types that have seed parameters
        SAMPLER_TYPES = {
            "KSampler",
            "KSamplerAdvanced",
            "SamplerCustom",
            "KSamplerSelect",
        }

        randomized_count = 0

        for node_id, node_data in prompt.items():
            class_type = node_data.get("class_type", "")

            if class_type in SAMPLER_TYPES:
                inputs = node_data.get("inputs", {})
                if "seed" in inputs:
                    # Generate random seed (ComfyUI uses large integers)
                    new_seed = random.randint(0, 2**32 - 1)
                    inputs["seed"] = new_seed
                    randomized_count += 1

        if randomized_count > 0:
            print(f"[ExecutionEngine] Randomized {randomized_count} seed(s) to prevent caching")

        return prompt

    def _inject_user_values(
        self,
        prompt: Dict[str, Any],
        generated_ui: Optional[GeneratedUI],
        user_values: Dict[str, Any],
        discovered_loaders: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Inject user-provided values into prompt

        This intelligently maps user values to the appropriate nodes:
        - Positive/negative prompts -> CLIPTextEncode nodes
        - Seed/steps/cfg/denoise -> KSampler nodes
        - Models -> Only into discovered loader nodes (prevents cross-contamination)

        Args:
            prompt: Execution prompt
            generated_ui: UI structure (optional)
            user_values: Values from UI components
            discovered_loaders: Map of discovered loader nodes (for targeted injection)

        Returns:
            Updated prompt
        """
        print(f"[ExecutionEngine] Injecting user values into prompt")

        # Track what we injected
        injected = []

        def is_linked_input(value: Any) -> bool:
            """Return True if the value is a node link rather than a literal."""
            return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)

        width_value = user_values.get("width")
        height_value = user_values.get("height")

        # First pass: collect all text encoding nodes and guess which is positive/negative
        # Support multiple node types with different parameter names
        TEXT_ENCODE_NODE_TYPES = {
            "CLIPTextEncode": "text",
            "TextEncodeQwenImageEditPlus": "prompt",
            "CLIPTextEncodeSDXL": "text",
            "CLIPTextEncodeFlux": "text",
        }

        clip_nodes = []
        for node_id, node_data in prompt.items():
            class_type = node_data.get("class_type", "")

            # Check if this is a text encoding node
            if class_type in TEXT_ENCODE_NODE_TYPES:
                param_name = TEXT_ENCODE_NODE_TYPES[class_type]
                node_title = node_data.get("_meta", {}).get("title", "").lower()
                original_text = node_data.get("inputs", {}).get(param_name, "")
                if isinstance(original_text, str):
                    original_text = original_text.lower()
                else:
                    original_text = ""

                # Guess type based on content and title
                is_negative = (
                    "negative" in node_title or
                    any(word in original_text for word in ["bad", "ugly", "worst", "low quality", "watermark", "3d", "cg", "blurry"])
                )

                clip_nodes.append((node_id, node_data, node_title, is_negative, original_text, param_name))
                print(f"[ExecutionEngine] Found {class_type} node {node_id}: param={param_name}, title='{node_title}', is_negative={is_negative}")

        # Sort nodes: positive first, then negative
        clip_nodes.sort(key=lambda x: x[3])  # False (positive) comes before True (negative)

        # Inject prompts into text encoding nodes
        positive_injected = False
        negative_injected = False

        for node_id, node_data, node_title, is_negative, original_text, param_name in clip_nodes:
            inputs = node_data.get("inputs", {})

            # Inject positive prompt to positive node
            if not positive_injected and not is_negative and user_values.get("positive_prompt"):
                new_text = user_values["positive_prompt"]
                inputs[param_name] = new_text
                injected.append(f"{node_id}.{param_name} (POSITIVE: '{new_text[:30]}...')")
                positive_injected = True
                print(f"[ExecutionEngine]   ✓ POSITIVE Node {node_id}: '{original_text[:50]}...' -> '{new_text[:50]}...'")
                continue

            # Inject negative prompt to negative node
            if not negative_injected and is_negative and user_values.get("negative_prompt") is not None:
                new_text = user_values["negative_prompt"] if user_values["negative_prompt"] else ""
                inputs[param_name] = new_text
                injected.append(f"{node_id}.{param_name} (NEGATIVE: '{new_text[:30]}...')")
                negative_injected = True
                print(f"[ExecutionEngine]   ✓ NEGATIVE Node {node_id}: '{original_text[:50]}...' -> '{new_text[:50]}...'")
                continue

        # Second pass: inject sampling parameters
        for node_id, node_data in prompt.items():
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})

            # Inject sampling parameters into KSampler nodes
            if class_type in {"KSampler", "KSamplerAdvanced", "SamplerCustom"}:
                if user_values.get("seed") is not None:
                    if "seed" in inputs:
                        inputs["seed"] = user_values["seed"]
                        injected.append(f"{node_id}.seed")
                else:
                    # No seed provided - randomize it
                    if "seed" in inputs:
                        inputs["seed"] = random.randint(0, 2**32 - 1)
                        injected.append(f"{node_id}.seed (random)")

                if user_values.get("steps") is not None and "steps" in inputs:
                    inputs["steps"] = user_values["steps"]
                    injected.append(f"{node_id}.steps")

                if user_values.get("cfg") is not None and "cfg" in inputs:
                    inputs["cfg"] = user_values["cfg"]
                    injected.append(f"{node_id}.cfg")

                if user_values.get("denoise") is not None and "denoise" in inputs:
                    inputs["denoise"] = user_values["denoise"]
                    injected.append(f"{node_id}.denoise")

            # Inject dimensions into EmptyLatentImage and similar nodes
            # CRITICAL FIX: Always set batch_size=1 to prevent VRAM overflow
            if class_type in {
                "EmptyLatentImage",
                "EmptySD3LatentImage",
                "EmptyFluxLatent",
                "EmptyFlux2Latent",
                "EmptyFluxLatentImage",
                "EmptyFlux2LatentImage",
            }:
                if width_value is not None and "width" in inputs:
                    inputs["width"] = width_value
                    injected.append(f"{node_id}.width")

                if height_value is not None and "height" in inputs:
                    inputs["height"] = height_value
                    injected.append(f"{node_id}.height")

                # CRITICAL: Always force batch_size=1 (prevents corruption to 1024)
                if "batch_size" in inputs:
                    inputs["batch_size"] = 1
                    injected.append(f"{node_id}.batch_size=1 (forced)")

            # Inject dimensions into image resize/scale nodes
            # This ensures dimensions are consistent throughout the pipeline
            if class_type in {
                "LoadAndResizeImage",
                "ImageResize",
                "ImageResizeKJ",
                "ImageResizeKJv2",
                "ImageScale",
                "ImageScaleBy",
            }:
                if width_value is not None and "width" in inputs:
                    inputs["width"] = width_value
                    injected.append(f"{node_id}.width")

                if height_value is not None and "height" in inputs:
                    inputs["height"] = height_value
                    injected.append(f"{node_id}.height")

                # For LoadAndResizeImage, disable keep_proportion to ensure exact dimensions
                if class_type == "LoadAndResizeImage" and "keep_proportion" in inputs:
                    inputs["keep_proportion"] = False
                    injected.append(f"{node_id}.keep_proportion=False")

                # For LoadAndResizeImage, enable resize flag
                if class_type == "LoadAndResizeImage" and "resize" in inputs:
                    inputs["resize"] = True
                    injected.append(f"{node_id}.resize=True")

            # Fallback: apply dimensions to any unlinked width/height inputs (covers new node types)
            for dim_name, dim_value in (("width", width_value), ("height", height_value)):
                if dim_value is None or dim_name not in inputs:
                    continue
                if is_linked_input(inputs[dim_name]):
                    continue
                if inputs[dim_name] == dim_value:
                    continue
                inputs[dim_name] = dim_value
                injected.append(f"{node_id}.{dim_name} (auto)")

        # Third pass: inject model selections using TARGETED approach
        # Only inject into the specific nodes we discovered to avoid cross-contamination
        if discovered_loaders:
            for category, loader_info in discovered_loaders.items():
                target_node_id = loader_info["node_id"]
                target_param = loader_info["param"]

                # Get the target node directly
                if target_node_id not in prompt:
                    print(f"[ExecutionEngine] WARNING: Target node {target_node_id} not found in prompt")
                    continue

                target_node = prompt[target_node_id]
                inputs = target_node.get("inputs", {})

                # Map UI categories to user values
                value_map = {
                    "checkpoint": "checkpoint",
                    "unet": "checkpoint",  # UNET uses checkpoint UI
                    "lora": "lora",
                    "vae": "vae",
                    "clip": None  # Don't inject CLIP - too many variants
                }

                # Special handling for LoRAs (Power Lora Loader supports multiple slots)
                if category == "lora":
                    class_type = target_node.get("class_type", "")
                    is_power_lora = "Power Lora Loader" in class_type

                    # Collect up to three LoRA selections from the UI
                    lora_entries = user_values.get("loras", [])
                    selected_lora = next(
                        (slot["name"] for slot in lora_entries if slot.get("enabled") and slot.get("name")),
                        None
                    )
                    if selected_lora is None:
                        selected_lora = user_values.get("lora")

                    if is_power_lora:
                        # Ensure we always have three slots to sync on/off state
                        lora_entries = (lora_entries or [])[:3]

                        # Update the _meta.info.unused_widget_values structure
                        meta = target_node.setdefault("_meta", {})
                        info = meta.setdefault("info", {})
                        widget_values = info.setdefault("unused_widget_values", [])

                        # Identify existing LoRA slot indices (skip header entries)
                        slot_indices = [
                            idx for idx, item in enumerate(widget_values)
                            if isinstance(item, dict) and "lora" in item
                        ]

                        # If there are fewer widget slots than UI entries, append new empty ones
                        while len(slot_indices) < len(lora_entries):
                            widget_values.append({
                                "on": False,
                                "lora": None,
                                "strength": 1.0,
                                "strengthTwo": None
                            })
                            slot_indices.append(len(widget_values) - 1)

                        # Turn every slot off before applying user selections
                        for idx in slot_indices:
                            if isinstance(widget_values[idx], dict):
                                widget_values[idx]["on"] = False

                        # Apply up to three LoRAs to corresponding slots
                        for slot_number, (entry, idx) in enumerate(zip(lora_entries, slot_indices), start=1):
                            if idx >= len(widget_values) or not isinstance(widget_values[idx], dict):
                                widget_values.append({
                                    "on": False,
                                    "lora": None,
                                    "strength": 1.0,
                                    "strengthTwo": None
                                })
                                idx = len(widget_values) - 1

                            lora_name = entry.get("name")
                            enabled = bool(entry.get("enabled") and lora_name)
                            strength_value = float(entry.get("strength", user_values.get("lora_strength", 1.0)))

                            widget_values[idx]["on"] = enabled
                            widget_values[idx]["lora"] = lora_name
                            widget_values[idx]["strength"] = strength_value
                            widget_values[idx]["strengthTwo"] = widget_values[idx].get("strengthTwo", None)

                            uppercase_param = f"LORA_{slot_number:02d}"
                            inputs[uppercase_param] = {
                                "on": enabled,
                                "lora": lora_name,
                                "strength": strength_value,
                                "strengthTwo": widget_values[idx].get("strengthTwo")
                            }
                            injected.append(f"{target_node_id}.{uppercase_param}")

                            if enabled:
                                print(f"[ExecutionEngine]   ✓ Enabled Power Lora slot {slot_number}: {lora_name} (strength {strength_value})")
                            else:
                                print(f"[ExecutionEngine]   ⚙️ Slot {slot_number} off (lora={lora_name})")

                        # Explicitly turn off any remaining slots beyond the first three
                        if len(slot_indices) > len(lora_entries):
                            for offset, idx in enumerate(slot_indices[len(lora_entries):], start=len(lora_entries) + 1):
                                if idx >= len(widget_values) or not isinstance(widget_values[idx], dict):
                                    continue
                                widget = widget_values[idx]
                                uppercase_param = f"LORA_{offset:02d}"
                                inputs[uppercase_param] = {
                                    "on": False,
                                    "lora": widget.get("lora"),
                                    "strength": float(widget.get("strength", 1.0)),
                                    "strengthTwo": widget.get("strengthTwo")
                                }
                                injected.append(f"{target_node_id}.{uppercase_param}")
                                print(f"[ExecutionEngine]   ⚙️ Slot {offset} off (lora={widget.get('lora')})")

                        continue

                    # Standard LoRA loaders use a single model
                    if selected_lora in ["None", "", None]:
                        print(f"[ExecutionEngine] Skipping LoRA injection (None selected)")
                        continue

                    inputs[target_param] = selected_lora
                    injected.append(f"{target_node_id}.{target_param} ({category})")
                    print(f"[ExecutionEngine] ✓ Injected {category}: {selected_lora[:30]}... into node {target_node_id}")

                    # Standard LoRA loaders use strength_model and strength_clip
                    lora_strength = user_values.get("lora_strength", 1.0)

                    if "strength_model" not in inputs:
                        inputs["strength_model"] = float(lora_strength)
                        print(f"[ExecutionEngine]   Added strength_model = {lora_strength}")
                    if "strength_clip" not in inputs:
                        inputs["strength_clip"] = float(lora_strength)
                        print(f"[ExecutionEngine]   Added strength_clip = {lora_strength}")

                    continue

                # Non-LoRA loader injection
                value_key = value_map.get(category)
                if value_key and user_values.get(value_key):
                    # Inject the value (will add parameter if it doesn't exist)
                    inputs[target_param] = user_values[value_key]
                    injected.append(f"{target_node_id}.{target_param} ({category})")
                    print(f"[ExecutionEngine] ✓ Injected {category}: {user_values[value_key][:30]}... into node {target_node_id}")
        else:
            # Fallback: Old blanket injection (if loaders not discovered)
            for node_id, node_data in prompt.items():
                inputs = node_data.get("inputs", {})

                if "ckpt_name" in inputs and user_values.get("checkpoint"):
                    inputs["ckpt_name"] = user_values["checkpoint"]
                    injected.append(f"{node_id}.ckpt_name")

                if "unet_name" in inputs and user_values.get("checkpoint"):
                    inputs["unet_name"] = user_values["checkpoint"]
                    injected.append(f"{node_id}.unet_name")

                if "lora_name" in inputs:
                    fallback_lora = user_values.get("lora")
                    if not fallback_lora:
                        fallback_lora = next(
                            (slot["name"] for slot in user_values.get("loras", []) if slot.get("enabled") and slot.get("name")),
                            None
                        )
                    if fallback_lora:
                        inputs["lora_name"] = fallback_lora
                        injected.append(f"{node_id}.lora_name")

                if "vae_name" in inputs and user_values.get("vae"):
                    inputs["vae_name"] = user_values["vae"]
                    injected.append(f"{node_id}.vae_name")

        if injected:
            print(f"[ExecutionEngine] Injected values: {', '.join(injected)}")
        else:
            print(f"[ExecutionEngine] WARNING: No values were injected (workflow might not have compatible nodes)")

        # Fourth pass: attach uploaded image/mask to appropriate nodes
        prompt = self._inject_images_and_masks(prompt, user_values)

        return prompt

    def _inject_images_and_masks(
        self,
        prompt: Dict[str, Any],
        user_values: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Attach uploaded image and mask paths to workflow nodes.

        Strategy:
        - If a node is an image loader (LoadImage/ImageInput/etc.), override its
          primary image parameter.
        - For any node with an editable input containing "image" or "mask",
          replace unlinked values with the uploaded path.
        """
        image_entries = [
            {"image": user_values.get("image_path"), "mask": user_values.get("mask_path")},
            {"image": user_values.get("image_path_2"), "mask": user_values.get("mask_path_2")},
        ]
        image_entries = [entry for entry in image_entries if entry.get("image") or entry.get("mask")]

        if not image_entries:
            return prompt

        print(f"[ExecutionEngine] Image/mask injection starting: {len(image_entries)} input(s)")

        def _is_linked(value: Any) -> bool:
            return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)

        replacements = []

        def _smart_image_node_sort_key(item: tuple) -> tuple:
            """
            Smart sorting for image input nodes using multiple heuristics:
            1. Connectivity (connected nodes before disconnected)
            2. Node type specificity (LoadImageOutput before LoadImage)
            3. Position (Y-coordinate, then X-coordinate) - top-to-bottom, left-to-right
            4. Title heuristics (primary/main before secondary/mask/reference)
            5. Node ID (numeric before alphabetic, then by value)

            Args:
                item: Tuple of (node_id, node_data)

            Returns:
                Sort key tuple
            """
            node_id, node_data = item

            # Extract metadata
            meta = node_data.get("_meta", {})
            title = meta.get("title", "").lower()
            pos = meta.get("pos", None)
            class_type = node_data.get("class_type", "")

            # Priority 0: Check if node is connected/used in workflow
            # A node with no output links is likely unused
            # This check happens during workflow-to-API conversion where links are removed
            # So we use a heuristic: if inputs have values (not just links), node is likely active
            inputs = node_data.get("inputs", {})
            has_input_values = any(
                v is not None and not (isinstance(v, list) and len(v) == 2)
                for v in inputs.values()
            )
            is_connected = 1 if not has_input_values else 0  # 0 = connected (higher priority)

            # Priority 1: Node type specificity
            # LoadImageOutput > LoadAndResizeImage > LoadImage
            type_priority = 2  # Default
            if class_type == "LoadImageOutput":
                type_priority = 0  # Highest priority (most specific)
            elif class_type == "LoadAndResizeImage":
                type_priority = 1  # Medium priority
            elif class_type == "LoadImage":
                type_priority = 2  # Lowest priority (most generic)

            # Priority 2: Title-based heuristics
            # Deprioritize nodes with "secondary", "mask", "reference", "controlnet", "depth" in title
            secondary_keywords = ["secondary", "mask", "reference", "controlnet", "depth", "canny", "pose"]
            is_secondary = any(keyword in title for keyword in secondary_keywords)

            # Prioritize nodes with "primary", "main", "input", "source" in title
            primary_keywords = ["primary", "main", "source", "base"]
            is_primary = any(keyword in title for keyword in primary_keywords)

            if is_primary:
                title_priority = 1  # High priority
            elif is_secondary:
                title_priority = 3  # Low priority
            else:
                title_priority = 2  # Medium priority

            # Priority 3: Use position if available (Y-coordinate primary, X-coordinate secondary)
            if pos and isinstance(pos, list) and len(pos) >= 2:
                y_pos = float(pos[1])  # Y-coordinate (vertical position)
                x_pos = float(pos[0])  # X-coordinate (horizontal position)
                return (is_connected, type_priority, 0, y_pos, x_pos, title_priority, node_id)

            # Priority 4: Node ID as final tiebreaker
            if isinstance(node_id, str) and node_id.isdigit():
                return (is_connected, type_priority, 1, 0, 0, title_priority, 0, int(node_id))
            else:
                return (is_connected, type_priority, 1, 0, 0, title_priority, 1, str(node_id))

        if len(image_entries) == 1:
            image_path = image_entries[0].get("image")
            mask_path = image_entries[0].get("mask")

            print(f"[ExecutionEngine] Image/mask injection paths: image={image_path}, mask={mask_path}")

            for node_id, node_data in prompt.items():
                if not isinstance(node_data, dict):
                    continue

                class_type = node_data.get("class_type", "")
                inputs = node_data.get("inputs", {})

                # Only inject images into known image input nodes
                if image_path and class_type in IMAGE_INPUT_NODE_TYPES:
                    if "image" in inputs:
                        inputs["image"] = image_path
                        replacements.append(f"{node_id}.image -> {image_path}")
                    # Also inject mask if loader exposes one
                    if mask_path and "mask" in inputs:
                        inputs["mask"] = mask_path
                        replacements.append(f"{node_id}.mask -> {mask_path}")

                # Heuristic fallback by name for other unlinked image fields
                for input_name, input_value in inputs.items():
                    is_linked = _is_linked(input_value)

                    lower_name = input_name.lower()

                    if image_path and ("image" in lower_name) and ("mask" not in lower_name) and not is_linked:
                        inputs[input_name] = image_path
                        replacements.append(f"{node_id}.{input_name} -> {image_path} (name)")
                    if mask_path and "mask" in lower_name and not is_linked:
                        inputs[input_name] = mask_path
                        replacements.append(f"{node_id}.{input_name} -> {mask_path} (name)")
        else:
            image_nodes = [
                (node_id, node_data)
                for node_id, node_data in prompt.items()
                if isinstance(node_data, dict) and node_data.get("class_type", "") in IMAGE_INPUT_NODE_TYPES
            ]
            # Use smart sorting: position-based > title-based > node ID
            image_nodes.sort(key=_smart_image_node_sort_key)

            # Debug: Log the sorted order
            print("[ExecutionEngine] Sorted image input nodes:")
            for idx, (node_id, node_data) in enumerate(image_nodes, 1):
                meta = node_data.get("_meta", {})
                title = meta.get("title", f"Node {node_id}")
                pos = meta.get("pos", None)
                print(f"  {idx}. Node {node_id}: '{title}' at position {pos}")

            for index, (node_id, node_data) in enumerate(image_nodes):
                if index >= len(image_entries):
                    break

                entry = image_entries[index]
                image_path = entry.get("image")
                mask_path = entry.get("mask")
                inputs = node_data.get("inputs", {})

                if image_path and "image" in inputs:
                    inputs["image"] = image_path
                    replacements.append(f"{node_id}.image -> {image_path} (slot {index + 1})")
                if mask_path and "mask" in inputs:
                    inputs["mask"] = mask_path
                    replacements.append(f"{node_id}.mask -> {mask_path} (slot {index + 1})")

        if replacements:
            print(f"[ExecutionEngine] Injected image/mask into nodes: {', '.join(replacements)}")
        else:
            print("[ExecutionEngine] WARNING: Uploaded image/mask provided but no matching inputs were found")

        return prompt
