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
from .core.execution_engine import ExecutionEngine
from .core.result_retriever import ResultRetriever
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
        self.execution_engine = ExecutionEngine(self.client)
        self.result_retriever = ResultRetriever(self.client)

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
                # Get node title from first component (safely)
                try:
                    label = getattr(node_components[0].component, 'label', None)
                    if label and " › " in str(label):
                        node_title = str(label).split(" › ")[0]
                    else:
                        node_title = node_id
                except:
                    node_title = node_id

                lines.append(f"**{node_title}** (Node ID: `{node_id}`)")

                for comp in node_components:
                    input_name = comp.input_name
                    value = comp.current_value
                    comp_type = type(comp.component).__name__

                    # Format value nicely
                    if isinstance(value, (int, float)):
                        value_str = str(value)
                    elif isinstance(value, str) and len(value) > 50:
                        value_str = value[:50] + "..."
                    else:
                        value_str = str(value)

                    lines.append(f"- **{input_name}**: `{value_str}` ({comp_type})")

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

    def execute_current_workflow(self) -> tuple[str, list]:
        """
        Execute the currently loaded workflow

        Returns:
            Tuple of (status_message, result_images)
        """
        print("[GradioApp] Execute button clicked")

        if not self.current_workflow:
            print("[GradioApp] No workflow loaded!")
            return "❌ No workflow loaded. Please select a workflow first.", []

        try:
            print(f"[GradioApp] Executing workflow with {len(self.current_workflow)} nodes")

            # Execute workflow
            status_msg = "🚀 **Submitting workflow to ComfyUI...**"
            exec_result = self.execution_engine.execute_workflow(
                self.current_workflow,
                self.current_ui
            )

            print(f"[GradioApp] Execution result: success={exec_result.success}, prompt_id={exec_result.prompt_id}")

            if not exec_result.success:
                error_msg = exec_result.error or "Unknown error"
                if exec_result.node_errors:
                    error_details = "\n".join(
                        f"- Node {nid}: {err}"
                        for nid, err in exec_result.node_errors.items()
                    )
                    return f"❌ **Execution Failed**\n\n{error_msg}\n\n**Node Errors:**\n{error_details}", []
                return f"❌ **Execution Failed**\n\n{error_msg}", []

            # Wait for results
            status_msg = f"⏳ **Executing workflow...**\n\nPrompt ID: `{exec_result.prompt_id}`"
            print(f"[GradioApp] Waiting for results...")

            retrieval_result = self.result_retriever.retrieve_results(
                exec_result.prompt_id,
                exec_result.client_id,
                self.current_workflow
            )

            print(f"[GradioApp] Retrieval result: success={retrieval_result.success}")

            if not retrieval_result.success:
                return f"❌ **Result Retrieval Failed**\n\n{retrieval_result.error}", []

            # Success!
            num_images = len(retrieval_result.images)
            num_videos = len(retrieval_result.videos)

            status_msg = f"✅ **Generation Complete!**\n\n"
            status_msg += f"- **Images**: {num_images}\n"
            status_msg += f"- **Videos**: {num_videos}\n"
            status_msg += f"- **Prompt ID**: `{exec_result.prompt_id}`"

            # Return images for gallery
            all_results = retrieval_result.images + retrieval_result.videos

            return status_msg, all_results

        except Exception as e:
            return f"❌ **Unexpected Error**\n\n```\n{str(e)}\n```", []

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
            **Phase 2:** Dynamic UI Generation + Workflow Execution

            ---

            ## Instructions
            1. **Select workflow** from dropdown or upload JSON file
            2. **Review** the detected parameters in the analysis section
            3. **Click Generate** to execute the workflow
            4. **View results** in the gallery below

            **Phase 2 Features:**
            - ✅ Dynamic UI generation (any workflow)
            - ✅ Workflow execution via ComfyUI API
            - ✅ Result retrieval from SaveImage nodes
            - ✅ Image/video gallery display
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

            # Execution section
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 3. Generate")

                    generate_btn = gr.Button(
                        "🚀 Generate",
                        variant="primary",
                        size="lg"
                    )

                    execution_status = gr.Markdown(
                        value="",
                        label="Status"
                    )

            # Results section
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 4. Results")

                    result_gallery = gr.Gallery(
                        label="Generated Images/Videos",
                        show_label=False,
                        columns=3,
                        object_fit="contain",
                        height="auto"
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

            # Generate button
            generate_btn.click(
                fn=self.execute_current_workflow,
                inputs=[],
                outputs=[execution_status, result_gallery]
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
