# ComfyUI_to_webui V2 (Refactored Architecture)

> **🍴 This is a fork of [kungful/ComfyUI_to_webui](https://github.com/kungful/ComfyUI_to_webui)**
> Original work by **hua (Kungfu)** - Thank you for creating this amazing project!
> This is V2 with a completely refactored architecture for better maintainability and modularity.
> See [CREDITS.md](CREDITS.md) for full attribution.

**📦 V2 Architecture:** This version features a modular design with separate core components (`core/`, `features/`, `ui/`, `utils/`) for easier development and testing. V1 code is preserved in the `v1-archive` branch for reference.

Gradio front-end for pairing with ComfyUI workflows. The plugin exposes workflow inputs/outputs through a Gradio UI, manages queueing, dynamic components, and live previews, and can be run alongside ComfyUI without editing the core server.

## 🎯 What's New in V2
- **Modular Architecture** - Clean separation of concerns with `core/`, `features/`, `ui/`, and `utils/` modules
- **Reduced Dependencies** - Moving away from reliance on custom Hua output nodes
- **Improved Maintainability** - Easier to understand, test, and extend
- **Fixed critical deadlock issues** with Gradio 4.44.0 streaming (from V1 fork improvements)
- **Intelligent queue polling** for workflows without custom output nodes
- **Enhanced Photopea integration** - automatic dimension detection and VRAM overflow prevention
  - Smart dimension priority: UI inputs → workflow settings → default (768x768)
  - Fixed batch_size corruption that caused GPU memory errors
  - Seamless round-trip editing with correct image dimensions
- **Enhanced stability** - no more hanging or crashes
- **Works with standard ComfyUI workflows** - no special nodes required
- **Extensive English documentation** and code comments
- See [PHASE1_COMPLETE.md](PHASE1_COMPLETE.md) and [PHASE3_COMPLETE.md](PHASE3_COMPLETE.md) for development milestones

## Features
- Dynamic creation of input controls for text prompts, LoRA selectors, numeric sliders, and other workflow nodes.
- Queue manager with progress reporting, interrupt, and history handling.
- Optional live sampler preview via websocket (requires `websocket-client`).
- Built-in workflow/model refresh, resolution presets, seed tools, and output gallery/video tabs.
- Inpaint-ready image input with sketch masking plus one-click "send to input" from gallery results.
- **Embedded Photopea editor** for in-browser image editing with automatic dimension preservation
  - Export edited images directly back to workflow at correct resolution
  - Send uploaded images or gallery results to Photopea for quick edits
  - No manual downloads required - seamless round-trip workflow
- Integrated Civitai browser with API-key support for searching and downloading models directly into ComfyUI folders.
- Helper utilities: API JSON manager, log viewer, floating system monitor, and node badge controls.

## Installation
1. Clone into `ComfyUI/custom_nodes`:
   ```bash
   cd /path/to/ComfyUI/custom_nodes
   git clone https://github.com/Gingertrout/ComfyUI_to_webui.git
   ```
2. Install requirements (use the same Python environment that runs ComfyUI):
   ```bash
   /path/to/python -m pip install -r ComfyUI_to_webui/requirements.txt
   ```
3. Launch ComfyUI; the plugin auto-registers and will attempt to install missing dependencies on startup.

## Usage
1. Open the Gradio UI (default `http://127.0.0.1:7861`) launched alongside ComfyUI.
2. Select or refresh workflows from the dropdown. V2 works with standard ComfyUI workflow JSON files.
3. Adjust prompts, resolutions, seeds, models, and other dynamically discovered components, then click **Generate** to enqueue requests.
4. Monitor live progress, view logs, or load existing outputs from the tabs on the right-hand column.
5. Use the **Photopea Editor** (if integrated) to push images to Photopea and pull edits back into the workflow.
6. Browse and download new checkpoints, LoRAs, and embeddings from the **Civitai Browser** tab without leaving the UI.

## V2 Architecture
The codebase is organized into clear modules:
- `core/` - ComfyUI client, execution engine, workflow analyzer, result retriever, UI generator
- `features/` - Optional feature modules
- `ui/` - UI component definitions
- `utils/` - Utility functions and helpers
- `static/` - Static assets (CSS, JS, images)
- `gradio_app.py` - Main Gradio application
- `config.py` - Configuration management

## Contributing
Pull requests that improve reliability, add new localized strings, or modernize the UI code are welcome. Please keep documentation and comments in English and follow the existing formatting conventions.

## Credits & License
This project is a fork maintaining the original MIT License from hua (Kungfu).
See [CREDITS.md](CREDITS.md) for detailed attribution and [LICENSE](LICENSE) for the full license text.

**Original Project:** https://github.com/kungful/ComfyUI_to_webui (Chinese version with different features)

**V1 Archive:** The original V1 codebase (with Hua custom nodes) is preserved in the `v1-archive` branch for reference.

---
**Note:** This is my first open-source project! 🎉 V2 is a work in progress - feedback and contributions welcome!
