"""
ComfyUI API Client

This module provides a clean abstraction layer for all ComfyUI HTTP API interactions.
Handles requests to /prompt, /object_info, /history, /queue endpoints with retry logic.
"""

import requests
import time
import uuid
from typing import Dict, Optional, Any, List
from dataclasses import dataclass

from ..config import (
    COMFYUI_BASE_URL,
    ComfyUIEndpoints,
    DEFAULT_TIMEOUTS,
    TimeoutConfig
)


@dataclass
class PromptResponse:
    """Response from submitting a prompt"""
    prompt_id: str
    number: int
    node_errors: Dict[str, Any]


class ComfyUIClient:
    """
    Client for interacting with ComfyUI's HTTP API

    Provides methods for:
    - Submitting workflows (/prompt)
    - Querying node schemas (/object_info)
    - Retrieving execution history (/history)
    - Polling queue status (/queue)
    - Interrupting execution (/interrupt)
    """

    def __init__(
        self,
        base_url: str = COMFYUI_BASE_URL,
        timeout_config: Optional[TimeoutConfig] = None
    ):
        """
        Initialize ComfyUI client

        Args:
            base_url: ComfyUI server URL (default: http://127.0.0.1:8188)
            timeout_config: Timeout configuration (uses DEFAULT_TIMEOUTS if None)
        """
        self.base_url = base_url.rstrip('/')
        self.timeout_config = timeout_config or DEFAULT_TIMEOUTS
        self.session = requests.Session()
        self._object_info_cache: Optional[Dict] = None

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True
    ) -> requests.Response:
        """
        Make HTTP request with retry logic

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            json_data: JSON payload for POST requests
            params: URL query parameters
            retry: Whether to retry on failure

        Returns:
            requests.Response object

        Raises:
            requests.RequestException: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"
        max_retries = self.timeout_config.max_retries if retry else 1

        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json_data,
                    params=params,
                    timeout=self.timeout_config.http_request
                )
                response.raise_for_status()
                return response

            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(self.timeout_config.retry_delay)
                    continue
                raise

    def get_object_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Query /object_info endpoint to get schemas for all node types

        Response structure:
        {
          "NodeClassName": {
            "input": {
              "required": {
                "param_name": ["TYPE", {"default": ..., "min": ..., "max": ...}]
              },
              "optional": {...}
            },
            "output": ["OUTPUT_TYPE"],
            "output_name": [...],
            "category": "category/subcategory"
          }
        }

        Args:
            force_refresh: Force refresh cache (default: False)

        Returns:
            Dictionary mapping node class names to their schemas
        """
        if self._object_info_cache is not None and not force_refresh:
            return self._object_info_cache

        response = self._make_request("GET", ComfyUIEndpoints.OBJECT_INFO)
        self._object_info_cache = response.json()
        return self._object_info_cache

    def submit_prompt(
        self,
        prompt: Dict[str, Any],
        client_id: Optional[str] = None
    ) -> PromptResponse:
        """
        Submit workflow prompt to ComfyUI for execution

        Args:
            prompt: Workflow prompt in API format (node_id -> {class_type, inputs})
            client_id: Unique client identifier (generated if None)

        Returns:
            PromptResponse with prompt_id for tracking execution

        Example:
            >>> response = client.submit_prompt({
            ...     "1": {
            ...         "class_type": "KSampler",
            ...         "inputs": {"seed": 42, "steps": 20}
            ...     }
            ... })
            >>> print(response.prompt_id)
        """
        if client_id is None:
            client_id = str(uuid.uuid4())

        payload = {
            "prompt": prompt,
            "client_id": client_id
        }

        response = self._make_request("POST", ComfyUIEndpoints.PROMPT, json_data=payload)
        data = response.json()

        return PromptResponse(
            prompt_id=data.get("prompt_id", ""),
            number=data.get("number", 0),
            node_errors=data.get("node_errors", {})
        )

    def get_history(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Query /history endpoint to get execution results

        Response structure:
        {
          "prompt_id": {
            "prompt": [...],
            "outputs": {
              "node_id": {
                "images": [{"filename": "...", "subfolder": "...", "type": "output"}],
                "gifs": [...]
              }
            },
            "status": {
              "status_str": "success",
              "completed": true,
              "messages": []
            }
          }
        }

        Args:
            client_id: Client ID to filter history (optional)

        Returns:
            Dictionary mapping prompt_id to execution results
        """
        endpoint = (
            ComfyUIEndpoints.get_history_url(client_id)
            if client_id
            else ComfyUIEndpoints.HISTORY
        )

        response = self._make_request("GET", endpoint)
        return response.json()

    def get_queue(self) -> Dict[str, List]:
        """
        Query /queue endpoint to get current queue status

        Response structure:
        {
          "queue_running": [
            [number, prompt_id, {...}, class_type]
          ],
          "queue_pending": [...]
        }

        Returns:
            Dictionary with queue_running and queue_pending lists
        """
        response = self._make_request("GET", ComfyUIEndpoints.QUEUE)
        return response.json()

    def interrupt(self) -> bool:
        """
        Send interrupt signal to stop current execution

        Returns:
            True if interrupt was successful
        """
        try:
            self._make_request("POST", ComfyUIEndpoints.INTERRUPT, retry=False)
            return True
        except requests.RequestException:
            return False

    def wait_for_prompt_completion(
        self,
        prompt_id: str,
        client_id: str,
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Poll /history until prompt_id appears (blocking)

        Args:
            prompt_id: Prompt ID to wait for
            client_id: Client ID used for submission
            timeout: Max wait time in seconds (uses config default if None)

        Returns:
            History entry for prompt_id, or None if timeout
        """
        timeout = timeout or self.timeout_config.prompt_execution
        deadline = time.time() + timeout
        poll_interval = self.timeout_config.history_poll_interval

        while time.time() < deadline:
            try:
                history = self.get_history(client_id)
                if prompt_id in history:
                    return history[prompt_id]
            except requests.RequestException:
                pass  # Ignore errors, keep polling

            time.sleep(poll_interval)

        return None

    def poll_queue_until_done(
        self,
        prompt_id: str,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Poll /queue until prompt_id disappears from queue (blocking)

        This is used for workflows without output nodes where history API
        may not reliably return status.

        Args:
            prompt_id: Prompt ID to wait for
            timeout: Max wait time in seconds (uses config default if None)

        Returns:
            True if prompt completed, False if timeout
        """
        timeout = timeout or self.timeout_config.prompt_execution
        deadline = time.time() + timeout
        poll_interval = self.timeout_config.queue_poll_interval

        while time.time() < deadline:
            try:
                queue_data = self.get_queue()

                # Check if prompt_id in queue_running or queue_pending
                # Queue items are lists: [number, prompt_id, {...}, class_type]
                in_running = any(
                    item[1] == prompt_id
                    for item in queue_data.get("queue_running", [])
                )
                in_pending = any(
                    item[1] == prompt_id
                    for item in queue_data.get("queue_pending", [])
                )

                if not in_running and not in_pending:
                    return True  # Execution complete

            except requests.RequestException:
                pass  # Ignore errors, keep polling

            time.sleep(poll_interval)

        return False  # Timeout

    def close(self):
        """Close the HTTP session"""
        self.session.close()
