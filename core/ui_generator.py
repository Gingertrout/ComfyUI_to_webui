"""
UI Generator

This module generates Gradio UI components dynamically from ComfyUI workflows.
It queries /object_info for node schemas and creates appropriate input controls.

Key Innovation: NO hardcoded node types - works with ANY workflow!
"""

import gradio as gr
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .comfyui_client import ComfyUIClient
from .workflow_analyzer import WorkflowAnalyzer, AnalyzedNode
from ..utils.type_mappers import TypeMapper
from ..config import UIConfig, DEFAULT_UI_CONFIG


@dataclass
class ComponentInfo:
    """Information about a generated Gradio component"""
    component: gr.components.Component
    node_id: str
    input_name: str
    input_schema: Any  # Original schema from /object_info
    current_value: Any


@dataclass
class GeneratedUI:
    """Complete generated UI structure"""
    components: List[ComponentInfo] = field(default_factory=list)
    component_map: Dict[str, Dict[str, ComponentInfo]] = field(default_factory=dict)
    grouped_components: Dict[str, List[ComponentInfo]] = field(default_factory=dict)
    all_gradio_components: List[gr.components.Component] = field(default_factory=list)


class UIGenerator:
    """
    Dynamically generates Gradio UI from ComfyUI workflow JSON

    Workflow:
    1. Analyze workflow to find editable nodes
    2. Query /object_info for node type schemas
    3. Create Gradio components from schemas
    4. Group components by category (samplers, loaders, etc.)
    5. Return structured UI layout
    """

    def __init__(
        self,
        comfyui_client: ComfyUIClient,
        ui_config: Optional[UIConfig] = None
    ):
        """
        Initialize UI generator

        Args:
            comfyui_client: ComfyUI API client
            ui_config: UI generation configuration
        """
        self.client = comfyui_client
        self.analyzer = WorkflowAnalyzer()
        self.type_mapper = TypeMapper(ui_config or DEFAULT_UI_CONFIG)
        self.ui_config = ui_config or DEFAULT_UI_CONFIG
        self._object_info_cache: Optional[Dict] = None

    def generate_ui_for_workflow(
        self,
        workflow: Dict[str, Any]
    ) -> GeneratedUI:
        """
        Generate dynamic Gradio UI for a workflow

        Args:
            workflow: ComfyUI workflow in API format

        Returns:
            GeneratedUI object with components and metadata

        Example:
            >>> ui = generator.generate_ui_for_workflow(workflow_json)
            >>> for component_info in ui.components:
            ...     print(f"{component_info.node_id}.{component_info.input_name}")
        """
        generated_ui = GeneratedUI()

        # 1. Analyze workflow to find editable inputs
        analysis = self.analyzer.analyze_workflow(workflow)

        # 2. Fetch node schemas from /object_info
        if self._object_info_cache is None:
            self._object_info_cache = self.client.get_object_info()

        # 3. Generate components for each editable node
        for node in analysis.editable_nodes:
            node_components = self._generate_components_for_node(
                node,
                workflow
            )

            for comp_info in node_components:
                # Add to flat list
                generated_ui.components.append(comp_info)
                generated_ui.all_gradio_components.append(comp_info.component)

                # Add to node map
                if comp_info.node_id not in generated_ui.component_map:
                    generated_ui.component_map[comp_info.node_id] = {}
                generated_ui.component_map[comp_info.node_id][comp_info.input_name] = comp_info

                # Add to category group
                category = node.category or "other"
                if category not in generated_ui.grouped_components:
                    generated_ui.grouped_components[category] = []
                generated_ui.grouped_components[category].append(comp_info)

        return generated_ui

    def _generate_components_for_node(
        self,
        node: AnalyzedNode,
        workflow: Dict[str, Any]
    ) -> List[ComponentInfo]:
        """
        Generate Gradio components for a single node's editable inputs

        Args:
            node: Analyzed node from WorkflowAnalyzer
            workflow: Original workflow JSON

        Returns:
            List of ComponentInfo objects
        """
        components = []

        # Get schema for this node type
        node_schema = self._object_info_cache.get(node.class_type, {})
        input_schemas = node_schema.get("input", {})
        required_inputs = input_schemas.get("required", {})
        optional_inputs = input_schemas.get("optional", {})

        # Generate component for each editable input
        for node_input in node.inputs:
            # Skip linked inputs
            if node_input.is_linked:
                continue

            # Get schema for this input
            input_schema = (
                required_inputs.get(node_input.name) or
                optional_inputs.get(node_input.name)
            )

            # Create Gradio component
            component = self.type_mapper.create_component(
                input_name=node_input.name,
                input_schema=input_schema,
                current_value=node_input.value,
                node_title=node.title,
                node_id=node.node_id
            )

            components.append(ComponentInfo(
                component=component,
                node_id=node.node_id,
                input_name=node_input.name,
                input_schema=input_schema,
                current_value=node_input.value
            ))

        return components

    def build_grouped_layout(
        self,
        generated_ui: GeneratedUI
    ) -> gr.Column:
        """
        Build organized Gradio layout with grouped components

        Components are grouped by category:
        - Samplers (KSampler, etc.)
        - LoRA Loaders
        - Checkpoint Loaders
        - Other nodes

        Each group is in a collapsible accordion.

        Args:
            generated_ui: Generated UI structure

        Returns:
            Gradio Column containing the complete layout
        """
        with gr.Column() as layout:
            # Group components by node AND category
            node_groups = self._group_by_node_and_category(generated_ui)

            # Render each category
            for category, nodes in sorted(node_groups.items()):
                self._render_category_group(category, nodes)

        return layout

    def _group_by_node_and_category(
        self,
        generated_ui: GeneratedUI
    ) -> Dict[str, List[Tuple[str, str, List[ComponentInfo]]]]:
        """
        Group components by category, then by individual node

        Returns:
            {
              "sampler": [
                ("node_123", "My KSampler", [ComponentInfo, ...]),
                ("node_456", "Another KSampler", [ComponentInfo, ...])
              ],
              "lora_loader": [...]
            }
        """
        category_groups = defaultdict(list)

        # Group by node first
        nodes_by_id = defaultdict(list)
        node_info_map = {}  # node_id -> (category, title)

        for comp_info in generated_ui.components:
            nodes_by_id[comp_info.node_id].append(comp_info)

            # Store category and title
            if comp_info.node_id not in node_info_map:
                # Find the node's category from grouped_components
                for category, comps in generated_ui.grouped_components.items():
                    if comp_info in comps:
                        # Get title from first component
                        title = comp_info.component.label.split(" › ")[0] if comp_info.component.label else comp_info.node_id
                        node_info_map[comp_info.node_id] = (category, title)
                        break

        # Group by category
        for node_id, components in nodes_by_id.items():
            category, title = node_info_map.get(node_id, ("other", node_id))
            category_groups[category].append((node_id, title, components))

        return dict(category_groups)

    def _render_category_group(
        self,
        category: str,
        nodes: List[Tuple[str, str, List[ComponentInfo]]]
    ):
        """
        Render a category group (e.g., all samplers)

        Args:
            category: Category name (sampler, lora_loader, etc.)
            nodes: List of (node_id, title, components) tuples
        """
        # Pretty category names
        category_names = {
            "sampler": "Samplers",
            "lora_loader": "LoRA Loaders",
            "checkpoint_loader": "Checkpoint Loaders",
            "unet_loader": "UNET Loaders",
            "image_input": "Image Inputs",
            "video_input": "Video Inputs",
            "output": "Output Nodes",
            "other": "Other Parameters"
        }

        category_title = category_names.get(category, category.replace("_", " ").title())

        # Create accordion for category
        with gr.Accordion(
            label=f"{category_title} ({len(nodes)})",
            open=not self.ui_config.collapse_by_default
        ):
            # Render each node in this category
            for node_id, node_title, components in nodes:
                self._render_node_components(node_id, node_title, components)

    def _render_node_components(
        self,
        node_id: str,
        node_title: str,
        components: List[ComponentInfo]
    ):
        """
        Render components for a single node

        Args:
            node_id: Node identifier
            node_title: Node display title
            components: List of components for this node
        """
        # If only one component, render inline
        if len(components) == 1:
            comp = components[0].component
            gr.render(comp)
            return

        # Multiple components - group in sub-accordion
        with gr.Accordion(label=node_title, open=True):
            for comp_info in components:
                gr.render(comp_info.component)

    def update_workflow_from_ui(
        self,
        workflow: Dict[str, Any],
        generated_ui: GeneratedUI,
        component_values: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update workflow with values from UI components

        Args:
            workflow: Original workflow JSON
            generated_ui: Generated UI structure
            component_values: Dictionary mapping component to new values

        Returns:
            Updated workflow JSON
        """
        # Clone workflow to avoid mutation
        import copy
        updated_workflow = copy.deepcopy(workflow)

        # Update each component's value in workflow
        for comp_info in generated_ui.components:
            component_id = id(comp_info.component)

            if component_id in component_values:
                new_value = component_values[component_id]

                # Update workflow
                node_id = comp_info.node_id
                input_name = comp_info.input_name

                if node_id in updated_workflow:
                    if "inputs" not in updated_workflow[node_id]:
                        updated_workflow[node_id]["inputs"] = {}

                    updated_workflow[node_id]["inputs"][input_name] = new_value

        return updated_workflow
