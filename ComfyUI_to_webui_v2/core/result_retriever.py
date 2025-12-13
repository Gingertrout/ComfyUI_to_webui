"""
Result Retriever

This module handles retrieving generated images/videos from ComfyUI:
- Poll /history for execution completion
- Extract output files from SaveImage/VHS_VideoCombine nodes
- Resolve file paths in ComfyUI output directory
- Fallback strategies for reliable result detection

Uses standard ComfyUI nodes (no custom Hua_Output nodes required)
"""

import time
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from .comfyui_client import ComfyUIClient
from ..config import OUTPUT_NODE_TYPES


@dataclass
class RetrievalResult:
    """Result of attempting to retrieve outputs"""
    success: bool
    images: List[str] = None  # List of image file paths
    videos: List[str] = None  # List of video file paths
    error: Optional[str] = None

    def __post_init__(self):
        if self.images is None:
            self.images = []
        if self.videos is None:
            self.videos = []


class ResultRetriever:
    """
    Retrieves execution results from ComfyUI

    Strategy:
    1. Poll /history until prompt_id appears
    2. Extract outputs from SaveImage/VHS_VideoCombine nodes
    3. Resolve file paths in output directory
    4. Fallback to filesystem scan if needed
    """

    def __init__(self, comfyui_client: ComfyUIClient):
        """
        Initialize result retriever

        Args:
            comfyui_client: ComfyUI API client
        """
        self.client = comfyui_client
        self._output_dir = self._get_output_directory()

    def _get_output_directory(self) -> Path:
        """Get ComfyUI output directory"""
        try:
            import folder_paths
            return Path(folder_paths.get_output_directory())
        except:
            # Fallback: common locations
            possible_paths = [
                Path("/home/oconnorja/Unstable-Diffusion/ComfyUI/output"),
                Path.cwd().parent.parent.parent / "output",
            ]
            for path in possible_paths:
                if path.exists():
                    return path
            return Path("/tmp/comfyui_output")

    def retrieve_results(
        self,
        prompt_id: str,
        client_id: str,
        workflow: Dict[str, Any],
        timeout: float = 300
    ) -> RetrievalResult:
        """
        Retrieve results from a completed execution

        Args:
            prompt_id: Prompt ID from submission
            client_id: Client ID used for submission
            workflow: Original workflow (to identify output nodes)
            timeout: Max time to wait for completion (seconds)

        Returns:
            RetrievalResult with file paths
        """
        try:
            print(f"[ResultRetriever] Waiting for prompt_id={prompt_id}, client_id={client_id}, timeout={timeout}s")

            # Check if workflow has output nodes
            has_output_nodes = any(
                node.get("class_type") in OUTPUT_NODE_TYPES
                for node in workflow.values()
                if isinstance(node, dict)
            )
            print(f"[ResultRetriever] Workflow has output nodes: {has_output_nodes}")
            if has_output_nodes:
                output_node_types = [
                    node.get("class_type")
                    for node in workflow.values()
                    if isinstance(node, dict) and node.get("class_type") in OUTPUT_NODE_TYPES
                ]
                print(f"[ResultRetriever] Output node types found: {output_node_types}")

            # Wait for completion
            history_entry = self.client.wait_for_prompt_completion(
                prompt_id,
                client_id,
                timeout
            )

            print(f"[ResultRetriever] History entry received: {history_entry is not None}")

            if not history_entry:
                print(f"[ResultRetriever] ERROR: Timed out after {timeout}s")
                return RetrievalResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s"
                )

            # Check for errors
            status = history_entry.get("status", {})
            print(f"[ResultRetriever] Status: {status}")

            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                error_msg = "; ".join(str(msg) for msg in messages)
                print(f"[ResultRetriever] ERROR: Execution failed: {error_msg}")
                return RetrievalResult(
                    success=False,
                    error=f"Execution failed: {error_msg}"
                )

            # Extract outputs from history
            print(f"[ResultRetriever] Extracting outputs from history...")
            print(f"[ResultRetriever] History entry keys: {list(history_entry.keys())}")
            print(f"[ResultRetriever] Outputs in history: {history_entry.get('outputs', {})}")

            images, videos = self._extract_outputs_from_history(history_entry)

            print(f"[ResultRetriever] Extracted from history: {len(images)} images, {len(videos)} videos")

            if images or videos:
                print(f"[ResultRetriever] SUCCESS: Found outputs in history")
                return RetrievalResult(
                    success=True,
                    images=images,
                    videos=videos
                )

            # Fallback: scan output directory
            print(f"[ResultRetriever] No outputs in history, trying filesystem scan...")
            print(f"[ResultRetriever] Output directory: {self._output_dir}")

            images, videos = self._fallback_scan_outputs(workflow)

            print(f"[ResultRetriever] Extracted from filesystem: {len(images)} images, {len(videos)} videos")

            if images or videos:
                print(f"[ResultRetriever] SUCCESS: Found outputs via filesystem scan")
                return RetrievalResult(
                    success=True,
                    images=images,
                    videos=videos
                )

            print(f"[ResultRetriever] ERROR: No outputs found in history or filesystem")
            return RetrievalResult(
                success=False,
                error="No outputs found in history or filesystem"
            )

        except Exception as e:
            return RetrievalResult(
                success=False,
                error=f"Error retrieving results: {str(e)}"
            )

    def _extract_outputs_from_history(
        self,
        history_entry: Dict[str, Any]
    ) -> tuple[List[str], List[str]]:
        """
        Extract output file paths from history entry

        ComfyUI history structure:
        {
          "outputs": {
            "node_id": {
              "images": [{"filename": "...", "subfolder": "...", "type": "output"}],
              "gifs": [...]
            }
          }
        }

        Args:
            history_entry: History entry from /history/{client_id}

        Returns:
            Tuple of (image_paths, video_paths)
        """
        images = []
        videos = []

        outputs = history_entry.get("outputs", {})

        for node_id, node_outputs in outputs.items():
            # Extract images from SaveImage nodes
            for img_info in node_outputs.get("images", []):
                path = self._resolve_output_path(
                    img_info.get("filename"),
                    img_info.get("subfolder", ""),
                    img_info.get("type", "output")
                )
                if path and path.exists():
                    images.append(str(path))

            # Extract videos from VHS_VideoCombine nodes
            for video_info in node_outputs.get("gifs", []):
                path = self._resolve_output_path(
                    video_info.get("filename"),
                    video_info.get("subfolder", ""),
                    video_info.get("type", "output")
                )
                if path and path.exists():
                    videos.append(str(path))

        return images, videos

    def _resolve_output_path(
        self,
        filename: Optional[str],
        subfolder: str,
        output_type: str
    ) -> Optional[Path]:
        """
        Resolve filename to absolute path in output directory

        Args:
            filename: Output filename
            subfolder: Subfolder within output directory
            output_type: Output type ("output", "temp", etc.)

        Returns:
            Path object or None if invalid
        """
        if not filename:
            return None

        # Build path
        if subfolder:
            path = self._output_dir / subfolder / filename
        else:
            path = self._output_dir / filename

        return path if path.exists() else None

    def _fallback_scan_outputs(
        self,
        workflow: Dict[str, Any]
    ) -> tuple[List[str], List[str]]:
        """
        Fallback: Scan output directory for recent files

        Args:
            workflow: Workflow to extract filename prefix

        Returns:
            Tuple of (image_paths, video_paths)
        """
        images = []
        videos = []

        # Get recent files (last 60 seconds)
        cutoff_time = time.time() - 60

        try:
            for file_path in self._output_dir.rglob("*"):
                if not file_path.is_file():
                    continue

                if file_path.stat().st_mtime < cutoff_time:
                    continue

                # Check file extension
                ext = file_path.suffix.lower()

                if ext in {".png", ".jpg", ".jpeg", ".webp"}:
                    images.append(str(file_path))
                elif ext in {".mp4", ".webm", ".gif"}:
                    videos.append(str(file_path))

        except Exception:
            pass

        return images, videos
