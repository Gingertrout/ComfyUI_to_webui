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

        # First pass: collect all CLIPTextEncode nodes and guess which is positive/negative
        clip_nodes = []
        for node_id, node_data in prompt.items():
            class_type = node_data.get("class_type", "")
            if class_type == "CLIPTextEncode":
                node_title = node_data.get("_meta", {}).get("title", "").lower()
                original_text = node_data.get("inputs", {}).get("text", "").lower()

                # Guess type based on content and title
                is_negative = (
                    "negative" in node_title or
                    any(word in original_text for word in ["bad", "ugly", "worst", "low quality", "watermark", "3d", "cg"])
                )

                clip_nodes.append((node_id, node_data, node_title, is_negative, original_text))
                print(f"[ExecutionEngine] Found CLIPTextEncode node {node_id}: title='{node_title}', is_negative={is_negative}")

        # Sort nodes: positive first, then negative
        clip_nodes.sort(key=lambda x: x[3])  # False (positive) comes before True (negative)

        # Inject prompts into CLIPTextEncode nodes
        positive_injected = False
        negative_injected = False

        for node_id, node_data, node_title, is_negative, original_text in clip_nodes:
            inputs = node_data.get("inputs", {})

            # Inject positive prompt to positive node
            if not positive_injected and not is_negative and user_values.get("positive_prompt"):
                new_text = user_values["positive_prompt"]
                inputs["text"] = new_text
                injected.append(f"{node_id}.text (POSITIVE: '{new_text[:30]}...')")
                positive_injected = True
                print(f"[ExecutionEngine]   ✓ POSITIVE Node {node_id}: '{original_text[:50]}...' -> '{new_text[:50]}...'")
                continue

            # Inject negative prompt to negative node
            if not negative_injected and is_negative and user_values.get("negative_prompt") is not None:
                new_text = user_values["negative_prompt"] if user_values["negative_prompt"] else ""
                inputs["text"] = new_text
                injected.append(f"{node_id}.text (NEGATIVE: '{new_text[:30]}...')")
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

                value_key = value_map.get(category)
                if value_key and user_values.get(value_key):
                    # For LoRA, handle None/empty selection
                    lora_value = user_values[value_key]
                    if category == "lora" and lora_value in ["None", "", None]:
                        print(f"[ExecutionEngine] Skipping LoRA injection (None selected)")
                        continue

                    # Inject the value (will add parameter if it doesn't exist)
                    inputs[target_param] = user_values[value_key]
                    injected.append(f"{target_node_id}.{target_param} ({category})")
                    print(f"[ExecutionEngine] ✓ Injected {category}: {user_values[value_key][:30]}... into node {target_node_id}")

                    # For LoRA loaders, handle different formats
                    if category == "lora":
                        class_type = target_node.get("class_type", "")

                        # Power Lora Loader (rgthree) uses a special dict format
                        if "Power Lora Loader" in class_type:
                            # rgthree expects UPPERCASE parameter names with dict values
                            # Format: LORA_01 = {'on': True, 'lora': 'filename.safetensors', 'strength': 1.0}

                            # Remove the lowercase string value we just added
                            if target_param in inputs:
                                lora_filename = inputs.pop(target_param)
                            else:
                                lora_filename = user_values[value_key]

                            # Get strength from user values (default to 1.0 if not provided)
                            lora_strength = user_values.get("lora_strength", 1.0)

                            # Add it back in the proper format
                            uppercase_param = target_param.upper()  # e.g., lora_01 -> LORA_01
                            inputs[uppercase_param] = {
                                'on': True,
                                'lora': lora_filename,
                                'strength': float(lora_strength),
                                'strengthTwo': None  # Optional: separate clip strength
                            }
                            print(f"[ExecutionEngine]   Formatted for rgthree: {uppercase_param} = {inputs[uppercase_param]}")

                        # Standard LoRA loaders use strength_model and strength_clip
                        else:
                            # Get strength from user values (default to 1.0 if not provided)
                            lora_strength = user_values.get("lora_strength", 1.0)

                            if "strength_model" not in inputs:
                                inputs["strength_model"] = float(lora_strength)
                                print(f"[ExecutionEngine]   Added strength_model = {lora_strength}")
                            if "strength_clip" not in inputs:
                                inputs["strength_clip"] = float(lora_strength)
                                print(f"[ExecutionEngine]   Added strength_clip = {lora_strength}")
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

                if "lora_name" in inputs and user_values.get("lora"):
                    inputs["lora_name"] = user_values["lora"]
                    injected.append(f"{node_id}.lora_name")

                if "vae_name" in inputs and user_values.get("vae"):
                    inputs["vae_name"] = user_values["vae"]
                    injected.append(f"{node_id}.vae_name")

        if injected:
            print(f"[ExecutionEngine] Injected values: {', '.join(injected)}")
        else:
            print(f"[ExecutionEngine] WARNING: No values were injected (workflow might not have compatible nodes)")

        return prompt
