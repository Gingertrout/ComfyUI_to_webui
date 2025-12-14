"""
Workflow Utilities

This module provides utilities for working with ComfyUI workflow JSON files.
Includes conversion between workflow format (graph) and API format (prompt).

Copied and adapted from V1 kelnel_ui/ui_def.py:283-386
"""

import json
from typing import Dict, Any, Optional


def convert_workflow_to_prompt(workflow_data: dict) -> dict:
    """
    Convert a ComfyUI workflow (graph) JSON to the API prompt dictionary structure.

    Workflow format has:
    - "nodes": list of node objects with id, type, widgets_values, inputs
    - "links": list of connections between nodes

    API format has:
    - Direct dictionary: {node_id: {class_type, inputs}}

    Args:
        workflow_data: Workflow JSON dictionary

    Returns:
        Prompt dictionary in API format
    """
    prompt = {}
    link_lookup = {}

    # Build link lookup table
    for link in workflow_data.get("links", []):
        # Expected format: [link_id, from_node_id, from_slot, to_node_id, to_slot, type]
        if not isinstance(link, list) or len(link) < 5:
            continue
        link_id, from_node, from_slot, *_rest = link
        try:
            link_lookup[int(link_id)] = (str(from_node), from_slot)
        except (TypeError, ValueError):
            continue

    extra_meta = workflow_data.get("extra", {}).get("nodeMetadata", {}) or {}

    # Convert each node
    for node in workflow_data.get("nodes", []):
        try:
            node_id = str(node["id"])
        except (KeyError, TypeError):
            continue

        inputs_map = {}
        widget_values = list(node.get("widgets_values") or [])
        widget_index = 0
        extra_widget_values = []

        def _matches_expected(expected_type, candidate):
            """Check if candidate value matches expected type"""
            if expected_type is None:
                return True
            if candidate is None:
                return True
            expected_upper = str(expected_type).upper()
            if expected_upper in {"INT", "INTEGER"}:
                return isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
            if expected_upper in {"FLOAT", "DOUBLE"}:
                return isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
            if expected_upper in {"BOOLEAN", "BOOL"}:
                if isinstance(candidate, bool):
                    return True
                if isinstance(candidate, str):
                    return candidate.lower() in {"true", "false", "enable", "disable"}
                return False
            if expected_upper == "STRING":
                return isinstance(candidate, str)
            if expected_upper == "COMBO":
                return isinstance(candidate, (str, int, float, bool))
            # For other custom types (MODEL, IMAGE, etc.), accept any primitive
            return True

        def _consume_widget_value(expected_type):
            """Consume next widget value matching expected type"""
            nonlocal widget_index
            while widget_index < len(widget_values):
                candidate = widget_values[widget_index]
                widget_index += 1
                if _matches_expected(expected_type, candidate):
                    return candidate
                extra_widget_values.append(candidate)
            return None

        # Process node inputs
        for input_def in node.get("inputs", []):
            name = input_def.get("name")
            if not name:
                continue

            # Check if input is linked
            link_id = input_def.get("link")
            if link_id is not None:
                link_entry = (
                    link_lookup.get(int(link_id))
                    if isinstance(link_id, int)
                    else link_lookup.get(link_id)
                )
                if link_entry:
                    inputs_map[name] = [link_entry[0], link_entry[1]]
                continue

            # Get value from widgets
            if "widget" in input_def:
                value = _consume_widget_value(input_def.get("type"))
            else:
                value = None
            inputs_map[name] = value

        # Capture any remaining widget values
        if widget_index < len(widget_values):
            extra_widget_values.extend(widget_values[widget_index:])

        # Build prompt entry
        prompt_entry = {
            "class_type": node.get("type"),
            "inputs": inputs_map
        }

        # Extract title metadata
        title = None
        node_properties = node.get("properties") or {}
        title = node_properties.get("Node name for S&R") or node_properties.get("title")
        if not title:
            meta_entry = extra_meta.get(node_id)
            if isinstance(meta_entry, dict):
                title = meta_entry.get("title")
        if title:
            prompt_entry["_meta"] = {"title": title}
        if extra_widget_values:
            prompt_entry.setdefault("_meta", {}).setdefault("info", {})[
                "unused_widget_values"
            ] = extra_widget_values

        prompt[node_id] = prompt_entry

    return prompt


def load_workflow_from_file(file_path: str) -> Dict[str, Any]:
    """
    Load workflow JSON from file and convert to API format if needed

    Args:
        file_path: Path to workflow JSON file

    Returns:
        Workflow in API prompt format

    Raises:
        ValueError: If file cannot be parsed
        FileNotFoundError: If file doesn't exist
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Check format
    if "nodes" in data and "links" in data:
        # Workflow format - convert to API format
        return convert_workflow_to_prompt(data)
    else:
        # Already in API format
        return data


def is_workflow_format(data: Dict[str, Any]) -> bool:
    """
    Check if JSON is in workflow format (vs API format)

    Args:
        data: Loaded JSON dictionary

    Returns:
        True if workflow format, False if API format
    """
    return "nodes" in data and "links" in data
