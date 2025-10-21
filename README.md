# ComfyUI_to_webui (English Fork)

> **🍴 This is a fork of [kungful/ComfyUI_to_webui](https://github.com/kungful/ComfyUI_to_webui)**
> Original work by **hua (Kungfu)** - Thank you for creating this amazing project!
> This fork includes stability fixes, English translation, and enhanced error handling.
> See [CREDITS.md](CREDITS.md) for full attribution.

Gradio front-end for pairing with ComfyUI workflows. The plugin exposes workflow inputs/outputs through a Gradio UI, manages queueing, dynamic components, and live previews, and can be run alongside ComfyUI without editing the core server.

## 🎯 What's New in This Fork
- **Fixed critical deadlock issues** with Gradio 4.44.0 streaming
- **Intelligent queue polling** for workflows without custom output nodes
- **Enhanced stability** - no more hanging or crashes
- **Works with standard ComfyUI workflows** - no special nodes required
- **Extensive English documentation** and code comments
- See [DEADLOCK_FIX.md](DEADLOCK_FIX.md) for technical details

## Features
- Dynamic creation of input controls for text prompts, LoRA selectors, numeric sliders, and other workflow nodes.
- Queue manager with progress reporting, interrupt, and history handling.
- Optional live sampler preview via websocket (requires `websocket-client`).
- Built-in workflow/model refresh, resolution presets, seed tools, and output gallery/video tabs.
- Inpaint-ready image input with sketch masking plus one-click "send to input" from gallery results.
- Embedded Photopea editor for in-browser round-tripping edits without manual downloads.
- Integrated Civitai browser with API-key support for searching and downloading models directly into ComfyUI folders.
- Helper utilities: API JSON manager, log viewer, floating system monitor, and node badge controls.

## Installation
1. Clone into `ComfyUI/custom_nodes`:
   ```bash
   cd /path/to/ComfyUI/custom_nodes
   git clone https://github.com/kungful/ComfyUI_to_webui.git
   ```
2. Install requirements (use the same Python environment that runs ComfyUI):
   ```bash
   /path/to/python -m pip install -r ComfyUI_to_webui/requirements.txt
   ```
3. Launch ComfyUI; the plugin auto-registers and will attempt to install missing dependencies on startup.

## Usage
1. Open the Gradio UI (default `http://127.0.0.1:7861`) launched alongside ComfyUI.
2. Select or refresh exported workflows (`output/*.json`). They are created automatically after a successful run that includes the provided Hua output nodes.
3. Adjust prompts, resolutions, seeds, models, and other dynamically discovered components, then click **Generate** to enqueue requests.
4. Monitor live progress, view logs, or load existing outputs from the tabs on the right-hand column.
5. Use the **Photopea Editor** accordion on the left to push the current image to Photopea and pull edits back into the workflow.
6. Browse and download new checkpoints, LoRAs, and embeddings from the **Civitai Browser** tab without leaving the UI.

## Sample Workflows
Example workflows demonstrating different configurations live under `Sample_preview`. They showcase:
- Text-to-image and image-to-image flows
- Batch storyboard generation
- ControlNet and video pipelines
- JSON export helpers and barcode utilities

## Contributing
Pull requests that improve reliability, add new localized strings, or modernize the UI code are welcome. Please keep documentation and comments in English and follow the existing formatting conventions.

## Credits & License
This project is a fork maintaining the original MIT License from hua (Kungfu).
See [CREDITS.md](CREDITS.md) for detailed attribution and [LICENSE](LICENSE) for the full license text.

**Original Project:** https://github.com/kungful/ComfyUI_to_webui (Chinese version with different features)

---
**Note:** This is my first open-source project! 🎉 Feedback and contributions welcome!
