"""
Workflow Analyzer

This module analyzes ComfyUI workflow JSON to:
- Extract node types and their inputs
- Identify editable vs linked inputs
- Detect output nodes for result retrieval
- Classify nodes by category (samplers, loaders, etc.)
"""

from typing import Dict, List, Set, Any, Optional, Tuple
from dataclasses import dataclass, field

from ..config import (
    OUTPUT_NODE_TYPES,
    IMAGE_INPUT_NODE_TYPES,
    VIDEO_INPUT_NODE_TYPES,
    SAMPLER_NODE_TYPES,
    LORA_NODE_TYPES,
    CHECKPOINT_NODE_TYPES,
    UNET_NODE_TYPES,
)


@dataclass
class NodeInput:
    """Represents a single node input"""
    name: str
    value: Any
    is_linked: bool  # True if connected to another node
    linked_from: Optional[Tuple[str, int]] = None  # (source_node_id, output_slot)


@dataclass
class AnalyzedNode:
    """Represents an analyzed workflow node"""
    node_id: str
    class_type: str
    title: str  # From _meta.title or node_id
    inputs: List[NodeInput]
    is_output_node: bool
    category: str = ""  # sampler, lora_loader, checkpoint_loader, etc.


@dataclass
class WorkflowAnalysis:
    """Complete workflow analysis results"""
    nodes: List[AnalyzedNode] = field(default_factory=list)
    editable_nodes: List[AnalyzedNode] = field(default_factory=list)
    output_nodes: List[AnalyzedNode] = field(default_factory=list)
    requires_image_input: bool = False
    requires_video_input: bool = False
    node_types: Set[str] = field(default_factory=set)


class WorkflowAnalyzer:
    """
    Analyzes ComfyUI workflow JSON to extract editable inputs and metadata

    The analyzer distinguishes between:
    - Primitive inputs (can be edited via UI)
    - Linked inputs (connected to other nodes, non-editable)
    """

    def analyze_workflow(self, workflow: Dict[str, Any]) -> WorkflowAnalysis:
        """
        Analyze workflow and return structured analysis

        Args:
            workflow: ComfyUI workflow in API format:
                {
                  "node_id": {
                    "class_type": "KSampler",
                    "inputs": {
                      "seed": 42,
                      "model": ["other_node", 0]  # Linked input
                    },
                    "_meta": {"title": "My Sampler"}
                  }
                }

        Returns:
            WorkflowAnalysis object with categorized nodes and metadata
        """
        analysis = WorkflowAnalysis()

        # Build link map for reference
        link_map = self._build_link_map(workflow)

        # Analyze each node
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue

            class_type = node_data.get("class_type", "")
            if not class_type:
                continue

            # Extract node metadata
            analyzed_node = self._analyze_node(
                node_id,
                node_data,
                link_map
            )

            # Add to results
            analysis.nodes.append(analyzed_node)
            analysis.node_types.add(class_type)

            # Categorize node
            if analyzed_node.is_output_node:
                analysis.output_nodes.append(analyzed_node)

            if any(inp for inp in analyzed_node.inputs if not inp.is_linked):
                analysis.editable_nodes.append(analyzed_node)

            # Check for input requirements
            if class_type in IMAGE_INPUT_NODE_TYPES:
                analysis.requires_image_input = True
            if class_type in VIDEO_INPUT_NODE_TYPES:
                analysis.requires_video_input = True

        return analysis

    def _analyze_node(
        self,
        node_id: str,
        node_data: Dict[str, Any],
        link_map: Dict[str, List[Tuple[str, int]]]
    ) -> AnalyzedNode:
        """
        Analyze a single node

        Args:
            node_id: Node identifier
            node_data: Node configuration
            link_map: Map of node_id -> [(source_node, output_slot)]

        Returns:
            AnalyzedNode object
        """
        class_type = node_data.get("class_type", "")
        meta = node_data.get("_meta", {})
        title = meta.get("title", node_id)

        # Analyze inputs
        inputs = []
        for input_name, input_value in node_data.get("inputs", {}).items():
            is_linked = self._is_linked_input(input_value)
            linked_from = None

            if is_linked:
                # input_value is ["source_node_id", output_slot]
                linked_from = (input_value[0], input_value[1])

            inputs.append(NodeInput(
                name=input_name,
                value=input_value,
                is_linked=is_linked,
                linked_from=linked_from
            ))

        # Determine category
        category = self._categorize_node(class_type)

        return AnalyzedNode(
            node_id=node_id,
            class_type=class_type,
            title=title,
            inputs=inputs,
            is_output_node=class_type in OUTPUT_NODE_TYPES,
            category=category
        )

    def _is_linked_input(self, input_value: Any) -> bool:
        """
        Check if input is linked to another node

        Linked inputs are represented as: ["source_node_id", output_slot]
        Primitive inputs are: int, float, str, bool, etc.

        Args:
            input_value: Input value to check

        Returns:
            True if input is linked to another node
        """
        return (
            isinstance(input_value, list) and
            len(input_value) == 2 and
            isinstance(input_value[0], str)  # Node ID is string
        )

    def _build_link_map(
        self,
        workflow: Dict[str, Any]
    ) -> Dict[str, List[Tuple[str, int]]]:
        """
        Build map of node connections

        Args:
            workflow: Workflow JSON

        Returns:
            Dictionary mapping node_id to list of (source_node_id, output_slot) tuples
        """
        link_map: Dict[str, List[Tuple[str, int]]] = {}

        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue

            for input_name, input_value in node_data.get("inputs", {}).items():
                if self._is_linked_input(input_value):
                    source_node = input_value[0]
                    output_slot = input_value[1]

                    if node_id not in link_map:
                        link_map[node_id] = []
                    link_map[node_id].append((source_node, output_slot))

        return link_map

    def _categorize_node(self, class_type: str) -> str:
        """
        Categorize node by type for UI grouping

        Args:
            class_type: Node class type

        Returns:
            Category string (sampler, lora_loader, etc.)
        """
        if class_type in SAMPLER_NODE_TYPES:
            return "sampler"
        elif class_type in LORA_NODE_TYPES:
            return "lora_loader"
        elif class_type in CHECKPOINT_NODE_TYPES:
            return "checkpoint_loader"
        elif class_type in UNET_NODE_TYPES:
            return "unet_loader"
        elif class_type in OUTPUT_NODE_TYPES:
            return "output"
        elif class_type in IMAGE_INPUT_NODE_TYPES:
            return "image_input"
        elif class_type in VIDEO_INPUT_NODE_TYPES:
            return "video_input"
        else:
            return "other"

    def get_editable_inputs(
        self,
        workflow: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract only editable (non-linked) inputs from workflow

        Args:
            workflow: Workflow JSON

        Returns:
            Dictionary mapping node_id to editable inputs:
            {
              "node_123": {
                "seed": 42,
                "steps": 20
                # (linked inputs excluded)
              }
            }
        """
        editable = {}

        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue

            node_editable = {}
            for input_name, input_value in node_data.get("inputs", {}).items():
                if not self._is_linked_input(input_value):
                    node_editable[input_name] = input_value

            if node_editable:
                editable[node_id] = node_editable

        return editable
