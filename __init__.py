"""
ComfyUI_to_webui V2 - ComfyUI Plugin Registration

This module is loaded by ComfyUI on startup and auto-launches the Gradio interface.
"""

import os
import sys
import threading
from pathlib import Path

# Add parent directory to Python path for relative imports
PLUGIN_DIR = Path(__file__).parent
sys.path.insert(0, str(PLUGIN_DIR.parent))

from .config import VERSION, PROJECT_NAME

# ============================================================================
# Plugin Metadata
# ============================================================================

__version__ = VERSION
__author__ = "ComfyUI_to_webui V2 Team"
__description__ = "Dynamic Gradio interface for ComfyUI workflows"


# ============================================================================
# Custom Node Mappings
# ============================================================================

# V2 doesn't require custom Hua nodes - it works with standard ComfyUI workflows
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


# ============================================================================
# Auto-Launch Gradio Interface
# ============================================================================

def auto_launch_gradio():
    """
    Launch Gradio interface in a background thread
    """
    try:
        from .gradio_app import ComfyUIGradioApp

        print("\n" + "=" * 70)
        print(f"  {PROJECT_NAME} - {VERSION}")
        print("=" * 70)
        print("  🚀 Starting Gradio interface...")
        print("=" * 70)
        print("")

        app = ComfyUIGradioApp()
        app.launch(inbrowser=False)  # Don't auto-open browser

    except Exception as e:
        print(f"❌ Failed to launch Gradio interface: {e}")
        print("  You can still launch manually:")
        print(f"    cd {PLUGIN_DIR}")
        print("    python gradio_app.py")


def launch_gradio_interface():
    """
    Manually launch the Gradio interface in a new thread

    Usage:
        >>> import ComfyUI_to_webui
        >>> ComfyUI_to_webui.launch_gradio_interface()
    """
    thread = threading.Thread(target=auto_launch_gradio, daemon=True)
    thread.start()


# ============================================================================
# ComfyUI Plugin Entry Point
# ============================================================================

# Auto-launch Gradio when ComfyUI loads this module
launch_gradio_interface()


# Export for external use
__all__ = [
    "launch_gradio_interface",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "__version__",
]
