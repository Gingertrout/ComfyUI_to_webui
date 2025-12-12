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

    def generate_ui_from_workflow_path(self, workflow_path: str) -> gr.Column:
        """
        Generate UI from workflow file path (used by dropdown)

        Args:
            workflow_path: Full path to workflow JSON file

        Returns:
            Gradio Column with dynamically generated components
        """
        if not workflow_path or workflow_path == "None":
            return gr.Column(visible=False)

        try:
            # Load workflow
            self.current_workflow = load_workflow_from_file(workflow_path)

            # Generate UI
            self.current_ui = self.ui_generator.generate_ui_for_workflow(
                self.current_workflow
            )

            # Build grouped layout
            layout = self.ui_generator.build_grouped_layout(self.current_ui)

            return layout

        except Exception as e:
            with gr.Column() as error_layout:
                gr.Markdown(f"### Error Loading Workflow\n\n```\n{str(e)}\n```")
            return error_layout

    def generate_ui_from_workflow(self, workflow_file) -> gr.Column:
        """
        Gradio callback: Generate UI when workflow file is uploaded

        Args:
            workflow_file: Gradio File component value

        Returns:
            Gradio Column with dynamically generated components
        """
        if workflow_file is None:
            return gr.Column(visible=False)

        try:
            # Load workflow (auto-converts from workflow format to API format)
            self.current_workflow = load_workflow_from_file(workflow_file.name)

            # Generate UI
            self.current_ui = self.ui_generator.generate_ui_for_workflow(
                self.current_workflow
            )

            # Build grouped layout
            layout = self.ui_generator.build_grouped_layout(self.current_ui)

            return layout

        except Exception as e:
            with gr.Column() as error_layout:
                gr.Markdown(f"### Error Loading Workflow\n\n```\n{str(e)}\n```")
            return error_layout

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
                        type="file"  # Gradio 3.x compatibility
                    )

                    gr.Markdown("""
                    **Tip:** Workflows are auto-converted from graph format to API format.
                    Both ComfyUI workflow JSON and API JSON formats are supported.
                    """)

            # Dynamic UI container
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 2. Generated Parameters")

                    # This will be populated dynamically
                    dynamic_ui_container = gr.Column(visible=False)

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
                    return gr.Column(visible=False)
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
