"""
ComfyUI_to_webui V2 - ComfyUI Plugin Registration

This module is loaded by ComfyUI on startup.
For Phase 1, it provides manual launch capability.
Future phases will add auto-launch and custom node registration.
"""

import os
import sys
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
# Custom Node Mappings (Future)
# ============================================================================

# Phase 1: No custom nodes
# Future phases may add custom output nodes if needed

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


# ============================================================================
# Plugin Initialization
# ============================================================================

def initialize_plugin():
    """
    Initialize the plugin

    Phase 1: Just print info message
    Future: Auto-launch Gradio server
    """
    print("\n" + "=" * 70)
    print(f"  {PROJECT_NAME} - {VERSION}")
    print("=" * 70)
    print("  Phase 1 MVP: Dynamic UI Generation")
    print("")
    print("  Status: Loaded successfully!")
    print("")
    print("  To launch the Gradio interface:")
    print("    1. Open a terminal")
    print("    2. Navigate to:", str(PLUGIN_DIR))
    print("    3. Run: python -m ComfyUI_to_webui_v2.gradio_app")
    print("")
    print("  OR run from Python:")
    print("    >>> from ComfyUI_to_webui_v2.gradio_app import main")
    print("    >>> main()")
    print("=" * 70)
    print("")


# ============================================================================
# Manual Launch Function
# ============================================================================

def launch_gradio_interface():
    """
    Manually launch the Gradio interface

    Usage:
        >>> import ComfyUI_to_webui_v2
        >>> ComfyUI_to_webui_v2.launch_gradio_interface()
    """
    from .gradio_app import main
    main()


# ============================================================================
# ComfyUI Plugin Entry Point
# ============================================================================

# Initialize plugin when ComfyUI loads this module
initialize_plugin()


# Export for external use
__all__ = [
    "launch_gradio_interface",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "__version__",
]
