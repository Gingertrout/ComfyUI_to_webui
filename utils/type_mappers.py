"""
Type Mappers

This module provides factories to convert ComfyUI input type schemas
into appropriate Gradio UI components.

ComfyUI /object_info schema format:
{
  "NodeClass": {
    "input": {
      "required": {
        "param_name": ["TYPE", {"default": value, "min": ..., "max": ...}]
      },
      "optional": {...}
    }
  }
}

Type examples:
- ["INT", {"default": 20, "min": 1, "max": 1000}]
- ["FLOAT", {"default": 7.0, "min": 0.0, "max": 100.0, "step": 0.1}]
- ["STRING", {"multiline": True}]
- [["option1", "option2", "option3"], {}]  # COMBO
- ["BOOLEAN", {}]
"""

import gradio as gr
from typing import Any, Optional, Union, List

from ..config import (
    PRIMITIVE_TYPES,
    COMPLEX_TYPES,
    DEFAULT_UI_CONFIG,
    UIConfig
)


class TypeMapper:
    """
    Factory for creating Gradio components from ComfyUI type schemas
    """

    def __init__(self, ui_config: Optional[UIConfig] = None):
        """
        Initialize type mapper

        Args:
            ui_config: UI generation configuration (uses default if None)
        """
        self.ui_config = ui_config or DEFAULT_UI_CONFIG

    def create_component(
        self,
        input_name: str,
        input_schema: Any,
        current_value: Any,
        node_title: str = "",
        node_id: str = ""
    ) -> gr.components.Component:
        """
        Create Gradio component from ComfyUI input schema

        Args:
            input_name: Name of the input parameter
            input_schema: Schema from /object_info (e.g., ["INT", {...}])
            current_value: Current value from workflow
            node_title: Human-readable node title
            node_id: Node identifier

        Returns:
            Gradio component (Slider, Textbox, Dropdown, etc.)
        """
        # Generate label
        label = self._generate_label(input_name, node_title, node_id)

        # Handle None or invalid schema
        if not input_schema or not isinstance(input_schema, (list, tuple)):
            return self._create_fallback_component(label, current_value)

        # Extract type definition and metadata
        type_def = input_schema[0]
        metadata = input_schema[1] if len(input_schema) > 1 else {}

        # COMBO type (list of choices)
        if isinstance(type_def, list):
            return self._create_dropdown(label, type_def, current_value, metadata)

        # INT type
        if type_def in {"INT", "INTEGER"}:
            return self._create_int_component(label, current_value, metadata)

        # FLOAT type
        if type_def in {"FLOAT", "DOUBLE"}:
            return self._create_float_component(label, current_value, metadata)

        # STRING type
        if type_def == "STRING":
            return self._create_string_component(label, current_value, metadata)

        # BOOLEAN type
        if type_def in {"BOOLEAN", "BOOL"}:
            return self._create_boolean_component(label, current_value, metadata)

        # Complex types (MODEL, IMAGE, LATENT, etc.) - non-editable
        if type_def in COMPLEX_TYPES:
            return self._create_complex_type_display(label, type_def)

        # Unknown type - fallback
        return self._create_fallback_component(label, current_value, type_def)

    def _generate_label(
        self,
        input_name: str,
        node_title: str,
        node_id: str
    ) -> str:
        """
        Generate human-readable label for component

        Args:
            input_name: Parameter name
            node_title: Node title
            node_id: Node ID

        Returns:
            Formatted label string
        """
        if node_title and node_title != node_id:
            return f"{node_title} › {input_name}"
        else:
            return f"{node_id} › {input_name}"

    def _create_int_component(
        self,
        label: str,
        value: Any,
        metadata: dict
    ) -> Union[gr.Slider, gr.Number]:
        """Create component for INT type"""
        min_val = metadata.get("min", 0)
        max_val = metadata.get("max", 10000)
        default = metadata.get("default", value if value is not None else 0)
        step = metadata.get("step", 1)

        # Use slider if range is reasonable and preference set
        if (
            self.ui_config.prefer_sliders and
            (max_val - min_val) <= self.ui_config.int_slider_threshold
        ):
            return gr.Slider(
                label=label,
                minimum=min_val,
                maximum=max_val,
                value=int(value) if value is not None else int(default),
                step=step
            )
        else:
            return gr.Number(
                label=label,
                value=int(value) if value is not None else int(default),
                precision=0,
                minimum=min_val,
                maximum=max_val
            )

    def _create_float_component(
        self,
        label: str,
        value: Any,
        metadata: dict
    ) -> Union[gr.Slider, gr.Number]:
        """Create component for FLOAT type"""
        min_val = metadata.get("min", 0.0)
        max_val = metadata.get("max", 100.0)
        default = metadata.get("default", value if value is not None else 0.0)
        step = metadata.get("step", 0.01)

        # Use slider if range is reasonable and preference set
        if (
            self.ui_config.prefer_sliders and
            (max_val - min_val) <= self.ui_config.float_slider_threshold
        ):
            return gr.Slider(
                label=label,
                minimum=min_val,
                maximum=max_val,
                value=float(value) if value is not None else float(default),
                step=step
            )
        else:
            return gr.Number(
                label=label,
                value=float(value) if value is not None else float(default),
                minimum=min_val,
                maximum=max_val,
                step=step
            )

    def _create_string_component(
        self,
        label: str,
        value: Any,
        metadata: dict
    ) -> gr.Textbox:
        """Create component for STRING type"""
        multiline = metadata.get("multiline", False)
        default = metadata.get("default", value if value is not None else "")

        # Auto-detect multiline if not specified
        if not multiline and isinstance(default, str):
            multiline = len(default) > self.ui_config.multiline_threshold

        return gr.Textbox(
            label=label,
            value=str(value) if value is not None else str(default),
            lines=5 if multiline else 1,
            max_lines=20 if multiline else 1
        )

    def _create_boolean_component(
        self,
        label: str,
        value: Any,
        metadata: dict
    ) -> gr.Checkbox:
        """Create component for BOOLEAN type"""
        default = metadata.get("default", value if value is not None else False)

        return gr.Checkbox(
            label=label,
            value=bool(value) if value is not None else bool(default)
        )

    def _create_dropdown(
        self,
        label: str,
        choices: List[str],
        value: Any,
        metadata: dict
    ) -> gr.Dropdown:
        """Create dropdown for COMBO type"""
        default = metadata.get("default", value)

        # Ensure value is in choices
        if value not in choices and choices:
            value = choices[0]
        elif value is None and choices:
            value = choices[0]

        return gr.Dropdown(
            label=label,
            choices=choices,
            value=value
        )

    def _create_complex_type_display(
        self,
        label: str,
        type_name: str
    ) -> gr.Markdown:
        """
        Create read-only display for complex types (MODEL, IMAGE, etc.)

        These inputs are typically connected to other nodes and can't be
        edited directly via UI.
        """
        if not self.ui_config.show_linked_inputs:
            # Return invisible component
            return gr.Markdown(visible=False)

        return gr.Markdown(
            value=f"**{label}** (type: `{type_name}`)  \n_Connected to upstream node_",
            visible=True
        )

    def _create_fallback_component(
        self,
        label: str,
        value: Any,
        type_name: str = "UNKNOWN"
    ) -> gr.Textbox:
        """
        Fallback component for unknown types

        Args:
            label: Component label
            value: Current value
            type_name: Type identifier

        Returns:
            Textbox component
        """
        return gr.Textbox(
            label=f"{label} ({type_name})",
            value=str(value) if value is not None else "",
            placeholder=f"Enter {type_name} value..."
        )


class ComponentValueExtractor:
    """
    Helper class to extract values from Gradio components and convert
    back to ComfyUI-compatible types
    """

    @staticmethod
    def extract_value(component: gr.components.Component, type_schema: Any) -> Any:
        """
        Extract value from Gradio component and convert to correct type

        Args:
            component: Gradio component
            type_schema: Original ComfyUI type schema

        Returns:
            Value in ComfyUI-compatible format
        """
        value = component.value

        # Extract type from schema
        if not type_schema or not isinstance(type_schema, (list, tuple)):
            return value

        type_def = type_schema[0]

        # Type conversion
        if type_def in {"INT", "INTEGER"}:
            return int(value) if value is not None else 0
        elif type_def in {"FLOAT", "DOUBLE"}:
            return float(value) if value is not None else 0.0
        elif type_def in {"BOOLEAN", "BOOL"}:
            return bool(value)
        elif type_def == "STRING":
            return str(value) if value is not None else ""
        elif isinstance(type_def, list):  # COMBO
            return value
        else:
            return value
