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

    # Note: load_workflow_from_file is now imported from utils.workflow_utils

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

            # Workflow upload
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 1. Upload Workflow")
                    workflow_file = gr.File(
                        label="Workflow JSON (API Format)",
                        file_types=[".json"],
                        type="file"  # Gradio 3.x compatibility
                    )

                    load_btn = gr.Button("Load Workflow", variant="primary")

                    gr.Markdown("""
                    **Tip:** To get API format from ComfyUI:
                    1. Enable Settings → Dev Mode
                    2. Use "Save (API Format)" instead of "Save"
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
            load_btn.click(
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
