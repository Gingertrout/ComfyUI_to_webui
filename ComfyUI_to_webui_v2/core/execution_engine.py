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
        user_values: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        Execute a workflow with optional user-provided values

        Args:
            workflow: Original workflow JSON (API format)
            generated_ui: Generated UI structure (contains current values)
            user_values: User-provided values (future: from interactive UI)

        Returns:
            ExecutionResult with prompt_id and status
        """
        # Generate unique client ID
        client_id = str(uuid.uuid4())

        try:
            print(f"[ExecutionEngine] Building prompt for client_id: {client_id}")

            # Build execution prompt
            prompt = self._build_execution_prompt(
                workflow,
                generated_ui,
                user_values
            )

            print(f"[ExecutionEngine] Prompt has {len(prompt)} nodes")

            # Submit to ComfyUI
            print(f"[ExecutionEngine] Submitting to ComfyUI...")
            response = self.client.submit_prompt(prompt, client_id)

            print(f"[ExecutionEngine] Response received: prompt_id={response.prompt_id}")

            # Check for node errors
            if response.node_errors:
                print(f"[ExecutionEngine] Node errors detected: {response.node_errors}")
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
        user_values: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build execution prompt from workflow and user values

        For Phase 2: Just use the workflow as-is (no user edits yet)
        Future: Inject user_values from interactive UI components

        Args:
            workflow: Original workflow
            generated_ui: UI structure with components
            user_values: User-provided values

        Returns:
            Execution prompt ready for /prompt endpoint
        """
        # For Phase 2 MVP: Clone workflow and use as-is
        prompt = copy.deepcopy(workflow)

        # Future Phase: Inject user values
        # if user_values and generated_ui:
        #     prompt = self._inject_user_values(prompt, generated_ui, user_values)

        return prompt

    def _inject_user_values(
        self,
        prompt: Dict[str, Any],
        generated_ui: GeneratedUI,
        user_values: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Inject user-provided values into prompt (Future Phase)

        Args:
            prompt: Execution prompt
            generated_ui: UI structure
            user_values: Values from UI components

        Returns:
            Updated prompt
        """
        # Future implementation: Update prompt with user values
        # For each component in generated_ui:
        #   - Get user value from user_values dict
        #   - Update corresponding node input in prompt

        for comp_info in generated_ui.components:
            node_id = comp_info.node_id
            input_name = comp_info.input_name

            # Get user value (example - actual implementation will vary)
            if node_id in user_values and input_name in user_values[node_id]:
                new_value = user_values[node_id][input_name]

                # Update prompt
                if node_id in prompt and "inputs" in prompt[node_id]:
                    prompt[node_id]["inputs"][input_name] = new_value

        return prompt
