"""
ComfyUI_to_webui V2 - Main Gradio Application

This is the entry point for the dynamic Gradio interface.
It demonstrates Phase 1 functionality: dynamic UI generation from workflow JSON.

Phase 1 Features:
- Load workflow JSON (file upload or selector)
- Parse workflow and extract editable inputs
- Dynamically generate Gradio components from /object_info schemas
- Display organized UI grouped by node type

Future Phases:
- Phase 2: Workflow execution and result retrieval
- Phase 3: WebSocket preview, Photopea, monitoring
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
from .utils.workflow_utils import load_workflow_from_file
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
        self.current_workflow: Optional[Dict[str, Any]] = None
        self.current_ui: Optional[GeneratedUI] = None

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

    def generate_ui_from_workflow_path(self, workflow_path: str) -> str:
        """
        Generate UI from workflow file path (used by dropdown)

        Args:
            workflow_path: Full path to workflow JSON file

        Returns:
            Markdown string with workflow info and editable parameters
        """
        if not workflow_path or workflow_path == "None":
            return ""

        try:
            # Load workflow
            self.current_workflow = load_workflow_from_file(workflow_path)

            # Generate UI metadata
            self.current_ui = self.ui_generator.generate_ui_for_workflow(
                self.current_workflow
            )

            # Build markdown representation
            return self._build_workflow_summary_markdown()

        except Exception as e:
            return f"### ❌ Error Loading Workflow\n\n```\n{str(e)}\n```"

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
                # Get node title from first component
                node_title = node_components[0].component.label.split(" › ")[0] if node_components[0].component.label else node_id

                lines.append(f"**{node_title}** (Node ID: `{node_id}`)")

                for comp in node_components:
                    input_name = comp.input_name
                    value = comp.current_value
                    comp_type = type(comp.component).__name__

                    lines.append(f"- **{input_name}**: `{value}` ({comp_type})")

                lines.append("")

        lines.append("\n---\n")
        lines.append("**Note:** Phase 1 demonstrates dynamic UI generation. ")
        lines.append("In Phase 2, these parameters will be editable with actual Gradio components!")

        return "\n".join(lines)

    def generate_ui_from_workflow(self, workflow_file: str) -> str:
        """
        Gradio callback: Generate UI when workflow file is uploaded

        Args:
            workflow_file: File path string (Gradio 4.x type="filepath")

        Returns:
            Markdown string with workflow info
        """
        if not workflow_file:
            return ""

        try:
            # Load workflow (auto-converts from workflow format to API format)
            self.current_workflow = load_workflow_from_file(workflow_file)

            # Generate UI metadata
            self.current_ui = self.ui_generator.generate_ui_for_workflow(
                self.current_workflow
            )

            # Build markdown representation
            return self._build_workflow_summary_markdown()

        except Exception as e:
            return f"### ❌ Error Loading Workflow\n\n```\n{str(e)}\n```"

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
            **Phase 1 MVP:** Dynamic UI Generation

            ---

            ## Instructions
            1. Upload a ComfyUI workflow JSON file (API format)
            2. The UI will dynamically generate input controls based on the workflow
            3. All editable parameters will appear grouped by node type

            **Note:** Phase 1 only demonstrates dynamic UI generation.
            Execution, preview, and other features coming in future phases!
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

            # Dynamic UI container
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 2. Workflow Analysis")

                    # This will be populated dynamically
                    dynamic_ui_container = gr.Markdown(
                        value="",
                        label="Workflow Details"
                    )

            # Info section
            with gr.Row():
                gr.Markdown(f"""
                ---
                ### About This Demo

                This is a **Phase 1 MVP** demonstrating the core innovation of V2:
                **schema-driven dynamic UI generation** that works with ANY workflow.

                **What's Different from V1:**
                - ❌ No hardcoded node types (Hua_Output, GradioTextOk, etc.)
                - ❌ No fixed component pools (MAX_DYNAMIC_COMPONENTS=20)
                - ❌ No custom output nodes required
                - ✅ Works with ANY ComfyUI workflow
                - ✅ Unlimited dynamic components
                - ✅ Auto-detects node types via /object_info API

                **Coming in Future Phases:**
                - Phase 2: Workflow execution, result retrieval
                - Phase 3: WebSocket preview, Photopea, monitoring
                - Phase 4: Component grouping, model scanner
                - Phase 5: Civitai browser, batch processing

                **Development Info:**
                - Branch: `v2-dynamic-rewrite`
                - ComfyUI Server: {COMFYUI_BASE_URL}
                """)

            # Wire up event handlers
            # Dropdown selection
            def on_dropdown_change(workflow_name):
                if workflow_name == "None" or not workflow_name:
                    return ""
                workflow_path = self.available_workflows.get(workflow_name)
                return self.generate_ui_from_workflow_path(workflow_path)

            workflow_dropdown.change(
                fn=on_dropdown_change,
                inputs=[workflow_dropdown],
                outputs=[dynamic_ui_container]
            )

            # File upload
            workflow_file.change(
                fn=self.generate_ui_from_workflow,
                inputs=[workflow_file],
                outputs=[dynamic_ui_container]
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
