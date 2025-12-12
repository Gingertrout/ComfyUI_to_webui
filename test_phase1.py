#!/usr/bin/env python3
"""
Quick test script for Phase 1 MVP

This script launches the Gradio interface to test dynamic UI generation.
"""

import sys
from pathlib import Path

# Add ComfyUI_to_webui_v2 to path
sys.path.insert(0, str(Path(__file__).parent))

from ComfyUI_to_webui_v2.gradio_app import main

if __name__ == "__main__":
    print("Starting Phase 1 MVP test...")
    print("This will open in your browser at http://127.0.0.1:7861")
    print("")
    main()
